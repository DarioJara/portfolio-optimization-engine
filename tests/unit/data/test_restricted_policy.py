"""CON-021 (E-09): RestrictedExistingPositionPolicy como configuración obligatoria."""

from __future__ import annotations

import tomllib

import pandas as pd
import pytest

from portfolio_engine.config import EngineConfig, load_engine_config
from portfolio_engine.data.validation import (
    IssueCode,
    PortfolioValidator,
    UniverseValidator,
    effective_restricted_policy,
)
from portfolio_engine.exceptions import ConfigError, DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy as Policy
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.synthetic import holdings_frame, replace_section, universe_frame

pytestmark = pytest.mark.unit


@pytest.fixture()
def restricted_universe(config: EngineConfig) -> Universe:
    frame = universe_frame(3, RestrictedAssetFlag=[True, False, None])
    return UniverseValidator(config.constraints).validate(frame).universe


def _without_policy(config: EngineConfig) -> EngineConfig:
    return replace_section(config, "constraints", restricted_existing_position_policy=None)


def _codes(error: pytest.ExceptionInfo[DataValidationError]) -> set[IssueCode]:
    return {issue.code for issue in error.value.issues}  # type: ignore[attr-defined]


def test_policy_values_are_exactly_the_approved_ones() -> None:
    assert [policy.name for policy in Policy] == [
        "HOLD_OR_REDUCE",
        "FREEZE_WEIGHT",
        "FORCE_LIQUIDATE",
    ]


def test_example_configuration_uses_hold_or_reduce(config: EngineConfig) -> None:
    assert config.constraints.restricted_existing_position_policy is Policy.HOLD_OR_REDUCE


def test_policy_names_are_validated_by_loader() -> None:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        raw = tomllib.load(handle)
    raw["constraints"]["restricted_existing_position_policy"] = "SELL_ALL"
    with pytest.raises(ConfigError, match="HOLD_OR_REDUCE"):
        load_engine_config(raw)


def test_policy_may_be_omitted_in_config(config: EngineConfig) -> None:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        raw = tomllib.load(handle)
    del raw["constraints"]["restricted_existing_position_policy"]
    assert load_engine_config(raw).constraints.restricted_existing_position_policy is None


def test_held_restricted_asset_without_policy_is_rejected(
    config: EngineConfig, restricted_universe: Universe
) -> None:
    cfg = _without_policy(config)
    holdings = holdings_frame([("P1", "A000", 0.4), ("P1", "A001", 0.6)])
    with pytest.raises(DataValidationError) as error:
        PortfolioValidator(cfg.constraints, cfg.data).validate(holdings, restricted_universe)
    [issue] = [
        i
        for i in error.value.issues
        if i.code is IssueCode.RESTRICTED_POLICY_REQUIRED  # type: ignore[attr-defined]
    ]
    assert (issue.asset_id, issue.portfolio_id) == ("A000", "P1")


def test_no_policy_needed_when_no_restricted_asset_is_held(
    config: EngineConfig, restricted_universe: Universe
) -> None:
    cfg = _without_policy(config)
    holdings = holdings_frame([("P1", "A001", 1.0)])
    PortfolioValidator(cfg.constraints, cfg.data).validate(holdings, restricted_universe)


@pytest.mark.parametrize("policy", list(Policy))
def test_explicit_global_policy_accepts_held_restricted_asset(
    config: EngineConfig, restricted_universe: Universe, policy: Policy
) -> None:
    cfg = replace_section(config, "constraints", restricted_existing_position_policy=policy)
    holdings = holdings_frame([("P1", "A000", 0.4), ("P1", "A001", 0.6)])
    result = PortfolioValidator(cfg.constraints, cfg.data).validate(holdings, restricted_universe)
    assert result.states["P1"].weight_of("A000") == 0.4  # la política no altera el estado actual


def test_portfolio_override_policy_satisfies_requirement(
    config: EngineConfig, restricted_universe: Universe
) -> None:
    cfg = _without_policy(config)
    holdings = holdings_frame([("P1", "A000", 0.4), ("P1", "A001", 0.6)])
    specs = pd.DataFrame(
        {"PortfolioID": ["P1"], "RestrictedExistingPositionPolicy": ["FREEZE_WEIGHT"]}
    )
    result = PortfolioValidator(cfg.constraints, cfg.data).validate(
        holdings, restricted_universe, specs
    )
    spec = result.specs["P1"]
    assert effective_restricted_policy(spec, cfg.constraints) is Policy.FREEZE_WEIGHT
    assert effective_restricted_policy(spec, config.constraints) is Policy.FREEZE_WEIGHT
    assert effective_restricted_policy(None, config.constraints) is Policy.HOLD_OR_REDUCE


def test_held_asset_with_unknown_restricted_status_is_rejected(
    config: EngineConfig, restricted_universe: Universe
) -> None:
    holdings = holdings_frame([("P1", "A002", 1.0)])
    with pytest.raises(DataValidationError) as error:
        PortfolioValidator(config.constraints, config.data).validate(holdings, restricted_universe)
    assert IssueCode.RESTRICTED_STATUS_UNKNOWN in _codes(error)
