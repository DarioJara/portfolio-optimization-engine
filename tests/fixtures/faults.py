"""Inyección de fallos en workers reales (Bloque 5.4): morir, colgar, retrasar o no arrancar.

Los workers se crean con ``spawn``: el *initializer* y su especificación deben ser picklables por
referencia, por eso viven en un módulo importable. Las tareas se identifican por ``PortfolioID``.
Los fallos se inyectan **dentro del worker**, en ``run_portfolio`` (el punto donde ``run_batch``
llama al motor), de modo que atraviesan exactamente el mismo camino que un fallo real: marca de
progreso, ``BrokenProcessPool``, supervisor.
"""

from __future__ import annotations

import dataclasses
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from portfolio_engine.config.parallel_config import CacheConfig
from portfolio_engine.parallel import worker as worker_module
from portfolio_engine.parallel.executor import ParallelExecutor
from portfolio_engine.parallel.markers import register_worker
from portfolio_engine.parallel.shared_data import SnapshotHandle, WorkerBundle
from portfolio_engine.parallel.task import ExecutionContext, PortfolioRequest

#: Un colgado «para siempre» (el supervisor debe terminarlo; nunca se espera a que acabe).
HANG_SECONDS = 3600.0
EXIT_CODE = 23


@dataclass(frozen=True, slots=True)
class FaultSpec:
    """Qué fallos inyectar.

    Attributes:
        delay: segundos que se retrasa **cada** tarea (para poder interrumpir una ejecución).
        die: carteras cuyo worker muere (``os._exit``) cada vez que las ejecuta (venenosas).
        die_once: carteras que matan a su worker solo la primera vez (kill externo transitorio).
        hang: carteras que no terminan nunca.
        flag_dir: directorio de las banderas de ``die_once``.
        init: ``""`` (sano), ``"exit"`` (muere sin registrarse), ``"exit_registered"`` (se registra
            y muere) o ``"tamper"`` (el snapshot llega con un hash incorrecto: el *initializer*
            lanza una excepción real).
    """

    delay: float = 0.0
    die: tuple[str, ...] = ()
    die_once: tuple[str, ...] = ()
    hang: tuple[str, ...] = ()
    flag_dir: str = ""
    init: str = ""


def _install(spec: FaultSpec) -> None:
    real = worker_module.run_portfolio

    def faulty(request: PortfolioRequest, context: ExecutionContext, **kwargs: Any) -> Any:
        portfolio_id = request.portfolio_id
        if spec.delay:
            time.sleep(spec.delay)
        if portfolio_id in spec.hang:
            time.sleep(HANG_SECONDS)
        if portfolio_id in spec.die:
            os._exit(EXIT_CODE)
        if portfolio_id in spec.die_once:
            flag = Path(spec.flag_dir) / f"{portfolio_id}.died"
            if not flag.exists():
                flag.write_text("x", encoding="utf-8")
                os._exit(EXIT_CODE)
        return real(request, context, **kwargs)

    worker_module.run_portfolio = faulty  # type: ignore[assignment]


def faulty_initializer(
    spec: FaultSpec,
    progress_dir: str,
    handle: SnapshotHandle,
    blas_threads: int,
    cache: CacheConfig | None,
    max_message_chars: int,
) -> None:
    """*Initializer* supervisado con los fallos de ``spec``."""
    if spec.init == "exit":
        os._exit(EXIT_CODE)
    if spec.init == "exit_registered":
        register_worker(progress_dir)
        os._exit(EXIT_CODE)
    worker_module.initialize_worker_supervised(
        progress_dir, handle, blas_threads, cache, max_message_chars
    )
    _install(spec)


class FaultyExecutor(ParallelExecutor):
    """``ParallelExecutor`` cuyos workers inyectan los fallos de un :class:`FaultSpec`."""

    def __init__(self, *args: Any, spec: FaultSpec, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._spec = spec

    def _new_pool(self, bundle: SnapshotHandle) -> ProcessPoolExecutor:
        import multiprocessing

        parallel = self._parallel
        handle = bundle
        if self._spec.init == "tamper" and isinstance(bundle, WorkerBundle):
            handle = dataclasses.replace(bundle, sha256="0" * len(bundle.sha256))
        return ProcessPoolExecutor(
            max_workers=parallel.workers,
            mp_context=multiprocessing.get_context(parallel.start_method.value),
            initializer=faulty_initializer,
            initargs=(
                self._spec,
                str(self._progress_dir),
                handle,
                parallel.blas_threads,
                parallel.cache,
                parallel.recovery.max_message_chars,
            ),
            max_tasks_per_child=parallel.max_tasks_per_child,
        )


def fault_config(workers: int = 2, batch_size: int | None = 1, **recovery: Any) -> Any:
    """``ParallelConfig`` de pruebas de recuperación: sondeo rápido, diario permitido.

    Un lote en vuelo por worker (la atribución de fallos es más nítida) y los límites del
    supervisor ajustados para que las pruebas con procesos reales terminen pronto.
    """
    from tests.fixtures.parallel import parallel_config

    base = parallel_config(
        workers=workers, batch_size=batch_size, max_in_flight_batches_per_worker=1
    )
    changes = {
        "supervision_poll_seconds": 0.1,
        "cancel_grace_seconds": 0.5,
        "journal_enabled": True,
        "max_rebuilds_without_progress": 2,
        **recovery,
    }
    return dataclasses.replace(base, recovery=dataclasses.replace(base.recovery, **changes))
