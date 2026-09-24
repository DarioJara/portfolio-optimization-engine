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
    """

    long_only: bool
    global_min_weight: float | None
    global_max_weight: float | None
    restricted_existing_position_policy: RestrictedExistingPositionPolicy | None
    global_max_turnover: float | None
    group_limits: tuple[GroupLimit, ...]

    def __post_init__(self) -> None:
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
