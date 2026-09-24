"""CON-012, FEA-006, CFG-005 (A-11): restricción ADV/NAV con posición existente protegida.

``LiquidityCapacity = p · ADV · días / NAV`` (constantes de ``tests/fixtures/liquidity.py``:
``p = 0,10``, ``días = 5``, ``NAV = 1e8``, ``ADV_A000 = 2e7`` ⇒ 0,10, calculado a mano). Posición
nueva: ``w <= capacidad``; posición existente: ``w <= max(w_current, capacidad)``.
"""

from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path

import numpy as np
import pytest

from portfolio_engine.config import FxRate, LiquidityConfig, load_engine_config
from portfolio_engine.constraints import (
    ConstraintCompiler,
    PreFeasibilityChecker,
    build_constraint_set,
)
from portfolio_engine.constraints.feasibility import minimum_forced_turnover
from portfolio_engine.data.validation import UniverseValidator
from portfolio_engine.exceptions import ConfigError, ConstraintCompilationError, DataValidationError
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy
from portfolio_engine.validation import SolutionValidator, ValidationContext, ValidationTolerances
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.liquidity import (
    ADV_A000,
    ADV_OTHERS,
    CAPACITY_A000,
    liquidity_config,
    liquidity_problem,
)
from tests.fixtures.problems import base_config, policy_config, restricted_universe, spec_with
from tests.fixtures.synthetic import universe_frame

pytestmark = pytest.mark.unit

Policy = RestrictedExistingPositionPolicy
NEW = [0.0, 0.5, 0.5, 0.0]  # A000 no está en cartera
HELD_BELOW = [0.05, 0.95, 0.0, 0.0]  # 0,05 < capacidad 0,10
HELD_ABOVE = [0.20, 0.80, 0.0, 0.0]  # 0,20 > capacidad 0,10
NEW_COMPOSITION = ("A000", "A001", "A002")
ADV_USD = ["USD", "EUR", "EUR", "EUR"]


def _compile(config, problem):  # type: ignore[no-untyped-def]
    constraint_set = build_constraint_set(
        config.constraints,
        problem.spec,
        "P1",
        config.frontier.min_holding_weight,
        config.candidates.unknown_liquidity_policy,
    )
    composition = problem.composition_asset_ids or problem.state.asset_ids
    return ConstraintCompiler().compile(
        constraint_set, problem.universe, composition, problem.state
    )


def _checks(config, compiled, weights):  # type: ignore[no-untyped-def]
    validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
    n = compiled.size
    context = ValidationContext(np.full(n, 0.05), np.eye(n) * 0.01, None)
    report = validator.validate(np.asarray(weights), compiled, context)
    return report, {v.constraint_id for v in report.violations}


# ------------------------------------------------------------ casos 1-7: nuevas y existentes


def test_1_a_new_position_below_the_limit_is_allowed() -> None:
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    compiled = _compile(config, problem)
    assert compiled.upper[0] == pytest.approx(CAPACITY_A000)
    _, violated = _checks(config, compiled, [0.05, 0.5, 0.45])
    assert not any(v.startswith("LIQUIDITY_CAP") for v in violated)
    rule = next(r for r in compiled.liquidity_rules if r.asset_id == "A000")
    assert not rule.is_held and rule.capacity == pytest.approx(0.10) and rule.fx_rate is None


def test_2_a_new_position_above_the_limit_is_rejected() -> None:
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    compiled = _compile(config, problem)
    _, violated = _checks(config, compiled, [0.15, 0.5, 0.35])
    assert "LIQUIDITY_CAP:A000:capacity" in violated


def test_3_a_held_position_below_the_limit_may_grow_up_to_the_capacity() -> None:
    config, problem = liquidity_problem(HELD_BELOW)
    compiled = _compile(config, problem)
    assert compiled.upper[0] == pytest.approx(0.10)  # max(0,05, 0,10)
    assert not any(v.startswith("LIQUIDITY") for v in _checks(config, compiled, [0.10, 0.90])[1])
    _, violated = _checks(config, compiled, [0.12, 0.88])
    assert "LIQUIDITY_CAP:A000:no_increase_above_capacity" in violated


