"""CAN-006: ``LocalSearch`` (ascenso de mejor mejora) con evaluación exacta.

Se usa el evaluador ``QP_UTILITY``: la utilidad de cada composición es su óptimo real y la
condición de óptimo local se verifica con SLSQP independiente sobre todo el vecindario 1-swap.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from portfolio_engine.candidates import EvaluationBudget, LocalSearch, NeighborhoodExpander
from portfolio_engine.frontiers import QPCompositionEvaluator
from tests.fixtures.candidates import corr_matrix, exact_net_utility, root_node, services_for
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem

pytestmark = pytest.mark.unit

N = 7
LAM = 4.0
MU = np.array([0.03, 0.035, 0.04, 0.10, 0.09, 0.08, 0.02])
VOLS = [0.12, 0.13, 0.14, 0.16, 0.15, 0.20, 0.30]
SIGMA = cov_from_vol_corr(VOLS, corr_matrix(N, 0.15))
CURRENT = [0.4, 0.3, 0.3, 0.0, 0.0, 0.0, 0.0]
BUY_BPS = [10.0, 12.0, 14.0, 20.0, 18.0, 16.0, 30.0]
SELL_BPS = [15.0, 17.0, 19.0, 25.0, 23.0, 21.0, 35.0]
BUY, SELL = np.array(BUY_BPS) / 1e4, np.array(SELL_BPS) / 1e4
MAX_WEIGHT = 0.6


def _config(**changes):  # type: ignore[no-untyped-def]
    values = {
        "swap_orders": (1,),
        "max_levels": 5,
        "shortlist_in": 4,
        "shortlist_out": 3,
        "refinement_iterations": 0,
        "utility_risk_aversions": (LAM,),
        "max_evaluations": 200,
    }
    values.update(changes)
    from portfolio_engine.models.enums import EvaluationMode

    return base_config(candidates={"evaluation_mode": EvaluationMode.QP_UTILITY, **values})


def _problem(config):  # type: ignore[no-untyped-def]
    return make_problem(
        MU, SIGMA, CURRENT, config,
        universe_overrides={
            "MaxWeight": [MAX_WEIGHT] * N,
            "BuyCost": BUY_BPS,
            "SellCost": SELL_BPS,
        },
    )  # fmt: skip


def _exact_utility(problem, positions):  # type: ignore[no-untyped-def]
    """Utilidad óptima exacta (SLSQP) de una composición dada respecto a la cartera actual."""
    idx = sorted(positions)
    sigma = np.array(problem.risk_model.sigma)
    current_all = np.array(CURRENT)
    leaving = [i for i in range(N) if current_all[i] > 0 and i not in idx]
    exit_cost = float(sum(SELL[i] * current_all[i] for i in leaving))
    return exact_net_utility(
        MU[idx], sigma[np.ix_(idx, idx)], current_all[idx], BUY[idx], SELL[idx], exit_cost, 1.0,
        np.zeros(len(idx)), np.full(len(idx), MAX_WEIGHT), LAM,
    )[0]  # fmt: skip


def _setup(config=None):  # type: ignore[no-untyped-def]
    config = config or _config()
    problem = _problem(config)
    services = services_for(problem, config, QPCompositionEvaluator(config))
    root, baseline = root_node(services, problem, LAM)
    return config, problem, services, root, baseline


def _run(config=None, budget=200):  # type: ignore[no-untyped-def]
    config, problem, services, root, baseline = _setup(config)
    search = LocalSearch(services, NeighborhoodExpander(services))
    outcome = search.run(root, LAM, baseline, {root.composition_hash}, EvaluationBudget(budget))
    return problem, root, baseline, outcome


def test_the_path_strictly_improves_the_estimated_utility() -> None:
    _, root, _, outcome = _run()
    assert outcome.path[0] is root and len(outcome.path) > 1
    gains = [node.gain for node in outcome.path]
    assert all(later > earlier + 1e-12 for earlier, later in itertools.pairwise(gains))
    assert all(len(node.positions) == 3 for node in outcome.path)
    assert outcome.stop_reason == "LOCAL_OPTIMUM"


def test_the_final_composition_is_a_local_optimum_for_the_independent_exact_utility() -> None:
    problem, _, _, outcome = _run()
    final = outcome.path[-1]
    final_exact = _exact_utility(problem, final.positions)
    assert final.estimate.utility == pytest.approx(final_exact, abs=1e-7)  # el evaluador es exacto
    for out, entering in itertools.product(final.positions, set(range(N)) - set(final.positions)):
        neighbor = (set(final.positions) - {out}) | {entering}
        assert _exact_utility(problem, neighbor) <= final_exact + 1e-7, (out, entering)


def test_every_step_moves_to_the_best_improving_neighbor() -> None:
    problem, _, _, outcome = _run()
    for parent, child in zip(outcome.path, outcome.path[1:], strict=False):
        chosen = _exact_utility(problem, child.positions)
        for out, entering in itertools.product(
            parent.positions, set(range(N)) - set(parent.positions)
        ):
            neighbor = (set(parent.positions) - {out}) | {entering}
            assert _exact_utility(problem, neighbor) <= chosen + 1e-7


def test_reaches_the_global_optimum_of_the_designed_landscape() -> None:
    """Las composiciones de alto retorno {A003, A004, A005} dominan; el óptimo global por
    enumeración exhaustiva (SLSQP) coincide con el óptimo local alcanzado."""
    problem, _, _, outcome = _run()
    best = max(itertools.combinations(range(N), 3), key=lambda c: _exact_utility(problem, c))
    assert set(outcome.path[-1].positions) == set(best)


def test_starting_at_a_local_optimum_makes_no_move() -> None:
    _, _, services, root, baseline = _setup()
    search = LocalSearch(services, NeighborhoodExpander(services))
    first = search.run(root, LAM, baseline, {root.composition_hash}, EvaluationBudget(200))
    optimum = first.path[-1]
    again = search.run(optimum, LAM, baseline, {optimum.composition_hash}, EvaluationBudget(200))
    assert again.path == (optimum,) and again.stop_reason == "LOCAL_OPTIMUM"
    assert again.stages and again.stages[-1].survivors == 0


def test_budget_and_level_limits_stop_the_search_with_their_reason() -> None:
    _, _, _, outcome = _run(budget=2)
    assert outcome.stop_reason in {"BUDGET_EXHAUSTED", "LOCAL_OPTIMUM", "MAX_LEVELS"}
    limited = _run(_config(max_levels=1))[3]
    assert limited.stop_reason == "MAX_LEVELS" and len(limited.path) == 2
    exhausted = _run(budget=0)[3]
    assert exhausted.stop_reason == "BUDGET_EXHAUSTED" and len(exhausted.path) == 1


def test_evaluated_neighbors_are_reported_without_duplicates() -> None:
    _, _, _, outcome = _run()
    hashes = [node.composition_hash for node in outcome.evaluated]
    assert len(hashes) == len(set(hashes)) > len(outcome.path) - 1
