"""TC-001..TC-004, TC-009, TC-012: costes asimétricos sobre la unión current ∪ composición."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.costs import TransactionCostModel, align_union, to_return_units, turnover
from portfolio_engine.exceptions import TransactionCostInputError
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import CostSource
from portfolio_engine.models.portfolio import CurrentPortfolioState
from portfolio_engine.models.universe_index import AssetIndex

pytestmark = pytest.mark.unit

IDS = ("A", "B", "C", "D")


def _state(weights: dict[str, float]) -> CurrentPortfolioState:
    return CurrentPortfolioState.from_weights("P", weights, AssetIndex(IDS), None)


def _costs(buy: list[float], sell: list[float]) -> AssetCostVector:
    return AssetCostVector(IDS, np.array(buy), np.array(sell), (CostSource.BUY_SELL,) * len(IDS))


def test_union_alignment() -> None:
    """TC-001: la unión ordenada contiene los activos actuales y los nuevos; 0 fuera de la
    actual."""
    alignment = align_union(_state({"A": 0.4, "B": 0.6}), ("B", "C"))
    assert alignment.asset_ids == ("A", "B", "C")
    assert alignment.current_weights.tolist() == [0.4, 0.6, 0.0]
    assert alignment.composition_positions.tolist() == [1, 2]
    assert alignment.exited_asset_ids() == ("A",)
    assert alignment.expand(np.array([0.7, 0.3])).tolist() == [0.0, 0.7, 0.3]


def test_manual_values() -> None:
    """TC-002: coste asimétrico calculado a mano (compra 10 bps, venta 30 bps)."""
    model = TransactionCostModel(
        align_union(_state({"A": 0.5, "B": 0.5}), ("A", "B")),
        _costs([0.001, 0.002, 0.0, 0.0], [0.003, 0.004, 0.0, 0.0]),
        horizon_years=1.0,
    )
    # A: 0.5 → 0.3 (venta 0.2 · 0.003); B: 0.5 → 0.7 (compra 0.2 · 0.002)
    expected = 0.2 * 0.003 + 0.2 * 0.002
    assert model.cost_one_off(np.array([0.3, 0.7])) == pytest.approx(expected, abs=1e-15)
    assert model.asset_costs_one_off(np.array([0.3, 0.7])).tolist() == pytest.approx(
        [0.2 * 0.003, 0.2 * 0.002]
    )


def test_exited_assets_included() -> None:
    """TC-003/TC-004: un activo actual ausente de la composición se vende por completo."""
    alignment = align_union(_state({"A": 0.10, "B": 0.90}), ("B", "C"))
    model = TransactionCostModel(
        alignment, _costs([0.001, 0.0, 0.002, 0.0], [0.005, 0.0, 0.0, 0.0]), horizon_years=1.0
    )
    weights = np.array([0.90, 0.10])  # B = 0.90, C = 0.10 (nuevo)
    # venta completa de A: 0.10 · 0.005; compra de C: 0.10 · 0.002; B sin cambios
    assert model.cost_one_off(weights) == pytest.approx(0.10 * 0.005 + 0.10 * 0.002, abs=1e-15)
    assert model.turnover(weights) == pytest.approx(0.10, abs=1e-15)
    assert alignment.exited_asset_ids() == ("A",)
    assert model.cost_one_off(weights) > 0.0


def test_cost_is_not_computed_only_on_new_composition() -> None:
    """Regresión: ignorar los activos que salen subestimaría el coste."""
    alignment = align_union(_state({"A": 0.5, "B": 0.5}), ("B", "C"))
    model = TransactionCostModel(
        alignment, _costs([0.0, 0.0, 0.0, 0.0], [0.01, 0.0, 0.0, 0.0]), 1.0
    )
    assert model.cost_one_off(np.array([1.0, 0.0])) == pytest.approx(0.5 * 0.01)


def test_horizon_units() -> None:
    """TC-009: ``TransactionCost = TransactionCostOneOff / H`` para varios horizontes."""
    alignment = align_union(_state({"A": 1.0}), ("A", "B"))
    costs = _costs([0.0, 0.004, 0.0, 0.0], [0.002, 0.0, 0.0, 0.0])
    weights = np.array([0.6, 0.4])
    one_off = 0.4 * 0.002 + 0.4 * 0.004
    for horizon in (0.5, 1.0, 2.0, 5.0):
        model = TransactionCostModel(alignment, costs, horizon_years=horizon)
        assert model.cost_one_off(weights) == pytest.approx(one_off)
        assert model.cost(weights) == pytest.approx(one_off / horizon)
    assert to_return_units(0.01, 4.0) == pytest.approx(0.0025)


def test_asset_costs_sum_to_total() -> None:
    """TC-012: los costes por activo suman el coste total, para cada fila."""
    alignment = align_union(_state({"A": 0.25, "B": 0.25, "C": 0.5}), ("A", "B", "C"))
    model = TransactionCostModel(
        alignment, _costs([0.001, 0.002, 0.003, 0.0], [0.004, 0.005, 0.006, 0.0]), 2.0
    )
    grid = np.array([[0.1, 0.3, 0.6], [0.5, 0.25, 0.25], [0.25, 0.25, 0.5]])
    per_asset = model.asset_costs_one_off(grid)
    assert per_asset.shape == (3, 3)
    assert per_asset.sum(axis=1) == pytest.approx(model.cost_one_off(grid))
    assert per_asset[2].tolist() == [0.0, 0.0, 0.0]


def test_zero_weights_change_costs_nothing() -> None:
    model = TransactionCostModel(
        align_union(_state({"A": 0.5, "B": 0.5}), ("A", "B")),
        _costs([0.01] * 4, [0.01] * 4),
        1.0,
    )
    assert model.cost_one_off(np.array([0.5, 0.5])) == 0.0
    assert model.turnover(np.array([0.5, 0.5])) == 0.0


def test_no_current_portfolio_has_no_cost_model() -> None:
    """TC-007: sin cartera actual el coste no está disponible (no se inventa)."""
    empty = CurrentPortfolioState.from_weights("P", {}, AssetIndex(IDS), None)
    alignment = align_union(empty, ("A", "B"))
    assert not alignment.has_current_portfolio
    with pytest.raises(TransactionCostInputError, match="no está disponible"):
        TransactionCostModel(alignment, _costs([0.0] * 4, [0.0] * 4), 1.0)


def test_missing_cost_data_and_bad_inputs_are_errors() -> None:
    state = _state({"A": 1.0})
    partial = AssetCostVector(("A",), np.array([0.0]), np.array([0.0]), (CostSource.BUY_SELL,))
    with pytest.raises(TransactionCostInputError, match="sin coste"):
        TransactionCostModel(align_union(state, ("A", "B")), partial, 1.0)
    with pytest.raises(TransactionCostInputError, match="horizonte"):
        TransactionCostModel(align_union(state, ("A",)), partial, 0.0)
    with pytest.raises(TransactionCostInputError, match="repetidos"):
        align_union(state, ("A", "A"))


def test_turnover_function_convention() -> None:
    """TC-006: ``0.5·Σ|Δw|``; sustitución total = 1; sin cambios = 0."""
    current = np.array([0.5, 0.5, 0.0, 0.0])
    assert turnover(np.array([0.0, 0.0, 0.5, 0.5]), current) == pytest.approx(1.0)
    assert turnover(current, current) == 0.0
    grid = np.array([[0.5, 0.25, 0.25, 0.0], [0.25, 0.25, 0.25, 0.25]])
    assert turnover(grid, current).tolist() == pytest.approx([0.25, 0.5])
