"""CON-006..009, CON-013, CON-014: cada dimensión de grupo, restringido nuevo y activo de caja."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.config import GroupLimit
from portfolio_engine.models.enums import (
    CostTreatment,
    GroupDimension,
    RestrictedExistingPositionPolicy,
    StrategyID,
)
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    point_of,
    policy_config,
    restricted_universe,
    weights_of,
    with_group_limits,
)

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = cov_from_vol_corr(
    [0.10, 0.15, 0.25, 0.20],
    [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
)
CURRENT = [0.4, 0.3, 0.2, 0.1]
ATTRIBUTES = {
    GroupDimension.SECTOR: ("Sector", ["S1", "S2", "S1", "S2"]),
    GroupDimension.COUNTRY: ("Country", ["ES", "ES", "FR", "FR"]),
    GroupDimension.ASSET_CLASS: ("AssetClass", ["Equity", "Bond", "Equity", "Bond"]),
    GroupDimension.CURRENCY: ("Currency", ["EUR", "USD", "EUR", "USD"]),
}


@pytest.mark.parametrize("dimension", list(GroupDimension))
def test_group_limits_bind_on_every_dimension(dimension: GroupDimension) -> None:
    """Un máximo y un mínimo sobre cada dimensión se cumplen y el máximo ata en la frontera."""
    column, values = ATTRIBUTES[dimension]
    first, second = values[0], values[3]
    config = with_group_limits(
        base_config(),
        [GroupLimit(dimension, first, None, 0.35), GroupLimit(dimension, second, 0.4, None)],
    )
    problem = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4, column: values}
    )
    result = frontier_result(problem, config)
    assert all(p.is_valid_solution for p in result.points)
    members_first = [i for i, v in enumerate(values) if v == first]
    members_second = [i for i, v in enumerate(values) if v == second]
    totals = [
        (weights_of(p)[members_first].sum(), weights_of(p)[members_second].sum())
        for p in result.points
    ]
    assert all(a <= 0.35 + 1e-7 and b >= 0.4 - 1e-7 for a, b in totals)
    assert any(abs(a - 0.35) < 1e-6 for a, _ in totals)  # el máximo ata en algún punto


def test_new_restricted_asset_gets_zero_weight_everywhere() -> None:
    """CON-013: un restringido de la composición que no está en la cartera nunca se compra."""
    config = policy_config(base_config(), RestrictedExistingPositionPolicy.HOLD_OR_REDUCE)
    problem = make_problem(
        MU,
        SIGMA,
        [0.5, 0.3, 0.2, 0.0],
        config,
        universe_overrides=restricted_universe(4, [3], MaxWeight=[0.6] * 4),
        composition=("A000", "A001", "A002", "A003"),
    )
    for treatment in (CostTreatment.GROSS,):
        result = frontier_result(problem, config, treatment)
        assert all(p.is_valid_solution for p in result.points)
        assert all(abs(weights_of(p)[3]) <= 1e-7 for p in result.points)
    # el activo restringido tiene el mayor retorno atractivo en MaxReturn de otro modo
    unrestricted = make_problem(
        MU,
        SIGMA,
        [0.5, 0.3, 0.2, 0.0],
        config,
        universe_overrides={"MaxWeight": [0.6] * 4},
        composition=("A000", "A001", "A002", "A003"),
    )
    free = weights_of(point_of(frontier_result(unrestricted, config), StrategyID.MAX_RETURN))
    assert free[3] > 0.1


def test_cash_like_asset_with_zero_variance_is_an_ordinary_frontier_asset() -> None:
    """CON-014: caja como activo de retorno ``rf`` y varianzas nulas (Σ singular PSD)."""
    config = base_config()
    risk_free = config.returns.risk_free_rate
    sigma = np.zeros((4, 4))
    sigma[:3, :3] = SIGMA[:3, :3]
    mu = np.array([0.06, 0.09, 0.13, risk_free])
    problem = make_problem(
        mu,
        sigma,
        [0.3, 0.3, 0.2, 0.2],
        config,
        universe_overrides={"MaxWeight": [0.6] * 3 + [0.35]},
    )
    result = frontier_result(problem, config)
    assert all(p.is_valid_solution for p in result.points)
    minimum = weights_of(point_of(result, StrategyID.MIN_VARIANCE))
    assert minimum[3] == pytest.approx(0.35, abs=1e-7)  # la caja (varianza 0) topa en su límite
    assert point_of(result, StrategyID.MIN_VARIANCE).metrics is not None
    assert all(
        w.sum() == pytest.approx(1.0, abs=1e-7) for w in (weights_of(p) for p in result.points)
    )
