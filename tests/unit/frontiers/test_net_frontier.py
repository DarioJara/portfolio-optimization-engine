"""FRN-010, FRN-011, FRN-013, TST-009 (contractual B2): Gross y Net Frontier con costes dentro de
la optimización."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.frontiers import ContinuousFrontierEngine, RiskAversionGrid
from portfolio_engine.models.enums import CostTreatment, FrontierMethod, FrontierScope, StrategyID
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    weights_of,
)
from tests.fixtures.reference import two_asset_net_optimum

pytestmark = pytest.mark.unit

SIGMA2 = cov_from_vol_corr([0.20, 0.30], [[1.0, 0.2], [0.2, 1.0]])
MU2 = np.array([0.05, 0.10])
CURRENT2 = [0.7, 0.3]
COSTS2 = {"BuyCost": [100.0, 150.0], "SellCost": [300.0, 450.0], "MaxWeight": [1.0, 1.0]}
UP = 0.01 + 0.045  # c_b1 + c_s2
DOWN = 0.03 + 0.015  # c_s1 + c_b2


def _net_session(config):  # type: ignore[no-untyped-def]
    problem = make_problem(MU2, SIGMA2, CURRENT2, config, universe_overrides=COSTS2)
    return ContinuousFrontierEngine(config).open_session(
        problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )


def test_net_risk_aversion_matches_the_two_asset_analytic_optimum() -> None:
    """FRN-010: el óptimo NET coincide con el análisis por tramos de ``wᵀΣw − θμᵀw + θ·TC``."""
    config = base_config()
    grid = RiskAversionGrid(_net_session(config))
    at_kink, moving = 0, 0
    for theta in (0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 3.0, 8.0, 20.0):
        expected = two_asset_net_optimum(SIGMA2, MU2, theta, 0.7, UP, DOWN, 1.0, 0.0, 1.0)
        point = grid.solve_theta(theta)
        assert weights_of(point) == pytest.approx([expected, 1.0 - expected], abs=1e-6)
        at_kink += abs(expected - 0.7) < 1e-7
        moving += abs(expected - 0.7) > 1e-3
    assert at_kink >= 1 and moving >= 1  # el caso diseñado incluye el nudo y soluciones fuera de él


def test_net_reduces_to_gross_without_costs() -> None:
    config = base_config()
    zero = {"BuyCost": [0.0, 0.0], "SellCost": [0.0, 0.0], "MaxWeight": [1.0, 1.0]}
    problem = make_problem(MU2, SIGMA2, CURRENT2, config, universe_overrides=zero)
    engine = ContinuousFrontierEngine(config)
    gross = engine.solve(problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)
    net = engine.solve(problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)
    for a, b in zip(gross.points, net.points, strict=True):
        assert weights_of(a) == pytest.approx(weights_of(b), abs=1e-6)


def test_higher_costs_reduce_turnover_of_the_net_solution() -> None:
    """Con costes mayores la solución NET se mueve menos que la solución bruta."""
    config = base_config()
    problem = make_problem(MU2, SIGMA2, CURRENT2, config, universe_overrides=COSTS2)
    engine = ContinuousFrontierEngine(config)
    gross = engine.solve(problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)
    net = engine.solve(problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)
    for g, n in zip(gross.points, net.points, strict=True):
        assert (
            g.metrics
            and n.metrics
            and g.metrics.turnover is not None
            and n.metrics.turnover is not None
        )
        if g.strategy_id is StrategyID.FRONTIER_POINT:
            assert n.metrics.turnover <= g.metrics.turnover + 1e-8


def test_gross_frontier() -> None:
    """FRN-013: frontera bruta con extremos, puntos válidos y flags de eficiencia bruta."""
    config = base_config()
    problem = make_problem(
        [0.05, 0.08, 0.12, 0.10],
        cov_from_vol_corr([0.1, 0.15, 0.25, 0.2], np.eye(4) * 0.8 + 0.2),
        [0.4, 0.3, 0.2, 0.1],
        config,
    )
    result = frontier_result(problem, config)
    assert (
        result.cost_treatment is CostTreatment.GROSS
        and result.frontier_type == "CONTINUOUS_FRONTIER:GROSS"
    )
    assert result.scope is FrontierScope.CONTINUOUS_FRONTIER and result.pre_check_feasible
    assert len(result.points) == config.frontier.frontier_points
    assert all(p.is_valid_solution for p in result.points)
    assert all(p.is_gross_efficient for p in result.points if not p.is_duplicate)
    assert result.current_metrics is not None and result.current_metrics.turnover == 0.0
    assert result.current_metrics.transaction_cost == 0.0


def test_net_never_exceeds_gross_on_every_point() -> None:
    """TST-009: con costes positivos ``ExpectedReturnNet <= ExpectedReturnGross`` en toda la
    frontera."""
    config = base_config()
    problem = make_problem(MU2, SIGMA2, CURRENT2, config, universe_overrides=COSTS2)
    for treatment in (CostTreatment.GROSS, CostTreatment.NET, CostTreatment.POST_COST_GROSS):
        for point in frontier_result(problem, config, treatment).valid_points:
            assert point.metrics is not None and point.metrics.expected_return_net is not None
            assert (
                point.metrics.transaction_cost is not None and point.metrics.transaction_cost >= 0.0
            )
            assert point.metrics.expected_return_net <= point.metrics.expected_return_gross + 1e-12


def test_current_portfolio_as_frontier_point_has_zero_cost_and_turnover() -> None:
    """Si los pesos óptimos coinciden con los actuales: turnover 0 y coste 0 (dataset y punto)."""
    config = base_config()
    sigma = np.diag([0.04, 0.09, 0.16])
    optimal = (1 / np.diag(sigma)) / (1 / np.diag(sigma)).sum()
    problem = make_problem(
        [0.05, 0.08, 0.12],
        sigma,
        optimal.tolist(),
        config,
        universe_overrides={
            "MaxWeight": [1.0] * 3,
            "BuyCost": [100.0] * 3,
            "SellCost": [100.0] * 3,
        },
    )
    minimum = frontier_result(problem, config, CostTreatment.NET).points[0]
    assert minimum.metrics is not None
    assert minimum.metrics.turnover == pytest.approx(0.0, abs=1e-7)
    assert minimum.metrics.transaction_cost == pytest.approx(0.0, abs=1e-8)
