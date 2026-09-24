"""Deduplicación de puntos de frontera por tolerancias (MASTER_SPEC §43; FRN-020).

Dos carteras son prácticamente idénticas si **a la vez** difieren menos que la tolerancia en pesos
(norma infinito), en retorno bruto y en volatilidad. Los duplicados no se eliminan del
almacenamiento: se marcan (``is_duplicate``, ``duplicate_of``) y se excluyen del cálculo de Pareto.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np

from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.models.frontier import FrontierPoint


def is_equivalent(first: FrontierPoint, second: FrontierPoint, config: FrontierConfig) -> bool:
    """``True`` si ``first`` y ``second`` son equivalentes en pesos, retorno y volatilidad."""
    if first.weights is None or second.weights is None:
        return False
    if first.metrics is None or second.metrics is None:
        return False
    return bool(
        float(np.max(np.abs(first.weights - second.weights))) <= config.dedup_weight_tolerance
        and abs(first.metrics.expected_return_gross - second.metrics.expected_return_gross)
        <= config.dedup_return_tolerance
        and abs(first.metrics.volatility - second.metrics.volatility)
        <= config.dedup_volatility_tolerance
    )


def deduplicate(
    points: Sequence[FrontierPoint], config: FrontierConfig
) -> tuple[FrontierPoint, ...]:
    """Marca como duplicado cada punto válido equivalente a uno anterior (en el orden dado)."""
    kept: list[FrontierPoint] = []
    result: list[FrontierPoint] = []
    for point in points:
        original = (
            next((k for k in kept if is_equivalent(point, k, config)), None)
            if point.is_valid_solution
            else None
        )
        if original is None:
            result.append(replace(point, is_duplicate=False, duplicate_of=None))
            if point.is_valid_solution:
                kept.append(point)
        else:
            result.append(replace(point, is_duplicate=True, duplicate_of=original.point_id))
    return tuple(result)
