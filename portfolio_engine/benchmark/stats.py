"""Estadísticos de tiempos (MASTER_SPEC §71; BEN-002, subconjunto B2).

Reporta media, percentiles configurados (``BenchmarkConfig.percentiles``), máximo y el número de
muestras. No hay percentiles ni umbrales fijos en el código.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from portfolio_engine.config.benchmark_config import BenchmarkConfig
from portfolio_engine.exceptions import PortfolioEngineError


@dataclass(frozen=True, slots=True)
class TimingSummary:
    """Resumen de una serie de tiempos (segundos)."""

    count: int
    mean: float
    maximum: float
    percentiles: tuple[tuple[float, float], ...]

    def percentile(self, level: float) -> float:
        """Valor del percentil ``level`` (debe estar en la configuración del benchmark)."""
        for candidate, value in self.percentiles:
            if candidate == level:
                return value
        raise PortfolioEngineError(f"Percentil {level!r} no configurado.")


def summarize(samples: Sequence[float], config: BenchmarkConfig) -> TimingSummary:
    """Media, percentiles configurados y máximo de ``samples`` (no vacía)."""
    if not samples:
        raise PortfolioEngineError("No hay muestras que resumir.")
    values = np.asarray(samples, dtype=np.float64)
    levels = config.percentiles
    computed = np.percentile(values, levels)
    return TimingSummary(
        count=int(values.shape[0]),
        mean=float(values.mean()),
        maximum=float(values.max()),
        percentiles=tuple(
            (float(level), float(value)) for level, value in zip(levels, computed, strict=True)
        ),
    )
