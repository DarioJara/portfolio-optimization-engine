"""Anualización lineal configurable (MASTER_SPEC §9).

``mu_annual = TradingDays · mu_daily`` y ``Sigma_annual = TradingDays · Sigma_daily``.
``TradingDays`` procede siempre de ``ReturnConfig.trading_days_per_year``.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import ConfigError


def _check_trading_days(trading_days: int) -> None:
    if isinstance(trading_days, bool) or not isinstance(trading_days, int) or trading_days <= 0:
        raise ConfigError(f"trading_days debe ser un entero positivo (recibido {trading_days!r}).")


def annualize_mean(
    mean_per_period: npt.NDArray[np.float64], trading_days: int
) -> npt.NDArray[np.float64]:
    """Anualiza medias por periodo: ``TradingDays · mu``."""
    _check_trading_days(trading_days)
    return np.asarray(mean_per_period, dtype=np.float64) * float(trading_days)


def annualize_covariance(
    covariance_per_period: npt.NDArray[np.float64], trading_days: int
) -> npt.NDArray[np.float64]:
    """Anualiza una covarianza por periodo: ``TradingDays · Sigma``."""
    _check_trading_days(trading_days)
    return np.asarray(covariance_per_period, dtype=np.float64) * float(trading_days)
