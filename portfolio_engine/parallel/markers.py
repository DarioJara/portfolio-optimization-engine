"""Marcas de progreso de los workers en un directorio de la ejecución (Bloque 5.4).

``ProcessPoolExecutor`` no dice qué proceso ejecuta qué tarea ni detecta siempre a tiempo la muerte
de un worker creado bajo demanda (deuda D-DET). El supervisor lo resuelve con **ficheros vacíos
cuyo nombre es el dato**, sin canales compartidos ni claves privadas del ejecutor:

* ``w.<pid>``: el worker está registrado. Se borra al salir **limpiamente** (finalizador de
  ``multiprocessing``); si el proceso muere de forma abrupta el fichero queda: marca «caído».
* ``t.<batch>.<posición>.<pid>``: el worker ``pid`` está ejecutando la tarea ``posición`` del lote
  ``batch``. Se crea antes de cada tarea y se borra al terminar el lote; tras una caída indica qué
  tarea estaba en curso (la sospechosa).

El coordinador solo **lista** el directorio (nunca abre los ficheros), de modo que no hay
contención de lectura/escritura en Windows. Todo vive bajo el directorio temporal de la ejecución y
se elimina con ella.
"""

from __future__ import annotations

import contextlib
import os
import signal
from dataclasses import dataclass
from multiprocessing import util as mp_util
from pathlib import Path
from types import TracebackType

from portfolio_engine.parallel.shared_data import pid_alive

WORKER_PREFIX = "w."
TASK_PREFIX = "t."
SEPARATOR = "."
TASK_FIELDS = 4  # t, batch, posición, pid
ZOMBIE_STATE = "Z"


@dataclass(frozen=True, slots=True)
class TaskMarker:
    """Tarea que un worker declaró estar ejecutando."""

    batch_id: int
    position: int
    pid: int


@dataclass(frozen=True, slots=True)
class MarkerSnapshot:
    """Instantánea del directorio de marcas.

    Attributes:
        workers: PIDs registrados que no han salido limpiamente.
        tasks: por lote, la tarea en curso (la de mayor posición declarada).
    """

    workers: frozenset[int]
    tasks: dict[int, TaskMarker]


def register_worker(directory: str) -> None:
    """Registra el proceso actual; la marca se borra al salir limpiamente."""
    path = Path(directory) / f"{WORKER_PREFIX}{os.getpid()}"
    path.touch()
    mp_util.Finalize(None, _remove, args=(str(path),), exitpriority=0)


def _remove(path: str) -> None:
    with contextlib.suppress(OSError):
        Path(path).unlink()


class BatchMarker:
    """Marca las tareas de un lote en ejecución; al salir normalmente borra su última marca."""

    def __init__(self, directory: str | None, batch_id: int) -> None:
        self._directory = directory
        self._batch_id = batch_id
        self._current: str | None = None

    def __enter__(self) -> BatchMarker:
        return self

    def start(self, position: int) -> None:
        """Declara que la tarea ``position`` va a empezar (sustituye a la marca anterior)."""
        if self._directory is None:
            return
        name = SEPARATOR.join(("t", str(self._batch_id), str(position), str(os.getpid())))
        path = str(Path(self._directory) / name)
        Path(path).touch()
        if self._current is not None:
            _remove(self._current)
        self._current = path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Una excepción de Python (no una muerte abrupta) deja el lote bien resuelto: se limpia.
        if self._current is not None:
            _remove(self._current)


def scan(directory: str | Path) -> MarkerSnapshot:
    """Lee las marcas de ``directory`` (solo nombres de fichero)."""
    workers: set[int] = set()
    tasks: dict[int, TaskMarker] = {}
    try:
        names = os.listdir(directory)
    except OSError:
        return MarkerSnapshot(frozenset(), {})
    for name in names:
        if name.startswith(WORKER_PREFIX):
            suffix = name[len(WORKER_PREFIX) :]
            if suffix.isdigit():
                workers.add(int(suffix))
        elif name.startswith(TASK_PREFIX):
            parts = name.split(SEPARATOR)
            if len(parts) == TASK_FIELDS and all(part.isdigit() for part in parts[1:]):
                _, batch_id, position, pid = parts
                marker = TaskMarker(int(batch_id), int(position), int(pid))
                known = tasks.get(marker.batch_id)
                if known is None or marker.position > known.position:
                    tasks[marker.batch_id] = marker
    return MarkerSnapshot(frozenset(workers), tasks)


def clear(directory: str | Path) -> None:
    """Borra todas las marcas (tras descartar un pool)."""
    with contextlib.suppress(OSError):
        for name in os.listdir(directory):
            _remove(str(Path(directory) / name))


def _is_zombie(pid: int) -> bool:
    """Linux: un proceso terminado pero no recogido sigue «existiendo» para ``kill(pid, 0)``."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    after_name = text.rsplit(")", 1)[-1].split()
    return bool(after_name) and after_name[0] == ZOMBIE_STATE  # el primer campo es el estado


def process_is_gone(pid: int) -> bool:
    """``True`` si el proceso ya no existe (o es un zombi pendiente de recoger)."""
    return not pid_alive(pid) or _is_zombie(pid)


def terminate_process(pid: int) -> None:
    """Termina el proceso ``pid`` de forma inmediata (``TerminateProcess`` / ``SIGKILL``)."""
    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.kill(pid, kill_signal)
