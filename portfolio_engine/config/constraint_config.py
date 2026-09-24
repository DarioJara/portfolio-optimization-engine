"""Configuración de restricciones (MASTER_SPEC §12; base en el Bloque 1, extensión en el 2).

El Bloque 2 añade las restricciones de grupo (sector, país, clase de activo, divisa) y el turnover
máximo global. Las restricciones cónicas, de cardinalidad y de exposición pertenecen a bloques
posteriores.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_finite, require_non_negative
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import GroupDimension, RestrictedExistingPositionPolicy


@dataclass(frozen=True, slots=True)
class GroupLimit:
    """Límites de peso agregado de un grupo (``SectorMin/Max``, ``CountryMin/Max``, …).

    Attributes:
        dimension: atributo del universo por el que se agrupa.
        group: valor del atributo (p. ej. el nombre del sector).
        min_weight: peso agregado mínimo (``None`` = sin mínimo).
        max_weight: peso agregado máximo (``None`` = sin máximo).
    """

    dimension: GroupDimension
    group: str
    min_weight: float | None
    max_weight: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, GroupDimension):
            raise ConfigError("group_limits.dimension debe ser un GroupDimension.")
        if not isinstance(self.group, str) or not self.group:
            raise ConfigError("group_limits.group debe ser un texto no vacío.")
        if self.min_weight is None and self.max_weight is None:
            raise ConfigError(f"El grupo {self.group!r} no define ningún límite.")
        for name in ("min_weight", "max_weight"):
            value = getattr(self, name)
            if value is not None:
                require_non_negative(value, f"group_limits.{name}")
        if (
            self.min_weight is not None
            and self.max_weight is not None
            and self.min_weight > self.max_weight
        ):
            raise ConfigError(f"El grupo {self.group!r} tiene min_weight > max_weight.")


@dataclass(frozen=True, slots=True)
class FxRate:
    """Tipo de cambio explícito para expresar ``ADV`` en la divisa de ``NAV`` (A-11).

    ``from_currency`` es la divisa de ``ADV`` y ``to_currency`` la de ``NAV``; ``rate`` son unidades
    de ``NAVCurrency`` por unidad de ``ADVCurrency`` (``ADV_en_NAV = ADV · rate``; p. ej. 0,90 EUR
    por USD: 100 USD = 90 EUR). Nunca se infiere ni se invierte otro par: si falta el par exacto,
    el cálculo se rechaza.
    """

    from_currency: str
    to_currency: str
    rate: float

    def __post_init__(self) -> None:
        for name in ("from_currency", "to_currency"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ConfigError(f"fx_rates.{name} debe ser un texto no vacío.")
        if self.from_currency == self.to_currency:
            raise ConfigError("fx_rates: las divisas de origen y destino deben ser distintas.")
        require_finite(self.rate, "fx_rates.rate")
        if not self.rate > 0:
            raise ConfigError("fx_rates.rate debe ser > 0.")


@dataclass(frozen=True, slots=True)
class LiquidityConfig:
    """``LiquidityConstraint`` ADV/NAV (A-11, ``MASTER_SPEC`` §12).

    ``LiquidityCapacity_i = max_adv_participation · ADV_i · liquidation_days / NAV``. Es un límite
    de tamaño de posición, **no** una garantía de que una venta pueda ejecutarse ni una restricción
    de volumen negociable por operación.

    Attributes:
        enabled: aplica la restricción. Con ``False`` no se aplica y sus parámetros son opcionales.
        max_adv_participation: fracción máxima del ADV, ``0 < p <= 1`` (obligatorio si ``enabled``).
        liquidation_days: días de liquidación, ``>= 1`` (obligatorio si ``enabled``).
        fx_rates: tipos de cambio explícitos ``ADV → divisa de NAV`` (vacío = sin conversión).
    """

    enabled: bool
    max_adv_participation: float | None
    liquidation_days: float | None
    fx_rates: tuple[FxRate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError("liquidity.enabled debe ser booleano.")
        if self.enabled and (self.max_adv_participation is None or self.liquidation_days is None):
            raise ConfigError(
                "liquidity.enabled = true exige max_adv_participation y liquidation_days "
                "(no se desactiva la restricción en silencio)."
            )
        if self.max_adv_participation is not None:
            require_finite(self.max_adv_participation, "liquidity.max_adv_participation")
            if not 0 < self.max_adv_participation <= 1:
                raise ConfigError("liquidity.max_adv_participation debe cumplir 0 < p <= 1.")
        if self.liquidation_days is not None:
            require_finite(self.liquidation_days, "liquidity.liquidation_days")
            if self.liquidation_days < 1:
                raise ConfigError("liquidity.liquidation_days debe ser >= 1.")
        if not isinstance(self.fx_rates, tuple) or not all(
            isinstance(rate, FxRate) for rate in self.fx_rates
        ):
            raise ConfigError("liquidity.fx_rates debe ser una tupla de FxRate.")
        pairs = [(rate.from_currency, rate.to_currency) for rate in self.fx_rates]
        if len(set(pairs)) != len(pairs):
            raise ConfigError("liquidity.fx_rates contiene pares duplicados.")

    def rate_for(self, from_currency: str, to_currency: str) -> float | None:
        """Tipo de cambio explícito del par exacto, o ``None`` si no está configurado."""
        for rate in self.fx_rates:
            if rate.from_currency == from_currency and rate.to_currency == to_currency:
                return rate.rate
        return None


@dataclass(frozen=True, slots=True)
class ConstraintConfig:
    """Parámetros de restricciones.

    Attributes:
        long_only: prohíbe pesos negativos.
        global_min_weight: límite inferior global por activo (``None`` = no configurado).
        global_max_weight: límite superior global por activo (``None`` = no configurado).
        restricted_existing_position_policy: política para activos restringidos ya en cartera
            (E-09). ``None`` solo es válido si ninguna cartera mantiene activos restringidos;
            la validación de carteras lo exige en caso contrario.
        global_max_turnover: turnover máximo global (``None`` = no configurado); el valor de
            ``PortfolioSpec.max_turnover`` prevalece sobre este.
        group_limits: límites de peso agregado por grupo (sector, país, clase de activo, divisa).
        liquidity: restricción ADV/NAV (A-11); sin valores productivos por defecto.
    """

    long_only: bool
    global_min_weight: float | None
    global_max_weight: float | None
    restricted_existing_position_policy: RestrictedExistingPositionPolicy | None
    global_max_turnover: float | None
    group_limits: tuple[GroupLimit, ...]
    liquidity: LiquidityConfig

    def __post_init__(self) -> None:
        if not isinstance(self.liquidity, LiquidityConfig):
            raise ConfigError("constraints.liquidity debe ser un LiquidityConfig.")
        if not isinstance(self.long_only, bool):
            raise ConfigError("long_only debe ser booleano.")
        self._check_weight_limits()
        if self.global_max_turnover is not None:
            require_non_negative(self.global_max_turnover, "global_max_turnover")
        self._check_group_limits()

    def _check_weight_limits(self) -> None:
        for name in ("global_min_weight", "global_max_weight"):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, name)
                if self.long_only and value < 0:
                    raise ConfigError(f"{name} no puede ser negativo con long_only.")
        if (
            self.global_min_weight is not None
            and self.global_max_weight is not None
            and self.global_min_weight > self.global_max_weight
        ):
            raise ConfigError("global_min_weight no puede superar global_max_weight.")

    def _check_group_limits(self) -> None:
        if not isinstance(self.group_limits, tuple):
            raise ConfigError("group_limits debe ser una tupla.")
        seen: set[tuple[GroupDimension, str]] = set()
        for limit in self.group_limits:
            if not isinstance(limit, GroupLimit):
                raise ConfigError("group_limits solo admite GroupLimit.")
            key = (limit.dimension, limit.group)
            if key in seen:
                raise ConfigError(f"Límite de grupo duplicado: {limit.dimension}/{limit.group}.")
            seen.add(key)
