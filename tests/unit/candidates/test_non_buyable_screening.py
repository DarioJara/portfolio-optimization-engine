"""E-10 en el ``EligibilityFilter`` y el screening: una posición no comprable no se puntúa como si
pudiera entrar con peso ``1/T`` (H-1 de AUDIT_BLOCK_3, ``CandidateScreening``/estimaciones)."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.candidates import CandidateScreening, EligibilityFilter, UniverseSnapshot
from portfolio_engine.models.enums import EligibilityStatus
from tests.fixtures.non_buyable import BLOCKERS, HELD_WEIGHT, non_buyable_problem

pytestmark = pytest.mark.unit

LAM = 4.0
TARGET_SIZE = 2  # peso de entrada supuesto a un entrante: 1/T = 0,5, muy por encima del tope 0,10


def _setup(case: str):  # type: ignore[no-untyped-def]
    config, problem = non_buyable_problem(case)
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    eligibility = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    return config, problem, snapshot, eligibility


@pytest.mark.parametrize("case", list(BLOCKERS))
def test_the_eligibility_result_exposes_the_cap_of_a_held_non_buyable_asset(case: str) -> None:
    _, _, snapshot, eligibility = _setup(case)
    a000 = int(snapshot.index.indices_of(["A000"])[0])
    assert eligibility.status[a000] is EligibilityStatus.LIQUIDATE_ONLY
    assert eligibility.weight_cap[a000] == pytest.approx(HELD_WEIGHT)
    others = np.delete(eligibility.weight_cap, a000)
    assert np.all(np.isinf(others))  # A001 (comprable) y los nuevos elegibles no tienen tope


@pytest.mark.parametrize("case", list(BLOCKERS))
def test_the_screening_scores_a_re_entering_non_buyable_asset_at_its_cap(case: str) -> None:
    config, _, snapshot, eligibility = _setup(case)
    screening = CandidateScreening(config.candidates, config.returns.risk_free_rate)
    a000 = int(snapshot.index.indices_of(["A000"])[0])
    a001 = int(snapshot.index.indices_of(["A001"])[0])
    node = np.array([a001])  # composición sin A000; A000 reentra como «entrante»
    node_weights = np.array([1.0])
    entrants = np.setdiff1d(eligibility.enterable.global_indices, node)
    assert a000 in entrants
    weight = 1.0 / TARGET_SIZE
    capped = screening.screen(
        snapshot, node, node_weights, entrants, LAM, weight, eligibility.weight_cap[entrants]
    ).entrants
    at_cap = screening.screen(snapshot, node, node_weights, entrants, LAM, HELD_WEIGHT).entrants
    uncapped = screening.screen(snapshot, node, node_weights, entrants, LAM, weight).entrants
    row = int(np.flatnonzero(capped.positions == a000)[0])
    # oráculo: el entrante topado se puntúa igual que con peso de entrada 0,10 ...
    assert capped.raw[:, row] == pytest.approx(at_cap.raw[:, row], nan_ok=True)
    # ... y no como con 0,5 (la utilidad incremental y el riesgo marginal dependen del peso)
    assert not np.allclose(capped.raw[:, row], uncapped.raw[:, row], equal_nan=True)
    # los entrantes sin tope conservan el peso 1/T
    other = int(np.flatnonzero(capped.positions != a000)[0])
    assert capped.raw[:, other] == pytest.approx(uncapped.raw[:, other], nan_ok=True)


@pytest.mark.parametrize("case", ["not_eligible", "not_liquid"])
def test_the_neighborhood_expander_screens_with_the_cap(case: str) -> None:
    """Cableado: ``expand`` pasa ``weight_cap`` al screening (peso de entrada de A000: 0,10)."""
    from portfolio_engine.candidates import EvaluationBudget, NeighborhoodExpander
    from portfolio_engine.models.enums import CandidateOrigin
    from tests.fixtures.candidates import root_node, services_for

    config, problem = non_buyable_problem(case)
    services = services_for(problem, config)
    root, baseline = root_node(services, problem, LAM)
    expander = NeighborhoodExpander(services)
    visited = {root.composition_hash}
    children = expander.expand(
        root, LAM, 1, visited, EvaluationBudget(500), baseline, CandidateOrigin.BEAM_SEARCH
    ).children
    a000 = int(services.snapshot.index.indices_of(["A000"])[0])
    without = next(c for c in children if a000 not in c.positions)  # A000 sale y puede reentrar
    expansion = expander.expand(
        without, LAM, 2, visited, EvaluationBudget(500), baseline, CandidateOrigin.BEAM_SEARCH
    )
    table = expansion.screening.entrants  # type: ignore[union-attr]
    row = int(np.flatnonzero(table.positions == a000)[0])
    screening = CandidateScreening(config.candidates, config.returns.risk_free_rate)
    entrants = np.setdiff1d(
        services.eligibility.enterable.global_indices, np.array(without.positions)
    )
    oracle = screening.screen(
        services.snapshot,
        np.array(without.positions),
        without.estimate.weights,
        entrants,
        LAM,
        HELD_WEIGHT,  # peso de entrada esperado: el tope (0,10), no 1/T = 0,5
    ).entrants
    assert table.raw[:, row] == pytest.approx(
        oracle.raw[:, int(np.flatnonzero(oracle.positions == a000)[0])], nan_ok=True
    )
