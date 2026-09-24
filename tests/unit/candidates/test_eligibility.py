"""CAN-013, CON-013, CON-022 (traducción en la búsqueda): ``EligibilityFilter``.

Escenario de 12 activos con todos los roles: mantenido libre (A), obligatorio (C), solo liquidable
(D), salida obligatoria, elegible nuevo (B) y excluido (E), según ``EligibleFlag``,
``LiquidityFlag``, ``RestrictedAssetFlag``, ``InvestmentUniverse`` y la política de restringidos.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.candidates import EligibilityFilter, UniverseSnapshot
from portfolio_engine.exceptions import CandidateError
from portfolio_engine.models.enums import (
    EligibilityReason,
    EligibilityStatus,
    RestrictedExistingPositionPolicy,
    UnknownFlagPolicy,
)
from tests.fixtures.candidates import ROLES_HELD, ROLES_N, roles_problem, with_candidates
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    make_problem,
    policy_config,
    risk_model,
    spec_with,
)

pytestmark = pytest.mark.unit

N = ROLES_N
Status, Reason, Policy = EligibilityStatus, EligibilityReason, RestrictedExistingPositionPolicy
HELD = list(ROLES_HELD)
MU = np.linspace(0.04, 0.12, N)
SIGMA = cov_from_vol_corr([0.2] * N, np.full((N, N), 0.3) + 0.7 * np.eye(N))
OVERRIDES = {
    "EligibleFlag": [i not in (1, 5) for i in range(N)],
    "LiquidityFlag": [None if i == 8 else i not in (3, 6) for i in range(N)],
    "RestrictedAssetFlag": [None if i == 9 else i in (2, 7) for i in range(N)],
    "MaxWeight": [1.0] * N,
}


def _classify(config, *, spec=None):  # type: ignore[no-untyped-def]
    problem = roles_problem(config, spec)
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    result = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    return problem, result


def _status(result, position):  # type: ignore[no-untyped-def]
    return result.status[position]


def test_roles_under_hold_or_reduce() -> None:
    _, result = _classify(policy_config(base_config(), Policy.HOLD_OR_REDUCE))
    expected = {
        0: Status.HELD,
        1: Status.LIQUIDATE_ONLY,  # no elegible pero mantenido: puede conservarse o venderse
        2: Status.LIQUIDATE_ONLY,  # restringido, HOLD_OR_REDUCE: mantener o reducir, nunca comprar
        3: Status.LIQUIDATE_ONLY,  # ilíquido mantenido
        4: Status.ELIGIBLE_NEW,
        5: Status.EXCLUDED,
        6: Status.EXCLUDED,
        7: Status.EXCLUDED,
        8: Status.EXCLUDED,  # LiquidityFlag desconocido con política EXCLUDE
        9: Status.EXCLUDED,
        10: Status.ELIGIBLE_NEW,
        11: Status.ELIGIBLE_NEW,
    }
    assert dict(enumerate(result.status)) == expected
    # Ningún activo no elegible/restringido/ilíquido puede introducirse como posición nueva.
    assert result.enterable.global_indices.tolist() == [0, 1, 2, 3, 4, 10, 11]
    assert not result.mandatory_hold and not result.mandatory_exit
    assert result.held_positions.tolist() == HELD


def test_held_non_eligible_asset_is_not_liquidated_automatically() -> None:
    """D: se puede conservar (está entre los activos que pueden formar composiciones)."""
    _, result = _classify(base_config())
    assert Status.LIQUIDATE_ONLY is _status(result, 1)
    assert result.enterable.contains_global(1) and not result.purchasable[1]


def test_freeze_weight_makes_the_held_restricted_asset_mandatory() -> None:
    _, result = _classify(policy_config(base_config(), Policy.FREEZE_WEIGHT))
    assert _status(result, 2) is Status.MANDATORY_HOLD
    assert result.mandatory_hold == frozenset({2}) and not result.mandatory_exit
    assert result.enterable.contains_global(2)
    assert Reason.FREEZE_WEIGHT in result.reasons[2]


def test_force_liquidate_removes_the_asset_from_every_composition() -> None:
    _, result = _classify(policy_config(base_config(), Policy.FORCE_LIQUIDATE))
    assert _status(result, 2) is Status.MANDATORY_EXIT
    assert result.mandatory_exit == frozenset({2}) and not result.mandatory_hold
    assert not result.enterable.contains_global(2)
    assert Reason.FORCE_LIQUIDATE in result.reasons[2]


def test_the_policy_is_read_from_the_spec_first_then_from_the_configuration() -> None:
    config = policy_config(base_config(), Policy.HOLD_OR_REDUCE)
    spec = spec_with(restricted_existing_position_policy=Policy.FREEZE_WEIGHT)
    _, result = _classify(config, spec=spec)
    assert (
        result.mandatory_hold == frozenset({2}) and result.restricted_policy is Policy.FREEZE_WEIGHT
    )


def test_held_restricted_asset_without_a_policy_is_an_error() -> None:
    config = base_config()
    config = dataclasses.replace(
        config,
        constraints=dataclasses.replace(
            config.constraints, restricted_existing_position_policy=None
        ),
    )
    with pytest.raises(CandidateError, match="RestrictedExistingPositionPolicy"):
        _classify(config)


def test_exclusion_reasons_are_explicit() -> None:
    _, result = _classify(base_config())
    assert result.reasons[5] == (Reason.NOT_ELIGIBLE,)
    assert result.reasons[6] == (Reason.NOT_LIQUID,)
    assert result.reasons[7] == (Reason.RESTRICTED,)
    assert result.reasons[8] == (Reason.UNKNOWN_LIQUIDITY_FLAG,)
    assert result.reasons[9] == (Reason.UNKNOWN_RESTRICTED_FLAG,)
    assert Reason.NOT_ELIGIBLE in result.reasons[1] and Reason.NOT_LIQUID in result.reasons[3]
    assert Reason.RESTRICTED in result.reasons[2]
    assert result.reasons[0] == () and result.reasons[4] == ()


def test_unknown_liquidity_flag_policy_is_explicit() -> None:
    config = policy_config(base_config(), Policy.HOLD_OR_REDUCE)
    allow = with_candidates(config, unknown_liquidity_policy=UnknownFlagPolicy.ALLOW)
    _, result = _classify(allow)
    assert _status(result, 8) is Status.ELIGIBLE_NEW
    error = with_candidates(config, unknown_liquidity_policy=UnknownFlagPolicy.ERROR)
    with pytest.raises(CandidateError, match="LiquidityFlag desconocido"):
        _classify(error)


def test_investment_universe_restricts_new_purchases_but_not_held_positions() -> None:
    config = policy_config(base_config(), Policy.HOLD_OR_REDUCE)
    allowed = tuple(f"A{i:03d}" for i in range(N) if i not in (10, 11))
    spec = spec_with(investment_universe=allowed)
    _, result = _classify(config, spec=spec)
    assert _status(result, 10) is Status.EXCLUDED and _status(result, 11) is Status.EXCLUDED
    assert Reason.OUTSIDE_INVESTMENT_UNIVERSE in result.reasons[10]
    assert _status(result, 4) is Status.ELIGIBLE_NEW
    # Un activo mantenido fuera del InvestmentUniverse no se liquida automáticamente.
    narrow = spec_with(investment_universe=("A004",))
    _, result = _classify(config, spec=narrow)
    assert _status(result, 0) is Status.LIQUIDATE_ONLY and result.enterable.contains_global(0)
    assert _status(result, 4) is Status.ELIGIBLE_NEW and _status(result, 11) is Status.EXCLUDED


def test_counts_cover_every_status_and_add_up() -> None:
    _, result = _classify(policy_config(base_config(), Policy.HOLD_OR_REDUCE))
    counts = dict(result.counts())
    assert sum(counts.values()) == N
    assert counts[Status.ELIGIBLE_NEW.value] == 3 and counts[Status.EXCLUDED.value] == 5
    assert counts[Status.LIQUIDATE_ONLY.value] == 3 and counts[Status.HELD.value] == 1
    assert result.positions_with(Status.ELIGIBLE_NEW).tolist() == [4, 10, 11]


def test_assets_without_risk_data_are_reported_and_held_ones_are_an_error() -> None:
    config = policy_config(base_config(), Policy.HOLD_OR_REDUCE)
    problem = make_problem(
        MU, SIGMA, [0.25] * 4 + [0.0] * (N - 4), config, universe_overrides=OVERRIDES
    )
    partial = risk_model(MU[:-1], SIGMA[:-1, :-1], config, problem.risk_model.asset_ids[:-1])
    snapshot = UniverseSnapshot.build(partial, problem.universe, problem.costs)
    assert snapshot.universe_only_ids == ("A011",) and snapshot.size == N - 1
    result = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    assert result.universe_only_ids == ("A011",) and len(result.status) == N - 1
    without_held = risk_model(MU[1:], SIGMA[1:, 1:], config, problem.risk_model.asset_ids[1:])
    with pytest.raises(CandidateError, match="sin datos en el modelo de riesgo"):
        EligibilityFilter(config.candidates, config.constraints).apply(
            UniverseSnapshot.build(without_held, problem.universe, problem.costs),
            problem.state,
            problem.spec,
        )
