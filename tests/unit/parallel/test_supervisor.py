"""P-03, P-04, P-06, D-DET: política del supervisor con un pool simulado (sin procesos reales).

El pool simulado resuelve cada lote según un guion: ``ok``, ``crash`` (el pool se rompe y la marca
de progreso señala una posición), ``hang`` (el futuro queda pendiente hasta que el pool se rompe o
se cierra) o ``init_error``. Así se prueban las reglas de cuarentena, intentos, cotas, plazos y
cancelación de forma rápida y determinista; las pruebas con procesos reales están en
``test_recovery.py``. Nunca se termina un proceso real: ``terminate_process`` se sustituye.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

import pytest

from portfolio_engine.config.parallel_config import RecoveryConfig
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.parallel import supervisor as supervisor_module
from portfolio_engine.parallel.batching import PortfolioBatch, SequencedRequest, canonical_order
from portfolio_engine.parallel.protocols import CancellationToken
from portfolio_engine.parallel.supervisor import BatchSupervisor, SupervisorHooks
from portfolio_engine.parallel.task import ExecutionStatus, PortfolioRequest, TaskResult
from portfolio_engine.parallel.worker import ResultBatch, WorkerInitializationError
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import requests_for
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

FAKE_PID = 4_000_000
Action = tuple[Any, ...]
OK: Action = ("ok",)


def _policy(**changes: Any) -> RecoveryConfig:
    base: dict[str, Any] = {
        "max_task_attempts": 2,
        "max_rebuilds_without_progress": 3,
        "max_total_rebuilds": 30,
        "supervision_poll_seconds": 0.01,
        "task_timeout_seconds": None,
        "batch_timeout_seconds": None,
        "cancel_grace_seconds": 0.05,
        "journal_enabled": False,
        "max_message_chars": 120,
    }
    return RecoveryConfig(**{**base, **changes})


class FakePool:
    """Pool simulado que resuelve los lotes según ``script(pool_index, batch)``."""

    def __init__(self, index: int, script: Callable[[int, PortfolioBatch], Action], root: Path):
        self.index = index
        self.script = script
        self.root = root
        self.broken = False
        self.closed = False
        self.waiting: list[Future[ResultBatch]] = []

    def submit_batch(self, batch: PortfolioBatch) -> Future[ResultBatch]:
        if self.broken or self.closed:
            raise BrokenProcessPool("pool roto")
        future: Future[ResultBatch] = Future()
        action = self.script(self.index, batch)
        kind = action[0]
        if kind == "ok":
            future.set_result(_result_batch(batch))
        elif kind == "init_error":
            future.set_exception(WorkerInitializationError(action[1]))
        elif kind == "crash":
            self._mark(batch, action[1])
            future.set_exception(BrokenProcessPool("worker muerto"))
            self._break()
        elif kind == "hang":
            if len(action) > 1:
                self._mark(batch, action[1])
            self.waiting.append(future)
        else:  # pragma: no cover - guion mal escrito
            raise AssertionError(action)
        return future

    def _mark(self, batch: PortfolioBatch, position: int) -> None:
        (self.root / f"t.{batch.batch_id}.{position}.{FAKE_PID}").touch()

    def _break(self) -> None:
        self.broken = True
        for future in self.waiting:
            if not future.done():
                future.set_exception(BrokenProcessPool("pool roto"))
        self.waiting.clear()

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self.closed = True
        self._break()


def _result_batch(batch: PortfolioBatch) -> ResultBatch:
    results = tuple(_completed(item) for item in batch.items)
    return ResultBatch(batch.batch_id, results, FAKE_PID, 0.0)


def _completed(item: SequencedRequest) -> TaskResult:
    return TaskResult(
        task_id=_task_id(item.request),
        portfolio_id=item.request.portfolio_id,
        workload_hash=item.request.workload.workload_hash,
        sequence_id=item.sequence_id,
        execution_status=ExecutionStatus.COMPLETED,
        operations=(),
        error=None,
        elapsed_seconds=0.0,
        worker_pid=FAKE_PID,
    )


def _task_id(request: PortfolioRequest) -> str:
    return f"task-{request.portfolio_id}"


@pytest.fixture(scope="module")
def items() -> tuple[SequencedRequest, ...]:
    config = base_config()
    problem = random_problem(8, [0, 1, 2], 3, config)
    workload = WorkloadSpec(
        (OperationSpec(OperationKind.STRATEGY_MAX_SHARPE, CostTreatment.GROSS),)
    )
    return canonical_order(requests_for(problem, workload, 9, seed=3))


class Harness:
    """Ejecuta el supervisor con un guion y recoge lo que entrega."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        script: Callable[[int, PortfolioBatch], Action],
        policy: RecoveryConfig,
        control: CancellationToken | None = None,
        max_in_flight: int = 4,
    ) -> None:
        self.results: list[TaskResult] = []
        self.pools: list[FakePool] = []
        self.terminated: list[int] = []
        self.events: list[tuple[str, str]] = []
        monkeypatch.setattr(
            supervisor_module.markers, "terminate_process", lambda pid: self.terminated.append(pid)
        )

        def new_pool() -> Any:
            pool = FakePool(len(self.pools), script, tmp_path)
            self.pools.append(pool)
            return pool

        hooks = SupervisorHooks(
            new_pool=new_pool,
            submit=lambda pool, batch: pool.submit_batch(batch),
            task_id=_task_id,
            on_batch=lambda outcome: self.results.extend(outcome.results),
            on_final=lambda results: self.results.extend(results),
            report=lambda kind, detail: self.events.append((kind, detail)),
        )
        self.supervisor = BatchSupervisor(hooks, policy, max_in_flight, tmp_path, control)

    def run(self, batches: list[PortfolioBatch]) -> Any:
        report = self.supervisor.run(batches)
        self.report = report
        return report

    def statuses(self) -> dict[int, ExecutionStatus]:
        found = {r.sequence_id: r.execution_status for r in self.results}
        assert len(found) == len(self.results), "una tarea con más de un resultado final"
        return found  # type: ignore[return-value]


