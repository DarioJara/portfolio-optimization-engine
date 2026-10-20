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
    """

    workers: int
    batch_size: int | None
    auto_batches_per_worker: int
    max_batch_size: int
    max_in_flight_batches_per_worker: int
    start_method: ProcessStartMethod
    blas_threads: int
    max_tasks_per_child: int | None

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
