"""Benchmark de recuperación ante fallos y coste del diario (B5.5; E9, E16; BEN-001/004/006).

Mide, con procesos reales y fallos inyectados **dentro del worker**
(``tests/fixtures/faults.py``), el coste de cada mecanismo de B5.4 frente a una ejecución
limpia de la misma carga:

* ``clean``: sin diario (referencia) y ``clean_journal`` (coste del diario, E16);
* ``worker_killed_once``: un worker muere (``os._exit``) una vez ⇒ reintento aislado;
* ``poison_task``: una tarea mata siempre a su worker ⇒ ``WORKER_CRASHED`` y vecinas completas;
* ``hanging_task``: una tarea no termina ⇒ ``TIMED_OUT`` tras el plazo configurado;
* ``cancel_then_resume``: cancelación a mitad (latencia) y reanudación desde el diario
  (tiempo, tareas rehechas, resultado final ≡ ejecución ininterrumpida bajo T1);
* ``corrupt_shard_then_resume``: un shard truncado se detecta y solo esa parte se rehace.

Cada escenario verifica: orden canónico, integridad (cada tarea exactamente una vez, enviadas = Σ
estados finales) y T1 frente a la referencia secuencial para todas las tareas no afectadas por el
fallo. Un escenario que viole alguna comprobación no es una medición válida y el script termina con
error. Datos sintéticos; sin SQL Server. Medición local descriptiva (no producción).

Uso::

    python benchmarks/scripts/recovery_bench.py --portfolios 12 --workers 2 --repetitions 3
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
import synthetic_portfolios  # noqa: E402

from portfolio_engine.benchmark.scaling import percentile_summary  # noqa: E402
from portfolio_engine.config.scaling_config import (  # noqa: E402
    ClassShare,
    WorkloadMix,
    load_scaling_benchmark_config,
)
from portfolio_engine.parallel.executor import (  # noqa: E402
    JournalSpec,
    ParallelExecutor,
    RunResult,
    SequentialExecutor,
)
from portfolio_engine.parallel.protocols import (  # noqa: E402
    CancellationToken,
    ProgressEvent,
    ProgressKind,
    RecordingProgressReporter,
)
from portfolio_engine.parallel.task import ExecutionStatus  # noqa: E402
from tests.fixtures.faults import FaultSpec, FaultyExecutor, fault_config  # noqa: E402
from tests.fixtures.parallel import compare_results  # noqa: E402

DEFAULT_CONFIG = ROOT / "config" / "default_benchmark.toml"
WORKLOAD_LABEL = "W0-NET-TARGET"


def _check(
    run: RunResult, reference: RunResult, *, except_ids: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Comprobaciones de validez de un escenario (orden, integridad y T1 de las tareas sanas)."""
    ordered = [r.portfolio_id for r in run.results] == [r.portfolio_id for r in reference.results]
    balanced = run.accounting is not None and run.accounting.balanced
    once = len({r.task_id for r in run.results}) == len(reference.results)
    differences = 0
    for got, expected in zip(run.results, reference.results, strict=True):
        if got.portfolio_id in except_ids:
            continue
        if got.execution_status is not ExecutionStatus.COMPLETED:
            differences += 1
            continue
        differences += len(compare_results(expected, got).differences)
    return {
        "canonical_order": ordered,
        "accounting_balanced": balanced,
        "each_task_exactly_once": once,
        "t1_differences_healthy_tasks": differences,
        "valid": ordered and balanced and once and differences == 0,
    }


def _recovery_fields(run: RunResult) -> dict[str, Any]:
    report = run.recovery
    return {
        "crashes": report.crashes,
        "isolated_retries": report.isolated_retries,
        "poisoned_tasks": report.poisoned_tasks,
        "timeouts": report.timeouts,
        "pool_rebuilds": run.pool_rebuilds,
        "cancelled": report.cancelled,
        "aborted": report.aborted,
        "execution_statuses": _common.status_counts(run.results),
        "accounting": dict(run.accounting.by_status) if run.accounting else None,
    }


