"""Proceso worker: ``WorkerInitializer`` y ``WorkerContext`` (PAR-013; MASTER_SPEC §58, §60).

Cada worker conserva únicamente el :class:`~portfolio_engine.parallel.task.ExecutionContext`
inmutable (``MarketSnapshot`` + configuración); todo lo demás se crea y se descarta por tarea
(aislamiento entre carteras).

El snapshot llega al worker por una referencia diminuta (ruta o nombre de segmento más hashes,
véase ``parallel.shared_data``): con ``spawn`` en Windows el padre escribe los argumentos del
proceso en un *pipe* de búfer reducido y se bloquea hasta que el hijo los lee, y el hijo no los
lee hasta haber importado ``__main__``; un payload mayor que el búfer serializa el arranque de los
workers (sonda en ``BLOCK_5_IMPLEMENTATION_PLAN.md`` §8). El modo de entrega (fichero de arranque,
``mmap`` o ``shared_memory``) se elige en ``ParallelConfig.shared_data_mode``.

Cada worker puede tener además una caché de resultados propia y acotada
(``parallel.operation_cache``),
desactivada por defecto; su ciclo de vida es el del proceso.

Las funciones de este módulo son las que ``ProcessPoolExecutor`` ejecuta en los hijos, por lo que
son de nivel de módulo (picklables por referencia) y el estado del worker es una variable de módulo
privada, inevitable con ese ejecutor.
"""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass, field, replace

from portfolio_engine.cache import CacheMetrics, ResultCache
from portfolio_engine.config.parallel_config import CacheConfig
from portfolio_engine.parallel.batching import PortfolioBatch
from portfolio_engine.parallel.markers import BatchMarker, register_worker
from portfolio_engine.parallel.operation_cache import OperationCache
from portfolio_engine.parallel.shared_data import (
    Attachment,
    SnapshotHandle,
    attach_snapshot,
)
from portfolio_engine.parallel.task import (
    ExecutionContext,
    ExecutionStatus,
    MarketSnapshot,
    TaskError,
    TaskResult,
    run_portfolio,
)
from portfolio_engine.parallel.threading_control import (
    ThreadPoolState,
    blas_thread_report,
    limit_blas_threads,
)
from portfolio_engine.utils.hashing import hash_float_array, sha256_hex


@dataclass(frozen=True, eq=False, slots=True)
class WorkerContext:
    """Estado inmutable de un worker."""

    execution: ExecutionContext
    fingerprint: str
    blas_threads: int
    cache: OperationCache | None = None
    attachment: Attachment | None = None
    attach_seconds: float = 0.0
    max_message_chars: int | None = None


@dataclass(frozen=True, eq=False, slots=True)
class ResultBatch:
    """Resultados de un lote (en el orden de ``SequenceID`` del lote) y su procedencia."""

    batch_id: int
    results: tuple[TaskResult, ...]
    worker_pid: int
    elapsed_seconds: float
    cache: CacheMetrics = field(default_factory=CacheMetrics)


class WorkerInitializationError(RuntimeError):
    """El *initializer* del worker falló (fallo de entorno, no de una tarea; Bloque 5.4).

    Un *initializer* que lanza una excepción rompe todo el ``ProcessPoolExecutor`` sin dejar
    rastro de la causa. El *initializer* supervisado la captura y el primer lote que llega al
    worker la relanza con esta clase: así el coordinador distingue «el entorno no arranca» de «una
    tarea mató al proceso».
    """


_CONTEXT: WorkerContext | None = None
_INIT_ERROR: str | None = None
#: Profundidad máxima al seguir la cadena de propietarios de un array.
MAX_BACKING_DEPTH = 8


def snapshot_fingerprint(snapshot: MarketSnapshot) -> str:
    """Huella numérica de los arrays del snapshot (deuda L-1) para detectar contaminación.

    Cubre ``mu``, ``Σ``, los costes de compra/venta y los escenarios de retorno con sus pesos. El
    universo y las definiciones de escenario son dataclasses inmutables (no hay arrays que alterar).
    """
    risk = snapshot.risk_model
    parts = [hash_float_array(risk.mu), hash_float_array(risk.sigma)]
    if snapshot.costs is not None:
        parts += [
            hash_float_array(snapshot.costs.buy_costs),
            hash_float_array(snapshot.costs.sell_costs),
        ]
    if snapshot.return_scenarios is not None:
        parts += [
            hash_float_array(snapshot.return_scenarios.returns),
            hash_float_array(snapshot.return_scenarios.weights),
        ]
    return sha256_hex("|".join(parts))


