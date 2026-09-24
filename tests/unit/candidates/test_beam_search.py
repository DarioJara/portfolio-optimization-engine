"""CAN-007, CAN-008 (en el haz), CAN-015 (deduplicación): ``BeamSearch`` no es una búsqueda greedy.

``BeamWidth`` mantiene varias composiciones distintas por nivel, la búsqueda devuelve varias
finalistas y con ``B > 1`` encuentra composiciones que el camino greedy (``B = 1``) no alcanza.
"""

from __future__ import annotations

import pytest

from portfolio_engine.candidates import (
    BeamSearch,
    EvaluationBudget,
    NeighborhoodExpander,
    component_counts,
    select_survivors,
)
from portfolio_engine.constraints.integer import swap_count
from portfolio_engine.models.enums import CandidateOrigin, CandidateType
from tests.fixtures.candidates import random_problem, root_node, search, services_for
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

LAM = 4.0
HELD = [0, 1, 2, 3]


def _config(beam=3, levels=2, **changes):  # type: ignore[no-untyped-def]
    values = {
        "beam_width": beam,
        "max_levels": levels,
        "swap_orders": (1,),
        "local_search_starts": 0,
        "utility_risk_aversions": (LAM,),
        "max_candidates": 40,
        "refinement_iterations": 15,
        "max_evaluations": 500,
        "stagnation_levels": 5,
        "shortlist_in": 8,
        "shortlist_out": 4,
    }
    values.update(changes)
    return base_config(candidates=values)


def _alternatives(config, seed):  # type: ignore[no-untyped-def]
    problem = random_problem(10, HELD, seed, config)
    return search(config, problem).compositions[1:]


@pytest.mark.parametrize("seed", [3, 18, 19])
def test_a_wider_beam_finds_compositions_the_greedy_path_misses(seed: int) -> None:
    """Con B = 3 aparece una composición estrictamente mejor que la mejor con B = 1 (semillas
    encontradas por barrido: el haz no es un greedy disfrazado)."""
    greedy = _alternatives(_config(beam=1), seed)
    beam = _alternatives(_config(beam=3), seed)
    best_greedy = max(c.estimated_utility_gain for c in greedy)
    best_beam = max(c.estimated_utility_gain for c in beam)
    assert best_beam > best_greedy + 1e-9
    assert len(beam) > len(greedy) > 0


def test_the_beam_expands_several_parents_per_level_while_greedy_expands_one() -> None:
    """Los nodos de nivel 2 del ``pool`` descienden de un único padre con B = 1 y de B padres
    distintos con B = 3: se mantienen varias composiciones por nivel."""

    def parents_of_level_two(beam: int) -> set[str | None]:
        config = _config(beam=beam)
        problem = random_problem(10, HELD, 5, config)
        services = services_for(problem, config)
        root, baseline = root_node(services, problem, LAM)
        outcome = BeamSearch(services, NeighborhoodExpander(services)).run(
            root, LAM, baseline, {root.composition_hash}, EvaluationBudget(500)
        )
        return {n.parent_hash for n in outcome.pool if len(n.moves) == 2}

    assert len(parents_of_level_two(1)) == 1
    assert len(parents_of_level_two(3)) == 3


def test_survivors_per_level_never_exceed_the_beam_width_and_are_distinct() -> None:
    for beam in (1, 2, 4):
        config = _config(beam=beam, levels=3)
        problem = random_problem(10, HELD, 5, config)
        result = search(config, problem)
        stages = [
            s for s in result.diagnostics.stages if s.algorithm is CandidateOrigin.BEAM_SEARCH
        ]
        assert stages and all(s.survivors <= beam for s in stages)
        hashes = [c.composition_hash for c in result.compositions]
        assert len(hashes) == len(set(hashes))  # deduplicación por CompositionHash


def test_returned_finalists_are_many_not_only_the_best() -> None:
    config = _config(beam=4, levels=2)
    assert len(_alternatives(config, 5)) >= 4


def test_the_current_composition_is_kept_as_reference_even_if_it_is_not_the_best() -> None:
    config = _config(beam=3)
    problem = random_problem(10, HELD, 5, config)
    result = search(config, problem)
    reference = result.compositions[0]
    assert reference.is_reference
    assert (
        max(c.estimated_utility_gain for c in result.compositions[1:])
        > reference.estimated_utility_gain
    )


