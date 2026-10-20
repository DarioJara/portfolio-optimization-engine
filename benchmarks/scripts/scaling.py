"""Benchmark oficial de escalado del ejecutor paralelo (B5.5; BEN-001/002/004/006).

Para cada lote sintético (una mezcla ``ENG-MIX-*`` o una clase pura W0–W5), cada modo de ejecución
(``sequential``, ``spawn``, ``forkserver``) y cada número de workers mide: tiempo de pared (mínimo y
mediana de N repeticiones), throughput, latencia por cartera (p50/p95/p99/máx. medida **dentro del
worker**), tiempo de arranque del pool, tamaño y coste de (de)serialización de tareas y resultados,
memoria (RSS/USS del coordinador y de los workers) y estados de ejecución y de solver.

**Una medición solo es válida si el resultado es correcto**: cada ejecución paralela se compara con
la secuencial bajo T1 (``|Δ| ≤ 1e-6``, estados idénticos, ver ``BLOCK_5_BENCHMARK_PLAN.md`` §7), se
comprueba la integridad de conteo (cada tarea exactamente una vez) y se revalidan de forma
independiente presupuesto, largo-solo y ``MaxWeight`` de todas las soluciones. Una celda con
diferencias se marca ``valid_measurement = false`` y el script termina con error.

Es una medición descriptiva de UNA máquina, con datos sintéticos (sin datos reales, sin SQL Server):
no es rendimiento de producción ni se extrapola. Las mezclas son supuestos de ingeniería. Los
tiempos de esta máquina son bimodales (véase la memoria del proyecto): se informan mínimo, mediana y
contadores deterministas de trabajo. Las cargas de ≥ 1.000 carteras requieren autorización expresa
(D-12) y se rechazan salvo ``--authorized-by``.

Uso::

    python benchmarks/scripts/scaling.py --scales 10 100 --mix ENG-MIX-BASE --workers 1 2 4
    python benchmarks/scripts/scaling.py --scales 10 --classes all --workers 1 2 4 \
        --methods sequential spawn
"""

from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
import synthetic_portfolios  # noqa: E402

from portfolio_engine.benchmark.scaling import (  # noqa: E402
    efficiency,
    karp_flatt,
    percentile_summary,
    speedup,
)
from portfolio_engine.config import config_hash  # noqa: E402
from portfolio_engine.config.parallel_config import (  # noqa: E402
    ProcessStartMethod,
    SharedDataMode,
)
from portfolio_engine.config.scaling_config import (  # noqa: E402
    ClassShare,
    ScalingBenchmarkConfig,
    WorkloadMix,
    load_scaling_benchmark_config,
)
from portfolio_engine.parallel.executor import (  # noqa: E402
    ParallelExecutor,
    RunResult,
    SequentialExecutor,
)
from portfolio_engine.parallel.shared_data import worker_bundle  # noqa: E402
from portfolio_engine.parallel.task import ExecutionContext  # noqa: E402
from portfolio_engine.parallel.threading_control import worker_thread_environment  # noqa: E402
from portfolio_engine.parallel.worker import initialize_worker, worker_diagnostics  # noqa: E402
from tests.fixtures.parallel import class_workloads, compare_results, parallel_config  # noqa: E402
from tests.fixtures.problems import base_config  # noqa: E402

DEFAULT_CONFIG = ROOT / "config" / "default_benchmark.toml"
LEVELS = (50.0, 95.0, 99.0)


def _pure_class_mix(label: str) -> WorkloadMix:
    return WorkloadMix(f"PURE:{label}", (ClassShare(label, 1.0),))


def _sequential_cell(
    batch: synthetic_portfolios.SyntheticBatch, repetitions: int, warmup: int
) -> tuple[dict[str, Any], RunResult]:
    executor = SequentialExecutor(batch.config, batch.snapshot)
    for _ in range(warmup):
        executor.run(batch.requests)
    walls: list[float] = []
    runs: list[RunResult] = []
    for _ in range(repetitions):
        run, wall = _common.timed(executor.run, batch.requests)
        walls.append(wall)
        runs.append(run)
    reference = runs[0]
    # Determinismo secuencial↔secuencial (diagnóstico T0 y criterio T1).
    repeat_differences = sum(
        len(compare_results(reference.results[i], later.results[i]).differences)
        for later in runs[1:]
        for i in range(len(reference.results))
    )
    latencies = [r.elapsed_seconds for r in reference.results]
    with _common.MemorySampler() as sampler:
        executor.run(batch.requests)
    cell = {
        "mode": "sequential",
        "workers": 1,
        "wall_seconds_samples": walls,
        "wall": percentile_summary(walls, ()),
        "throughput_portfolios_per_second_min_wall": len(batch.requests) / min(walls),
        "task_latency_seconds": percentile_summary(latencies, LEVELS),
        "memory": sampler.report.to_json(),
        "t1_differences_between_repetitions": repeat_differences,
        "valid_measurement": repeat_differences == 0,
        "execution_statuses": _common.status_counts(reference.results),
        "warmup_runs_discarded": warmup,
    }
    return cell, reference


