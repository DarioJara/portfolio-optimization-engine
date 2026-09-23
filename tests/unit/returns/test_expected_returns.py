"""RET-001, RET-002, RET-003, RET-008: interfaz de expected returns, alpha externo y etiquetado."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.data.validation import build_external_alpha
from portfolio_engine.exceptions import ConfigError, DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.enums import ExpectedReturnMode, ReturnKind
from portfolio_engine.models.market_data import ReturnsMatrix
from portfolio_engine.models.risk_model import ExpectedReturns
from portfolio_engine.returns.expected import (
    ExpectedReturnProvider,
    ExternalAlphaProvider,
    HistoricalMeanProvider,
    make_expected_return_provider,
)
from tests.fixtures.synthetic import replace_section

pytestmark = pytest.mark.unit


def _returns() -> ReturnsMatrix:
    values = np.array([[0.01, 0.002], [0.03, -0.004], [-0.01, 0.005]])
    dates = np.array(["2024-01-02", "2024-01-03", "2024-01-04"], dtype="datetime64[ns]")
    return ReturnsMatrix(dates, ("A000", "A001"), values, ReturnKind.ARITHMETIC, None)


def _alpha_frame(**columns: list[object]) -> pd.DataFrame:
    base: dict[str, list[object]] = {
        "AssetID": ["A000", "A001"],
        "ExpectedReturn": [0.16, 0.03],
        "HorizonYears": [2.0, 0.5],
    }
    base.update(columns)
    return pd.DataFrame(base)


def test_historical_mean_is_annualized_arithmetic_mean() -> None:
    result = HistoricalMeanProvider(252).estimate(["A000", "A001"], _returns())
    np.testing.assert_allclose(result.values, 252 * np.array([0.01, 0.001]), rtol=1e-12)
    assert result.mode is ExpectedReturnMode.INTERNAL_ESTIMATION
    assert result.method == "HISTORICAL_MEAN"
    assert not result.is_external_alpha


def test_historical_mean_is_never_labelled_as_alpha() -> None:
    with pytest.raises(DataValidationError, match="EXTERNAL_ALPHA"):
        ExpectedReturns(("A",), np.zeros(1), ExpectedReturnMode.EXTERNAL_ALPHA, "HISTORICAL_MEAN")
    with pytest.raises(DataValidationError, match="no es alpha"):
        ExpectedReturns(
            ("A",), np.zeros(1), ExpectedReturnMode.INTERNAL_ESTIMATION, "EXTERNAL_ALPHA"
        )


def test_external_alpha_converted_to_annual_basis(universe: Universe) -> None:
    alpha = build_external_alpha(_alpha_frame(), universe, source="research-desk")
    result = ExternalAlphaProvider(alpha).estimate(["A000", "A001"], None)
    np.testing.assert_allclose(result.values, [0.08, 0.06], rtol=1e-15)
    assert result.is_external_alpha
    assert result.method == "EXTERNAL_ALPHA"


def test_external_alpha_requires_full_coverage(universe: Universe) -> None:
    alpha = build_external_alpha(_alpha_frame(), universe, source="desk")
    with pytest.raises(DataValidationError, match="A002"):
        ExternalAlphaProvider(alpha).estimate(["A000", "A002"], None)


@pytest.mark.parametrize(
    "columns",
    [
        {"HorizonYears": [0.0, 1.0]},
        {"HorizonYears": [-1.0, 1.0]},
        {"ExpectedReturn": [np.nan, 0.1]},
        {"ExpectedReturn": [np.inf, 0.1]},
        {"AssetID": ["A000", "A000"]},
        {"AssetID": ["A000", "NOPE"]},
    ],
)
def test_invalid_external_alpha(universe: Universe, columns: dict[str, list[object]]) -> None:
    with pytest.raises(DataValidationError):
        build_external_alpha(_alpha_frame(**columns), universe, source="desk")


def test_factory_follows_configuration(config: EngineConfig, universe: Universe) -> None:
    provider: ExpectedReturnProvider = make_expected_return_provider(config.returns, None)
    assert isinstance(provider, HistoricalMeanProvider)
    external = replace_section(
        config, "returns", expected_return_mode=ExpectedReturnMode.EXTERNAL_ALPHA
    ).returns
    with pytest.raises(ConfigError, match="alpha"):
        make_expected_return_provider(external, None)
    alpha = build_external_alpha(_alpha_frame(), universe, source="desk")
    assert isinstance(make_expected_return_provider(external, alpha), ExternalAlphaProvider)


def test_expected_returns_reject_non_finite_values() -> None:
    with pytest.raises(DataValidationError):
        ExpectedReturns(
            ("A",), np.array([np.nan]), ExpectedReturnMode.INTERNAL_ESTIMATION, "HISTORICAL_MEAN"
        )
