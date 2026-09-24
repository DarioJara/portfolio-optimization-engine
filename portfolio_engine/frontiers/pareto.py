"""Eficiencia de Pareto de los puntos de una frontera (MASTER_SPEC §40).

Requisitos: FRN-014, FRN-015, FRN-016.

Un punto está dominado si otro válido tiene menor o igual volatilidad y mayor o igual retorno,
estrictamente mejor en al menos una de las dos (con tolerancia de configuración).
``X = Volatility``; ``Y = ExpectedReturnGross`` para ``IsGrossEfficient`` e
``Y = ExpectedReturnNet`` para ``IsNetEfficient``. Los puntos dominados **no se eliminan**: solo
se marcan. Los puntos inválidos se almacenan pero no participan en el cálculo (FRN-023). Un
duplicado hereda la eficiencia de su original.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np
import numpy.typing as npt

from portfolio_engine.models.frontier import FrontierPoint


def pareto_mask(
    volatility: npt.NDArray[np.float64],
    value: npt.NDArray[np.float64],
    valid: npt.NDArray[np.bool_],
    tolerance: float,
) -> npt.NDArray[np.bool_]:
    """``True`` para los puntos válidos no dominados en (volatilidad ↓, ``value`` ↑)."""
    vol_i, vol_j = volatility[:, np.newaxis], volatility[np.newaxis, :]
    val_i, val_j = value[:, np.newaxis], value[np.newaxis, :]
    no_worse = (vol_j <= vol_i + tolerance) & (val_j >= val_i - tolerance)
    strictly_better = (vol_j < vol_i - tolerance) | (val_j > val_i + tolerance)
    dominated = (no_worse & strictly_better & valid[np.newaxis, :]).any(axis=1)
    return np.asarray(valid & ~dominated, dtype=np.bool_)


def apply_efficiency(
    points: Sequence[FrontierPoint], tolerance: float
) -> tuple[FrontierPoint, ...]:
    """Devuelve ``points`` con ``is_gross_efficient`` e ``is_net_efficient`` calculados."""
    if not points:
        return ()
    eligible = np.array(
        [p.is_valid_solution and p.metrics is not None and not p.is_duplicate for p in points]
    )
    volatility = np.array([p.metrics.volatility if p.metrics else np.nan for p in points])
    gross = np.array([p.metrics.expected_return_gross if p.metrics else np.nan for p in points])
    gross_flags = pareto_mask(volatility, gross, eligible, tolerance)
    net_available = all(
        p.metrics is not None and p.metrics.expected_return_net is not None
        for p in points
        if p.is_valid_solution
    )
    net_flags: npt.NDArray[np.bool_] | None = None
    if net_available:
        net = np.array(
            [
                p.metrics.expected_return_net
                if p.metrics and p.metrics.expected_return_net is not None
                else np.nan
                for p in points
            ]
        )
        net_flags = pareto_mask(volatility, net, eligible, tolerance)
    by_id = {p.point_id: index for index, p in enumerate(points)}
    result: list[FrontierPoint] = []
    for index, point in enumerate(points):
        source = by_id.get(point.duplicate_of, index) if point.duplicate_of else index
        result.append(
            replace(
                point,
                is_gross_efficient=bool(gross_flags[source]),
                is_net_efficient=None if net_flags is None else bool(net_flags[source]),
            )
        )
    return tuple(result)