def test_4_a_held_position_above_the_limit_is_not_forced_out() -> None:
    config, problem = liquidity_problem(HELD_ABOVE)
    compiled = _compile(config, problem)
    assert compiled.lower[0] == 0.0
    assert compiled.upper[0] == pytest.approx(0.20)  # max(0,20, 0,10): no obliga a vender
    rule = next(r for r in compiled.liquidity_rules if r.asset_id == "A000")
    assert rule.is_held and rule.capacity == pytest.approx(0.10)


def test_5_a_held_position_above_the_limit_cannot_be_increased() -> None:
    config, problem = liquidity_problem(HELD_ABOVE)
    compiled = _compile(config, problem)
    _, violated = _checks(config, compiled, [0.25, 0.75])
    assert "LIQUIDITY_CAP:A000:no_increase_above_capacity" in violated


@pytest.mark.parametrize("weight", [0.20, 0.15, 0.10, 0.0])
def test_6_and_7_a_held_position_above_the_limit_may_be_kept_or_reduced(weight: float) -> None:
    config, problem = liquidity_problem(HELD_ABOVE)
    compiled = _compile(config, problem)
    report, violated = _checks(config, compiled, [weight, 1.0 - weight])
    assert not any(v.startswith(("LIQUIDITY", "BOUNDS")) for v in violated), report.violations


def test_the_validator_does_not_rely_on_the_compiled_upper_bound() -> None:
    config, problem = liquidity_problem(HELD_ABOVE)
    compiled = _compile(config, problem)
    tampered = dataclasses.replace(compiled, upper=np.array([1.0, 1.0]))
    _, violated = _checks(config, tampered, [0.25, 0.75])
    assert "BOUNDS:A000:upper" not in violated
    assert "LIQUIDITY_CAP:A000:no_increase_above_capacity" in violated


# ------------------------------------------------------------------ 8: ADV = 0, 9: NAV inválido


def test_8_zero_adv_blocks_entry_but_keeps_a_held_position() -> None:
    config, new = liquidity_problem(NEW, adv_a000=0.0, composition=NEW_COMPOSITION)
    assert _compile(config, new).upper[0] == 0.0
    config, held = liquidity_problem(HELD_ABOVE, adv_a000=0.0)
    assert _compile(config, held).upper[0] == pytest.approx(0.20)  # capacidad 0: solo reduce


@pytest.mark.parametrize("nav", [0.0, -1e8, float("nan"), float("inf")])
def test_9_an_invalid_nav_is_rejected_by_the_portfolio_spec(nav: float) -> None:
    with pytest.raises(DataValidationError, match="NAV"):
        spec_with(nav=nav)


def test_9_a_missing_nav_with_the_constraint_enabled_is_an_error_not_a_silent_skip() -> None:
    config, problem = liquidity_problem(NEW, nav=None, composition=NEW_COMPOSITION)
    with pytest.raises(ConstraintCompilationError, match="NAV"):
        _compile(config, problem)
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    with pytest.raises(ConstraintCompilationError, match="NAV"):
        _compile(config, dataclasses.replace(problem, spec=None))


def test_a_missing_adv_with_the_constraint_enabled_is_an_error() -> None:
    config, problem = liquidity_problem(
        NEW, composition=NEW_COMPOSITION, overrides={"ADV": [None, 1e9, 1e9, 1e9]}
    )
    with pytest.raises(ConstraintCompilationError, match="ADV"):
        _compile(config, problem)


def test_a_negative_adv_is_rejected_when_the_universe_is_loaded() -> None:
    frame = universe_frame(4, ADV=[-1.0, 1e9, 1e9, 1e9])
    with pytest.raises(DataValidationError):
        UniverseValidator(base_config().constraints).validate(frame)


# ------------------------------------------------------- 10, 11, 14: configuración inválida


@pytest.mark.parametrize("participation", [0.0, -0.1, 1.5, float("nan"), float("inf")])
def test_10_invalid_participation_is_rejected(participation: float) -> None:
    with pytest.raises(ConfigError, match="max_adv_participation"):
        LiquidityConfig(True, participation, 5.0, ())


@pytest.mark.parametrize("days", [0.0, 0.5, -3.0, float("nan"), float("inf")])
def test_11_invalid_liquidation_days_are_rejected(days: float) -> None:
    with pytest.raises(ConfigError, match="liquidation_days"):
        LiquidityConfig(True, 0.1, days, ())


def test_valid_boundary_values_are_accepted() -> None:
    LiquidityConfig(True, 1.0, 1.0, ())  # p = 1 y días = 1 son válidos


