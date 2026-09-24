"""E-10, CAN-013, CON-022, FRN-002, FRN-003 (H-1 de AUDIT_BLOCK_3): una posición actual no
comprable no puede incrementarse en ninguna capa.

``A000`` pesa 0,10, es muchísimo más rentable que el resto y no admite compras. Sin restricción
alguna el optimizador lo llevaría por encima de 0,10; el valor esperado en cada capa es la
constante 0,10 del escenario (``tests/fixtures/non_buyable.py``), no una función bajo prueba.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.candidates.candidate_engine import NOTE_NON_BUYABLE_CAPPED
from portfolio_engine.frontiers import ContinuousFrontierEngine, GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import (
    CostTreatment,
    EvaluationMode,
    FrontierMethod,
    RestrictedExistingPositionPolicy,
)
from tests.fixtures.candidates import search, with_candidates
from tests.fixtures.non_buyable import (
    BLOCKERS,
    CURRENT,
    HELD_WEIGHT,
    MU,
    MU_UNATTRACTIVE,
    OPEN_BOUNDS,
    SIGMA,
    non_buyable_problem,
)
from tests.fixtures.problems import (
    base_config,
    make_problem,
    policy_config,
    restricted_universe,
    spec_with,
)

pytestmark = pytest.mark.integration

TOLERANCE = 1e-6
CASES = list(BLOCKERS)
TREATMENTS = (CostTreatment.GROSS, CostTreatment.NET)
FULL = ("A000", "A001", "A002", "A003")


def _weight_of_a000(asset_ids: tuple[str, ...], weights: np.ndarray) -> float:  # type: ignore[type-arg]
    return float(weights[asset_ids.index("A000")])


@pytest.fixture(scope="module", params=CASES)
def scenario(request):  # type: ignore[no-untyped-def]
    config, problem = non_buyable_problem(request.param)
    return request.param, config, problem


# ------------------------------------------------------------------------ frontera continua


def test_control_without_the_rule_the_optimizer_would_buy_the_asset() -> None:
    """Sin bloqueo de compra A000 (rentabilidad 0,30 con vol 0,10) supera con creces el 10 %."""
    config = base_config()
    problem = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides=OPEN_BOUNDS, composition=FULL
    )
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    weights = [
        _weight_of_a000(result.asset_ids, p.weights) for p in result.points if p.weights is not None
    ]
    assert max(weights) > 0.5


@pytest.mark.parametrize("treatment", TREATMENTS)
@pytest.mark.parametrize("method", list(FrontierMethod))
def test_the_continuous_frontier_never_exceeds_the_current_weight(
    scenario,
    treatment: CostTreatment,
    method: FrontierMethod,  # type: ignore[no-untyped-def]
) -> None:
    case, config, _ = scenario
    problem = non_buyable_problem(case, config, composition=FULL)[1]
    result = ContinuousFrontierEngine(config).solve(problem, treatment, method)
    weights = [
        _weight_of_a000(result.asset_ids, point.weights)
        for point in result.points
        if point.weights is not None
    ]
    assert len(weights) >= 5
    assert max(weights) <= HELD_WEIGHT + TOLERANCE
    # con este retorno esperado el tope es vinculante: el activo se puede mantener en 10 %
    assert max(weights) == pytest.approx(HELD_WEIGHT, abs=1e-4)
    assert all(point.is_valid_solution for point in result.points if point.weights is not None)


def test_the_continuous_frontier_can_reduce_a_non_buyable_position_to_zero(scenario) -> None:  # type: ignore[no-untyped-def]
    case, _, _ = scenario
    config, problem = non_buyable_problem(case, mu=MU_UNATTRACTIVE, composition=FULL)
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    weights = [
        _weight_of_a000(result.asset_ids, point.weights)
        for point in result.points
        if point.weights is not None
    ]
    assert (
        min(weights) <= TOLERANCE
    )  # reducir hasta salir está permitido (no es liquidación forzosa)
    assert max(weights) <= HELD_WEIGHT + TOLERANCE


def test_a_non_buyable_asset_cannot_enter_an_explicit_composition(scenario) -> None:  # type: ignore[no-untyped-def]
    case, config, _ = scenario
    overrides, universe, _ = BLOCKERS[case]
    problem = make_problem(
        MU,
        SIGMA,
        [0.0, 0.5, 0.5, 0.0],  # A000 no está en la cartera
        config,
        universe_overrides={**OPEN_BOUNDS, **overrides},
        spec=spec_with(investment_universe=universe) if universe else None,
        composition=("A000", "A001", "A002"),
    )
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    weights = [
        _weight_of_a000(result.asset_ids, point.weights)
        for point in result.points
        if point.weights is not None
    ]
    assert weights and max(weights) <= TOLERANCE  # peso nuevo esperado: exactamente 0


# ---------------------------------------------------------------------------- CandidateEngine


def test_every_candidate_estimate_respects_the_current_weight(scenario) -> None:  # type: ignore[no-untyped-def]
    _, config, problem = scenario
    result = search(config, problem)
    containing = [c for c in result.compositions if "A000" in c.asset_ids]
    assert len(result.compositions) > 1 and containing
    for candidate in result.compositions:
        for estimate in candidate.estimates:
            if "A000" in candidate.asset_ids:
                assert (
                    _weight_of_a000(candidate.asset_ids, estimate.weights)
                    <= HELD_WEIGHT + TOLERANCE
                )
            assert estimate.satisfies_constraints
    capped_note = [n for n in result.diagnostics.notes if n.startswith(NOTE_NON_BUYABLE_CAPPED)]
    assert len(capped_note) == 1 and "A000" in capped_note[0]


# ------------------------------------------------------------------- GlobalCandidateFrontier


@pytest.mark.parametrize("treatment", TREATMENTS)
def test_the_global_candidate_frontier_respects_the_current_weight(
    scenario,
    treatment: CostTreatment,  # type: ignore[no-untyped-def]
) -> None:
    _, config, problem = scenario
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, treatment, FrontierMethod.RISK_AVERSION_GRID
    )
    checked = 0
    for entry in result.points:
        if "A000" not in entry.asset_ids or entry.point.weights is None:
            continue
        checked += 1
        assert _weight_of_a000(entry.asset_ids, entry.point.weights) <= HELD_WEIGHT + TOLERANCE
        assert entry.point.is_valid_solution
    assert checked > 0


# --------------------------------------------------- E-09 (restringidos) sigue funcionando


@pytest.mark.parametrize(
    ("policy", "low", "high"),
    [
        (RestrictedExistingPositionPolicy.HOLD_OR_REDUCE, 0.0, HELD_WEIGHT),
        (RestrictedExistingPositionPolicy.FREEZE_WEIGHT, HELD_WEIGHT, HELD_WEIGHT),
        (RestrictedExistingPositionPolicy.FORCE_LIQUIDATE, 0.0, 0.0),
    ],
)
def test_a_restricted_and_ineligible_position_follows_its_restricted_policy(
    policy: RestrictedExistingPositionPolicy, low: float, high: float
) -> None:
    config = policy_config(base_config(), policy)
    config, problem = non_buyable_problem(
        "not_eligible",
        config,
        extra_overrides=restricted_universe(4, [0]),
        composition=FULL,
    )
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    weights = [
        _weight_of_a000(result.asset_ids, point.weights)
        for point in result.points
        if point.weights is not None
    ]
    assert weights
    assert min(weights) >= low - TOLERANCE
    assert max(weights) <= high + TOLERANCE
    if policy is not RestrictedExistingPositionPolicy.HOLD_OR_REDUCE:
        assert max(weights) == pytest.approx(high, abs=1e-4)


def test_the_exact_qp_evaluation_mode_respects_the_cap_too(scenario) -> None:  # type: ignore[no-untyped-def]
    """``QP_UTILITY`` (óptimo exacto por composición) usa las mismas restricciones compiladas."""
    _, config, problem = scenario
    config = with_candidates(
        config, evaluation_mode=EvaluationMode.QP_UTILITY, refinement_iterations=0
    )
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    checked = 0
    for candidate in result.candidates:
        if "A000" not in candidate.asset_ids:
            continue
        for estimate in candidate.estimates:
            assert estimate.basis is EvaluationMode.QP_UTILITY
            checked += 1
            weight = _weight_of_a000(candidate.asset_ids, estimate.weights)
            assert weight <= HELD_WEIGHT + TOLERANCE
    assert checked > 0
