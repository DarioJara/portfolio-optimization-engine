"""TC-005: modelo de datos y validación de inputs de costes de transacción (obligatorio B1)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.data.validation import IssueCode, UniverseValidator, resolve_asset_costs
from portfolio_engine.exceptions import TransactionCostInputError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import CostInputUnit, CostSource
from tests.fixtures.synthetic import replace_section, universe_frame

pytestmark = pytest.mark.unit


def _universe(config: EngineConfig, **columns: list[object]) -> Universe:
    return UniverseValidator(config.constraints).validate(universe_frame(4, **columns)).universe


def test_buy_sell_in_bps_converted_to_decimal(config: EngineConfig) -> None:
    resolution = resolve_asset_costs(_universe(config), config.transaction_costs)
    costs = resolution.require_complete()
    np.testing.assert_array_equal(costs.buy_costs, np.full(4, 5.0 / 10_000))
    np.testing.assert_array_equal(costs.sell_costs, np.full(4, 7.0 / 10_000))
    assert costs.sources == (CostSource.BUY_SELL,) * 4
    assert costs.costs_of("A002") == (0.0005, 0.0007)


def test_decimal_input_unit_is_not_rescaled(config: EngineConfig) -> None:
    tc = replace_section(
        config, "transaction_costs", input_unit=CostInputUnit.DECIMAL
    ).transaction_costs
    universe = _universe(config, BuyCost=[0.001] * 4, SellCost=[0.002] * 4)
    costs = resolve_asset_costs(universe, tc).require_complete()
    np.testing.assert_array_equal(costs.buy_costs, np.full(4, 0.001))


def test_precedence_falls_back_per_asset(config: EngineConfig) -> None:
    universe = _universe(
        config,
        BuyCost=[5.0, None, None, None],
        SellCost=[7.0, None, None, None],
        EstimatedTransactionCost=[10.0, 12.0, None, None],
        BidAskSpread=[4.0, 4.0, 6.0, None],
    )
    tc = replace_section(config, "transaction_costs", spread_commission=0.0001).transaction_costs
    resolution = resolve_asset_costs(universe, tc)
    costs = resolution.costs
    assert costs.asset_ids == ("A000", "A001", "A002")
    assert costs.sources == (CostSource.BUY_SELL, CostSource.ESTIMATED, CostSource.BID_ASK_SPREAD)
    assert costs.costs_of("A001") == (0.0012, 0.0012)
    half_spread = 6.0 / 10_000 / 2
    assert costs.costs_of("A002") == pytest.approx((half_spread + 0.0001,) * 2, abs=0, rel=1e-15)
    assert resolution.missing_asset_ids == ("A003",)
    with pytest.raises(TransactionCostInputError, match="A003"):
        resolution.require_complete()  # nunca se asume coste cero


def test_custom_precedence_order_is_respected(config: EngineConfig) -> None:
    tc = replace_section(
        config,
        "transaction_costs",
        source_precedence=(CostSource.ESTIMATED, CostSource.BUY_SELL),
    ).transaction_costs
    costs = resolve_asset_costs(_universe(config), tc).require_complete()
    assert costs.sources == (CostSource.ESTIMATED,) * 4
    np.testing.assert_array_equal(costs.buy_costs, np.full(4, 0.001))


def test_incomplete_buy_sell_pair_warns_and_falls_through(config: EngineConfig) -> None:
    universe = _universe(config, SellCost=[None, 7.0, 7.0, 7.0])
    resolution = resolve_asset_costs(universe, config.transaction_costs)
    assert resolution.costs.sources[0] is CostSource.ESTIMATED
    assert [i.asset_id for i in resolution.report.issues_for(IssueCode.MISSING_METADATA)] == [
        "A000"
    ]


def test_implausible_cost_is_rejected_as_unit_error(config: EngineConfig) -> None:
    universe = _universe(config, BuyCost=[5.0, 5.0, 5.0, 600.0])  # 600 bps = 6 % > 5 %
    with pytest.raises(TransactionCostInputError) as error:
        resolve_asset_costs(universe, config.transaction_costs)
    assert [issue.asset_id for issue in error.value.issues] == ["A003"]  # type: ignore[attr-defined]


def test_subset_resolution(config: EngineConfig) -> None:
    costs = resolve_asset_costs(_universe(config), config.transaction_costs, ["A003", "A001"])
    assert costs.costs.asset_ids == ("A001", "A003")


@pytest.mark.parametrize(
    ("buy", "sell"),
    [([-0.1], [0.1]), ([math.nan], [0.1]), ([0.1], [math.inf])],
)
def test_cost_vector_rejects_invalid_values(buy: list[float], sell: list[float]) -> None:
    with pytest.raises(TransactionCostInputError):
        AssetCostVector(("A",), np.array(buy), np.array(sell), (CostSource.BUY_SELL,))


def test_cost_vector_is_read_only() -> None:
    vector = AssetCostVector(("A",), np.array([0.1]), np.array([0.2]), (CostSource.BUY_SELL,))
    with pytest.raises(ValueError):
        vector.buy_costs[0] = 0.0


def test_cost_vector_requires_one_source_per_asset() -> None:
    with pytest.raises(TransactionCostInputError, match="fuente"):
        AssetCostVector(("A", "B"), np.zeros(2), np.zeros(2), (CostSource.BUY_SELL,))
