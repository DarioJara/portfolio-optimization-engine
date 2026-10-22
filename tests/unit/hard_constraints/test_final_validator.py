"""HC-009: validación final obligatoria de propuestas (criterios de aceptación 1-7 y 10).

Cada caso construye una propuesta con pesos explícitos y comprueba el veredicto y **todas** las
causas de rechazo. Los valores esperados (volatilidad, concentración, retorno) se calculan en el
propio test con NumPy a partir de los pesos, sin usar el validador ni el motor.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from portfolio_engine.hard_constraints.validator import (
    FinalProposalValidator,
    volatility_tolerance,
)
from portfolio_engine.models.enums import CardinalityPolicy, CostTreatment, SolverStatus
from tests.fixtures.hard_constraints import (
    HELD,
    effective_of,
    eleven_asset_problem,
    equal_weights,
    proposal_context,
    with_mandate,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

VALIDATOR = FinalProposalValidator()
VOL = 0.20


def _sigma_vol(weights: dict[str, float]) -> float:
    """σ analítica: ``σ_i = 0,20`` y ``ρ = 0``."""
    return VOL * math.sqrt(sum(w * w for w in weights.values()))


def _validate(config, problem, weights, **kwargs):  # type: ignore[no-untyped-def]
    return VALIDATOR.validate(weights, proposal_context(config, problem), **kwargs)


@pytest.fixture(scope="module")
def problem():  # type: ignore[no-untyped-def]
    return eleven_asset_problem(base_config())


@pytest.fixture(scope="module")
def ids(problem):  # type: ignore[no-untyped-def]
    return problem.universe.asset_ids


def _codes(report) -> set[str]:  # type: ignore[no-untyped-def]
    return set(report.rejection_codes)


def test_the_original_portfolio_is_accepted_and_keeps_exactly_eleven_positions(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate(max_replacements=3, max_total_changed_assets=6)
    report = _validate(config, problem, equal_weights(ids[:HELD]))
    assert report.accepted, report.violations
    assert report.metrics is not None
    assert report.metrics.size == HELD
    assert report.metrics.added == report.metrics.removed == 0
    assert report.metrics.volatility == pytest.approx(_sigma_vol(equal_weights(ids[:HELD])))


def test_three_replacements_are_accepted_and_four_are_rejected(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate(max_replacements=3)
    three = equal_weights([*ids[: HELD - 3], *ids[HELD : HELD + 3]])
    four = equal_weights([*ids[: HELD - 4], *ids[HELD : HELD + 4]])
    accepted = _validate(config, problem, three)
    rejected = _validate(config, problem, four)
    assert accepted.accepted and accepted.metrics is not None
    assert accepted.metrics.replacements == 3 and accepted.metrics.size == HELD
    assert not rejected.accepted and rejected.metrics is not None
    assert rejected.metrics.replacements == 4
    assert "HC_REJECTED:MAX_REPLACEMENTS" in _codes(rejected)
    assert "HC_REJECTED:CARDINALITY" not in _codes(rejected)  # sigue habiendo 11 posiciones


def test_independent_additions_and_removals_are_not_replacements(problem, ids):  # type: ignore[no-untyped-def]
    """Una baja sin alta no es una sustitución: cuenta como baja independiente."""
    config = with_mandate(
        cardinality_policy=CardinalityPolicy.DECREASE, max_size_decrease=2, max_replacements=0
    )
    ten = equal_weights(ids[: HELD - 1])
    report = _validate(config, problem, ten)
    assert report.accepted, report.violations
    assert report.metrics is not None
    assert (report.metrics.removed, report.metrics.added) == (1, 0)
    assert (report.metrics.replacements, report.metrics.pure_removals) == (0, 1)
    swap = equal_weights([*ids[: HELD - 1], ids[HELD]])
    assert "HC_REJECTED:MAX_REPLACEMENTS" in _codes(_validate(config, problem, swap))


def test_forty_percent_in_one_asset_is_rejected_when_the_maximum_is_twenty(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate(max_active_weight=0.20)
    rest = 0.60 / (HELD - 1)
    weights = {ids[0]: 0.40, **{asset: rest for asset in ids[1:HELD]}}
    report = _validate(config, problem, weights)
    assert not report.accepted
    assert "HC_REJECTED:MAX_ACTIVE_WEIGHT" in _codes(report)
    offender = next(c for c in report.violations if c.check == "MAX_ACTIVE_WEIGHT")
    assert offender.value == pytest.approx(0.40) and offender.limit == 0.20
    assert offender.detail == ids[0]
    assert report.metrics is not None and report.metrics.max_position_weight == pytest.approx(0.40)


def test_volatility_below_the_minimum_is_rejected(problem, ids):  # type: ignore[no-untyped-def]
    weights = equal_weights(ids[:HELD])
    actual = _sigma_vol(weights)
    config = with_mandate(min_volatility=actual + 0.01, **_band())
    report = _validate(config, problem, weights)
    assert not report.accepted and "HC_REJECTED:MIN_VOLATILITY" in _codes(report)
    check = next(c for c in report.violations if c.check == "MIN_VOLATILITY")
    assert check.value == pytest.approx(actual)
    assert check.excess == pytest.approx(0.01)


def _band():  # type: ignore[no-untyped-def]
    from tests.fixtures.hard_constraints import BAND_PARAMS

    return dict(BAND_PARAMS)


def test_volatility_above_the_maximum_is_rejected(problem, ids):  # type: ignore[no-untyped-def]
    weights = equal_weights(ids[:HELD])
    config = with_mandate(max_volatility=_sigma_vol(weights) - 0.01)
    report = _validate(config, problem, weights)
    assert not report.accepted and "HC_REJECTED:MAX_VOLATILITY" in _codes(report)
    assert "HC_REJECTED:MIN_VOLATILITY" not in _codes(report)


def test_volatility_inside_the_band_is_accepted_and_recomputed_from_the_official_covariance(
    problem, ids
):  # type: ignore[no-untyped-def]
    weights = equal_weights(ids[:HELD])
    actual = _sigma_vol(weights)
    config = with_mandate(min_volatility=actual - 0.01, max_volatility=actual + 0.01, **_band())
    report = _validate(config, problem, weights)
    assert report.accepted, report.violations
    assert report.metrics is not None
    official = float(
        np.sqrt(
            np.array([weights.get(a, 0.0) for a in problem.risk_model.asset_ids])
            @ problem.risk_model.sigma
            @ np.array([weights.get(a, 0.0) for a in problem.risk_model.asset_ids])
        )
    )
    assert report.metrics.volatility == pytest.approx(official, rel=1e-12)


def test_a_positive_weight_below_the_per_position_minimum_is_rejected(problem, ids):  # type: ignore[no-untyped-def]
    """0,004 > umbral de posición (1e-8): cuenta como posición y viola el mínimo de 0,02."""
    config = with_mandate(min_active_weight=0.02)
    tiny = 0.004
    others = (1.0 - tiny) / (HELD - 1)
    weights = {ids[0]: tiny, **{asset: others for asset in ids[1:HELD]}}
    report = _validate(config, problem, weights)
    assert not report.accepted
    assert _codes(report) == {"HC_REJECTED:MIN_ACTIVE_WEIGHT"}
    assert report.metrics is not None and report.metrics.size == HELD


def test_weights_below_the_position_threshold_are_zero_and_never_hide_cardinality(problem, ids):  # type: ignore[no-untyped-def]
    """Diez posiciones reales más pesos diminutos: no son posiciones, pero su masa se vigila."""
    config = with_mandate(position_weight_threshold=1e-6)
    ten = list(ids[: HELD - 1])
    weights = {asset: (1.0 - 5e-6) / len(ten) for asset in ten}
    weights.update({asset: 1e-6 for asset in ids[HELD : HELD + 5]})  # = umbral: no es posición
    report = _validate(config, problem, weights)
    assert report.metrics is not None and report.metrics.size == HELD - 1
    assert "HC_REJECTED:CARDINALITY" in _codes(report)
    assert "HC_REJECTED:DUST_MASS" in _codes(report)  # 5e-6 de masa en pesos no contados


def test_cardinality_counts_real_positions_not_listed_assets(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate()
    nine_real_plus_two_zero = {
        **equal_weights(ids[: HELD - 2]),
        ids[HELD - 2]: 0.0,
        ids[HELD - 1]: 0.0,
    }
    report = _validate(config, problem, nine_real_plus_two_zero)
    assert not report.accepted and "HC_REJECTED:CARDINALITY" in _codes(report)
    assert report.metrics is not None and report.metrics.size == HELD - 2


def test_concentration_hhi_and_effective_number_of_positions(problem, ids):  # type: ignore[no-untyped-def]
    weights = {ids[0]: 0.30, **{asset: 0.70 / (HELD - 1) for asset in ids[1:HELD]}}
    hhi = sum(w * w for w in weights.values())
    ok = _validate(with_mandate(max_concentration_hhi=hhi + 0.01), problem, weights)
    assert ok.accepted, ok.violations
    over = _validate(with_mandate(max_concentration_hhi=hhi - 0.01), problem, weights)
    assert _codes(over) == {"HC_REJECTED:MAX_HHI"}
    neff = _validate(
        with_mandate(min_effective_number_of_positions=1.0 / hhi + 0.5), problem, weights
    )
    assert _codes(neff) == {"HC_REJECTED:MIN_EFFECTIVE_POSITIONS"}
    assert neff.metrics is not None
    assert neff.metrics.effective_positions == pytest.approx(1.0 / hhi)


def test_expected_return_must_not_fall_below_the_original_when_configured(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate(
        preserve_original_expected_return=True, expected_return_treatment=CostTreatment.GROSS
    )
    mu = dict(zip(problem.risk_model.asset_ids, problem.risk_model.mu.tolist(), strict=True))
    original = sum(mu[a] / HELD for a in ids[:HELD])
    # μ crece con el índice: sustituir el último activo por uno de mayor μ mejora el retorno
    better = equal_weights([*ids[: HELD - 1], ids[HELD + 4]])
    assert sum(mu[a] * w for a, w in better.items()) > original
    assert _validate(config, problem, better).accepted
    # mismas 11 posiciones inclinadas hacia los activos de menor μ: el retorno cae por debajo
    tilt = {ids[i]: (1.0 + 0.5 * (5 - i) / 5) / HELD for i in range(HELD)}
    assert sum(tilt.values()) == pytest.approx(1.0)
    report = _validate(config, problem, tilt)
    assert _codes(report) == {"HC_REJECTED:MIN_EXPECTED_RETURN"}
    assert report.metrics is not None and report.metrics.size == HELD
    assert report.metrics.original_expected_return == pytest.approx(original)
    assert report.metrics.expected_return_gross < original


def test_an_absolute_expected_return_floor_and_net_treatment(problem, ids):  # type: ignore[no-untyped-def]
    weights = equal_weights(ids[:HELD])
    mu = problem.risk_model.mu
    gross = float(sum(mu[i] / HELD for i in range(HELD)))
    ok = with_mandate(
        min_expected_return=gross - 0.001, expected_return_treatment=CostTreatment.GROSS
    )
    assert _validate(ok, problem, weights).accepted
    bad = with_mandate(
        min_expected_return=gross + 0.001, expected_return_treatment=CostTreatment.GROSS
    )
    assert _codes(_validate(bad, problem, weights)) == {"HC_REJECTED:MIN_EXPECTED_RETURN"}
    net = with_mandate(
        min_expected_return=gross - 1e-9, expected_return_treatment=CostTreatment.NET
    )
    swapped = equal_weights(
        [*ids[: HELD - 1], ids[HELD]]
    )  # compra y venta: el coste reduce el neto
    report = _validate(net, problem, swapped)
    assert report.metrics is not None and report.metrics.expected_return_net is not None
    assert report.metrics.expected_return_net < report.metrics.expected_return_gross


def test_turnover_and_transaction_cost_are_recomputed_including_full_liquidations(problem, ids):  # type: ignore[no-untyped-def]
    weights = equal_weights([*ids[: HELD - 1], ids[HELD]])
    report = _validate(with_mandate(), problem, weights)
    assert report.metrics is not None
    assert report.metrics.turnover == pytest.approx(1.0 / HELD)  # 0,5·(1/11 + 1/11)
    assert report.metrics.transaction_cost_one_off is not None
    assert report.metrics.transaction_cost_one_off > 0.0
    over = _validate(with_mandate(max_transaction_cost=1e-9), problem, weights)
    assert "HC_REJECTED:MAX_TRANSACTION_COST" in _codes(over)


def test_unacceptable_solver_states_reject_the_proposal(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate()
    weights = equal_weights(ids[:HELD])
    assert _validate(config, problem, weights, solver_status=SolverStatus.OPTIMAL).accepted
    for status in (SolverStatus.INFEASIBLE, SolverStatus.NUMERICAL_ERROR, SolverStatus.UNKNOWN):
        report = _validate(config, problem, weights, solver_status=status)
        assert not report.accepted and "HC_REJECTED:SOLVER_STATUS" in _codes(report)
    inaccurate = _validate(config, problem, weights, solver_status=SolverStatus.OPTIMAL_INACCURATE)
    assert not inaccurate.accepted  # accept_inaccurate_solutions = false en la configuración


def test_all_rejection_causes_are_recorded_not_only_the_first(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate(max_active_weight=0.20, max_replacements=1, max_volatility=0.05)
    weights = {
        ids[0]: 0.50,
        **{asset: 0.50 / 9 for asset in [*ids[1:8], ids[HELD], ids[HELD + 1]]},
    }
    report = _validate(config, problem, weights)
    assert {
        "HC_REJECTED:MAX_ACTIVE_WEIGHT",
        "HC_REJECTED:MAX_REPLACEMENTS",
        "HC_REJECTED:MAX_VOLATILITY",
    } <= _codes(report)
    assert len(report.rejection_codes) == len(set(report.rejection_codes))


def test_non_finite_and_unbalanced_weights_are_rejected(problem, ids):  # type: ignore[no-untyped-def]
    config = with_mandate()
    nan = {**equal_weights(ids[:HELD]), ids[0]: float("nan")}
    report = _validate(config, problem, nan)
    assert not report.accepted and "HC_REJECTED:FINITE" in _codes(report)
    unbalanced = {asset: 0.5 / HELD for asset in ids[:HELD]}
    assert "HC_REJECTED:BUDGET" in _codes(_validate(config, problem, unbalanced))
    negative = {**equal_weights(ids[: HELD - 1]), ids[HELD - 1]: -0.01}
    assert "HC_REJECTED:LONG_ONLY" in _codes(_validate(config, problem, negative))


def test_the_volatility_tolerance_is_bounded_by_the_band_width(problem):  # type: ignore[no-untyped-def]
    """Una tolerancia numérica no puede hacer aceptable una violación material."""
    narrow = with_mandate(min_volatility=0.0600, max_volatility=0.0600 + 2e-7, **_band())
    effective = effective_of(narrow, problem)
    assert effective.volatility_tolerance == 1e-7  # solver.constraint_tolerance
    assert volatility_tolerance(effective) == pytest.approx(2e-9)  # 1 % del ancho
    wide = with_mandate(min_volatility=0.05, max_volatility=0.10, **_band())
    assert volatility_tolerance(effective_of(wide, problem)) == 1e-7


def test_eligibility_and_mandate_of_the_final_composition_are_checked_from_raw_data(problem, ids):  # type: ignore[no-untyped-def]
    """Un activo no elegible que entra se rechaza aunque el solver lo hubiera aceptado."""
    blocked = eleven_asset_problem(
        base_config(),
        universe_overrides={"EligibleFlag": [i != HELD for i in range(16)]},
    )
    ids_blocked = blocked.universe.asset_ids
    config = with_mandate(max_replacements=3)
    weights = equal_weights([*ids_blocked[: HELD - 1], ids_blocked[HELD]])
    report = _validate(config, blocked, weights)
    assert not report.accepted and "HC_REJECTED:ELIGIBILITY" in _codes(report)
    check = next(c for c in report.violations if c.check == "ELIGIBILITY")
    assert "NEW_ASSET_NOT_ELIGIBLE" in check.detail
