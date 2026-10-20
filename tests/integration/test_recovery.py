"""B5.4 con procesos reales: recuperación, reintentos, plazos, cancelación, diario y reanudación.

Cada prueba inyecta el fallo **dentro de un worker real** (``tests/fixtures/faults.py``): muerte
abrupta, cuelgue, *initializer* roto. Contrasta siempre con la referencia secuencial (T1) y con el
invariante de conteo (cada ``TaskID`` exactamente una vez; enviadas = Σ estados finales).
Datos sintéticos pequeños; ninguna prueba depende de tiempos de pared salvo como cota de seguridad.
"""

from __future__ import annotations

import dataclasses
import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.parallel.batching import ParallelExecutionError
from portfolio_engine.parallel.executor import (
    JournalSpec,
    ParallelExecutor,
    RunResult,
    SequentialExecutor,
)
from portfolio_engine.parallel.journal import (
    JournalIncompatibleError,
    inspect_journal,
)
from portfolio_engine.parallel.protocols import (
    CancellationToken,
    CollectingResultSink,
    ProgressEvent,
    ProgressKind,
    RecordingProgressReporter,
)
from portfolio_engine.parallel.shared_data import (
    RUN_DIR_PREFIX,
    inventory_orphans,
    remove_orphans,
)
from portfolio_engine.parallel.task import ExecutionStatus, PortfolioRequest
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.faults import FaultSpec, FaultyExecutor, fault_config
from tests.fixtures.parallel import compare_results, requests_for, snapshot_of
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.integration

CONFIG = base_config()
WORKLOAD = WorkloadSpec(
    (
        OperationSpec(
            OperationKind.FRONTIER_FIXED_COMPOSITION,
            CostTreatment.NET,
            method=FrontierMethod.RISK_AVERSION_GRID,
        ),
    )
)
N_REQUESTS = 8
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def problem() -> Any:
    return random_problem(8, [0, 1, 2], 3, CONFIG)


@pytest.fixture(scope="module")
def snapshot(problem: Any) -> Any:
    return snapshot_of(problem)


@pytest.fixture(scope="module")
def requests(problem: Any) -> list[PortfolioRequest]:
    return requests_for(problem, WORKLOAD, N_REQUESTS, seed=21)


@pytest.fixture(scope="module")
def sequential(snapshot: Any, requests: list[PortfolioRequest]) -> RunResult:
    return SequentialExecutor(CONFIG, snapshot).run(requests)


def _ids(requests: list[PortfolioRequest]) -> list[str]:
    return sorted(r.portfolio_id for r in requests)


def _assert_matches(
    run: RunResult, sequential: RunResult, *, except_ids: set[str] = frozenset()
) -> None:  # type: ignore[assignment]
    """Orden canónico, una vez cada tarea y T1 contra la referencia para todo lo no excluido."""
    assert [r.portfolio_id for r in run.results] == [r.portfolio_id for r in sequential.results]
    assert run.accounting is not None and run.accounting.balanced
    assert run.accounting.submitted == len(sequential.results)
    for got, expected in zip(run.results, sequential.results, strict=True):
        if got.portfolio_id in except_ids:
            continue
        assert got.execution_status is ExecutionStatus.COMPLETED, got.portfolio_id
        assert compare_results(expected, got).differences == [], got.portfolio_id


# ------------------------------------------------------------------- plazo del solver (capa 1)


def test_a_solver_time_limit_is_a_solver_status_not_an_execution_failure() -> None:
    """P-04 (F-04): ``TIME_LIMIT`` del backend viaja intacto dentro de una tarea ``COMPLETED``.

    El supervisor solo gobierna plazos de tarea y de lote; el plazo del solver es de cada backend
    (``solver.time_limit_seconds``) y no se reetiqueta como ``TIMED_OUT``: el estado matemático y
    el de ejecución son independientes, igual en secuencial y en paralelo.
    """
    from portfolio_engine.models.enums import CrossCheckPolicy, SolverStatus

    tight = base_config(
        solver={"time_limit_seconds": 1e-12, "ambiguous_status_policy": CrossCheckPolicy.NONE}
    )
    tight_problem = random_problem(8, [0, 1, 2], 3, tight)
    reqs = requests_for(tight_problem, WORKLOAD, 4, seed=1)
    snap = snapshot_of(tight_problem)
    reference = SequentialExecutor(tight, snap).run(reqs)
    run = ParallelExecutor(tight, snap, fault_config(2, 2)).run(reqs)
    assert {r.execution_status for r in run.results} == {ExecutionStatus.COMPLETED}
    for got, expected in zip(run.results, reference.results, strict=True):
        statuses = {
            point.status
            for operation in got.operations
            for point in operation.result.points  # type: ignore[union-attr]
        }
        assert statuses == {SolverStatus.TIME_LIMIT}
        assert compare_results(expected, got).differences == []
    assert run.recovery.timeouts == 0 and run.recovery.pool_rebuilds == 0


