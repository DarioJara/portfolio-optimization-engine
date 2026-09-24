"""TST-006..009: invariantes financieros de toda solución de la frontera continua (Hypothesis)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from tests.fixtures.problems import base_config, make_problem

pytestmark = pytest.mark.property

PROFILE = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
CONFIG = base_config()
ENGINE = ContinuousFrontierEngine(CONFIG)


@st.composite
def frontier_problems(draw):  # type: ignore[no-untyped-def]
    n = draw(st.integers(min_value=2, max_value=5))
    seed = draw(st.integers(min_value=0, max_value=10_000))
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, n)) * 0.1
    sigma = factor @ factor.T + np.diag(rng.uniform(0.01, 0.05, n))
    mu = rng.uniform(0.02, 0.15, n)
    raw = rng.uniform(0.05, 1.0, n)
    current = (raw / raw.sum()).tolist()
    buy = rng.uniform(1.0, 200.0, n).tolist()
    sell = rng.uniform(1.0, 200.0, n).tolist()
    return make_problem(
        mu,
        sigma,
        current,
        CONFIG,
        universe_overrides={"MaxWeight": [1.0] * n, "BuyCost": buy, "SellCost": sell},
    )


@PROFILE
@given(
    problem=frontier_problems(),
    treatment=st.sampled_from(list(CostTreatment)),
    method=st.sampled_from(list(FrontierMethod)),
)
def test_every_frontier_point_satisfies_the_financial_invariants(
    problem, treatment, method
) -> None:  # type: ignore[no-untyped-def]
    """Σw ≈ 1 (TST-006), Vol ≥ 0 (TST-007), TC ≥ 0 (TST-008) y Net ≤ Gross con costes > 0
    (TST-009)."""
    result = ENGINE.solve(problem, treatment, method)
    assert result.pre_check_feasible and result.points
    for point in result.points:
        assert point.is_valid_solution, (point.status, point.validation)
        assert point.weights is not None and point.metrics is not None
        assert point.weights.sum() == pytest.approx(1.0, abs=1e-6)
        assert point.weights.min() >= -1e-6
        assert point.metrics.volatility >= 0.0
        assert point.metrics.transaction_cost is not None and point.metrics.transaction_cost >= 0.0
        assert point.metrics.expected_return_net is not None
        assert point.metrics.expected_return_net <= point.metrics.expected_return_gross + 1e-12
        assert point.metrics.turnover is not None and 0.0 <= point.metrics.turnover <= 1.0 + 1e-9


@PROFILE
@given(problem=frontier_problems())
def test_the_net_frontier_never_has_lower_net_return_than_the_gross_frontier_at_the_extremes(
    problem,
) -> None:  # type: ignore[no-untyped-def]
    """El retorno neto máximo de la frontera NET es ≥ el neto del MaxReturn bruto (costes en la
    optimización)."""
    gross = ENGINE.solve(problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)
    net = ENGINE.solve(problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)
    best_net = net.points[-1].metrics
    gross_end = gross.points[-1].metrics
    assert (
        best_net
        and gross_end
        and best_net.expected_return_net is not None
        and gross_end.expected_return_net is not None
    )
    assert best_net.expected_return_net >= gross_end.expected_return_net - 1e-7
