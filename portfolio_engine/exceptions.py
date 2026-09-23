"""Jerarquía de excepciones propias del motor (MASTER_SPEC §3).

Todas las excepciones del motor derivan de :class:`PortfolioEngineError`, de modo que un
llamador puede distinguir errores del motor de errores de programación genéricos.
"""

from __future__ import annotations

from collections.abc import Sequence


class PortfolioEngineError(Exception):
    """Base de todas las excepciones del motor."""


class ConfigError(PortfolioEngineError):
    """Configuración ausente, desconocida, mal tipada o incoherente."""


class DataValidationError(PortfolioEngineError):
    """Los datos de entrada no superan la validación (MASTER_SPEC §10).

    ``issues`` contiene los problemas detectados (objetos ``DataIssue``) para que el
    llamador pueda auditarlos; nunca se corrigen datos silenciosamente.
    """

    def __init__(self, message: str, issues: Sequence[object] = ()) -> None:
        super().__init__(message)
        self.issues: tuple[object, ...] = tuple(issues)


class AssetResolutionError(DataValidationError):
    """Un identificador (AssetID o Ticker) no puede resolverse de forma inequívoca."""


class InsufficientDataError(DataValidationError):
    """No hay observaciones suficientes para el cálculo solicitado."""


class TransactionCostInputError(DataValidationError):
    """Los datos de costes de transacción son inválidos (MASTER_SPEC §6, §23)."""


class CovarianceEstimationError(PortfolioEngineError):
    """Fallo al estimar o validar una matriz de covarianza (MASTER_SPEC §11)."""


class NotPositiveSemidefiniteError(CovarianceEstimationError):
    """La matriz no es PSD y la configuración no autoriza su reparación."""
