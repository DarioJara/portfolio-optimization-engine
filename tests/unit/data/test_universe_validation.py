"""DAT-009, DAT-014, DAT-028, DAT-030: universo, identidad de activos, metadatos y límites."""

from __future__ import annotations

import math

import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.data.validation import IssueCode, UniverseValidator
from portfolio_engine.exceptions import AssetResolutionError, DataValidationError
from portfolio_engine.models.asset import Universe
from tests.fixtures.synthetic import replace_section, universe_frame

pytestmark = pytest.mark.unit


def _codes(error: pytest.ExceptionInfo[DataValidationError]) -> set[IssueCode]:
    return {issue.code for issue in error.value.issues}  # type: ignore[attr-defined]


def test_valid_universe_builds_all_fields(config: EngineConfig) -> None:
    result = UniverseValidator(config.constraints).validate(universe_frame(3))
    asset = result.universe.get("A001")
    assert asset.ticker == "T001"
    assert asset.max_weight == 0.5
    assert asset.buy_cost == 5.0
    assert asset.restricted is False
    assert result.universe.asset_ids == ("A000", "A001", "A002")
    assert not result.report.has_errors


def test_missing_required_column_is_schema_error(config: EngineConfig) -> None:
    frame = universe_frame(2).drop(columns=["EligibleFlag"])
    with pytest.raises(DataValidationError) as error:
        UniverseValidator(config.constraints).validate(frame)
    assert IssueCode.SCHEMA in _codes(error)


def test_null_required_metadata_is_error(config: EngineConfig) -> None:
    frame = universe_frame(2, Ticker=["T0", None])
    with pytest.raises(DataValidationError) as error:
        UniverseValidator(config.constraints).validate(frame)
    assert IssueCode.MISSING_METADATA in _codes(error)


def test_missing_recommended_metadata_is_warning(config: EngineConfig) -> None:
    frame = universe_frame(2, Sector=[None, "Tech"])
    report = UniverseValidator(config.constraints).validate(frame).report
    assert [i.asset_id for i in report.issues_for(IssueCode.MISSING_RECOMMENDED_METADATA)] == [
        "A000"
    ]
    assert not report.has_errors


def test_duplicate_asset_id_and_ambiguous_ticker(config: EngineConfig) -> None:
    frame = universe_frame(3, AssetID=["A", "A", "B"], Ticker=["X", "Y", "Y"])
    with pytest.raises(DataValidationError) as error:
        UniverseValidator(config.constraints).validate(frame)
    assert {IssueCode.DUPLICATE, IssueCode.AMBIGUOUS_TICKER} <= _codes(error)


@pytest.mark.parametrize(
    ("min_weight", "max_weight"),
    [(0.4, 0.3), (-0.1, 0.3), (0.0, -0.2), (1.2, 1.5)],
)
def test_incompatible_limits(config: EngineConfig, min_weight: float, max_weight: float) -> None:
    frame = universe_frame(1, MinWeight=[min_weight], MaxWeight=[max_weight])
    with pytest.raises(DataValidationError) as error:
        UniverseValidator(config.constraints).validate(frame)
    assert IssueCode.INCOMPATIBLE_LIMITS in _codes(error)


def test_negative_limits_allowed_without_long_only(config: EngineConfig) -> None:
    constraints = replace_section(config, "constraints", long_only=False).constraints
    frame = universe_frame(1, MinWeight=[-0.1], MaxWeight=[0.3])
    assert UniverseValidator(constraints).validate(frame).universe.get("A000").min_weight == -0.1


@pytest.mark.parametrize("column", ["BuyCost", "ADV", "MarketCap"])
def test_negative_or_non_finite_numeric_metadata(config: EngineConfig, column: str) -> None:
    for value, code in ((-1.0, IssueCode.INVALID_VALUE), (math.inf, IssueCode.NON_FINITE_VALUE)):
        frame = universe_frame(1, **{column: [value]})
        with pytest.raises(DataValidationError) as error:
            UniverseValidator(config.constraints).validate(frame)
        assert code in _codes(error)


def test_unknown_restricted_status_is_warning_at_universe_level(config: EngineConfig) -> None:
    frame = universe_frame(2, RestrictedAssetFlag=[None, False])
    report = UniverseValidator(config.constraints).validate(frame).report
    assert report.issues_for(IssueCode.RESTRICTED_STATUS_UNKNOWN)


def test_resolution_by_asset_id_or_unique_ticker(universe: Universe) -> None:
    assert universe.resolve("A002") == "A002"
    assert universe.resolve("T002") == "A002"
    with pytest.raises(AssetResolutionError, match="desconocido"):
        universe.resolve("ZZZ")


def test_identifier_that_is_ticker_of_other_asset_is_ambiguous(config: EngineConfig) -> None:
    frame = universe_frame(2, AssetID=["X", "Y"], Ticker=["Y", "Z"])
    universe = UniverseValidator(config.constraints).validate(frame).universe
    with pytest.raises(AssetResolutionError, match="ambiguo"):
        universe.resolve("Y")