def test_stop_reasons_are_recorded() -> None:
    problem = random_problem(10, HELD, 5, _config())
    assert dict(search(_config(levels=1), problem).diagnostics.stop_reasons) == {LAM: "MAX_LEVELS"}
    stagnant = _config(levels=8, stagnation_levels=1)
    assert dict(search(stagnant, problem).diagnostics.stop_reasons) == {LAM: "STAGNATION"}
    tiny = _config(levels=8, max_evaluations=3)
    assert dict(search(tiny, problem).diagnostics.stop_reasons) == {LAM: "BUDGET_EXHAUSTED"}


def test_diversity_min_distance_separates_the_survivors() -> None:
    config = _config(beam=6, diversity_min_distance=2)
    problem = random_problem(10, HELD, 5, config)
    services = services_for(problem, config)
    root, baseline = root_node(services, problem, LAM)
    expansion = NeighborhoodExpander(services).expand(
        root,
        LAM,
        1,
        {root.composition_hash},
        EvaluationBudget(500),
        baseline,
        CandidateOrigin.BEAM_SEARCH,
    )
    children = list(expansion.children)
    assert len(children) > 6
    apart = select_survivors(children, 6, 2)
    ids = [frozenset(node.prepared.asset_ids) for node in apart]
    assert all(swap_count(a, b) >= 2 for i, a in enumerate(ids) for b in ids[i + 1 :])
    close = select_survivors(children, 6, 1)
    assert any(
        swap_count(frozenset(a.prepared.asset_ids), frozenset(b.prepared.asset_ids)) == 1
        for i, a in enumerate(close)
        for b in close[i + 1 :]
    )


def test_selection_orders_by_estimated_gain_and_breaks_ties_by_hash() -> None:
    config = _config(beam=6)
    problem = random_problem(10, HELD, 5, config)
    services = services_for(problem, config)
    root, baseline = root_node(services, problem, LAM)
    children = list(
        NeighborhoodExpander(services)
        .expand(
            root,
            LAM,
            1,
            {root.composition_hash},
            EvaluationBudget(500),
            baseline,
            CandidateOrigin.BEAM_SEARCH,
        )
        .children
    )
    chosen = select_survivors(children, 6, 1)
    keys = [node.ranking_key() for node in chosen]
    assert keys == sorted(keys) and len(chosen) == 6
    assert (
        select_survivors(list(reversed(children)), 6, 1) == chosen
    )  # independiente del orden de entrada


def test_shortlist_types_follow_the_exploration_mix_of_the_configuration() -> None:
    config = _config(shortlist_in=10)
    problem = random_problem(14, HELD, 5, config)
    services = services_for(problem, config)
    root, baseline = root_node(services, problem, LAM)
    expansion = NeighborhoodExpander(services).expand(
        root,
        LAM,
        1,
        {root.composition_hash},
        EvaluationBudget(500),
        baseline,
        CandidateOrigin.BEAM_SEARCH,
    )
    counts = {kind: list(expansion.shortlisted.values()).count(kind) for kind in CandidateType}
    expected = component_counts(config.candidates.exploration, 10)
    assert (
        counts[CandidateType.HIGH_CONVICTION],
        counts[CandidateType.DIVERSIFICATION],
        counts[CandidateType.EXPLORATION],
    ) == expected


def test_beam_outcome_exposes_the_pool_and_stage_diagnostics() -> None:
    config = _config(beam=3, levels=3)
    problem = random_problem(10, HELD, 5, config)
    services = services_for(problem, config)
    root, baseline = root_node(services, problem, LAM)
    outcome = BeamSearch(services, NeighborhoodExpander(services)).run(
        root, LAM, baseline, {root.composition_hash}, EvaluationBudget(500)
    )
    assert root.composition_hash in {n.composition_hash for n in outcome.pool}
    assert len(outcome.pool) > 3 and outcome.stages
    assert outcome.root_screening is not None and outcome.root_shortlist
    assert sum(s.evaluated for s in outcome.stages) >= len(outcome.pool) - 1  # sin la raíz
    levels = [s.level for s in outcome.stages]
    assert levels == sorted(levels) and levels[0] == 1
