"""Malla de retorno objetivo (MASTER_SPEC §36, §38; FRN-008, FRN-009, FRN-011).

Resuelve ``min wᵀΣw`` s.a. retorno ``>= R``: bruto ``μᵀw >= R`` o neto ``μᵀw − TC(w) >= R``
(la fila de retorno de ``A`` lleva los costes linealizados; la restricción sigue siendo lineal).
``P``, ``A`` y ``q`` son constantes: solo cambia ``lower`` de la fila de retorno.

El rango es ``[R_MV, R_max]`` (neto: ``[R_net(MV), R_net_max]``); los extremos son las carteras
explícitas MinimumVariance y MaximumReturn y los puntos interiores se reparten linealmente.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from portfolio_engine.frontiers.session import FrontierSession
from portfolio_engine.models.enums import StrategyID
from portfolio_engine.models.frontier import FrontierPoint


def target_range(
    minimum_variance_return: float, maximum_return: float
) -> tuple[float, float] | None:
    """Rango ``[R_MV, R_max]`` del grid, o ``None`` si es degenerado (``R_max <= R_MV``)."""
    if maximum_return <= minimum_variance_return:
        return None
    return minimum_variance_return, maximum_return


def interior_targets(low: float, high: float, count: int) -> npt.NDArray[np.float64]:
    """``count`` retornos objetivo equiespaciados en el interior abierto de ``(low, high)``."""
    if count <= 0:
        return np.empty(0, dtype=np.float64)
    step = (high - low) / (count + 1)
    return np.asarray(low + step * np.arange(1, count + 1), dtype=np.float64)


class TargetReturnGrid:
    """Recorre una malla de retornos objetivo sobre un workspace reutilizable."""

    def __init__(self, session: FrontierSession) -> None:
        self._session = session

    def solve_target(self, target: float, *, adaptive: bool = False) -> FrontierPoint:
        """Punto de frontera para un retorno objetivo concreto."""
        return self._session.solve_target(
            target, strategy=StrategyID.FRONTIER_POINT, adaptive=adaptive
        )

    def solve_grid(self, targets: Sequence[float] | npt.NDArray[np.float64]) -> list[FrontierPoint]:
        """Un punto por cada objetivo de ``targets``, en el orden dado."""
        return [self.solve_target(float(target)) for target in targets]
