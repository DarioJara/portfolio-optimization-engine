"""DAT-012, DAT-013 (nivel global), DAT-016: estado actual, índice global y hash de estado."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from portfolio_engine.exceptions import AssetResolutionError, DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.portfolio import (
    CurrentPortfolioState,
    composition_hash,
    current_portfolio_state_hash,
)
from portfolio_engine.models.universe_index import AssetIndex

pytestmark = pytest.mark.unit


@pytest.fixture()
def index(universe: Universe) -> AssetIndex:
    return AssetIndex.from_universe(universe)


def test_asset_index_round_trip(index: AssetIndex) -> None:
    assert len(index) == 6
    for position, asset_id in enumerate(index.asset_ids):
        assert index.index_of(asset_id) == position
        assert index.asset_id_at(position) == asset_id
    positions = index.indices_of(["A004", "A001"])
    np.testing.assert_array_equal(positions, [4, 1])
    assert not positions.flags.writeable
    with pytest.raises(AssetResolutionError):
        index.index_of("NOPE")


def test_asset_index_requires_sorted_unique_ids() -> None:
    with pytest.raises(DataValidationError):
        AssetIndex(["B", "A"])
    with pytest.raises(DataValidationError):
        AssetIndex(["A", "A"])


def test_state_preserves_composition_and_weights(index: AssetIndex) -> None:
    state = CurrentPortfolioState.from_weights("P1", {"A003": 0.3, "A001": 0.7}, index, 5e6)
    assert state.has_current_portfolio
    assert state.asset_ids == ("A001", "A003")
    np.testing.assert_array_equal(state.weights, [0.7, 0.3])
    np.testing.assert_array_equal(state.global_indices, [1, 3])
    assert state.weight_of("A003") == 0.3
    assert state.weight_of("A000") == 0.0
    assert state.total_weight == pytest.approx(1.0)
    composition = state.composition()
    assert composition.asset_ids == frozenset({"A001", "A003"})
    assert composition.composition_hash == composition_hash(frozenset({"A003", "A001"}))


def test_state_arrays_are_read_only(index: AssetIndex) -> None:
    state = CurrentPortfolioState.from_weights("P1", {"A001": 1.0}, index, None)
    with pytest.raises(ValueError):
        state.weights[0] = 0.5
    with pytest.raises(ValueError):
        state.global_indices[0] = 2


def test_empty_state(index: AssetIndex) -> None:
    state = CurrentPortfolioState.from_weights("P0", {}, index, None)
    assert not state.has_current_portfolio
    assert state.total_weight == 0.0


@pytest.mark.parametrize("weights", [{"A001": 0.0}, {"A001": float("nan")}])
def test_state_rejects_zero_or_non_finite_weights(
    index: AssetIndex, weights: dict[str, float]
) -> None:
    with pytest.raises(DataValidationError):
        CurrentPortfolioState.from_weights("P1", weights, index, None)


def test_state_hash_depends_only_on_asset_weight_pairs(index: AssetIndex) -> None:
    a = CurrentPortfolioState.from_weights("P1", {"A001": 0.7, "A003": 0.3}, index, None)
    b = CurrentPortfolioState.from_weights("P2", {"A003": 0.3, "A001": 0.7}, index, 1e6)
    assert a.state_hash == b.state_hash
    assert a.state_hash == current_portfolio_state_hash({"A003": 0.3, "A001": 0.7})


def test_state_hash_changes_with_any_weight_change(index: AssetIndex) -> None:
    base = {"A001": 0.7, "A003": 0.3}
    reference = current_portfolio_state_hash(base)
    nudged = {"A001": float(np.nextafter(0.7, 1.0)), "A003": 0.3}
    assert current_portfolio_state_hash(nudged) != reference
    swapped = {"A001": 0.3, "A003": 0.7}
    assert current_portfolio_state_hash(swapped) != reference
    other_asset = {"A002": 0.7, "A003": 0.3}
    assert current_portfolio_state_hash(other_asset) != reference


def test_state_hash_normalizes_zero_rows_and_negative_zero() -> None:
    assert current_portfolio_state_hash({"A": 1.0, "B": 0.0}) == current_portfolio_state_hash(
        {"A": 1.0, "B": -0.0}
    )
    assert current_portfolio_state_hash({"A": 1.0, "B": 0.0}) == current_portfolio_state_hash(
        {"A": 1.0}
    )


def test_state_hash_matches_documented_canonical_form() -> None:
    """E-06: SHA-256 de los pares (AssetID, float.hex(peso)) ordenados, recalculado aparte.

    No usa ``hash()`` de Python, por lo que es estable entre procesos.
    """
    canonical = (
        '{"CurrentPortfolioState":[["A","0x1.0000000000000p-1"],["B","0x1.8000000000000p-2"]]}'
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert current_portfolio_state_hash({"B": 0.375, "A": 0.5}) == expected
