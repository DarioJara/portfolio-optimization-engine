"""Enumeraciones del Bloque 1.

Solo se definen valores cuya funcionalidad existe. Los métodos diferidos (p. ej. ``OAS`` y
``EWMA`` para covarianza, enmienda E-07) se añadirán junto con su implementación para no
exponer opciones seleccionables sin implementar.
"""

from __future__ import annotations

from enum import StrEnum


class ReturnKind(StrEnum):
    """Tipo de retorno (MASTER_SPEC §9). ``LOG`` exige justificación explícita."""

    ARITHMETIC = "ARITHMETIC"
    LOG = "LOG"


class ExpectedReturnMode(StrEnum):
    """Origen de los expected returns (MASTER_SPEC §8)."""

    INTERNAL_ESTIMATION = "INTERNAL_ESTIMATION"
    EXTERNAL_ALPHA = "EXTERNAL_ALPHA"


class InternalEstimationMethod(StrEnum):
    """Métodos internos implementados. EWMA, factoriales, bayesianos y señales son futuros."""

    HISTORICAL_MEAN = "HISTORICAL_MEAN"


class CovarianceMethod(StrEnum):
    """Estimadores de covarianza implementados (MASTER_SPEC §11; OAS/EWMA diferidos, E-07)."""

    EMPIRICAL = "EMPIRICAL"
    LEDOIT_WOLF = "LEDOIT_WOLF"


class PSDRepairMethod(StrEnum):
    """Reparación de matrices no PSD (MASTER_SPEC §11)."""

    NONE = "NONE"
    EIGENVALUE_FLOOR = "EIGENVALUE_FLOOR"
    NEAREST_PSD = "NEAREST_PSD"


class RestrictedExistingPositionPolicy(StrEnum):
    """Tratamiento de activos restringidos ya presentes en cartera (MASTER_SPEC §12, E-09)."""

    HOLD_OR_REDUCE = "HOLD_OR_REDUCE"
    FREEZE_WEIGHT = "FREEZE_WEIGHT"
    FORCE_LIQUIDATE = "FORCE_LIQUIDATE"


class CostInputUnit(StrEnum):
    """Unidad en la que llegan los costes unitarios del universo."""

    DECIMAL = "DECIMAL"
    BPS = "BPS"


class CostSource(StrEnum):
    """Fuente de coste unitario utilizada para un activo (precedencia configurable)."""

    BUY_SELL = "BUY_SELL"
    ESTIMATED = "ESTIMATED"
    BID_ASK_SPREAD = "BID_ASK_SPREAD"


class IssueSeverity(StrEnum):
    """Severidad de un problema de calidad de datos."""

    WARNING = "WARNING"
    ERROR = "ERROR"


class AssetErrorPolicy(StrEnum):
    """Qué hacer con un activo que tiene errores de datos: detener o excluirlo (registrado)."""

    FAIL = "FAIL"
    EXCLUDE_ASSET = "EXCLUDE_ASSET"


class ResidualWeightPolicy(StrEnum):
    """Qué hacer si los pesos actuales no suman 1 dentro de la tolerancia (decisión A-34)."""

    ERROR = "ERROR"
    ASSIGN_TO_CASH = "ASSIGN_TO_CASH"


class OutlierMethod(StrEnum):
    """Método de detección de outliers en retornos (solo detecta; nunca corrige)."""

    ROBUST_ZSCORE = "ROBUST_ZSCORE"


class BoundSource(StrEnum):
    """Procedencia de un límite de peso efectivo (precedencia de ARCHITECTURE §6.4)."""

    PORTFOLIO_OVERRIDE = "PORTFOLIO_OVERRIDE"
    GLOBAL_CONFIG = "GLOBAL_CONFIG"
    UNIVERSE = "UNIVERSE"
    UNSET = "UNSET"
