"""OPT-007, FRN-006, SOL-002 (H-1 de AUDIT_BLOCK_2): robustez de MaximumReturn con N >= 20.

Los casos ``H1_CASES`` son problemas sintéticos deterministas (mismas semillas que la auditoría)
en los que la versión original fallaba: el LP de la etapa 1 en OSQP terminaba ``MAX_ITERATIONS``
(sin frontera) o la etapa 2 (franja ``R* − 1e-9``) daba ``INFEASIBLE``/``MAX_ITERATIONS`` espurios.
Los valores esperados proceden de ``scipy.optimize.linprog`` escrito aquí, no del motor.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import linprog

from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.frontiers.continuous_frontier import (
    NOTE_DEGENERATE,
    NOTE_MAX_RETURN_FAILED,
    NOTE_MIN_VARIANCE_FAILED,
    FrontierProblem,
)
from portfolio_engine.frontiers.session import (
    NOTE_MAX_RETURN_STAGE_2_FAILED,
    FrontierSession,
)
from portfolio_engine.models.enums import (
    CostTreatment,
    CrossCheckPolicy,
    FrontierMethod,
    SolverStatus,
    StrategyID,
)
from portfolio_engine.optimizers import SolverRouter
from tests.fixtures.problems import (
    base_config,
    frontier_result,
    make_problem,
    point_of,
    synthetic_problem,
    weights_of,
)

pytestmark = pytest.mark.unit

GROSS, NET = CostTreatment.GROSS, CostTreatment.NET
#: (activos, semilla, tratamiento) que fallaban en AUDIT_BLOCK_2 (LP en OSQP o etapa 2 espuria).
H1_CASES = [
    (20, 0, NET),  # LP etapa 1: MAX_ITERATIONS (sin frontera)
    (40, 2, NET),  # LP etapa 1: MAX_ITERATIONS (sin frontera)
    (10, 3, GROSS),  # etapa 2: INFEASIBLE espurio
    (20, 0, GROSS),  # etapa 2: INFEASIBLE espurio
    (40, 0, GROSS),  # etapa 2: INFEASIBLE inaccurate / 250 000 iteraciones
    (10, 4, NET),  # etapa 2: OPTIMAL_INACCURATE tras 250 000 iteraciones
    (20, 2, NET),  # etapa 2: MAX_ITERATIONS
    (20, 4, NET),
]
CASE_IDS = [f"N{n}-seed{seed}-{treatment.value}" for n, seed, treatment in H1_CASES]


def _reference_max_return(
    problem: FrontierProblem, treatment: CostTreatment, horizon: float
) -> tuple[np.ndarray, float]:
    """``max μᵀw [− TC(w)]`` s.a. ``1ᵀw = 1``, ``0 <= w <= 0.25`` con HiGHS (referencia).

    Devuelve un óptimo y el valor óptimo (retorno bruto o neto según ``treatment``).
    """
    mu = np.asarray(problem.risk_model.mu)
    n = mu.shape[0]
    current = np.asarray(problem.state.weights)
    if treatment is GROSS:
        result = linprog(
            -mu, A_eq=np.ones((1, n)), b_eq=[1.0], bounds=[(0.0, 0.25)] * n, method="highs"
        )
        assert result.success
        return np.asarray(result.x), float(-result.fun)
    assert problem.costs is not None
    buy, sell = problem.costs.buy_costs, problem.costs.sell_costs
    cost = np.concatenate([-mu, buy / horizon, sell / horizon])
    ident = np.eye(n)
    a_eq = np.vstack(
        [
            np.hstack([np.ones((1, n)), np.zeros((1, n)), np.zeros((1, n))]),
            np.hstack([ident, -ident, ident]),
        ]
    )
    b_eq = np.concatenate([[1.0], current])
    bounds = [(0.0, 0.25)] * n + [(0.0, None)] * (2 * n)
    result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert result.success
    return np.asarray(result.x[:n]), float(-result.fun)


@pytest.mark.parametrize(("n_assets", "seed", "treatment"), H1_CASES, ids=CASE_IDS)
@pytest.mark.parametrize("method", list(FrontierMethod))
def test_h1_cases_now_produce_a_complete_healthy_frontier(
    n_assets: int, seed: int, treatment: CostTreatment, method: FrontierMethod
) -> None:
    config = base_config()
    problem = synthetic_problem(n_assets, seed, config)
    result = frontier_result(problem, config, treatment, method)
    assert result.notes == (), result.notes
    assert len(result.valid_points) == config.frontier.frontier_points
    best = point_of(result, StrategyID.MAX_RETURN)
    weights = weights_of(best)
    reference, reference_value = _reference_max_return(
        problem, treatment, config.optimization_horizon_years
    )
    assert best.metrics is not None
    achieved = (
        best.metrics.expected_return_gross
        if treatment is GROSS
        else best.metrics.expected_return_net
    )
    assert achieved == pytest.approx(reference_value, abs=1e-8)
    # la etapa 2 nunca empeora la varianza de un óptimo del LP (aquí el óptimo es único)
    sigma = np.asarray(problem.risk_model.sigma)
    assert weights @ sigma @ weights <= reference @ sigma @ reference + 1e-9
    assert weights == pytest.approx(reference, abs=1e-5)


@pytest.mark.parametrize(("n_assets", "seed"), [(20, 0), (40, 2)])
def test_net_target_return_grid_meets_every_net_target(n_assets: int, seed: int) -> None:
    """H-1 con objetivo de retorno neto (costes, cartera actual): cada punto cumple su objetivo."""
    config = base_config()
    problem = synthetic_problem(n_assets, seed, config)
    result = frontier_result(problem, config, NET, FrontierMethod.TARGET_RETURN_GRID)
    assert result.notes == () and len(result.valid_points) == config.frontier.frontier_points
    targeted = [p for p in result.points if p.target_return is not None]
    assert len(targeted) >= config.frontier.frontier_points - 2
    for point in targeted:
        assert point.metrics is not None and point.metrics.expected_return_net is not None
        assert point.metrics.expected_return_net >= point.target_return - 1e-7  # type: ignore[operator]


def test_lp_goes_to_highs_and_qps_to_osqp(monkeypatch: pytest.MonkeyPatch) -> None:
    """R2-01: ningún LP con ``P = 0`` se resuelve con OSQP; los QP sí."""
    routed: list[tuple[str, str]] = []
    original = SolverRouter.route

    def spy(self: SolverRouter, problem):  # type: ignore[no-untyped-def]
        backend = original(self, problem)
        routed.append((problem.problem_class.value, backend.name))
        return backend

    monkeypatch.setattr(SolverRouter, "route", spy)
    config = base_config()
    frontier_result(synthetic_problem(20, 0, config), config, NET)
    assert ("LP", "HiGHS") in routed and ("LP", "OSQP") not in routed
    assert {name for cls, name in routed if cls == "QP"} == {"OSQP"}


def test_tie_break_at_n20_selects_the_minimum_variance_face_point() -> None:
    """A-14 con 20 activos: 4 activos empatados en el máximo retorno; la etapa 2 reparte por
    varianza inversa (fórmula cerrada) y descarta el resto."""
    n = 20
    mu = np.linspace(0.02, 0.06, n)
    mu[:4] = 0.10
    variances = np.linspace(0.02, 0.09, n)
    variances[:4] = [0.02, 0.04, 0.06, 0.08]
    config = base_config()
    problem = make_problem(
        mu, np.diag(variances), [1.0 / n] * n, config, universe_overrides={"MaxWeight": [1.0] * n}
    )
    point = point_of(frontier_result(problem, config), StrategyID.MAX_RETURN)
    inverse = 1.0 / variances[:4]
    expected = np.zeros(n)
    expected[:4] = inverse / inverse.sum()
    assert weights_of(point) == pytest.approx(expected, abs=1e-6)
    assert point.metrics is not None and point.metrics.expected_return_gross == pytest.approx(0.10)


def test_stage_two_target_is_the_configured_tolerance_below_the_lp_optimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La holgura de la etapa 2 es ``max(abs, rel·|R*|)`` de ``SolverConfig`` (fuente única)."""
    config = base_config()
    problem = synthetic_problem(20, 1, config)
    recorded: list[float] = []
    original = FrontierSession._solve_on_optimal_face

    def spy(self: FrontierSession, target: float, duals):  # type: ignore[no-untyped-def]
        recorded.append(target)
        return original(self, target, duals)

    monkeypatch.setattr(FrontierSession, "_solve_on_optimal_face", spy)
    for treatment in (GROSS, NET):
        recorded.clear()
        session = ContinuousFrontierEngine(config).open_session(
            problem, treatment, FrontierMethod.RISK_AVERSION_GRID
        )
        session.solve_maximum_return()
        _, best = _reference_max_return(problem, treatment, config.optimization_horizon_years)
        tolerance = config.solver.max_return_tie_tolerance(best)
        assert recorded == [pytest.approx(best - tolerance, abs=1e-9)]


