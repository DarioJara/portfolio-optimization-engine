"""Ejecutores secuencial y paralelo de lotes de carteras (MASTER_SPEC §56-61; PAR-001…013).

* :class:`SequentialExecutor` — referencia: ejecuta :func:`run_portfolio` en el proceso actual.
* :class:`ParallelExecutor` — ``ProcessPoolExecutor`` con contexto ``spawn``/``forkserver``
  (``fork`` no se admite), ``initializer`` que carga el snapshot una vez por worker, 1 hilo numérico
  por worker, planificación dinámica con **cola acotada** (contrapresión) y ordenación final por
  ``SequenceID``.

Garantías (probadas): cada ``PortfolioID`` produce exactamente un :class:`TaskResult`; el orden de
salida es el canónico y no depende del orden de envío ni de finalización; un fallo individual no
afecta a otras carteras; el pool se cierra siempre (también ante errores) y el entorno del padre se
restaura.

Bloque 5.4: la ejecución paralela la gobierna :class:`~portfolio_engine.parallel.supervisor.
BatchSupervisor` (caídas, reintentos con cuarentena, plazos, cancelación; véase su docstring) y,
opcionalmente, un diario local (:mod:`portfolio_engine.parallel.journal`) permite reanudar. Una
caída ya **no** marca como ``WORKER_CRASHED`` a todos los lotes en vuelo: solo a la tarea
confirmada como venenosa tras ``max_task_attempts`` intentos aislados.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import multiprocessing
import platform
import sys
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path

from portfolio_engine.cache import CacheMetrics, ResultCache
from portfolio_engine.config import EngineConfig
from portfolio_engine.config.parallel_config import CacheConfig, ParallelConfig
from portfolio_engine.parallel.batching import (
    ParallelExecutionError,
    PortfolioBatch,
    SequencedRequest,
    canonical_order,
    make_batches,
    resolve_batch_size,
)
from portfolio_engine.parallel.journal import (
    JournalScan,
    RunJournal,
    build_identity,
)
from portfolio_engine.parallel.operation_cache import OperationCache
from portfolio_engine.parallel.protocols import (
    ProgressEvent,
    ProgressKind,
    ProgressReporter,
    ResultSink,
    RunControl,
)
from portfolio_engine.parallel.shared_data import (
    PublicationInfo,
    SnapshotHandle,
    publish_snapshot,
    scratch_directory,
)
from portfolio_engine.parallel.supervisor import BatchSupervisor, RecoveryReport, SupervisorHooks
from portfolio_engine.parallel.task import (
    ExecutionContext,
    ExecutionStatus,
    MarketSnapshot,
    PortfolioRequest,
    TaskResult,
    run_portfolio,
)
from portfolio_engine.parallel.threading_control import worker_thread_environment
from portfolio_engine.parallel.worker import (
    ResultBatch,
    initialize_worker_supervised,
    run_batch,
)
from portfolio_engine.utils.hashing import canonical_json, sha256_hex


@dataclass(frozen=True, eq=False, slots=True)
class RunManifest:
    """Identidad y condiciones de una ejecución (requisito propuesto P-08; mínima de B5.2)."""

    run_hash: str
    config_hash: str
    snapshot_key: str
    n_portfolios: int
    mode: str
    workers: int
    batch_size: int
    start_method: str | None
    blas_threads: int | None
    shared_data_mode: str | None
    cache_enabled: bool
    python_version: str
    platform: str
    library_versions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class JournalSpec:
    """Diario local de una ejecución.

    Attributes:
        directory: carpeta del diario.
        resume: ``True`` reanuda un diario existente y compatible; ``False`` exige una carpeta
            vacía o inexistente.
    """

    directory: Path
    resume: bool = False


@dataclass(frozen=True, slots=True)
class RunAccounting:
    """Contabilidad de integridad (P-03): enviadas = Σ estados finales.

    Attributes:
        submitted: tareas de la ejecución.
        by_status: tareas por estado final, ordenadas por nombre. Las restauradas del diario
            figuran como ``SKIPPED_BY_RESUME``; sus resultados conservan su estado original.
        resumed: tareas restauradas del diario sin ejecutarse.
    """

    submitted: int
    by_status: tuple[tuple[str, int], ...]
    resumed: int

    @property
    def balanced(self) -> bool:
        """``True`` si cada tarea enviada tiene exactamente un estado final."""
        return sum(count for _, count in self.by_status) == self.submitted


def _account(results: Sequence[TaskResult], resumed: frozenset[str]) -> RunAccounting:
    """Cuenta los estados finales y verifica el invariante ``enviadas = Σ estados``."""
    counts = Counter(
        ExecutionStatus.SKIPPED_BY_RESUME.value
        if result.task_id in resumed
        else result.execution_status.value
        for result in results
    )
    accounting = RunAccounting(len(results), tuple(sorted(counts.items())), len(resumed))
    if not accounting.balanced:
        raise ParallelExecutionError("Integridad violada: los estados finales no suman las tareas.")
    return accounting


@dataclass(frozen=True, eq=False, slots=True)
class RunResult:
    """Resultados ordenados por ``SequenceID`` (uno por cartera) y manifiesto de la ejecución."""

    results: tuple[TaskResult, ...]
    manifest: RunManifest
    elapsed_seconds: float
    batches: int
    pool_rebuilds: int
    cache_metrics: CacheMetrics = field(default_factory=CacheMetrics)
    publication: PublicationInfo | None = None
    accounting: RunAccounting | None = None
    recovery: RecoveryReport = field(default_factory=RecoveryReport)
    journal_scan: JournalScan | None = None
    resumed_task_ids: tuple[str, ...] = ()

    def by_portfolio(self) -> dict[str, TaskResult]:
        """Resultados indexados por ``PortfolioID``."""
        return {result.portfolio_id: result for result in self.results}


_TRACKED_LIBRARIES = ("numpy", "scipy", "osqp", "clarabel", "pyscipopt", "threadpoolctl")


def _library_versions() -> tuple[tuple[str, str], ...]:
    versions = []
    for name in _TRACKED_LIBRARIES:
        try:
            versions.append((name, importlib.metadata.version(name)))
        except importlib.metadata.PackageNotFoundError:
            versions.append((name, "NOT_INSTALLED"))
    return tuple(versions)


def _manifest(
    context: ExecutionContext,
    n_portfolios: int,
    mode: str,
    workers: int,
    batch_size: int,
    parallel: ParallelConfig | None,
    cache_enabled: bool = False,
) -> RunManifest:
    versions = _library_versions()
    payload = {
        "config_hash": context.config_hash,
        "snapshot_key": context.snapshot_key,
        "n_portfolios": n_portfolios,
        "mode": mode,
        "workers": workers,
        "batch_size": batch_size,
        "start_method": None if parallel is None else parallel.start_method.value,
        "blas_threads": None if parallel is None else parallel.blas_threads,
        "shared_data_mode": None if parallel is None else parallel.shared_data_mode.value,
        "cache_enabled": cache_enabled,
        "versions": [list(item) for item in versions],
    }
    return RunManifest(
        run_hash=sha256_hex(canonical_json(payload)),
        config_hash=context.config_hash,
        snapshot_key=context.snapshot_key,
        n_portfolios=n_portfolios,
        mode=mode,
        workers=workers,
        batch_size=batch_size,
        start_method=None if parallel is None else parallel.start_method.value,
        blas_threads=None if parallel is None else parallel.blas_threads,
        shared_data_mode=None if parallel is None else parallel.shared_data_mode.value,
        cache_enabled=cache_enabled,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        library_versions=versions,
    )


def _verify_exactly_once(
    expected: Sequence[SequencedRequest], results: Sequence[TaskResult]
) -> tuple[TaskResult, ...]:
    """Ordena por ``SequenceID`` y comprueba que cada cartera aparece exactamente una vez."""
    ordered = tuple(
        sorted(results, key=lambda result: -1 if result.sequence_id is None else result.sequence_id)
    )
    expected_ids = [item.sequence_id for item in expected]
    got_ids = [result.sequence_id for result in ordered]
    if got_ids != expected_ids:
        raise ParallelExecutionError(
            f"Integridad violada: se esperaban {len(expected_ids)} resultados únicos y se "
            f"recibieron {len(got_ids)} (pérdida o duplicación de carteras)."
        )
    for item, result in zip(expected, ordered, strict=True):
        if result.portfolio_id != item.request.portfolio_id:
            raise ParallelExecutionError(
                f"Integridad violada: el resultado {result.sequence_id} pertenece a "
                f"{result.portfolio_id!r}, no a {item.request.portfolio_id!r}."
            )
    return ordered


class SequentialExecutor:
    """Ejecutor de referencia: una cartera tras otra en el proceso actual."""

    def __init__(
        self, config: EngineConfig, snapshot: MarketSnapshot, cache: CacheConfig | None = None
    ) -> None:
        self._context = ExecutionContext.create(config, snapshot)
        self._cache_config = cache

    @property
    def context(self) -> ExecutionContext:
        """Contexto de ejecución (configuración, snapshot y hashes)."""
        return self._context

    def run(self, requests: Sequence[PortfolioRequest]) -> RunResult:
        """Ejecuta todas las solicitudes y devuelve los resultados en orden canónico.

        Con ``cache`` activada se usa una caché de resultados para toda la ejecución.
        """
        started = time.perf_counter()
        items = canonical_order(requests)
        cache = None
        if self._cache_config is not None and self._cache_config.enabled:
            cache = OperationCache(
                self._context,
                ResultCache(self._cache_config.max_entries, self._cache_config.max_bytes),
            )
        results = [
            replace(
                run_portfolio(item.request, self._context, cache=cache),
                sequence_id=item.sequence_id,
            )
            for item in items
        ]
        ordered = _verify_exactly_once(items, results)
        manifest = _manifest(self._context, len(items), "SEQUENTIAL", 1, 1, None, cache is not None)
        metrics = CacheMetrics() if cache is None else cache.metrics
        return RunResult(
            ordered,
            manifest,
            time.perf_counter() - started,
            len(items),
            0,
            metrics,
            None,
            _account(ordered, frozenset()),
        )


class _Collector:
    """Recibe los resultados finales de una ejecución: lista, diario, receptor y progreso."""

    def __init__(
        self,
        total: int,
        journal: RunJournal | None,
        sink: ResultSink | None,
        progress: ProgressReporter | None,
    ) -> None:
        self.results: list[TaskResult] = []
        self.cache_metrics = CacheMetrics()
        self._total = total
        self._journal = journal
        self._sink = sink
        self._progress = progress

    def report(self, kind: ProgressKind, detail: str = "") -> None:
        """Notifica un evento; un fallo del receptor nunca aborta el cálculo."""
        if self._progress is None:
            return
        event = ProgressEvent(kind, len(self.results), self._total, detail)
        with contextlib.suppress(Exception):
            self._progress.report(event)

    def final(self, results: Sequence[TaskResult]) -> None:
        """Acepta resultados finales: los guarda, los anota en el diario y los entrega."""
        if not results:
            return
        self.results.extend(results)
        if self._journal is not None:
            self._journal.record(results)
        if self._sink is not None:
            self._sink.accept(tuple(results))
        self.report(ProgressKind.RESULTS)

    def batch(self, outcome: ResultBatch) -> None:
        """Acepta el resultado de un lote terminado."""
        self.cache_metrics = self.cache_metrics + outcome.cache
        self.final(outcome.results)

    def recovery_event(self, kind: str, detail: str) -> None:
        """Registra un evento del supervisor en el diario y lo notifica."""
        if self._journal is not None:
            self._journal.event(kind, detail=detail)
        self.report(_progress_kind(kind), f"{kind}: {detail}")


def _progress_kind(name: str) -> ProgressKind:
    if name == "cancel_requested":
        return ProgressKind.CANCELLED
    if name == "aborted":
        return ProgressKind.ABORTED
    return ProgressKind.RECOVERY


class ParallelExecutor:
    """Ejecutor paralelo por procesos con cola acotada, supervisión y orden canónico de salida."""

    def __init__(
        self, config: EngineConfig, snapshot: MarketSnapshot, parallel: ParallelConfig
    ) -> None:
        method = parallel.start_method.value
        if method not in multiprocessing.get_all_start_methods():
            raise ParallelExecutionError(
                f"El método de arranque '{method}' no está disponible en esta plataforma "
                f"(disponibles: {multiprocessing.get_all_start_methods()})."
            )
        self._context = ExecutionContext.create(config, snapshot)
        self._parallel = parallel
        self._cache_metrics = CacheMetrics()
        self._progress_dir: Path | None = None

    @property
    def context(self) -> ExecutionContext:
        """Contexto de ejecución (configuración, snapshot y hashes)."""
        return self._context

    def _new_pool(self, bundle: SnapshotHandle) -> ProcessPoolExecutor:
        parallel = self._parallel
        return ProcessPoolExecutor(
            max_workers=parallel.workers,
            mp_context=multiprocessing.get_context(parallel.start_method.value),
            initializer=initialize_worker_supervised,
            initargs=(
                str(self._progress_dir),
                bundle,
                parallel.blas_threads,
                parallel.cache,
                parallel.recovery.max_message_chars,
            ),
            max_tasks_per_child=parallel.max_tasks_per_child,
        )

    def _submit(self, pool: ProcessPoolExecutor, batch: PortfolioBatch) -> Future[ResultBatch]:
        """Envía un lote al pool (punto de extensión de las pruebas de inyección de fallos)."""
        return pool.submit(run_batch, batch, str(self._progress_dir))

    def _open_journal(
        self,
        spec: JournalSpec | None,
        items: Sequence[SequencedRequest],
        task_ids: dict[int, str],
    ) -> RunJournal | None:
        if spec is None:
            return None
        if not self._parallel.recovery.journal_enabled:
            raise ParallelExecutionError(
                "El diario está desactivado: active parallel.recovery.journal_enabled."
            )
        identity = build_identity(self._context, list(task_ids.values()))
        expected = {
            task_ids[item.sequence_id]: (item.sequence_id, item.request.portfolio_id)
            for item in items
        }
        return RunJournal.open(spec.directory, identity, expected, resume=spec.resume)

    def run(
        self,
        requests: Sequence[PortfolioRequest],
        *,
        journal: JournalSpec | None = None,
        control: RunControl | None = None,
        progress: ProgressReporter | None = None,
        sink: ResultSink | None = None,
    ) -> RunResult:
        """Ejecuta todas las solicitudes en el pool y devuelve los resultados en orden canónico.

        Args:
            requests: solicitudes (``PortfolioID`` únicos).
            journal: diario local para recuperar/reanudar (``None`` = sin diario). Requiere
                ``parallel.recovery.journal_enabled``. Con ``resume`` se omiten las tareas ya
                restaurables del diario (que se devuelven con su resultado original) y se rechaza
                un diario de otra ejecución sin modificarlo.
            control: permite cancelar; las tareas sin concluir quedan ``CANCELLED``.
            progress: receptor de eventos de progreso (sin datos de carteras).
            sink: recibe cada resultado final exactamente una vez, también los restaurados.
        """
        started = time.perf_counter()
        items = canonical_order(requests)
        task_ids = {item.sequence_id: self._context.task_id(item.request) for item in items}
        run_journal = self._open_journal(journal, items, task_ids)
        try:
            collector = _Collector(len(items), run_journal, sink, progress)
            restored = {} if run_journal is None else dict(run_journal.restored)
            if restored:
                ordered_restored = sorted(restored.values(), key=lambda r: r.sequence_id or 0)
                collector.results.extend(ordered_restored)
                if sink is not None:
                    sink.accept(tuple(ordered_restored))
                collector.report(ProgressKind.RESUMED, f"{len(restored)} tarea(s) restauradas")
            collector.report(ProgressKind.STARTED)
            pending = [item for item in items if task_ids[item.sequence_id] not in restored]
            batches = make_batches(pending, self._parallel) if pending else ()
            batch_size = resolve_batch_size(self._parallel, len(pending)) if pending else 0
            recovery = RecoveryReport()
            publication: PublicationInfo | None = None
            if batches:
                publication, recovery = self._execute(batches, collector, control)
            self._cache_metrics = collector.cache_metrics
            ordered = _verify_exactly_once(items, collector.results)
            accounting = _account(ordered, frozenset(restored))
            if run_journal is not None:
                run_journal.event(
                    "finished", **{status: count for status, count in accounting.by_status}
                )
        finally:
            if run_journal is not None:
                run_journal.close()
        manifest = _manifest(
            self._context,
            len(items),
            "PARALLEL",
            self._parallel.workers,
            batch_size,
            self._parallel,
            self._parallel.cache.enabled,
        )
        collector.report(ProgressKind.FINISHED)
        return RunResult(
            ordered,
            manifest,
            time.perf_counter() - started,
            len(batches),
            recovery.pool_rebuilds,
            self._cache_metrics,
            publication,
            accounting,
            recovery,
            None if run_journal is None else run_journal.scan,
            tuple(sorted(restored)),
        )

    # ----------------------------------------------------------------------------------- pool

    def _execute(
        self,
        batches: Sequence[PortfolioBatch],
        collector: _Collector,
        control: RunControl | None,
    ) -> tuple[PublicationInfo, RecoveryReport]:
        with ExitStack() as stack:
            stack.enter_context(worker_thread_environment(self._parallel.blas_threads))
            published = stack.enter_context(
                publish_snapshot(self._context, self._parallel.shared_data_mode)
            )
            self._progress_dir = stack.enter_context(scratch_directory())
            handle = published.handle
            hooks = SupervisorHooks(
                new_pool=lambda: self._new_pool(handle),
                submit=self._submit,
                task_id=self._context.task_id,
                on_batch=collector.batch,
                on_final=collector.final,
                report=collector.recovery_event,
            )
            supervisor = BatchSupervisor(
                hooks,
                self._parallel.recovery,
                self._parallel.max_in_flight_batches,
                self._progress_dir,
                control,
            )
            try:
                report = supervisor.run(batches)
            finally:
                self._progress_dir = None
            return published.info, report