def _batches(items: tuple[SequencedRequest, ...], size: int) -> list[PortfolioBatch]:
    return [
        PortfolioBatch(index, items[start : start + size])
        for index, start in enumerate(range(0, len(items), size))
    ]


def _contains(batch: PortfolioBatch, sequence_id: int) -> int | None:
    for position, item in enumerate(batch.items):
        if item.sequence_id == sequence_id:
            return position
    return None


# ------------------------------------------------------------------------------ caídas


def test_only_the_poison_task_fails_and_every_neighbour_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    poison = 1

    def script(pool: int, batch: PortfolioBatch) -> Action:
        position = _contains(batch, poison)
        if position is not None:
            return ("crash", position)
        if batch.batch_id == 1 and pool == 0:
            return ("hang", 0)  # víctima inocente en vuelo cuando muere el otro worker
        return OK

    harness = Harness(tmp_path, monkeypatch, script, _policy())
    report = harness.run(_batches(items, 3))
    statuses = harness.statuses()
    assert set(statuses) == {item.sequence_id for item in items}  # exactamente una vez
    assert statuses.pop(poison) is ExecutionStatus.WORKER_CRASHED
    assert set(statuses.values()) == {ExecutionStatus.COMPLETED}
    assert report.poisoned_tasks == 1 and report.isolated_retries == 2  # max_task_attempts
    assert report.pool_rebuilds >= 3 and not report.aborted
    failed = next(r for r in harness.results if r.sequence_id == poison)
    assert failed.error is not None and failed.error.error_type == "WorkerCrashed"
    assert harness.terminated  # los workers se terminaron por PID registrado en marcas


def test_a_transient_crash_is_retried_in_isolation_and_nobody_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    """Un kill externo (OOM, usuario) a mitad de tarea no convierte la cartera en fallida."""

    def script(pool: int, batch: PortfolioBatch) -> Action:
        position = _contains(batch, 4)
        if pool == 0 and position is not None and len(batch.items) > 1:
            return ("crash", position)
        return OK

    harness = Harness(tmp_path, monkeypatch, script, _policy())
    report = harness.run(_batches(items, 3))
    assert set(harness.statuses().values()) == {ExecutionStatus.COMPLETED}
    assert report.poisoned_tasks == 0 and report.isolated_retries == 1
    assert report.recovery_seconds >= 0.0


