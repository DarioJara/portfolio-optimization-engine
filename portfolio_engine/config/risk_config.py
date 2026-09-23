"""Configuración del modelo de riesgo (MASTER_SPEC §11)."""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_non_negative, require_positive
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import CovarianceMethod, PSDRepairMethod


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Parámetros de estimación, diagnóstico y reparación de la covarianza.

    Attributes:
        covariance_method: ``EMPIRICAL`` o ``LEDOIT_WOLF`` (OAS/EWMA diferidos, E-07).
        empirical_ddof: grados de libertad restados en la covarianza empírica (0 o 1).
        symmetry_tolerance: asimetría relativa máxima ``max|Σ−Σᵀ| / max|Σ|`` antes de
            simetrizar; por encima se rechaza la matriz (no se corrige en silencio).
        psd_tolerance: una matriz es PSD si ``λ_min ≥ −psd_tolerance · max|λ|``.
        repair_method: ``NONE`` (error si no es PSD), ``EIGENVALUE_FLOOR`` o ``NEAREST_PSD``.
        eigenvalue_floor_relative: suelo relativo ``λ ≥ floor · λ_max`` (solo ``EIGENVALUE_FLOOR``).
        condition_number_limit: si se define, una matriz PSD con número de condición superior
            se repara con ``EIGENVALUE_FLOOR``; ``None`` = solo se registra.
    """

    covariance_method: CovarianceMethod
    empirical_ddof: int
    symmetry_tolerance: float
    psd_tolerance: float
    repair_method: PSDRepairMethod
    eigenvalue_floor_relative: float | None
    condition_number_limit: float | None

    def __post_init__(self) -> None:
        if isinstance(self.empirical_ddof, bool) or self.empirical_ddof not in (0, 1):
            raise ConfigError("empirical_ddof debe ser 0 o 1.")
        require_positive(self.symmetry_tolerance, "symmetry_tolerance")
        require_non_negative(self.psd_tolerance, "psd_tolerance")
        uses_floor = self.repair_method is PSDRepairMethod.EIGENVALUE_FLOOR
        if uses_floor:
            if self.eigenvalue_floor_relative is None:
                raise ConfigError("EIGENVALUE_FLOOR exige eigenvalue_floor_relative.")
            require_positive(self.eigenvalue_floor_relative, "eigenvalue_floor_relative")
        elif self.eigenvalue_floor_relative is not None:
            raise ConfigError("eigenvalue_floor_relative solo se admite con EIGENVALUE_FLOOR.")
        if self.condition_number_limit is not None:
            require_positive(self.condition_number_limit, "condition_number_limit")
            if not uses_floor:
                raise ConfigError(
                    "condition_number_limit exige repair_method EIGENVALUE_FLOOR: es el único "
                    "método que mejora el condicionamiento."
                )