def _startup_seconds(
    batch: synthetic_portfolios.SyntheticBatch, workers: int, method: str, blas_threads: int
) -> float:
    """Tiempo de crear un pool con ``workers`` procesos listos (initializer ejecutado)."""
    started = time.perf_counter()
    with (
        worker_thread_environment(blas_threads),
        worker_bundle(ExecutionContext.create(batch.config, batch.snapshot)) as bundle,
        ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context(method),
            initializer=initialize_worker,
            initargs=(bundle, blas_threads),
        ) as pool,
    ):
        for future in [pool.submit(worker_diagnostics) for _ in range(workers * 2)]:
            future.result()
    return time.perf_counter() - started


def _parallel_cell(
    batch: synthetic_portfolios.SyntheticBatch,
    reference: RunResult,
    method: str,
    workers: int,
    repetitions: int,
    warmup: int,
    startup_repetitions: int,
    batch_size: int | None,
    blas_threads: int,
    shared_mode: str,
) -> dict[str, Any]:
    pconfig = replace(
        parallel_config(workers=workers, batch_size=batch_size),
        start_method=ProcessStartMethod(method),
        blas_threads=blas_threads,
        shared_data_mode=SharedDataMode[shared_mode],
    )

    def execute() -> RunResult:
        return ParallelExecutor(batch.config, batch.snapshot, pconfig).run(batch.requests)

    for _ in range(warmup):
        execute()
    walls: list[float] = []
    differences = 0
    inexact = 0
    max_abs = 0.0
    last: RunResult | None = None
    for _ in range(repetitions):
        last, wall = _common.timed(execute)
        walls.append(wall)
        for got, expected in zip(last.results, reference.results, strict=True):
            comparison = compare_results(expected, got)
            differences += len(comparison.differences)
            inexact += comparison.inexact_floats
            max_abs = max(max_abs, comparison.max_abs_difference)
    assert last is not None
    audit = _common.audit_constraints(last.results, batch.snapshot, batch.config)
    latencies = [r.elapsed_seconds for r in last.results]
    busy: dict[int | None, float] = {}
    for result in last.results:
        busy[result.worker_pid] = busy.get(result.worker_pid, 0.0) + result.elapsed_seconds
    with _common.MemorySampler() as sampler:
        execute()
    startups = [
        _startup_seconds(batch, workers, method, blas_threads) for _ in range(startup_repetitions)
    ]
    sample_request = pickle.dumps(batch.requests[0], protocol=5)
    sample_result = pickle.dumps(last.results[0], protocol=5)
    dumps_started = time.perf_counter()
    for _ in range(20):
        pickle.loads(pickle.dumps(last.results[0], protocol=5))
    roundtrip = (time.perf_counter() - dumps_started) / 20
    exactly_once = (
        last.accounting is not None
        and last.accounting.balanced
        and len({r.task_id for r in last.results}) == len(batch.requests)
    )
    valid = differences == 0 and audit.clean and exactly_once
    wall_min = min(walls)
    return {
        "mode": method,
        "workers": workers,
        "batch_size": "AUTO" if batch_size is None else batch_size,
        "blas_threads": blas_threads,
        "shared_data_mode": shared_mode,
        "effective_batch_size": last.manifest.batch_size,
        "batches": last.batches,
        "pool_rebuilds": last.pool_rebuilds,
        "wall_seconds_samples": walls,
        "wall": percentile_summary(walls, ()),
        "throughput_portfolios_per_second_min_wall": len(batch.requests) / wall_min,
        "task_latency_seconds": percentile_summary(latencies, LEVELS),
        "sum_task_compute_seconds": sum(latencies),
        "compute_occupancy": sum(latencies) / (workers * wall_min),
        "max_worker_busy_seconds": max(busy.values()),
        "overhead_estimate_seconds": wall_min - max(busy.values()),
        "distinct_worker_pids": len({p for p in busy if p is not None}),
        "pool_startup_seconds_samples": startups,
        "pool_startup_seconds": percentile_summary(startups, ()),
        "ipc": {
            "request_pickle_bytes": len(sample_request),
            "result_pickle_bytes": len(sample_result),
            "result_dumps_loads_roundtrip_seconds": roundtrip,
        },
        "memory": sampler.report.to_json(),
        "t1_differences_vs_sequential": differences,
        "t0_inexact_floats_vs_sequential": inexact,
        "t1_max_abs_difference": max_abs,
        "exactly_once_and_balanced": exactly_once,
        "constraint_audit": audit.to_json(),
        "valid_measurement": valid,
        "execution_statuses": _common.status_counts(last.results),
        "warmup_runs_discarded": warmup,
    }