def initialize_worker(
    handle: SnapshotHandle,
    blas_threads: int,
    cache: CacheConfig | None = None,
    max_message_chars: int | None = None,
) -> None:
    """*Initializer* del pool: adjunta el snapshot, fija hilos numéricos, ignora ``SIGINT``.

    ``handle`` es la referencia publicada por el coordinador (verificada por hash al adjuntar);
    ``cache`` activa la caché de resultados del worker (``None`` o ``enabled=false``: sin caché).

    ``SIGINT`` lo gestiona el proceso coordinador; un Ctrl+C no debe dejar workers a medias con
    trazas de ``KeyboardInterrupt``.
    """
    global _CONTEXT  # estado de proceso del worker (inevitable con ProcessPoolExecutor)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    limit_blas_threads(blas_threads)
    attach_started = time.perf_counter()
    execution, attachment = attach_snapshot(handle)
    attach_seconds = time.perf_counter() - attach_started
    operation_cache = None
    if cache is not None and cache.enabled:
        operation_cache = OperationCache(execution, ResultCache(cache.max_entries, cache.max_bytes))
    _CONTEXT = WorkerContext(
        execution=execution,
        fingerprint=snapshot_fingerprint(execution.snapshot),
        blas_threads=blas_threads,
        cache=operation_cache,
        attachment=attachment,
        attach_seconds=attach_seconds,
        max_message_chars=max_message_chars,
    )


def initialize_worker_supervised(
    progress_dir: str,
    handle: SnapshotHandle,
    blas_threads: int,
    cache: CacheConfig | None,
    max_message_chars: int,
) -> None:
    """*Initializer* del supervisor: se registra, inicializa y conserva el fallo sin romper el pool.

    Con éxito equivale a :func:`initialize_worker`. Si falla, guarda el error (acotado) y
    ``run_batch`` lo relanza como :class:`WorkerInitializationError`.
    """
    global _INIT_ERROR  # estado de proceso del worker
    register_worker(progress_dir)
    try:
        initialize_worker(handle, blas_threads, cache, max_message_chars)
    except Exception as error:  # límite: el fallo se comunica en el primer lote
        _INIT_ERROR = f"{type(error).__name__}: {error}"[:max_message_chars]


def bound_errors(result: TaskResult, limit: int | None) -> TaskResult:
    """Recorta mensaje y traza de los errores de ``result`` a ``limit`` caracteres (deuda L-2).

    No toca estados, resultados numéricos ni el tipo de la excepción: solo el texto libre, que
    puede ser arbitrariamente largo y contener datos de la entrada.
    """
    if limit is None:
        return result

    def cut(error: TaskError | None) -> TaskError | None:
        if error is None:
            return None
        return replace(error, message=error.message[:limit], traceback=error.traceback[:limit])

    operations = tuple(replace(op, error=cut(op.error)) for op in result.operations)
    return replace(result, error=cut(result.error), operations=operations)


def worker_context() -> WorkerContext:
    """Contexto del worker actual (``RuntimeError`` si no se ha inicializado)."""
    if _CONTEXT is None:
        raise RuntimeError("El worker no está inicializado (falta initialize_worker).")
    return _CONTEXT


