"""TST-016 y propiedades del Bloque 3 (Hypothesis): venta de activos retirados, hash de
composición, proyección sobre cotas, vecindarios sin duplicados y rangos del screening."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from portfolio_engine.candidates import (
    Shortlist,
    SwapGenerator,
    average_rank_percentile,
    composition_hash_of,
    project_box_budget,
)
from portfolio_engine.costs import TransactionCostModel, align_union
from portfolio_engine.data.validation import resolve_asset_costs
from portfolio_engine.models.portfolio import CurrentPortfolioState
from portfolio_engine.models.universe_index import AssetIndex
from tests.fixtures.candidates import with_candidates
from tests.fixtures.problems import base_config, build_universe

pytestmark = pytest.mark.property

SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
CONFIG = base_config()


@st.composite
def _liquidation_case(draw):  # type: ignore[no-untyped-def]
    n = draw(st.integers(3, 8))
    held_count = draw(st.integers(2, n - 1))
    shares = draw(st.lists(st.floats(0.05, 1.0), min_size=held_count, max_size=held_count))
    weights = np.array(shares) / sum(shares)
    buy = draw(st.lists(st.floats(1.0, 80.0), min_size=n, max_size=n))
    sell = draw(st.lists(st.floats(1.0, 80.0), min_size=n, max_size=n))
    removed = draw(st.integers(0, held_count - 1))
    entering = draw(st.integers(held_count, n - 1))
    return n, held_count, weights, buy, sell, removed, entering


@SETTINGS
@given(_liquidation_case())
def test_a_removed_asset_always_has_a_sale_and_a_cost_when_costs_are_positive(case) -> None:  # type: ignore[no-untyped-def]
    """TST-016: ``w_current_i > 0`` y ``w_new_i = 0`` ⇒ existe venta y coste correspondiente."""
    n, held_count, weights, buy, sell, removed, entering = case
    universe = build_universe(n, CONFIG, {"BuyCost": buy, "SellCost": sell, "MaxWeight": [1.0] * n})
    costs = resolve_asset_costs(universe, CONFIG.transaction_costs).require_complete()
    index = AssetIndex.from_universe(universe)
    held = {f"A{i:03d}": float(w) for i, w in enumerate(weights)}
    state = CurrentPortfolioState.from_weights("P", held, index, None)
    kept = [i for i in range(held_count) if i != removed] + [entering]
    composition = tuple(sorted(f"A{i:03d}" for i in kept))
    alignment = align_union(state, composition)
    model = TransactionCostModel(alignment, costs, 1.0)
    # nueva cartera: el peso del activo retirado pasa al entrante; el resto no cambia
    new = {f"A{i:03d}": (float(weights[i]) if i < held_count else 0.0) for i in kept}
    new[f"A{entering:03d}"] = float(weights[removed])
    vector = np.array([new[a] for a in composition])
    # valores esperados con bucles explícitos sobre la unión
    sale = float(weights[removed])
    expected_cost = sale * (sell[removed] / 1e4) + sale * (buy[entering] / 1e4)
    assert float(model.cost_one_off(vector)) == pytest.approx(expected_cost, rel=1e-9)
    assert float(model.turnover(vector)) == pytest.approx(0.5 * (sale + sale), rel=1e-9)
    assert float(model.turnover(vector)) > 0.0 and float(model.cost_one_off(vector)) > 0.0
    removed_only = model.exit_cost_one_off()
    assert removed_only == pytest.approx(sale * sell[removed] / 1e4, rel=1e-9)
    assert float(model.cost_one_off(vector)) >= removed_only  # no solo los activos de la nueva


@SETTINGS
@given(
    st.lists(st.text("ABCDEFGH", min_size=1, max_size=3), min_size=1, max_size=8, unique=True),
    st.randoms(),
)
def test_composition_hash_is_invariant_to_order(ids, random) -> None:  # type: ignore[no-untyped-def]
    shuffled = list(ids)
    random.shuffle(shuffled)
    assert composition_hash_of(ids) == composition_hash_of(shuffled)
    other = [*ids, "ZZZ-extra"]
    assert composition_hash_of(other) != composition_hash_of(ids)


@st.composite
def _projection_case(draw):  # type: ignore[no-untyped-def]
    n = draw(st.integers(2, 8))
    lower = np.array(draw(st.lists(st.floats(0.0, 0.05), min_size=n, max_size=n)))
    span = np.array(draw(st.lists(st.floats(0.4, 1.0), min_size=n, max_size=n)))
    target = np.array(draw(st.lists(st.floats(-1.0, 2.0), min_size=n, max_size=n)))
    seed = draw(st.integers(0, 10_000))
    return lower, lower + span, target, seed


@SETTINGS
@given(_projection_case())
def test_projection_is_feasible_idempotent_and_the_closest_feasible_point(case) -> None:  # type: ignore[no-untyped-def]
    lower, upper, target, seed = case
    assume(lower.sum() <= 1.0 <= upper.sum())  # conjunto factible no vacío
    projected = project_box_budget(target, lower, upper, 1.0)
    assert projected.sum() == pytest.approx(1.0, abs=1e-9)
    assert np.all(projected >= lower - 1e-9) and np.all(projected <= upper + 1e-9)
    assert np.allclose(project_box_budget(projected, lower, upper, 1.0), projected, atol=1e-9)
    rng = np.random.default_rng(seed)
    best = float(np.sum((projected - target) ** 2))
    for _ in range(40):  # ningún punto factible aleatorio está más cerca del objetivo
        candidate = np.clip(rng.dirichlet(np.ones(len(target))), lower, upper)
        candidate = project_box_budget(candidate, lower, upper, 1.0) * 0.5 + projected * 0.5
        assert float(np.sum((candidate - target) ** 2)) >= best - 1e-9


@st.composite
def _neighborhood_case(draw):  # type: ignore[no-untyped-def]
    size = draw(st.integers(2, 6))
    outs = draw(st.integers(1, size))
    ins = draw(st.integers(1, 6))
    orders = draw(st.sampled_from([(1,), (1, 2), (1, 2, 3)]))
    limit = draw(st.integers(1, 40))
    keep = draw(st.lists(st.floats(0.0, 1.0), min_size=outs, max_size=outs))
    score = draw(st.lists(st.floats(0.0, 1.0), min_size=ins, max_size=ins))
    return size, outs, ins, orders, limit, keep, score


@SETTINGS
@given(_neighborhood_case())
def test_swap_neighborhoods_keep_the_size_and_never_repeat_a_composition(case) -> None:  # type: ignore[no-untyped-def]
    size, outs, ins, orders, limit, keep, score = case
    config = with_candidates(CONFIG, swap_orders=orders, max_neighbors_per_order=limit)
    node = frozenset(range(size))
    out_positions = np.arange(outs)
    in_positions = np.arange(100, 100 + ins)
    neighbors = SwapGenerator(config.candidates).neighbors(
        node,
        size,
        Shortlist(out_positions, np.array(keep)),
        Shortlist(in_positions, np.array(score)),
    )
    seen = set()
    for neighbor in neighbors:
        assert len(neighbor.positions) == size  # el tamaño objetivo se conserva
        assert neighbor.positions != node and neighbor.positions not in seen
        seen.add(neighbor.positions)
        assert (
            set(neighbor.out_positions) <= set(out_positions.tolist())
            and not set(neighbor.in_positions) & node
        )
        assert node - neighbor.positions == set(neighbor.out_positions)
        assert neighbor.positions - node == set(neighbor.in_positions)
    assert len(neighbors) <= limit * len(orders)


@SETTINGS
@given(st.lists(st.floats(-1e6, 1e6), min_size=1, max_size=30))
def test_rank_percentiles_preserve_order_and_stay_in_the_unit_interval(values) -> None:  # type: ignore[no-untyped-def]
    array = np.array(values)
    ranks = average_rank_percentile(array)
    assert ranks.shape == array.shape and np.all((ranks >= 0.0) & (ranks <= 1.0))
    order = np.argsort(array, kind="stable")
    assert np.all(np.diff(ranks[order]) >= -1e-12)  # monótono con el valor
    for i in range(len(values)):
        for j in range(len(values)):
            if array[i] == array[j]:
                assert ranks[i] == pytest.approx(ranks[j])  # los empates comparten rango
