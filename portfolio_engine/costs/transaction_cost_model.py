"""Costes de transacción sobre la unión ``current ∪ nueva composición`` (MASTER_SPEC §23, §25).

::

    Δw = w_new − w_current                       (sobre la UNIÓN de activos)
    TC_one_off(w) = Σ_i [ BuyCost_i·max(Δw_i, 0) + SellCost_i·max(−Δw_i, 0) ]
    TC(w)         = TC_one_off(w) / H            (unidades de retorno anualizado, E-03)

Un activo mantenido que no pertenece a la composición nueva tiene ``w_new = 0``: se contabiliza
su venta completa (§23). El coste nunca se calcula solo sobre los activos de la composición.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.costs.turnover import turnover as union_turnover
from portfolio_engine.exceptions import TransactionCostInputError
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.portfolio import CurrentPortfolioState
from portfolio_engine.utils.numerics import readonly_float_array, readonly_int_array


@dataclass(frozen=True, eq=False, slots=True)
class UnionAlignment:
    """Alineación de la composición nueva con la cartera actual sobre su unión (TC-001).

    Attributes:
        asset_ids: AssetID de la unión, ordenados.
        current_weights: peso actual de cada activo de la unión (0 si no se mantiene).
        composition_positions: posición en la unión de cada activo de la composición nueva, en el
            orden de esta.
        has_current_portfolio: ``False`` si la cartera actual está vacía (turnover y coste no
            disponibles, MASTER_SPEC §24).
    """

    asset_ids: tuple[str, ...]
    current_weights: npt.NDArray[np.float64]
    composition_positions: npt.NDArray[np.int64]
    has_current_portfolio: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "current_weights", readonly_float_array(self.current_weights))
        object.__setattr__(
            self, "composition_positions", readonly_int_array(self.composition_positions)
        )

    @property
    def size(self) -> int:
        """Número de activos de la unión."""
        return len(self.asset_ids)

    def expand(self, weights: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """Lleva pesos de la composición (``K×n`` o ``n``) a la unión (``K×M`` o ``M``); 0 fuera."""
        array = np.asarray(weights, dtype=np.float64)
        expanded = np.zeros((*array.shape[:-1], self.size), dtype=np.float64)
        expanded[..., self.composition_positions] = array
        return expanded

    def current_on_composition(self) -> npt.NDArray[np.float64]:
        """Pesos actuales de los activos de la composición (0 si no se mantienen)."""
        return readonly_float_array(self.current_weights[self.composition_positions])

    def exited_asset_ids(self) -> tuple[str, ...]:
        """Activos mantenidos que no están en la composición nueva (se liquidan por completo)."""
        in_composition = set(self.composition_positions.tolist())
        return tuple(
            asset_id
            for position, asset_id in enumerate(self.asset_ids)
            if position not in in_composition and self.current_weights[position] != 0.0
        )


def align_union(
    state: CurrentPortfolioState, composition_asset_ids: Sequence[str]
) -> UnionAlignment:
    """Unión ordenada de la cartera actual y la composición nueva (TC-001)."""
    if len(set(composition_asset_ids)) != len(composition_asset_ids):
        raise TransactionCostInputError("La composición contiene AssetID repetidos.")
    union = tuple(sorted(set(state.asset_ids) | set(composition_asset_ids)))
    position = {asset_id: index for index, asset_id in enumerate(union)}
    current = np.zeros(len(union), dtype=np.float64)
    for asset_id, weight in zip(state.asset_ids, state.weights.tolist(), strict=True):
        current[position[asset_id]] = weight
    composition_positions = np.array(
        [position[asset_id] for asset_id in composition_asset_ids], dtype=np.int64
    )
    return UnionAlignment(union, current, composition_positions, state.has_current_portfolio)


def to_return_units(one_off_cost: npt.ArrayLike, horizon_years: float) -> npt.NDArray[np.float64]:
    """``TransactionCost = TransactionCostOneOff / H`` (TC-009, enmienda E-03)."""
    return np.asarray(one_off_cost, dtype=np.float64) / horizon_years


class TransactionCostModel:
    """Coste de transacción asimétrico y turnover sobre la unión current ∪ composición."""

    __slots__ = ("_alignment", "_buy", "_horizon", "_sell")

    def __init__(
        self, alignment: UnionAlignment, costs: AssetCostVector, horizon_years: float
    ) -> None:
        if not alignment.has_current_portfolio:
            raise TransactionCostInputError(
                "Sin cartera actual el coste de transacción no está disponible (MASTER_SPEC §24)."
            )
        if horizon_years <= 0:
            raise TransactionCostInputError("El horizonte debe ser positivo.")
        missing = sorted(set(alignment.asset_ids) - set(costs.asset_ids))
        if missing:
            raise TransactionCostInputError(f"Activos sin coste de transacción: {missing}")
        positions = [costs.asset_ids.index(asset_id) for asset_id in alignment.asset_ids]
        self._alignment = alignment
        self._buy = readonly_float_array(costs.buy_costs[positions])
        self._sell = readonly_float_array(costs.sell_costs[positions])
        self._horizon = float(horizon_years)

    @property
    def alignment(self) -> UnionAlignment:
        """Alineación sobre la unión."""
        return self._alignment

    @property
    def horizon_years(self) -> float:
        """Horizonte ``H`` (años) usado para pasar a unidades de retorno."""
        return self._horizon

    @property
    def buy_costs(self) -> npt.NDArray[np.float64]:
        """Costes de compra por activo de la unión."""
        return self._buy

    @property
    def sell_costs(self) -> npt.NDArray[np.float64]:
        """Costes de venta por activo de la unión."""
        return self._sell

    def asset_costs_one_off(self, weights: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """Coste único por activo de la unión (``K×M``); suma por fila = ``TransactionCostOneOff``.

        ``weights`` son pesos de la composición (``K×n`` o ``n``). Suma de columnas = TC-012.
        """
        delta = self._alignment.expand(weights) - self._alignment.current_weights
        return np.asarray(
            self._buy * np.maximum(delta, 0.0) + self._sell * np.maximum(-delta, 0.0),
            dtype=np.float64,
        )

    def cost_one_off(self, weights: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """``TransactionCostOneOff`` (fracción del NAV) de cada fila de pesos."""
        return np.asarray(self.asset_costs_one_off(weights).sum(axis=-1), dtype=np.float64)

    def cost(self, weights: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """``TransactionCost`` en unidades de retorno anualizado (``one_off / H``)."""
        return to_return_units(self.cost_one_off(weights), self._horizon)

    def exit_cost_one_off(self) -> float:
        """Coste único constante de liquidar por completo los activos fuera de la composición.

        ``Σ_{j retirado} [BuyCost_j·max(−w0_j, 0) + SellCost_j·max(w0_j, 0)]`` (``w_new = 0``):
        no depende de los pesos optimizados (``K_E``, MASTER_SPEC §23).
        """
        kept = np.zeros(self._alignment.size, dtype=bool)
        kept[self._alignment.composition_positions] = True
        current = self._alignment.current_weights[~kept]
        delta = -current
        return float(
            self._buy[~kept] @ np.maximum(delta, 0.0) + self._sell[~kept] @ np.maximum(-delta, 0.0)
        )

    def turnover(self, weights: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """``Turnover = 0.5·Σ|Δw|`` sobre la unión (incluye las liquidaciones completas)."""
        return union_turnover(self._alignment.expand(weights), self._alignment.current_weights)
