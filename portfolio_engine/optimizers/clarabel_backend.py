"""Backend cónico con Clarabel (MASTER_SPEC §46, §48; SOL-005, decisiones A-32, A-37).

Clarabel resuelve ``min ½xᵀPx + qᵀx`` sujeto a ``A x + s = b`` con ``s`` en un producto de conos
(cero, ortante no negativo y segundo orden). El problema llega en la forma del motor,
``lower <= A x <= upper`` más conos ``‖Fx + g‖ <= aᵀx + c``, y aquí se traduce **sin aproximar
nada**:

* filas con ``lower == upper`` → cono cero (``A_i x = b_i``);
* cota superior finita → ``A_i x + s = upper_i``, ``s >= 0``;
* cota inferior finita → ``−A_i x + s = −lower_i``, ``s >= 0``;
* cada cono de segundo orden → ``−[aᵀ; F] x + s = [c; g]``, ``s ∈ SOC``.

Backend de primera clase del ``SolverRouter``: resuelve SOCP (volatilidad, Max Sharpe, peor caso,
robustez) y también QP/LP con restricciones lineales (verificación cruzada de OSQP, política
``SECOND_SOLVER``). ``update`` solo modifica ``q`` y ``b`` (``lower``/``upper``) sobre un
workspace vivo si la estructura de filas finitas no cambia; si cambia, reconstruye el problema y lo
registra como ``setup``. Clarabel es un método de punto interior: no admite arranque en caliente
(``warm_start`` lanza :class:`SolverError` en lugar de ignorarse). Los estados se normalizan con
:func:`map_clarabel_status`; ``x`` solo se expone si el estado es ``OPTIMAL`` u
``OPTIMAL_INACCURATE`` y es finito.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import clarabel
import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.config.conic_config import ConicSolverConfig
from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import (
    OptimalityClaim,
    ProblemClass,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.solution import USABLE_STATUSES, SolveResult
from portfolio_engine.optimizers.base import (
    BackendCapabilities,
    OptimizationBackend,
    SetupInfo,
    UpdateInfo,
)
from portfolio_engine.optimizers.problem import CanonicalProblem, ConicProblem
from portfolio_engine.optimizers.status import map_clarabel_status

#: Estado nativo de Clarabel cuando se agota ``max_iter`` (el reintento mantiene la numérica).
ITERATION_LIMIT_STATUS = "MaxIterations"

SUPPORTED_CLASSES = frozenset({ProblemClass.QP, ProblemClass.LP, ProblemClass.SOCP})


@dataclass(frozen=True, eq=False, slots=True)
class ConicForm:
    """Datos de Clarabel ``(P, q, A, b, conos)`` y la estructura de filas de la que proceden.

    ``equality``, ``above`` y ``below`` son las máscaras de filas lineales originales (cono cero,
    cota superior y cota inferior); permiten reconstruir ``b`` si cambian ``lower``/``upper`` y
    comprobar que la estructura no ha cambiado.
    """

    P: Any
    q: npt.NDArray[np.float64]
    A: Any
    b: npt.NDArray[np.float64]
    cones: tuple[Any, ...]
    equality: npt.NDArray[np.bool_]
    above: npt.NDArray[np.bool_]
    below: npt.NDArray[np.bool_]
    n_linear_rows: int

    def same_structure(self, other: ConicForm) -> bool:
        """``True`` si ``other`` solo difiere en valores de ``q`` y ``b`` (no en la estructura)."""
        return (
            np.array_equal(self.equality, other.equality)
            and np.array_equal(self.above, other.above)
            and np.array_equal(self.below, other.below)
        )


def to_conic_form(
    problem: CanonicalProblem,
    q: npt.NDArray[np.float64],
    lower: npt.NDArray[np.float64],
    upper: npt.NDArray[np.float64],
) -> ConicForm:
    """Traduce ``problem`` (con ``q``, ``lower`` y ``upper`` actuales) a la forma de Clarabel."""
    finite_lower, finite_upper = np.isfinite(lower), np.isfinite(upper)
    equality = finite_lower & finite_upper & (lower == upper)
    above = finite_upper & ~equality
    below = finite_lower & ~equality
    matrix = sparse.csr_matrix(problem.A)
    blocks = [matrix[equality], matrix[above], -matrix[below]]
    offsets = [upper[equality], upper[above], -lower[below]]
    cones: list[Any] = []
    if equality.any():
        cones.append(clarabel.ZeroConeT(int(equality.sum())))
    inequalities = int(above.sum() + below.sum())
    if inequalities:
        cones.append(clarabel.NonnegativeConeT(inequalities))
    n_linear = int(equality.sum()) + inequalities
    if isinstance(problem, ConicProblem):
        for cone in problem.cones:
            height = sparse.csr_matrix(cone.a.reshape(1, -1))
            blocks.append(-sparse.vstack([height, cone.F], format="csr"))
            offsets.append(np.concatenate([[cone.c], cone.g]))
            cones.append(clarabel.SecondOrderConeT(cone.dimension))
    stacked = sparse.vstack(blocks, format="csc")
    return ConicForm(
        P=sparse.csc_matrix(problem.P),
        q=np.array(q, dtype=np.float64),
        A=stacked,
        b=np.concatenate(offsets).astype(np.float64),
        cones=tuple(cones),
        equality=equality,
        above=above,
        below=below,
        n_linear_rows=n_linear,
    )


class ClarabelBackend(OptimizationBackend):
    """Backend de SOCP (y QP/LP) basado en Clarabel."""

    def __init__(self, solver_config: SolverConfig, conic_config: ConicSolverConfig) -> None:
        self._solver_config = solver_config
        self._conic = conic_config
        self._problem: CanonicalProblem | None = None
        self._solver: Any = None
        self._form: ConicForm | None = None
        self._q = np.empty(0, dtype=np.float64)
        self._lower = np.empty(0, dtype=np.float64)
        self._upper = np.empty(0, dtype=np.float64)
        self._setup_count = 0
        self._update_count = 0
        self._solve_count = 0
        self._pending_setup_time = 0.0
        self._pending_update_time = 0.0
        self._updated_fields: list[str] = []
        self._last_native_status = ""

    @property
    def name(self) -> str:
        """Nombre del solver."""
        return "CLARABEL"

    @property
    def version(self) -> str:
        """Versión de Clarabel instalada."""
        return str(clarabel.__version__)

    @property
    def capabilities(self) -> BackendCapabilities:
        """Capacidades verificadas por tests: conos de segundo orden y actualización de vectores.

        Sin cono PSD (no implementado en el motor), sin arranque en caliente (punto interior).
        """
        return BackendCapabilities(
            supports_qp=True,
            supports_socp=True,
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
        """Clarabel resuelve LP, QP y SOCP convexos."""
        return problem_class in SUPPORTED_CLASSES

    def setup(self, problem: CanonicalProblem) -> SetupInfo:
        """Crea el workspace de Clarabel para ``problem``."""
        if not self.supports(problem.problem_class):
            raise SolverError(f"Clarabel no resuelve problemas {problem.problem_class}.")
        if type(problem) not in (CanonicalProblem, ConicProblem):
            raise SolverError(f"Clarabel no admite {type(problem).__name__}.")
        started = time.perf_counter()
        form = to_conic_form(problem, problem.q, problem.lower, problem.upper)
        self._solver = self._new_solver(form, self._conic.max_iterations, self._conic.equilibrate)
        elapsed = time.perf_counter() - started
        self._problem = problem
        self._form = form
        self._q = np.array(problem.q, dtype=np.float64)
        self._lower = np.array(problem.lower, dtype=np.float64)
        self._upper = np.array(problem.upper, dtype=np.float64)
        self._setup_count += 1
        self._pending_setup_time += elapsed
        return SetupInfo(elapsed, problem.n_variables, form.A.shape[0])

    def update(
        self,
        *,
        q: npt.NDArray[np.float64] | None = None,
        lower: npt.NDArray[np.float64] | None = None,
        upper: npt.NDArray[np.float64] | None = None,
    ) -> UpdateInfo:
        """Actualiza ``q``, ``lower`` y/o ``upper``.

        Con la misma estructura de filas finitas solo se modifican ``q`` y ``b`` del workspace
        vivo; si cambia (una cota pasa de finita a infinita o a igualdad) se reconstruye el
        problema completo y se contabiliza como ``setup``.
        """
        problem = self._require_problem()
        new_q = _checked(q, problem.n_variables, "q", allow_inf=False)
        new_lower = _checked(lower, problem.n_constraints, "lower", allow_inf=True)
        new_upper = _checked(upper, problem.n_constraints, "upper", allow_inf=True)
        merged_q = self._q if new_q is None else new_q
        merged_lower = self._lower if new_lower is None else new_lower
        merged_upper = self._upper if new_upper is None else new_upper
        if np.any(merged_lower > merged_upper):
            raise SolverError("Actualización inválida: lower > upper.")
        started = time.perf_counter()
        form = to_conic_form(problem, merged_q, merged_lower, merged_upper)
        current = self._require_form()
        if form.same_structure(current):
            self._solver.update(q=merged_q, b=form.b)
        else:
            self._solver = self._new_solver(
                form, self._conic.max_iterations, self._conic.equilibrate
            )
            self._setup_count += 1
        elapsed = time.perf_counter() - started
        self._form = form
        for label, value in (("q", new_q), ("lower", new_lower), ("upper", new_upper)):
            if value is not None:
                self._updated_fields.append(label)
        self._q, self._lower, self._upper = merged_q, merged_lower, merged_upper
        self._update_count += 1
        self._pending_update_time += elapsed
        return UpdateInfo(elapsed)

    def warm_start(
        self,
        x: npt.NDArray[np.float64] | None = None,
        y: npt.NDArray[np.float64] | None = None,
    ) -> None:
        """Clarabel (punto interior) no admite arranque en caliente: se rechaza explícitamente."""
        raise SolverError("Clarabel no admite arranque en caliente (punto interior).")

    def solve(self) -> SolveResult:
        """Resuelve con los datos actuales del workspace."""
        raw = self._require_solver().solve()
        self._last_native_status = str(raw.status)
        result = self._normalize(
            raw,
            setup_time=self._pending_setup_time,
            update_time=self._pending_update_time,
            cold_retries=0,
            source=StatusSource.SOLVER,
        )
        self._pending_setup_time = 0.0
        self._pending_update_time = 0.0
        self._solve_count += 1
        return result

    def cold_retry(self) -> SolveResult:
        """Reintento en frío: solver nuevo con los datos actuales y más iteraciones.

        Las tolerancias son las configuradas (no se relajan). Tras un estancamiento numérico
        (``AlmostSolved``, ``NumericalError``, ``InsufficientProgress``) repetir el mismo método
        determinista reproduce el mismo estancamiento, así que el reintento usa otra numérica
        (``conic.retry_equilibrate``); un ``Solved`` del reintento cumple exactamente las mismas
        condiciones que uno del primer intento. Tras ``MaxIterations`` el límite era el nº de
        iteraciones, no la numérica: se conserva el equilibrado primario. El estado del reintento
        es el suyo (nunca se mejora artificialmente).
        """
        form = self._require_form()
        iterations = self._conic.max_iterations * self._solver_config.retry_iteration_multiplier
        started = time.perf_counter()
        equilibrate = (
            self._conic.equilibrate
            if self._last_native_status == ITERATION_LIMIT_STATUS
            else self._conic.retry_equilibrate
        )
        retry = self._new_solver(form, iterations, equilibrate)
        setup_time = time.perf_counter() - started
        return self._normalize(
            retry.solve(),
            setup_time=setup_time,
            update_time=0.0,
            cold_retries=1,
            source=StatusSource.CROSS_CHECK,
        )

    # -------------------------------------------------------------------------------- internos

    def _new_solver(self, form: ConicForm, max_iterations: int, equilibrate: bool) -> Any:
        settings = clarabel.DefaultSettings()
        settings.verbose = False
        settings.max_iter = max_iterations
        settings.tol_gap_abs = self._conic.tol_gap_abs
        settings.tol_gap_rel = self._conic.tol_gap_rel
        settings.tol_feas = self._conic.tol_feas
        settings.tol_infeas_abs = self._conic.tol_infeas_abs
        settings.tol_infeas_rel = self._conic.tol_infeas_rel
        settings.equilibrate_enable = equilibrate
        if self._conic.time_limit_seconds is not None:
            settings.time_limit = self._conic.time_limit_seconds
        return clarabel.DefaultSolver(form.P, form.q, form.A, form.b, list(form.cones), settings)

    def _normalize(
        self,
        raw: Any,
        *,
        setup_time: float,
        update_time: float,
        cold_retries: int,
        source: StatusSource,
    ) -> SolveResult:
        problem = self._require_problem()
        native = str(raw.status)
        status = map_clarabel_status(native)
        x = np.array(raw.x, dtype=np.float64)
        if status in USABLE_STATUSES and not np.all(np.isfinite(x)):
            status = SolverStatus.NUMERICAL_ERROR
        usable = status in USABLE_STATUSES
        return SolveResult(
            status=status,
            native_status=native,
            status_source=source,
            solver_name=self.name,
            solver_version=self.version,
            problem_class=problem.problem_class,
            x=x if usable else None,
            y=None,
            objective_value=_finite_or_none(raw.obj_val) if usable else None,
            iterations=int(raw.iterations),
            setup_time=setup_time,
            update_time=update_time,
            solve_time=float(raw.solve_time),
            primal_residual=_finite_or_none(raw.r_prim),
            dual_residual=_finite_or_none(raw.r_dual),
            warm_start_used=False,
            cold_retries=cold_retries,
            optimality_claim=(
                OptimalityClaim.CONVEX_GLOBAL
                if status is SolverStatus.OPTIMAL
                else OptimalityClaim.NOT_ASSESSED
            ),
        )

    def _require_problem(self) -> CanonicalProblem:
        if self._problem is None:
            raise SolverError("El workspace no está creado: llame a setup() primero.")
        return self._problem

    def _require_solver(self) -> Any:
        self._require_problem()
        return self._solver

    def _require_form(self) -> ConicForm:
        self._require_problem()
        if self._form is None:
            raise SolverError("El workspace no está creado: llame a setup() primero.")
        return self._form


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
