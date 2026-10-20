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
Un worker que muere (``BrokenProcessPool``) rompe **todo el pool**: los lotes en vuelo cuando el
pool detecta la caída (hasta ``workers × max_in_flight_batches_per_worker`` lotes) se marcan
``WORKER_CRASHED``, incluidas las carteras sanas y las ya calculadas dentro de esos lotes, y el pool
se reconstruye para continuar. ``WORKER_CRASHED`` significa «afectada por una caída», no «causó la
caída». La detección puede retrasarse hasta el siguiente evento del pool si muere el último worker
creado bajo demanda (véase ``ARCHITECTURE.md`` §3.7). **No hay reintentos, plazos ni cancelación**
todavía (Bloque 5.4).
"""

from __future__ import annotations

import importlib.metadata
import multiprocessing
import platform
import sys
import time
from collections import deque
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from contextlib import ExitStack
from dataclasses import dataclass, field, replace

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
from portfolio_engine.parallel.operation_cache import OperationCache
from portfolio_engine.parallel.shared_data import (
    PublicationInfo,
    SnapshotHandle,
    publish_snapshot,
)
from portfolio_engine.parallel.task import (
    ExecutionContext,
    ExecutionStatus,
    MarketSnapshot,
    PortfolioRequest,
    TaskError,
    TaskResult,
    run_portfolio,
)
from portfolio_engine.parallel.threading_control import worker_thread_environment
from portfolio_engine.parallel.worker import (
    ResultBatch,
    crashed_result,
    initialize_worker,
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
            ordered, manifest, time.perf_counter() - started, len(items), 0, metrics, None
        )


def _crash_error(batch: PortfolioBatch, cause: BaseException) -> TaskError:
    return TaskError(
        error_type=type(cause).__name__,
        message=f"El lote {batch.batch_id} no devolvió resultado: {cause}",
        operation_index=None,
        traceback="",
    )


class ParallelExecutor:
    """Ejecutor paralelo por procesos con cola acotada y orden canónico de salida."""

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

    @property
    def context(self) -> ExecutionContext:
        """Contexto de ejecución (configuración, snapshot y hashes)."""
        return self._context

    def _new_pool(self, bundle: SnapshotHandle) -> ProcessPoolExecutor:
        parallel = self._parallel
        return ProcessPoolExecutor(
            max_workers=parallel.workers,
            mp_context=multiprocessing.get_context(parallel.start_method.value),
            initializer=initialize_worker,
            initargs=(bundle, parallel.blas_threads, parallel.cache),
            max_tasks_per_child=parallel.max_tasks_per_child,
        )

    def run(self, requests: Sequence[PortfolioRequest]) -> RunResult:
        """Ejecuta todas las solicitudes en el pool y devuelve los resultados en orden canónico."""
        started = time.perf_counter()
        items = canonical_order(requests)
        batches = make_batches(items, self._parallel) if items else ()
        batch_size = resolve_batch_size(self._parallel, len(items)) if items else 0
        results: list[TaskResult] = []
        rebuilds = 0
        self._cache_metrics = CacheMetrics()
        publication: PublicationInfo | None = None
        if batches:
            with ExitStack() as stack:
                stack.enter_context(worker_thread_environment(self._parallel.blas_threads))
                published = stack.enter_context(
                    publish_snapshot(self._context, self._parallel.shared_data_mode)
                )
                publication = published.info
                rebuilds = self._execute(batches, results, published.handle)
        ordered = _verify_exactly_once(items, results)
        manifest = _manifest(
            self._context,
            len(items),
            "PARALLEL",
            self._parallel.workers,
            batch_size,
            self._parallel,
            self._parallel.cache.enabled,
        )
        return RunResult(
            ordered,
            manifest,
            time.perf_counter() - started,
            len(batches),
            rebuilds,
            self._cache_metrics,
            publication,
        )

    # ----------------------------------------------------------------------------------- pool

    def _execute(
        self, batches: Sequence[PortfolioBatch], results: list[TaskResult], bundle: SnapshotHandle
    ) -> int:
        pending = deque(batches)
        in_flight: dict[Future[ResultBatch], PortfolioBatch] = {}
        limit = self._parallel.max_in_flight_batches
        pool = self._new_pool(bundle)
        rebuilds = 0
        try:
            while pending or in_flight:
                while pending and len(in_flight) < limit:
                    batch = pending.popleft()
                    in_flight[pool.submit(run_batch, batch)] = batch
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                broken = False
                for future in done:
                    broken |= self._collect(future, in_flight.pop(future), results)
                if broken:
                    # Un pool roto falla todos sus futuros pendientes: se recogen (como caídas),
                    # se descarta el pool y se crea uno nuevo para los lotes aún sin enviar.
                    for future in list(in_flight):
                        self._collect(future, in_flight.pop(future), results)
                    pool.shutdown(wait=True, cancel_futures=True)
                    pool = self._new_pool(bundle)
                    rebuilds += 1
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        return rebuilds

    def _collect(
        self, future: Future[ResultBatch], batch: PortfolioBatch, results: list[TaskResult]
    ) -> bool:
        """Añade los resultados del lote; devuelve ``True`` si el pool quedó roto."""
        try:
            outcome = future.result()
        except BrokenProcessPool as error:
            results.extend(self._failed(batch, error, ExecutionStatus.WORKER_CRASHED))
            return True
        except Exception as error:  # fallo del lote (p. ej. resultado no serializable)
            results.extend(self._failed(batch, error, ExecutionStatus.FAILED_EXCEPTION))
            return False
        results.extend(outcome.results)
        self._cache_metrics = self._cache_metrics + outcome.cache
        return False

    def _failed(
        self, batch: PortfolioBatch, cause: BaseException, status: ExecutionStatus
    ) -> list[TaskResult]:
        error = _crash_error(batch, cause)
        return [
            crashed_result(
                self._context.task_id(item.request),
                item.request.portfolio_id,
                item.request.workload.workload_hash,
                item.sequence_id,
                status,
                error,
            )
            for item in batch.items
        ]
