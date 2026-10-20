"""Benchmark LOCAL y PEQUEÑO de datos compartidos (E4) y caché de resultados (E8) del Bloque 5.3.

Parte 1 (E4): para cada tamaño de universo, modo de datos (``BUNDLE_FILE``, ``FILE_MMAP``,
``SHARED_MEMORY``), método de arranque y número de workers mide el coste de publicar el snapshot,
el tamaño de la referencia que viaja por el pipe de arranque, el tiempo hasta que el pool está
listo, el tiempo de adjunción dentro del worker y la memoria de cada worker (RSS y USS; PSS en
Linux, vía ``psutil``). Una ejecución real con 8 carteras W0 se compara con la referencia
secuencial (T1) y se comprueba que no quedan recursos residuales.

Parte 2 (E8): carteras W0 con una operación repetida ``k`` veces, con la caché desactivada y
activada (secuencial, para contar llamadas reales al solver): tiempo, aciertos, fallos y llamadas
al solver.

Es una medición descriptiva de una máquina local, con pocas carteras y universos sintéticos: no es
rendimiento de producción ni se extrapola. Los tiempos de esta máquina son bimodales (véase la
memoria del proyecto): se informa mínimo y mediana de las repeticiones. Sin datos reales ni SQL
Server.

Uso::

    python benchmarks/scripts/shared_data_cache.py --universe 50 500 --workers 1 2 4
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import multiprocessing
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.config import SharedDataMode  # noqa: E402
from portfolio_engine.config import config_hash as engine_config_hash  # noqa: E402
from portfolio_engine.config.parallel_config import ProcessStartMethod  # noqa: E402
from portfolio_engine.models.enums import CostTreatment, FrontierMethod  # noqa: E402
from portfolio_engine.parallel.executor import ParallelExecutor, SequentialExecutor  # noqa: E402
from portfolio_engine.parallel.shared_data import (  # noqa: E402
    inventory_orphans,
    publish_snapshot,
)
from portfolio_engine.parallel.task import ExecutionContext  # noqa: E402
from portfolio_engine.parallel.threading_control import worker_thread_environment  # noqa: E402
from portfolio_engine.parallel.worker import (  # noqa: E402
    initialize_worker,
    process_memory,
    worker_diagnostics,
)
from portfolio_engine.parallel.workload import (  # noqa: E402
    OperationKind,
    OperationSpec,
    WorkloadSpec,
)
from tests.fixtures.candidates import universe_problem  # noqa: E402
from tests.fixtures.parallel import (  # noqa: E402
    cache_config,
    compare_results,
    count_solver_calls,
    parallel_config,
    requests_for,
    snapshot_of,
)
from tests.fixtures.problems import base_config  # noqa: E402

#: Carteras de la comprobación T1 de cada celda de E4 y de las ejecuciones de E8.
T1_PORTFOLIOS = 8
E8_PORTFOLIOS = 12
HELD_ASSETS = 20
#: Posiciones por cartera: con ``MaxWeight = 0.2`` hacen falta >= 5 para un presupuesto factible.
PORTFOLIO_HOLDINGS = 10
RETURN_PERIODS = 300
MAX_PORTFOLIOS = 999  # D-12: sin cargas de >= 1.000 carteras en este script


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


def _valid_points(run: Any) -> int:
    """Puntos de frontera con solución válida en una ejecución (prueba de que no es trivial)."""
    total = 0
    for result in run.results:
        for outcome in result.operations:
            total += sum(1 for p in getattr(outcome.result, "points", ()) if p.is_valid_solution)
    return total


def _mb(value: int | None) -> float | None:
    return None if value is None else round(value / 1e6, 2)


def _stats(samples: list[float]) -> dict[str, float]:
    return {"min": min(samples), "median": statistics.median(samples), "max": max(samples)}


# --------------------------------------------------------------------------------- E4


def _startup_once(
    context: ExecutionContext, mode: SharedDataMode, method: str, workers: int
) -> dict[str, Any]:
    """Un pool completo: publica, arranca, adjunta y mide memoria de cada worker distinto."""
    mp_context = multiprocessing.get_context(method)
    coordinator_before = process_memory()
    started = time.perf_counter()
    with worker_thread_environment(1), publish_snapshot(context, mode) as published:
        publish_done = time.perf_counter()
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp_context,
            initializer=initialize_worker,
            initargs=(published.handle, 1),
        ) as pool:
            seen: dict[int, Any] = {}
            attempts = 0
            while len(seen) < workers and attempts < workers * 12:
                batch = [pool.submit(worker_diagnostics) for _ in range(workers * 2)]
                for future in batch:
                    diag = future.result()
                    seen[diag.pid] = diag
                attempts += 1
            ready = time.perf_counter()
            coordinator_after = process_memory()
    diagnostics = list(seen.values())
    return {
        "publish_seconds": publish_done - started,
        "ready_seconds": ready - started,
        "handle_bytes": published.info.handle_bytes,
        "header_bytes": published.info.header_bytes,
        "data_bytes": published.info.data_bytes,
        "n_buffers": published.info.n_buffers,
        "workers_observed": len(diagnostics),
        "attach_seconds": [d.attach_seconds for d in diagnostics],
        "sigma_backing": sorted({d.sigma_backing for d in diagnostics}),
        "worker_rss_mb": [_mb(d.memory.rss) if d.memory else None for d in diagnostics],
        "worker_uss_mb": [_mb(d.memory.uss) if d.memory else None for d in diagnostics],
        "worker_pss_mb": [_mb(d.memory.pss) if d.memory else None for d in diagnostics],
        "coordinator_rss_mb_before": _mb(coordinator_before.rss) if coordinator_before else None,
        "coordinator_rss_mb_after": _mb(coordinator_after.rss) if coordinator_after else None,
    }


def _e4_cell(
    config: Any,
    problem: Any,
    snapshot: Any,
    mode: SharedDataMode,
    method: str,
    workers: int,
    repetitions: int,
    reference: Any,
    requests: list[Any],
) -> dict[str, Any]:
    context = ExecutionContext.create(config, snapshot)
    runs = [_startup_once(context, mode, method, workers) for _ in range(repetitions)]
    pconfig = dataclasses.replace(
        parallel_config(workers=workers, batch_size=2),
        shared_data_mode=mode,
        start_method=ProcessStartMethod(method),
    )
    started = time.perf_counter()
    result = ParallelExecutor(config, snapshot, pconfig).run(requests)
    run_wall = time.perf_counter() - started
    differences = sum(
        len(compare_results(a, b).differences)
        for a, b in zip(reference.results, result.results, strict=True)
    )
    orphans = inventory_orphans(min_age_seconds=0.0)
    last = runs[-1]
    return {
        "mode": mode.value,
        "start_method": method,
        "workers": workers,
        "repetitions": repetitions,
        "ready_seconds": _stats([r["ready_seconds"] for r in runs]),
        "publish_seconds": _stats([r["publish_seconds"] for r in runs]),
        "attach_seconds_max_over_workers": _stats([max(r["attach_seconds"]) for r in runs]),
        "handle_bytes": last["handle_bytes"],
        "header_bytes": last["header_bytes"],
        "data_bytes": last["data_bytes"],
        "n_buffers": last["n_buffers"],
        "sigma_backing": last["sigma_backing"],
        "workers_observed": last["workers_observed"],
        "worker_rss_mb": last["worker_rss_mb"],
        "worker_uss_mb": last["worker_uss_mb"],
        "worker_pss_mb": last["worker_pss_mb"],
        "worker_uss_mb_sum": (
            None
            if any(v is None for v in last["worker_uss_mb"])
            else round(sum(last["worker_uss_mb"]), 2)
        ),
        "coordinator_rss_mb_after": last["coordinator_rss_mb_after"],
        "w0_run_wall_seconds": run_wall,
        "w0_run_t1_differences_vs_sequential": differences,
        "w0_valid_frontier_points": _valid_points(result),
        "valid_measurement": differences == 0,
        "leftover_directories": len(orphans.directories),
        "leftover_shared_memory": len(orphans.shared_memory),
    }


# --------------------------------------------------------------------------------- E8


def _e8(
    config: Any, problem: Any, snapshot: Any, repetitions: int, seed: int
) -> list[dict[str, Any]]:
    op = OperationSpec(
        OperationKind.FRONTIER_FIXED_COMPOSITION,
        CostTreatment.NET,
        method=FrontierMethod.RISK_AVERSION_GRID,
    )
    rows = []
    for k in (1, 2, 4):
        workload = WorkloadSpec(tuple(op for _ in range(k)))
        requests = requests_for(
            problem, workload, E8_PORTFOLIOS, holdings=PORTFOLIO_HOLDINGS, seed=seed, prefix="C-"
        )
        reference = None
        entry: dict[str, Any] = {"repeated_operations_k": k, "portfolios": E8_PORTFOLIOS}
        for label, cache in (("cache_off", None), ("cache_on", cache_config())):
            walls, metrics, calls = [], None, 0
            result = None
            for _ in range(repetitions):
                executor = SequentialExecutor(config, snapshot, cache)
                with count_solver_calls() as counter:
                    started = time.perf_counter()
                    result = executor.run(requests)
                    walls.append(time.perf_counter() - started)
                calls = counter.count
                metrics = result.cache_metrics
            assert result is not None and metrics is not None
            if reference is None:
                reference = result
            differences = sum(
                len(compare_results(a, b).differences)
                for a, b in zip(reference.results, result.results, strict=True)
            )
            entry[label] = {
                "wall_seconds": _stats(walls),
                "solver_calls": calls,
                "hits": metrics.hits,
                "misses": metrics.misses,
                "stores": metrics.stores,
                "cache_entries": metrics.entries,
                "cache_bytes": metrics.bytes,
                "t1_differences_vs_cache_off": differences,
                "valid_frontier_points": _valid_points(result),
            }
        off, on = entry["cache_off"], entry["cache_on"]
        entry["speedup_min"] = off["wall_seconds"]["min"] / on["wall_seconds"]["min"]
        entry["solver_calls_avoided"] = off["solver_calls"] - on["solver_calls"]
        rows.append(entry)
    return rows


def _cell_line(size: int, cell: dict[str, Any]) -> str:
    attach_ms = cell["attach_seconds_max_over_workers"]["min"] * 1e3
    return (
        f"N={size:4d} {cell['start_method']:10s} w={cell['workers']} {cell['mode']:13s} "
        f"listo={cell['ready_seconds']['min']:6.2f}s adjunción={attach_ms:7.1f}ms "
        f"USS/worker={cell['worker_uss_mb']} ref={cell['handle_bytes']}B "
        f"T1={cell['w0_run_t1_differences_vs_sequential']} "
        f"puntos_válidos={cell['w0_valid_frontier_points']}"
    )


def _e8_line(row: dict[str, Any]) -> str:
    off, on = row["cache_off"], row["cache_on"]
    return (
        f"E8 k={row['repeated_operations_k']} sin caché {off['wall_seconds']['min']:.2f}s "
        f"({off['solver_calls']} llamadas) / con caché {on['wall_seconds']['min']:.2f}s "
        f"({on['solver_calls']} llamadas, {on['hits']} aciertos)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=int, nargs="+", default=[50, 500])
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--start-methods", nargs="+", default=["spawn"])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--skip-e4", action="store_true")
    parser.add_argument("--skip-e8", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    args = parser.parse_args()
    if max(T1_PORTFOLIOS, E8_PORTFOLIOS) > MAX_PORTFOLIOS:
        raise SystemExit("Cargas de 1.000 o más carteras requieren aprobación específica (D-12).")
    config = base_config()
    workload = WorkloadSpec(
        (
            OperationSpec(
                OperationKind.FRONTIER_FIXED_COMPOSITION,
                CostTreatment.NET,
                method=FrontierMethod.RISK_AVERSION_GRID,
            ),
        )
    )
    e4: list[dict[str, Any]] = []
    e8: list[dict[str, Any]] = []
    snapshot_sizes: dict[str, dict[str, Any]] = {}
    last_problem = None
    for size in args.universe:
        problem = universe_problem(size, HELD_ASSETS, args.seed, config)
        snapshot = snapshot_of(problem, return_periods=RETURN_PERIODS, seed=args.seed)
        requests = requests_for(
            problem,
            workload,
            T1_PORTFOLIOS,
            holdings=PORTFOLIO_HOLDINGS,
            seed=args.seed,
            prefix="E4-",
        )
        context = ExecutionContext.create(config, snapshot)
        snapshot_sizes[str(size)] = {
            "sigma_mb": _mb(int(problem.risk_model.sigma.nbytes)),
            "returns_mb": _mb(int(snapshot.return_scenarios.returns.nbytes)),  # type: ignore[union-attr]
            "snapshot_key": context.snapshot_key,
        }
        last_problem = (problem, snapshot)
        if not args.skip_e4:
            reference = SequentialExecutor(config, snapshot).run(requests)
            for method in args.start_methods:
                for workers in args.workers:
                    for mode in SharedDataMode:
                        cell = _e4_cell(
                            config,
                            problem,
                            snapshot,
                            mode,
                            method,
                            workers,
                            args.repetitions,
                            reference,
                            requests,
                        )
                        cell["universe_assets"] = size
                        e4.append(cell)
                        print(_cell_line(size, cell), flush=True)
    if not args.skip_e8 and last_problem is not None:
        problem, snapshot = last_problem
        e8 = _e8(config, problem, snapshot, args.repetitions, args.seed)
        for row in e8:
            print(_e8_line(row), flush=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    document = {
        "metadata": {
            "benchmark": "shared_data_cache",
            "evidence_for": ["PAR-004", "PAR-005", "CCH-001..005", "BEN-004", "BEN-006"],
            "execution_timestamp_utc": stamp,
            "git_commit": _git_commit(),
            "engine_config_hash": engine_config_hash(config),
            "random_seed": args.seed,
            "universe_assets": args.universe,
            "held_assets": HELD_ASSETS,
            "workers": args.workers,
            "start_methods": args.start_methods,
            "repetitions": args.repetitions,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus_informational": os.cpu_count(),
            "psutil_available": process_memory() is not None,
            "tempdir": tempfile.gettempdir(),
            "note": (
                "Medición local y pequeña con universos sintéticos. No es rendimiento de "
                "producción ni se extrapola. Tiempos bimodales de esta máquina: mínimo y mediana. "
                "USS excluye páginas compartidas; en Linux PSS reparte las compartidas."
            ),
        },
        "snapshot_sizes": snapshot_sizes,
        "e4_shared_data": e4,
        "e8_cache": e8,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"shared_data_cache_{stamp}.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"resultado: {path}")
    if any(not cell["valid_measurement"] for cell in e4):
        raise SystemExit("Hay celdas con diferencias T1: medición NO válida.")


if __name__ == "__main__":
    main()