def run_batch(batch: PortfolioBatch, progress_dir: str | None = None) -> ResultBatch:
    """Ejecuta un lote completo en este worker y devuelve sus resultados.

    Comprueba antes y después que los datos de mercado compartidos no han cambiado; si cambiaran,
    lanza ``RuntimeError`` (el ejecutor lo registra como fallo del lote, nunca como resultado).
    Con ``progress_dir`` declara cada tarea antes de empezarla (véase ``parallel.markers``).
    """
    if _INIT_ERROR is not None:
        raise WorkerInitializationError(_INIT_ERROR)
    context = worker_context()
    started = time.perf_counter()
    if snapshot_fingerprint(context.execution.snapshot) != context.fingerprint:
        raise RuntimeError("El snapshot compartido cambió antes de ejecutar el lote.")
    before = CacheMetrics() if context.cache is None else context.cache.metrics
    pid = os.getpid()
    results: list[TaskResult] = []
    with BatchMarker(progress_dir, batch.batch_id) as marker:
        for position, item in enumerate(batch.items):
            marker.start(position)
            outcome = run_portfolio(item.request, context.execution, cache=context.cache)
            results.append(
                bound_errors(
                    replace(outcome, sequence_id=item.sequence_id, worker_pid=pid),
                    context.max_message_chars,
                )
            )
    if snapshot_fingerprint(context.execution.snapshot) != context.fingerprint:
        raise RuntimeError("El snapshot compartido fue alterado durante el lote (contaminación).")
    cache_delta = CacheMetrics() if context.cache is None else context.cache.metrics.since(before)
    return ResultBatch(
        batch.batch_id, tuple(results), pid, time.perf_counter() - started, cache_delta
    )


@dataclass(frozen=True, slots=True)
class MemoryUsage:
    """Memoria de un proceso en bytes (``psutil``; ``uss``/``pss`` según la plataforma)."""

    rss: int
    uss: int | None
    pss: int | None


def array_backing(array: object) -> str:
    """Tipo del objeto que posee la memoria de un array (``mmap``, ``bytes``, ``ndarray``…).

    Distingue las vistas sin copia sobre una proyección (``mmap``) o un segmento compartido de una
    copia privada deserializada en banda (``bytes``). Sigue ``.base`` y ``memoryview.obj``.
    """
    current: object = array
    for _ in range(MAX_BACKING_DEPTH):
        if isinstance(current, memoryview):
            current = current.obj
        else:
            base = getattr(current, "base", None)
            if base is None:
                break
            current = base
    return type(current).__name__


def process_memory(pid: int | None = None) -> MemoryUsage | None:
    """Memoria del proceso ``pid`` (el actual por defecto); ``None`` si ``psutil`` no está
    instalado.

    ``psutil`` es una dependencia opcional del grupo ``bench``: solo se usa para medir.
    """
    try:
        import psutil
    except ImportError:
        return None
    process = psutil.Process(pid)
    full = process.memory_full_info()
    return MemoryUsage(
        rss=int(full.rss),
        uss=int(full.uss) if hasattr(full, "uss") else None,
        pss=int(full.pss) if hasattr(full, "pss") else None,
    )


@dataclass(frozen=True, slots=True)
class WorkerDiagnostics:
    """Estado observable de un worker (pruebas de aislamiento y de hilos)."""

    pid: int
    blas_threads_configured: int
    thread_pools: tuple[ThreadPoolState, ...]
    environment: tuple[tuple[str, str], ...]
    memory: MemoryUsage | None = None
    sigma_backing: str = ""
    attach_seconds: float = 0.0


def worker_diagnostics(_: int = 0) -> WorkerDiagnostics:
    """Diagnóstico del worker actual (se invoca como tarea del pool en las pruebas)."""
    context = worker_context()
    names = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
    return WorkerDiagnostics(
        pid=os.getpid(),
        blas_threads_configured=context.blas_threads,
        thread_pools=blas_thread_report(),
        environment=tuple((name, os.environ.get(name, "")) for name in names),
        memory=process_memory(),
        sigma_backing=array_backing(context.execution.snapshot.risk_model.sigma),
        attach_seconds=context.attach_seconds,
    )


def crashed_result(
    item_task_id: str,
    portfolio_id: str,
    workload_hash: str,
    sequence_id: int,
    status: ExecutionStatus,
    error: TaskError,
) -> TaskResult:
    """Resultado de una tarea cuyo lote no devolvió resultado (caída o fallo del worker)."""
    return TaskResult(
        task_id=item_task_id,
        portfolio_id=portfolio_id,
        workload_hash=workload_hash,
        sequence_id=sequence_id,
        execution_status=status,
        operations=(),
        error=error,
        elapsed_seconds=0.0,
        worker_pid=None,
    )
