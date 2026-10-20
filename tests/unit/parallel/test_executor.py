"""PAR-001, PAR-008, PAR-010…013: ``SequentialExecutor`` y ``ParallelExecutor`` (procesos reales).

Los pools usan ``spawn`` (el método que existe en Windows y Linux) con pocos workers y carteras
sintéticas pequeñas. Cubre: orden e identidad, número de workers, errores individuales, caída de un
worker, cierre limpio de procesos, restauración del entorno y límite de hilos dentro del worker.
"""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import random
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any

import pytest

from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.models.portfolio import CurrentPortfolioState
from portfolio_engine.models.universe_index import AssetIndex
from portfolio_engine.parallel import worker as worker_module
from portfolio_engine.parallel.batching import ParallelExecutionError
from portfolio_engine.parallel.executor import ParallelExecutor, RunResult, SequentialExecutor
from portfolio_engine.parallel.shared_data import (
    WorkerBundle,
    load_worker_bundle,
    worker_bundle,
    write_worker_bundle,
)
from portfolio_engine.parallel.task import ExecutionContext, ExecutionStatus, PortfolioRequest
from portfolio_engine.parallel.worker import initialize_worker, worker_diagnostics
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import (
    compare_results,
    parallel_config,
    requests_for,
    snapshot_of,
)
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
BAD = WorkloadSpec((OperationSpec(OperationKind.STRATEGY_VOL_TARGET, CostTreatment.GROSS),))


@pytest.fixture(scope="module")
def problem() -> Any:
    return random_problem(8, [0, 1, 2], 3, CONFIG)


@pytest.fixture(scope="module")
def snapshot(problem: Any) -> Any:
    return snapshot_of(problem)


@pytest.fixture(scope="module")
def requests(problem: Any) -> list[PortfolioRequest]:
    return requests_for(problem, WORKLOAD, 9, seed=21)


@pytest.fixture(scope="module")
def sequential(snapshot: Any, requests: list[PortfolioRequest]) -> RunResult:
    return SequentialExecutor(CONFIG, snapshot).run(requests)


def _assert_same_as_sequential(run: RunResult, reference: RunResult) -> None:
    assert [r.portfolio_id for r in run.results] == [r.portfolio_id for r in reference.results]
    assert [r.sequence_id for r in run.results] == list(range(len(reference.results)))
    for got, expected in zip(run.results, reference.results, strict=True):
        assert compare_results(expected, got).differences == [], got.portfolio_id


# ------------------------------------------------------------------------------ secuencial


def test_the_sequential_executor_orders_by_portfolio_id_and_records_the_run(
    sequential: RunResult, requests: list[PortfolioRequest]
) -> None:
    assert [r.portfolio_id for r in sequential.results] == sorted(r.portfolio_id for r in requests)
    assert [r.sequence_id for r in sequential.results] == list(range(len(requests)))
    assert all(r.execution_status is ExecutionStatus.COMPLETED for r in sequential.results)
    manifest = sequential.manifest
    assert manifest.mode == "SEQUENTIAL" and manifest.n_portfolios == len(requests)
    assert manifest.start_method is None and manifest.workers == 1
    assert dict(manifest.library_versions)["numpy"] != "NOT_INSTALLED"
    assert len(manifest.run_hash) == 64 and sequential.pool_rebuilds == 0


def test_the_sequential_executor_rejects_duplicate_ids(
    snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    with pytest.raises(ParallelExecutionError, match="duplicado"):
        SequentialExecutor(CONFIG, snapshot).run([*requests, requests[0]])


def test_an_empty_run_is_valid(snapshot: Any) -> None:
    run = SequentialExecutor(CONFIG, snapshot).run([])
    assert run.results == () and run.manifest.n_portfolios == 0


# --------------------------------------------------------------------------------- paralelo


def test_the_parallel_run_matches_the_sequential_reference_in_canonical_order(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    shuffled = list(requests)
    random.Random(4).shuffle(shuffled)
    run = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=2, batch_size=2)).run(shuffled)
    _assert_same_as_sequential(run, sequential)
    assert run.batches == 5 and run.pool_rebuilds == 0
    manifest = run.manifest
    assert manifest.mode == "PARALLEL" and manifest.workers == 2 and manifest.batch_size == 2
    assert manifest.start_method == "spawn" and manifest.blas_threads == 1
    assert manifest.config_hash == sequential.manifest.config_hash
    assert manifest.snapshot_key == sequential.manifest.snapshot_key
    assert manifest.run_hash != sequential.manifest.run_hash  # el modo forma parte del manifiesto