def test_a_crash_with_no_mark_blames_nobody_and_hits_the_progress_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    """Un worker que muere antes de empezar tareas, siempre: no hay bucle infinito (M-1)."""

    def script(pool: int, batch: PortfolioBatch) -> Action:
        raise BrokenProcessPool("initializer que mata el proceso")

    harness = Harness(tmp_path, monkeypatch, script, _policy())
    report = harness.run(_batches(items, 3))
    statuses = harness.statuses()
    assert set(statuses.values()) == {ExecutionStatus.ABORTED}
    assert len(statuses) == len(items) and report.aborted
    assert report.pool_rebuilds == 3  # max_rebuilds_without_progress
    assert all(
        r.error is not None and "puede reintentarse" in r.error.message for r in harness.results
    )


def test_when_every_task_kills_its_worker_the_run_aborts_instead_of_poisoning_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    """Un entorno que mata a todo proceso (p. ej. librería nativa rota) no recorre las N tareas."""

    def script(pool: int, batch: PortfolioBatch) -> Action:
        return ("crash", 0)

    harness = Harness(tmp_path, monkeypatch, script, _policy())
    report = harness.run(_batches(items, 3))
    counts = Counter(harness.statuses().values())
    assert counts[ExecutionStatus.WORKER_CRASHED] == 3  # max_rebuilds_without_progress
    assert counts[ExecutionStatus.ABORTED] == len(items) - 3
    assert report.aborted and report.poisoned_tasks == 3
    assert sum(counts.values()) == len(items)


def test_a_consistently_failing_initializer_ends_as_worker_init_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    def script(pool: int, batch: PortfolioBatch) -> Action:
        return ("init_error", "SharedDataError: hash incorrecto")

    harness = Harness(tmp_path, monkeypatch, script, _policy())
    report = harness.run(_batches(items, 3))
    assert set(harness.statuses().values()) == {ExecutionStatus.WORKER_INIT_FAILED}
    assert report.init_failures >= 3 and report.aborted
    assert report.pool_rebuilds == 3
    sample = harness.results[0].error
    assert sample is not None and "hash incorrecto" in sample.message
    assert sample.error_type == "WorkerInitializationError"


def test_a_transient_initializer_failure_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    def script(pool: int, batch: PortfolioBatch) -> Action:
        return ("init_error", "fallo transitorio") if pool == 0 else OK

    harness = Harness(tmp_path, monkeypatch, script, _policy())
    harness.run(_batches(items, 3))
    assert set(harness.statuses().values()) == {ExecutionStatus.COMPLETED}


def test_a_pool_broken_during_submit_loses_no_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    """Se captura ``BrokenProcessPool`` también en ``submit``; el lote no enviado no se pierde."""

    def script(pool: int, batch: PortfolioBatch) -> Action:
        if pool == 0 and batch.batch_id == 0:
            return ("crash", 0)  # rompe el pool: los envíos siguientes fallan en submit
        return OK

    harness = Harness(tmp_path, monkeypatch, script, _policy())
    harness.run(_batches(items, 3))
    assert set(harness.statuses().values()) == {ExecutionStatus.COMPLETED}
    assert any(kind == "submit_broken" for kind, _ in harness.events)


def test_progress_resets_the_consecutive_limit_but_the_total_limit_still_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    def script(pool: int, batch: PortfolioBatch) -> Action:
        if len(batch.items) == 3 and pool < 5:  # cada pool nuevo completa algo y vuelve a caer
            return ("crash", 0) if batch.batch_id == 2 else OK
        return OK

    harness = Harness(tmp_path, monkeypatch, script, _policy(max_rebuilds_without_progress=2))
    report = harness.run(_batches(items, 3))
    assert not report.aborted
    assert set(harness.statuses().values()) == {ExecutionStatus.COMPLETED}

    def always(pool: int, batch: PortfolioBatch) -> Action:
        position = _contains(batch, 0)
        return OK if position is None else ("crash", position)

    bounded = Harness(
        tmp_path, monkeypatch, always, _policy(max_total_rebuilds=2, max_task_attempts=5)
    )
    report = bounded.run(_batches(items, 3))
    assert report.aborted and report.pool_rebuilds == 2
    assert ExecutionStatus.ABORTED in bounded.statuses().values()
    assert len(bounded.statuses()) == len(items)


