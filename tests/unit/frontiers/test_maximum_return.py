"""OPT-007 (contractual B2): Maximum Return lexicográfico frente a soluciones cerradas."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.models.enums import CostTreatment, FrontierMethod, StrategyID
from tests.fixtures.problems import (
    base_config,
    frontier_result,
    make_problem,
    point_of,
    weights_of,
)
from tests.fixtures.reference import max_net_return_lp, max_return_box_budget

pytestmark = pytest.mark.unit

SIGMA = np.diag([0.04, 0.09, 0.02, 0.05])
MU = np.array([0.05, 0.08, 0.12, 0.10])


def test_box_and_budget_closed_form() -> None:
    """Retorno máximo con caja y presupuesto: llenado voraz por retorno (activos 3 y 4 al tope)."""
    config = base_config()
    caps = np.array([0.5, 0.5, 0.45, 0.5])
    problem = make_problem(
        MU, SIGMA, [0.25] * 4, config, universe_overrides={"MaxWeight": caps.tolist()}
    )
    point = point_of(frontier_result(problem, config), StrategyID.MAX_RETURN)
    expected = max_return_box_budget(MU, np.zeros(4), caps)
    assert expected.tolist() == pytest.approx([0.0, 0.05, 0.45, 0.5])
    assert weights_of(point) == pytest.approx(expected, abs=1e-7)
    assert point.metrics is not None
    assert point.metrics.expected_return_gross == pytest.approx(float(MU @ expected), abs=1e-9)


def test_lower_bounds_shift_the_greedy_solution() -> None:
    config = base_config()
    lower = np.array([0.1, 0.1, 0.0, 0.0])
    upper = np.array([0.6, 0.6, 0.6, 0.6])
    problem = make_problem(
        MU,
        SIGMA,
        [0.25] * 4,
        config,
        universe_overrides={"MinWeight": lower.tolist(), "MaxWeight": upper.tolist()},
    )
    point = point_of(frontier_result(problem, config), StrategyID.MAX_RETURN)
    assert weights_of(point) == pytest.approx(max_return_box_budget(MU, lower, upper), abs=1e-7)


def test_ties_are_broken_by_minimum_variance() -> None:
    """A-14: con retornos iguales (óptimo múltiple) la segunda etapa elige la mínima varianza."""
    config = base_config()
    mu = np.array([0.10, 0.10, 0.05])
    variances = np.array([0.04, 0.09, 0.01])
    problem = make_problem(
        mu, np.diag(variances), [0.3, 0.3, 0.4], config, universe_overrides={"MaxWeight": [1.0] * 3}
    )
    point = point_of(frontier_result(problem, config), StrategyID.MAX_RETURN)
    inverse = 1.0 / variances[:2]
    expected = np.append(inverse / inverse.sum(), 0.0)  # reparto de mínima varianza entre empatados
    assert weights_of(point) == pytest.approx(expected, abs=1e-6)
    assert point.metrics is not None and point.metrics.expected_return_gross == pytest.approx(0.10)


def test_maximum_return_is_the_highest_return_of_every_frontier() -> None:
    config = base_config()
    problem = make_problem(
        MU, SIGMA, [0.25] * 4, config, universe_overrides={"MaxWeight": [0.6] * 4}
    )
    for method in FrontierMethod:
        result = frontier_result(problem, config, method=method)
        best = point_of(result, StrategyID.MAX_RETURN).metrics
        assert best is not None and result.points[-1].strategy_id is StrategyID.MAX_RETURN
        assert all(
            p.metrics is not None
            and p.metrics.expected_return_gross <= best.expected_return_gross + 1e-9
            for p in result.valid_points
        )


def test_net_maximum_return_accounts_for_costs() -> None:
    """MaxReturn neto: ``max μᵀw − TC(w)``; con costes altos el óptimo se queda cerca de la
    cartera actual."""
    config = base_config()
    costs = {"BuyCost": [400.0] * 4, "SellCost": [400.0] * 4}
    problem = make_problem(
        MU,
        SIGMA,
        [0.5, 0.5, 0.0, 0.0],
        config,
        universe_overrides={"MaxWeight": [1.0] * 4, **costs},
    )
    gross = point_of(frontier_result(problem, config), StrategyID.MAX_RETURN)
    net = point_of(frontier_result(problem, config, CostTreatment.NET), StrategyID.MAX_RETURN)
    assert gross.metrics is not None and net.metrics is not None
    assert (
        net.metrics.expected_return_net is not None
        and gross.metrics.expected_return_net is not None
    )
    # el óptimo neto tiene mayor retorno neto y menor turnover que el óptimo bruto evaluado ex post
    assert net.metrics.expected_return_net >= gross.metrics.expected_return_net - 1e-9
    assert net.metrics.turnover is not None and gross.metrics.turnover is not None
    assert net.metrics.turnover < gross.metrics.turnover
    exact = max_net_return_lp(
        MU,
        np.array([0.5, 0.5, 0.0, 0.0]),
        np.full(4, 0.04),
        np.full(4, 0.04),
        np.zeros(4),
        np.ones(4),
    )
    assert net.metrics.expected_return_net == pytest.approx(exact, abs=1e-8)
