"""Configuración de validación de datos (MASTER_SPEC §10, decisión A-34)."""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import (
    require_int_at_least,
    require_non_negative,
    require_positive,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import (
    AssetErrorPolicy,
    IssueSeverity,
    OutlierMethod,
    ResidualWeightPolicy,
)

#: Una covarianza muestral necesita al menos dos observaciones de retorno.
_MIN_RETURN_OBSERVATIONS_FLOOR = 2


@dataclass(frozen=True, slots=True)
class DataConfig:
    """Parámetros de validación de datos. Ninguno tiene valor por defecto implícito.

    Attributes:
        min_return_observations: mínimo de retornos por activo (histórico insuficiente).
        max_stale_run: máximo de retornos nulos consecutivos (precios repetidos) antes de marcar
            el activo como "stale".
        stale_price_severity: severidad asignada a precios stale.
        outlier_method: método de detección de outliers (solo detecta, no corrige).
        outlier_threshold: umbral del estadístico de outlier.
        outlier_severity: severidad asignada a outliers.
        max_calendar_gap_days: máximo de días naturales entre observaciones consecutivas.
        calendar_gap_severity: severidad de huecos de calendario.
        asset_error_policy: detener (``FAIL``) o excluir el activo con errores (registrado).
        weight_sum_tolerance: tolerancia absoluta de ``|Σ CurrentWeight − 1|``.
        residual_weight_policy: tratamiento de residuos de peso fuera de tolerancia.
        cash_asset_id: activo de caja que recibe el residuo si la política es ``ASSIGN_TO_CASH``.
    """

    min_return_observations: int
    max_stale_run: int
    stale_price_severity: IssueSeverity
    outlier_method: OutlierMethod
    outlier_threshold: float
    outlier_severity: IssueSeverity
    max_calendar_gap_days: int
    calendar_gap_severity: IssueSeverity
    asset_error_policy: AssetErrorPolicy
    weight_sum_tolerance: float
    residual_weight_policy: ResidualWeightPolicy
    cash_asset_id: str | None

    def __post_init__(self) -> None:
        require_int_at_least(
            self.min_return_observations, _MIN_RETURN_OBSERVATIONS_FLOOR, "min_return_observations"
        )
        require_int_at_least(self.max_stale_run, 1, "max_stale_run")
        require_int_at_least(self.max_calendar_gap_days, 1, "max_calendar_gap_days")
        require_positive(self.outlier_threshold, "outlier_threshold")
        require_non_negative(self.weight_sum_tolerance, "weight_sum_tolerance")
        if self.residual_weight_policy is ResidualWeightPolicy.ASSIGN_TO_CASH:
            if not self.cash_asset_id:
                raise ConfigError("ASSIGN_TO_CASH exige cash_asset_id.")
        elif self.cash_asset_id is not None:
            raise ConfigError(
                "cash_asset_id solo se admite con residual_weight_policy ASSIGN_TO_CASH."
            )
