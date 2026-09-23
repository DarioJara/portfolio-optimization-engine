"""Selección del proveedor de expected returns según configuración (única fuente de verdad)."""

from __future__ import annotations

from portfolio_engine.config.return_config import ReturnConfig
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import ExpectedReturnMode, InternalEstimationMethod
from portfolio_engine.models.risk_model import ExternalAlpha
from portfolio_engine.returns.expected.base import ExpectedReturnProvider
from portfolio_engine.returns.expected.external_alpha import ExternalAlphaProvider
from portfolio_engine.returns.expected.historical_mean import HistoricalMeanProvider


def make_expected_return_provider(
    config: ReturnConfig, external_alpha: ExternalAlpha | None
) -> ExpectedReturnProvider:
    """Construye el proveedor indicado por ``config.expected_return_mode``."""
    if config.expected_return_mode is ExpectedReturnMode.EXTERNAL_ALPHA:
        if external_alpha is None:
            raise ConfigError("expected_return_mode EXTERNAL_ALPHA exige datos de alpha externo.")
        return ExternalAlphaProvider(external_alpha)
    if config.internal_estimation_method is InternalEstimationMethod.HISTORICAL_MEAN:
        return HistoricalMeanProvider(config.trading_days_per_year)
    raise ConfigError(f"Método interno no soportado: {config.internal_estimation_method}")
