"""CON-012, FEA-006 (F-1, F-2, F-4 de AUDIT_BLOCK_3_CLOSURE): contrato de datos de ADV/NAV.

``ADV`` es exclusivamente un **importe monetario medio negociado por día** (``NOTIONAL_PER_DAY``);
``ADVCurrency`` y ``NAVCurrency`` son obligatorias; FX = unidades de ``NAVCurrency`` por unidad de
``ADVCurrency`` (``ADV_en_NAV = ADV · FX``). Valores esperados calculados a mano: ``p = 0,10``,
``días = 5``, ``NAV = 1e8`` ⇒ ``ADV = 2e7`` da capacidad 0,10; ``1e8 USD × 0,90 = 9e7 EUR`` da 0,45.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.candidates import CandidateEngine
from portfolio_engine.config import FxRate
from portfolio_engine.constraints import liquidity as liquidity_module
from portfolio_engine.constraints.liquidity import liquidity_capacity
from portfolio_engine.data.validation import UniverseValidator
from portfolio_engine.exceptions import ConstraintCompilationError, DataValidationError
from portfolio_engine.frontiers import ContinuousFrontierEngine, GlobalCandidateFrontierEngine
from portfolio_engine.models.asset import AssetMetadata, Universe
from portfolio_engine.models.enums import (
    AdvUnit,
    CostTreatment,
    FrontierMethod,
    RestrictedExistingPositionPolicy,
)
from portfolio_engine.validation import SolutionValidator, ValidationContext, ValidationTolerances
from tests.fixtures.candidates import context_of, search
from tests.fixtures.liquidity import liquidity_config, liquidity_problem
from tests.fixtures.problems import base_config, policy_config, restricted_universe
from tests.fixtures.synthetic import universe_frame
from tests.unit.constraints.test_liquidity_capacity import _compile

pytestmark = pytest.mark.unit

NEW = [0.0, 0.5, 0.5, 0.0]
HELD = [0.10, 0.90, 0.0, 0.0]
NEW_COMPOSITION = ("A000", "A001", "A002")
FRONTIER = (CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)


def _with_asset(problem, **changes):  # type: ignore[no-untyped-def]
    """Problema con ``A000`` modificado directamente (sin pasar por el cargador)."""
    assets = [
        dataclasses.replace(a, **changes) if a.asset_id == "A000" else a for a in problem.universe
    ]
    return dataclasses.replace(problem, universe=Universe(assets))


# ------------------------------------------------------------------------ F-1: unidad de ADV


def test_a_notional_adv_gives_the_hand_computed_dimensionless_weight() -> None:
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    compiled = _compile(config, problem)
    assert compiled.upper[0] == pytest.approx(0.10)  # 0,10 · 2e7 EUR/día · 5 días / 1e8 EUR
    rule = compiled.liquidity_rules[0]
    assert rule.adv_unit is AdvUnit.NOTIONAL_PER_DAY and rule.adv_source == "TEST_FEED"


@pytest.mark.parametrize("unit", [AdvUnit.SHARES_PER_DAY, AdvUnit.CONTRACTS_PER_DAY])
def test_adv_in_shares_or_contracts_is_rejected_without_implicit_conversion(unit) -> None:  # type: ignore[no-untyped-def]
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    problem = _with_asset(problem, adv_unit=unit)
    with pytest.raises(ConstraintCompilationError, match=f"{unit.value}.*no es un importe"):
        _compile(config, problem)


def test_a_missing_adv_unit_is_rejected() -> None:
    config, problem = liquidity_problem(
        NEW, composition=NEW_COMPOSITION, overrides={"ADVUnit": [None] * 4}
    )
    with pytest.raises(ConstraintCompilationError, match="sin unidad de ADV"):
        _compile(config, problem)


def test_an_unknown_adv_unit_is_rejected_by_the_loader_and_by_direct_construction() -> None:
    frame = universe_frame(4, ADVUnit=["NOTIONAL_PER_DAY", "BOGUS", "NOTIONAL_PER_DAY", None])
    with pytest.raises(DataValidationError):
        UniverseValidator(base_config().constraints).validate(frame)
    _, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    with pytest.raises(DataValidationError, match="AdvUnit"):
        _with_asset(problem, adv_unit="NOTIONAL_PER_DAY")  # cadena arbitraria: no es un AdvUnit


@pytest.mark.parametrize("adv", [-1.0, float("nan"), float("inf")])
def test_a_negative_or_non_finite_adv_is_rejected_by_a_direct_call(adv: float) -> None:
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    with pytest.raises(ConstraintCompilationError, match="ADV inválido"):
        _compile(config, _with_asset(problem, adv=adv))


def test_a_missing_adv_source_is_rejected() -> None:
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    with pytest.raises(ConstraintCompilationError, match="ADVSource"):
        _compile(config, _with_asset(problem, adv_source=None))


# ------------------------------------------------------------------- F-2: divisas y FX


def test_equal_currencies_use_adv_directly() -> None:
    config, problem = liquidity_problem(
        NEW,
        nav_currency="USD",
        composition=NEW_COMPOSITION,
        overrides={"ADVCurrency": ["USD"] * 4},
    )
    compiled = _compile(config, problem)
    assert compiled.upper[0] == pytest.approx(0.10) and compiled.liquidity_rules[0].fx_rate is None


def test_different_currencies_with_the_explicit_fx_in_the_documented_orientation() -> None:
    """ADV en USD, NAV en EUR, 0,90 EUR por USD: 100 USD = 90 EUR y 1e8 USD ⇒ 0,45."""
    asset = AssetMetadata(
        "X", "X", True, None, None, None, None, None, True, None, None, None, None, None, None,
        100.0, None, False, "USD", AdvUnit.NOTIONAL_PER_DAY, "FEED",
    )  # fmt: skip
    config = liquidity_config(fx=(FxRate("USD", "EUR", 0.90),))
    converted = liquidity_capacity(asset, config.constraints.liquidity, 1e8, "EUR")
    assert converted.adv_in_nav_currency == pytest.approx(90.0) and converted.fx_rate == 0.90
    config, problem = liquidity_problem(
        NEW,
        config,
        adv_a000=1e8,
        nav_currency="EUR",
        composition=NEW_COMPOSITION,
        overrides={"ADVCurrency": ["USD", "EUR", "EUR", "EUR"]},
    )
    assert _compile(config, problem).upper[0] == pytest.approx(0.45)  # 0,1·(1e8·0,9)·5/1e8


def test_an_fx_in_the_wrong_orientation_is_not_inverted_and_is_rejected() -> None:
    config = liquidity_config(fx=(FxRate("EUR", "USD", 1 / 0.90),))  # par inverso: no vale
    config, problem = liquidity_problem(
        NEW,
        config,
        nav_currency="EUR",
        composition=NEW_COMPOSITION,
        overrides={"ADVCurrency": ["USD", "EUR", "EUR", "EUR"]},
    )
    with pytest.raises(ConstraintCompilationError, match="unidades de EUR por unidad de USD"):
        _compile(config, problem)


def test_a_required_fx_that_is_absent_is_rejected() -> None:
    config, problem = liquidity_problem(
        NEW,
        nav_currency="EUR",
        composition=NEW_COMPOSITION,
        overrides={"ADVCurrency": ["USD", "EUR", "EUR", "EUR"]},
    )
    with pytest.raises(ConstraintCompilationError, match="tipo de cambio"):
        _compile(config, problem)


def test_both_currencies_absent_is_an_error_not_an_assumption_of_equality() -> None:
    config, problem = liquidity_problem(
        NEW, nav_currency=None, composition=NEW_COMPOSITION, overrides={"ADVCurrency": [None] * 4}
    )
    with pytest.raises(ConstraintCompilationError, match="obligatorias"):
        _compile(config, problem)


@pytest.mark.parametrize(("nav_currency", "adv_currency"), [(None, "EUR"), ("EUR", None)])
def test_a_single_missing_currency_is_an_error(nav_currency, adv_currency) -> None:  # type: ignore[no-untyped-def]
    config, problem = liquidity_problem(
        NEW,
        nav_currency=nav_currency,
        composition=NEW_COMPOSITION,
        overrides={"ADVCurrency": [adv_currency] * 4},
    )
    with pytest.raises(ConstraintCompilationError, match="obligatorias"):
        _compile(config, problem)


# ------------------------------------- F-4: activos restringidos, nuevos y existentes sin ADV


@pytest.mark.parametrize("policy", list(RestrictedExistingPositionPolicy))
def test_a_restricted_held_asset_without_adv_is_an_error_under_every_policy(policy) -> None:  # type: ignore[no-untyped-def]
    config = policy_config(liquidity_config(), policy)
    config, problem = liquidity_problem(
        HELD,
        config,
        overrides={**restricted_universe(4, [0]), "ADV": [None, 1e9, 1e9, 1e9]},
    )
    with pytest.raises(ConstraintCompilationError, match="ADV"):
        _compile(config, problem)


@pytest.mark.parametrize("current", [NEW, HELD])
def test_new_and_existing_assets_without_adv_are_errors(current) -> None:  # type: ignore[no-untyped-def]
    config, problem = liquidity_problem(
        current,
        composition=NEW_COMPOSITION if current is NEW else None,
        overrides={"ADV": [None, 1e9, 1e9, 1e9]},
    )
    with pytest.raises(ConstraintCompilationError, match="ADV"):
        _compile(config, problem)


# ------------------------------------------------------------ interacción E-09 / E-10 / E-11


def test_e10_prevails_over_a_larger_liquidity_capacity() -> None:
    """``w_current = 0,10``, capacidad 0,20 (ADV 4e7), ``EligibleFlag = False`` ⇒ máximo 0,10."""
    config, problem = liquidity_problem(
        HELD, adv_a000=4e7, overrides={"EligibleFlag": [False, True, True, True]}
    )
    compiled = _compile(config, problem)
    assert compiled.upper[0] == pytest.approx(0.10)
    assert compiled.liquidity_rules[0].capacity == pytest.approx(0.20)


@pytest.mark.parametrize(
    ("policy", "bounds"),
    [
        (RestrictedExistingPositionPolicy.HOLD_OR_REDUCE, (0.0, 0.10)),
        (RestrictedExistingPositionPolicy.FREEZE_WEIGHT, (0.10, 0.10)),
        (RestrictedExistingPositionPolicy.FORCE_LIQUIDATE, (0.0, 0.0)),
    ],
)
def test_e09_keeps_its_semantics_with_the_complete_data_contract(policy, bounds) -> None:  # type: ignore[no-untyped-def]
    config = policy_config(liquidity_config(), policy)
    config, problem = liquidity_problem(
        HELD, config, adv_a000=4e7, overrides=restricted_universe(4, [0])
    )
    compiled = _compile(config, problem)
    assert (compiled.lower[0], compiled.upper[0]) == pytest.approx(bounds)


# ------------------------------- llamadas directas a los motores (sin cargador TOML/universo)


@pytest.fixture(params=["shares", "no_currencies"])
def bad_problem(request):  # type: ignore[no-untyped-def]
    if request.param == "shares":
        config, problem = liquidity_problem(HELD)
        return config, _with_asset(problem, adv_unit=AdvUnit.SHARES_PER_DAY)
    return liquidity_problem(HELD, nav_currency=None, overrides={"ADVCurrency": [None] * 4})


def test_the_continuous_frontier_rejects_a_bad_contract(bad_problem) -> None:  # type: ignore[no-untyped-def]
    config, problem = bad_problem
    with pytest.raises(ConstraintCompilationError):
        ContinuousFrontierEngine(config).solve(problem, *FRONTIER)


def test_the_candidate_engine_rejects_a_bad_contract(bad_problem) -> None:  # type: ignore[no-untyped-def]
    config, problem = bad_problem
    with pytest.raises(ConstraintCompilationError):
        CandidateEngine(config).search(problem.state.composition(), context_of(problem))
    with pytest.raises(ConstraintCompilationError):
        search(config, problem)


def test_the_global_frontier_rejects_a_bad_contract(bad_problem) -> None:  # type: ignore[no-untyped-def]
    config, problem = bad_problem
    with pytest.raises(ConstraintCompilationError):
        GlobalCandidateFrontierEngine(config).solve(problem, *FRONTIER)


def test_the_candidate_engine_rejects_a_restricted_asset_without_adv_at_start() -> None:
    config, problem = liquidity_problem(
        HELD, overrides={**restricted_universe(4, [0]), "ADV": [None, 1e9, 1e9, 1e9]}
    )
    with pytest.raises(ConstraintCompilationError, match="ADV"):
        search(config, problem)


# ------------------------------------------------------------------------ SolutionValidator


def test_the_validator_detects_a_rule_whose_data_contract_is_violated() -> None:
    config, problem = liquidity_problem(HELD)
    compiled = _compile(config, problem)
    rules = tuple(
        dataclasses.replace(r, adv_unit=AdvUnit.SHARES_PER_DAY) if r.asset_id == "A000" else r
        for r in compiled.liquidity_rules
    )
    tampered = dataclasses.replace(compiled, liquidity_rules=rules)
    validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
    report = validator.validate(
        np.array([0.10, 0.90]),
        tampered,
        ValidationContext(np.full(2, 0.05), np.eye(2) * 0.01, None),
    )
    assert "LIQUIDITY_CAP:A000:data_contract" in {v.constraint_id for v in report.violations}
    valid = validator.validate(
        np.array([0.10, 0.90]),
        compiled,
        ValidationContext(np.full(2, 0.05), np.eye(2) * 0.01, None),
    )
    assert valid.is_valid


# ------------------------------------------------------------- detección de mutantes (F-1, F-2)


def _contract_assertions() -> None:
    """Lo que el contrato exige; debe fallar si se omite la validación de unidad o se supone la
    igualdad de divisas ante la ausencia de metadatos."""
    config, problem = liquidity_problem(NEW, composition=NEW_COMPOSITION)
    with pytest.raises(ConstraintCompilationError):
        _compile(config, _with_asset(problem, adv_unit=AdvUnit.SHARES_PER_DAY))
    with pytest.raises(ConstraintCompilationError):
        _compile(config, _with_asset(problem, adv_unit=None))
    config, problem = liquidity_problem(
        NEW, nav_currency=None, composition=NEW_COMPOSITION, overrides={"ADVCurrency": [None] * 4}
    )
    with pytest.raises(ConstraintCompilationError):
        _compile(config, problem)


def test_the_contract_assertions_pass_on_the_real_implementation() -> None:
    _contract_assertions()


def test_mutant_omitting_the_unit_validation_is_detected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(liquidity_module, "check_adv_unit", lambda asset: AdvUnit.NOTIONAL_PER_DAY)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _contract_assertions()


def test_mutant_assuming_equal_currencies_when_both_are_missing_is_detected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    original = liquidity_module.check_currencies

    def mutant(asset, config, nav_currency):  # type: ignore[no-untyped-def]
        if asset.adv_currency is None and not nav_currency:
            return "ASSUMED", None  # la conducta que se corrigió (F-2)
        return original(asset, config, nav_currency)

    monkeypatch.setattr(liquidity_module, "check_currencies", mutant)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _contract_assertions()
