"""DAT-010, DAT-011, DAT-029 y decisión A-34: carteras actuales, especificaciones y pesos."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.data.validation import IssueCode, PortfolioValidator, UniverseValidator
from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.enums import (
    BoundSource,
    ResidualWeightPolicy,
    RestrictedExistingPositionPolicy,
)
from portfolio_engine.models.portfolio import (
    PortfolioSpec,
    WeightBounds,
    resolve_effective_weight_bounds,
)
from tests.fixtures.synthetic import holdings_frame, replace_section, universe_frame

pytestmark = pytest.mark.unit


def _validator(config: EngineConfig) -> PortfolioValidator:
    return PortfolioValidator(config.constraints, config.data)


def _codes(error: pytest.ExceptionInfo[DataValidationError]) -> set[IssueCode]:
    return {issue.code for issue in error.value.issues}  # type: ignore[attr-defined]


def test_valid_holdings_build_states(config: EngineConfig, universe: Universe) -> None:
    holdings = holdings_frame([("P1", "A002", 0.25), ("P1", "A000", 0.75), ("P2", "T001", 1.0)])
    result = _validator(config).validate(holdings, universe)
    p1 = result.states["P1"]
    assert p1.asset_ids == ("A000", "A002")
    np.testing.assert_array_equal(p1.weights, [0.75, 0.25])
    np.testing.assert_array_equal(p1.global_indices, [0, 2])
    assert result.states["P2"].asset_ids == ("A001",)  # resuelto desde Ticker


@pytest.mark.parametrize(
    ("weight", "code"),
    [
        (math.nan, IssueCode.MISSING_WEIGHT),
        (math.inf, IssueCode.NON_FINITE_VALUE),
        (-0.1, IssueCode.NEGATIVE_WEIGHT),
    ],
)
def test_invalid_weights(
    config: EngineConfig, universe: Universe, weight: float, code: IssueCode
) -> None:
    holdings = holdings_frame([("P1", "A000", 1.0), ("P1", "A001", weight)])
    with pytest.raises(DataValidationError) as error:
        _validator(config).validate(holdings, universe)
    assert code in _codes(error)


def test_duplicate_and_unknown_assets(config: EngineConfig, universe: Universe) -> None:
    holdings = holdings_frame([("P1", "A000", 0.5), ("P1", "T000", 0.5), ("P2", "ZZZ", 1.0)])
    with pytest.raises(DataValidationError) as error:
        _validator(config).validate(holdings, universe)
    assert {IssueCode.DUPLICATE, IssueCode.UNKNOWN_ASSET} <= _codes(error)


def test_weights_not_summing_to_one_are_not_renormalized(
    config: EngineConfig, universe: Universe
) -> None:
    holdings = holdings_frame([("P1", "A000", 0.5), ("P1", "A001", 0.4)])
    with pytest.raises(DataValidationError) as error:
        _validator(config).validate(holdings, universe)
    assert IssueCode.INCONSISTENT_WEIGHTS in _codes(error)


def test_sum_within_tolerance_is_kept_exactly(config: EngineConfig, universe: Universe) -> None:
    tolerance = config.data.weight_sum_tolerance
    holdings = holdings_frame([("P1", "A000", 0.5), ("P1", "A001", 0.5 - tolerance / 2)])
    state = _validator(config).validate(holdings, universe).states["P1"]
    assert state.weights[1] == 0.5 - tolerance / 2  # sin renormalizar


def test_residual_assigned_to_cash_is_logged(config: EngineConfig) -> None:
    frame = universe_frame(3, AssetID=["A000", "A001", "CASH"], Ticker=["T0", "T1", "TC"])
    universe = UniverseValidator(config.constraints).validate(frame).universe
    data = replace_section(
        config,
        "data",
        residual_weight_policy=ResidualWeightPolicy.ASSIGN_TO_CASH,
        cash_asset_id="CASH",
    )
    holdings = holdings_frame([("P1", "A000", 0.5), ("P1", "A001", 0.3)])
    result = PortfolioValidator(data.constraints, data.data).validate(holdings, universe)
    state = result.states["P1"]
    assert state.weight_of("CASH") == pytest.approx(0.2)
    assert state.total_weight == pytest.approx(1.0)
    [correction] = result.report.corrections
    assert correction.action == "ASSIGN_RESIDUAL_TO_CASH"
    assert correction.target == "P1"


def test_negative_residual_cannot_go_to_cash(config: EngineConfig) -> None:
    frame = universe_frame(2, AssetID=["A000", "CASH"], Ticker=["T0", "TC"])
    universe = UniverseValidator(config.constraints).validate(frame).universe
    data = replace_section(
        config,
        "data",
        residual_weight_policy=ResidualWeightPolicy.ASSIGN_TO_CASH,
        cash_asset_id="CASH",
    )
    holdings = holdings_frame([("P1", "A000", 1.2)])
    with pytest.raises(DataValidationError) as error:
        PortfolioValidator(data.constraints, data.data).validate(holdings, universe)
    assert IssueCode.INCONSISTENT_WEIGHTS in _codes(error)


def test_zero_weight_rows_are_not_holdings(config: EngineConfig, universe: Universe) -> None:
    holdings = holdings_frame([("P1", "A000", 1.0), ("P1", "A001", 0.0)])
    result = _validator(config).validate(holdings, universe)
    assert result.states["P1"].asset_ids == ("A000",)
    assert result.report.issues_for(IssueCode.ZERO_WEIGHT_IGNORED)


def _specs(**columns: list[object]) -> pd.DataFrame:
    base: dict[str, list[object]] = {
        "PortfolioID": ["P1"],
        "TargetPortfolioSize": [20.0],
        "VolatilityLimit": [0.15],
        "MaxTurnover": [0.3],
        "InvestmentUniverse": ["A000;T001;A002"],
        "RestrictedExistingPositionPolicy": [None],
        "NAV": [1e6],
    }
    base.update(columns)
    return pd.DataFrame(base)


def test_portfolio_specs_are_parsed(config: EngineConfig, universe: Universe) -> None:
    holdings = holdings_frame([("P1", "A000", 1.0)])
    overrides = pd.DataFrame(
        {"PortfolioID": ["P1"], "AssetID": ["A000"], "MinWeight": [0.1], "MaxWeight": [0.4]}
    )
    result = _validator(config).validate(holdings, universe, _specs(), overrides)
    spec = result.specs["P1"]
    assert spec.target_portfolio_size == 20
    assert spec.investment_universe == ("A000", "A001", "A002")
    assert spec.weight_bound_overrides["A000"] == WeightBounds(0.1, 0.4)
    assert result.states["P1"].nav == 1e6


def test_spec_without_holdings_gives_empty_state(config: EngineConfig, universe: Universe) -> None:
    holdings = holdings_frame([("P2", "A000", 1.0)])
    state = _validator(config).validate(holdings, universe, _specs()).states["P1"]
    assert not state.has_current_portfolio
    assert state.asset_ids == ()


@pytest.mark.parametrize(
    "columns",
    [
        {"TargetPortfolioSize": [2.5]},
        {"TargetPortfolioSize": [0.0]},
        {"VolatilityLimit": [-0.1]},
        {"MaxTurnover": [-0.2]},
        {"NAV": [0.0]},
        {"InvestmentUniverse": ["A000;NOPE"]},
        {"RestrictedExistingPositionPolicy": ["SELL_EVERYTHING"]},
        {"PortfolioID": [None]},
    ],
)
def test_invalid_specs(
    config: EngineConfig, universe: Universe, columns: dict[str, list[object]]
) -> None:
    holdings = holdings_frame([("P1", "A000", 1.0)])
    with pytest.raises(DataValidationError) as error:
        _validator(config).validate(holdings, universe, _specs(**columns))
    assert IssueCode.INVALID_PORTFOLIO_SPEC in _codes(error)


def test_invalid_overrides(config: EngineConfig, universe: Universe) -> None:
    holdings = holdings_frame([("P1", "A000", 1.0)])
    bad = pd.DataFrame(
        {"PortfolioID": ["P1"], "AssetID": ["A000"], "MinWeight": [0.5], "MaxWeight": [0.4]}
    )
    orphan = pd.DataFrame(
        {"PortfolioID": ["P9"], "AssetID": ["A000"], "MinWeight": [0.1], "MaxWeight": [0.4]}
    )
    for overrides in (bad, orphan):
        with pytest.raises(DataValidationError) as error:
            _validator(config).validate(holdings, universe, _specs(), overrides)
        assert IssueCode.INVALID_PORTFOLIO_SPEC in _codes(error)


def test_held_outside_investment_universe_is_warning(
    config: EngineConfig, universe: Universe
) -> None:
    holdings = holdings_frame([("P1", "A005", 1.0)])
    report = _validator(config).validate(holdings, universe, _specs()).report
    assert report.issues_for(IssueCode.HELD_OUTSIDE_INVESTMENT_UNIVERSE)


def test_effective_bounds_precedence(universe: Universe) -> None:
    asset = universe.get("A000")  # universo: Min 0.0, Max 0.5
    spec = PortfolioSpec(
        portfolio_id="P1",
        target_portfolio_size=None,
        volatility_limit=None,
        max_turnover=None,
        investment_universe=None,
        restricted_existing_position_policy=RestrictedExistingPositionPolicy.HOLD_OR_REDUCE,
        nav=None,
        weight_bound_overrides={"A000": WeightBounds(None, 0.2)},
    )
    bounds = resolve_effective_weight_bounds(asset, spec, WeightBounds(0.01, 0.3))
    assert (bounds.min_weight, bounds.min_source) == (0.01, BoundSource.GLOBAL_CONFIG)
    assert (bounds.max_weight, bounds.max_source) == (0.2, BoundSource.PORTFOLIO_OVERRIDE)
    no_global = resolve_effective_weight_bounds(asset, None, WeightBounds(None, None))
    assert (no_global.min_source, no_global.max_source) == (BoundSource.UNIVERSE,) * 2
    unlimited = dataclasses.replace(universe.get("A001"), min_weight=None, max_weight=None)
    unset = resolve_effective_weight_bounds(unlimited, None, WeightBounds(None, None))
    assert (unset.min_weight, unset.min_source) == (None, BoundSource.UNSET)
    with pytest.raises(DataValidationError, match="incompatibles"):
        resolve_effective_weight_bounds(asset, None, WeightBounds(0.6, None))