class _CancelAfter(RecordingProgressReporter):
    """Cancela tras ``count`` resultados y anota el instante exacto de la petición."""

    def __init__(self, token: CancellationToken, count: int) -> None:
        super().__init__()
        self._token = token
        self._count = count
        self.cancelled_at: float | None = None

    def report(self, event: ProgressEvent) -> None:
        super().report(event)
        if (
            event.kind is ProgressKind.RESULTS
            and event.completed >= self._count
            and self.cancelled_at is None
        ):
            self.cancelled_at = time.perf_counter()
            self._token.cancel()


def _scenario_clean(env: dict[str, Any], journal: bool) -> dict[str, Any]:
    scratch = Path(tempfile.mkdtemp(prefix="recbench-"))
    try:
        started = time.perf_counter()
        spec = JournalSpec(scratch / "j") if journal else None
        run = ParallelExecutor(env["config"], env["snapshot"], env["pconfig"]).run(
            env["requests"], journal=spec
        )
        wall = time.perf_counter() - started
        journal_bytes = (
            sum(f.stat().st_size for f in (scratch / "j").rglob("*") if f.is_file())
            if journal
            else 0
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {
        "wall_seconds": wall,
        "journal_bytes": journal_bytes,
        **_check(run, env["reference"]),
        **_recovery_fields(run),
    }


def _scenario_fault(env: dict[str, Any], spec: FaultSpec, pconfig: Any) -> dict[str, Any]:
    started = time.perf_counter()
    run = FaultyExecutor(env["config"], env["snapshot"], pconfig, spec=spec).run(env["requests"])
    wall = time.perf_counter() - started
    affected = frozenset(spec.die + spec.hang)
    return {
        "wall_seconds": wall,
        **_check(run, env["reference"], except_ids=affected),
        **_recovery_fields(run),
    }


def _cancel_then_resume(env: dict[str, Any], corrupt: bool) -> dict[str, Any]:
    scratch = Path(tempfile.mkdtemp(prefix="recbench-"))
    journal = scratch / "j"
    try:
        token = CancellationToken()
        reporter = _CancelAfter(token, max(2, len(env["requests"]) // 3))
        slow = FaultSpec(delay=env["delay"])
        started = time.perf_counter()
        first = FaultyExecutor(env["config"], env["snapshot"], env["pconfig"], spec=slow).run(
            env["requests"], journal=JournalSpec(journal), control=token, progress=reporter
        )
        first_wall = time.perf_counter() - started
        cancel_latency = None
        if reporter.cancelled_at is not None:
            cancel_latency = (started + first_wall) - reporter.cancelled_at
        completed_before = sum(
            r.execution_status is ExecutionStatus.COMPLETED for r in first.results
        )
        damaged = 0
        if corrupt:
            shards = sorted((journal / "shards").glob("s-*.json"))
            if shards:
                data = shards[0].read_bytes()
                shards[0].write_bytes(data[: len(data) // 2])
                damaged = 1
        started = time.perf_counter()
        resumed = ParallelExecutor(env["config"], env["snapshot"], env["pconfig"]).run(
            env["requests"], journal=JournalSpec(journal, resume=True)
        )
        resume_wall = time.perf_counter() - started
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {
        "first_run_wall_seconds": first_wall,
        "cancel_latency_seconds": cancel_latency,
        "completed_before_cancel": completed_before,
        "damaged_shards": damaged,
        "resume_wall_seconds": resume_wall,
        "tasks_restored_from_journal": resumed.accounting.resumed if resumed.accounting else None,
        "tasks_redone": len(env["requests"])
        - (resumed.accounting.resumed if resumed.accounting else 0),
        "journal_scan": None if resumed.journal_scan is None else repr(resumed.journal_scan),
        **_check(resumed, env["reference"]),
        **_recovery_fields(resumed),
    }


def _summarize(samples: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    summary: dict[str, Any] = {"repetitions": len(samples)}
    for key in keys:
        values = [s[key] for s in samples if isinstance(s.get(key), (int, float))]
        if values:
            summary[key] = percentile_summary(values, ())
    summary["all_valid"] = all(s["valid"] for s in samples)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--portfolios", type=int, default=12)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--task-timeout", type=float, default=3.0)
    parser.add_argument(
        "--delay", type=float, default=0.3, help="retraso por tarea para poder cancelar"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    args = parser.parse_args()
    if args.portfolios > 999:
        raise SystemExit("Este benchmark es local y pequeño (D-12): menos de 1.000 carteras.")

    scaling = load_scaling_benchmark_config(args.config)
    mix = WorkloadMix("RECOVERY", (ClassShare(WORKLOAD_LABEL, 1.0),))
    batch = synthetic_portfolios.generate(scaling, mix, args.portfolios, args.seed)
    reference = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    ids = sorted(r.portfolio_id for r in batch.requests)
    victim, poison, hung = ids[3 % len(ids)], ids[2 % len(ids)], ids[4 % len(ids)]
    env: dict[str, Any] = {
        "config": batch.config,
        "snapshot": batch.snapshot,
        "requests": list(batch.requests),
        "reference": reference,
        "pconfig": fault_config(args.workers, 2),
        "delay": args.delay,
    }
    scratch_flags = Path(tempfile.mkdtemp(prefix="recbench-flags-"))
    scenarios: dict[str, Any] = {
        "clean": lambda: _scenario_clean(env, False),
        "clean_journal": lambda: _scenario_clean(env, True),
        "worker_killed_once": lambda: _scenario_fault(
            env, FaultSpec(die_once=(victim,), flag_dir=str(scratch_flags)), env["pconfig"]
        ),
        "poison_task": lambda: _scenario_fault(
            env, FaultSpec(die=(poison,)), fault_config(args.workers, 4)
        ),
        "hanging_task": lambda: _scenario_fault(
            env,
            FaultSpec(hang=(hung,)),
            fault_config(args.workers, 1, task_timeout_seconds=args.task_timeout),
        ),
        "cancel_then_resume": lambda: _cancel_then_resume(env, corrupt=False),
        "corrupt_shard_then_resume": lambda: _cancel_then_resume(env, corrupt=True),
    }
    results: dict[str, Any] = {}
    for name, scenario in scenarios.items():
        samples = []
        for repetition in range(args.repetitions):
            for flag in scratch_flags.glob("*.died"):
                flag.unlink()  # die_once debe volver a morir en cada repetición
            sample = scenario()
            samples.append(sample)
            print(f"{name} #{repetition}: válido={sample['valid']}", flush=True)
        results[name] = {
            "samples": samples,
            "summary": _summarize(
                samples,
                (
                    "wall_seconds",
                    "first_run_wall_seconds",
                    "resume_wall_seconds",
                    "cancel_latency_seconds",
                    "tasks_redone",
                    "journal_bytes",
                ),
            ),
        }
    shutil.rmtree(scratch_flags, ignore_errors=True)
    clean_min = results["clean"]["summary"]["wall_seconds"]["min"]
    overheads = {
        name: results[name]["summary"]["wall_seconds"]["min"] - clean_min
        for name in ("clean_journal", "worker_killed_once", "poison_task", "hanging_task")
    }
    meta = _common.metadata(
        "recovery_bench",
        ["BEN-001", "BEN-004", "BEN-006", "PAR-011", "P-03", "P-04", "P-05", "P-06"],
        portfolios=args.portfolios,
        workers=args.workers,
        repetitions=args.repetitions,
        workload_class=WORKLOAD_LABEL,
        random_seed=args.seed,
        start_method="spawn",
        task_timeout_seconds=args.task_timeout,
        injected_delay_per_task_seconds=args.delay,
        threads_alive_at_end=threading.active_count(),
        children_alive_at_end=len(multiprocessing.active_children()),
    )
    document = {
        "metadata": meta,
        "note": (
            "Medición local de una sola máquina con datos sintéticos; los fallos se "
            "inyectan dentro del worker (os._exit / cuelgue). No es rendimiento de producción."
        ),
        "overhead_vs_clean_min_wall_seconds": overheads,
        "scenarios": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"recovery_{args.portfolios}portfolios_{meta['execution_timestamp_utc']}.json"
    path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
    print(f"resultado: {path}")
    invalid = [name for name, entry in results.items() if not entry["summary"]["all_valid"]]
    if invalid:
        raise SystemExit(f"Escenarios con comprobaciones fallidas: {invalid}")


if __name__ == "__main__":
    main()
