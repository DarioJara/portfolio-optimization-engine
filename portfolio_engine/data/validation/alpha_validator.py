"""Validación de alpha externo (MASTER_SPEC §8; E-03).

El alpha llega como retorno esperado simple sobre ``HorizonYears`` años y se convierte a base
anualizada con la convención lineal de §9: ``alpha_anual = alpha_H / HorizonYears``. La
comparación con el horizonte de optimización (``OptimizationHorizonYears``) se hace aguas
abajo sobre la base anualizada.
"""

from __future__ import annotations

import math

import pandas as pd

from portfolio_engine.data.validation.report import IssueCode, IssueCollector
from portfolio_engine.exceptions import AssetResolutionError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.risk_model import ExternalAlpha

REQUIRED_COLUMNS = ("ExpectedReturn", "HorizonYears")


def build_external_alpha(frame: pd.DataFrame, universe: Universe, source: str) -> ExternalAlpha:
    """Valida la tabla canónica de alpha y devuelve :class:`ExternalAlpha` anualizado."""
    collector = IssueCollector()
    identifier = "AssetID" if "AssetID" in frame.columns else "Ticker"
    missing = [c for c in (*REQUIRED_COLUMNS, identifier) if c not in frame.columns]
    if missing:
        collector.error(IssueCode.SCHEMA, f"Columnas obligatorias ausentes: {missing}")
        collector.report().raise_if_errors("Alpha externo")
    values: dict[str, float] = {}
    for row in frame.to_dict("records"):
        asset_id = _resolve(row.get(identifier), universe, collector)
        annualized = _annualized(row, asset_id, collector)
        if asset_id is None or annualized is None:
            continue
        if asset_id in values:
            collector.error(IssueCode.DUPLICATE, "Alpha duplicado.", asset_id=asset_id)
            continue
        values[asset_id] = annualized
    collector.report().raise_if_errors("Alpha externo")
    asset_ids = tuple(sorted(values))
    return ExternalAlpha(asset_ids, [values[a] for a in asset_ids], source)  # type: ignore[arg-type]


def _resolve(value: object, universe: Universe, collector: IssueCollector) -> str | None:
    if not isinstance(value, str):
        collector.error(IssueCode.MISSING_METADATA, "Fila de alpha sin identificador.")
        return None
    try:
        return universe.resolve(value)
    except AssetResolutionError as error:
        collector.error(IssueCode.UNKNOWN_ASSET, str(error), asset_id=value)
        return None


def _annualized(
    row: dict[str, object], asset_id: str | None, collector: IssueCollector
) -> float | None:
    expected = row.get("ExpectedReturn")
    horizon = row.get("HorizonYears")
    if not isinstance(expected, float) or not math.isfinite(expected):
        collector.error(
            IssueCode.INVALID_VALUE, "ExpectedReturn ausente o no finito.", asset_id=asset_id
        )
        return None
    if not isinstance(horizon, float) or not math.isfinite(horizon) or horizon <= 0:
        collector.error(
            IssueCode.INVALID_VALUE, "HorizonYears debe ser finito y > 0.", asset_id=asset_id
        )
        return None
    return expected / horizon
