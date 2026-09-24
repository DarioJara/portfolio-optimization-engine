"""Routing de problemas a backends y política de estados ambiguos (MASTER_SPEC §46).

Requisitos: SOL-008, SOL-014, OPT-005.

Reglas del Bloque 2 (``FAST_PRODUCTION``)::

    QP con restricciones lineales       →  OSQP
    LP con restricciones lineales       →  HiGHS (SciPy)  (MaximumReturn etapa 1, R2-01)
    SOCP / SDP (cónico)                 →  Clarabel      (Bloque 4: no disponible)
    MIQP / MIQCP / MISOCP               →  solver mixto  (Bloque 4: no disponible, jamás OSQP)
    NLP no convexo                      →  NonConvex     (Bloque 4: no disponible)

Un problema sin backend disponible se **rechaza** con :class:`RoutingError`; nunca se degrada a
un backend incompatible (MASTER_SPEC §79). La verificación cruzada con un segundo solver
(Clarabel) llega en el Bloque 4; en el Bloque 2 la política ``COLD_RETRY`` reintenta desde cero.
"""

from __future__ import annotations

from dataclasses import replace

from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.exceptions import RoutingError
from portfolio_engine.models.enums import CrossCheckPolicy, OptimizationFamily, ProblemClass
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers.base import OptimizationBackend
from portfolio_engine.optimizers.highs_backend import HiGHSLPBackend
from portfolio_engine.optimizers.osqp_backend import OSQPBackend
from portfolio_engine.optimizers.problem import CanonicalProblem
from portfolio_engine.optimizers.status import AMBIGUOUS_STATUSES

_CONIC = frozenset({ProblemClass.SOCP, ProblemClass.SDP})
_MIXED_INTEGER = frozenset({ProblemClass.MIQP, ProblemClass.MIQCP, ProblemClass.MISOCP})


class SolverRouter:
    """Selecciona el backend según la clase del problema y su familia."""

    def __init__(self, config: SolverConfig) -> None:
        self._config = config

    def route(self, problem: CanonicalProblem) -> OptimizationBackend:
        """Backend nuevo (con su propio workspace) para ``problem``, o :class:`RoutingError`."""
        problem_class = problem.problem_class
        if problem_class in _MIXED_INTEGER or problem.family is OptimizationFamily.EXACT_MIP:
            raise RoutingError(
                f"{problem_class} (familia {problem.family}) requiere un solver mixto entero "
                "(Bloque 4); nunca se envía a OSQP."
            )
        if problem_class in _CONIC:
            raise RoutingError(f"{problem_class} requiere Clarabel (Bloque 4): no disponible.")
        if problem_class is ProblemClass.NLP_NONCONVEX:
            raise RoutingError(
                "NLP no convexo requiere NonConvexBackend (Bloque 4): no disponible."
            )
        if problem.family is OptimizationFamily.FAST_PRODUCTION:
            if problem_class is ProblemClass.QP:
                return OSQPBackend(self._config)
            if problem_class is ProblemClass.LP:
                return HiGHSLPBackend(self._config)
        raise RoutingError(f"Sin backend para {problem_class} en la familia {problem.family}.")


def solve_with_policy(backend: OptimizationBackend, policy: CrossCheckPolicy) -> SolveResult:
    """Resuelve y, ante un estado ambiguo, aplica la política configurada (SOL-014).

    ``INFEASIBLE`` y ``UNBOUNDED`` de OSQP son certificados firmes y no se reintentan; los estados
    ``OPTIMAL_INACCURATE``, ``MAX_ITERATIONS``, ``NUMERICAL_ERROR`` y ``UNKNOWN`` con
    ``COLD_RETRY`` se reintentan una vez desde cero. El resultado del reintento (con
    ``StatusSource.CROSS_CHECK``) sustituye al primero; su estado nunca se mejora artificialmente.
    Los tiempos y las iteraciones del resultado devuelto incluyen los del primer intento.
    """
    first = backend.solve()
    if policy is CrossCheckPolicy.COLD_RETRY and first.status in AMBIGUOUS_STATUSES:
        retried = backend.cold_retry()
        return replace(
            retried,
            setup_time=first.setup_time + retried.setup_time,
            update_time=first.update_time + retried.update_time,
            solve_time=first.solve_time + retried.solve_time,
            iterations=first.iterations + retried.iterations,
        )
    return first