@pytest.mark.parametrize(("participation", "days"), [(None, 5.0), (0.1, None), (None, None)])
def test_14_enabled_with_incomplete_parameters_is_a_configuration_error(
    participation, days
) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ConfigError, match="enabled = true"):
        LiquidityConfig(True, participation, days, ())


def _raw_config():  # type: ignore[no-untyped-def]
    return tomllib.loads(Path(DEFAULT_CONFIG_PATH).read_text(encoding="utf-8"))


def test_14_the_loader_rejects_an_enabled_section_without_parameters() -> None:
    raw = _raw_config()
    raw["constraints"]["liquidity"] = {"enabled": True, "fx_rates": []}
    with pytest.raises(ConfigError, match="enabled = true"):
        load_engine_config(raw)


def test_the_default_configuration_has_no_productive_values_and_the_constraint_disabled() -> None:
    liquidity = load_engine_config(_raw_config()).constraints.liquidity
    assert liquidity.enabled is False
    assert liquidity.max_adv_participation is None and liquidity.liquidation_days is None
    assert liquidity.fx_rates == ()


def test_the_loader_reads_an_explicit_section_and_fx_rates() -> None:
    raw = _raw_config()
    raw["constraints"]["liquidity"] = {
        "enabled": True,
        "max_adv_participation": 0.2,
        "liquidation_days": 3,
        "fx_rates": [{"from_currency": "USD", "to_currency": "EUR", "rate": 0.5}],
    }
    liquidity = load_engine_config(raw).constraints.liquidity
    assert (liquidity.max_adv_participation, liquidity.liquidation_days) == (0.2, 3.0)
    assert liquidity.rate_for("USD", "EUR") == 0.5 and liquidity.rate_for("EUR", "USD") is None


def test_disabled_means_the_constraint_is_not_applied() -> None:
    config = liquidity_config(None, None, enabled=False)
    config, problem = liquidity_problem(NEW, config, composition=NEW_COMPOSITION, nav=None)
    compiled = _compile(config, problem)
    assert compiled.liquidity_rules == () and compiled.upper[0] == pytest.approx(1.0)


@pytest.mark.parametrize("rate", [0.0, -1.0, float("nan")])
def test_invalid_fx_rates_are_rejected(rate: float) -> None:
    with pytest.raises(ConfigError):
        FxRate("USD", "EUR", rate)


# ------------------------------------------------------------------------ 12, 13: divisas


def test_12_adv_in_another_currency_is_converted_with_the_explicit_rate() -> None:
    """ADV_A000 = 4e7 USD, NAV en EUR, 1 USD = 0,5 EUR ⇒ 2e7 EUR ⇒ 0,10·2e7·5/1e8 = 0,10."""
    config = liquidity_config(fx=(FxRate("USD", "EUR", 0.5),))
    config, problem = liquidity_problem(
        NEW,
        config,
        adv_a000=4e7,
        nav_currency="EUR",
        composition=NEW_COMPOSITION,
        overrides={"ADVCurrency": ADV_USD},
    )
    compiled = _compile(config, problem)
    assert compiled.upper[0] == pytest.approx(0.10)
    rule = next(r for r in compiled.liquidity_rules if r.asset_id == "A000")
    assert rule.fx_rate == 0.5 and rule.adv == 4e7  # trazable: ADV original y tipo usado


def test_12_the_same_declared_currency_needs_no_rate() -> None:
    config, problem = liquidity_problem(
        NEW, nav_currency="EUR", composition=NEW_COMPOSITION, overrides={"ADVCurrency": ["EUR"] * 4}
    )
    assert _compile(config, problem).upper[0] == pytest.approx(0.10)


def test_13_a_currency_mismatch_without_fx_is_rejected() -> None:
    config, problem = liquidity_problem(
        NEW, nav_currency="EUR", composition=NEW_COMPOSITION, overrides={"ADVCurrency": ADV_USD}
    )
    with pytest.raises(ConstraintCompilationError, match="tipo de cambio"):
        _compile(config, problem)
    inverse = liquidity_config(fx=(FxRate("EUR", "USD", 2.0),))  # solo el par exacto vale
    config, problem = liquidity_problem(
        NEW,
        inverse,
        nav_currency="EUR",
        composition=NEW_COMPOSITION,
        overrides={"ADVCurrency": ADV_USD},
    )
    with pytest.raises(ConstraintCompilationError, match="tipo de cambio"):
        _compile(config, problem)


