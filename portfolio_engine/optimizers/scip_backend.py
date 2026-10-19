"""Backend mixto entero con SCIP / PySCIPOpt (MASTER_SPEC §49; MIP-002, MIP-007, enmienda E-24).

Resuelve ``EXACT_MIP`` (MIQP / MIQCP / MISOCP) de forma exacta con branch-and-bound. Traducción del
problema del motor (``min ½xᵀPx + qᵀx``, ``lower <= Ax <= upper``, conos ``‖Fx+g‖ <= aᵀx+c`` y
variables binarias):

* SCIP exige objetivo lineal: se introduce una variable epígrafe ``t`` y la restricción cuadrática
  convexa ``½xᵀPx + qᵀx <= t`` (objetivo ``min t``);
* cada cono se escribe con variables auxiliares ``y = Fx + g`` y ``h = aᵀx + c >= 0`` y la
  restricción cuadrática convexa ``Σ y² <= h²``;
* las filas lineales se añaden tal cual.

Estados (:func:`map_scip_status`): ``optimal`` es ``OPTIMAL``; ``gaplimit`` se promueve a
``OPTIMAL`` únicamente si la brecha relativa o absoluta cumple la tolerancia configurada; un límite
de tiempo o de nodos nunca es ``OPTIMAL`` aunque exista una solución entera, que se devuelve como
``MipDiagnostics.incumbent`` con su cota dual (sin cota dual finita no hay brecha certificada).
La cota dual del solver es la única base de un ``optimality gap``; nunca se inventa.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import sparse

from portfolio_engine.config.exact_mip_config import ExactMIPConfig
from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import (
    OptimalityClaim,
    ProblemClass,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.solution import MipDiagnostics, SolveResult
from portfolio_engine.optimizers.base import BackendCapabilities, SetupInfo
from portfolio_engine.optimizers.mixed_integer_backend import (
    MIXED_INTEGER_CLASSES,
    MixedIntegerBackend,
)
from portfolio_engine.optimizers.problem import CanonicalProblem, MixedIntegerProblem
from portfolio_engine.optimizers.status import map_scip_status

try:  # pyscipopt es una dependencia opcional (grupo ``exact-mip``, A-24)
    import pyscipopt as _scip

    SCIP_AVAILABLE = True
except ImportError:  # pragma: no cover - depende del entorno
    _scip = None  # type: ignore[assignment]
    SCIP_AVAILABLE = False


class SCIPBackend(MixedIntegerBackend):
    """Backend ``EXACT_MIP`` de referencia basado en SCIP."""

    def __init__(self, config: ExactMIPConfig, seed: int) -> None:
        if not SCIP_AVAILABLE:
            raise SolverError("PySCIPOpt no está instalado: EXACT_MIP no está disponible.")
        self._config = config
        self._seed = int(seed)
        self._problem: MixedIntegerProblem | None = None
        self._model: Any = None
        self._variables: list[Any] = []
        self._epigraph: Any = None
        self._hint: npt.NDArray[np.float64] | None = None
        self._setup_count = 0
        self._solve_count = 0
        self._pending_setup_time = 0.0

    @property
    def name(self) -> str:
        """Nombre del solver."""
        return "SCIP"

    @property
    def version(self) -> str:
        """Versión de SCIP enlazada por PySCIPOpt."""
        return str(_scip.Model().version())

    @property
    def capabilities(self) -> BackendCapabilities:
        """Capacidades: enteros y conos (MIQCP/MISOCP); sin actualización ni SDP."""
        return BackendCapabilities(
            supports_qp=True,
            supports_socp=True,
            supports_sdp=False,
            supports_integer=True,
            supports_nonconvex=False,
            supports_vector_update=False,
            supports_matrix_update=False,
            supports_warm_start=True,
            supports_factorization_reuse=False,
        )

    @property
    def setup_count(self) -> int:
        """Modelos construidos."""
        return self._setup_count

    @property
    def update_count(self) -> int:
        """Siempre 0: un problema exacto no se actualiza."""
        return 0

    @property
    def solve_count(self) -> int:
        """Resoluciones realizadas."""
        return self._solve_count

    @property
    def updated_fields(self) -> tuple[str, ...]:
        """Siempre vacío (sin actualizaciones)."""
        return ()

    def supports(self, problem_class: ProblemClass) -> bool:
        """SCIP resuelve MIQP, MIQCP y MISOCP."""
        return problem_class in MIXED_INTEGER_CLASSES

    def setup(self, problem: CanonicalProblem) -> SetupInfo:
        """Construye el modelo SCIP de ``problem`` (debe ser un :class:`MixedIntegerProblem`)."""
        if not isinstance(problem, MixedIntegerProblem) or not self.supports(problem.problem_class):
            raise SolverError(
                f"SCIP resuelve MixedIntegerProblem (MIQP/MIQCP/MISOCP), no {problem.problem_class}"
            )
        started = time.perf_counter()
        self._model, self._variables, self._epigraph = self._build(problem)
        self._problem = problem
        elapsed = time.perf_counter() - started
        self._setup_count += 1
        self._pending_setup_time += elapsed
        return SetupInfo(elapsed, problem.n_variables, problem.n_constraints)

    def hint(self, x: npt.NDArray[np.float64]) -> None:
        """Guarda una solución inicial que ``solve`` ofrece a SCIP (puede rechazarla)."""
        problem = self._require_problem()
        array = np.array(x, dtype=np.float64)
        if array.shape != (problem.n_variables,) or not np.all(np.isfinite(array)):
            raise SolverError("hint: dimensión incorrecta o valores no finitos.")
        self._hint = array

    def warm_start(
        self,
        x: npt.NDArray[np.float64] | None = None,
        y: npt.NDArray[np.float64] | None = None,
    ) -> None:
        """Equivale a :meth:`hint` con ``x`` (``y`` no existe en un problema entero)."""
        if y is not None:
            raise SolverError("Un problema entero no tiene multiplicadores duales que sugerir.")
        if x is not None:
            self.hint(x)

    def solve(self) -> SolveResult:
        """Resuelve el modelo (branch-and-bound) con los límites configurados."""
        problem = self._require_problem()
        model = self._model
        if self._hint is not None:
            self._offer_hint(problem, self._hint)
        started = time.perf_counter()
        model.optimize()
        elapsed = time.perf_counter() - started
        result = self._normalize(problem, elapsed)
        self._pending_setup_time = 0.0
        self._solve_count += 1
        return result

    def cold_retry(self) -> SolveResult:
        """Reconstruye el modelo desde cero y lo vuelve a resolver (mismos límites)."""
        problem = self._require_problem()
        self._model, self._variables, self._epigraph = self._build(problem)
        self._setup_count += 1
        self._hint = None
        result = self.solve()
        return SolveResult(
            status=result.status,
            native_status=result.native_status,
            status_source=StatusSource.CROSS_CHECK,
            solver_name=result.solver_name,
            solver_version=result.solver_version,
            problem_class=result.problem_class,
            x=result.x,
            y=None,
            objective_value=result.objective_value,
            iterations=result.iterations,
            setup_time=result.setup_time,
            update_time=0.0,
            solve_time=result.solve_time,
            primal_residual=result.primal_residual,
            dual_residual=None,
            warm_start_used=False,
            cold_retries=1,
            optimality_claim=result.optimality_claim,
            mip=result.mip,
        )

    # -------------------------------------------------------------------------------- internos

    def _build(self, problem: MixedIntegerProblem) -> tuple[Any, list[Any], Any]:
        model = _scip.Model()
        model.hideOutput()
        config = self._config
        model.setParam("limits/time", config.time_limit_seconds)
        model.setParam("limits/gap", config.relative_gap_tolerance)
        model.setParam("limits/absgap", config.absolute_gap_tolerance)
        model.setParam("parallel/maxnthreads", config.threads)
        model.setParam("randomization/randomseedshift", self._seed % int(np.iinfo(np.int32).max))
        if config.node_limit is not None:
            model.setParam("limits/nodes", config.node_limit)
        binary = frozenset(problem.binary_indices)
        variables = [
            model.addVar(
                name=f"x{index}",
                vtype="B" if index in binary else "C",
                lb=0.0 if index in binary else None,
                ub=1.0 if index in binary else None,
            )
            for index in range(problem.n_variables)
        ]
        objective = model.addVar(name="epigraph", vtype="C", lb=None, ub=None)
        model.setObjective(objective, "minimize")
        model.addCons(_objective_expression(problem, variables) <= objective)
        self._add_rows(model, problem, variables)
        for index, cone in enumerate(problem.cones):
            self._add_cone(model, cone, variables, index)
        return model, variables, objective

    @staticmethod
    def _add_rows(model: Any, problem: CanonicalProblem, variables: list[Any]) -> None:
        matrix = problem.A.tocsr()
        for row in range(problem.n_constraints):
            start, end = matrix.indptr[row], matrix.indptr[row + 1]
            terms = [
                float(matrix.data[k]) * variables[int(matrix.indices[k])] for k in range(start, end)
            ]
            expression = _scip.quicksum(terms)
            low, high = float(problem.lower[row]), float(problem.upper[row])
            if math.isfinite(low) and low == high:
                model.addCons(expression == high)
                continue
            if math.isfinite(high):
                model.addCons(expression <= high)
            if math.isfinite(low):
                model.addCons(expression >= low)

    @staticmethod
    def _add_cone(model: Any, cone: Any, variables: list[Any], index: int) -> None:
        height = model.addVar(name=f"cone{index}_h", vtype="C", lb=0.0, ub=None)
        linear = _scip.quicksum(
            float(coefficient) * variables[position]
            for position, coefficient in enumerate(cone.a.tolist())
            if coefficient != 0.0
        )
        model.addCons(height == linear + cone.c)
        matrix = cone.F.tocsr()
        squares = []
        for row in range(matrix.shape[0]):
            start, end = matrix.indptr[row], matrix.indptr[row + 1]
            component = model.addVar(name=f"cone{index}_y{row}", vtype="C", lb=None, ub=None)
            terms = _scip.quicksum(
                float(matrix.data[k]) * variables[int(matrix.indices[k])] for k in range(start, end)
            )
            model.addCons(component == terms + float(cone.g[row]))
            squares.append(component * component)
        model.addCons(_scip.quicksum(squares) <= height * height)

    def _offer_hint(self, problem: MixedIntegerProblem, hint: npt.NDArray[np.float64]) -> None:
        model = self._model
        solution = model.createSol()
        for index, variable in enumerate(self._variables):
            model.setSolVal(solution, variable, float(hint[index]))
        model.setSolVal(solution, self._epigraph, _objective_value(problem, hint))
        model.addSol(solution, free=True)
        self._hint = None

    def _normalize(self, problem: MixedIntegerProblem, elapsed: float) -> SolveResult:
        model = self._model
        native = str(model.getStatus())
        status = map_scip_status(native)
        n_solutions = int(model.getNSols())
        incumbent = self._incumbent(problem) if n_solutions > 0 else None
        primal = _finite_or_none(model.getPrimalbound()) if incumbent is not None else None
        dual = _finite_or_none(model.getDualbound())
        gap = _finite_or_none(model.getGap()) if dual is not None else None
        if (
            native.lower() == "gaplimit"
            and incumbent is not None
            and self._gap_closed(primal, dual)
        ):
            status = SolverStatus.OPTIMAL
        proven = status is SolverStatus.OPTIMAL and incumbent is not None
        if status is SolverStatus.OPTIMAL and incumbent is None:
            status = SolverStatus.NUMERICAL_ERROR
        diagnostics = MipDiagnostics(
            primal_bound=primal,
            dual_bound=dual,
            relative_gap=gap,
            nodes=int(model.getNNodes()),
            solutions_found=n_solutions,
            incumbent=incumbent,
        )
        exposed = incumbent if proven else None
        if proven:
            claim = (
                OptimalityClaim.MIP_PROVEN
                if diagnostics.has_valid_dual_bound
                else OptimalityClaim.FEASIBLE_ONLY
            )
        elif incumbent is not None:
            claim = (
                OptimalityClaim.MIP_INCUMBENT
                if diagnostics.has_valid_dual_bound
                else OptimalityClaim.FEASIBLE_ONLY
            )
        else:
            claim = OptimalityClaim.NOT_ASSESSED
        return SolveResult(
            status=status,
            native_status=native,
            status_source=StatusSource.SOLVER,
            solver_name=self.name,
            solver_version=self.version,
            problem_class=problem.problem_class,
            x=exposed,
            y=None,
            objective_value=None if exposed is None else _objective_value(problem, exposed),
            iterations=int(model.getNNodes()),
            setup_time=self._pending_setup_time,
            update_time=0.0,
            solve_time=elapsed,
            primal_residual=None,
            dual_residual=None,
            warm_start_used=False,
            cold_retries=0,
            optimality_claim=claim,
            mip=diagnostics,
        )

    def _incumbent(self, problem: MixedIntegerProblem) -> npt.NDArray[np.float64] | None:
        model = self._model
        solution = model.getBestSol()
        values = np.array([model.getSolVal(solution, v) for v in self._variables], dtype=float)
        if not np.all(np.isfinite(values)):
            return None
        binary = np.array(problem.binary_indices, dtype=np.int64)
        snapped = np.round(values[binary])
        near = np.abs(values[binary] - snapped) <= self._config.integrality_tolerance
        values[binary[near]] = snapped[near]
        return values

    def _gap_closed(self, primal: float | None, dual: float | None) -> bool:
        if primal is None or dual is None:
            return False
        absolute = abs(primal - dual)
        relative = absolute / max(abs(primal), abs(dual), np.finfo(np.float64).tiny)
        config = self._config
        return (
            absolute <= config.absolute_gap_tolerance or relative <= config.relative_gap_tolerance
        )

    def _require_problem(self) -> MixedIntegerProblem:
        if self._problem is None or self._model is None:
            raise SolverError("El modelo no está creado: llame a setup() primero.")
        return self._problem


def _objective_expression(problem: CanonicalProblem, variables: list[Any]) -> Any:
    """``½xᵀPx + qᵀx`` como expresión de SCIP (``P`` almacenada triangular superior)."""
    matrix = problem.P.tocoo()
    terms: list[Any] = []
    for row, column, value in zip(
        matrix.row.tolist(), matrix.col.tolist(), matrix.data.tolist(), strict=True
    ):
        weight = 0.5 * value if row == column else value
        terms.append(weight * variables[row] * variables[column])
    for index, value in enumerate(problem.q.tolist()):
        if value != 0.0:
            terms.append(value * variables[index])
    return _scip.quicksum(terms)


def _objective_value(problem: CanonicalProblem, x: npt.NDArray[np.float64]) -> float:
    """Valor del objetivo original ``½xᵀ(P + Pᵀ − diag P)x + qᵀx`` calculado desde ``x``."""
    upper = problem.P
    full = upper + upper.T - sparse.diags(upper.diagonal(), format="csc")
    return float(0.5 * x @ (full @ x) + problem.q @ x)


def _finite_or_none(value: object) -> float | None:
    number = float(value)  # type: ignore[arg-type]
    return number if math.isfinite(number) else None
