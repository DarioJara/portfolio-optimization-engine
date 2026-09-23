"""RET-010, RET-012: retornos aritméticos exactos y log returns solo con justificación."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.exceptions import DataValidationError, InsufficientDataError
from portfolio_engine.models.enums import ReturnKind
from portfolio_engine.models.market_data import PriceHistory, ReturnsMatrix
from portfolio_engine.returns import ReturnsEngine
from tests.fixtures.synthetic import replace_section

pytestmark = pytest.mark.unit


def _history(prices: dict[str, list[float]]) -> PriceHistory:
    dates = pd.bdate_range("2024-01-01", periods=len(next(iter(prices.values()))))
    rows = [
        {"Date": date, "AssetID": asset, "AdjustedClose": value}
        for asset, values in prices.items()
        for date, value in zip(dates, values, strict=True)
    ]
    return PriceHistory(pd.DataFrame(rows))


def test_arithmetic_returns_exact_values(config: EngineConfig) -> None:
    history = _history({"B": [50.0, 55.0, 44.0], "A": [100.0, 110.0, 99.0]})
    result = ReturnsEngine(config.returns).compute(history)
    assert result.asset_ids == ("A", "B")
    assert result.kind is ReturnKind.ARITHMETIC
    expected = np.array([[110 / 100 - 1, 55 / 50 - 1], [99 / 110 - 1, 44 / 55 - 1]])
    np.testing.assert_allclose(result.values, expected, rtol=0, atol=1e-15)
    np.testing.assert_allclose(result.values[:, 0], [0.1, -0.1], rtol=0, atol=1e-15)
    assert result.dates[0] == np.datetime64("2024-01-02")  # fecha de fin de periodo


def test_returns_matrix_is_read_only(config: EngineConfig) -> None:
    result = ReturnsEngine(config.returns).compute(_history({"A": [1.0, 2.0, 3.0]}))
    with pytest.raises(ValueError):
        result.values[0, 0] = 0.0


def test_log_returns_only_with_justification(config: EngineConfig) -> None:
    returns_config = replace_section(
        config,
        "returns",
        return_kind=ReturnKind.LOG,
        log_return_justification="Suma temporal para agregación multi-periodo",
    ).returns
    result = ReturnsEngine(returns_config).compute(_history({"A": [100.0, 110.0, 99.0]}))
    np.testing.assert_allclose(result.values[:, 0], np.log([1.1, 0.9]), rtol=0, atol=1e-15)
    assert result.kind is ReturnKind.LOG
    assert result.justification
    with pytest.raises(DataValidationError, match="justificación"):
        ReturnsMatrix(result.dates, ("A",), result.values, ReturnKind.LOG, None)


def test_missing_cells_are_not_filled(config: EngineConfig) -> None:
    frame = _history({"A": [1.0, 2.0, 3.0], "B": [1.0, 2.0, 3.0]}).frame().iloc[:-1]
    with pytest.raises(DataValidationError, match="no rellenan"):
        ReturnsEngine(config.returns).compute(PriceHistory(frame))


def test_non_positive_prices_rejected(config: EngineConfig) -> None:
    with pytest.raises(DataValidationError, match="no positivos"):
        ReturnsEngine(config.returns).compute(_history({"A": [1.0, 0.0, 2.0]}))


def test_single_date_is_insufficient(config: EngineConfig) -> None:
    with pytest.raises(InsufficientDataError):
        ReturnsEngine(config.returns).compute(_history({"A": [1.0]}))


def test_price_history_rejects_duplicates_and_nulls() -> None:
    frame = _history({"A": [1.0, 2.0]}).frame()
    with pytest.raises(DataValidationError, match="duplicados"):
        PriceHistory(pd.concat([frame, frame]))
    frame.loc[0, "AdjustedClose"] = np.nan
    with pytest.raises(DataValidationError, match="nulos"):
        PriceHistory(frame)
