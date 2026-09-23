"""Resolución y validación de costes unitarios de transacción (MASTER_SPEC §6, §23; A-04).

Para cada activo se prueban las fuentes en el orden de ``source_precedence``:

* ``BUY_SELL``: ``BuyCost`` y ``SellCost`` (ambos presentes);
* ``ESTIMATED``: ``EstimatedTransactionCost`` simétrico;
* ``BID_ASK_SPREAD``: ``BidAskSpread / 2 + spread_commission`` simétrico.

Los valores del universo se convierten de ``input_unit`` a decimal. Un valor negativo, no
finito o superior a ``max_unit_cost`` es un error explícito. Un activo sin ninguna fuente se
reporta como ausente (nunca se asume coste cero).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from portfolio_engine.config.transaction_cost_config import TransactionCostConfig
from portfolio_engine.data.validation.report import DataQualityReport, IssueCode, IssueCollector
from portfolio_engine.exceptions import TransactionCostInputError
from portfolio_engine.models.asset import AssetMetadata, Universe
from portfolio_engine.models.costs import BPS_PER_UNIT, AssetCostVector
from portfolio_engine.models.enums import CostInputUnit, CostSource


@dataclass(frozen=True, slots=True)
class CostResolution:
    """Costes resueltos, activos sin coste disponible e informe."""

    costs: AssetCostVector
    missing_asset_ids: tuple[str, ...]
    report: DataQualityReport

    def require_complete(self) -> AssetCostVector:
        """Devuelve los costes o lanza ``TransactionCostInputError`` si falta algún activo."""
        if self.missing_asset_ids:
            raise TransactionCostInputError(
                f"Activos sin coste de transacción disponible: {list(self.missing_asset_ids)}"
            )
        return self.costs


def resolve_asset_costs(
    universe: Universe,
    config: TransactionCostConfig,
    asset_ids: Iterable[str] | None = None,
) -> CostResolution:
    """Resuelve los costes unitarios decimales de ``asset_ids`` (por defecto, todo el universo)."""
    collector = IssueCollector()
    wanted = sorted(set(universe.asset_ids if asset_ids is None else asset_ids))
    resolved: dict[str, _UnitCosts] = {}
    missing: list[str] = []
    for asset_id in wanted:
        costs = _resolve_one(universe.get(asset_id), config, collector)
        if costs is None:
            missing.append(asset_id)
        else:
            resolved[asset_id] = costs
    report = collector.report()
    if report.has_errors:
        raise TransactionCostInputError(
            f"Costes de transacción inválidos en {len(report.errors)} activo(s).", report.issues
        )
    vector = AssetCostVector(
        asset_ids=tuple(resolved),
        buy_costs=np.array([costs.buy for costs in resolved.values()], dtype=np.float64),
        sell_costs=np.array([costs.sell for costs in resolved.values()], dtype=np.float64),
        sources=tuple(costs.source for costs in resolved.values()),
    )
    return CostResolution(vector, tuple(missing), report)


def to_decimal(value: float, unit: CostInputUnit) -> float:
    """Convierte un coste unitario de ``unit`` a fracción decimal."""
    return value / BPS_PER_UNIT if unit is CostInputUnit.BPS else value


@dataclass(frozen=True, slots=True)
class _UnitCosts:
    buy: float
    sell: float
    source: CostSource


def _resolve_one(
    asset: AssetMetadata, config: TransactionCostConfig, collector: IssueCollector
) -> _UnitCosts | None:
    for source in config.source_precedence:
        candidate = _candidate(asset, source, config, collector)
        if candidate is not None:
            buy, sell = candidate
            if _valid(asset.asset_id, source, buy, sell, config, collector):
                return _UnitCosts(buy, sell, source)
            return None
    return None


def _candidate(
    asset: AssetMetadata,
    source: CostSource,
    config: TransactionCostConfig,
    collector: IssueCollector,
) -> tuple[float, float] | None:
    unit = config.input_unit
    if source is CostSource.BUY_SELL:
        buy, sell = asset.buy_cost, asset.sell_cost
        if buy is None and sell is None:
            return None
        if buy is None or sell is None:
            collector.warning(
                IssueCode.MISSING_METADATA,
                "BuyCost/SellCost incompleto: se prueba la siguiente fuente.",
                asset_id=asset.asset_id,
            )
            return None
        return to_decimal(buy, unit), to_decimal(sell, unit)
    if source is CostSource.ESTIMATED:
        if asset.estimated_transaction_cost is None:
            return None
        cost = to_decimal(asset.estimated_transaction_cost, unit)
        return cost, cost
    if asset.bid_ask_spread is None:
        return None
    half_spread = to_decimal(asset.bid_ask_spread, unit) / 2.0
    cost = half_spread + config.spread_commission
    return cost, cost


def _valid(
    asset_id: str,
    source: CostSource,
    buy: float,
    sell: float,
    config: TransactionCostConfig,
    collector: IssueCollector,
) -> bool:
    for side, value in (("compra", buy), ("venta", sell)):
        if not math.isfinite(value) or value < 0:
            collector.error(
                IssueCode.INVALID_VALUE,
                f"Coste de {side} {value!r} ({source}) no finito o negativo.",
                asset_id=asset_id,
            )
            return False
        if value > config.max_unit_cost:
            collector.error(
                IssueCode.INVALID_VALUE,
                f"Coste de {side} {value!r} ({source}) > max_unit_cost {config.max_unit_cost!r}: "
                "revise datos o unidades.",
                asset_id=asset_id,
            )
            return False
    return True