def test_work_is_done_by_the_configured_number_of_separate_processes(
    snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    run = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=2, batch_size=1)).run(requests)
    pids = {r.worker_pid for r in run.results}
    assert None not in pids and os.getpid() not in pids
    assert 1 <= len(pids) <= 2  # nunca más procesos que workers


def test_a_single_worker_runs_everything_in_one_process(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    run = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=1)).run(requests)
    assert len({r.worker_pid for r in run.results}) == 1
    _assert_same_as_sequential(run, sequential)


def test_processes_are_released_and_the_environment_is_restored(
    snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    environment = dict(os.environ)
    ParallelExecutor(CONFIG, snapshot, parallel_config(workers=2)).run(requests[:4])
    assert multiprocessing.active_children() == []
    assert dict(os.environ) == environment  # variables de hilos restauradas


def test_an_individual_failure_does_not_affect_other_portfolios(
    problem: Any, snapshot: Any, sequential: RunResult
) -> None:
    good = requests_for(problem, WORKLOAD, 4, seed=21, prefix="OK")
    invalid = requests_for(problem, BAD, 1, seed=3, prefix="BAD-ENGINE")
    index = AssetIndex.from_universe(problem.universe)
    no_workload = PortfolioRequest(
        "BAD-INPUT",
        CurrentPortfolioState.from_weights("BAD-INPUT", {}, index, None),
        None,
        WorkloadSpec(()),
    )
    empty = [no_workload]
    run = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=2, batch_size=3)).run(
        [*good, *invalid, *empty]
    )
    by_id = run.by_portfolio()
    assert by_id["BAD-ENGINE0000"].execution_status is ExecutionStatus.FAILED_EXCEPTION
    assert by_id["BAD-ENGINE0000"].error is not None
    assert by_id["BAD-ENGINE0000"].error.error_type == "UnsupportedCombinationError"
    assert by_id["BAD-INPUT"].execution_status is ExecutionStatus.FAILED_INPUT_VALIDATION
    assert all(by_id[r.portfolio_id].completed for r in good)
    reference = SequentialExecutor(CONFIG, snapshot).run([*good, *invalid, *empty])
    _assert_same_as_sequential(run, reference)


def test_results_are_independent_of_which_other_portfolios_share_the_batch(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """Sin contaminación: una cartera da el mismo resultado sola o en un lote grande."""
    alone = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=1, batch_size=1)).run(
        requests[:1]
    )
    together = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=1, batch_size=9)).run(
        requests
    )
    target = alone.results[0].portfolio_id
    mine = dataclasses.replace(together.by_portfolio()[target], sequence_id=0)
    assert compare_results(alone.results[0], mine).differences == []


# ------------------------------------------------------------------- hilos dentro del worker


def test_workers_limit_numeric_threads_to_the_configured_value(snapshot: Any) -> None:
    """PAR-007: dentro del worker cada librería numérica con hilos queda en 1 hilo."""
    from portfolio_engine.parallel.threading_control import worker_thread_environment

    with (
        worker_thread_environment(1),
        worker_bundle(ExecutionContext.create(CONFIG, snapshot)) as bundle,
        ProcessPoolExecutor(
            max_workers=1,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize_worker,
            initargs=(bundle, 1),
        ) as pool,
    ):
        diagnostics = pool.submit(worker_diagnostics).result()
    assert diagnostics.pid != os.getpid()
    assert diagnostics.blas_threads_configured == 1
    assert diagnostics.thread_pools, "threadpoolctl no detectó ninguna librería numérica"
    assert all(state.num_threads == 1 for state in diagnostics.thread_pools)
    assert dict(diagnostics.environment) == {
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }


# ------------------------------------------------------------------------ caída de un worker


def _die_once(flag: str, bundle: WorkerBundle, blas_threads: int) -> None:
    """Initializer de prueba: el primer worker que consume la bandera muere abruptamente."""
    initialize_worker(bundle, blas_threads)
    try:
        Path(flag).unlink()
    except FileNotFoundError:
        return
    os._exit(1)


