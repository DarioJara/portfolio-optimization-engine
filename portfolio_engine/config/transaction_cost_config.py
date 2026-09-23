"""Configuración de datos de costes de transacción (MASTER_SPEC §6, §23; decisión A-04).

El horizonte de comparación de costes NO reside aquí: su única fuente de verdad es
``EngineConfig.optimization_horizon_years`` (enmienda E-03).
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_non_negative, require_positive
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import CostInputUnit, CostSource


@dataclass(frozen=True, slots=True)
class TransactionCostConfig:
    """Resolución y validación de costes unitarios por activo.

    Attributes:
        input_unit: unidad de los campos de coste del universo (``DECIMAL`` o ``BPS``).
        source_precedence: orden de fuentes a probar por activo (sin repeticiones).
        spread_commission: comisión (decimal) sumada a ``BidAskSpread/2`` en esa fuente.
        max_unit_cost: coste unitario máximo plausible (decimal); valores superiores se
            rechazan como error de datos o de unidades.
    """

    input_unit: CostInputUnit
    source_precedence: tuple[CostSource, ...]
    spread_commission: float
    max_unit_cost: float

    def __post_init__(self) -> None:
        if not isinstance(self.source_precedence, tuple) or not self.source_precedence:
            raise ConfigError("source_precedence debe ser una tupla no vacía.")
        if len(set(self.source_precedence)) != len(self.source_precedence):
            raise ConfigError("source_precedence no admite fuentes repetidas.")
        require_non_negative(self.spread_commission, "spread_commission")
        require_positive(self.max_unit_cost, "max_unit_cost")
        if self.spread_commission > self.max_unit_cost:
            raise ConfigError("spread_commission no puede superar max_unit_cost.")
