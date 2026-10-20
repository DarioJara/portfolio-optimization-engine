"""Benchmark LOCAL y PEQUEÑO del ejecutor paralelo (Bloque 5.2; BEN-001/002/004, BEN-006).

Mide, sobre carteras sintéticas deterministas (universo pequeño, mezcla de clases de coste fijada
por ``--mix``), el ejecutor secuencial de referencia frente al paralelo con distinto número de
workers y tamaño de lote. Cada ejecución paralela se **compara con la secuencial bajo T1** antes de
aceptar su medición: un resultado distinto invalida el benchmark.

Es una medición descriptiva de una máquina local (no Arsys), con pocas carteras: NO es rendimiento
de producción, NO se extrapola y la mezcla por defecto es un supuesto de ingeniería (no la
distribución real de AAA-A). Los tiempos de esta máquina son bimodales (véase la memoria del
proyecto): se informa mínimo y mediana de las repeticiones y contadores deterministas.

No usa datos reales ni SQL Server. Cargas de 1.000 o más carteras requieren aprobación específica
(D-12): el script se niega a ejecutarlas.

Uso::

    .venv/Scripts/python benchmarks/scripts/parallel_scaling.py --workers 1 2 4 --repetitions 3
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import pickle
import platform
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.config import config_hash  # noqa: E402
from portfolio_engine.models.frontier import (  # noqa: E402
    CompositionFrontierResult,
    GlobalFrontierResult,
)
from portfolio_engine.parallel.executor import (  # noqa: E402
    ParallelExecutor,
    RunResult,
    SequentialExecutor,
)
from portfolio_engine.parallel.shared_data import worker_bundle  # noqa: E402
from portfolio_engine.parallel.task import (  # noqa: E402
    ExecutionContext,
    ExecutionStatus,
    PortfolioRequest,
)
from portfolio_engine.parallel.threading_control import worker_thread_environment  # noqa: E402
from portfolio_engine.parallel.worker import initialize_worker, worker_diagnostics  # noqa: E402
from tests.fixtures.candidates import random_problem  # noqa: E402
from tests.fixtures.parallel import (  # noqa: E402
    class_workloads,
    compare_results,
    parallel_config,
    requests_for,
    snapshot_of,
)
from tests.fixtures.problems import base_config  # noqa: E402

#: Límite duro (D-12): este script no ejecuta cargas masivas.
MAX_PORTFOLIOS = 999
#: Mezcla por defecto: SUPUESTO DE INGENIERÍA (no datos reales). Etiqueta -> nº de carteras.
DEFAULT_MIX = {
    "W0-GROSS-RISK": 6,
    "W0-NET-TARGET": 6,
    "W1-GLOBAL-NET": 2,
    "W3-MIN-CVAR": 4,
    "W4-ROBUST": 2,
    "W4-MAX-SHARPE": 2,
    "W4-VOL-TARGET": 2,
}


def _git_commit() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _parse_mix(items: list[str] | None) -> dict[str, int]:
    if not items:
        return dict(DEFAULT_MIX)
    mix: dict[str, int] = {}
    for item in items:
        label, _, count = item.partition("=")
        mix[label] = int(count)
    return mix


def _build_requests(
    mix: dict[str, int], assets: int, seed: int
) -> tuple[Any, list[PortfolioRequest], Any]:
    config = base_config()
    problem = random_problem(assets, [0, 1, 2], seed, config)
    snapshot = snapshot_of(problem, return_periods=300, seed=seed)
    workloads = class_workloads()
    requests: list[PortfolioRequest] = []
    for label, count in mix.items():
        universe, workload = workloads[label]
        if universe != "p8":
            raise SystemExit(f"{label}: solo se admiten workloads del universo p8 en este script.")
        requests.extend(
            requests_for(problem, workload, count, seed=seed + len(label), prefix=f"{label}-")
        )
    return config, requests, snapshot


def _frontier_iterations(result: Any) -> int:
    """Contador determinista de trabajo: iteraciones de solver de las fronteras de un resultado."""
    total = 0
    for outcome in result.operations:
        value = outcome.result
        if isinstance(value, CompositionFrontierResult):
            total += value.diagnostics.total_iterations
        elif isinstance(value, GlobalFrontierResult):
            total += sum(r.diagnostics.total_iterations for r in value.composition_results)
    return total


def _percentiles(samples: list[float], levels: tuple[float, ...]) -> dict[str, float]:
    values = np.asarray(samples, dtype=np.float64)
    return {str(level): float(np.percentile(values, level)) for level in levels}


def _summary(
    run: RunResult, wall: float, workers: int, levels: tuple[float, ...]
) -> dict[str, Any]:
    elapsed = [r.elapsed_seconds for r in run.results]
    busy: dict[int | None, float] = {}
    for result in run.results:
        busy[result.worker_pid] = busy.get(result.worker_pid, 0.0) + result.elapsed_seconds
    compute = sum(elapsed)
    return {
        "wall_seconds": wall,
        "portfolios": len(run.results),
        "portfolios_per_second": len(run.results) / wall,
        "task_latency_seconds": {
            "p": _percentiles(elapsed, levels),
            "max": max(elapsed),
            "mean": statistics.fmean(elapsed),
        },
        "sum_task_compute_seconds": compute,
        # Ocupación = tiempo de cómputo de las tareas / (workers × tiempo de pared). Estimación.
        "compute_occupancy": compute / (workers * wall),
        # Camino crítico = el worker más cargado; el resto del tiempo de pared es arranque,
        # IPC y planificación (estimación; no se mide por separado en este bloque).
        "max_worker_busy_seconds": max(busy.values()),
        "overhead_estimate_seconds": wall - max(busy.values()),
        "distinct_worker_pids": len({p for p in busy if p is not None}),
        "statuses": {
            status.value: sum(1 for r in run.results if r.execution_status is status)
            for status in ExecutionStatus
        },
    }


def _startup_seconds(config: Any, snapshot: Any, workers: int, repetitions: int) -> list[float]:
    """Tiempo de crear un pool ``spawn`` con ``workers`` procesos listos (initializer incluido)."""
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        with (
            worker_thread_environment(1),
            worker_bundle(ExecutionContext.create(config, snapshot)) as bundle,
            ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=initialize_worker,
                initargs=(bundle, 1),
            ) as pool,
        ):
            for future in [pool.submit(worker_diagnostics) for _ in range(workers * 4)]:
                future.result()
        samples.append(time.perf_counter() - started)
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, nargs="+", required=True)
    parser.add_argument("--batch-sizes", nargs="+", default=["1", "AUTO"])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--assets", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--mix", nargs="*", help="etiqueta=nº, p. ej. W0-GROSS-RISK=6")
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    args = parser.parse_args()
    mix = _parse_mix(args.mix)
    total = sum(mix.values())
    if total > MAX_PORTFOLIOS:
        raise SystemExit("Cargas de 1.000 o más carteras requieren aprobación específica (D-12).")
    config, requests, snapshot = _build_requests(mix, args.assets, args.seed)
    levels = config.benchmark.percentiles

    # 1) Referencia secuencial (mínimo y mediana de las repeticiones).
    sequential_walls: list[float] = []
    reference: RunResult | None = None
    for _ in range(args.repetitions):
        started = time.perf_counter()
        reference = SequentialExecutor(config, snapshot).run(requests)
        sequential_walls.append(time.perf_counter() - started)
    assert reference is not None
    seq_min, seq_median = min(sequential_walls), statistics.median(sequential_walls)
    work_counter = sum(_frontier_iterations(r) for r in reference.results)
    sequential = {
        "wall_seconds_samples": sequential_walls,
        "wall_seconds_min": seq_min,
        "wall_seconds_median": seq_median,
        **_summary(reference, seq_min, 1, levels),
    }
    print(f"secuencial: {total} carteras, min={seq_min:.2f} s mediana={seq_median:.2f} s")

    # 2) Ejecuciones paralelas, cada una verificada contra la referencia.
    runs: list[dict[str, Any]] = []
    for workers in args.workers:
        for batch_label in args.batch_sizes:
            batch = None if batch_label.upper() == "AUTO" else int(batch_label)
            pconfig = parallel_config(workers=workers, batch_size=batch)
            walls: list[float] = []
            last: RunResult | None = None
            differences = 0
            for _ in range(args.repetitions):
                started = time.perf_counter()
                last = ParallelExecutor(config, snapshot, pconfig).run(requests)
                walls.append(time.perf_counter() - started)
                for got, expected in zip(last.results, reference.results, strict=True):
                    differences += len(compare_results(expected, got).differences)
            assert last is not None
            wmin, wmedian = min(walls), statistics.median(walls)
            entry = {
                "workers": workers,
                "batch_size": batch_label,
                "effective_batch_size": last.manifest.batch_size,
                "batches": last.batches,
                "wall_seconds_samples": walls,
                "wall_seconds_min": wmin,
                "wall_seconds_median": wmedian,
                "speedup_vs_sequential_min": seq_min / wmin,
                "speedup_vs_sequential_median": seq_median / wmedian,
                "efficiency_min": seq_min / wmin / workers,
                "t1_differences_vs_sequential": differences,
                "valid_measurement": differences == 0,
                **_summary(last, wmin, workers, levels),
            }
            runs.append(entry)
            print(
                f"workers={workers} lote={batch_label:>4s} (efectivo {last.manifest.batch_size}) "
                f"min={wmin:6.2f} s mediana={wmedian:6.2f} s speedup(min)={seq_min / wmin:4.2f} "
                f"ocupación={entry['compute_occupancy']:.2f} diferencias_T1={differences}"
            )

    startup = {
        str(w): _startup_seconds(config, snapshot, w, max(2, args.repetitions - 1))
        for w in args.workers
    }
    payload = {
        "pickle_bytes": {
            "snapshot": len(pickle.dumps(snapshot, protocol=5)),
            "request_mean": statistics.fmean(len(pickle.dumps(r, protocol=5)) for r in requests),
            "result_mean": statistics.fmean(
                len(pickle.dumps(r, protocol=5)) for r in reference.results
            ),
        },
        "pool_startup_seconds_by_workers": startup,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    document = {
        "metadata": {
            "benchmark": "parallel_scaling",
            "evidence_for": ["BEN-001", "BEN-002", "BEN-004 (parcial)", "BEN-006", "PAR-008"],
            "execution_timestamp_utc": stamp,
            "git_commit": _git_commit(),
            "engine_config_hash": config_hash(config),
            "snapshot_key": reference.manifest.snapshot_key,
            "random_seed": args.seed,
            "universe_assets": args.assets,
            "mix_is_an_engineering_assumption": True,
            "mix": mix,
            "portfolios": total,
            "repetitions": args.repetitions,
            "start_method": "spawn",
            "blas_threads_per_worker": 1,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus_informational": os.cpu_count(),
            "versions": dict(reference.manifest.library_versions),
            "work_counter_frontier_solver_iterations": work_counter,
            "note": (
                "Medición local y pequeña (no es Arsys). Tiempos bimodales de esta máquina: "
                "se informan mínimo y mediana. No son rendimiento de producción ni se extrapolan. "
                "Una ejecución con diferencias T1 frente a la secuencial NO es una medición válida."
            ),
        },
        "sequential": sequential,
        "parallel": runs,
        "common": payload,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"parallel_scaling_{total}portfolios_{stamp}.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"resultado: {path}")
    if any(not entry["valid_measurement"] for entry in runs):
        raise SystemExit("Hay ejecuciones con diferencias T1: medición NO válida.")


if __name__ == "__main__":
    main()
