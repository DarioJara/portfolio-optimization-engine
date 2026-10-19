"""Configuración de la optimización robusta (MASTER_SPEC §52; CFG-001, CFG-015).

Distingue tres cosas que no deben confundirse: *shrinkage* (un estimador de ``μ``, no es
optimización robusta), *conjuntos de incertidumbre* (``μ`` en caja o elipsoide, ``Σ`` escalada) y
*escenarios deterministas* (Bloque 4, ``ScenarioEngine``). Sin defaults implícitos.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_finite, require_non_negative
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import MuUncertaintyKind, ShrinkageMethod, ShrinkageTarget


@dataclass(frozen=True, slots=True)
class RobustConfig:
    """Parámetros de los conjuntos de incertidumbre y del shrinkage de ``μ``.

    Incertidumbre de ``μ`` (error estándar de la media con observaciones iid, ``Ω = Σ/T``):

    * ``BOX``: ``|μ_i − μ̂_i| ≤ δ_i``, ``δ_i = box_z·√(Σ_ii/T)``.
    * ``ELLIPSOIDAL``: ``(μ − μ̂)ᵀ Ω⁻¹ (μ − μ̂) ≤ κ²`` con ``κ² = χ²_{n}(ellipsoid_confidence)``.

    Attributes:
        mu_uncertainty: tipo de conjunto de incertidumbre de ``μ`` (``NONE`` = sin incertidumbre).
        box_z: multiplicador del error estándar del conjunto en caja (solo ``BOX``).
        ellipsoid_confidence: nivel de confianza en ``(0, 1)`` del elipsoide (solo ``ELLIPSOIDAL``).
        covariance_scale_max: cota ``s ≥ 1`` del conjunto de covarianzas ``{aΣ : a ∈ [1, s]}``
            (``None`` = sin incertidumbre en ``Σ``); el peor caso es ``sΣ``.
        shrinkage_method: estimador de shrinkage de ``μ`` (``None`` = sin shrinkage).
        shrinkage_intensity: intensidad ``δ ∈ [0, 1]`` (solo ``FIXED_INTENSITY``).
        shrinkage_target: destino del shrinkage (con ``shrinkage_method``).
    """

    mu_uncertainty: MuUncertaintyKind
    box_z: float | None
    ellipsoid_confidence: float | None
    covariance_scale_max: float | None
    shrinkage_method: ShrinkageMethod | None
    shrinkage_intensity: float | None
    shrinkage_target: ShrinkageTarget | None

    def __post_init__(self) -> None:
        kind = self.mu_uncertainty
        if kind is MuUncertaintyKind.BOX:
            if self.box_z is None:
                raise ConfigError("robust.mu_uncertainty = BOX exige robust.box_z.")
            require_non_negative(self.box_z, "robust.box_z")
        elif self.box_z is not None:
            raise ConfigError("robust.box_z solo se admite con mu_uncertainty = BOX.")
        if kind is MuUncertaintyKind.ELLIPSOIDAL:
            confidence = self.ellipsoid_confidence
            if confidence is None:
                raise ConfigError("ELLIPSOIDAL exige robust.ellipsoid_confidence.")
            require_finite(confidence, "robust.ellipsoid_confidence")
            if not 0.0 < confidence < 1.0:
                raise ConfigError("robust.ellipsoid_confidence debe estar en (0, 1).")
        elif self.ellipsoid_confidence is not None:
            raise ConfigError("robust.ellipsoid_confidence solo se admite con ELLIPSOIDAL.")
        if self.covariance_scale_max is not None:
            require_finite(self.covariance_scale_max, "robust.covariance_scale_max")
            if self.covariance_scale_max < 1.0:
                raise ConfigError("robust.covariance_scale_max debe ser >= 1.")
        self._check_shrinkage()

    def _check_shrinkage(self) -> None:
        method = self.shrinkage_method
        if method is None:
            if self.shrinkage_intensity is not None or self.shrinkage_target is not None:
                raise ConfigError("robust.shrinkage_* exige robust.shrinkage_method.")
            return
        if self.shrinkage_target is None:
            raise ConfigError("robust.shrinkage_method exige robust.shrinkage_target.")
        if method is ShrinkageMethod.FIXED_INTENSITY:
            intensity = self.shrinkage_intensity
            if intensity is None:
                raise ConfigError("FIXED_INTENSITY exige robust.shrinkage_intensity.")
            require_finite(intensity, "robust.shrinkage_intensity")
            if not 0.0 <= intensity <= 1.0:
                raise ConfigError("robust.shrinkage_intensity debe estar en [0, 1].")
        elif self.shrinkage_intensity is not None:
            raise ConfigError("JORION estima la intensidad: no admite shrinkage_intensity.")
