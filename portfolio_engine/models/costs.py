"""Modelo de datos de costes de transacción unitarios (MASTER_SPEC §6, §23).

Solo contiene los costes unitarios por activo ya resueltos y validados. El cálculo de
``TransactionCost(w)``, turnover y rentabilidad neta pertenece al Bloque 2.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import TransactionCostInputError
from portfolio_engine.models.enums import CostSource
from portfolio_engine.utils.numerics import readonly_float_array

#: Conversión de unidades: 1 unidad decimal = 10.000 puntos básicos (constante de unidades).
BPS_PER_UNIT = 10_000.0


@dataclass(frozen=True, eq=False, slots=True)
class AssetCostVector:
    """Costes unitarios de compra y venta por activo, en fracción decimal del nocional.

    ``sources`` indica qué fuente de coste se usó para cada activo (auditoría, decisión A-04).
    """

    asset_ids: tuple[str, ...]
    buy_costs: npt.NDArray[np.float64]
    sell_costs: npt.NDArray[np.float64]
    sources: tuple[CostSource, ...]

    def __post_init__(self) -> None:
        if list(self.asset_ids) != sorted(set(self.asset_ids)):
            raise TransactionCostInputError("AssetCostVector exige AssetID únicos y ordenados.")
        buy = readonly_float_array(self.buy_costs)
        sell = readonly_float_array(self.sell_costs)
        expected_shape = (len(self.asset_ids),)
        if buy.shape != expected_shape or sell.shape != expected_shape:
            raise TransactionCostInputError("Dimensiones incoherentes en AssetCostVector.")
        if len(self.sources) != len(self.asset_ids):
            raise TransactionCostInputError("Debe haber una fuente de coste por activo.")
        if not (np.all(np.isfinite(buy)) and np.all(np.isfinite(sell))):
            raise TransactionCostInputError("Los costes unitarios deben ser finitos.")
        if np.any(buy < 0.0) or np.any(sell < 0.0):
            raise TransactionCostInputError("Los costes unitarios no pueden ser negativos.")
        object.__setattr__(self, "buy_costs", buy)
        object.__setattr__(self, "sell_costs", sell)

    def costs_of(self, asset_id: str) -> tuple[float, float]:
        """``(BuyCost, SellCost)`` decimales de ``asset_id``."""
        position = self.asset_ids.index(asset_id)
        return float(self.buy_costs[position]), float(self.sell_costs[position])