# ------------------------------------------------------------------------- caídas de worker


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_a_worker_killed_mid_task_is_retried_and_the_result_equals_an_uninterrupted_run(
    tmp_path: Path,
    snapshot: Any,
    requests: list[PortfolioRequest],
    sequential: RunResult,
    workers: int,
) -> None:
    """C-12: matar el worker en medio de una tarea ⇒ reintento y resultado final = sin fallos."""
    victim = _ids(requests)[3]
    spec = FaultSpec(die_once=(victim,), flag_dir=str(tmp_path))
    run = FaultyExecutor(CONFIG, snapshot, fault_config(workers, 2), spec=spec).run(requests)
    _assert_matches(run, sequential)
    assert run.recovery.crashes >= 1 and run.recovery.poisoned_tasks == 0
    assert run.recovery.isolated_retries >= 1 and not run.recovery.aborted
    assert (tmp_path / f"{victim}.died").exists()
    assert multiprocessing.active_children() == []


def test_a_poison_task_does_not_fail_its_healthy_batch_neighbours(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """C-14: la tarea venenosa queda ``WORKER_CRASHED``; las vecinas del lote se completan."""
    poison = _ids(requests)[2]
    spec = FaultSpec(die=(poison,))
    run = FaultyExecutor(CONFIG, snapshot, fault_config(2, 4), spec=spec).run(requests)
    _assert_matches(run, sequential, except_ids={poison})
    crashed = run.by_portfolio()[poison]
    assert crashed.execution_status is ExecutionStatus.WORKER_CRASHED
    assert crashed.error is not None and crashed.error.error_type == "WorkerCrashed"
    assert run.recovery.poisoned_tasks == 1
    assert dict(run.accounting.by_status if run.accounting else ()) == {
        "COMPLETED": N_REQUESTS - 1,
        "WORKER_CRASHED": 1,
    }
    assert multiprocessing.active_children() == []


def test_workers_that_are_recycled_are_not_mistaken_for_crashes(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """La vigilancia de PID no debe dar falsos positivos con ``max_tasks_per_child``."""
    config = dataclasses.replace(fault_config(2, 1), max_tasks_per_child=1)
    run = ParallelExecutor(CONFIG, snapshot, config).run(requests)
    _assert_matches(run, sequential)
    assert run.recovery.pool_rebuilds == 0 and run.recovery.crashes == 0


# ------------------------------------------------------------------------- el entorno no arranca


@pytest.mark.parametrize(
    ("init", "status", "message"),
    [
        ("tamper", ExecutionStatus.WORKER_INIT_FAILED, "hash"),
        ("exit", ExecutionStatus.ABORTED, "puede reintentarse"),
        ("exit_registered", ExecutionStatus.ABORTED, "puede reintentarse"),
    ],
)
def test_an_initializer_that_always_fails_ends_with_bounded_rebuilds(
    snapshot: Any,
    requests: list[PortfolioRequest],
    init: str,
    status: ExecutionStatus,
    message: str,
) -> None:
    """M-1: sin bucle infinito; cada tarea consta una vez con un estado que dice qué pasó."""
    config = fault_config(2, 2, max_rebuilds_without_progress=2)
    started = time.monotonic()
    run = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec(init=init)).run(requests)
    assert time.monotonic() - started < 240.0  # cota de seguridad, no una afirmación de tiempo
    assert [r.portfolio_id for r in run.results] == _ids(requests)
    assert {r.execution_status for r in run.results} == {status}
    assert all(r.error is not None and message in r.error.message for r in run.results)
    assert run.recovery.aborted and run.pool_rebuilds == 2
    assert run.accounting is not None and run.accounting.balanced
    assert multiprocessing.active_children() == []


# ---------------------------------------------------------------------------------- plazos


def test_a_hanging_task_is_timed_out_and_the_rest_complete(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """C-15: tarea que excede el plazo ⇒ ``TIMED_OUT``; el worker se termina de verdad."""
    hung = _ids(requests)[4]
    config = fault_config(2, 1, task_timeout_seconds=3.0)
    run = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec(hang=(hung,))).run(requests)
    _assert_matches(run, sequential, except_ids={hung})
    result = run.by_portfolio()[hung]
    assert result.execution_status is ExecutionStatus.TIMED_OUT
    assert result.error is not None and result.error.error_type == "TaskTimeout"
    assert run.recovery.timeouts == 1 and run.recovery.poisoned_tasks == 0
    assert multiprocessing.active_children() == []  # el proceso colgado no sobrevive


def test_more_deadlines_than_the_failure_budget_still_let_healthy_tasks_finish(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """M-1 con procesos reales: 3 plazos vencidos con ``max_total_rebuilds=1``."""
    ids = _ids(requests)
    hung = {ids[1], ids[3], ids[6]}
    config = fault_config(2, 1, task_timeout_seconds=3.0, max_total_rebuilds=1)
    run = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec(hang=tuple(hung))).run(requests)
    _assert_matches(run, sequential, except_ids=hung)
    assert {
        r.portfolio_id for r in run.results if r.execution_status is ExecutionStatus.TIMED_OUT
    } == hung
    assert run.recovery.timeouts == 3 and not run.recovery.aborted
    assert run.recovery.deadline_rebuilds >= 3 > config.recovery.max_total_rebuilds
    assert ExecutionStatus.ABORTED not in {r.execution_status for r in run.results}
    assert multiprocessing.active_children() == []


def test_a_batch_over_its_deadline_is_split_and_only_the_hanging_task_fails(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    hung = _ids(requests)[1]
    config = fault_config(2, 4, batch_timeout_seconds=4.0)
    run = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec(hang=(hung,))).run(requests)
    _assert_matches(run, sequential, except_ids={hung})
    result = run.by_portfolio()[hung]
    assert result.execution_status is ExecutionStatus.TIMED_OUT
    assert result.error is not None and result.error.error_type == "BatchTimeout"
    assert run.recovery.batches_split >= 1 and run.recovery.timeouts == 1


# ----------------------------------------------------------------------------- cancelación


def test_cancellation_keeps_completed_work_and_sends_nothing_more(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """C-15: la cancelación conserva lo completado y no envía más trabajo."""
    token = CancellationToken()

    class CancelAfter(RecordingProgressReporter):
        def report(self, event: ProgressEvent) -> None:
            super().report(event)
            if event.kind is ProgressKind.RESULTS and event.completed >= 3:
                token.cancel()

    reporter = CancelAfter()
    sink = CollectingResultSink()
    config = fault_config(1, 1)
    run = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec(delay=0.3)).run(
        requests, control=token, progress=reporter, sink=sink
    )
    statuses = [r.execution_status for r in run.results]
    assert run.recovery.cancelled and ExecutionStatus.CANCELLED in statuses
    done = [r for r in run.results if r.execution_status is ExecutionStatus.COMPLETED]
    assert 3 <= len(done) < N_REQUESTS
    for result in done:
        reference = sequential.by_portfolio()[result.portfolio_id]
        assert compare_results(reference, result).differences == []
    assert {s for s in statuses} <= {ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED}
    assert run.accounting is not None and run.accounting.balanced
    assert sorted(r.task_id for r in sink.received) == sorted(r.task_id for r in run.results)
    assert ProgressKind.CANCELLED in {e.kind for e in reporter.events}
    assert multiprocessing.active_children() == []


# ------------------------------------------------------------------------------------ diario


def _journal_config(workers: int = 2, batch: int | None = 1, **recovery: Any) -> Any:
    return fault_config(workers, batch, **recovery)


def test_a_journalled_run_resumes_without_executing_anything_and_matches_exactly(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    config = _journal_config()
    first = ParallelExecutor(CONFIG, snapshot, config).run(
        requests, journal=JournalSpec(tmp_path / "j")
    )
    _assert_matches(first, sequential)
    sink = CollectingResultSink()
    second = ParallelExecutor(CONFIG, snapshot, config).run(
        requests, journal=JournalSpec(tmp_path / "j", resume=True), sink=sink
    )
    assert second.batches == 0 and second.pool_rebuilds == 0
    assert second.accounting is not None and second.accounting.resumed == N_REQUESTS
    assert dict(second.accounting.by_status) == {"SKIPPED_BY_RESUME": N_REQUESTS}
    assert len(second.resumed_task_ids) == N_REQUESTS
    for original, restored in zip(first.results, second.results, strict=True):
        assert restored.execution_status is ExecutionStatus.COMPLETED  # estado original
        assert compare_results(original, restored, tolerance=0.0).differences == []
    assert sorted(r.task_id for r in sink.received) == sorted(r.task_id for r in second.results)
    info = inspect_journal(tmp_path / "j")
    assert info["complete"] is True and info["restorable_records"] == N_REQUESTS


def test_resume_executes_only_the_missing_tasks(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """Se pierden algunos shards (borrados): solo esas tareas se re-ejecutan."""
    config = _journal_config()
    ParallelExecutor(CONFIG, snapshot, config).run(requests, journal=JournalSpec(tmp_path / "j"))
    shards = sorted((tmp_path / "j" / "shards").glob("s-*.json"))
    lost = len(shards) // 2
    for shard in shards[:lost]:
        shard.unlink()
    run = ParallelExecutor(CONFIG, snapshot, config).run(
        requests, journal=JournalSpec(tmp_path / "j", resume=True)
    )
    _assert_matches(run, sequential)
    assert run.accounting is not None
    assert run.accounting.resumed == N_REQUESTS - lost
    assert dict(run.accounting.by_status) == {
        "COMPLETED": lost,
        "SKIPPED_BY_RESUME": N_REQUESTS - lost,
    }


def test_resume_after_the_cause_of_the_failure_is_fixed_completes_the_task(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """Un ``WORKER_CRASHED`` no se restaura: al reanudar (ya sin el fallo) se completa."""
    poison = _ids(requests)[5]
    config = _journal_config()
    broken = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec(die=(poison,))).run(
        requests, journal=JournalSpec(tmp_path / "j")
    )
    assert broken.by_portfolio()[poison].execution_status is ExecutionStatus.WORKER_CRASHED
    fixed = ParallelExecutor(CONFIG, snapshot, config).run(
        requests, journal=JournalSpec(tmp_path / "j", resume=True)
    )
    _assert_matches(fixed, sequential)
    assert fixed.accounting is not None and fixed.accounting.resumed == N_REQUESTS - 1
    events = (tmp_path / "j" / "events.jsonl").read_text(encoding="utf-8")
    assert "poisoned" in events and "not_restorable" in events and poison not in events


def test_resume_with_a_different_snapshot_config_or_requests_is_rejected_untouched(
    tmp_path: Path, problem: Any, snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    config = _journal_config()
    ParallelExecutor(CONFIG, snapshot, config).run(requests, journal=JournalSpec(tmp_path / "j"))
    before = {p: p.read_bytes() for p in (tmp_path / "j").rglob("*") if p.is_file()}
    before.pop(tmp_path / "j" / ".lock", None)
    other_snapshot = snapshot_of(random_problem(8, [0, 1, 2], 4, CONFIG))
    other_requests = requests_for(problem, WORKLOAD, N_REQUESTS, seed=77)
    cases = {
        "snapshot": (ParallelExecutor(CONFIG, other_snapshot, config), requests),
        "requests": (ParallelExecutor(CONFIG, snapshot, config), other_requests),
        "fewer requests": (ParallelExecutor(CONFIG, snapshot, config), requests[:-1]),
    }
    for label, (executor, reqs) in cases.items():
        with pytest.raises(JournalIncompatibleError):
            executor.run(reqs, journal=JournalSpec(tmp_path / "j", resume=True))
        after = {p: p.read_bytes() for p in (tmp_path / "j").rglob("*") if p.is_file()}
        after.pop(tmp_path / "j" / ".lock", None)
        assert after == before, label  # sin corrupción ni cambios


def test_the_journal_is_opt_in_in_the_configuration(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    config = fault_config(1, 2, journal_enabled=False)
    with pytest.raises(ParallelExecutionError, match="journal_enabled"):
        ParallelExecutor(CONFIG, snapshot, config).run(
            requests, journal=JournalSpec(tmp_path / "j")
        )
    assert not (tmp_path / "j").exists()  # ni siquiera se crea


def test_a_run_does_not_leave_scratch_or_snapshot_directories(
    tmp_path: Path,
    snapshot: Any,
    requests: list[PortfolioRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    spec = FaultSpec(die_once=(_ids(requests)[0],), flag_dir=str(tmp_path))
    FaultyExecutor(CONFIG, snapshot, fault_config(2, 2), spec=spec).run(requests)
    assert [p for p in tmp_path.iterdir() if p.name.startswith(RUN_DIR_PREFIX)] == []


# ------------------------------------------------------------- caída del coordinador (real)

COORDINATOR_SCRIPT = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.fixtures.candidates import random_problem
from tests.fixtures.faults import FaultSpec, FaultyExecutor, fault_config
from tests.fixtures.parallel import requests_for, snapshot_of
from tests.fixtures.problems import base_config
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.parallel.executor import JournalSpec
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec

def main():
    config = base_config()
    problem = random_problem(8, [0, 1, 2], 3, config)
    workload = WorkloadSpec((OperationSpec(
        OperationKind.FRONTIER_FIXED_COMPOSITION, CostTreatment.NET,
        method=FrontierMethod.RISK_AVERSION_GRID),))
    requests = requests_for(problem, workload, int(sys.argv[3]), seed=21)
    executor = FaultyExecutor(config, snapshot_of(problem), fault_config(2, 1),
                              spec=FaultSpec(delay=float(sys.argv[4])))
    executor.run(requests, journal=JournalSpec(Path(sys.argv[2])))

if __name__ == "__main__":
    main()
"""


def _spawn_coordinator(
    tmp_path: Path, journal: Path, n: int, delay: float, name: str
) -> subprocess.Popen[bytes]:
    script = tmp_path / f"coordinator_{name}.py"
    script.write_text(COORDINATOR_SCRIPT, encoding="utf-8")
    scratch = tmp_path / f"tmp_{name}"
    scratch.mkdir(exist_ok=True)
    env = {**os.environ, "TEMP": str(scratch), "TMP": str(scratch), "TMPDIR": str(scratch)}
    return subprocess.Popen(
        [sys.executable, str(script), str(REPO_ROOT), str(journal), str(n), str(delay)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for(condition: Any, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.2)
    return False


def test_killing_the_coordinator_mid_run_and_resuming_equals_an_uninterrupted_run(
    tmp_path: Path, problem: Any, snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    """C-12: matar el coordinador a mitad y reanudar ⇒ idéntico a la ejecución ininterrumpida."""
    journal = tmp_path / "j"
    process = _spawn_coordinator(tmp_path, journal, N_REQUESTS, 1.5, "a")
    try:
        shards = journal / "shards"
        assert _wait_for(lambda: shards.is_dir() and len(list(shards.glob("s-*.json"))) >= 2, 240.0)
    finally:
        process.kill()
        process.wait()
    done_before = len(list((journal / "shards").glob("s-*.json")))
    assert 2 <= done_before < N_REQUESTS  # murió a mitad
    sequential = SequentialExecutor(CONFIG, snapshot).run(requests)
    run = ParallelExecutor(CONFIG, snapshot, fault_config(2, 1)).run(
        requests, journal=JournalSpec(journal, resume=True)
    )
    _assert_matches(run, sequential)
    assert run.accounting is not None and run.accounting.resumed >= done_before
    assert run.journal_scan is not None and run.journal_scan.corrupt_shards == ()
    # El coordinador muerto no pudo limpiar: sus restos se detectan y se eliminan (L-3).
    scratch = tmp_path / "tmp_a"

    def cleaned() -> bool:
        remove_orphans(inventory_orphans(scratch, min_age_seconds=0.0))
        return not [p for p in scratch.iterdir() if p.name.startswith(RUN_DIR_PREFIX)]

    assert _wait_for(cleaned, 60.0)


def test_two_simultaneous_coordinators_with_separate_journals_do_not_collide(
    tmp_path: Path, problem: Any, snapshot: Any
) -> None:
    n = 3
    reqs = requests_for(problem, WORKLOAD, n, seed=21)
    reference = SequentialExecutor(CONFIG, snapshot).run(reqs)
    first = _spawn_coordinator(tmp_path, tmp_path / "one", n, 0.0, "one")
    second = _spawn_coordinator(tmp_path, tmp_path / "two", n, 0.0, "two")
    assert first.wait(timeout=420) == 0 and second.wait(timeout=420) == 0
    for name in ("one", "two"):
        info = inspect_journal(tmp_path / name)
        assert info["complete"] is True and info["restorable_records"] == n
    for name in ("one", "two"):
        run = ParallelExecutor(CONFIG, snapshot, fault_config(1, 1)).run(
            reqs, journal=JournalSpec(tmp_path / name, resume=True)
        )
        _assert_matches(run, reference)
        assert run.accounting is not None and run.accounting.resumed == n
    assert json.dumps(inspect_journal(tmp_path / "one")["identity"]["request_set_hash"])
