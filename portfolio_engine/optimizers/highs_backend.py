"""Backend LP con HiGHS a través de SciPy (MASTER_SPEC §46; SOL-004, OPT-007, remediación R2-01).

Resuelve el LP de retorno máximo (``P = 0``) de la etapa 1 de MaximumReturn. OSQP sigue siendo el
backend de los QP: un LP degenerado con ``P = 0`` no converge de forma fiable con un método de
primer orden (AUDIT_BLOCK_2, H-1), mientras que un simplex/punto interior sí lo hace.

El problema llega en la forma canónica ``lower <= A x <= upper`` con variables libres; aquí se
traduce a ``linprog``: filas con ``lower == upper`` → igualdades; cotas finitas → desigualdades
``A x <= upper`` y ``−A x <= −lower``; las cotas de variable ya son filas de ``A``. Se conserva el
estado nativo de HiGHS. ``SolveResult.y`` contiene los multiplicadores por fila de la forma
canónica con la convención ``y_i > 0``: cota superior (o igualdad) activa, ``y_i < 0``: cota
inferior activa, ``|y_i|`` = magnitud del multiplicador de HiGHS; permiten identificar la cara
óptima del LP (complementariedad) en la etapa 2 de MaximumReturn.

No admite arranque en caliente (``linprog`` no lo expone): ``warm_start`` lanza
:class:`SolverError` en lugar de ignorarse en silencio.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import scipy
import scipy.sparse as sparse
from scipy.optimize import linprog

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
from portfolio_engine.optimizers.status import map_highs_status

#: Algoritmo de la resolución normal (HiGHS elige) y del reintento (simplex dual, distinto).
PRIMARY_METHOD = "highs"
RETRY_METHOD = "highs-ds"


class HiGHSLPBackend(OptimizationBackend):
    """Backend de LP con restricciones lineales basado en HiGHS (``scipy.optimize.linprog``)."""

    def __init__(self, config: SolverConfig) -> None:
        self._config = config
        self._problem: CanonicalProblem | None = None
        self._matrix: Any = None
        self._q = np.empty(0, dtype=np.float64)
        self._lower = np.empty(0, dtype=np.float64)
        self._upper = np.empty(0, dtype=np.float64)
        self._setup_count = 0
        self._update_count = 0
        self._solve_count = 0
        self._pending_setup_time = 0.0
        self._pending_update_time = 0.0
        self._updated_fields: list[str] = []

    @property
    def name(self) -> str:
        """Nombre del solver."""
        return "HiGHS"

    @property
    def version(self) -> str:
        """HiGHS se distribuye con SciPy: se informa la versión de SciPy que lo empaqueta."""
        return f"scipy-{scipy.__version__}"

    @property
    def capabilities(self) -> BackendCapabilities:
        """Capacidades reales: solo LP, sin arranque en caliente ni factorización reutilizable."""
        return BackendCapabilities(
            supports_qp=False,
            supports_socp=False,
            supports_sdp=False,
            supports_integer=False,
            supports_nonconvex=False,
            supports_vector_update=True,
            supports_matrix_update=False,
            supports_warm_start=False,
            supports_factorization_reuse=False,
        )

    @property
    def setup_count(self) -> int:
        """Problemas registrados con ``setup``."""
        return self._setup_count

    @property
    def update_count(self) -> int:
        """Actualizaciones de vectores realizadas."""
        return self._update_count

    @property
    def solve_count(self) -> int:
        """Resoluciones realizadas (sin contar los reintentos)."""
        return self._solve_count

    @property
    def updated_fields(self) -> tuple[str, ...]:
        """Campos actualizados, en orden (``q``, ``lower``, ``upper``)."""
        return tuple(self._updated_fields)

    def supports(self, problem_class: ProblemClass) -> bool:
        """HiGHS (vía ``linprog``) resuelve LP; los QP van a OSQP."""
        return problem_class is ProblemClass.LP

    def setup(self, problem: CanonicalProblem) -> SetupInfo:
        """Registra el LP (``P`` debe ser nula)."""
        if not self.supports(problem.problem_class) or problem.P.nnz:
            raise SolverError(f"HiGHS solo resuelve LP (P = 0), no {problem.problem_class}.")
        started = time.perf_counter()
        self._matrix = sparse.csr_matrix(problem.A)
        self._problem = problem
        self._q = np.array(problem.q, dtype=np.float64)
        self._lower = np.array(problem.lower, dtype=np.float64)
        self._upper = np.array(problem.upper, dtype=np.float64)
        elapsed = time.perf_counter() - started
        self._setup_count += 1
        self._pending_setup_time += elapsed
        return SetupInfo(elapsed, problem.n_variables, problem.n_constraints)

    def update(
        self,
        *,
        q: npt.NDArray[np.float64] | None = None,
        lower: npt.NDArray[np.float64] | None = None,
        upper: npt.NDArray[np.float64] | None = None,
    ) -> UpdateInfo:
        """Actualiza ``q``, ``lower`` y/o ``upper``; valida antes de modificar el estado."""
        problem = self._require_problem()
        new_q = _checked(q, problem.n_variables, "q", allow_inf=False)
        new_lower = _checked(lower, problem.n_constraints, "lower", allow_inf=True)
        new_upper = _checked(upper, problem.n_constraints, "upper", allow_inf=True)
        merged_lower = self._lower if new_lower is None else new_lower
        merged_upper = self._upper if new_upper is None else new_upper
        if np.any(merged_lower > merged_upper):
            raise SolverError("Actualización inválida: lower > upper.")
        started = time.perf_counter()
        if new_q is not None:
            self._q = new_q
            self._updated_fields.append("q")
        if new_lower is not None:
            self._lower = new_lower
            self._updated_fields.append("lower")
        if new_upper is not None:
            self._upper = new_upper
            self._updated_fields.append("upper")
        elapsed = time.perf_counter() - started
        self._update_count += 1
        self._pending_update_time += elapsed
        return UpdateInfo(elapsed)

    def warm_start(
        self,
        x: npt.NDArray[np.float64] | None = None,
        y: npt.NDArray[np.float64] | None = None,
    ) -> None:
        """No soportado: ``linprog`` no expone el arranque en caliente de HiGHS."""
        raise SolverError("El backend HiGHS (linprog) no admite arranque en caliente.")

    def solve(self) -> SolveResult:
        """Resuelve con el algoritmo por defecto de HiGHS."""
        result = self._run(
            PRIMARY_METHOD,
            self._config.lp_max_iterations,
            StatusSource.SOLVER,
            0,
            self._pending_setup_time,
            self._pending_update_time,
        )
        self._pending_setup_time = 0.0
        self._pending_update_time = 0.0
        self._solve_count += 1
        return result

    def cold_retry(self) -> SolveResult:
        """Reintento con otro algoritmo (simplex dual) y más iteraciones (``CROSS_CHECK``)."""
        iterations = self._config.lp_max_iterations * self._config.retry_iteration_multiplier
        return self._run(RETRY_METHOD, iterations, StatusSource.CROSS_CHECK, 1, 0.0, 0.0)

    # -------------------------------------------------------------------------------- internos

    def _run(
        self,
        method: str,
        max_iterations: int,
        source: StatusSource,
        cold_retries: int,
        setup_time: float,
        update_time: float,
    ) -> SolveResult:
        problem = self._require_problem()
        ineq_matrix, ineq_bound, eq_matrix, eq_bound, rows = self._assemble()
        options: dict[str, Any] = {
            "primal_feasibility_tolerance": self._config.lp_feasibility_tolerance,
            "dual_feasibility_tolerance": self._config.lp_feasibility_tolerance,
            "maxiter": max_iterations,
        }
        if self._config.time_limit_seconds is not None:
            options["time_limit"] = self._config.time_limit_seconds
        started = time.perf_counter()
        raw = linprog(
            self._q,
            A_ub=ineq_matrix,
            b_ub=ineq_bound,
            A_eq=eq_matrix,
            b_eq=eq_bound,
            bounds=(None, None),
            method=method,
            options=options,
        )
        solve_time = time.perf_counter() - started
        native = f"{raw.status}: {str(raw.message).strip()}"
        status = map_highs_status(int(raw.status), str(raw.message))
        x = None if raw.x is None else np.array(raw.x, dtype=np.float64)
        if status in USABLE_STATUSES and (x is None or not np.all(np.isfinite(x))):
            status, x = SolverStatus.NUMERICAL_ERROR, None
        if status not in USABLE_STATUSES:
            x = None
        return SolveResult(
            status=status,
            native_status=native,
            status_source=source,
            solver_name=self.name,
            solver_version=self.version,
            problem_class=problem.problem_class,
            x=x,
            y=None if x is None else _row_multipliers(raw, rows, problem.n_constraints),
            objective_value=None if x is None else float(self._q @ x),
            iterations=int(getattr(raw, "nit", 0) or 0),
            setup_time=setup_time,
            update_time=update_time,
            solve_time=solve_time,
            primal_residual=None if x is None else self._primal_residual(x),
            dual_residual=None,
            warm_start_used=False,
            cold_retries=cold_retries,
        )

    def _assemble(
        self,
    ) -> tuple[Any, npt.NDArray[np.float64] | None, Any, npt.NDArray[np.float64] | None, _RowSplit]:
        """Igualdades y desigualdades de ``linprog`` desde ``lower <= A x <= upper``."""
        lower, upper, matrix = self._lower, self._upper, self._matrix
        finite_lower, finite_upper = np.isfinite(lower), np.isfinite(upper)
        equality = finite_lower & finite_upper & (lower == upper)
        above = finite_upper & ~equality
        below = finite_lower & ~equality
        eq_matrix = matrix[equality] if equality.any() else None
        eq_bound = upper[equality] if equality.any() else None
        if above.any() or below.any():
            ineq_matrix = sparse.vstack([matrix[above], -matrix[below]], format="csr")
            ineq_bound = np.concatenate([upper[above], -lower[below]])
        else:
            ineq_matrix, ineq_bound = None, None
        return ineq_matrix, ineq_bound, eq_matrix, eq_bound, _RowSplit(equality, above, below)

    def _primal_residual(self, x: npt.NDArray[np.float64]) -> float:
        """Mayor violación de ``lower <= A x <= upper`` de la solución."""
        product = np.asarray(self._matrix @ x, dtype=np.float64)
        excess = np.maximum(self._lower - product, product - self._upper)
        return float(max(excess.max(initial=0.0), 0.0))

    def _require_problem(self) -> CanonicalProblem:
        if self._problem is None:
            raise SolverError("El problema no está registrado: llame a setup() primero.")
        return self._problem


@dataclass(frozen=True, eq=False, slots=True)
class _RowSplit:
    """Filas canónicas que van a igualdades, a ``A x <= upper`` y a ``−A x <= −lower``."""

    equality: npt.NDArray[np.bool_]
    above: npt.NDArray[np.bool_]
    below: npt.NDArray[np.bool_]


def _row_multipliers(raw: Any, rows: _RowSplit, size: int) -> npt.NDArray[np.float64] | None:
    """Multiplicadores por fila canónica (``None`` si HiGHS no los devolvió)."""
    inequality = getattr(raw, "ineqlin", None)
    equality = getattr(raw, "eqlin", None)
    n_above, n_below = int(rows.above.sum()), int(rows.below.sum())
    duals = np.zeros(size, dtype=np.float64)
    if rows.equality.any():
        if equality is None:
            return None
        duals[rows.equality] = np.abs(np.asarray(equality.marginals, dtype=np.float64))
    if n_above or n_below:
        if inequality is None:
            return None
        marginals = np.abs(np.asarray(inequality.marginals, dtype=np.float64))
        duals[rows.above] += marginals[:n_above]
        duals[rows.below] -= marginals[n_above:]
    return duals if np.all(np.isfinite(duals)) else None


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
