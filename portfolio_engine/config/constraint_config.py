"""Configuración base de restricciones (MASTER_SPEC §12; parte del Bloque 1).

Solo incluye lo necesario para validar datos y estado actual en el Bloque 1. Las restricciones
de optimización (grupos, turnover, volatilidad, etc.) se añaden en los bloques 2–4.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_finite
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy


@dataclass(frozen=True, slots=True)
class ConstraintConfig:
    """Parámetros base de restricciones.

    Attributes:
        long_only: prohíbe pesos negativos.
        global_min_weight: límite inferior global por activo (``None`` = no configurado).
        global_max_weight: límite superior global por activo (``None`` = no configurado).
        restricted_existing_position_policy: política para activos restringidos ya en cartera
            (E-09). ``None`` solo es válido si ninguna cartera mantiene activos restringidos;
            la validación de carteras lo exige en caso contrario.
    """

    long_only: bool
    global_min_weight: float | None
    global_max_weight: float | None
    restricted_existing_position_policy: RestrictedExistingPositionPolicy | None

    def __post_init__(self) -> None:
        if not isinstance(self.long_only, bool):
            raise ConfigError("long_only debe ser booleano.")
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
