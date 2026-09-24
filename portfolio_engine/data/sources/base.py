"""Contrato de fuentes de datos y canonicalización de tablas (MASTER_SPEC §5.1).

El optimizador nunca depende del origen físico: toda fuente devuelve las mismas tablas
canónicas (mismos nombres de columna y tipos). La canonicalización es estricta: un valor no
parseable como número, fecha o booleano es un error explícito, nunca un ``NaN`` silencioso.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

import numpy as np
import pandas as pd

from portfolio_engine.exceptions import DataValidationError

_TRUE_TOKENS = frozenset({"true", "1"})
_FALSE_TOKENS = frozenset({"false", "0"})


class Table(StrEnum):
    """Tablas lógicas de entrada."""

    PRICES = "PRICES"
    UNIVERSE = "UNIVERSE"
    HOLDINGS = "HOLDINGS"
    PORTFOLIO_SPECS = "PORTFOLIO_SPECS"
    WEIGHT_OVERRIDES = "WEIGHT_OVERRIDES"
    EXTERNAL_ALPHA = "EXTERNAL_ALPHA"


@dataclass(frozen=True, slots=True)
class TableSchema:
    """Tipos de columna conocidos de una tabla. Columnas extra se conservan como texto."""

    text: tuple[str, ...] = ()
    numeric: tuple[str, ...] = ()
    boolean: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()

    @property
    def columns(self) -> tuple[str, ...]:
        """Columnas conocidas en orden canónico."""
        return self.dates + self.text + self.boolean + self.numeric


SCHEMAS: Mapping[Table, TableSchema] = MappingProxyType(
    {
        Table.PRICES: TableSchema(
            dates=("Date",),
            text=("AssetID", "Ticker"),
            numeric=("AdjustedClose", "Volume", "Bid", "Ask", "FXRate", "MarketCap"),
        ),
        Table.UNIVERSE: TableSchema(
            text=(
                "AssetID",
                "Ticker",
                "Sector",
                "Industry",
                "Country",
                "Currency",
                "AssetClass",
                "ADVCurrency",
                "ADVUnit",
                "ADVSource",
            ),
            boolean=("EligibleFlag", "LiquidityFlag", "RestrictedAssetFlag"),
            numeric=(
                "MinWeight",
                "MaxWeight",
                "EstimatedTransactionCost",
                "BuyCost",
                "SellCost",
                "BidAskSpread",
                "ADV",
                "MarketCap",
            ),
        ),
        Table.HOLDINGS: TableSchema(
            text=("PortfolioID", "AssetID", "Ticker"), numeric=("CurrentWeight",)
        ),
        Table.PORTFOLIO_SPECS: TableSchema(
            text=(
                "PortfolioID",
                "InvestmentUniverse",
                "RestrictedExistingPositionPolicy",
                "NAVCurrency",
            ),
            numeric=("TargetPortfolioSize", "VolatilityLimit", "MaxTurnover", "NAV"),
        ),
        Table.WEIGHT_OVERRIDES: TableSchema(
            text=("PortfolioID", "AssetID", "Ticker"), numeric=("MinWeight", "MaxWeight")
        ),
        Table.EXTERNAL_ALPHA: TableSchema(
            text=("AssetID", "Ticker", "Source"), numeric=("ExpectedReturn", "HorizonYears")
        ),
    }
)


class DataSource(Protocol):
    """Fuente de datos intercambiable. Devuelve tablas canónicas (ver :func:`canonicalize`)."""

    def load_prices(self) -> pd.DataFrame:
        """Histórico de mercado (Date, AssetID/Ticker, AdjustedClose, opcionales)."""
        ...

    def load_universe(self) -> pd.DataFrame:
        """Universo de inversión (§6)."""
        ...

    def load_current_portfolios(self) -> pd.DataFrame:
        """Carteras actuales (PortfolioID, AssetID/Ticker, CurrentWeight)."""
        ...

    def load_portfolio_specs(self) -> pd.DataFrame | None:
        """Configuración por cartera (§7) o ``None`` si no existe."""
        ...

    def load_weight_overrides(self) -> pd.DataFrame | None:
        """Límites de peso por cartera y activo o ``None``."""
        ...

    def load_external_alpha(self) -> pd.DataFrame | None:
        """Alpha externo (§8) o ``None``."""
        ...


def canonicalize(frame: pd.DataFrame, table: Table) -> pd.DataFrame:
    """Devuelve una copia con nombres y tipos canónicos para ``table``.

    Texto → ``object`` con ``str`` o ``None``; numérico → ``float64``; booleano → ``object``
    con ``bool`` o ``None``; fechas → ``datetime64[ns]``. Lanza :class:`DataValidationError`
    ante valores no parseables.
    """
    schema = SCHEMAS[table]
    data = frame.copy()
    data.columns = [str(column).strip() for column in data.columns]
    if len(set(data.columns)) != len(data.columns):
        raise DataValidationError(f"{table}: nombres de columna duplicados.")
    for column in data.columns:
        data[column] = _convert_column(data[column], column, schema, table)
    known = [column for column in schema.columns if column in data.columns]
    extra = sorted(column for column in data.columns if column not in schema.columns)
    return data.loc[:, known + extra].reset_index(drop=True)


def _convert_column(series: pd.Series, column: str, schema: TableSchema, table: Table) -> Any:
    try:
        if column in schema.dates:
            return pd.to_datetime(series, errors="raise").astype("datetime64[ns]")
        if column in schema.numeric:
            if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
                return series.astype(np.float64)
            return series.map(_parse_float).astype(np.float64)
    except (ValueError, TypeError) as error:
        raise DataValidationError(f"{table}.{column}: valor no parseable ({error}).") from error
    if column in schema.boolean:
        return series.map(lambda value: _parse_bool(value, f"{table}.{column}")).astype(object)
    return series.map(_to_text).astype(object)


def _parse_float(value: object) -> float:
    """Parseo exacto (redondeo correcto de ``float()``) de números llegados como texto.

    ``pandas.to_numeric`` sobre texto usa un parser rápido que no garantiza el redondeo
    correcto; aquí se exige que el texto de un CSV reproduzca exactamente el float original.
    """
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return float("nan")
    if isinstance(value, bool):
        raise ValueError(f"booleano {value!r} en columna numérica")
    text = str(value).strip()
    return float("nan") if text == "" else float(text)


def _to_text(value: object) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _parse_bool(value: object, where: str) -> bool | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    if token == "":
        return None
    raise DataValidationError(f"{where}: valor booleano no reconocido {value!r}.")
