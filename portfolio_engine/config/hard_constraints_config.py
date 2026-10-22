"""Parámetros declarativos de las restricciones obligatorias de carteras finales (HC-001..HC-010).

Un :class:`MandateSettings` agrupa **todos** los límites duros de una propuesta final; cada campo
``None`` significa «no configurado en este nivel» (nunca un valor implícito), salvo
``cardinality_policy`` cuyo valor efectivo es ``FIXED`` si ningún nivel lo define (decisión del
mandato de este desarrollo: la política más restrictiva es la de partida; el motor ya generaba
composiciones de tamaño fijo antes de este módulo).

Tres niveles de configuración, con la precedencia **global < perfil < cartera** (véase
:mod:`portfolio_engine.hard_constraints.resolver`): un nivel posterior solo puede *endurecer* un
límite del anterior; relajarlo exige una :class:`RelaxationAuthorization` explícita y trazable.

Unidades: pesos como fracción del NAV (``0.2`` = 20 %); volatilidad y retorno **anualizados** en
tanto por uno (``0.15`` = 15 % anual), las mismas de ``RiskModel`` (ARCHITECTURE §5.2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import (
    CardinalityPolicy,
    CostTreatment,
    VolatilityBandEnforcement,
)

#: Techo de seguridad de toda tolerancia de validación final (tolerancia numérica, nunca material).
#: Un valor mayor se rechaza al construir la configuración: la tolerancia no puede convertir en
#: aceptable una violación material (véase ``HARD_CONSTRAINTS_DESIGN.md`` §6).
TOLERANCE_CEILING = 1e-6


#: Campos de :class:`MandateSettings` con el sentido en el que se *relaja* un límite.
#: ``MAX``: límite superior (relajar = aumentar); ``MIN``: límite inferior (relajar = disminuir);
#: ``EXACT``: valor que no puede cambiarse sin autorización; ``FLAG_TRUE``: ``True`` es más
#: estricto;
#: ``POLICY``: ``FIXED`` es la política más estricta; ``FREE``: parámetro blando, sin sentido de
#: relajación.
FIELD_SENSE: Mapping[str, str] = MappingProxyType(
    {
        "target_size": "EXACT",
        "min_size": "MIN",
        "max_size": "MAX",
        "max_size_increase": "MAX",
        "max_size_decrease": "MAX",
        "max_added_assets": "MAX",
        "max_removed_assets": "MAX",
        "max_total_changed_assets": "MAX",
        "max_replacements": "MAX",
        "max_pure_additions": "MAX",
        "max_pure_removals": "MAX",
        "min_volatility": "MIN",
        "max_volatility": "MAX",
        "min_active_weight": "MIN",
        "max_active_weight": "MAX",
        "max_concentration_hhi": "MAX",
        "min_effective_number_of_positions": "MIN",
        "min_expected_return": "MIN",
        "preserve_original_expected_return": "FLAG_TRUE",
        "expected_return_treatment": "EXACT",
        "max_transaction_cost": "MAX",
        "position_weight_threshold": "MAX",
        "cardinality_policy": "POLICY",
        "diversification_penalty_weight": "FREE",
    }
)
#: Campos que solo pueden definirse en el nivel global (tolerancias y definiciones comunes).
GLOBAL_ONLY_FIELDS = frozenset(
    {
        "weight_tolerance",
        "budget_tolerance",
        "volatility_tolerance",
        "hhi_tolerance",
        "return_tolerance",
        "volatility_band_enforcement",
        "band_max_starts",
        "band_max_iterations",
        "band_convergence_tolerance",
    }
)


def _check_optional_float(value: object, name: str, *, positive: bool, upper: float | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"hard_constraints.{name} debe ser numérico.")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"hard_constraints.{name} debe ser finito.")
    if positive and number <= 0.0:
        raise ConfigError(f"hard_constraints.{name} debe ser > 0.")
    if not positive and number < 0.0:
        raise ConfigError(f"hard_constraints.{name} no puede ser negativo.")
    if upper is not None and number > upper:
        raise ConfigError(f"hard_constraints.{name} no puede superar {upper}.")


def _check_optional_int(value: object, name: str, *, minimum: int) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"hard_constraints.{name} debe ser entero.")
    if value < minimum:
        raise ConfigError(f"hard_constraints.{name} debe ser >= {minimum}.")


@dataclass(frozen=True, slots=True)
class MandateSettings:
    """Límites duros de una propuesta final. ``None`` = no configurado en este nivel.

    Cardinalidad (número de posiciones realmente mantenidas, ``w_i > position_weight_threshold``):
        ``cardinality_policy``, ``target_size`` (tamaño exacto), ``min_size`` / ``max_size``
        (intervalo absoluto) y ``max_size_increase`` / ``max_size_decrease`` (variación máxima
        respecto al tamaño original; obligatorios con ``INCREASE`` / ``DECREASE`` salvo que
        ``max_size`` / ``min_size`` acoten el intervalo).

    Componentes respecto a la cartera original (``a`` = incorporados, ``r`` = retirados):
        ``max_added_assets`` (``a``), ``max_removed_assets`` (``r``), ``max_total_changed_assets``
        (``a + r``), ``max_replacements`` (sustituciones uno a uno, ``min(a, r)``),
        ``max_pure_additions`` (altas independientes, ``a − min(a, r)``) y ``max_pure_removals``
        (bajas independientes, ``r − min(a, r)``).

    Volatilidad anualizada: ``min_volatility`` / ``max_volatility`` y su modo de aplicación.

    Concentración y pesos: ``min_active_weight`` / ``max_active_weight`` (por posición),
    ``max_concentration_hhi`` (``Σ w_i² <=``), ``min_effective_number_of_positions``
    (``1 / Σ w_i² >=``) y ``diversification_penalty_weight`` (objetivo secundario **blando**).

    Retorno y costes: ``min_expected_return`` (absoluto), ``preserve_original_expected_return``
    (``μᵀw >= μᵀw0``), ``expected_return_treatment`` (``GROSS`` o ``NET``) y
    ``max_transaction_cost`` (coste único de la transición, fracción del NAV).

    Definiciones y tolerancias (solo nivel global): ``position_weight_threshold`` es el único
    umbral con el que se cuenta una posición (``w_i > umbral``); ``*_tolerance`` son las
    tolerancias de la validación final (cada una ``<= TOLERANCE_CEILING``).

    Estrategia de la banda de volatilidad (solo nivel global; obligatorios con
    ``min_volatility``, que hace el problema no convexo): ``band_max_starts`` puntos de arranque,
    ``band_max_iterations`` iteraciones por arranque y ``band_convergence_tolerance`` (mejora
    mínima de retorno que cuenta como progreso).
    """

    cardinality_policy: CardinalityPolicy | None = None
    target_size: int | None = None
    min_size: int | None = None
    max_size: int | None = None
    max_size_increase: int | None = None
    max_size_decrease: int | None = None
    max_added_assets: int | None = None
    max_removed_assets: int | None = None
    max_total_changed_assets: int | None = None
    max_replacements: int | None = None
    max_pure_additions: int | None = None
    max_pure_removals: int | None = None
    min_volatility: float | None = None
    max_volatility: float | None = None
    volatility_band_enforcement: VolatilityBandEnforcement | None = None
    min_active_weight: float | None = None
    max_active_weight: float | None = None
    max_concentration_hhi: float | None = None
    min_effective_number_of_positions: float | None = None
    diversification_penalty_weight: float | None = None
    min_expected_return: float | None = None
    preserve_original_expected_return: bool | None = None
    expected_return_treatment: CostTreatment | None = None
    max_transaction_cost: float | None = None
    position_weight_threshold: float | None = None
    weight_tolerance: float | None = None
    budget_tolerance: float | None = None
    volatility_tolerance: float | None = None
    hhi_tolerance: float | None = None
    return_tolerance: float | None = None
    band_max_starts: int | None = None
    band_max_iterations: int | None = None
    band_convergence_tolerance: float | None = None

    def __post_init__(self) -> None:
        self._check_counts()
        self._check_risk_and_weights()
        self._check_tolerances()
        self._check_enums()

    def _check_counts(self) -> None:
        for name in ("target_size", "min_size", "max_size"):
            _check_optional_int(getattr(self, name), name, minimum=1)
        for name in (
            "max_size_increase",
            "max_size_decrease",
            "max_added_assets",
            "max_removed_assets",
            "max_total_changed_assets",
            "max_replacements",
            "max_pure_additions",
            "max_pure_removals",
        ):
            _check_optional_int(getattr(self, name), name, minimum=0)
        _check_optional_int(self.band_max_starts, "band_max_starts", minimum=1)
        _check_optional_int(self.band_max_iterations, "band_max_iterations", minimum=1)

    def _check_risk_and_weights(self) -> None:
        for name in ("min_volatility", "max_volatility"):
            _check_optional_float(getattr(self, name), name, positive=False, upper=None)
        if self.max_volatility is not None and self.max_volatility <= 0.0:
            raise ConfigError("hard_constraints.max_volatility debe ser > 0.")
        for name in ("min_active_weight", "max_active_weight"):
            _check_optional_float(getattr(self, name), name, positive=True, upper=1.0)
        _check_optional_float(
            self.max_concentration_hhi, "max_concentration_hhi", positive=True, upper=1.0
        )
        _check_optional_float(
            self.min_effective_number_of_positions,
            "min_effective_number_of_positions",
            positive=True,
            upper=None,
        )
        _check_optional_float(
            self.diversification_penalty_weight,
            "diversification_penalty_weight",
            positive=False,
            upper=None,
        )
        if self.min_expected_return is not None and not math.isfinite(self.min_expected_return):
            raise ConfigError("hard_constraints.min_expected_return debe ser finito.")
        _check_optional_float(
            self.max_transaction_cost, "max_transaction_cost", positive=False, upper=None
        )

    def _check_tolerances(self) -> None:
        _check_optional_float(
            self.position_weight_threshold,
            "position_weight_threshold",
            positive=False,
            upper=TOLERANCE_CEILING,
        )
        for name in (
            "weight_tolerance",
            "budget_tolerance",
            "volatility_tolerance",
            "hhi_tolerance",
            "return_tolerance",
        ):
            _check_optional_float(
                getattr(self, name), name, positive=False, upper=TOLERANCE_CEILING
            )
        _check_optional_float(
            self.band_convergence_tolerance,
            "band_convergence_tolerance",
            positive=True,
            upper=None,
        )

    def _check_enums(self) -> None:
        if self.cardinality_policy is not None and not isinstance(
            self.cardinality_policy, CardinalityPolicy
        ):
            raise ConfigError("hard_constraints.cardinality_policy debe ser un CardinalityPolicy.")
        if self.volatility_band_enforcement is not None and not isinstance(
            self.volatility_band_enforcement, VolatilityBandEnforcement
        ):
            raise ConfigError("hard_constraints.volatility_band_enforcement solo admite HARD.")
        if self.expected_return_treatment is not None and (
            self.expected_return_treatment not in (CostTreatment.GROSS, CostTreatment.NET)
        ):
            raise ConfigError("hard_constraints.expected_return_treatment debe ser GROSS o NET.")
        if self.preserve_original_expected_return is not None and not isinstance(
            self.preserve_original_expected_return, bool
        ):
            raise ConfigError("hard_constraints.preserve_original_expected_return debe ser bool.")

    def set_fields(self) -> dict[str, object]:
        """Campos configurados (no ``None``) de este nivel, por nombre."""
        values = {name: getattr(self, name) for name in self.__dataclass_fields__}
        return {name: value for name, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class RelaxationAuthorization:
    """Autorización explícita y trazable para que un nivel *relaje* un límite del nivel previo.

    Sin una autorización del campo concreto en el **mismo** nivel, relajar un límite obligatorio
    es un error de configuración. La autorización se conserva en los parámetros efectivos y en su
    hash: el relajamiento queda registrado, nunca es silencioso.
    """

    field: str
    authorized_by: str
    reason: str
    reference: str

    def __post_init__(self) -> None:
        if self.field not in FIELD_SENSE:
            raise ConfigError(f"relaxation_authorizations.field desconocido: {self.field!r}.")
        for name in ("authorized_by", "reason", "reference"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(
                    f"relaxation_authorizations.{name} debe ser un texto no vacío (trazabilidad)."
                )


@dataclass(frozen=True, slots=True)
class MandateLevel:
    """Nivel de override: un perfil de riesgo (``name`` = perfil) o una cartera (``name`` = ID).

    ``profile`` solo se admite en un nivel de cartera: el perfil que le corresponde.
    """

    name: str
    settings: MandateSettings
    relaxations: tuple[RelaxationAuthorization, ...] = ()
    profile: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ConfigError("hard_constraints: el nombre de un nivel no puede ser vacío.")
        if not isinstance(self.settings, MandateSettings):
            raise ConfigError("hard_constraints: settings debe ser un MandateSettings.")
        forbidden = sorted(GLOBAL_ONLY_FIELDS & set(self.settings.set_fields()))
        if forbidden:
            raise ConfigError(
                f"hard_constraints[{self.name!r}]: {forbidden} solo pueden definirse en el nivel "
                "global (tolerancias y definiciones comunes)."
            )
        fields = [authorization.field for authorization in self.relaxations]
        if len(set(fields)) != len(fields):
            raise ConfigError(f"hard_constraints[{self.name!r}]: autorizaciones duplicadas.")


@dataclass(frozen=True, slots=True)
class HardConstraintsConfig:
    """Árbol declarativo completo: global, perfiles de riesgo y carteras.

    Es la **única fuente de verdad** de las restricciones obligatorias (junto con los campos del
    motor que ya existían y que el resolvedor integra: ``candidates.max_new_assets``,
    ``candidates.max_swaps``, ``constraints.global_*_weight``, ``frontier.min_holding_weight``,
    ``PortfolioSpec.target_portfolio_size`` / ``volatility_limit`` / ``weight_bound_overrides``).
    """

    global_settings: MandateSettings
    profiles: tuple[MandateLevel, ...] = ()
    portfolios: tuple[MandateLevel, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.global_settings, MandateSettings):
            raise ConfigError("hard_constraints.global_settings debe ser un MandateSettings.")
        for kind, levels in (("profiles", self.profiles), ("portfolios", self.portfolios)):
            names = [level.name for level in levels]
            if len(set(names)) != len(names):
                raise ConfigError(f"hard_constraints.{kind}: nombres duplicados.")
        for level in self.profiles:
            if level.profile is not None:
                raise ConfigError("hard_constraints.profiles: un perfil no tiene perfil padre.")
        known = {level.name for level in self.profiles}
        for level in self.portfolios:
            if level.profile is not None and level.profile not in known:
                raise ConfigError(
                    f"hard_constraints.portfolios[{level.name!r}]: perfil desconocido "
                    f"{level.profile!r}."
                )

    def profile(self, name: str) -> MandateLevel | None:
        """Nivel del perfil ``name`` (``None`` si no existe)."""
        return next((level for level in self.profiles if level.name == name), None)

    def portfolio(self, portfolio_id: str) -> MandateLevel | None:
        """Nivel de la cartera ``portfolio_id`` (``None`` si no tiene overrides)."""
        return next((level for level in self.portfolios if level.name == portfolio_id), None)