def _derive(cells: list[dict[str, Any]]) -> None:
    """Añade speedup, eficiencia y fracción serie respecto a la celda secuencial."""
    sequential = next(c for c in cells if c["mode"] == "sequential")
    seq_min, seq_median = sequential["wall"]["min"], sequential["wall"]["median"]
    for cell in cells:
        if cell["mode"] == "sequential":
            continue
        s_min = speedup(seq_min, cell["wall"]["min"])
        s_med = speedup(seq_median, cell["wall"]["median"])
        cell["speedup_min"] = s_min
        cell["speedup_median"] = s_med
        cell["efficiency_min"] = efficiency(s_min, cell["workers"])
        cell["efficiency_median"] = efficiency(s_med, cell["workers"])
        cell["karp_flatt_serial_fraction_min"] = karp_flatt(s_min, cell["workers"])


def run_batch_set(
    scaling: ScalingBenchmarkConfig,
    mix: WorkloadMix,
    portfolios: int,
    seed: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    batch = synthetic_portfolios.generate(scaling, mix, portfolios, seed)
    repetitions = args.repetitions or scaling.repetitions_for(portfolios)
    parallel_repetitions = args.parallel_repetitions or repetitions
    print(
        f"[{mix.name}] {portfolios} carteras, {repetitions} rep. (paralelo {parallel_repetitions})"
    )
    cells: list[dict[str, Any]] = []
    sequential, reference = _sequential_cell(batch, repetitions, scaling.warmup_runs)
    cells.append(sequential)
    print(
        f"  sequential        min={sequential['wall']['min']:.2f} s "
        f"mediana={sequential['wall']['median']:.2f} s"
    )
    available = multiprocessing.get_all_start_methods()
    for method in args.methods:
        if method == "sequential":
            continue
        if method not in available:
            cells.append(
                {
                    "mode": method,
                    "available": False,
                    "reason": f"start method no disponible en {sys.platform}: {available}",
                }
            )
            print(f"  {method}: NO DISPONIBLE en esta plataforma")
            continue
        for workers, batch_size in itertools.product(args.workers, _batch_sizes(args)):
            cell = _parallel_cell(
                batch,
                reference,
                method,
                workers,
                parallel_repetitions,
                scaling.warmup_runs,
                args.startup_repetitions,
                batch_size,
                args.blas_threads,
                args.shared_data_mode,
            )
            cells.append(cell)
            print(
                f"  {method:10s} w={workers} lote={cell['batch_size']} "
                f"min={cell['wall']['min']:.2f} s "
                f"mediana={cell['wall']['median']:.2f} s "
                f"inicio={cell['pool_startup_seconds']['median']:.2f} s "
                f"T1_dif={cell['t1_differences_vs_sequential']} válida={cell['valid_measurement']}"
            )
    _derive([c for c in cells if c.get("available", True)])
    solver_calls = None
    if args.count_solver_calls:
        from tests.fixtures.parallel import count_solver_calls

        with count_solver_calls() as counter:
            SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
        solver_calls = counter.count
    return {
        "mix": mix.name,
        "mix_shares": {s.label: s.fraction for s in mix.shares},
        "portfolios": portfolios,
        "class_counts": batch.counts,
        "repetitions": repetitions,
        "parallel_repetitions": parallel_repetitions,
        "work_counters": {
            "frontier_solver_iterations": _common.frontier_iterations(reference.results),
            "solver_calls": solver_calls,
        },
        "snapshot_key": reference.manifest.snapshot_key,
        "cells": cells,
    }


def _batch_sizes(args: argparse.Namespace) -> list[int | None]:
    return [None if str(item).upper() == "AUTO" else int(item) for item in args.batch_size]


def _batch_label_list(args: argparse.Namespace) -> list[str]:
    return [str(item).upper() for item in args.batch_size]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--scales", type=int, nargs="+", required=True)
    parser.add_argument("--mix", help="nombre de mezcla (config); omitido con --classes")
    parser.add_argument(
        "--classes", nargs="*", help="clases puras (etiquetas de class_workloads) o 'all'"
    )
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--methods", nargs="+", default=["sequential", "spawn", "forkserver"])
    parser.add_argument(
        "--batch-size",
        nargs="*",
        default=["AUTO"],
        help="tamaños de lote a medir (enteros o AUTO); varios = barrido E3/E13",
    )
    parser.add_argument("--repetitions", type=int, default=0, help="0 = según la configuración")
    parser.add_argument(
        "--parallel-repetitions", type=int, default=0, help="0 = igual que --repetitions"
    )
    parser.add_argument("--startup-repetitions", type=int, default=3)
    parser.add_argument("--blas-threads", type=int, default=1, help="hilos BLAS por worker (E6)")
    parser.add_argument(
        "--shared-data-mode",
        default="BUNDLE_FILE",
        choices=["BUNDLE_FILE", "FILE_MMAP", "SHARED_MEMORY"],
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--count-solver-calls", action="store_true")
    parser.add_argument("--authorized-by", help="autorización expresa (D-12) para ≥ 1.000 carteras")
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    parser.add_argument("--tag", default="", help="etiqueta añadida al nombre del fichero")
    args = parser.parse_args()

    scaling = load_scaling_benchmark_config(args.config)
    if max(args.scales) > scaling.max_portfolios_without_authorization and not args.authorized_by:
        raise SystemExit(
            f"Cargas de más de {scaling.max_portfolios_without_authorization} carteras requieren "
            "autorización expresa (D-12): use --authorized-by con su referencia."
        )
    if bool(args.mix) == bool(args.classes):
        raise SystemExit("Indique exactamente una de --mix o --classes.")
    if args.classes:
        labels = list(class_workloads()) if args.classes == ["all"] else args.classes
        mixes = [_pure_class_mix(label) for label in labels]
    else:
        mixes = [scaling.mix(args.mix)]

    meta = _common.metadata(
        "scaling",
        ["BEN-001", "BEN-002", "BEN-004", "BEN-006", "BEN-007", "GOV-012", "PAR-008"],
        scaling_config=str(args.config.relative_to(ROOT))
        if args.config.is_relative_to(ROOT)
        else str(args.config),
        scaling_config_sha256=_file_sha256(args.config),
        random_seed=args.seed,
        engine_config_hash=None,
        mixes_are_engineering_assumptions=True,
        start_methods_requested=args.methods,
        start_methods_available=multiprocessing.get_all_start_methods(),
        blas_threads_per_worker=args.blas_threads,
        shared_data_mode=args.shared_data_mode,
        batch_sizes=_batch_label_list(args),
        authorized_by=args.authorized_by,
    )
    results: list[dict[str, Any]] = []
    for mix in mixes:
        for portfolios in args.scales:
            entry = run_batch_set(scaling, mix, portfolios, args.seed, args)
            results.append(entry)
    meta["engine_config_hash"] = config_hash(base_config())
    document = {
        "metadata": meta,
        "note": (
            "Medición local de una sola máquina con datos sintéticos; no es rendimiento de "
            "producción ni se extrapola. Tiempos bimodales: se informan mínimo y mediana. Una "
            "celda "
            "con diferencias T1 o violaciones de restricciones NO es una medición válida."
        ),
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    name = args.mix or "classes"
    tag = f"_{args.tag}" if args.tag else ""
    scales = "-".join(str(s) for s in args.scales)
    path = (
        args.out / f"scaling_{name}_{scales}portfolios{tag}_{meta['execution_timestamp_utc']}.json"
    )
    path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
    print(f"resultado: {path}")
    invalid = [
        (entry["mix"], entry["portfolios"], cell["mode"], cell["workers"])
        for entry in results
        for cell in entry["cells"]
        if cell.get("available", True) and not cell["valid_measurement"]
    ]
    if invalid:
        raise SystemExit(f"Mediciones NO válidas (diferencias o restricciones violadas): {invalid}")


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
