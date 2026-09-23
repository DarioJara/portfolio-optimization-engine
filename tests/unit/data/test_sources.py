"""DAT-003 … DAT-006: fuentes intercambiables que producen tablas canónicas idénticas."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.data.sources import (
    CSVSource,
    DataFrameSource,
    ParquetSource,
    Table,
    TablePaths,
    canonicalize,
)
from portfolio_engine.data.validation import MarketDataValidator, UniverseValidator
from portfolio_engine.exceptions import DataValidationError
from tests.fixtures.synthetic import holdings_frame, price_frame, universe_frame

pytestmark = pytest.mark.unit


def _tables() -> dict[str, pd.DataFrame]:
    return {
        "prices": price_frame(4, 80, seed=7),
        "universe": universe_frame(4),
        "holdings": holdings_frame([("P1", "A000", 0.6), ("P1", "A001", 0.4)]),
    }


def _write(tables: dict[str, pd.DataFrame], directory: Path, suffix: str) -> TablePaths:
    paths = {}
    for name, frame in tables.items():
        path = directory / f"{name}.{suffix}"
        if suffix == "csv":
            frame.to_csv(path, index=False, float_format="%.17g")  # round-trip exacto
        else:
            frame.to_parquet(path, index=False)
        paths[name] = path
    return TablePaths(**paths)


def test_all_sources_yield_identical_canonical_tables(tmp_path: Path) -> None:
    tables = _tables()
    sources = [
        DataFrameSource(**tables),
        CSVSource(_write(tables, tmp_path, "csv")),
        ParquetSource(_write(tables, tmp_path, "parquet")),
    ]
    reference = sources[0]
    for source in sources[1:]:
        for load in ("load_prices", "load_universe", "load_current_portfolios"):
            pd.testing.assert_frame_equal(
                getattr(source, load)(), getattr(reference, load)(), check_exact=True
            )
        assert source.load_portfolio_specs() is None
        assert source.load_external_alpha() is None


def test_validated_outputs_do_not_depend_on_origin(tmp_path: Path, config: EngineConfig) -> None:
    tables = _tables()
    results = []
    for source in (DataFrameSource(**tables), CSVSource(_write(tables, tmp_path, "csv"))):
        universe = UniverseValidator(config.constraints).validate(source.load_universe()).universe
        prices = MarketDataValidator(config.data).validate(source.load_prices(), universe).prices
        results.append((universe, prices))
    assert results[0][0] == results[1][0]
    assert results[0][1] == results[1][1]


def test_canonical_types() -> None:
    frame = canonicalize(universe_frame(2), Table.UNIVERSE)
    assert frame["MinWeight"].dtype == np.float64
    assert frame["AssetID"].dtype == object
    assert frame["EligibleFlag"].tolist() == [True, True]
    prices = canonicalize(price_frame(2, 3, seed=1), Table.PRICES)
    assert prices["Date"].dtype == "datetime64[ns]"


def test_csv_identifiers_are_not_coerced_to_numbers(tmp_path: Path) -> None:
    universe = universe_frame(2, AssetID=["007", "010"], Ticker=["007", "010"])
    path = tmp_path / "u.csv"
    universe.to_csv(path, index=False)
    loaded = CSVSource(TablePaths(prices=path, universe=path, holdings=path)).load_universe()
    assert loaded["AssetID"].tolist() == ["007", "010"]


@pytest.mark.parametrize(
    ("column", "value"),
    [("AdjustedClose", "abc"), ("Date", "not-a-date")],
)
def test_unparseable_values_raise_instead_of_becoming_nan(column: str, value: str) -> None:
    frame = price_frame(1, 3, seed=1).astype({column: object})
    frame.loc[1, column] = value
    with pytest.raises(DataValidationError, match="no parseable"):
        canonicalize(frame, Table.PRICES)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("FALSE", False), ("1", True), ("0", False), (None, None)],
)
def test_boolean_parsing(raw: object, expected: bool | None) -> None:
    frame = universe_frame(1, EligibleFlag=[raw])
    assert canonicalize(frame, Table.UNIVERSE)["EligibleFlag"].tolist() == [expected]


def test_unrecognized_boolean_raises() -> None:
    with pytest.raises(DataValidationError, match="booleano"):
        canonicalize(universe_frame(1, EligibleFlag=["yes"]), Table.UNIVERSE)


def test_missing_mandatory_file_is_explicit_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    source = CSVSource(TablePaths(prices=missing, universe=missing, holdings=missing))
    with pytest.raises(DataValidationError, match="No se puede leer"):
        source.load_prices()