class _CrashingExecutor(ParallelExecutor):
    """``ParallelExecutor`` cuyo primer pool pierde un worker (para probar la reconstrucción)."""

    def __init__(self, *args: Any, flag: Path, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._flag = str(flag)

    def _new_pool(self, bundle: WorkerBundle) -> ProcessPoolExecutor:
        parallel = self._parallel
        return ProcessPoolExecutor(
            max_workers=parallel.workers,
            mp_context=multiprocessing.get_context(parallel.start_method.value),
            initializer=_die_once,
            initargs=(self._flag, bundle, 1),
        )


def test_a_worker_crash_is_reported_and_the_run_continues(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    flag = tmp_path / "die-once.flag"
    flag.write_text("x", encoding="utf-8")
    executor = _CrashingExecutor(
        CONFIG, snapshot, parallel_config(workers=1, batch_size=3), flag=flag
    )
    run = executor.run(requests)
    statuses = [r.execution_status for r in run.results]
    assert len(run.results) == len(requests)  # exactamente un resultado por cartera
    assert [r.portfolio_id for r in run.results] == sorted(r.portfolio_id for r in requests)
    assert ExecutionStatus.WORKER_CRASHED in statuses
    assert run.pool_rebuilds >= 1
    crashed = [r for r in run.results if r.execution_status is ExecutionStatus.WORKER_CRASHED]
    assert all(r.error is not None and r.operations == () for r in crashed)
    assert all(s in {ExecutionStatus.COMPLETED, ExecutionStatus.WORKER_CRASHED} for s in statuses)
    assert ExecutionStatus.COMPLETED in statuses  # el pool reconstruido terminó el trabajo
    assert multiprocessing.active_children() == []


def _rendezvous_initializer(
    directory: str,
    poison: str,
    healthy: str,
    hold: float,
    bundle: WorkerBundle,
    blas_threads: int,
) -> None:
    """Initializer de prueba: la cartera ``poison`` mata a su worker cuando ``healthy`` ya corre.

    Determinista y sin tiempos frágiles: ambas tareas se esperan mediante ficheros-bandera (cita
    con plazo de 120 s que, si venciera, falla la prueba con un error explícito, nunca se cuelga).
    Así, cuando el worker de ``poison`` muere, ``healthy`` está **a mitad de tarea** en otro worker.
    """
    initialize_worker(bundle, blas_threads)
    root = Path(directory)
    real = worker_module.run_portfolio

    def patched(request: PortfolioRequest, context: ExecutionContext, **kwargs: Any) -> Any:
        portfolio_id = request.portfolio_id
        if portfolio_id not in (poison, healthy):
            return real(request, context, **kwargs)
        mine, other = ("poison", "healthy") if portfolio_id == poison else ("healthy", "poison")
        (root / f"{mine}.started").write_text("x", encoding="utf-8")
        deadline = time.monotonic() + 120.0
        while not (root / f"{other}.started").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("la cita entre las dos carteras de la prueba venció")
            time.sleep(0.02)
        if portfolio_id == poison:
            os._exit(1)
        time.sleep(hold)  # la cartera sana sigue «ejecutándose» durante ``hold`` segundos
        return real(request, context, **kwargs)

    worker_module.run_portfolio = patched  # type: ignore[assignment]


class _MidTaskCrashExecutor(ParallelExecutor):
    """``ParallelExecutor`` cuyos workers ejecutan la cita ``poison``/``healthy`` de la prueba.

    ``warm_up=True`` crea todos los workers y espera un resultado de cada uno **antes** de enviar
    trabajo. Motivo (observado, Windows / CPython 3.13.6): ``ProcessPoolExecutor`` crea los workers
    bajo demanda y el hilo gestor calcula su lista de *sentinels* antes de que el último worker
    exista; si muere precisamente el worker creado en último lugar, la caída puede no detectarse
    hasta el siguiente evento del pool (otro resultado o envío). Hasta entonces un vecino sano puede
    terminar con normalidad (``COMPLETED``) y es una cartera enviada después la que se pierde.
    Con ``warm_up=True`` la detección es inmediata y la semántica es la de «todos los lotes en
    vuelo»; con ``warm_up=False`` solo valen los invariantes del test no determinista.
    """

    def __init__(
        self,
        *args: Any,
        directory: Path,
        poison: str,
        healthy: str,
        hold: float,
        warm_up: bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._rendezvous = (str(directory), poison, healthy, hold)
        self._warm_up = warm_up

    def _new_pool(self, bundle: WorkerBundle) -> ProcessPoolExecutor:
        parallel = self._parallel
        pool = ProcessPoolExecutor(
            max_workers=parallel.workers,
            mp_context=multiprocessing.get_context(parallel.start_method.value),
            initializer=_rendezvous_initializer,
            initargs=(*self._rendezvous, bundle, parallel.blas_threads),
        )
        if self._warm_up:
            wait([pool.submit(os.getpid) for _ in range(parallel.workers)])
        return pool


@pytest.mark.parametrize(
    ("batch_size", "healthy_position", "crashed"),
    [(1, 1, 2), (2, 2, 4)],
    ids=["batch of 1", "batch of 2"],
)
def test_a_crash_mid_task_marks_every_in_flight_batch_as_worker_crashed(
    tmp_path: Path,
    snapshot: Any,
    requests: list[PortfolioRequest],
    sequential: RunResult,
    batch_size: int,
    healthy_position: int,
    crashed: int,
) -> None:
    """Semántica ACTUAL de ``WORKER_CRASHED`` en B5.2 (auditoría H-1), sin reintentos.

    Con 2 workers y 1 lote en vuelo por worker, una cartera mata a su worker mientras otra cartera
    sana corre en el otro. Un ``BrokenProcessPool`` invalida **todos los lotes en vuelo**, no solo
    el
    del worker caído: la cartera sana (y las que acompañan a ambas en sus lotes) quedan
    ``WORKER_CRASHED`` sin reintento y sin operaciones. Las carteras aún no enviadas se completan en
    el pool reconstruido y coinciden con la referencia secuencial (T1). Es un comportamiento a
    mejorar en B5.4 (reintento y cuarentena); si se mejora, esta prueba debe actualizarse.
    """
    ordered = sorted(r.portfolio_id for r in requests)
    config = dataclasses.replace(
        parallel_config(workers=2, batch_size=batch_size), max_in_flight_batches_per_worker=1
    )
    executor = _MidTaskCrashExecutor(
        CONFIG,
        snapshot,
        config,
        directory=tmp_path,
        poison=ordered[0],
        healthy=ordered[healthy_position],
        hold=120.0,  # la cartera sana sigue en ejecución hasta que el pool se rompe
        warm_up=True,
    )
    run = executor.run(requests)
    assert [r.portfolio_id for r in run.results] == ordered  # exactamente una vez, orden canónico
    statuses = [r.execution_status for r in run.results]
    assert statuses[:crashed] == [ExecutionStatus.WORKER_CRASHED] * crashed
    assert statuses[crashed:] == [ExecutionStatus.COMPLETED] * (len(ordered) - crashed)
    assert run.pool_rebuilds == 1
    healthy = run.results[healthy_position]  # víctima inocente: no causó la caída
    assert healthy.execution_status is ExecutionStatus.WORKER_CRASHED
    for victim in run.results[:crashed]:
        assert victim.operations == () and victim.worker_pid is None
        assert victim.error is not None and "no devolvió resultado" in victim.error.message
        assert victim.error.error_type == "BrokenProcessPool"
    for got, expected in zip(run.results[crashed:], sequential.results[crashed:], strict=True):
        assert compare_results(expected, got).differences == [], got.portfolio_id
    assert multiprocessing.active_children() == []


def test_a_crash_without_warm_up_keeps_exactly_once_and_bounded_damage(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """Invariantes que valen aunque la detección de la caída se retrase (sin ``warm_up``).

    No fija qué vecino sano resulta afectado (depende de cuándo detecta el pool la caída), solo lo
    que debe cumplirse siempre: una salida por cartera en orden canónico, la cartera culpable y
    su lote perdidos, daño máximo igual al de los lotes en vuelo, y toda cartera ``COMPLETED``
    idéntica a la referencia secuencial (T1). Sin esperas por tiempo: la cartera sana retiene su
    worker 2 s y la prueba termina cuando termina el pool.
    """
    ordered = sorted(r.portfolio_id for r in requests)
    config = dataclasses.replace(
        parallel_config(workers=2, batch_size=1), max_in_flight_batches_per_worker=1
    )
    run = _MidTaskCrashExecutor(
        CONFIG,
        snapshot,
        config,
        directory=tmp_path,
        poison=ordered[0],
        healthy=ordered[1],
        hold=2.0,
        warm_up=False,
    ).run(requests)
    assert [r.portfolio_id for r in run.results] == ordered
    by_id = run.by_portfolio()
    assert by_id[ordered[0]].execution_status is ExecutionStatus.WORKER_CRASHED  # la culpable
    crashed = [r for r in run.results if r.execution_status is ExecutionStatus.WORKER_CRASHED]
    assert 1 <= len(crashed) <= config.max_in_flight_batches + 1  # lotes en vuelo (+ envío tardío)
    assert run.pool_rebuilds >= 1
    for result in run.results:
        if result.execution_status is ExecutionStatus.COMPLETED:
            expected = dataclasses.replace(
                sequential.by_portfolio()[result.portfolio_id], worker_pid=None
            )
            got = dataclasses.replace(result, worker_pid=None)
            assert compare_results(expected, got).differences == [], result.portfolio_id
        else:
            assert result.execution_status is ExecutionStatus.WORKER_CRASHED
            assert result.operations == () and result.error is not None
            assert result.error.error_type == "BrokenProcessPool"
    assert multiprocessing.active_children() == []


# --------------------------------------------------------------------------- configuración


def test_an_unavailable_start_method_is_rejected_up_front(
    snapshot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(multiprocessing, "get_all_start_methods", lambda: ["spawn"])
    from portfolio_engine.config import ProcessStartMethod

    config = parallel_config(start_method=ProcessStartMethod.FORKSERVER)
    with pytest.raises(ParallelExecutionError, match="no está disponible"):
        ParallelExecutor(CONFIG, snapshot, config)


# ----------------------------------------------------- granularidad, reutilización y planificación


def test_each_portfolio_runs_whole_in_one_worker_reusing_the_solver_workspace(
    snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    """PAR-001/002: la tarea es la cartera; los puntos de una frontera no se reparten.

    El workspace del solver se reutiliza dentro del worker (menos ``setup`` que ``solve``),
    exactamente como en la ejecución secuencial (SOL-009).
    """
    run = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=2, batch_size=1)).run(requests)
    sequential_diagnostics = {
        r.portfolio_id: r.operations[0].result.diagnostics  # type: ignore[union-attr]
        for r in SequentialExecutor(CONFIG, snapshot).run(requests).results
    }
    for result in run.results:
        diagnostics = result.operations[0].result.diagnostics  # type: ignore[union-attr]
        assert result.worker_pid is not None
        assert 1 <= diagnostics.setup_count < diagnostics.solve_count
        expected = sequential_diagnostics[result.portfolio_id]
        assert (diagnostics.setup_count, diagnostics.solve_count, diagnostics.update_count) == (
            expected.setup_count,
            expected.solve_count,
            expected.update_count,
        )


def test_task_payload_is_small_and_independent_of_the_universe_size() -> None:
    """PAR-005: la solicitud no transporta matrices globales (viajan una vez por worker)."""
    import pickle

    sizes = {}
    for assets in (20, 100):
        problem = random_problem(assets, [0, 1, 2], 3, CONFIG)
        request = requests_for(problem, WORKLOAD, 1, seed=1)[0]
        sigma_bytes = int(problem.risk_model.sigma.nbytes)
        payload = len(pickle.dumps(request, protocol=5))
        sizes[assets] = (payload, sigma_bytes)
    small, large = sizes[20], sizes[100]
    assert large[1] > 20 * small[1]  # Σ crece con el universo…
    assert large[0] < large[1] / 10  # …y la solicitud es una fracción pequeña de Σ
    assert large[0] <= small[0] * 1.5  # …y no crece con el universo


class _Tracker:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int]] = []  # (índice de envío, no terminados, terminados)
        self.futures: list[Any] = []


class _TrackingPool(ProcessPoolExecutor):
    def __init__(self, tracker: _Tracker, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tracker = tracker

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        tracker = self._tracker
        done = sum(1 for future in tracker.futures if future.done())
        pending = len(tracker.futures) - done
        tracker.events.append((len(tracker.futures), pending, done))
        future = super().submit(fn, *args, **kwargs)
        tracker.futures.append(future)
        return future


class _TrackedExecutor(ParallelExecutor):
    def __init__(self, *args: Any, tracker: _Tracker, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tracker = tracker

    def _new_pool(self, bundle: WorkerBundle) -> ProcessPoolExecutor:
        parallel = self._parallel
        return _TrackingPool(
            self._tracker,
            max_workers=parallel.workers,
            mp_context=multiprocessing.get_context(parallel.start_method.value),
            initializer=initialize_worker,
            initargs=(bundle, parallel.blas_threads),
        )


def test_scheduling_is_dynamic_and_the_queue_is_bounded(
    snapshot: Any, requests: list[PortfolioRequest], sequential: RunResult
) -> None:
    """PAR-011, P-02: envío dinámico por lotes y nunca más del límite de lotes en vuelo."""
    tracker = _Tracker()
    config = parallel_config(workers=1, batch_size=1, max_in_flight_batches_per_worker=2)
    run = _TrackedExecutor(CONFIG, snapshot, config, tracker=tracker).run(requests)
    assert len(tracker.events) == len(requests) == 9  # un envío por lote, todos enviados
    limit = config.max_in_flight_batches
    assert limit == 2
    assert max(pending for _, pending, _ in tracker.events) <= limit - 1  # antes de cada envío
    # Mientras no ha terminado ninguno, se envían como mucho ``limit`` lotes (cola acotada).
    assert all(index < limit for index, _, done in tracker.events if done == 0)
    # El resto se envía de forma dinámica, tras terminar lotes anteriores.
    assert any(done > 0 for _, _, done in tracker.events)
    _assert_same_as_sequential(run, sequential)


# ------------------------------------------------------------- fichero de arranque de los workers


def test_the_bundle_round_trips_and_its_reference_is_tiny(snapshot: Any) -> None:
    """Los argumentos de arranque deben caber en el búfer de un pipe (véase worker.py)."""
    import pickle

    context = ExecutionContext.create(CONFIG, snapshot)
    with worker_bundle(context) as bundle:
        assert Path(bundle.path).is_file()
        restored = load_worker_bundle(bundle)
        assert restored.snapshot_key == context.snapshot_key == snapshot.snapshot_key
        assert restored.config_hash == context.config_hash
        assert restored.config == CONFIG
        assert len(pickle.dumps(bundle)) < 1024  # una ruta y un hash, no los datos
    assert not Path(bundle.path).exists()  # el directorio temporal se elimina siempre


def test_a_tampered_bundle_is_rejected_before_unpickling(tmp_path: Path, snapshot: Any) -> None:
    bundle = write_worker_bundle(tmp_path, ExecutionContext.create(CONFIG, snapshot))
    Path(bundle.path).write_bytes(Path(bundle.path).read_bytes() + b"x")
    with pytest.raises(RuntimeError, match="hash"):
        load_worker_bundle(bundle)


def test_the_temporary_bundle_directory_is_removed_after_success_and_failure(
    tmp_path: Path,
    snapshot: Any,
    requests: list[PortfolioRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    ParallelExecutor(CONFIG, snapshot, parallel_config(workers=1)).run(requests[:2])
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ParallelExecutionError):  # id duplicado: falla antes de crear nada
        ParallelExecutor(CONFIG, snapshot, parallel_config(workers=1)).run(
            [*requests[:2], requests[0]]
        )
    assert list(tmp_path.iterdir()) == []


def test_the_integrity_check_detects_lost_duplicated_and_swapped_results(
    sequential: RunResult, requests: list[PortfolioRequest]
) -> None:
    """P-03 (propuesto): cada cartera aparece exactamente una vez y con su identidad."""
    import dataclasses as dc

    from portfolio_engine.parallel.batching import canonical_order
    from portfolio_engine.parallel.executor import _verify_exactly_once

    items = canonical_order(requests)
    results = list(sequential.results)
    assert _verify_exactly_once(items, list(reversed(results))) == tuple(results)  # reordena
    with pytest.raises(ParallelExecutionError, match="pérdida o duplicación"):
        _verify_exactly_once(items, results[:-1])  # perdido
    with pytest.raises(ParallelExecutionError, match="pérdida o duplicación"):
        _verify_exactly_once(items, [*results[:-1], results[0]])  # duplicado
    swapped = dc.replace(results[1], portfolio_id=results[0].portfolio_id)
    with pytest.raises(ParallelExecutionError, match="pertenece a"):
        _verify_exactly_once(items, [results[0], swapped, *results[2:]])  # identidad cruzada


def test_a_worker_crash_leaves_no_temporary_run_directories(
    tmp_path: Path,
    snapshot: Any,
    requests: list[PortfolioRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L-3: tras una caída de worker (Windows retiene manejadores un instante) no quedan restos."""
    from portfolio_engine.parallel.shared_data import RUN_DIR_PREFIX, inventory_orphans

    flag = tmp_path / "die-once.flag"
    flag.write_text("x", encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    run = _CrashingExecutor(
        CONFIG, snapshot, parallel_config(workers=1, batch_size=3), flag=flag
    ).run(requests)
    assert any(r.execution_status is ExecutionStatus.WORKER_CRASHED for r in run.results)
    assert [p for p in tmp_path.iterdir() if p.name.startswith(RUN_DIR_PREFIX)] == []
    assert inventory_orphans(tmp_path, min_age_seconds=0.0).empty
