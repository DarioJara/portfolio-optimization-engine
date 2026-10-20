"""Proceso worker: ``WorkerInitializer`` y ``WorkerContext`` (PAR-013; MASTER_SPEC §58, §60).

Cada worker conserva únicamente el :class:`~portfolio_engine.parallel.task.ExecutionContext`
inmutable (``MarketSnapshot`` + configuración); todo lo demás se crea y se descarta por tarea
(aislamiento entre carteras).

En el Bloque 5.2 el snapshot llega al worker por un **fichero de arranque** (``WorkerBundle``) que
el coordinador escribe una vez en un directorio temporal privado; el *initializer* solo recibe su
ruta y su SHA-256 (unos cientos de bytes). Motivo medido: con ``spawn`` en Windows el padre
escribe los argumentos del proceso en un *pipe* de búfer reducido y se bloquea hasta que el hijo
los lee; el hijo no los lee hasta haber importado el módulo ``__main__``, de modo que un payload
mayor que el búfer serializa el arranque de los workers (sonda en
``BLOCK_5_IMPLEMENTATION_PLAN.md`` §8). El fichero se verifica por hash antes de deserializarlo
(``pickle`` solo entre procesos de confianza de la misma ejecución). El mecanismo definitivo de
datos compartidos (memoria compartida, ``memmap``, formatos no ejecutables) es del Bloque 5.3.

Las funciones de este módulo son las que ``ProcessPoolExecutor`` ejecuta en los hijos, por lo que
son de nivel de módulo (picklables por referencia) y el estado del worker es una variable de módulo
privada, inevitable con ese ejecutor.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import signal
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from portfolio_engine.parallel.batching import PortfolioBatch
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


@dataclass(frozen=True, eq=False, slots=True)
class ResultBatch:
    """Resultados de un lote (en el orden de ``SequenceID`` del lote) y su procedencia."""

    batch_id: int
    results: tuple[TaskResult, ...]
    worker_pid: int
    elapsed_seconds: float


_CONTEXT: WorkerContext | None = None
BUNDLE_FILE_NAME = "worker_bundle.pkl"


@dataclass(frozen=True, slots=True)
class WorkerBundle:
    """Referencia (ruta + SHA-256) al fichero de arranque con la configuración y el snapshot."""

    path: str
    sha256: str


def write_worker_bundle(directory: Path, context: ExecutionContext) -> WorkerBundle:
    """Escribe el fichero de arranque de los workers en ``directory`` y devuelve su referencia.

    Contiene el contexto completo, con ``ConfigHash`` y ``snapshot_key`` ya calculados por el
    coordinador (los workers no los recalculan).
    """
    payload = pickle.dumps(context, protocol=pickle.HIGHEST_PROTOCOL)
    path = directory / BUNDLE_FILE_NAME
    path.write_bytes(payload)
    return WorkerBundle(str(path), hashlib.sha256(payload).hexdigest())


def load_worker_bundle(bundle: WorkerBundle) -> ExecutionContext:
    """Lee y deserializa el fichero de arranque tras verificar su SHA-256."""
    payload = Path(bundle.path).read_bytes()
    if hashlib.sha256(payload).hexdigest() != bundle.sha256:
        raise RuntimeError(
            "El fichero de arranque del worker no coincide con su hash (integridad)."
        )
    context = pickle.loads(payload)  # fichero propio, verificado por hash
    if not isinstance(context, ExecutionContext):
        raise RuntimeError("El fichero de arranque no contiene un ExecutionContext.")
    return context


@contextmanager
def worker_bundle(context: ExecutionContext) -> Iterator[WorkerBundle]:
    """Directorio temporal privado con el fichero de arranque; se elimina siempre al salir."""
    with tempfile.TemporaryDirectory(prefix="portfolio_engine_run_") as directory:
        yield write_worker_bundle(Path(directory), context)


def snapshot_fingerprint(snapshot: MarketSnapshot) -> str:
    """Huella numérica de ``mu`` y ``Σ`` para detectar que un worker no altera los datos."""
    risk = snapshot.risk_model
    return sha256_hex(hash_float_array(risk.mu) + hash_float_array(risk.sigma))


def initialize_worker(bundle: WorkerBundle, blas_threads: int) -> None:
    """*Initializer* del pool: carga el snapshot, fija hilos numéricos, ignora ``SIGINT``.

    ``SIGINT`` lo gestiona el proceso coordinador; un Ctrl+C no debe dejar workers a medias con
    trazas de ``KeyboardInterrupt``.
    """
    global _CONTEXT  # estado de proceso del worker (inevitable con ProcessPoolExecutor)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    limit_blas_threads(blas_threads)
    execution = load_worker_bundle(bundle)
    _CONTEXT = WorkerContext(
        execution=execution,
        fingerprint=snapshot_fingerprint(execution.snapshot),
        blas_threads=blas_threads,
    )


def worker_context() -> WorkerContext:
    """Contexto del worker actual (``RuntimeError`` si no se ha inicializado)."""
    if _CONTEXT is None:
        raise RuntimeError("El worker no está inicializado (falta initialize_worker).")
    return _CONTEXT


def run_batch(batch: PortfolioBatch) -> ResultBatch:
    """Ejecuta un lote completo en este worker y devuelve sus resultados.

    Comprueba antes y después que los datos de mercado compartidos no han cambiado; si cambiaran,
    lanza ``RuntimeError`` (el ejecutor lo registra como fallo del lote, nunca como resultado).
    """
    context = worker_context()
    started = time.perf_counter()
    if snapshot_fingerprint(context.execution.snapshot) != context.fingerprint:
        raise RuntimeError("El snapshot compartido cambió antes de ejecutar el lote.")
    pid = os.getpid()
    results = tuple(
        replace(
            run_portfolio(item.request, context.execution),
            sequence_id=item.sequence_id,
            worker_pid=pid,
        )
        for item in batch.items
    )
    if snapshot_fingerprint(context.execution.snapshot) != context.fingerprint:
        raise RuntimeError("El snapshot compartido fue alterado durante el lote (contaminación).")
    return ResultBatch(batch.batch_id, results, pid, time.perf_counter() - started)


@dataclass(frozen=True, slots=True)
class WorkerDiagnostics:
    """Estado observable de un worker (pruebas de aislamiento y de hilos)."""

    pid: int
    blas_threads_configured: int
    thread_pools: tuple[ThreadPoolState, ...]
    environment: tuple[tuple[str, str], ...]


def worker_diagnostics(_: int = 0) -> WorkerDiagnostics:
    """Diagnóstico del worker actual (se invoca como tarea del pool en las pruebas)."""
    context = worker_context()
    names = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
    return WorkerDiagnostics(
        pid=os.getpid(),
        blas_threads_configured=context.blas_threads,
        thread_pools=blas_thread_report(),
        environment=tuple((name, os.environ.get(name, "")) for name in names),
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
