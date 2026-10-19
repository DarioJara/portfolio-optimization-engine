"""Routing de problemas a backends y política de estados ambiguos (MASTER_SPEC §46).

Requisitos: SOL-005, SOL-008, SOL-014, OPT-005, MIP-002, MIP-005, NCV-001, NCV-002.

Reglas (el tipo del problema debe coincidir con su clase: nunca se disfraza un cono de QP)::

    QP con restricciones lineales       →  OSQP
    LP con restricciones lineales       →  HiGHS (SciPy)  (MaximumReturn etapa 1, R2-01)
    SOCP (conos de segundo orden)       →  Clarabel       (ConicProblem)
    SDP                                 →  rechazado (sin cono PSD implementado)
    MIQP / MIQCP / MISOCP               →  SCIP           (MixedIntegerProblem, familia EXACT_MIP)
    NLP no convexo                      →  NonConvexBackend (sin algoritmos por defecto, E-25)

Un problema sin backend disponible se **rechaza** con :class:`RoutingError`; nunca se degrada a
un backend incompatible (MASTER_SPEC §79): un MIQP jamás se envía a OSQP y un cono jamás se ignora.
``EXACT_MIP`` y ``NONCONVEX_RESEARCH`` no pertenecen al bucle interno de producción: con
``inner_loop=True`` se rechazan (MIP-005). La verificación cruzada con un segundo solver
(:func:`cross_check_with_second_solver`) es explícita; la política ``COLD_RETRY`` reintenta desde
cero.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.conic_config import ConicSolverConfig
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.exact_mip_config import ExactMIPConfig
from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.exceptions import RoutingError
from portfolio_engine.models.enums import CrossCheckPolicy, OptimizationFamily, ProblemClass
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers.base import OptimizationBackend
from portfolio_engine.optimizers.clarabel_backend import ClarabelBackend
from portfolio_engine.optimizers.highs_backend import HiGHSLPBackend
from portfolio_engine.optimizers.mixed_integer_backend import MIXED_INTEGER_CLASSES
from portfolio_engine.optimizers.nonconvex_backend import NonConvexAlgorithm, NonConvexBackend
from portfolio_engine.optimizers.osqp_backend import OSQPBackend
from portfolio_engine.optimizers.problem import (
    CanonicalProblem,
    ConicProblem,
    MixedIntegerProblem,
    NonConvexProblem,
)
from portfolio_engine.optimizers.scip_backend import SCIP_AVAILABLE, SCIPBackend
from portfolio_engine.optimizers.status import AMBIGUOUS_STATUSES

_CONIC = frozenset({ProblemClass.SOCP})


class SolverRouter:
    """Selecciona el backend según la clase del problema y su familia.

    ``conic`` (Clarabel), ``exact_mip`` y ``seed`` (SCIP) y ``nonconvex_algorithms`` son opcionales
    para conservar el contrato del Bloque 2; sin ellos los problemas que los necesitan se rechazan
    con un motivo explícito. :meth:`from_engine_config` los toma de la configuración del motor.
    """

    def __init__(
        self,
        config: SolverConfig,
        *,
        conic: ConicSolverConfig | None = None,
        exact_mip: ExactMIPConfig | None = None,
        seed: int = 0,
        nonconvex_algorithms: tuple[NonConvexAlgorithm, ...] = (),
        inner_loop: bool = False,
    ) -> None:
        self._inner_loop = inner_loop
        self._config = config
        self._conic = conic
        self._exact_mip = exact_mip
        self._seed = seed
        self._nonconvex_algorithms = nonconvex_algorithms

    @classmethod
    def from_engine_config(
        cls, config: EngineConfig, nonconvex_algorithms: tuple[NonConvexAlgorithm, ...] = ()
    ) -> SolverRouter:
        """Router con todas las configuraciones de backend de ``config``."""
        return cls(
            config.solver,
            conic=config.conic,
            exact_mip=config.exact_mip,
            seed=config.random_seed,
            nonconvex_algorithms=nonconvex_algorithms,
        )

    def route(self, problem: CanonicalProblem, *, inner_loop: bool = False) -> OptimizationBackend:
        """Backend nuevo (con su propio workspace) para ``problem``, o :class:`RoutingError`.

        ``inner_loop = True`` marca una llamada del bucle interno de producción: ``EXACT_MIP`` y
        ``NONCONVEX_RESEARCH`` se rechazan siempre en él (MIP-005).
        """
        problem_class = problem.problem_class
        mixed = (
            problem_class in MIXED_INTEGER_CLASSES or problem.family is OptimizationFamily.EXACT_MIP
        )
        nonconvex = problem_class is ProblemClass.NLP_NONCONVEX
        if (inner_loop or self._inner_loop) and (mixed or nonconvex):
            raise RoutingError(
                f"{problem_class} (familia {problem.family}) no se ejecuta en el bucle interno de "
                "producción (MIP-005): EXACT_MIP y NONCONVEX_RESEARCH son modos de validación."
            )
        if mixed:
            return self._mixed_integer(problem)
        if nonconvex:
            return self._nonconvex(problem)
        if problem_class in _CONIC or isinstance(problem, ConicProblem):
            return self._conic_backend(problem)
        if problem_class is ProblemClass.SDP:
            raise RoutingError("SDP no está implementado (sin cono PSD): problema rechazado.")
        if problem.family is OptimizationFamily.FAST_PRODUCTION:
            return self._linear(problem)
        raise RoutingError(f"Sin backend para {problem_class} en la familia {problem.family}.")

    def cross_check_backend(self, problem: CanonicalProblem) -> OptimizationBackend:
        """Segundo solver (Clarabel) para verificar un QP/LP/SOCP convexo de forma independiente."""
        if problem.problem_class not in (ProblemClass.QP, ProblemClass.LP, *_CONIC):
            raise RoutingError(f"{problem.problem_class} no admite verificación cruzada convexa.")
        return self._conic_backend(problem, allow_linear=True)

    def _linear(self, problem: CanonicalProblem) -> OptimizationBackend:
        if type(problem) is not CanonicalProblem:
            raise RoutingError(
                f"{type(problem).__name__} no es un problema lineal-cuadrático puro: OSQP/HiGHS "
                "ignorarían su estructura adicional."
            )
        if problem.problem_class is ProblemClass.QP:
            return OSQPBackend(self._config)
        if problem.problem_class is ProblemClass.LP:
            return HiGHSLPBackend(self._config)
        raise RoutingError(
            f"Sin backend para {problem.problem_class} en la familia {problem.family}."
        )

    def _conic_backend(
        self, problem: CanonicalProblem, *, allow_linear: bool = False
    ) -> OptimizationBackend:
        if self._conic is None:
            raise RoutingError("Clarabel requiere ConicSolverConfig: router sin configuración.")
        if problem.problem_class in _CONIC:
            if not isinstance(problem, ConicProblem):
                raise RoutingError("Un problema SOCP debe ser un ConicProblem con sus conos.")
        elif not allow_linear or type(problem) is not CanonicalProblem:
            raise RoutingError(f"{problem.problem_class} no es un problema cónico para Clarabel.")
        return ClarabelBackend(self._config, self._conic)

    def _mixed_integer(self, problem: CanonicalProblem) -> OptimizationBackend:
        if not isinstance(problem, MixedIntegerProblem):
            raise RoutingError(
                f"{problem.problem_class} requiere un MixedIntegerProblem (variables binarias); "
                "nunca se envía a OSQP."
            )
        if self._exact_mip is None:
            raise RoutingError("EXACT_MIP requiere ExactMIPConfig: router sin configuración.")
        if not SCIP_AVAILABLE:
            raise RoutingError(
                "PySCIPOpt no está instalado: no hay solver mixto entero disponible (E-24). "
                "Instale el grupo opcional exact-mip; no se sustituye por otro algoritmo."
            )
        return SCIPBackend(self._exact_mip, self._seed)

    def _nonconvex(self, problem: CanonicalProblem) -> OptimizationBackend:
        if not isinstance(problem, NonConvexProblem):
            raise RoutingError("NLP no convexo requiere un NonConvexProblem.")
        if problem.has_convex_reformulation:
            raise RoutingError(
                "El problema admite una reformulación convexa "
                f"({problem.convex_reformulation}): no se resuelve como no convexo (NCV-002)."
            )
        if not self._nonconvex_algorithms:
            raise RoutingError(
                "No hay algoritmos no convexos registrados (E-25): NONCONVEX_RESEARCH solo "
                "existe como arquitectura."
            )
        return NonConvexBackend(self._nonconvex_algorithms)


@dataclass(frozen=True, eq=False, slots=True)
class CrossCheckReport:
    """Verificación de una solución con un segundo solver de otra familia (SOL-014).

    ``agree`` es ``None`` si alguno de los dos no entrega solución utilizable (no se puede
    comparar); si ambos la entregan, ``True`` cuando la diferencia relativa de objetivo no supera
    ``tolerance``. Un desacuerdo o un estado no óptimo del segundo solver no promueve ni degrada
    en silencio el primer resultado: se informa.
    """

    first: SolveResult
    second: SolveResult
    objective_difference: float | None
    max_abs_solution_difference: float | None
    tolerance: float
    agree: bool | None


def cross_check_with_second_solver(
    problem: CanonicalProblem,
    first: SolveResult,
    router: SolverRouter,
    tolerance: float,
    *,
    q: npt.NDArray[np.float64] | None = None,
    lower: npt.NDArray[np.float64] | None = None,
    upper: npt.NDArray[np.float64] | None = None,
) -> CrossCheckReport:
    """Resuelve ``problem`` con Clarabel y lo compara con ``first`` (p. ej. de OSQP).

    ``q``, ``lower`` y ``upper`` son los datos vigentes de ``first`` si difieren de los del
    problema (un workspace actualizado).
    """
    backend = router.cross_check_backend(problem)
    backend.setup(problem)
    if q is not None or lower is not None or upper is not None:
        backend.update(q=q, lower=lower, upper=upper)
    second = backend.solve()
    if first.x is None or second.x is None:
        return CrossCheckReport(first, second, None, None, tolerance, None)
    first_value = float(first.objective_value or 0.0)
    second_value = float(second.objective_value or 0.0)
    scale = max(abs(first_value), abs(second_value), float(np.finfo(np.float64).tiny))
    difference = abs(first_value - second_value) / scale
    solution_gap = float(np.max(np.abs(first.x - second.x)))
    return CrossCheckReport(
        first, second, difference, solution_gap, tolerance, difference <= tolerance
    )


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
