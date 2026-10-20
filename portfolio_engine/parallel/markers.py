"""Marcas de progreso de los workers en un directorio de la ejecución (Bloque 5.4).

``ProcessPoolExecutor`` no dice qué proceso ejecuta qué tarea ni detecta siempre a tiempo la muerte
de un worker creado bajo demanda (deuda D-DET). El supervisor lo resuelve con **ficheros vacíos
cuyo nombre es el dato**, sin canales compartidos ni claves privadas del ejecutor:

* ``w.<pid>.<inicio>``: el worker está registrado; ``<inicio>`` es la hora de creación del proceso
  (identidad: un PID reutilizado por otro proceso tendría otra, véase :func:`start_token`). Se
  borra al salir **limpiamente** (finalizador de ``multiprocessing``); si el proceso muere de forma
  abrupta el fichero queda: marca «caído».
* ``t.<batch>.<posición>.<pid>``: el worker ``pid`` está ejecutando la tarea ``posición`` del lote
  ``batch``. Se crea antes de cada tarea y se borra al terminar el lote; tras una caída indica qué
  tarea estaba en curso (la sospechosa).

El coordinador solo **lista** el directorio (nunca abre los ficheros), de modo que no hay
contención de lectura/escritura en Windows. Todo vive bajo el directorio temporal de la ejecución y
se elimina con ella.
"""

from __future__ import annotations

import contextlib
import ctypes
import multiprocessing
import os
import signal
from dataclasses import dataclass, field
from multiprocessing import util as mp_util
from pathlib import Path
from types import TracebackType

from portfolio_engine.parallel.shared_data import pid_alive

WORKER_PREFIX = "w."
TASK_PREFIX = "t."
SEPARATOR = "."
TASK_FIELDS = 4  # t, batch, posición, pid
ZOMBIE_STATE = "Z"
LINUX_STARTTIME_INDEX = 19  # campo 22 de /proc/<pid>/stat, contado tras «pid (nombre)» y el estado
WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
FILETIME_HIGH_SHIFT = 32
FILETIME_COUNT = 4  # creación, salida, núcleo, usuario


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
        tokens: hora de creación registrada de cada worker (si la plataforma la facilita).
        tasks: por lote, la tarea en curso (la de mayor posición declarada).
    """

    workers: frozenset[int]
    tasks: dict[int, TaskMarker]
    tokens: dict[int, str] = field(default_factory=dict)


def _windows_start_token(pid: int) -> str | None:
    """Hora de creación (``FILETIME``) del proceso ``pid`` en Windows; ``None`` si no existe."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        *(ctypes.POINTER(wintypes.FILETIME),) * FILETIME_COUNT,
    )
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(WIN_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        created, exited, kernel_time, user_time = (
            wintypes.FILETIME() for _ in range(FILETIME_COUNT)
        )
        ok = kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return None
        return str((created.dwHighDateTime << FILETIME_HIGH_SHIFT) | created.dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def start_token(pid: int) -> str | None:
    """Identidad temporal de un proceso: su hora de creación (``None`` si no se puede obtener).

    Dos procesos que hayan tenido el mismo PID en momentos distintos tienen *tokens* distintos.
    Linux: campo ``starttime`` de ``/proc/<pid>/stat``; Windows: ``GetProcessTimes``. En otras
    plataformas devuelve ``None`` y la identidad se apoya solo en la pertenencia al coordinador.
    """
    if os.name == "nt":
        return _windows_start_token(pid)
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    fields = text.rsplit(")", 1)[-1].split()
    return fields[LINUX_STARTTIME_INDEX] if len(fields) > LINUX_STARTTIME_INDEX else None


def register_worker(directory: str) -> None:
    """Registra el proceso actual; la marca se borra al salir limpiamente."""
    token = start_token(os.getpid())
    suffix = "" if token is None else f"{SEPARATOR}{token}"
    path = Path(directory) / f"{WORKER_PREFIX}{os.getpid()}{suffix}"
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
    tokens: dict[int, str] = {}
    tasks: dict[int, TaskMarker] = {}
    try:
        names = os.listdir(directory)
    except OSError:
        return MarkerSnapshot(frozenset(), {})
    for name in names:
        if name.startswith(WORKER_PREFIX):
            pid_text, _, token = name[len(WORKER_PREFIX) :].partition(SEPARATOR)
            if pid_text.isdigit() and (not token or token.isdigit()):
                workers.add(int(pid_text))
                if token:
                    tokens[int(pid_text)] = token
        elif name.startswith(TASK_PREFIX):
            parts = name.split(SEPARATOR)
            if len(parts) == TASK_FIELDS and all(part.isdigit() for part in parts[1:]):
                _, batch_id, position, pid = parts
                marker = TaskMarker(int(batch_id), int(position), int(pid))
                known = tasks.get(marker.batch_id)
                if known is None or marker.position > known.position:
                    tasks[marker.batch_id] = marker
    return MarkerSnapshot(frozenset(workers), tasks, tokens)


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


def process_is_gone(pid: int, token: str | None = None) -> bool:
    """``True`` si el proceso registrado ya no existe, es un zombi o su PID lo usa otro proceso."""
    if not pid_alive(pid) or _is_zombie(pid):
        return True
    return token is not None and start_token(pid) != token


def owned_pids() -> frozenset[int]:
    """PIDs de los procesos hijo vivos de este coordinador (``multiprocessing.active_children``)."""
    return frozenset(
        child.pid for child in multiprocessing.active_children() if child.pid is not None
    )


def is_our_worker(pid: int, token: str | None = None) -> bool:
    """``True`` solo si ``pid`` es hijo de este proceso y, si se conoce, coincide su hora de inicio.

    Es la condición para poder terminar un proceso: el PID de una marca puede haber sido
    reutilizado por un proceso ajeno, y ninguno de los dos controles lo permitiría.
    """
    if pid not in owned_pids():
        return False
    return token is None or start_token(pid) == token


def terminate_process(pid: int) -> None:
    """Termina el proceso ``pid`` de forma inmediata (``TerminateProcess`` / ``SIGKILL``)."""
    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.kill(pid, kill_signal)


def terminate_owned(pid: int, token: str | None = None) -> bool:
    """Termina ``pid`` solo si es un worker nuestro (:func:`is_our_worker`); devuelve si lo hizo."""
    if not is_our_worker(pid, token):
        return False
    terminate_process(pid)
    return True