def test_13_only_one_of_the_two_currencies_declared_is_rejected() -> None:
    config, problem = liquidity_problem(NEW, nav_currency=None, composition=NEW_COMPOSITION)
    with pytest.raises(ConstraintCompilationError, match="obligatorias"):
        _compile(config, problem)


def test_the_universe_loader_reads_adv_currency() -> None:
    frame = universe_frame(4, ADVCurrency=["USD", "EUR", None, "EUR"])
    universe = UniverseValidator(base_config().constraints).validate(frame).universe
    assert [universe.get(f"A00{i}").adv_currency for i in range(4)] == ["USD", "EUR", None, "EUR"]


# ---------------------------------------------------------------- 15, 16, 17: E-09 y E-10


@pytest.mark.parametrize(
    ("policy", "bounds"),
    [
        (Policy.HOLD_OR_REDUCE, (0.0, 0.20)),
        (Policy.FREEZE_WEIGHT, (0.20, 0.20)),
        (Policy.FORCE_LIQUIDATE, (0.0, 0.0)),
    ],
)
def test_15_16_17_restricted_policies_keep_precedence_over_the_liquidity_cap(
    policy, bounds
) -> None:  # type: ignore[no-untyped-def]
    config = policy_config(liquidity_config(), policy)
    config, problem = liquidity_problem(HELD_ABOVE, config, overrides=restricted_universe(4, [0]))
    compiled = _compile(config, problem)
    assert (compiled.lower[0], compiled.upper[0]) == pytest.approx(bounds)
    # F-4: el activo restringido también valida sus datos ADV/NAV (E-09 no exime); la política manda
    assert any(rule.asset_id == "A000" for rule in compiled.liquidity_rules)


def test_e10_stays_stricter_than_the_liquidity_cap_for_a_non_buyable_position() -> None:
    blocked = {"EligibleFlag": [False, True, True, True]}
    below = liquidity_problem(HELD_BELOW, overrides=blocked)
    assert _compile(*below).upper[0] == pytest.approx(0.05)  # E-10: min(w_current, MaxWeight)
    above = liquidity_problem(HELD_ABOVE, overrides=blocked)
    assert _compile(*above).upper[0] == pytest.approx(0.20)


# ------------------------------------------------------------------------ 18: MaxTurnover


def test_18_no_forced_sale_means_max_turnover_zero_is_still_feasible() -> None:
    spec = spec_with(nav=1e8, nav_currency="EUR", max_turnover=0.0)
    config, problem = liquidity_problem([0.20, 0.50, 0.30, 0.0], spec=spec)
    compiled = _compile(config, problem)
    # calculado a mano: ninguna posición supera su tope ⇒ turnover mínimo forzado 0
    assert minimum_forced_turnover(compiled) == pytest.approx(0.0)
    report = PreFeasibilityChecker(config.solver.constraint_tolerance).check(compiled)
    assert report.feasible, report.causes


# ------------------------------------------------------------------ FEA-006 (check_liquidity)


def test_liquidity_rules() -> None:
    """FEA-006: incompatibilidades detectadas antes del solver, con causa y activos."""
    checker = PreFeasibilityChecker(base_config().solver.constraint_tolerance)
    # (a) mínimo 0,30 > capacidad 0,10 de una posición nueva
    config, problem = liquidity_problem(
        NEW, composition=NEW_COMPOSITION, overrides={"MinWeight": [0.30, 0.0, 0.0, 0.0]}
    )
    codes = {c.code for c in checker.check(_compile(config, problem)).causes}
    assert "LIQUIDITY_CAP_BELOW_MIN_WEIGHT" in codes
    # (b) dos activos nuevos de capacidad 0,10 no pueden sumar el presupuesto
    config, problem = liquidity_problem(
        NEW,
        composition=("A000", "A003"),
        overrides={"ADV": [ADV_A000, ADV_OTHERS, ADV_OTHERS, ADV_A000]},
    )
    report = checker.check(_compile(config, problem))
    assert not report.feasible
    detail = next(c.detail for c in report.causes if c.code == "LIQUIDITY_CAPS_BELOW_BUDGET")
    assert "A000" in detail and "A003" in detail
    # (c) caso factible: sin causas de liquidez
    config, problem = liquidity_problem(HELD_ABOVE)
    assert checker.check(_compile(config, problem)).feasible
