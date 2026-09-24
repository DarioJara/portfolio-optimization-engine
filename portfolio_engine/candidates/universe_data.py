"""Vistas numéricas del universo alineadas con el modelo de riesgo (MASTER_SPEC §59; CAN-012).

``UniverseSnapshot`` convierte una sola vez los metadatos del universo, los costes y el modelo de
riesgo en arrays alineados con el **índice global** (orden de ``mu_global``/``Sigma_global``) para
que el screening opere de forma vectorizada. ``mu`` y ``sigma`` son **referencias** al modelo de
riesgo (solo lectura): el snapshot nunca copia la covarianza global ``N×N``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import CandidateError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.risk_model import RiskModel
from portfolio_engine.models.universe_index import AssetIndex
from portfolio_engine.utils.numerics import readonly_float_array, readonly_int_array


def _flag_arrays(values: list[bool | None]) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """``(conocido, valor)`` de una bandera opcional (el valor es ``False`` si es desconocida)."""
    known = np.array([value is not None for value in values], dtype=np.bool_)
    truth = np.array([bool(value) for value in values], dtype=np.bool_)
    return known, truth


@dataclass(frozen=True, eq=False, slots=True)
class UniverseSnapshot:
    """Arrays por activo alineados con el índice global del modelo de riesgo.

    Los valores ausentes son ``NaN`` (numéricos) o banderas ``*_known = False``; el screening y el
    filtro de elegibilidad los tratan con políticas explícitas, nunca con un reemplazo implícito.

    Attributes:
        index: índice global (``AssetID`` → posición en ``mu``/``sigma``).
        mu: expected returns globales (referencia de solo lectura, sin copia).
        sigma: covarianza global ``N×N`` (referencia de solo lectura, sin copia).
        eligible_flag: ``EligibleFlag`` del universo.
        liquidity_known: ``LiquidityFlag`` informado.
        liquidity_ok: valor de ``LiquidityFlag`` (``False`` si es desconocido).
        restricted_known: ``RestrictedAssetFlag`` informado.
        restricted: valor de ``RestrictedAssetFlag`` (``False`` si es desconocido).
        sector_codes: código entero del sector (``-1`` si es desconocido).
        sector_count: número de sectores distintos.
        adv: volumen medio diario (``NaN`` si falta).
        buy_cost: coste unitario de compra (``NaN`` si falta).
        sell_cost: coste unitario de venta (``NaN`` si falta).
        universe_only_ids: activos del universo sin datos en el modelo de riesgo.
    """

    index: AssetIndex
    mu: npt.NDArray[np.float64]
    sigma: npt.NDArray[np.float64]
    eligible_flag: npt.NDArray[np.bool_]
    liquidity_known: npt.NDArray[np.bool_]
    liquidity_ok: npt.NDArray[np.bool_]
    restricted_known: npt.NDArray[np.bool_]
    restricted: npt.NDArray[np.bool_]
    sector_codes: npt.NDArray[np.int64]
    sector_count: int
    adv: npt.NDArray[np.float64]
    buy_cost: npt.NDArray[np.float64]
    sell_cost: npt.NDArray[np.float64]
    universe_only_ids: tuple[str, ...]

    @classmethod
    def build(
        cls, risk_model: RiskModel, universe: Universe, costs: AssetCostVector | None
    ) -> UniverseSnapshot:
        """Snapshot de ``universe`` (y ``costs``) alineado con ``risk_model``."""
        index = AssetIndex(risk_model.asset_ids)
        missing = [asset_id for asset_id in index.asset_ids if asset_id not in universe]
        if missing:
            raise CandidateError(
                f"Activos del modelo de riesgo sin metadatos de universo: {missing}"
            )
        assets = [universe.get(asset_id) for asset_id in index.asset_ids]
        liquidity_known, liquidity_ok = _flag_arrays([asset.liquidity_flag for asset in assets])
        restricted_known, restricted = _flag_arrays([asset.restricted for asset in assets])
        sectors = sorted({asset.sector for asset in assets if asset.sector is not None})
        code = {sector: position for position, sector in enumerate(sectors)}
        buy = np.full(len(index), np.nan, dtype=np.float64)
        sell = np.full(len(index), np.nan, dtype=np.float64)
        if costs is not None:
            for asset_id in costs.asset_ids:
                if asset_id in index:
                    position = index.index_of(asset_id)
                    buy[position], sell[position] = costs.costs_of(asset_id)
        return cls(
            index=index,
            mu=risk_model.mu,
            sigma=risk_model.sigma,
            eligible_flag=np.array([asset.eligible for asset in assets], dtype=np.bool_),
            liquidity_known=liquidity_known,
            liquidity_ok=liquidity_ok,
            restricted_known=restricted_known,
            restricted=restricted,
            sector_codes=readonly_int_array(
                [-1 if asset.sector is None else code[asset.sector] for asset in assets]
            ),
            sector_count=len(sectors),
            adv=readonly_float_array(
                [np.nan if asset.adv is None else asset.adv for asset in assets]
            ),
            buy_cost=readonly_float_array(buy),
            sell_cost=readonly_float_array(sell),
            universe_only_ids=tuple(
                asset_id for asset_id in universe.asset_ids if asset_id not in index
            ),
        )

    @property
    def size(self) -> int:
        """Número de activos del universo global (con datos de mu y Sigma)."""
        return len(self.index)
