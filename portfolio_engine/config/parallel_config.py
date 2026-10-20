"""``ParallelConfig``: ajustes de ejecución del ejecutor paralelo (MASTER_SPEC §56-61; CFG-011).

Son ajustes de **ejecución**, no matemáticos: viven en su propio fichero TOML y no forman parte de
``EngineConfig`` ni de su ``ConfigHash`` (cambiar el número de workers no debe invalidar resultados
ni claves de caché). Se aplican las mismas reglas estrictas que al resto de la configuración: toda
clave obligatoria debe estar presente, toda clave desconocida es un error y no hay valores por
defecto en el código (``workers`` nunca se deduce de ``os.cpu_count()``, PAR-012).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from portfolio_engine.config.loader import build_dataclass, read_toml
from portfolio_engine.exceptions import ConfigError

PARALLEL_SECTION = "parallel"


class ProcessStartMethod(StrEnum):
    """Método de arranque de procesos admitido.

        ``fork`` no se admite: es inseguro con librerías con hilos (BLAS, solvers) y con estado de
        hilos heredado del padre. ``FORKSERVER`` solo existe en Unix y **no está validado**: el
        Bloque 5.2
    solo se ha ejecutado con ``SPAWN`` en Windows; hasta ejecutar la suite en Linux no se declara
    compatibilidad.
    """

    SPAWN = "spawn"
    FORKSERVER = "forkserver"


class SharedDataMode(StrEnum):
    """Cómo llegan los datos de mercado inmutables a los workers (MASTER_SPEC §58; PAR-004).

    * ``BUNDLE_FILE``: fichero de arranque hash-verificado que cada worker deserializa por completo
      (modo de B5.2; copia privada por worker). Es el modo de reserva (*fallback*).
    * ``FILE_MMAP``: cabecera de *pickle* con *buffers* fuera de banda; los arrays viven en un único
      fichero que cada worker proyecta en memoria de solo lectura (``mmap``): las páginas se
      comparten a través de la caché de páginas del sistema.
    * ``SHARED_MEMORY``: igual, pero los arrays viven en un segmento de
      ``multiprocessing.shared_memory`` gestionado por el coordinador.
    """

    BUNDLE_FILE = "BUNDLE_FILE"
    FILE_MMAP = "FILE_MMAP"
    SHARED_MEMORY = "SHARED_MEMORY"


@dataclass(frozen=True, slots=True)
class CacheConfig:
    """Caché de resultados por worker (MASTER_SPEC §62; CCH-001…005).

    Attributes:
        enabled: la caché se entrega **desactivada** (``false``); activarla es una decisión
            explícita. Con ``false`` no se calcula ninguna clave ni se guarda nada.
        max_entries: número máximo de resultados por worker (``>= 1``).
        max_bytes: tamaño máximo en bytes serializados por worker (``>= 1``); un único resultado
            mayor que este límite no se guarda.
    """

    enabled: bool
    max_entries: int
    max_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError("parallel.cache.enabled debe ser booleano.")
        _require_at_least_one(self.max_entries, "parallel.cache.max_entries")
        _require_at_least_one(self.max_bytes, "parallel.cache.max_bytes")


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    """Supervisión, reintentos, plazos y diario del ejecutor (Bloque 5.4; P-03…P-06).

    Attributes:
        max_task_attempts: intentos **aislados** (una tarea sola en el pool) que se permiten a una
            tarea sospechosa de una caída antes de declararla ``WORKER_CRASHED`` (``>= 1``).
        max_rebuilds_without_progress: tope (``>= 1``) de caídas consecutivas **sin atribuir a
            ninguna tarea** y de tareas venenosas consecutivas, en ambos casos sin ningún resultado
            recibido en medio; al alcanzarlo la ejecución se aborta.
        max_total_rebuilds: cota absoluta de reconstrucciones por ejecución (``>= 1``).
        supervision_poll_seconds: periodo del sondeo del supervisor (plazos, vigilancia de
            procesos, cancelación); ``> 0``.
        task_timeout_seconds: plazo de pared de **una cartera** desde que su worker la empieza
            (omitido = sin plazo). Se hace cumplir terminando el worker.
        batch_timeout_seconds: plazo de pared de **un lote** desde que su worker lo empieza
            (omitido = sin plazo). Un lote de varias carteras que lo agota se descompone en lotes
            unitarios; un lote unitario que lo agota termina ``TIMED_OUT``.
        cancel_grace_seconds: tras una cancelación, tiempo (``>= 0``) que se espera a los lotes en
            vuelo antes de terminar sus workers.
        journal_enabled: permite escribir el diario local (``false``: ``journal`` se rechaza).
        max_message_chars: longitud máxima de los mensajes de error en eventos y resultados
            sintéticos (observabilidad acotada); ``>= 1``.
    """

    max_task_attempts: int
    max_rebuilds_without_progress: int
    max_total_rebuilds: int
    supervision_poll_seconds: float
    task_timeout_seconds: float | None
    batch_timeout_seconds: float | None
    cancel_grace_seconds: float
    journal_enabled: bool
    max_message_chars: int

    def __post_init__(self) -> None:
        _require_at_least_one(self.max_task_attempts, "parallel.recovery.max_task_attempts")
        _require_at_least_one(
            self.max_rebuilds_without_progress, "parallel.recovery.max_rebuilds_without_progress"
        )
        _require_at_least_one(self.max_total_rebuilds, "parallel.recovery.max_total_rebuilds")
        _require_at_least_one(self.max_message_chars, "parallel.recovery.max_message_chars")
        _require_positive(
            self.supervision_poll_seconds, "parallel.recovery.supervision_poll_seconds"
        )
        if self.task_timeout_seconds is not None:
            _require_positive(self.task_timeout_seconds, "parallel.recovery.task_timeout_seconds")
        if self.batch_timeout_seconds is not None:
            _require_positive(self.batch_timeout_seconds, "parallel.recovery.batch_timeout_seconds")
        if isinstance(self.cancel_grace_seconds, bool) or self.cancel_grace_seconds < 0:
            raise ConfigError("parallel.recovery.cancel_grace_seconds debe ser >= 0.")
        if not isinstance(self.journal_enabled, bool):
            raise ConfigError("parallel.recovery.journal_enabled debe ser booleano.")


@dataclass(frozen=True, slots=True)
class ParallelConfig:
    """Ajustes del ejecutor paralelo.

    Attributes:
        workers: número de procesos worker (``>= 1``); explícito, nunca ``cpu_count()``.
        batch_size: carteras por lote; ``None`` = modo AUTO (PAR-003).
        auto_batches_per_worker: en AUTO, lotes por worker que se pretenden crear (equilibrio de
            carga frente a sobrecarga de planificación).
        max_batch_size: cota superior del tamaño de lote (también en modo AUTO).
        max_in_flight_batches_per_worker: lotes simultáneamente enviados por worker
            (contrapresión: la cola es acotada).
        start_method: método de arranque de procesos.
        blas_threads: hilos numéricos (BLAS/OpenMP) por worker; línea base 1 (§60).
        max_tasks_per_child: lotes tras los cuales un worker se recicla (``None`` = sin reciclado).
        shared_data_mode: cómo se entregan los datos de mercado a los workers.
        cache: caché de resultados por worker (desactivada por defecto).
        recovery: supervisión, reintentos, plazos y diario (Bloque 5.4).
    """

    workers: int
    batch_size: int | None
    auto_batches_per_worker: int
    max_batch_size: int
    max_in_flight_batches_per_worker: int
    start_method: ProcessStartMethod
    blas_threads: int
    max_tasks_per_child: int | None
    shared_data_mode: SharedDataMode
    cache: CacheConfig
    recovery: RecoveryConfig

    def __post_init__(self) -> None:
        _require_at_least_one(self.workers, "parallel.workers")
        if self.batch_size is not None:
            _require_at_least_one(self.batch_size, "parallel.batch_size")
        _require_at_least_one(self.auto_batches_per_worker, "parallel.auto_batches_per_worker")
        _require_at_least_one(self.max_batch_size, "parallel.max_batch_size")
        _require_at_least_one(
            self.max_in_flight_batches_per_worker, "parallel.max_in_flight_batches_per_worker"
        )
        _require_at_least_one(self.blas_threads, "parallel.blas_threads")
        if self.max_tasks_per_child is not None:
            _require_at_least_one(self.max_tasks_per_child, "parallel.max_tasks_per_child")
        if self.batch_size is not None and self.batch_size > self.max_batch_size:
            raise ConfigError("parallel.batch_size no puede superar parallel.max_batch_size.")

    @property
    def max_in_flight_batches(self) -> int:
        """Lotes simultáneamente en vuelo en total."""
        return self.workers * self.max_in_flight_batches_per_worker


def _require_positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ConfigError(f"{name} debe ser un número > 0 (recibido {value!r}).")


def _require_at_least_one(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{name} debe ser un entero >= 1 (recibido {value!r}).")


def load_parallel_config(source: str | Path | Mapping[str, Any]) -> ParallelConfig:
    """Carga y valida un :class:`ParallelConfig` desde un TOML o un diccionario."""
    raw = read_toml(source) if isinstance(source, (str, Path)) else source
    if not isinstance(raw, Mapping):
        raise ConfigError("La configuración paralela debe ser un diccionario de secciones.")
    unknown = sorted(set(raw) - {PARALLEL_SECTION})
    if unknown:
        raise ConfigError(f"Secciones desconocidas en la configuración paralela: {unknown}")
    if PARALLEL_SECTION not in raw:
        raise ConfigError(f"Sección de configuración ausente: [{PARALLEL_SECTION}]")
    return build_dataclass(ParallelConfig, raw[PARALLEL_SECTION], PARALLEL_SECTION)
