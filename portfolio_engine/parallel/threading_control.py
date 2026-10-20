"""Control de sobresuscripción de hilos numéricos (MASTER_SPEC §60; PAR-007).

Línea base: 1 hilo numérico por worker. Dos mecanismos complementarios:

* **Variables de entorno** (``OMP_NUM_THREADS``, ``OPENBLAS_NUM_THREADS``, ``MKL_NUM_THREADS``…)
  que los procesos hijos heredan **antes** de importar NumPy. Con ``spawn``/``forkserver`` el hijo
  importa NumPy al deserializar el *initializer*, así que el entorno debe estar fijado en el padre
  mientras dure el pool: :func:`worker_thread_environment`.
* ``threadpoolctl`` en el *initializer* del worker: limita las librerías ya cargadas
  (:func:`limit_blas_threads`) e informa del estado real (:func:`blas_thread_report`).

No se modifica ningún ajuste de solver (decisión diferida D-08).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from threadpoolctl import ThreadpoolController, threadpool_limits

#: Variables que controlan los hilos de BLAS/OpenMP y librerías afines.
THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


@dataclass(frozen=True, slots=True)
class ThreadPoolState:
    """Estado de una librería numérica con hilos (``threadpoolctl``)."""

    user_api: str
    internal_api: str
    num_threads: int


def thread_environment(threads: int) -> dict[str, str]:
    """Variables de entorno que fijan ``threads`` hilos numéricos."""
    if threads < 1:
        raise ValueError("threads debe ser >= 1.")
    return {name: str(threads) for name in THREAD_ENV_VARS}


@contextmanager
def worker_thread_environment(threads: int) -> Iterator[None]:
    """Fija en el proceso actual las variables de hilos y las restaura al salir.

    Los workers que se creen dentro del bloque las heredan. No afecta a las librerías ya cargadas
    en el proceso padre (su estado de hilos no se modifica).
    """
    desired = thread_environment(threads)
    previous = {name: os.environ.get(name) for name in desired}
    os.environ.update(desired)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def limit_blas_threads(threads: int) -> threadpool_limits:
    """Limita a ``threads`` los hilos de todas las librerías numéricas cargadas en este proceso.

    Devuelve el limitador de ``threadpoolctl`` (``restore_original_limits()`` deshace el límite).
    """
    if threads < 1:
        raise ValueError("threads debe ser >= 1.")
    return threadpool_limits(limits=threads)


def blas_thread_report() -> tuple[ThreadPoolState, ...]:
    """Estado actual de las librerías numéricas con hilos de este proceso."""
    return tuple(
        ThreadPoolState(
            user_api=str(info.get("user_api", "")),
            internal_api=str(info.get("internal_api", "")),
            num_threads=int(info["num_threads"]),
        )
        for info in ThreadpoolController().info()
    )
