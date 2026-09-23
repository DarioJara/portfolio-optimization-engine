"""DAT-001, DAT-002, DAT-020 … DAT-027, DAT-031: validación del histórico de mercado."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.data.validation import IssueCode, MarketDataValidator
from portfolio_engine.data.validation.market_data_validator import (
    longest_unchanged_run,
    robust_zscores,
)
from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.enums import AssetErrorPolicy, IssueSeverity
from tests.fixtures.synthetic import price_frame, replace_section

pytestmark = pytest.mark.unit

N_DATES = 90


def _validator(config: EngineConfig, **data_changes: object) -> MarketDataValidator:
    return MarketDataValidator(replace_section(config, "data", **data_changes).data)


def _codes(error: pytest.ExceptionInfo[DataValidationError]) -> dict[IssueCode, set[str | None]]:
    codes: dict[IssueCode, set[str | None]] = {}
    for issue in error.value.issues:
        codes.setdefault(issue.code, set()).add(issue.asset_id)  # type: ignore[attr-defined]
    return codes


def _prices() -> pd.DataFrame:
    return price_frame(6, N_DATES, seed=3)


def test_clean_history_passes(config: EngineConfig, universe: Universe) -> None:
    result = MarketDataValidator(config.data).validate(_prices(), universe)
    assert result.prices.asset_ids == universe.asset_ids
    assert not result.report.has_errors
    assert result.report.corrections == ()


def test_ticker_identifiers_are_resolved(config: EngineConfig, universe: Universe) -> None:
    frame = _prices().rename(columns={"AssetID": "Ticker"})
    frame["Ticker"] = frame["Ticker"].str.replace("A", "T")
    result = MarketDataValidator(config.data).validate(frame, universe)
    assert result.prices.asset_ids == universe.asset_ids


def test_missing_required_column(config: EngineConfig, universe: Universe) -> None:
    with pytest.raises(DataValidationError) as error:
        MarketDataValidator(config.data).validate(
            _prices().drop(columns=["AdjustedClose"]), universe
        )
    assert IssueCode.SCHEMA in _codes(error)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (np.nan, IssueCode.MISSING_PRICE),
        (np.inf, IssueCode.NON_FINITE_VALUE),
        (-np.inf, IssueCode.NON_FINITE_VALUE),
        (0.0, IssueCode.NON_POSITIVE_PRICE),
        (-5.0, IssueCode.NON_POSITIVE_PRICE),
    ],
)
def test_bad_prices_are_detected_per_asset(
    config: EngineConfig, universe: Universe, value: float, code: IssueCode
) -> None:
    frame = _prices()
    row = frame.index[(frame["AssetID"] == "A002")][10]
    frame.loc[row, "AdjustedClose"] = value
    with pytest.raises(DataValidationError) as error:
        MarketDataValidator(config.data).validate(frame, universe)
    assert _codes(error)[code] == {"A002"}


def test_duplicates_detected(config: EngineConfig, universe: Universe) -> None:
    frame = _prices()
    frame = pd.concat([frame, frame[frame["AssetID"] == "A001"].iloc[[5]]], ignore_index=True)
    with pytest.raises(DataValidationError) as error:
        MarketDataValidator(config.data).validate(frame, universe)
    assert _codes(error)[IssueCode.DUPLICATE] == {"A001"}


def test_invalid_and_future_dates(config: EngineConfig, universe: Universe) -> None:
    frame = _prices()
    frame.loc[frame.index[frame["AssetID"] == "A003"][4], "Date"] = pd.NaT
    as_of = np.datetime64(frame["Date"].max()) - np.timedelta64(1, "D")
    with pytest.raises(DataValidationError) as error:
        MarketDataValidator(config.data).validate(frame, universe, as_of=as_of)
    codes = _codes(error)
    assert codes[IssueCode.INVALID_DATE] == {"A003"}
    assert codes[IssueCode.FUTURE_DATE] == set(universe.asset_ids)


def test_misaligned_calendar_is_missing_observation(
    config: EngineConfig, universe: Universe
) -> None:
    frame = _prices()
    frame = frame.drop(frame.index[frame["AssetID"] == "A004"][20])
    with pytest.raises(DataValidationError) as error:
        MarketDataValidator(config.data).validate(frame, universe)
    assert _codes(error)[IssueCode.MISSING_OBSERVATION] == {"A004"}


def test_insufficient_history(config: EngineConfig, universe: Universe) -> None:
    frame = price_frame(6, 30, seed=3)
    with pytest.raises(DataValidationError) as error:
        _validator(config, min_return_observations=30).validate(frame, universe)
    assert _codes(error)[IssueCode.INSUFFICIENT_HISTORY] == set(universe.asset_ids)
    # 30 precios = 29 retornos: exactamente el mínimo debe pasar.
    _validator(config, min_return_observations=29).validate(frame, universe)


def test_stale_prices_use_configured_severity(config: EngineConfig, universe: Universe) -> None:
    frame = _prices()
    rows = frame.index[frame["AssetID"] == "A005"][30:37]
    frame.loc[rows, "AdjustedClose"] = frame.loc[rows[0], "AdjustedClose"]
    report = _validator(config, max_stale_run=5).validate(frame, universe).report
    stale = report.issues_for(IssueCode.STALE_PRICE)
    assert [(i.asset_id, i.severity) for i in stale] == [("A005", IssueSeverity.WARNING)]
    assert (
        not _validator(config, max_stale_run=6)
        .validate(frame, universe)
        .report.issues_for(IssueCode.STALE_PRICE)
    )
    with pytest.raises(DataValidationError):
        _validator(config, max_stale_run=5, stale_price_severity=IssueSeverity.ERROR).validate(
            frame, universe
        )


def test_outliers_detected_not_corrected(config: EngineConfig, universe: Universe) -> None:
    frame = _prices()
    row = frame.index[frame["AssetID"] == "A000"][50]
    original = frame.loc[row, "AdjustedClose"]
    frame.loc[row, "AdjustedClose"] = original * 3.0
    result = MarketDataValidator(config.data).validate(frame, universe)
    assert [i.asset_id for i in result.report.issues_for(IssueCode.OUTLIER)] == ["A000"]
    kept = result.prices.frame()
    value = kept.loc[
        (kept["AssetID"] == "A000") & (kept["Date"] == frame.loc[row, "Date"]), "AdjustedClose"
    ]
    assert value.item() == original * 3.0  # detectado, nunca corregido


def test_calendar_gap(config: EngineConfig, universe: Universe) -> None:
    frame = _prices()
    dates = np.sort(frame["Date"].unique())
    frame = frame[~frame["Date"].isin(dates[40:50])]
    report = MarketDataValidator(config.data).validate(frame, universe).report
    assert {i.asset_id for i in report.issues_for(IssueCode.CALENDAR_GAP)} == set(
        universe.asset_ids
    )


def test_optional_fields_invalid_values_are_warnings(
    config: EngineConfig, universe: Universe
) -> None:
    frame = _prices()
    frame["Volume"] = 1000.0
    frame["Bid"] = frame["AdjustedClose"] - 0.01
    frame["Ask"] = frame["AdjustedClose"] + 0.01
    frame.loc[frame.index[0], "Volume"] = -1.0
    frame.loc[frame.index[1], ["Bid", "Ask"]] = [101.0, 100.0]
    result = MarketDataValidator(config.data).validate(frame, universe)
    assert len(result.report.issues_for(IssueCode.INVALID_OPTIONAL_FIELD)) == 2
    assert "Volume" in result.prices.frame().columns


def test_exclude_policy_removes_whole_asset_and_logs_correction(
    config: EngineConfig, universe: Universe
) -> None:
    frame = _prices()
    frame.loc[frame.index[frame["AssetID"] == "A002"][10], "AdjustedClose"] = np.nan
    validator = _validator(config, asset_error_policy=AssetErrorPolicy.EXCLUDE_ASSET)
    result = validator.validate(frame, universe)
    assert "A002" not in result.prices.asset_ids
    assert len(result.prices.asset_ids) == 5
    [correction] = result.report.corrections
    assert (correction.action, correction.target) == ("EXCLUDE_ASSET", "A002")
    assert "MISSING_PRICE" in correction.reason
    assert result.report.issues_for(IssueCode.MISSING_PRICE)  # el error sigue registrado


def test_fail_policy_never_drops_data_silently(config: EngineConfig, universe: Universe) -> None:
    frame = _prices()
    frame.loc[frame.index[frame["AssetID"] == "A002"][10], "AdjustedClose"] = np.nan
    with pytest.raises(DataValidationError):
        MarketDataValidator(config.data).validate(frame, universe)


def test_unknown_identifier(config: EngineConfig, universe: Universe) -> None:
    frame = _prices()
    extra = frame[frame["AssetID"] == "A000"].assign(AssetID="ZZZ")
    with pytest.raises(DataValidationError) as error:
        MarketDataValidator(config.data).validate(pd.concat([frame, extra]), universe)
    assert _codes(error)[IssueCode.UNKNOWN_ASSET] == {"ZZZ"}


def test_empty_history_is_error(config: EngineConfig, universe: Universe) -> None:
    with pytest.raises(DataValidationError, match="vacío"):
        MarketDataValidator(config.data).validate(_prices().iloc[0:0], universe)


def test_longest_unchanged_run() -> None:
    assert longest_unchanged_run(np.array([1.0, 1.0, 1.0, 2.0, 2.0, 3.0])) == 2
    assert longest_unchanged_run(np.array([1.0, 2.0, 3.0])) == 0
    assert longest_unchanged_run(np.array([5.0, 5.0, 5.0, 5.0])) == 3


def test_robust_zscores_match_definition() -> None:
    values = np.array([0.0, 1.0, 2.0, 3.0, 100.0])
    median, mad = 2.0, 1.0
    expected = np.abs(values - median) / (1.482602218505602 * mad)
    np.testing.assert_allclose(robust_zscores(values), expected)
    np.testing.assert_array_equal(robust_zscores(np.ones(4)), np.zeros(4))
