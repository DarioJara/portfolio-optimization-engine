"""Validación del universo de inversión (MASTER_SPEC §6, §10; decisiones A-30, A-31)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pandas as pd

from portfolio_engine.config.constraint_config import ConstraintConfig
from portfolio_engine.data.validation.report import DataQualityReport, IssueCode, IssueCollector
from portfolio_engine.models.asset import AssetMetadata, Universe
from portfolio_engine.models.enums import AdvUnit, GroupDimension

REQUIRED_COLUMNS = ("AssetID", "Ticker", "EligibleFlag")
RECOMMENDED_TEXT = ("Sector", "Country", "Currency", "AssetClass")
#: Columna del universo que exige cada dimensión de límite de grupo (DAT-028, Bloque 2).
GROUP_COLUMN = MappingProxyType(
    {
        GroupDimension.SECTOR: "Sector",
        GroupDimension.COUNTRY: "Country",
        GroupDimension.ASSET_CLASS: "AssetClass",
        GroupDimension.CURRENCY: "Currency",
    }
)
_NON_NEGATIVE_NUMERIC = (
    "EstimatedTransactionCost",
    "BuyCost",
    "SellCost",
    "BidAskSpread",
    "ADV",
    "MarketCap",
)
_WEIGHT_COLUMNS = ("MinWeight", "MaxWeight")


@dataclass(frozen=True, slots=True)
class UniverseResult:
    """Universo validado y su informe de calidad."""

    universe: Universe
    report: DataQualityReport


class UniverseValidator:
    """Valida el universo canónico y construye :class:`Universe`.

    Los errores de metadatos del universo son siempre fatales (integridad de referencia);
    los metadatos recomendados ausentes se registran como avisos.
    """

    def __init__(self, constraints: ConstraintConfig) -> None:
        self._constraints = constraints

    def validate(self, frame: pd.DataFrame) -> UniverseResult:
        """Valida ``frame`` y devuelve el universo; lanza ``DataValidationError`` si hay errores."""
        collector = IssueCollector()
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            collector.error(IssueCode.SCHEMA, f"Columnas obligatorias ausentes: {missing}")
            collector.report().raise_if_errors("Universo")
        self._check_duplicates(frame, collector)
        assets = [
            asset
            for row in frame.to_dict("records")
            if (asset := self._build_asset(row, collector)) is not None
        ]
        report = collector.report()
        report.raise_if_errors("Universo")
        return UniverseResult(Universe(assets), report)

    @staticmethod
    def _check_duplicates(frame: pd.DataFrame, collector: IssueCollector) -> None:
        ids = frame["AssetID"].dropna()
        for asset_id in sorted(set(ids[ids.duplicated()])):
            collector.error(IssueCode.DUPLICATE, "AssetID duplicado.", asset_id=asset_id)
        tickers = frame["Ticker"].dropna()
        for ticker in sorted(set(tickers[tickers.duplicated()])):
            collector.error(
                IssueCode.AMBIGUOUS_TICKER, f"Ticker {ticker!r} asignado a varios activos."
            )

    def _build_asset(self, row: dict[str, Any], collector: IssueCollector) -> AssetMetadata | None:
        asset_id = _text(row.get("AssetID"))
        ticker = _text(row.get("Ticker"))
        eligible = row.get("EligibleFlag")
        if asset_id is None or ticker is None or not isinstance(eligible, bool):
            collector.error(
                IssueCode.MISSING_METADATA,
                "AssetID, Ticker y EligibleFlag son obligatorios.",
                asset_id=asset_id,
            )
            return None
        required = {GROUP_COLUMN[limit.dimension] for limit in self._constraints.group_limits}
        for column in RECOMMENDED_TEXT:
            if _text(row.get(column)) is not None:
                continue
            if column in required:
                collector.error(
                    IssueCode.MISSING_METADATA,
                    f"{column} es obligatorio: hay límites de grupo configurados sobre él.",
                    asset_id=asset_id,
                )
            else:
                collector.warning(
                    IssueCode.MISSING_RECOMMENDED_METADATA, f"{column} ausente.", asset_id=asset_id
                )
        if row.get("RestrictedAssetFlag") is None:
            collector.warning(
                IssueCode.RESTRICTED_STATUS_UNKNOWN,
                "RestrictedAssetFlag ausente: el activo no podrá mantenerse en cartera sin "
                "conocer su estado de restricción.",
                asset_id=asset_id,
            )
        numbers = {
            column: self._number(row, column, asset_id, collector)
            for column in (*_WEIGHT_COLUMNS, *_NON_NEGATIVE_NUMERIC)
        }
        self._check_limits(asset_id, numbers["MinWeight"], numbers["MaxWeight"], collector)
        unit = _text(row.get("ADVUnit"))
        if unit is not None and unit not in AdvUnit.__members__:
            collector.error(
                IssueCode.INVALID_VALUE,
                f"ADVUnit desconocida {unit!r}: use {sorted(AdvUnit.__members__)}.",
                asset_id=asset_id,
            )
            return None
        return AssetMetadata(
            asset_id=asset_id,
            ticker=ticker,
            eligible=eligible,
            sector=_text(row.get("Sector")),
            industry=_text(row.get("Industry")),
            country=_text(row.get("Country")),
            currency=_text(row.get("Currency")),
            asset_class=_text(row.get("AssetClass")),
            liquidity_flag=_bool(row.get("LiquidityFlag")),
            min_weight=numbers["MinWeight"],
            max_weight=numbers["MaxWeight"],
            estimated_transaction_cost=numbers["EstimatedTransactionCost"],
            buy_cost=numbers["BuyCost"],
            sell_cost=numbers["SellCost"],
            bid_ask_spread=numbers["BidAskSpread"],
            adv=numbers["ADV"],
            market_cap=numbers["MarketCap"],
            restricted=_bool(row.get("RestrictedAssetFlag")),
            adv_currency=_text(row.get("ADVCurrency")),
            adv_unit=None if unit is None else AdvUnit[unit],
            adv_source=_text(row.get("ADVSource")),
        )

    @staticmethod
    def _number(
        row: dict[str, Any], column: str, asset_id: str, collector: IssueCollector
    ) -> float | None:
        value = row.get(column)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        number = float(value)
        if not math.isfinite(number):
            collector.error(IssueCode.NON_FINITE_VALUE, f"{column} no finito.", asset_id=asset_id)
            return None
        if column in _NON_NEGATIVE_NUMERIC and number < 0:
            collector.error(IssueCode.INVALID_VALUE, f"{column} negativo.", asset_id=asset_id)
        return number

    def _check_limits(
        self,
        asset_id: str,
        min_weight: float | None,
        max_weight: float | None,
        collector: IssueCollector,
    ) -> None:
        if min_weight is not None and max_weight is not None and min_weight > max_weight:
            collector.error(
                IssueCode.INCOMPATIBLE_LIMITS,
                f"MinWeight {min_weight} > MaxWeight {max_weight}.",
                asset_id=asset_id,
            )
        if self._constraints.long_only:
            for name, value in (("MinWeight", min_weight), ("MaxWeight", max_weight)):
                if value is not None and value < 0:
                    collector.error(
                        IssueCode.INCOMPATIBLE_LIMITS,
                        f"{name} negativo con long_only.",
                        asset_id=asset_id,
                    )
        if min_weight is not None and min_weight > 1:
            collector.error(
                IssueCode.INCOMPATIBLE_LIMITS,
                f"MinWeight {min_weight} > 1 es incompatible con Σw = 1.",
                asset_id=asset_id,
            )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
