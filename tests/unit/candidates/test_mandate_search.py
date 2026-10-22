"""HC-002/HC-003: el ``CandidateEngine`` con restricciones obligatorias.

* Con un mandato equivalente al comportamiento previo (tamaño fijo y mismos límites de B3) genera
  exactamente las mismas composiciones: el mandato no altera la búsqueda ya validada.
* Con ``INCREASE``/``DECREASE`` busca un tamaño admisible por vez y fusiona sin duplicados.
* La validación de composiciones admite los nuevos límites y conserva los antiguos.
"""

from __future__ import annotations

import dataclasses

import pytest

from portfolio_engine.candidates import CandidateEngine
from portfolio_engine.candidates.merge import merge_search_results
from portfolio_engine.models.enums import CardinalityPolicy
from tests.fixtures.candidates import context_of, random_problem
from tests.fixtures.hard_constraints import HELD, POSITION_FLOOR, with_mandate
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def _search(config, problem):  # type: ignore[no-untyped-def]
    return CandidateEngine(config).search(problem.state.composition(), context_of(problem))


@pytest.fixture(scope="module")
def problem():  # type: ignore[no-untyped-def]
    return random_problem(14, list(range(HELD)), 4, base_config(), max_weight=0.6)


def test_a_fixed_size_mandate_reproduces_the_legacy_search_exactly(problem) -> None:  # type: ignore[no-untyped-def]
    legacy_config = base_config(
        frontier={"min_holding_weight": POSITION_FLOOR},
        candidates={"max_new_assets": 2, "max_swaps": 2},
    )
    legacy = _search(legacy_config, problem)
    mandated = _search(
        with_mandate(
            base_config(candidates={"max_new_assets": 2, "max_swaps": 2}),
            max_added_assets=2,
        ),
        problem,
    )
    assert [c.composition_id for c in mandated.compositions] == [
        c.composition_id for c in legacy.compositions
    ]
    assert mandated.diagnostics.total_evaluated == legacy.diagnostics.total_evaluated
    assert [c.estimated_utility_gain for c in mandated.compositions] == [
        c.estimated_utility_gain for c in legacy.compositions
    ]


def test_each_admissible_size_is_searched_and_the_reference_appears_once(problem) -> None:  # type: ignore[no-untyped-def]
    config = with_mandate(
        cardinality_policy=CardinalityPolicy.INCREASE,
        max_size_increase=2,
        max_total_changed_assets=5,
    )
    result = _search(config, problem)
    sizes = [len(c.asset_ids) for c in result.compositions]
    assert set(sizes) == {HELD, HELD + 1, HELD + 2}
    references = [c for c in result.compositions if c.is_reference]
    assert len(references) == 1 and result.compositions[0].is_reference
    assert len({c.composition_id for c in result.compositions}) == len(result.compositions)
    original = set(problem.state.asset_ids)
    for candidate in result.compositions:
        changed = set(candidate.asset_ids) ^ original
        assert len(changed) <= 5  # altas + bajas respecto a la cartera original
    assert len(result.compositions) <= config.candidates.max_candidates


def test_component_limits_prune_the_search_not_only_the_final_check(problem) -> None:  # type: ignore[no-untyped-def]
    narrow = _search(with_mandate(max_replacements=1), problem)
    wide = _search(with_mandate(max_replacements=3), problem)
    original = set(problem.state.asset_ids)
    assert all(len(set(c.asset_ids) - original) <= 1 for c in narrow.compositions)
    assert max(len(set(c.asset_ids) - original) for c in wide.compositions) >= 2


def test_merge_keeps_one_reference_orders_by_rank_and_caps_the_total(problem) -> None:  # type: ignore[no-untyped-def]
    config = with_mandate(
        cardinality_policy=CardinalityPolicy.DECREASE, max_size_decrease=2, max_added_assets=0
    )
    result = _search(config, problem)
    runs = []
    for size in (HELD - 2, HELD - 1, HELD):
        single = with_mandate(
            cardinality_policy=CardinalityPolicy.DECREASE,
            max_size_decrease=2,
            max_added_assets=0,
            target_size=size,
        )
        runs.append(_search(single, problem))
    merged = merge_search_results(runs, (HELD - 2, HELD - 1, HELD), 4)
    assert len(merged.compositions) <= 4 and merged.compositions[0].is_reference
    assert merge_search_results(runs[:1], (HELD,), 4) is runs[0]
    assert len({c.composition_id for c in merged.compositions}) == len(merged.compositions)
    assert result.diagnostics.notes[-1].startswith("CARDINALITY_SIZES_SEARCHED")
    assert merged.diagnostics.total_evaluated == sum(r.diagnostics.total_evaluated for r in runs)


def test_an_infeasible_mandate_returns_no_compositions_with_the_causes_in_the_notes(
    problem,
) -> None:  # type: ignore[no-untyped-def]
    result = _search(with_mandate(min_active_weight=0.10), problem)  # 11 × 0,10 > 1
    assert result.compositions == ()
    notes = [n for n in result.diagnostics.notes if n.startswith("HARD_CONSTRAINTS_INFEASIBLE")]
    assert notes and "HC_ALL_SIZES_INFEASIBLE" in notes[0]


def test_the_search_is_unchanged_when_the_mandate_section_is_absent(problem) -> None:  # type: ignore[no-untyped-def]
    config = base_config()
    first, second = _search(config, problem), _search(dataclasses.replace(config), problem)
    assert [c.composition_id for c in first.compositions] == [
        c.composition_id for c in second.compositions
    ]
    assert all("CARDINALITY_SIZES_SEARCHED" not in n for n in first.diagnostics.notes)
