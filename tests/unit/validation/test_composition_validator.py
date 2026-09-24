"""VAL-010: validación independiente de composiciones candidatas.

El validador parte de los datos crudos (universo, cartera, política) y no usa el
``EligibilityFilter``; aquí se comprueba regla a regla y que ambos coinciden en composiciones
aleatorias.
"""

from __future__ import annotations

import itertools

import pytest

from portfolio_engine.candidates import EligibilityFilter, UniverseSnapshot
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy, UnknownFlagPolicy
from portfolio_engine.validation import validate_candidate_composition
from tests.fixtures.candidates import ROLES_N, roles_problem, with_candidates
from tests.fixtures.problems import base_config, policy_config, spec_with

pytestmark = pytest.mark.unit

Policy = RestrictedExistingPositionPolicy
IDS = [f"A{i:03d}" for i in range(ROLES_N)]


def _validate(problem, config, ids, *, policy=Policy.HOLD_OR_REDUCE, reference=False, **limits):  # type: ignore[no-untyped-def]
    return validate_candidate_composition(
        ids,
        universe=problem.universe,
        state=problem.state,
        spec=problem.spec,
        restricted_policy=policy,
        unknown_liquidity_policy=config.candidates.unknown_liquidity_policy,
        target_size=limits.get("target_size", 4),
        max_new_assets=limits.get("max_new_assets"),
        max_swaps=limits.get("max_swaps"),
        is_reference=reference,
    )


def _setup(policy=Policy.HOLD_OR_REDUCE, spec=None):  # type: ignore[no-untyped-def]
    config = policy_config(base_config(), policy)
    return config, roles_problem(config, spec)


def test_the_current_composition_and_a_valid_swap_pass() -> None:
    config, problem = _setup()
    assert _validate(problem, config, IDS[:4]) == ()
    assert _validate(problem, config, ["A000", "A001", "A002", "A004"]) == ()  # A003 → A004


@pytest.mark.parametrize(
    ("entering", "code"),
    [
        ("A005", "NEW_ASSET_NOT_ELIGIBLE"),
        ("A006", "NEW_ASSET_NOT_LIQUID"),
        ("A007", "NEW_ASSET_RESTRICTED"),
        ("A008", "NEW_ASSET_NOT_LIQUID"),  # LiquidityFlag desconocido con política EXCLUDE
        ("A009", "NEW_ASSET_UNKNOWN_RESTRICTED_FLAG"),
    ],
)
def test_a_new_asset_must_be_eligible_liquid_and_unrestricted(entering: str, code: str) -> None:
    config, problem = _setup()
    result = _validate(problem, config, ["A000", "A001", "A002", entering])
    assert code in result


def test_unknown_liquidity_is_allowed_only_with_the_allow_policy() -> None:
    config, problem = _setup()
    allow = with_candidates(config, unknown_liquidity_policy=UnknownFlagPolicy.ALLOW)
    ids = ["A000", "A001", "A002", "A008"]
    assert "NEW_ASSET_NOT_LIQUID" in _validate(problem, config, ids)
    assert _validate(problem, allow, ids) == ()


def test_a_new_asset_outside_the_investment_universe_is_rejected() -> None:
    allowed = tuple(f"A{i:03d}" for i in range(ROLES_N) if i != 4)
    config, problem = _setup(spec=spec_with(investment_universe=allowed))
    assert "NEW_ASSET_OUTSIDE_INVESTMENT_UNIVERSE" in _validate(
        problem, config, ["A000", "A001", "A002", "A004"]
    )
    assert _validate(problem, config, IDS[:4]) == ()  # los mantenidos no se ven afectados


def test_held_assets_are_never_flagged_for_being_ineligible() -> None:
    """D: el activo mantenido no elegible puede conservarse."""
    config, problem = _setup()
    assert _validate(problem, config, ["A000", "A001", "A002", "A003"]) == ()


def test_freeze_weight_asset_cannot_disappear() -> None:
    config, problem = _setup(Policy.FREEZE_WEIGHT)
    assert (
        _validate(problem, config, ["A000", "A001", "A002", "A004"], policy=Policy.FREEZE_WEIGHT)
        == ()
    )
    without = _validate(
        problem, config, ["A000", "A001", "A003", "A004"], policy=Policy.FREEZE_WEIGHT
    )
    assert "FREEZE_WEIGHT_REMOVED" in without


def test_force_liquidate_asset_cannot_be_kept_except_in_the_reference() -> None:
    config, problem = _setup(Policy.FORCE_LIQUIDATE)
    kept = ["A000", "A001", "A002", "A003"]
    assert "FORCE_LIQUIDATE_RETAINED" in _validate(
        problem, config, kept, policy=Policy.FORCE_LIQUIDATE
    )
    assert _validate(problem, config, kept, policy=Policy.FORCE_LIQUIDATE, reference=True) == ()
    assert (
        _validate(problem, config, ["A000", "A001", "A003", "A004"], policy=Policy.FORCE_LIQUIDATE)
        == ()
    )


def test_cardinality_and_swap_limits_use_the_integer_constraint_definitions() -> None:
    config, problem = _setup()
    small = ["A000", "A001", "A002"]
    assert "CARDINALITY" in _validate(problem, config, small)
    assert (
        _validate(problem, config, small, reference=True, target_size=4) == ()
    )  # la referencia queda exenta
    two_new = ["A000", "A001", "A004", "A010"]
    assert "MAX_NEW_ASSETS" in _validate(problem, config, two_new, max_new_assets=1)
    assert "MAX_SWAPS" in _validate(problem, config, two_new, max_swaps=1)
    assert _validate(problem, config, two_new, max_new_assets=2, max_swaps=2) == ()


def test_duplicates_and_unknown_assets_are_reported() -> None:
    config, problem = _setup()
    assert "DUPLICATE_ASSET" in _validate(problem, config, ["A000", "A000", "A001", "A002"])
    assert _validate(problem, config, ["A000", "A001", "A002", "ZZZ"]) == ("UNKNOWN_ASSET",)


@pytest.mark.parametrize("policy", list(Policy))
def test_validator_and_eligibility_filter_agree_on_every_size_four_composition(
    policy: RestrictedExistingPositionPolicy,
) -> None:
    """Coincidencia exhaustiva (495 composiciones) entre el validador y el filtro de elegibilidad:
    válida ⇔ solo usa activos permitidos, conserva los obligatorios y tiene el tamaño objetivo."""
    config, problem = _setup(policy)
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    result = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    allowed = set(result.enterable.asset_ids)
    mandatory = {snapshot.index.asset_id_at(p) for p in result.mandatory_hold}
    checked = 0
    for combo in itertools.combinations(IDS, 4):
        expected_valid = set(combo) <= allowed and mandatory <= set(combo)
        valid = _validate(problem, config, combo, policy=policy) == ()
        assert valid == expected_valid, (policy, combo)
        checked += 1
    assert checked == 495
