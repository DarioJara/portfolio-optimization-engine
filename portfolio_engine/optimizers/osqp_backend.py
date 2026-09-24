"""Backend OSQP con API nativa (MASTER_SPEC §46-47; SOL-004, SOL-009, SOL-012).

Sin CVXPY: el problema llega ya en forma canónica. ``setup`` crea el workspace una vez;
``update`` cambia solo ``q``/``lower``/``upper`` (reutilizando ``P``, ``A`` y la factorización) y
el iterado anterior sirve de arranque en caliente. ``cold_retry`` reconstruye un workspace nuevo
con más iteraciones (reintento en frío real, decisión A-33).

Los estados se normalizan con :func:`map_osqp_status` y el texto nativo se conserva. El vector
``x`` solo se expone si el estado es ``OPTIMAL`` u ``OPTIMAL_INACCURATE`` y es finito.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import numpy.typing as npt
import osqp
import scipy.sparse as sparse

from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import ProblemClass, SolverStatus, StatusSource
from portfolio_engine.models.solution import USABLE_STATUSES, SolveResult
from portfolio_engine.optimizers.base import (
    BackendCapabilities,
    OptimizationBackend,
    SetupInfo,
    UpdateInfo,
)
from portfolio_engine.optimizers.problem import CanonicalProblem
from portfolio_engine.optimizers.status import map_osqp_status

SUPPORTED_CLASSES = frozenset({ProblemClass.QP, ProblemClass.LP})


class OSQPBackend(OptimizationBackend):
    """Backend de QP/LP con restricciones lineales basado en OSQP."""

    def __init__(self, config: SolverConfig) -> None:
        self._config = config
        self._problem: CanonicalProblem | None = None
        self._solver: Any = None
        self._q = np.empty(0, dtype=np.float64)
        self._lower = np.empty(0, dtype=np.float64)
        self._upper = np.empty(0, dtype=np.float64)
        self._setup_count = 0
        self._update_count = 0
        self._solve_count = 0
        self._solves_since_setup = 0
        self._explicit_warm_start = False
        self._pending_setup_time = 0.0
        self._pending_update_time = 0.0
        self._updated_fields: list[str] = []

    @property
    def name(self) -> str:
        """Nombre del solver."""
        return "OSQP"

    @property
    def version(self) -> str:
        """Versión de OSQP instalada."""
        return str(osqp.__version__)

    @property
    def capabilities(self) -> BackendCapabilities:
        """Capacidades reales: QP/LP, actualización de vectores, arranque en caliente."""
        return BackendCapabilities(
            supports_qp=True,
            supports_socp=False,
            supports_sdp=False,
            supports_integer=False,
            supports_nonconvex=False,
            supports_vector_update=True,
            supports_matrix_update=False,
            supports_warm_start=True,
            supports_factorization_reuse=True,
        )

    @property
    def setup_count(self) -> int:
        """Workspaces creados (sin contar los reintentos en frío)."""
        return self._setup_count

    @property
    def update_count(self) -> int:
        """Actualizaciones de vectores realizadas."""
        return self._update_count

    @property
    def solve_count(self) -> int:
        """Resoluciones realizadas (sin contar los reintentos en frío)."""
        return self._solve_count

    @property
    def updated_fields(self) -> tuple[str, ...]:
        """Campos actualizados, en orden (``q``, ``lower``, ``upper``)."""
        return tuple(self._updated_fields)

    def supports(self, problem_class: ProblemClass) -> bool:
        """OSQP resuelve QP y LP (``P = 0``) con restricciones lineales."""
        return problem_class in SUPPORTED_CLASSES

    def setup(self, problem: CanonicalProblem) -> SetupInfo:
        """Crea el workspace de OSQP para ``problem``."""
        if not self.supports(problem.problem_class):
            raise SolverError(f"OSQP no resuelve problemas {problem.problem_class}.")
        started = time.perf_counter()
        self._solver = self._new_solver(
            problem, problem.q, problem.lower, problem.upper, self._config.max_iterations
        )
        elapsed = time.perf_counter() - started
        self._problem = problem
        self._q = np.array(problem.q, dtype=np.float64)
        self._lower = np.array(problem.lower, dtype=np.float64)
        self._upper = np.array(problem.upper, dtype=np.float64)
        self._setup_count += 1
        self._solves_since_setup = 0
        self._explicit_warm_start = False
        self._pending_setup_time += elapsed
        return SetupInfo(elapsed, problem.n_variables, problem.n_constraints)

    def update(
        self,
        *,
        q: npt.NDArray[np.float64] | None = None,
        lower: npt.NDArray[np.float64] | None = None,
        upper: npt.NDArray[np.float64] | None = None,
    ) -> UpdateInfo:
        """Actualiza ``q``, ``lower`` y/o ``upper``; valida antes de tocar el workspace."""
        problem = self._require_problem()
        new_q = self._checked(q, problem.n_variables, "q", allow_inf=False)
        new_lower = self._checked(lower, problem.n_constraints, "lower", allow_inf=True)
        new_upper = self._checked(upper, problem.n_constraints, "upper", allow_inf=True)
        merged_lower = self._lower if new_lower is None else new_lower
        merged_upper = self._upper if new_upper is None else new_upper
        if np.any(merged_lower > merged_upper):
            raise SolverError("Actualización inválida: lower > upper.")
        kwargs: dict[str, npt.NDArray[np.float64]] = {}
        for label, value in (("q", new_q), ("l", new_lower), ("u", new_upper)):
            if value is not None:
                kwargs[label] = value
        started = time.perf_counter()
        if kwargs:
            self._solver.update(**kwargs)
        elapsed = time.perf_counter() - started
        if new_q is not None:
            self._q = new_q
            self._updated_fields.append("q")
        if new_lower is not None:
            self._lower = new_lower
            self._updated_fields.append("lower")
        if new_upper is not None:
            self._upper = new_upper
            self._updated_fields.append("upper")
        self._update_count += 1
        self._pending_update_time += elapsed
        return UpdateInfo(elapsed)

    def warm_start(
        self,
        x: npt.NDArray[np.float64] | None = None,
        y: npt.NDArray[np.float64] | None = None,
    ) -> None:
        """Inicializa el siguiente ``solve`` con ``x`` (primal) y/o ``y`` (dual)."""
        problem = self._require_problem()
        primal = self._checked(x, problem.n_variables, "x", allow_inf=False)
        dual = self._checked(y, problem.n_constraints, "y", allow_inf=False)
        self._solver.warm_start(x=primal, y=dual)
        self._explicit_warm_start = True

    def solve(self) -> SolveResult:
        """Resuelve con los datos actuales del workspace."""
        problem = self._require_problem()
        if not self._config.warm_start and self._solves_since_setup > 0:
            self._solver.warm_start(
                x=np.zeros(problem.n_variables), y=np.zeros(problem.n_constraints)
            )
        warm = self._explicit_warm_start or (
            self._config.warm_start and self._solves_since_setup > 0
        )
        raw = self._solver.solve(raise_error=False)
        result = self._normalize(
            raw,
            warm_started=warm,
            setup_time=self._pending_setup_time,
            update_time=self._pending_update_time,
            cold_retries=0,
        )
        self._pending_setup_time = 0.0
        self._pending_update_time = 0.0
        self._explicit_warm_start = False
        self._solve_count += 1
        self._solves_since_setup += 1
        return result

    def cold_retry(self) -> SolveResult:
        """Reintento en frío: workspace nuevo con los datos actuales y más iteraciones."""
        problem = self._require_problem()
        iterations = self._config.max_iterations * self._config.retry_iteration_multiplier
        started = time.perf_counter()
        retry_solver = self._new_solver(problem, self._q, self._lower, self._upper, iterations)
        setup_time = time.perf_counter() - started
        raw = retry_solver.solve(raise_error=False)
        result = self._normalize(
            raw,
            warm_started=False,
            setup_time=setup_time,
            update_time=0.0,
            cold_retries=1,
            source=StatusSource.CROSS_CHECK,
        )
        if result.is_usable and result.x is not None:
            self._solver.warm_start(x=np.array(result.x), y=np.array(raw.y))
        return result

    def _new_solver(
        self,
        problem: CanonicalProblem,
        q: npt.NDArray[np.float64],
        lower: npt.NDArray[np.float64],
        upper: npt.NDArray[np.float64],
        max_iterations: int,
    ) -> Any:
        settings: dict[str, Any] = {
            "verbose": False,
            "eps_abs": self._config.eps_abs,
            "eps_rel": self._config.eps_rel,
            "max_iter": max_iterations,
            "polishing": self._config.polish,
            "adaptive_rho": True,
            "adaptive_rho_interval": self._config.adaptive_rho_interval,
        }
        if self._config.time_limit_seconds is not None:
            settings["time_limit"] = self._config.time_limit_seconds
        solver = osqp.OSQP()
        solver.setup(
            sparse.csc_matrix(problem.P),
            q,
            sparse.csc_matrix(problem.A),
            lower,
            upper,
            **settings,
        )
        return solver

    def _normalize(
        self,
        raw: Any,
        *,
        warm_started: bool,
        setup_time: float,
        update_time: float,
        cold_retries: int,
        source: StatusSource = StatusSource.SOLVER,
    ) -> SolveResult:
        problem = self._require_problem()
        info = raw.info
        native = str(info.status)
        status = map_osqp_status(native)
        x = np.array(raw.x, dtype=np.float64) if raw.x is not None else None
        if status in USABLE_STATUSES and (x is None or not np.all(np.isfinite(x))):
            status, x = SolverStatus.NUMERICAL_ERROR, None
        if status not in USABLE_STATUSES:
            x = None
        y = np.array(raw.y, dtype=np.float64) if x is not None and raw.y is not None else None
        return SolveResult(
            status=status,
            native_status=native,
            status_source=source,
            solver_name=self.name,
            solver_version=self.version,
            problem_class=problem.problem_class,
            x=x,
            y=y,
            objective_value=_finite_or_none(info.obj_val) if x is not None else None,
            iterations=int(info.iter),
            setup_time=setup_time,
            update_time=update_time,
            solve_time=float(info.solve_time),
            primal_residual=_finite_or_none(info.prim_res),
            dual_residual=_finite_or_none(info.dual_res),
            warm_start_used=warm_started,
            cold_retries=cold_retries,
        )

    def _require_problem(self) -> CanonicalProblem:
        if self._problem is None or self._solver is None:
            raise SolverError("El workspace no está creado: llame a setup() primero.")
        return self._problem

    @staticmethod
    def _checked(
        values: npt.NDArray[np.float64] | None, size: int, label: str, *, allow_inf: bool
    ) -> npt.NDArray[np.float64] | None:
        if values is None:
            return None
        array = np.array(values, dtype=np.float64)
        if array.shape != (size,):
            raise SolverError(f"{label}: dimensión {array.shape} distinta de ({size},).")
        invalid = np.isnan(array) if allow_inf else ~np.isfinite(array)
        if np.any(invalid):
            raise SolverError(f"{label} contiene valores no válidos (NaN o infinitos).")
        return array


def _finite_or_none(value: object) -> float | None:
    number = float(value)  # type: ignore[arg-type]
    return number if np.isfinite(number) else None