@pytest.mark.parametrize("seed", range(12))
def test_random_crash_patterns_keep_exactly_once_and_blame_only_the_poison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    items: tuple[SequencedRequest, ...],
    seed: int,
) -> None:
    """Adversarial: tareas venenosas y caídas transitorias al azar; el invariante de conteo vale."""
    rng = random.Random(seed)
    poison = set(rng.sample(range(len(items)), rng.randint(0, 3)))
    flaky = {i for i in range(len(items)) if i not in poison and rng.random() < 0.3}
    flaked: set[int] = set()

    def script(pool: int, batch: PortfolioBatch) -> Action:
        for position, item in enumerate(batch.items):
            sequence = item.sequence_id
            if sequence in poison:
                return ("crash", position)
            if sequence in flaky and sequence not in flaked:
                flaked.add(sequence)
                return ("crash", position)
        return OK

    harness = Harness(
        tmp_path,
        monkeypatch,
        script,
        _policy(max_rebuilds_without_progress=20, max_total_rebuilds=200),
    )
    size = rng.randint(1, 4)
    report = harness.run(_batches(items, size))
    statuses = harness.statuses()
    assert set(statuses) == {item.sequence_id for item in items}
    crashed = {s for s, status in statuses.items() if status is ExecutionStatus.WORKER_CRASHED}
    assert crashed == poison
    assert Counter(statuses.values()).keys() <= {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.WORKER_CRASHED,
    }
    assert report.poisoned_tasks == len(poison) and not report.aborted


# --------------------------------------------------------------------------- D-DET


def test_a_vanished_worker_is_detected_without_waiting_for_the_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    """D-DET: el pool no avisa (futuro pendiente); la vigilancia de PID detecta la caída."""
    (tmp_path / f"w.{FAKE_PID}").touch()
    dead = {"now": False}

    def script(pool: int, batch: PortfolioBatch) -> Action:
        if pool == 0 and batch.batch_id == 0:
            dead["now"] = True
            return ("hang", 0)  # el worker «creado en último lugar» murió sin que el pool lo note
        return OK

    monkeypatch.setattr(
        supervisor_module.markers,
        "process_is_gone",
        lambda pid: dead["now"] and pid == FAKE_PID,
    )
    harness = Harness(tmp_path, monkeypatch, script, _policy())

    original_clear = supervisor_module.markers.clear

    def clear_and_revive(directory: Path) -> None:
        original_clear(directory)
        dead["now"] = False  # el pool nuevo tiene workers sanos

    monkeypatch.setattr(supervisor_module.markers, "clear", clear_and_revive)
    harness.run(_batches(items, 3))
    assert any(kind == "worker_vanished" for kind, _ in harness.events)
    assert set(harness.statuses().values()) == {ExecutionStatus.COMPLETED}
    assert len(harness.results) == len(items)  # ninguna tarea pendiente se perdió


# --------------------------------------------------------------------------- plazos


def test_a_task_over_its_deadline_is_timed_out_and_neighbours_are_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    def script(pool: int, batch: PortfolioBatch) -> Action:
        position = _contains(batch, 1)
        if position is not None:
            return ("hang", position)  # esta cartera nunca termina
        if batch.batch_id == 1 and pool == 0:
            return ("hang", 0)  # inocente en otro worker: se recalcula
        return OK

    harness = Harness(tmp_path, monkeypatch, script, _policy(task_timeout_seconds=0.05))
    report = harness.run(_batches(items, 3))
    statuses = harness.statuses()
    assert statuses.pop(1) is ExecutionStatus.TIMED_OUT
    assert set(statuses.values()) == {ExecutionStatus.COMPLETED}
    assert report.timeouts == 1 and report.poisoned_tasks == 0
    timed_out = next(r for r in harness.results if r.sequence_id == 1)
    assert timed_out.error is not None and timed_out.error.error_type == "TaskTimeout"
    assert "TASK" in timed_out.error.message and "0.05" in timed_out.error.message


