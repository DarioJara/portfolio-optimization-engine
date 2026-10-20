"""Aritmética de escalado y proyección de capacidad (BEN-004, BEN-007, GOV-012).

Funciones **puras** sobre mediciones ya hechas: speedup, eficiencia, fracción serie de
Karp–Flatt, modelo de coste de una mezcla ``T_seq = N · Σ s_i · c_i`` y proyección de duración,
recursos y coste de una carga mayor.

Una proyección es **aritmética sobre una medición concreta**, con su incertidumbre; nunca
sustituye a la ejecución (``BLOCK_5_BENCHMARK_PLAN.md`` §1.2). Por eso :func:`project_capacity`
exige un rango de entradas (cota baja, central, alta), devuelve un rango de salidas y nunca recibe
ni inventa precios: el coste se expresa en horas-núcleo y, solo si el llamador aporta un precio,
en dinero.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from portfolio_engine.exceptions import PortfolioEngineError

#: Segundos por hora (conversión de unidades).
SECONDS_PER_HOUR = 3600.0


def _positive(value: float, name: str) -> None:
    if not (math.isfinite(value) and value > 0.0):
        raise PortfolioEngineError(f"{name} debe ser un número finito > 0 (recibido {value!r}).")


def speedup(sequential_seconds: float, parallel_seconds: float) -> float:
    """``S(p) = T_seq / T_p``."""
    _positive(sequential_seconds, "T_seq")
    _positive(parallel_seconds, "T_p")
    return sequential_seconds / parallel_seconds


def efficiency(speedup_value: float, workers: int) -> float:
    """``E(p) = S(p) / p``."""
    if workers < 1:
        raise PortfolioEngineError("workers debe ser >= 1.")
    return speedup_value / workers


def karp_flatt(speedup_value: float, workers: int) -> float | None:
    """Fracción serie efectiva ``e = (1/S − 1/p) / (1 − 1/p)``; ``None`` con un solo worker."""
    if workers < 1:
        raise PortfolioEngineError("workers debe ser >= 1.")
    _positive(speedup_value, "speedup")
    if workers == 1:
        return None
    return (1.0 / speedup_value - 1.0 / workers) / (1.0 - 1.0 / workers)


def percentile_summary(samples: Sequence[float], levels: Sequence[float]) -> dict[str, float]:
    """Mínimo, mediana, media, máximo y percentiles ``levels`` de ``samples``."""
    if not samples:
        raise PortfolioEngineError("No hay muestras que resumir.")
    values = np.asarray(samples, dtype=np.float64)
    summary = {
        "min": float(values.min()),
        "median": float(np.median(values)),
        "mean": float(values.mean()),
        "max": float(values.max()),
    }
    for level in levels:
        summary[f"p{level:g}"] = float(np.percentile(values, level))
    return summary


# ------------------------------------------------------------------- modelo de coste de un mix


def predict_sequential_seconds(
    portfolios: int, shares: Mapping[str, float], unit_cost: Mapping[str, float]
) -> float:
    """``T_seq(mix) = N · Σ_i s_i · c_i`` (coste unitario ``c_i`` medido por clase)."""
    if portfolios < 1:
        raise PortfolioEngineError("portfolios debe ser >= 1.")
    missing = sorted(set(shares) - set(unit_cost))
    if missing:
        raise PortfolioEngineError(f"Falta el coste unitario de las clases {missing}.")
    return float(
        portfolios * sum(fraction * unit_cost[label] for label, fraction in shares.items())
    )


def class_contributions(
    shares: Mapping[str, float], unit_cost: Mapping[str, float]
) -> dict[str, float]:
    """Fracción del tiempo total que aporta cada clase en el mix (suma 1)."""
    weighted = {label: fraction * unit_cost[label] for label, fraction in shares.items()}
    total = sum(weighted.values())
    if total <= 0.0:
        raise PortfolioEngineError("El coste total del mix debe ser > 0.")
    return {label: value / total for label, value in weighted.items()}


# --------------------------------------------------------------------------------- proyección


@dataclass(frozen=True, slots=True)
class ProjectionInputs:
    """Entradas MEDIDAS de una proyección (cada una con su rango observado).

    Attributes:
        unit_seconds: coste secuencial por cartera ``(bajo, central, alto)`` (p. ej. mín., mediana,
            p95 de la medición).
        efficiency: eficiencia paralela observada ``(baja, central, alta)`` con ``workers``.
        startup_seconds: arranque del pool medido (una vez por ejecución).
        worker_rss_bytes: pico de memoria por worker medido.
        coordinator_rss_bytes: pico de memoria del coordinador medido.
        measured_portfolios: nº de carteras de la medición de la que proceden (para la cautela).
    """

    unit_seconds: tuple[float, float, float]
    efficiency: tuple[float, float, float]
    startup_seconds: float
    worker_rss_bytes: float
    coordinator_rss_bytes: float
    measured_portfolios: int


@dataclass(frozen=True, slots=True)
class CapacityProjection:
    """Proyección con rango: ``wall_seconds = (óptimo, central, pesimista)``."""

    portfolios: int
    workers: int
    wall_seconds: tuple[float, float, float]
    core_hours: tuple[float, float, float]
    peak_memory_bytes: float
    extrapolation_factor: float
    money: tuple[float, float, float] | None
    caveat: str


def project_capacity(
    inputs: ProjectionInputs,
    portfolios: int,
    workers: int,
    *,
    price_per_core_hour: float | None = None,
) -> CapacityProjection:
    """Duración, horas-núcleo y memoria de ``portfolios`` carteras con ``workers`` workers.

    ``wall = startup + N · c / (workers · eficiencia)``; el rango combina la cota baja de coste y
    la alta de eficiencia (óptimo) y al revés (pesimista). Las horas-núcleo son
    ``workers × wall / 3600``. La memoria es ``coordinador + workers × RSS_worker`` (sin asumir
    reparto de páginas compartidas). El factor de extrapolación es ``portfolios / medidas``: cuanto
    mayor, menos fiable la proyección.
    """
    if portfolios < 1 or workers < 1:
        raise PortfolioEngineError("portfolios y workers deben ser >= 1.")
    low_c, mid_c, high_c = inputs.unit_seconds
    low_e, mid_e, high_e = inputs.efficiency
    for value, name in ((low_c, "coste bajo"), (mid_c, "coste central"), (high_c, "coste alto")):
        _positive(value, name)
    for value, name in (
        (low_e, "eficiencia baja"),
        (mid_e, "eficiencia central"),
        (high_e, "eficiencia alta"),
    ):
        _positive(value, name)
    if not (low_c <= mid_c <= high_c and low_e <= mid_e <= high_e):
        raise PortfolioEngineError("Los rangos deben estar ordenados (bajo <= central <= alto).")

    def wall(cost: float, eff: float) -> float:
        return inputs.startup_seconds + portfolios * cost / (workers * min(eff, 1.0))

    walls = (wall(low_c, high_e), wall(mid_c, mid_e), wall(high_c, low_e))
    cores = tuple(workers * w / SECONDS_PER_HOUR for w in walls)
    money = (
        None
        if price_per_core_hour is None
        else (
            cores[0] * price_per_core_hour,
            cores[1] * price_per_core_hour,
            cores[2] * price_per_core_hour,
        )
    )
    factor = portfolios / inputs.measured_portfolios
    caveat = (
        f"Aritmética sobre una medición de {inputs.measured_portfolios} carteras "
        f"(factor de extrapolación ×{factor:.1f}); supone eficiencia y coste unitario constantes "
        "con el tamaño de la carga, lo que NO se ha verificado a esta escala. No sustituye a la "
        "ejecución."
    )
    return CapacityProjection(
        portfolios=portfolios,
        workers=workers,
        wall_seconds=walls,
        core_hours=(cores[0], cores[1], cores[2]),
        peak_memory_bytes=inputs.coordinator_rss_bytes + workers * inputs.worker_rss_bytes,
        extrapolation_factor=factor,
        money=money,
        caveat=caveat,
    )
