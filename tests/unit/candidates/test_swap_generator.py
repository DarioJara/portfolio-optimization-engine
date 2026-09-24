"""CAN-003, CAN-004, CAN-005, CAN-019: 1-swap, 2-swap, 3-swap opcional y movimientos ADD/DROP."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from portfolio_engine.candidates import Shortlist, SwapGenerator
from portfolio_engine.models.enums import MoveKind
from tests.fixtures.candidates import with_candidates
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

NODE = frozenset({0, 1, 2, 3})
OUT_POSITIONS = [0, 1, 2]
OUT_KEEP = [0.9, 0.2, 0.5]  # peor mantenimiento = menor score
IN_POSITIONS = [10, 11, 12, 13]
IN_SCORE = [0.3, 0.8, 0.6, 0.1]


def _generator(orders=(1, 2, 3), limit=1000):  # type: ignore[no-untyped-def]
    config = with_candidates(base_config(), swap_orders=orders, max_neighbors_per_order=limit)
    return SwapGenerator(config.candidates)


def _lists(outs=None, ins=None):  # type: ignore[no-untyped-def]
    return (
        Shortlist(np.array(outs or OUT_POSITIONS), np.array(OUT_KEEP)),
        Shortlist(np.array(ins or IN_POSITIONS), np.array(IN_SCORE)),
    )


def _expected(order: int) -> set[frozenset[int]]:
    """Vecindario esperado enumerado a mano con ``itertools`` sobre conjuntos."""
    return {
        (NODE - set(out)) | set(entering)
        for out in itertools.combinations(OUT_POSITIONS, order)
        for entering in itertools.combinations(IN_POSITIONS, order)
    }


def _by_kind_size(neighbors, order):  # type: ignore[no-untyped-def]
    return {n.positions for n in neighbors if len(n.out_positions) == order}


def test_one_swap_is_the_exhaustive_product_of_the_shortlists() -> None:
    neighbors = _generator().neighbors(NODE, 4, *_lists())
    one = [n for n in neighbors if len(n.out_positions) == 1]
    assert len(one) == 3 * 4
    assert _by_kind_size(neighbors, 1) == _expected(1)
    for neighbor in one:
        assert neighbor.kind is MoveKind.SWAP and len(neighbor.positions) == 4
        assert len(NODE - neighbor.positions) == 1 and len(neighbor.positions - NODE) == 1


def test_two_swap_is_exhaustive_when_it_fits_and_three_swap_is_optional() -> None:
    all_orders = _generator((1, 2, 3)).neighbors(NODE, 4, *_lists())
    assert len(_by_kind_size(all_orders, 2)) == 3 * 6  # C(3,2)·C(4,2)
    assert _by_kind_size(all_orders, 2) == _expected(2)
    assert _by_kind_size(all_orders, 3) == _expected(3) and len(_expected(3)) == 1 * 4
    only_pairs = _generator((1, 2)).neighbors(NODE, 4, *_lists())
    assert not [n for n in only_pairs if len(n.out_positions) == 3]  # 3-swap desactivado
    only_single = _generator((1,)).neighbors(NODE, 4, *_lists())
    assert {len(n.out_positions) for n in only_single} == {1}


def test_orders_larger_than_the_shortlists_are_skipped() -> None:
    generator = _generator((1, 2, 3))
    neighbors = generator.neighbors(NODE, 4, *_lists(outs=[0, 1], ins=[10, 11, 12]))
    assert {len(n.out_positions) for n in neighbors} == {1, 2}  # sin 3-swap con 2 salidas


def test_neighbors_are_sets_without_duplicates_and_independent_of_shortlist_order() -> None:
    generator = _generator((1, 2, 3))
    neighbors = generator.neighbors(NODE, 4, *_lists())
    sets = [n.positions for n in neighbors]
    assert len(sets) == len(set(sets))
    rng = np.random.default_rng(0)
    order_out, order_in = rng.permutation(3), rng.permutation(4)
    outs = Shortlist(np.array(OUT_POSITIONS)[order_out], np.array(OUT_KEEP)[order_out])
    ins = Shortlist(np.array(IN_POSITIONS)[order_in], np.array(IN_SCORE)[order_in])
    shuffled = generator.neighbors(NODE, 4, outs, ins)
    assert {n.positions for n in shuffled} == set(sets)
    assert len(shuffled) == len(neighbors)  # un cambio de orden no es una composición nueva


def test_the_prior_is_incoming_score_minus_keep_score_of_the_leaving_assets() -> None:
    neighbors = _generator((1, 2)).neighbors(NODE, 4, *_lists())
    keep = dict(zip(OUT_POSITIONS, OUT_KEEP, strict=True))
    score = dict(zip(IN_POSITIONS, IN_SCORE, strict=True))
    for neighbor in neighbors:
        expected = sum(score[p] for p in neighbor.in_positions) - sum(
            keep[p] for p in neighbor.out_positions
        )
        assert neighbor.prior == pytest.approx(expected)


def test_large_neighborhoods_keep_the_highest_prior_neighbors_per_order() -> None:
    """A-18: si el vecindario supera el límite se conservan los de mayor prior."""
    limit = 5
    neighbors = _generator((1,), limit).neighbors(NODE, 4, *_lists())
    assert len(neighbors) == limit
    all_priors = sorted(
        (s - k for s in IN_SCORE for k in OUT_KEEP),
        reverse=True,
    )
    assert sorted((n.prior for n in neighbors), reverse=True) == pytest.approx(all_priors[:limit])
    again = _generator((1,), limit).neighbors(NODE, 4, *_lists())
    assert [n.positions for n in again] == [n.positions for n in neighbors]  # determinista


def test_add_moves_when_the_composition_is_smaller_than_the_target() -> None:
    node = frozenset({0, 1})
    neighbors = _generator().neighbors(node, 3, *_lists())
    assert all(n.kind is MoveKind.ADD and not n.out_positions for n in neighbors)
    assert {n.positions for n in neighbors} == {node | {p} for p in IN_POSITIONS}
    assert all(len(n.positions) == 3 for n in neighbors)


def test_drop_moves_when_the_composition_is_larger_than_the_target() -> None:
    neighbors = _generator().neighbors(NODE, 3, *_lists())
    assert all(n.kind is MoveKind.DROP and not n.in_positions for n in neighbors)
    assert {n.positions for n in neighbors} == {NODE - {p} for p in OUT_POSITIONS}
    # se propone sacar primero el de peor mantenimiento (mayor prior = −keep)
    assert neighbors[0].out_positions == (1,)


def test_empty_shortlists_generate_no_neighbors() -> None:
    generator = _generator()
    empty = Shortlist(np.empty(0, dtype=np.int64), np.empty(0))
    assert generator.neighbors(NODE, 4, empty, _lists()[1]) == ()
    assert generator.neighbors(NODE, 4, _lists()[0], empty) == ()
