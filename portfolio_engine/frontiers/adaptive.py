"""Frontera adaptativa (MASTER_SPEC §42; FRN-019).

El retorno de la curva es el del tratamiento (``scoring_return``): bruto en ``GROSS``; neto
(``μᵀw − TC(w)``, incluida la liquidación de activos retirados) en ``NET``; y neto de los pesos
``GROSS`` en ``POST_COST_GROSS``, cuya frontera publicada es (volatilidad, retorno tras costes).

Parte de una malla inicial de ``InitialFrontierPoints < FrontierPoints`` puntos, resuelve, mide
huecos y curvatura sobre la curva (volatilidad, retorno) normalizada e inserta nuevos puntos en el
intervalo de mayor puntuación (bisección en el espacio del parámetro: media aritmética o
geométrica según el espaciado). Repite hasta ``FrontierPoints`` o hasta que ningún intervalo supere
``adaptive_gap_tolerance``.

Puntuación del intervalo entre los puntos activos ``i`` e ``i+1``::

    d = hypot(Δvol / rango_vol, Δret / rango_ret)
    κ = ángulo de giro en el extremo / π   (0 = recta, 1 = inversión)
    score = d · (1 + max(κ_i, κ_{i+1}))

Un punto insertado que resulta inválido o duplicado de un vecino agota su intervalo (no se vuelve a
dividir), de modo que el bucle termina siempre y nunca supera el máximo. Los puntos insertados se
marcan (``is_adaptive_insertion``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.exceptions import FrontierError
from portfolio_engine.frontiers.dedup import is_equivalent
from portfolio_engine.frontiers.theta_calibration import midpoint
from portfolio_engine.models.enums import CostTreatment, GridScale
from portfolio_engine.models.frontier import FrontierPoint, PointMetrics

#: Retorno de un punto (según el tratamiento de costes) con el que se puntúa la curva.
ReturnMetric = Callable[[PointMetrics], float]


def _gross_return(metrics: PointMetrics) -> float:
    return metrics.expected_return_gross


def _net_return(metrics: PointMetrics) -> float:
    if metrics.expected_return_net is None:
        raise FrontierError(
            "La frontera adaptativa NET/POST_COST_GROSS exige retorno neto "
            f"({metrics.unavailable_reason})."
        )
    return metrics.expected_return_net


def scoring_return(treatment: CostTreatment) -> ReturnMetric:
    """Retorno con el que la frontera adaptativa puntúa huecos y curvatura de ``treatment``."""
    return _gross_return if treatment is CostTreatment.GROSS else _net_return


@dataclass(frozen=True, eq=False, slots=True)
class ParametrizedPoint:
    """Un punto de frontera con el valor de parámetro (theta o retorno objetivo) que lo generó."""

    parameter: float
    point: FrontierPoint


class AdaptiveFrontier:
    """Refina una frontera insertando puntos donde hay mayor hueco o curvatura."""

    def __init__(
        self, config: FrontierConfig, scale: GridScale, score_return: ReturnMetric
    ) -> None:
        if not config.adaptive or config.adaptive_gap_tolerance is None:
            raise ValueError("AdaptiveFrontier exige adaptive = true en FrontierConfig.")
        self._config = config
        self._tolerance = config.adaptive_gap_tolerance
        self._scale = scale
        self._return = score_return

    def refine(
        self,
        seeds: Sequence[ParametrizedPoint],
        solve: Callable[[float], FrontierPoint],
    ) -> tuple[ParametrizedPoint, ...]:
        """Devuelve los puntos iniciales más las inserciones, ordenados por parámetro."""
        items = sorted(seeds, key=lambda item: item.parameter)
        exhausted: set[tuple[float, float]] = set()
        while len(items) < self._config.frontier_points:
            interval = self._best_interval(items, exhausted)
            if interval is None:
                break
            low, high = interval
            parameter = midpoint(low.parameter, high.parameter, self._scale)
            if not low.parameter < parameter < high.parameter:
                exhausted.add((low.parameter, high.parameter))
                continue
            point = solve(parameter)
            items.append(ParametrizedPoint(parameter, point))
            items.sort(key=lambda item: item.parameter)
            neighbours = (low.point, high.point)
            useless = not point.is_valid_solution or any(
                is_equivalent(point, other, self._config) for other in neighbours
            )
            if useless:
                exhausted.add((low.parameter, high.parameter))
        return tuple(items)

    def _best_interval(
        self, items: Sequence[ParametrizedPoint], exhausted: set[tuple[float, float]]
    ) -> tuple[ParametrizedPoint, ParametrizedPoint] | None:
        active = [
            item
            for item in items
            if item.point.is_valid_solution and item.point.metrics is not None
        ]
        if len(active) < 2:
            return None
        curve = np.array(
            [
                [item.point.metrics.volatility, self._return(item.point.metrics)]
                for item in active
                if item.point.metrics is not None
            ]
        )
        scores = _interval_scores(curve)
        best: tuple[float, int] | None = None
        for index, score in enumerate(scores.tolist()):
            key = (active[index].parameter, active[index + 1].parameter)
            if key in exhausted or score < self._tolerance:
                continue
            if best is None or score > best[0]:
                best = (score, index)
        if best is None:
            return None
        return active[best[1]], active[best[1] + 1]


def _interval_scores(curve: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Puntuación (hueco × curvatura) de cada intervalo entre puntos consecutivos de ``curve``."""
    span = curve.max(axis=0) - curve.min(axis=0)
    scale = np.where(span > 0.0, span, 1.0)
    unit = curve / scale
    steps = np.diff(unit, axis=0)
    gaps = np.hypot(steps[:, 0], steps[:, 1])
    turning = np.zeros(curve.shape[0])
    for index in range(1, curve.shape[0] - 1):
        turning[index] = _turning_angle(steps[index - 1], steps[index]) / math.pi
    curvature = np.maximum(turning[:-1], turning[1:])
    return np.asarray(gaps * (1.0 + curvature), dtype=np.float64)


def _turning_angle(before: npt.NDArray[np.float64], after: npt.NDArray[np.float64]) -> float:
    """Ángulo (radianes, en ``[0, π]``) entre dos tramos consecutivos; 0 si alguno es nulo."""
    norm = float(np.linalg.norm(before) * np.linalg.norm(after))
    if norm == 0.0:
        return 0.0
    cosine = float(np.clip(before @ after / norm, -1.0, 1.0))
    return math.acos(cosine)