def test_a_slow_multi_task_batch_is_split_and_only_a_hanging_task_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    """Plazo de lote: nadie falla por compartir lote lento; la que de verdad cuelga, sí."""

    def script(pool: int, batch: PortfolioBatch) -> Action:
        if len(batch.items) > 1 and _contains(batch, 0) is not None:
            return ("hang", 1)  # el lote entero supera el plazo
        position = _contains(batch, 2)
        if position is not None and len(batch.items) == 1:
            return ("hang", 0)  # la 2 cuelga también sola: ésta sí es culpable
        return OK

    harness = Harness(tmp_path, monkeypatch, script, _policy(batch_timeout_seconds=0.05))
    report = harness.run(_batches(items, 3))
    statuses = harness.statuses()
    assert statuses.pop(2) is ExecutionStatus.TIMED_OUT
    assert set(statuses.values()) == {ExecutionStatus.COMPLETED}
    assert report.batches_split >= 1 and report.timeouts == 1
    error = next(r.error for r in harness.results if r.sequence_id == 2)
    assert error is not None and error.error_type == "BatchTimeout"


# ----------------------------------------------------------------------- cancelación


def test_cancellation_keeps_completed_work_and_cancels_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    token = CancellationToken()

    def script(pool: int, batch: PortfolioBatch) -> Action:
        if batch.batch_id == 0:
            return OK
        if batch.batch_id == 1:
            token.cancel()  # se pide cancelar con el lote 1 en vuelo
            return ("hang", 0)
        return OK

    harness = Harness(tmp_path, monkeypatch, script, _policy(), control=token, max_in_flight=2)
    report = harness.run(_batches(items, 3))
    statuses = harness.statuses()
    assert {statuses[i] for i in (0, 1, 2)} == {ExecutionStatus.COMPLETED}  # lote 0 conservado
    rest = {statuses[i.sequence_id] for i in items[3:]}
    assert rest == {ExecutionStatus.CANCELLED}  # en vuelo (colgado) y sin enviar
    assert report.cancelled and len(statuses) == len(items)
    assert harness.terminated  # tras la gracia se termina al worker que no acabó
    assert harness.pools[0].closed


def test_cancellation_grace_lets_in_flight_batches_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    token = CancellationToken()
    holder: dict[str, Any] = {}

    def script(pool: int, batch: PortfolioBatch) -> Action:
        if batch.batch_id == 0:
            token.cancel()
            return ("hang",)
        return OK

    harness = Harness(
        tmp_path,
        monkeypatch,
        script,
        _policy(cancel_grace_seconds=2.0),
        control=token,
        max_in_flight=2,
    )
    original = harness.supervisor._hooks.submit

    def submit(pool: FakePool, batch: PortfolioBatch) -> Future[ResultBatch]:
        future = original(pool, batch)
        if batch.batch_id == 0:
            holder["future"] = future
            future.set_result(_result_batch(batch))  # termina dentro de la gracia
            pool.waiting.clear()
        return future

    harness.supervisor._hooks = SupervisorHooks(
        new_pool=harness.supervisor._hooks.new_pool,
        submit=submit,
        task_id=_task_id,
        on_batch=harness.supervisor._hooks.on_batch,
        on_final=harness.supervisor._hooks.on_final,
        report=harness.supervisor._hooks.report,
    )
    report = harness.run(_batches(items, 3))
    statuses = harness.statuses()
    assert {statuses[i] for i in range(6)} == {ExecutionStatus.COMPLETED}  # lo en vuelo se conserva
    assert {statuses[i.sequence_id] for i in items[6:]} == {ExecutionStatus.CANCELLED}  # sin enviar
    assert report.cancelled and not harness.terminated


def test_a_cancellation_requested_before_starting_cancels_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    token = CancellationToken()
    token.cancel()
    harness = Harness(tmp_path, monkeypatch, lambda p, b: OK, _policy(), control=token)
    harness.run(_batches(items, 3))
    assert set(harness.statuses().values()) == {ExecutionStatus.CANCELLED}
    assert harness.pools == []  # ni siquiera se creó un pool


def test_event_details_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: tuple[SequencedRequest, ...]
) -> None:
    long_message = "x" * 5000

    def script(pool: int, batch: PortfolioBatch) -> Action:
        return ("init_error", long_message)

    harness = Harness(tmp_path, monkeypatch, script, _policy(max_message_chars=50))
    harness.run(_batches(items, 3))
    assert all(len(detail) <= 50 for _, detail in harness.events)
    assert all(r.error is not None and len(r.error.message) <= 50 for r in harness.results)
