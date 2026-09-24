"""SOL-003, SOL-004, SOL-009, SOL-012, SOL-013, SOL-014: backend OSQP, workspace y estados."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import scipy.sparse as sparse

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import (
    CrossCheckPolicy,
    OptimizationFamily,
    ProblemClass,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers import (
    CanonicalProblem,
    OptimizationBackend,
    OSQPBackend,
    solve_with_policy,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

SOLVER = base_config().solver
VARIANCES = np.array([0.04, 0.09])


def _min_variance_problem(
    *, upper: float = 1.0, extra_lower: float | None = None
) -> CanonicalProblem:
    """``min wᵀΣw`` con ``Σ = diag(0.04, 0.09)``, ``1ᵀw = 1``, ``0 <= w <= upper``."""
    rows = [[1.0, 1.0], [1.0, 0.0], [0.0, 1.0]]
    lower = [1.0, 0.0, 0.0]
    high = [1.0, upper, upper]
    if extra_lower is not None:  # fila redundante 1ᵀw >= extra_lower (inviable si > 1)
        rows.append([1.0, 1.0])
        lower.append(extra_lower)
        high.append(np.inf)
    return CanonicalProblem(
        name="test_qp",
        problem_class=ProblemClass.QP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.triu(sparse.csc_matrix(np.diag(2.0 * VARIANCES))),
        q=np.zeros(2),
        A=sparse.csc_matrix(np.array(rows)),
        lower=np.array(lower),
        upper=np.array(high),
    )


def test_solution_matches_the_closed_form() -> None:
    """SOL-004: ``w_i ∝ 1/σ_i²`` (solución cerrada), con estado y diagnósticos completos."""
    backend = OSQPBackend(SOLVER)
    info = backend.setup(_min_variance_problem())
    result = backend.solve()
    expected = (1.0 / VARIANCES) / (1.0 / VARIANCES).sum()
    assert result.status is SolverStatus.OPTIMAL and result.native_status == "solved"
    assert result.x is not None and result.x == pytest.approx(expected, abs=1e-8)
    assert result.solver_name == "OSQP" and result.solver_version
    assert result.problem_class is ProblemClass.QP and result.status_source is StatusSource.SOLVER
    assert result.iterations > 0 and result.solve_time >= 0.0
    assert result.setup_time == pytest.approx(info.setup_time)
    assert result.primal_residual is not None and result.dual_residual is not None
    assert result.objective_value == pytest.approx(float(expected @ np.diag(VARIANCES) @ expected))
    assert not result.warm_start_used and result.cold_retries == 0


def test_workspace_reuse_updates_only_vectors_and_matches_cold_solves() -> None:
    """SOL-009: un solo ``setup``; solo ``q``/``lower``/``upper`` cambian; resultado = solve en
    frío."""
    reused = OSQPBackend(SOLVER)
    reused.setup(_min_variance_problem())
    for theta in (0.0, 0.1, 0.5, 1.0):
        q = -theta * np.array([0.05, 0.08])
        reused.update(q=q)
        warm = reused.solve()
        cold_backend = OSQPBackend(SOLVER)
        cold_backend.setup(_min_variance_problem())
        cold_backend.update(q=q)
        cold = cold_backend.solve()
        assert warm.x is not None and cold.x is not None
        assert warm.x == pytest.approx(cold.x, abs=1e-7)
    assert reused.setup_count == 1 and reused.update_count == 4 and reused.solve_count == 4
    assert set(reused.updated_fields) == {"q"}
    reused.update(lower=np.array([1.0, 0.1, 0.1]), upper=np.array([1.0, 0.9, 0.9]))
    assert set(reused.updated_fields) == {"q", "lower", "upper"}
    assert (
        reused.capabilities.supports_vector_update
        and not reused.capabilities.supports_matrix_update
    )


def test_updates_change_the_solution() -> None:
    """La capacidad de actualización es real: cambiar ``lower`` desplaza el óptimo."""
    backend = OSQPBackend(SOLVER)
    backend.setup(_min_variance_problem())
    first = backend.solve().x
    backend.update(lower=np.array([1.0, 0.0, 0.5]), upper=np.array([1.0, 1.0, 1.0]))
    second = backend.solve().x
    assert first is not None and second is not None
    assert second[1] == pytest.approx(0.5, abs=1e-7) and first[1] != pytest.approx(0.5, abs=1e-3)


def test_warm_start_is_used_and_does_not_need_more_iterations() -> None:
    backend = OSQPBackend(SOLVER)
    backend.setup(_min_variance_problem())
    cold = backend.solve()
    backend.update(q=np.array([-0.001, -0.001]))
    warm = backend.solve()
    assert not cold.warm_start_used and warm.warm_start_used
    assert warm.iterations <= cold.iterations
    no_warm = OSQPBackend(dataclasses.replace(SOLVER, warm_start=False))
    no_warm.setup(_min_variance_problem())
    no_warm.solve()
    no_warm.update(q=np.array([-0.001, -0.001]))
    assert not no_warm.solve().warm_start_used


def test_explicit_warm_start_from_a_vector() -> None:
    backend = OSQPBackend(SOLVER)
    backend.setup(_min_variance_problem())
    cold = backend.solve()
    other = OSQPBackend(SOLVER)
    other.setup(_min_variance_problem())
    assert cold.x is not None
    other.warm_start(x=cold.x, y=cold.y)
    started = other.solve()
    assert started.warm_start_used and started.iterations <= cold.iterations


def test_repeated_solves_are_bit_reproducible() -> None:
    """§70: mismas entradas y configuración ⇒ mismos bits e iteraciones (rho adaptativo fijo)."""
    runs = []
    for _ in range(3):
        backend = OSQPBackend(SOLVER)
        backend.setup(_min_variance_problem())
        runs.append(backend.solve())
    assert all(run.x is not None and np.array_equal(run.x, runs[0].x) for run in runs)
    assert len({run.iterations for run in runs}) == 1


def test_infeasible_problem_has_infeasible_status_and_no_vector() -> None:
    """SOL-013: OSQP certifica la inviabilidad; ``x`` no se expone; no es un fallo numérico."""
    backend = OSQPBackend(
        dataclasses.replace(SOLVER, ambiguous_status_policy=CrossCheckPolicy.NONE)
    )
    backend.setup(_min_variance_problem(extra_lower=3.0))
    result = solve_with_policy(backend, CrossCheckPolicy.COLD_RETRY)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.native_status == "primal infeasible"
    assert result.x is None and not result.is_usable and result.objective_value is None
    assert result.cold_retries == 0  # un certificado firme no se reintenta


def test_unbounded_problem_is_reported_as_unbounded() -> None:
    problem = CanonicalProblem(
        name="unbounded",
        problem_class=ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((1, 1)),
        q=np.array([-1.0]),
        A=sparse.csc_matrix(np.array([[1.0]])),
        lower=np.array([0.0]),
        upper=np.array([np.inf]),
    )
    backend = OSQPBackend(SOLVER)
    backend.setup(problem)
    result = backend.solve()
    assert result.status is SolverStatus.UNBOUNDED and result.x is None


def test_iteration_limit_is_max_iterations_not_infeasible() -> None:
    """Estado no óptimo reproducible: límite de iteraciones ⇒ ``MAX_ITERATIONS`` sin vector."""
    limited = dataclasses.replace(
        SOLVER, max_iterations=1, ambiguous_status_policy=CrossCheckPolicy.NONE
    )
    backend = OSQPBackend(limited)
    backend.setup(_min_variance_problem())
    result = solve_with_policy(backend, CrossCheckPolicy.NONE)
    assert result.status is SolverStatus.MAX_ITERATIONS
    assert result.native_status == "maximum iterations reached"
    assert result.x is None and result.status is not SolverStatus.INFEASIBLE


def test_cold_retry_recovers_from_an_iteration_limit() -> None:
    """SOL-014: ``COLD_RETRY`` reintenta desde cero con más iteraciones (retry real,
    CROSS_CHECK)."""
    limited = dataclasses.replace(SOLVER, max_iterations=1, retry_iteration_multiplier=10_000)
    backend = OSQPBackend(limited)
    backend.setup(_min_variance_problem())
    result = solve_with_policy(backend, CrossCheckPolicy.COLD_RETRY)
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    assert result.cold_retries == 1 and result.status_source is StatusSource.CROSS_CHECK
    assert not result.warm_start_used
    assert result.iterations > 1  # incluye el intento fallido
    expected = (1.0 / VARIANCES) / (1.0 / VARIANCES).sum()
    assert result.x == pytest.approx(expected, abs=1e-7)
    assert backend.setup_count == 1  # el reintento no cuenta como setup del workspace


def test_solve_result_exposes_x_only_for_usable_statuses() -> None:
    kwargs = {
        "native_status": "x",
        "status_source": StatusSource.SOLVER,
        "solver_name": "T",
        "solver_version": "0",
        "problem_class": ProblemClass.QP,
        "y": None,
        "objective_value": None,
        "iterations": 0,
        "setup_time": 0.0,
        "update_time": 0.0,
        "solve_time": 0.0,
        "primal_residual": None,
        "dual_residual": None,
        "warm_start_used": False,
        "cold_retries": 0,
    }
    with pytest.raises(SolverError):
        SolveResult(status=SolverStatus.INFEASIBLE, x=np.zeros(2), **kwargs)  # type: ignore[arg-type]
    with pytest.raises(SolverError):
        SolveResult(status=SolverStatus.OPTIMAL, x=None, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(SolverError, match="no finitos"):
        SolveResult(status=SolverStatus.OPTIMAL, x=np.array([np.nan]), **kwargs)  # type: ignore[arg-type]


def test_invalid_usage_is_rejected() -> None:
    backend = OSQPBackend(SOLVER)
    with pytest.raises(SolverError, match="setup"):
        backend.update(q=np.zeros(2))
    with pytest.raises(SolverError, match="setup"):
        backend.solve()
    backend.setup(_min_variance_problem())
    with pytest.raises(SolverError, match="dimensión"):
        backend.update(q=np.zeros(3))
    with pytest.raises(SolverError, match="no válidos"):
        backend.update(q=np.array([np.nan, 0.0]))
    with pytest.raises(SolverError, match="lower > upper"):
        backend.update(lower=np.array([2.0, 0.0, 0.0]))
    sample = backend.solve()
    assert (
        sample.status is SolverStatus.OPTIMAL
    )  # una actualización rechazada no corrompe el workspace


def test_canonical_problem_validates_its_data() -> None:
    base = _min_variance_problem()
    with pytest.raises(SolverError, match="lower > upper"):
        dataclasses.replace(base, lower=np.array([1.0, 2.0, 0.0]), upper=np.array([1.0, 1.0, 1.0]))
    with pytest.raises(SolverError, match="finitos"):
        dataclasses.replace(base, q=np.array([np.inf, 0.0]))
    with pytest.raises(SolverError, match="triangular"):
        dataclasses.replace(base, P=sparse.csc_matrix(np.array([[1.0, 0.0], [1.0, 1.0]])))


def test_backend_contract_is_abstract_and_declares_real_capabilities() -> None:
    """SOL-003: la interfaz es abstracta; OSQP declara solo lo que soporta."""
    with pytest.raises(TypeError):
        OptimizationBackend()  # type: ignore[abstract]
    backend = OSQPBackend(SOLVER)
    caps = backend.capabilities
    assert caps.supports_qp and not (caps.supports_socp or caps.supports_integer)
    assert caps.supports_warm_start and caps.supports_factorization_reuse
    assert backend.supports(ProblemClass.QP) and backend.supports(ProblemClass.LP)
    assert not backend.supports(ProblemClass.MIQP) and not backend.supports(ProblemClass.SOCP)
    socp = dataclasses.replace(_min_variance_problem(), problem_class=ProblemClass.SOCP)
    with pytest.raises(SolverError, match="no resuelve"):
        backend.setup(socp)


def test_time_limit_is_forwarded_to_the_solver() -> None:
    """``time_limit_seconds`` es real: un límite ínfimo produce ``TIME_LIMIT`` sin vector."""
    tiny = dataclasses.replace(
        SOLVER, time_limit_seconds=1e-12, ambiguous_status_policy=CrossCheckPolicy.NONE
    )
    backend = OSQPBackend(tiny)
    backend.setup(_min_variance_problem())
    result = solve_with_policy(backend, CrossCheckPolicy.NONE)
    assert result.status is SolverStatus.TIME_LIMIT and result.x is None
