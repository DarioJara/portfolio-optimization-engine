"""Estimación interna por media histórica (MASTER_SPEC §8).

Es una estimación estadística, no alpha: se etiqueta ``INTERNAL_ESTIMATION`` /
``HISTORICAL_MEAN``.
"""

from __future__ import annotations

from collections.abc import Sequence

from portfolio_engine.exceptions import InsufficientDataError
from portfolio_engine.models.enums import ExpectedReturnMode, InternalEstimationMethod
from portfolio_engine.models.market_data import ReturnsMatrix
from portfolio_engine.models.risk_model import ExpectedReturns
from portfolio_engine.returns.annualization import annualize_mean


class HistoricalMeanProvider:
    """``mu_annual = TradingDays · media(r)`` sobre la matriz de retornos recibida."""

    def __init__(self, trading_days_per_year: int) -> None:
        self._trading_days = trading_days_per_year

    @property
    def mode(self) -> ExpectedReturnMode:
        """Siempre ``INTERNAL_ESTIMATION``."""
        return ExpectedReturnMode.INTERNAL_ESTIMATION

    def estimate(self, asset_ids: Sequence[str], returns: ReturnsMatrix | None) -> ExpectedReturns:
        """Media aritmética anualizada de los retornos de ``asset_ids``."""
        if returns is None or returns.n_observations == 0:
            raise InsufficientDataError("La media histórica exige una matriz de retornos no vacía.")
        values = returns.columns_for(asset_ids).mean(axis=0)
        return ExpectedReturns(
            asset_ids=tuple(asset_ids),
            values=annualize_mean(values, self._trading_days),
            mode=self.mode,
            method=InternalEstimationMethod.HISTORICAL_MEAN.value,
        )
