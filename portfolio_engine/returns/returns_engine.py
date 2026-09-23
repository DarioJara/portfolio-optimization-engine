"""Motor de retornos (MASTER_SPEC §9).

Por defecto (según configuración) retornos aritméticos ``r[t,i] = P[t,i] / P[t-1,i] − 1``.
Los log returns solo se admiten con justificación explícita en ``ReturnConfig`` y quedan
registrados en el log y en la propia ``ReturnsMatrix``.
"""

from __future__ import annotations

import logging

import numpy as np

from portfolio_engine.config.return_config import ReturnConfig
from portfolio_engine.exceptions import DataValidationError, InsufficientDataError
from portfolio_engine.models.enums import ReturnKind
from portfolio_engine.models.market_data import PriceHistory, ReturnsMatrix
from portfolio_engine.utils.logging import get_logger, log_event

_LOGGER = get_logger("returns")


class ReturnsEngine:
    """Calcula la matriz de retornos a partir de un histórico validado."""

    def __init__(self, config: ReturnConfig) -> None:
        self._config = config

    def compute(self, prices: PriceHistory) -> ReturnsMatrix:
        """Retornos T×N (fechas de fin de periodo) sin rellenar huecos.

        Lanza ``DataValidationError`` si hay celdas sin precio (calendarios desalineados) o
        precios no positivos: esos casos deben resolverse en la validación de datos.
        """
        dates, asset_ids, wide = prices.wide_prices()
        if np.isnan(wide).any():
            raise DataValidationError(
                "Hay fechas sin precio para algún activo; los retornos no rellenan huecos. "
                "Valide el histórico con MarketDataValidator."
            )
        if np.any(wide <= 0):
            raise DataValidationError("Precios no positivos: los retornos no están definidos.")
        if wide.shape[0] < 2:
            raise InsufficientDataError("Se necesitan al menos dos fechas para calcular retornos.")
        relative = wide[1:] / wide[:-1]
        if self._config.return_kind is ReturnKind.LOG:
            values = np.log(relative)
            log_event(
                _LOGGER,
                logging.INFO,
                "log_returns_used",
                justification=self._config.log_return_justification,
            )
        else:
            values = relative - 1.0
        return ReturnsMatrix(
            dates=dates[1:],
            asset_ids=asset_ids,
            values=values,
            kind=self._config.return_kind,
            justification=self._config.log_return_justification,
        )
