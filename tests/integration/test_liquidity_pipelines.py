"""CON-012, FEA-006 (A-11): la capacidad ADV/NAV se respeta en frontera continua, candidatos y
frontera global; posición existente protegida.

Escenario de ``tests/fixtures/liquidity.py``: ``A000`` (retorno 0,30) con capacidad 0,10 calculada a
mano; sin la restricción el óptimo lo llevaría muy por encima.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.exceptions import ConstraintCompilationError
from portfolio_engine.frontiers import ContinuousFrontierEngine, GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import CostTreatment, EvaluationMode, FrontierMethod
from tests.fixtures.candidates import search, with_candidates
from tests.fixtures.liquidity import CAPACITY_A000, liquidity_config, liquidity_problem
from tests.fixtures.non_buyable import MU, SIGMA
from tests.fixtures.problems import base_config, make_problem, spec_with

pytestmark = pytest.mark.integration

TOLERANCE = 1e-6
FULL = ("A000", "A001", "A002", "A003")
HELD_BELOW = [0.05, 0.60, 0.35, 0.0]
HELD_ABOVE = [0.20, 0.50, 0.30, 0.0]
NEW = [0.0, 0.5, 0.5, 0.0]


def _a000(asset_ids, weights) -> float:  # type: ignore[no-untyped-def]
    return float(weights[asset_ids.index("A000")])


def _weights(
    config, problem, treatment=CostTreatment.GROSS, method=FrontierMethod.RISK_AVERSION_GRID
):  # type: ignore[no-untyped-def]
    result = ContinuousFrontierEngine(config).solve(problem, treatment, method)
    return result, [
        _a000(result.asset_ids, p.weights) for p in result.points if p.weights is not None
    ]


@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
@pytest.mark.parametrize("method", list(FrontierMethod))
def test_a_held_position_below_the_capacity_is_capped_at_the_capacity(treatment, method) -> None:  # type: ignore[no-untyped-def]
    config, problem = liquidity_problem(HELD_BELOW, composition=FULL)
    result, weights = _weights(config, problem, treatment, method)
    assert len(weights) >= 3
    assert max(weights) == pytest.approx(CAPACITY_A000, abs=1e-4)  # crece hasta la capacidad
    assert all(p.is_valid_solution for p in result.points if p.weights is not None)


@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_a_held_position_above_the_capacity_never_increases_and_is_not_forced_out(
    treatment,
) -> None:  # type: ignore[no-untyped-def]
    config, problem = liquidity_problem(HELD_ABOVE, composition=FULL)
    result, weights = _weights(config, problem, treatment)
    assert max(weights) == pytest.approx(0.20, abs=1e-4)  # se mantiene: max(0,20, 0,10)
    assert all(p.is_valid_solution for p in result.points if p.weights is not None)


def test_a_new_position_is_limited_to_the_capacity() -> None:
    config, problem = liquidity_problem(NEW, composition=("A000", "A001", "A002"))
    result, weights = _weights(config, problem)
    assert max(weights) == pytest.approx(CAPACITY_A000, abs=1e-4)
    assert all(p.is_valid_solution for p in result.points if p.weights is not None)


def test_control_without_the_constraint_the_optimizer_buys_far_more() -> None:
    config = liquidity_config(None, None, enabled=False)
    _, problem = liquidity_problem(NEW, config, composition=("A000", "A001", "A002"))
    _, weights = _weights(config, problem)
    assert max(weights) > 0.5


def test_a_held_position_above_the_capacity_can_be_reduced_to_zero() -> None:
    mu = np.array([-0.05, 0.04, 0.06, 0.09])  # A000 conviene vender
    config, problem = liquidity_problem(HELD_ABOVE, composition=FULL, mu=mu)
    _, weights = _weights(config, problem)
    assert min(weights) <= TOLERANCE and max(weights) <= 0.20 + TOLERANCE


def test_max_turnover_is_compatible_with_a_protected_position() -> None:
    spec = spec_with(nav=1e8, nav_currency="EUR", max_turnover=0.05)
    config, problem = liquidity_problem(HELD_ABOVE, composition=FULL, spec=spec)
    result, weights = _weights(config, problem)
    assert max(weights) <= 0.20 + TOLERANCE  # nunca por encima del peso actual
    current = np.array(HELD_ABOVE)
    for point in result.points:
        if point.weights is not None:
            assert point.is_valid_solution
            assert 0.5 * np.abs(point.weights - current).sum() <= 0.05 + 1e-6  # turnover a mano


@pytest.mark.parametrize("mode", [EvaluationMode.PROJECTED_WEIGHTS, EvaluationMode.QP_UTILITY])
def test_candidate_estimates_and_the_global_frontier_respect_the_capacity(mode) -> None:  # type: ignore[no-untyped-def]
    config, problem = liquidity_problem(HELD_BELOW)
    iterations = 8 if mode is EvaluationMode.PROJECTED_WEIGHTS else 0
    config = with_candidates(config, evaluation_mode=mode, refinement_iterations=iterations)
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert len(result.candidates) > 1
    checked = 0
    for candidate in result.candidates:
        if "A000" not in candidate.asset_ids:
            continue
        for estimate in candidate.estimates:
            assert _a000(candidate.asset_ids, estimate.weights) <= CAPACITY_A000 + TOLERANCE
            assert estimate.satisfies_constraints
    for entry in result.points:
        if "A000" in entry.asset_ids and entry.point.weights is not None:
            checked += 1
            assert _a000(entry.asset_ids, entry.point.weights) <= CAPACITY_A000 + TOLERANCE
    assert checked > 0
    assert any(n.startswith("A11_ADV_NAV") for n in result.candidate_diagnostics.notes)


def test_the_diagnostics_list_the_protected_positions_above_the_capacity() -> None:
    config, problem = liquidity_problem(HELD_ABOVE)
    notes = search(config, problem).diagnostics.notes
    (note,) = [n for n in notes if n.startswith("A11_ADV_NAV")]
    assert "positions_above_capacity_protected=['A000']" in note


def test_candidate_generation_stops_with_a_data_error_when_a_required_datum_is_missing() -> None:
    config, problem = liquidity_problem(HELD_BELOW, overrides={"ADV": [2e7, None, 1e9, 1e9]})
    with pytest.raises(ConstraintCompilationError, match="ADV"):
        search(config, problem)
    config, problem = liquidity_problem(HELD_BELOW, nav=None)
    with pytest.raises(ConstraintCompilationError, match="NAV"):
        search(config, problem)


def test_the_disabled_constraint_leaves_previous_behaviour_untouched() -> None:
    config = base_config()  # [constraints.liquidity] enabled = false
    problem = make_problem(
        MU, SIGMA, HELD_BELOW, config, universe_overrides={"MaxWeight": [1.0] * 4}
    )
    assert not any(n.startswith("A11") for n in search(config, problem).diagnostics.notes)
