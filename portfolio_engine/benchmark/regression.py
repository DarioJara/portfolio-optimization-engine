"""Detección de deterioros de rendimiento frente a un baseline (BEN-005, TST-005).

El umbral no es un porcentaje fijo: se deriva de la **variabilidad medida** del baseline,
``umbral = k × max(MAD, suelo_relativo × mediana)``, con ``k`` y el suelo en la configuración
(``ScalingBenchmarkConfig``). La MAD es la desviación absoluta mediana de las repeticiones del
baseline; el suelo evita un umbral nulo cuando hay pocas repeticiones casi idénticas.

Un cambio de tiempo **no se interpreta como un cambio de velocidad** si el contador determinista de
trabajo (llamadas al solver, iteraciones, evaluaciones) cambió: entonces se señala
``WORK_CHANGED`` (cambió el trabajo, no la velocidad). Los baselines son por
``(clase, escala, huella del host)``: comparar tiempos de otra máquina carece de sentido y devuelve
``HOST_MISMATCH`` (no una verdad ni un fallo).
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from portfolio_engine.exceptions import PortfolioEngineError

BASELINE_SCHEMA_VERSION = 1


class RegressionVerdict(StrEnum):
    """Resultado de comparar una medición con su baseline."""

    WITHIN_NOISE = "WITHIN_NOISE"
    SLOWER = "SLOWER"
    FASTER = "FASTER"
    WORK_CHANGED = "WORK_CHANGED"
    HOST_MISMATCH = "HOST_MISMATCH"
    NO_BASELINE = "NO_BASELINE"


@dataclass(frozen=True, slots=True)
class BaselineCell:
    """Medición de referencia de una celda ``(clase, escala)`` en un host.

    Attributes:
        samples: tiempos de pared (s) de las repeticiones medidas.
        work_counter: contador determinista de trabajo (``None`` si no se registró).
        host: huella del host que produjo las muestras.
    """

    samples: tuple[float, ...]
    work_counter: int | None
    host: str

    def __post_init__(self) -> None:
        if not self.samples:
            raise PortfolioEngineError("Un baseline necesita al menos una muestra.")
        if any(not (value > 0.0) for value in self.samples):
            raise PortfolioEngineError("Las muestras de un baseline deben ser tiempos > 0.")


@dataclass(frozen=True, slots=True)
class RegressionComparison:
    """Veredicto y las cifras que lo sustentan."""

    verdict: RegressionVerdict
    baseline_median: float | None
    current_median: float | None
    threshold: float | None
    difference: float | None
    detail: str


def _median(values: Sequence[float]) -> float:
    return float(statistics.median(values))


def _minimum(values: Sequence[float]) -> float:
    return float(min(values))


def _summary_function(statistic: str) -> Callable[[Sequence[float]], float]:
    if statistic == "median":
        return _median
    if statistic == "min":
        return _minimum
    raise PortfolioEngineError(f"statistic debe ser 'median' o 'min' (recibido {statistic!r}).")


def mad(samples: Sequence[float]) -> float:
    """Desviación absoluta mediana ``median(|x - median(x)|)``."""
    if not samples:
        raise PortfolioEngineError("MAD de una serie vacía.")
    centre = statistics.median(samples)
    return float(statistics.median(abs(value - centre) for value in samples))


def regression_threshold(
    baseline_samples: Sequence[float], k: float, relative_floor: float
) -> float:
    """``k × max(MAD, suelo_relativo × mediana)`` de las muestras del baseline."""
    if k <= 0 or relative_floor < 0:
        raise PortfolioEngineError("k debe ser > 0 y el suelo relativo >= 0.")
    centre = statistics.median(baseline_samples)
    return float(k * max(mad(baseline_samples), relative_floor * centre))


def compare_to_baseline(
    current_samples: Sequence[float],
    baseline: BaselineCell | None,
    *,
    host: str,
    k: float,
    relative_floor: float,
    current_work: int | None = None,
    statistic: str = "median",
) -> RegressionComparison:
    """Compara ``current_samples`` con el baseline usando el umbral por MAD.

    ``statistic`` elige el resumen comparado: ``"median"`` (por defecto) o ``"min"``. El mínimo es
    robusto a las fases lentas de máquinas con tiempos bimodales (un deterioro real sube el mínimo;
    una fase lenta pasajera, no). El umbral siempre se deriva de la MAD del baseline.

    El orden de las comprobaciones es deliberado: sin baseline o con host distinto no se emite
    juicio de velocidad; si el contador de trabajo cambió, tampoco (cambió el trabajo).
    """
    if not current_samples:
        raise PortfolioEngineError("No hay muestras actuales que comparar.")
    if baseline is None:
        return RegressionComparison(
            RegressionVerdict.NO_BASELINE, None, None, None, None, "no hay baseline para la celda"
        )
    if baseline.host != host:
        return RegressionComparison(
            RegressionVerdict.HOST_MISMATCH,
            None,
            None,
            None,
            None,
            f"baseline de otro host ({baseline.host!r} != {host!r}): tiempos no comparables",
        )
    if (
        baseline.work_counter is not None
        and current_work is not None
        and baseline.work_counter != current_work
    ):
        return RegressionComparison(
            RegressionVerdict.WORK_CHANGED,
            None,
            None,
            None,
            None,
            f"contador de trabajo {baseline.work_counter} -> {current_work}: cambió el trabajo",
        )
    summary = _summary_function(statistic)
    base_median = float(summary(baseline.samples))
    current_median = float(summary(current_samples))
    threshold = regression_threshold(baseline.samples, k, relative_floor)
    difference = current_median - base_median
    if difference > threshold:
        verdict = RegressionVerdict.SLOWER
    elif difference < -threshold:
        verdict = RegressionVerdict.FASTER
    else:
        verdict = RegressionVerdict.WITHIN_NOISE
    return RegressionComparison(
        verdict,
        base_median,
        current_median,
        threshold,
        difference,
        f"Δmediana = {difference:+.4f} s frente a un umbral de ±{threshold:.4f} s",
    )


# ---------------------------------------------------------------------------------- persistencia


def cell_key(workload_class: str, portfolios: int, mode: str) -> str:
    """Clave estable de una celda del baseline."""
    return f"{workload_class}|{portfolios}|{mode}"


def save_baseline(
    path: Path,
    cells: Mapping[str, BaselineCell],
    metadata: Mapping[str, Any],
) -> None:
    """Escribe un baseline (JSON versionado; sin ``pickle``)."""
    document = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "metadata": dict(metadata),
        "cells": {
            key: {
                "samples": list(cell.samples),
                "work_counter": cell.work_counter,
                "host": cell.host,
            }
            for key, cell in sorted(cells.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def load_baseline(path: Path) -> tuple[dict[str, BaselineCell], dict[str, Any]]:
    """Lee un baseline escrito por :func:`save_baseline` (valida versión y forma)."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortfolioEngineError(f"No se puede leer el baseline {path}: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise PortfolioEngineError(f"Versión de baseline no soportada en {path}.")
    cells: dict[str, BaselineCell] = {}
    for key, raw in document.get("cells", {}).items():
        cells[key] = BaselineCell(
            samples=tuple(float(value) for value in raw["samples"]),
            work_counter=None if raw["work_counter"] is None else int(raw["work_counter"]),
            host=str(raw["host"]),
        )
    return cells, dict(document.get("metadata", {}))
