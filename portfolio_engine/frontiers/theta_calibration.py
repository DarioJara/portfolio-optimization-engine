"""Calibración del rango de theta y mallas de parámetros (MASTER_SPEC §35; FRN-007, decisión A-16).

Con ``θ = 1/λ`` el problema ``min wᵀΣw − θμᵀw`` recorre la frontera: ``θ`` es la pendiente
``dσ²/dR`` de la curva (varianza, retorno) en el punto óptimo. ``AUTO`` toma como referencia la
pendiente media entre los extremos explícitos::

    θ_ref = (σ²_MR − σ²_MV) / (R_MR − R_MV)

y el rango ``[m_min·θ_ref, m_max·θ_ref]`` con multiplicadores de configuración (nunca constantes
en el código). ``EXPLICIT`` usa ``theta_min`` y ``theta_max`` de configuración. Si los extremos
coinciden en retorno o en varianza la frontera está degenerada y no hay malla que calibrar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.models.enums import GridScale, ThetaGridMode


@dataclass(frozen=True, slots=True)
class ThetaGrid:
    """Rango y espaciado de la malla de theta.

    Attributes:
        theta_min: theta mínimo de la malla.
        theta_max: theta máximo de la malla.
        scale: espaciado (lineal o logarítmico).
        reference: theta de referencia (pendiente media) en modo ``AUTO``; ``None`` si explícito.
    """

    theta_min: float
    theta_max: float
    scale: GridScale
    reference: float | None

    def values(self, count: int) -> npt.NDArray[np.float64]:
        """``count`` valores de theta ascendentes que incluyen ``theta_min`` y ``theta_max``."""
        return grid_values(self.theta_min, self.theta_max, count, self.scale)


def grid_values(low: float, high: float, count: int, scale: GridScale) -> npt.NDArray[np.float64]:
    """Malla ascendente de ``count`` valores entre ``low`` y ``high`` (ambos incluidos)."""
    if scale is GridScale.LOG:
        return np.geomspace(low, high, count, dtype=np.float64)
    return np.linspace(low, high, count, dtype=np.float64)


def midpoint(low: float, high: float, scale: GridScale) -> float:
    """Punto medio de ``[low, high]`` en el espaciado de la malla (media geométrica si es log)."""
    if scale is GridScale.LOG:
        return math.sqrt(low * high)
    return 0.5 * (low + high)


def calibrate_theta_grid(
    config: FrontierConfig,
    *,
    variance_min: float,
    return_min: float,
    variance_max: float,
    return_max: float,
    tolerance: float,
) -> ThetaGrid | None:
    """Rango de theta según ``config.theta_grid_mode``; ``None`` si la frontera es degenerada.

    ``tolerance`` es la diferencia mínima de retorno para considerar que existe un tramo de
    frontera (``dedup_return_tolerance``).
    """
    if config.theta_grid_mode is ThetaGridMode.EXPLICIT:
        if config.theta_min is None or config.theta_max is None:
            raise ValueError("theta_grid_mode = EXPLICIT exige theta_min y theta_max.")
        return ThetaGrid(config.theta_min, config.theta_max, config.theta_scale, None)
    span = return_max - return_min
    if span <= tolerance:
        return None
    reference = (variance_max - variance_min) / span
    if not math.isfinite(reference) or reference <= 0.0:
        return None
    return ThetaGrid(
        theta_min=config.theta_auto_min_multiplier * reference,
        theta_max=config.theta_auto_max_multiplier * reference,
        scale=config.theta_scale,
        reference=reference,
    )


def calibrate_theta_from_points(
    config: FrontierConfig,
    minimum_variance: tuple[float, float],
    maximum_return: tuple[float, float],
    tolerance: float,
) -> ThetaGrid | None:
    """Calibración a partir de los extremos ``(varianza, retorno)`` de MinVariance y MaxReturn."""
    return calibrate_theta_grid(
        config,
        variance_min=minimum_variance[0],
        return_min=minimum_variance[1],
        variance_max=maximum_return[0],
        return_max=maximum_return[1],
        tolerance=tolerance,
    )
