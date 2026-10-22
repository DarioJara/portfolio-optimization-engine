"""Cargas de referencia de la regresión de rendimiento (B5.5; BEN-005, TST-005).

Define, en un único sitio usado por ``baseline.py`` (que crea el baseline) y por
``tests/performance/test_performance_regression.py`` (que lo compara), las celdas pequeñas y
deterministas que se miden: ``(clase, nº de carteras)`` ejecutadas con el ejecutor secuencial
(sin pool: aísla el cómputo del arranque de procesos).

Cada celda produce **muestras de tiempo** (dependen del host y son bimodales en esta máquina) y
**contadores de trabajo** deterministas: llamadas reales a ``solve()`` (estructurales: no dependen
del host) e iteraciones de solver de las fronteras. Un cambio del contador es un cambio de
**trabajo**, no de velocidad (``portfolio_engine.benchmark.regression``).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
import synthetic_portfolios  # noqa: E402

from portfolio_engine.config.scaling_config import (  # noqa: E402
    ClassShare,
    ScalingBenchmarkConfig,
    WorkloadMix,
    load_scaling_benchmark_config,
)
from portfolio_engine.parallel.executor import SequentialExecutor  # noqa: E402
from tests.fixtures.parallel import count_solver_calls  # noqa: E402

SCALING_CONFIG_PATH = ROOT / "config" / "default_benchmark.toml"
BASELINE_DIR = ROOT / "benchmarks" / "results" / "baselines"
WORK_BASELINE = BASELINE_DIR / "perf_reference_work.json"
#: Semilla de la carga de referencia (parte de la definición del baseline).
SEED = 7
#: Celdas de referencia ``(clase, nº de carteras)``.
REFERENCE_CELLS: tuple[tuple[str, int], ...] = (
    ("W0-GROSS-RISK", 6),
    ("W0-NET-TARGET", 6),
    ("W1-GLOBAL-NET", 2),
    ("W3-MIN-CVAR", 6),
    ("W4-ROBUST", 6),
    ("W4-MAX-SHARPE", 6),
    ("W4-VOL-TARGET", 6),
)


@dataclass(frozen=True, slots=True)
class CellMeasurement:
    """Medición de una celda de referencia."""

    label: str
    portfolios: int
    samples: tuple[float, ...]
    solver_calls: int
    frontier_iterations: int


def scaling_config() -> ScalingBenchmarkConfig:
    return load_scaling_benchmark_config(SCALING_CONFIG_PATH)


def measure_cell(label: str, portfolios: int, repetitions: int) -> CellMeasurement:
    """Mide ``repetitions`` ejecuciones secuenciales de la celda y cuenta su trabajo."""
    mix = WorkloadMix(f"PERF:{label}", (ClassShare(label, 1.0),))
    batch = synthetic_portfolios.generate(scaling_config(), mix, portfolios, SEED)
    executor = SequentialExecutor(batch.config, batch.snapshot)
    executor.run(batch.requests)  # calentamiento descartado (importaciones, cachés de módulo)
    samples = []
    run = None
    for _ in range(repetitions):
        started = time.perf_counter()
        run = executor.run(batch.requests)
        samples.append(time.perf_counter() - started)
    assert run is not None
    with count_solver_calls() as counter:
        executor.run(batch.requests)
    return CellMeasurement(
        label,
        portfolios,
        tuple(samples),
        counter.count,
        _common.frontier_iterations(run.results),
    )
