"""Generadores sintéticos deterministas para tests (semilla explícita en cada llamada)."""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pandas as pd

from portfolio_engine.config import EngineConfig

START_DATE = "2024-01-01"


def asset_ids(n_assets: int) -> list[str]:
    """``A000``, ``A001``, …"""
    return [f"A{i:03d}" for i in range(n_assets)]


def universe_frame(n_assets: int, **overrides: list[Any]) -> pd.DataFrame:
    """Universo completo y válido; ``overrides`` sustituye columnas enteras."""
    ids = asset_ids(n_assets)
    data: dict[str, list[Any]] = {
        "AssetID": ids,
        "Ticker": [f"T{i:03d}" for i in range(n_assets)],
        "Sector": ["Tech", "Energy"] * (n_assets // 2) + ["Tech"] * (n_assets % 2),
        "Industry": ["Ind"] * n_assets,
        "Country": ["ES"] * n_assets,
        "Currency": ["EUR"] * n_assets,
        "AssetClass": ["Equity"] * n_assets,
        "EligibleFlag": [True] * n_assets,
        "LiquidityFlag": [True] * n_assets,
        "MinWeight": [0.0] * n_assets,
        "MaxWeight": [0.5] * n_assets,
        "EstimatedTransactionCost": [10.0] * n_assets,
        "BuyCost": [5.0] * n_assets,
        "SellCost": [7.0] * n_assets,
        "BidAskSpread": [4.0] * n_assets,
        "ADV": [1e6] * n_assets,
        "MarketCap": [1e9] * n_assets,
        "RestrictedAssetFlag": [False] * n_assets,
    }
    data.update(overrides)
    return pd.DataFrame(data)


def price_frame(n_assets: int, n_dates: int, seed: int) -> pd.DataFrame:
    """Precios log-normales en días hábiles, formato largo."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(START_DATE, periods=n_dates)
    log_returns = rng.normal(0.0003, 0.01, size=(n_dates - 1, n_assets))
    levels = 100.0 * np.exp(np.vstack([np.zeros(n_assets), np.cumsum(log_returns, axis=0)]))
    ids = asset_ids(n_assets)
    return pd.DataFrame(
        {
            "Date": np.repeat(dates.to_numpy(), n_assets),
            "AssetID": ids * n_dates,
            "AdjustedClose": levels.reshape(-1),
        }
    )


def holdings_frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """``[(PortfolioID, AssetID, CurrentWeight), …]``."""
    return pd.DataFrame(rows, columns=["PortfolioID", "AssetID", "CurrentWeight"])


def replace_section(config: EngineConfig, section: str, **changes: Any) -> EngineConfig:
    """Copia de ``config`` con campos cambiados en una subsección (valida de nuevo)."""
    updated = dataclasses.replace(getattr(config, section), **changes)
    return dataclasses.replace(config, **{section: updated})


def random_spd(n: int, seed: int) -> np.ndarray:
    """Matriz simétrica definida positiva bien condicionada."""
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, n))
    return factor @ factor.T + n * np.eye(n)
