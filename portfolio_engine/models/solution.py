"""Resultado de una resolución y de la validación independiente de una solución.

``SolveResult`` conserva el estado nativo del solver junto al estado normalizado (MASTER_SPEC
§45, §67); ``ValidationReport`` es el resultado del ``SolutionValidator`` (MASTER_SPEC §44).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import (
    ProblemClass,
    RecoveryOutcome,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.utils.numerics import readonly_float_array


def sum_iterations_by_solver(items: Iterable[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    """Suma ``(solver, iteraciones)`` por solver, ordenado por nombre.

    Las iteraciones de solvers distintos (OSQP: ADMM; HiGHS: símplex/punto interior) no son una
    medida homogénea de esfuerzo: el desglose por solver es la métrica comparable y su suma solo
    una métrica agregada de actividad.
    """
    totals: dict[str, int] = {}
    for name, iterations in items:
        totals[name] = totals.get(name, 0) + iterations
    return tuple(sorted(totals.items()))


#: Estados en los que el solver entrega un vector primal utilizable (pendiente de validación).
USABLE_STATUSES = frozenset({SolverStatus.OPTIMAL, SolverStatus.OPTIMAL_INACCURATE})


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    """Un intento de la recuperación numérica (o el intento original que la activó).

    ``strategy`` es ``ORIGINAL`` (resolución que falló), ``LP_FEASIBILITY_ORACLE`` (comprobación
    independiente de factibilidad) o ``NORMALIZED_RETURN_ROW`` (reintento con la fila de retorno
    centrada y escalada por ``row_scale``). ``rejected_by_validator`` marca un intento ``OPTIMAL``
    del solver cuya solución no supera la validación independiente (no se acepta).
    """

    strategy: str
    solver_name: str
    status: SolverStatus
    native_status: str
    iterations: int
    primal_residual: float | None
    dual_residual: float | None
    row_scale: float | None
    rejected_by_validator: bool = False


@dataclass(frozen=True, slots=True)
class RecoveryTrace:
    """Diagnóstico de la recuperación numérica de un punto (F-3): por qué se activó y qué ocurrió.

    ``trigger_status`` y ``trigger_native_status`` son los del solver inicial; ``feasibility`` es el
    veredicto del LP independiente (``None`` si no se consultó); ``attempts`` conserva todos los
    intentos en orden, el original incluido.
    """

    trigger_status: SolverStatus
    trigger_native_status: str
    feasibility: str | None
    attempts: tuple[RecoveryAttempt, ...]
    outcome: RecoveryOutcome

    @property
    def iterations_by_solver(self) -> tuple[tuple[str, int], ...]:
        """Iteraciones de todos los intentos (original, oráculo y reintentos) por solver.

        Ordenado por nombre de solver; cada intento se cuenta una sola vez.
        """
        return sum_iterations_by_solver((a.solver_name, a.iterations) for a in self.attempts)


@dataclass(frozen=True, eq=False, slots=True)
class SolveResult:
    """Salida normalizada de un backend (MASTER_SPEC §45, §67).

    ``x`` y ``y`` solo se rellenan si ``status`` es ``OPTIMAL`` u ``OPTIMAL_INACCURATE``; en
    cualquier otro estado el iterado del solver no se expone para evitar su uso accidental.
    ``setup_time`` y ``update_time`` son los tiempos pendientes (workspace y actualizaciones)
    atribuidos a esta resolución.

    ``iterations`` es el total de iteraciones de **todos** los solvers que intervinieron en la
    resolución: sin recuperación, las del solver propio; con recuperación numérica (F-3), las del
    intento original, del oráculo de factibilidad de HiGHS y de cada reintento (una sola vez por
    intento). Sumar solvers distintos da una métrica agregada de actividad, no de esfuerzo
    computacional homogéneo: ``iterations_by_solver`` da el desglose.
    """

    status: SolverStatus
    native_status: str
    status_source: StatusSource
    solver_name: str
    solver_version: str
    problem_class: ProblemClass
    x: npt.NDArray[np.float64] | None
    y: npt.NDArray[np.float64] | None
    objective_value: float | None
    iterations: int
    setup_time: float
    update_time: float
    solve_time: float
    primal_residual: float | None
    dual_residual: float | None
    warm_start_used: bool
    cold_retries: int
    recovery: RecoveryTrace | None = None

    def __post_init__(self) -> None:
        usable = self.status in USABLE_STATUSES
        if usable != (self.x is not None):
            raise SolverError("x debe estar presente si y solo si el estado es utilizable.")
        if self.x is not None:
            object.__setattr__(self, "x", readonly_float_array(self.x))
            if not np.all(np.isfinite(self.x)):
                raise SolverError("Un estado utilizable no puede contener valores no finitos.")
        if self.y is not None:
            object.__setattr__(self, "y", readonly_float_array(self.y))

    @property
    def iterations_by_solver(self) -> tuple[tuple[str, int], ...]:
        """Desglose de :attr:`iterations` por solver (suma igual a ``iterations``)."""
        if self.recovery is None:
            return ((self.solver_name, self.iterations),)
        return self.recovery.iterations_by_solver

    @property
    def is_usable(self) -> bool:
        """``True`` si el solver entregó un vector primal finito (pendiente de validar)."""
        return self.x is not None


@dataclass(frozen=True, slots=True)
class Violation:
    """Violación de una restricción detectada por el validador."""

    constraint_id: str
    value: float
    bound: float
    violation: float


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Resultado de la validación independiente de una solución (MASTER_SPEC §44, §63).

    Attributes:
        is_valid: ``True`` si no hay violaciones por encima de las tolerancias.
        max_violation: mayor violación absoluta detectada (0 si no hay).
        violations: violaciones por encima de la tolerancia.
        checks: identificadores de las comprobaciones que se ejecutaron.
    """

    is_valid: bool
    max_violation: float
    violations: tuple[Violation, ...]
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_violation) and self.is_valid:
            raise SolverError("Un informe válido no puede tener una violación no finita.")
        if self.is_valid and self.violations:
            raise SolverError("Un informe válido no puede listar violaciones.")
