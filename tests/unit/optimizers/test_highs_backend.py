"""SOL-004, SOL-002, OPT-007 (H-1): backend LP con HiGHS y mapeo de sus estados."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import scipy.sparse as sparse
from scipy.optimize import linprog

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import (
    OptimizationFamily,
    ProblemClass,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.optimizers import (
    CanonicalProblem,
    HiGHSLPBackend,
    map_highs_status,
)
from tests.fixtures.problems import base_config
from tests.fixtures.reference import max_return_box_budget

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])


def _box_lp(mu: np.ndarray = MU, cap: float = 0.5) -> CanonicalProblem:
    """``min −μᵀw`` s.a. ``1ᵀw = 1``, ``0 <= w <= cap`` (filas: presupuesto y cotas)."""
    n = mu.shape[0]
    matrix = np.vstack([np.ones((1, n)), np.eye(n)])
    return CanonicalProblem(
        name="box_lp",
        problem_class=ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((n, n)),
        q=-mu,
        A=sparse.csc_matrix(matrix),
        lower=np.concatenate([[1.0], np.zeros(n)]),
        upper=np.concatenate([[1.0], np.full(n, cap)]),
    )


def _backend(**solver_changes: object) -> HiGHSLPBackend:
    config = dataclasses.replace(base_config().solver, **solver_changes)
    return HiGHSLPBackend(config)


def test_solution_matches_the_closed_form_and_an_independent_linprog() -> None:
    backend = _backend()
    backend.setup(_box_lp())
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    expected = max_return_box_budget(MU, np.zeros(4), np.full(4, 0.5))
    assert result.x == pytest.approx(expected, abs=1e-9)
    reference = linprog(
        -MU,
        A_eq=np.ones((1, 4)),
        b_eq=[1.0],
        bounds=[(0.0, 0.5)] * 4,
        method="highs",
    )
    assert result.objective_value == pytest.approx(reference.fun, abs=1e-12)
    assert result.solver_name == "HiGHS" and result.solver_version.startswith("scipy-")
    assert result.status_source is StatusSource.SOLVER and result.cold_retries == 0
    assert result.primal_residual is not None and result.primal_residual < 1e-9
    assert not result.warm_start_used


def test_multipliers_follow_the_row_convention() -> None:
    """``y > 0``: cota superior/igualdad activa; ``y < 0``: cota inferior activa; 0: holgada."""
    backend = _backend()
    backend.setup(_box_lp())
    result = backend.solve()
    assert result.y is not None
    # w* = (0, 0, 0.5, 0.5): activos 3 y 4 en su cota superior, 1 y 2 en la inferior. El dual del
    # presupuesto está en [0.08, 0.10] (degenerado): el activo 2 puede tener multiplicador 0.
    budget, bound_rows = result.y[0], result.y[1:]
    assert bound_rows[2] > 0.0 and bound_rows[3] >= 0.0  # cota superior activa (signo positivo)
    assert bound_rows[0] < 0.0 and bound_rows[1] <= 0.0  # cota inferior activa (signo negativo)
    assert abs(budget) > 0.0


def test_slack_rows_have_zero_multiplier() -> None:
    backend = _backend()
    backend.setup(_box_lp(cap=0.9))  # w* = (0, 0, 0.9, 0.1): el activo 4 no toca ninguna cota
    result = backend.solve()
    assert result.y is not None and result.x is not None
    assert result.x == pytest.approx([0.0, 0.0, 0.9, 0.1], abs=1e-9)
    assert result.y[1 + 3] == 0.0


def test_update_changes_the_solution_and_records_fields() -> None:
    backend = _backend()
    problem = _box_lp()
    backend.setup(problem)
    lower = problem.lower.copy()
    lower[1 + 0] = 0.3  # obliga a mantener al menos 0.3 en el activo de menor retorno
    backend.update(lower=lower)
    result = backend.solve()
    expected = max_return_box_budget(MU, np.array([0.3, 0.0, 0.0, 0.0]), np.full(4, 0.5))
    assert result.x == pytest.approx(expected, abs=1e-9)
    assert backend.updated_fields == ("lower",) and backend.update_count == 1
    backend.update(q=-MU * 2.0)
    assert backend.updated_fields == ("lower", "q")
    assert backend.solve().x == pytest.approx(expected, abs=1e-9)


def test_update_validates_before_touching_state() -> None:
    backend = _backend()
    problem = _box_lp()
    backend.setup(problem)
    with pytest.raises(SolverError, match="dimensión"):
        backend.update(q=np.zeros(3))
    with pytest.raises(SolverError, match="no válidos"):
        backend.update(q=np.array([np.nan, 0.0, 0.0, 0.0]))
    with pytest.raises(SolverError, match="lower > upper"):
        backend.update(lower=problem.upper + 1.0)
    assert backend.updated_fields == () and backend.update_count == 0
    assert backend.solve().status is SolverStatus.OPTIMAL


def test_infeasible_lp_is_reported_as_infeasible_not_as_a_numerical_error() -> None:
    backend = _backend()
    problem = _box_lp(cap=0.2)  # 4 · 0.2 = 0.8 < 1: presupuesto imposible
    backend.setup(problem)
    result = backend.solve()
    assert result.status is SolverStatus.INFEASIBLE
    assert result.x is None and result.y is None and not result.is_usable
    assert "infeasible" in result.native_status.lower()


def test_unbounded_lp_is_reported_as_unbounded() -> None:
    problem = CanonicalProblem(
        name="unbounded",
        problem_class=ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((2, 2)),
        q=np.array([-1.0, 0.0]),
        A=sparse.csc_matrix(np.array([[0.0, 1.0]])),
        lower=np.array([0.0]),
        upper=np.array([1.0]),
    )
    backend = _backend()
    backend.setup(problem)
    result = backend.solve()
    assert result.status is SolverStatus.UNBOUNDED and result.x is None


def test_iteration_limit_is_reported_and_cold_retry_uses_another_algorithm() -> None:
    rng = np.random.default_rng(3)
    n = 60
    mu = rng.uniform(0.03, 0.12, n)
    backend = _backend(lp_max_iterations=1, retry_iteration_multiplier=10_000)
    backend.setup(_box_lp(mu, cap=0.05))
    first = backend.solve()
    assert first.status is SolverStatus.MAX_ITERATIONS and first.x is None
    retried = backend.cold_retry()
    assert retried.status is SolverStatus.OPTIMAL and retried.x is not None
    assert retried.status_source is StatusSource.CROSS_CHECK and retried.cold_retries == 1
    reference = linprog(
        -mu, A_eq=np.ones((1, n)), b_eq=[1.0], bounds=[(0.0, 0.05)] * n, method="highs"
    )
    assert retried.objective_value == pytest.approx(reference.fun, abs=1e-10)


def test_time_limit_maps_to_time_limit_status() -> None:
    assert map_highs_status(1, "Time limit reached") is SolverStatus.TIME_LIMIT
    assert map_highs_status(1, "Iteration limit reached") is SolverStatus.MAX_ITERATIONS


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, SolverStatus.OPTIMAL),
        (1, SolverStatus.MAX_ITERATIONS),
        (2, SolverStatus.INFEASIBLE),
        (3, SolverStatus.UNBOUNDED),
        (4, SolverStatus.NUMERICAL_ERROR),
        (5, SolverStatus.UNKNOWN),
        (-1, SolverStatus.UNKNOWN),
        (99, SolverStatus.UNKNOWN),
    ],
)
def test_highs_status_mapping_never_collapses_states(code: int, expected: SolverStatus) -> None:
    assert map_highs_status(code, "") is expected


def test_only_lp_is_accepted_and_warm_start_is_refused() -> None:
    backend = _backend()
    qp = dataclasses.replace(
        _box_lp(), problem_class=ProblemClass.QP, P=sparse.identity(4, format="csc")
    )
    with pytest.raises(SolverError, match="solo resuelve LP"):
        backend.setup(qp)
    with pytest.raises(SolverError, match="setup"):
        backend.solve()
    backend.setup(_box_lp())
    with pytest.raises(SolverError, match="arranque en caliente"):
        backend.warm_start(x=np.zeros(4))
    assert backend.supports(ProblemClass.LP) and not backend.supports(ProblemClass.QP)
    capabilities = backend.capabilities
    assert not capabilities.supports_qp and not capabilities.supports_warm_start
    assert capabilities.supports_vector_update and not capabilities.supports_matrix_update


def test_setup_and_solve_counters_and_time_attribution() -> None:
    backend = _backend()
    info = backend.setup(_box_lp())
    assert info.n_variables == 4 and info.n_constraints == 5 and backend.setup_count == 1
    first = backend.solve()
    second = backend.solve()
    assert first.setup_time > 0.0 and second.setup_time == 0.0  # el setup se atribuye una vez
    assert backend.solve_count == 2
