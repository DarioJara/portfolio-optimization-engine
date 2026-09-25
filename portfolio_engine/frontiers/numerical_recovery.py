"""Recuperación numérica de puntos de retorno objetivo que el solver no resuelve (F-3).

Cuando OSQP no devuelve ``OPTIMAL`` en un punto con retorno objetivo (``INFEASIBLE``,
``NUMERICAL_ERROR``, ``MAX_ITERATIONS``, ``OPTIMAL_INACCURATE``, ``UNKNOWN``) se aplica, una sola
vez por punto y de forma determinista::

    1. (solo INFEASIBLE / NUMERICAL_ERROR / UNKNOWN) LP de factibilidad de HiGHS con las mismas
       filas. Si es INFEASIBLE el punto es verdaderamente infactible: no se reintenta nada y el
       estado del solver queda confirmado.
    2. Escalera de reintentos: workspace nuevo con la fila de retorno centrada y escalada
       (``NormalizedReturnProblem``), una resolución por escala de
       ``SolverConfig.recovery_row_scales`` con el presupuesto de iteraciones del reintento en
       frío (``max_iterations × retry_iteration_multiplier``), hasta obtener ``OPTIMAL``.

Reglas:

* Solo un ``OPTIMAL`` de un reintento que además supera el ``SolutionValidator`` (retorno objetivo
  original, sin modificar) sustituye al resultado original; ``OPTIMAL_INACCURATE`` no se promueve
  nunca. Un ``OPTIMAL`` rechazado por el validador se registra y se pasa a la siguiente escala.
* Si nada recupera el punto y el solver inicial había declarado ``INFEASIBLE`` mientras el LP
  independiente lo halla factible, el estado se reclasifica a ``NUMERICAL_ERROR`` (un fallo
  numérico jamás se presenta como inviabilidad matemática); en otro caso se conserva el estado
  original.
* El resultado conserva los diagnósticos de todos los intentos (:class:`RecoveryTrace`) y suma
  iteraciones y tiempos. ``SolveResult.iterations`` es el total de todos los intentos, oráculo de
  HiGHS incluido (mismo criterio que ``solve_time``); ``SolveResult.iterations_by_solver`` lo
  desglosa por solver.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.models.enums import RecoveryOutcome, SolverStatus, StatusSource
from portfolio_engine.models.solution import RecoveryAttempt, RecoveryTrace, SolveResult
from portfolio_engine.optimizers.base import OptimizationBackend
from portfolio_engine.optimizers.feasibility_oracle import FeasibilityVerdict, lp_feasibility
from portfolio_engine.optimizers.formulations.qp_builder import BuiltProblem
from portfolio_engine.optimizers.router import SolverRouter
from portfolio_engine.optimizers.status import AMBIGUOUS_STATUSES

STRATEGY_ORIGINAL = "ORIGINAL"
STRATEGY_ORACLE = "LP_FEASIBILITY_ORACLE"
STRATEGY_NORMALIZED = "NORMALIZED_RETURN_ROW"

#: Estados que activan la recuperación (los ambiguos del router más el certificado de OSQP).
RECOVERABLE_STATUSES = AMBIGUOUS_STATUSES | {SolverStatus.INFEASIBLE}
#: Estados en los que se consulta al LP independiente antes de reintentar.
ORACLE_STATUSES = frozenset(
    {SolverStatus.INFEASIBLE, SolverStatus.NUMERICAL_ERROR, SolverStatus.UNKNOWN}
)


#: Decide si la solución de un reintento supera la validación independiente (retorno objetivo
#: original incluido).
Acceptor = Callable[[SolveResult], bool]


def _attempt(
    strategy: str,
    result: SolveResult,
    row_scale: float | None = None,
    *,
    rejected: bool = False,
) -> RecoveryAttempt:
    return RecoveryAttempt(
        strategy,
        result.solver_name,
        result.status,
        result.native_status,
        result.iterations,
        result.primal_residual,
        result.dual_residual,
        row_scale,
        rejected,
    )


class NumericalRecovery:
    """Recuperación numérica de un punto de retorno objetivo (F-3)."""

    def __init__(self, config: SolverConfig) -> None:
        self._config = config
        # cada reintento dispone del presupuesto de iteraciones del reintento en frío
        extended = dataclasses.replace(
            config, max_iterations=config.max_iterations * config.retry_iteration_multiplier
        )
        self._router = SolverRouter(extended)

    def applies(
        self, built: BuiltProblem, lower: npt.NDArray[np.float64], result: SolveResult
    ) -> bool:
        """``True`` si el punto tiene retorno objetivo activo y un estado recuperable."""
        return (
            self._config.numerical_recovery
            and math.isfinite(float(lower[built.return_row]))
            and result.status in RECOVERABLE_STATUSES
        )

    def recover(
        self,
        built: BuiltProblem,
        q: npt.NDArray[np.float64],
        lower: npt.NDArray[np.float64],
        first: SolveResult,
        backends: list[OptimizationBackend],
        accept: Acceptor,
    ) -> SolveResult:
        """Resultado tras la recuperación; ``backends`` recibe los workspaces creados.

        Un reintento solo se acepta si es ``OPTIMAL`` **y** ``accept`` (el validador independiente
        con el retorno objetivo original) lo aprueba; si no, se prueba la siguiente escala.
        """
        attempts = [_attempt(STRATEGY_ORIGINAL, first)]
        extra_setup = extra_solve = 0.0
        verdict: FeasibilityVerdict | None = None
        if first.status in ORACLE_STATUSES:
            verdict, oracle = lp_feasibility(built.problem, lower, self._config)
            attempts.append(_attempt(STRATEGY_ORACLE, oracle))
            extra_setup, extra_solve = oracle.setup_time, oracle.solve_time
            if verdict is FeasibilityVerdict.INFEASIBLE:
                trace = self._trace(first, verdict, attempts, RecoveryOutcome.CONFIRMED_INFEASIBLE)
                return self._merge(first, first, attempts, trace, extra_setup, extra_solve)
        winner = None
        for weight_scale in self._config.recovery_row_scales:
            normalized = built.normalize_return_row(weight_scale)
            if normalized is None:
                break
            problem = dataclasses.replace(
                normalized.problem, q=q, lower=normalized.lower_for(lower)
            )
            backend = self._router.route(problem)
            backends.append(backend)
            backend.setup(problem)
            retried = backend.solve()
            optimal = retried.status is SolverStatus.OPTIMAL
            rejected = optimal and not accept(retried)
            attempts.append(
                _attempt(STRATEGY_NORMALIZED, retried, normalized.row_scale, rejected=rejected)
            )
            extra_setup += retried.setup_time
            extra_solve += retried.solve_time
            if optimal and not rejected:
                winner = retried
                break
        if winner is not None:
            trace = self._trace(first, verdict, attempts, RecoveryOutcome.RECOVERED)
            return self._merge(first, winner, attempts, trace, extra_setup, extra_solve)
        trace = self._trace(first, verdict, attempts, RecoveryOutcome.NOT_RECOVERED)
        base = first
        if first.status is SolverStatus.INFEASIBLE and verdict is FeasibilityVerdict.FEASIBLE:
            base = dataclasses.replace(first, status=SolverStatus.NUMERICAL_ERROR)
        return self._merge(first, base, attempts, trace, extra_setup, extra_solve)

    @staticmethod
    def _trace(
        first: SolveResult,
        verdict: FeasibilityVerdict | None,
        attempts: list[RecoveryAttempt],
        outcome: RecoveryOutcome,
    ) -> RecoveryTrace:
        return RecoveryTrace(
            first.status,
            first.native_status,
            None if verdict is None else verdict.value,
            tuple(attempts),
            outcome,
        )

    @staticmethod
    def _merge(
        first: SolveResult,
        chosen: SolveResult,
        attempts: list[RecoveryAttempt],
        trace: RecoveryTrace,
        extra_setup: float,
        extra_solve: float,
    ) -> SolveResult:
        """``chosen`` con la traza y con iteraciones y tiempos de todos los intentos sumados.

        Los multiplicadores ``y`` de un reintento pertenecen a la fila normalizada, no al problema
        original, y no se exponen. La fuente del estado solo pasa a ``CROSS_CHECK`` si el estado
        deja de ser el del solver inicial (recuperación o reclasificación).
        """
        from_retry = trace.outcome is RecoveryOutcome.RECOVERED
        return dataclasses.replace(
            chosen,
            y=None if from_retry else chosen.y,
            status_source=first.status_source if chosen is first else StatusSource.CROSS_CHECK,
            warm_start_used=first.warm_start_used,
            cold_retries=first.cold_retries,
            iterations=sum(item.iterations for item in attempts),
            setup_time=first.setup_time + extra_setup,
            update_time=first.update_time,
            solve_time=first.solve_time + extra_solve,
            recovery=trace,
        )