# ------------------------------------------------------------------- caminos de degradación


def test_stage_one_failure_is_reported_and_the_grid_is_skipped() -> None:
    """LP de la etapa 1 sin resolver (límite de iteraciones): ``NOTE_MAX_RETURN_FAILED``, sin
    malla, con el estado real del solver y sin presentarlo como inviabilidad."""
    config = base_config(
        solver={"lp_max_iterations": 1, "ambiguous_status_policy": CrossCheckPolicy.NONE}
    )
    problem = synthetic_problem(20, 0, config)
    result = frontier_result(problem, config, NET)
    assert NOTE_MAX_RETURN_FAILED in result.notes
    assert len(result.points) == 2 and len(result.valid_points) == 1
    failed = result.points[-1]
    assert not failed.is_valid_solution and failed.status is SolverStatus.MAX_ITERATIONS
    assert failed.solve is not None and failed.solve.solver_name == "HiGHS"


def test_stage_two_failure_returns_the_valid_stage_one_solution_with_a_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Etapa 2 sin solución válida (objetivo imposible, ``INFEASIBLE`` real de OSQP): se devuelve
    el óptimo de la etapa 1 (válido) con nota explícita y la frontera sigue completa."""
    original = FrontierSession._solve_on_optimal_face

    def impossible(self: FrontierSession, target: float, duals):  # type: ignore[no-untyped-def]
        return original(self, target + 1.0, duals)

    monkeypatch.setattr(FrontierSession, "_solve_on_optimal_face", impossible)
    config = base_config()
    problem = synthetic_problem(20, 3, config)
    result = frontier_result(problem, config, GROSS)
    assert result.notes == (NOTE_MAX_RETURN_STAGE_2_FAILED,)
    assert len(result.valid_points) == config.frontier.frontier_points
    best = point_of(result, StrategyID.MAX_RETURN)
    assert best.is_valid_solution and best.solve is not None
    assert best.solve.solver_name == "HiGHS"  # es la solución de la etapa 1
    _, reference_value = _reference_max_return(problem, GROSS, config.optimization_horizon_years)
    assert best.metrics is not None
    assert best.metrics.expected_return_gross == pytest.approx(reference_value, abs=1e-8)


def test_minimum_variance_failure_skips_the_grid() -> None:
    config = base_config(
        solver={"max_iterations": 1, "ambiguous_status_policy": CrossCheckPolicy.NONE}
    )
    result = frontier_result(synthetic_problem(20, 0, config), config, GROSS)
    assert result.notes == (NOTE_MIN_VARIANCE_FAILED,) and len(result.points) == 1
    assert not result.points[0].is_valid_solution


def test_degenerate_frontier_when_all_expected_returns_are_equal() -> None:
    """Óptimo del LP = todo el conjunto factible (retornos iguales): la etapa 2 elige la mínima
    varianza y la frontera es un único punto, señalado con ``NOTE_DEGENERATE``."""
    config = base_config()
    sigma = np.diag([0.04, 0.09, 0.02, 0.05])
    problem = make_problem(
        np.full(4, 0.08), sigma, [0.25] * 4, config, universe_overrides={"MaxWeight": [1.0] * 4}
    )
    result = frontier_result(problem, config)
    assert NOTE_DEGENERATE in result.notes
    best = point_of(result, StrategyID.MAX_RETURN)
    inverse = 1.0 / np.diag(sigma)
    assert weights_of(best) == pytest.approx(inverse / inverse.sum(), abs=1e-6)
