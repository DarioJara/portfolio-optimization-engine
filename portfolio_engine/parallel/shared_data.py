"""Datos de mercado inmutables compartidos con los workers (MASTER_SPEC §58-59; PAR-004, PAR-005).

El coordinador **publica** una vez el :class:`~portfolio_engine.parallel.task.ExecutionContext`
(configuración + ``MarketSnapshot`` + hashes) y cada worker lo **adjunta** al arrancar. Las
referencias que viajan por el *pipe* de arranque son diminutas (una ruta o un nombre y hashes);
ninguna matriz global se envía por tarea.

Modos (:class:`~portfolio_engine.config.parallel_config.SharedDataMode`):

``BUNDLE_FILE``
    Modo de B5.2 y *fallback*: un fichero con el contexto completo, deserializado (copiado) por cada
    worker.
``FILE_MMAP``
    ``pickle`` de protocolo 5 con los *buffers* de los arrays **fuera de banda**: la cabecera es
    pequeña y los arrays se escriben una vez en un único fichero que cada worker proyecta en memoria
    de solo lectura (``mmap``). Al deserializar, los arrays son vistas sin copia sobre esa
    proyección (las páginas físicas se comparten entre workers por la caché de páginas del sistema).
``SHARED_MEMORY``
    Igual, con los arrays en un segmento de ``multiprocessing.shared_memory`` creado por el
    coordinador.

Seguridad e integridad:

* Toda referencia se verifica al adjuntar: SHA-256 de la cabecera y de **cada** *buffer* antes de
  deserializar. ``pickle`` solo se aplica a ficheros de esta misma ejecución, escritos por el
  coordinador en un directorio temporal privado y verificados por hash (no hay lectura de orígenes
  externos).
* Los arrays adjuntos no son editables: los *buffers* se entregan como ``memoryview`` de solo
  lectura, de modo que ``flags.writeable`` es ``False`` y escribir lanza ``ValueError``.
* Sobre las copias defensivas de B1–B4 (``readonly_float_array`` copia al **construir**): la
  deserialización no ejecuta ``__post_init__``, por lo que no vuelve a copiar; los objetos ya fueron
  validados al construirse en el coordinador y su contenido está protegido por los hashes. No se
  elude ninguna validación matemática: ningún motor construye un ``RiskModel`` desde estas vistas.
  Los motores hacen copias pequeñas (``Σ_C`` de la composición), nunca de la ``Σ`` global.
* Ciclo de vida: el coordinador crea un directorio ``portfolio_engine_run_*`` con ``owner.json``
  (PID, momento y nombre de segmento) y lo elimina —y descarta el segmento— en ``finally``. Ante
  muerte brusca del coordinador quedan huérfanos: :func:`inventory_orphans` los lista (PID del
  propietario muerto) y :func:`remove_orphans` los elimina.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import mmap
import os
import pickle
import secrets
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing import resource_tracker, shared_memory
from pathlib import Path

from portfolio_engine.config.parallel_config import SharedDataMode
from portfolio_engine.exceptions import PortfolioEngineError
from portfolio_engine.parallel.task import ExecutionContext

#: Alineación de cada *buffer* dentro del bloque de datos (línea de caché).
ALIGNMENT = 64
#: Protocolo de ``pickle`` con *buffers* fuera de banda (PEP 574).
PICKLE_OUT_OF_BAND_PROTOCOL = 5
#: Bytes aleatorios del sufijo del nombre de un segmento de memoria compartida.
SHM_TOKEN_BYTES = 6
#: Partes del nombre ``pe_<pid>_<token>`` de un segmento de este paquete.
SHM_NAME_PARTS = 3
#: Reintentos y espera (s) al borrar el directorio de una ejecución: en Windows el borrado puede
#: fallar mientras el sistema libera los manejadores de un worker recién terminado.
REMOVE_RETRIES = 50
REMOVE_DELAY_SECONDS = 0.1
#: Windows: ``PROCESS_QUERY_LIMITED_INFORMATION`` y código de salida ``STILL_ACTIVE``.
WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WIN_STILL_ACTIVE = 259
RUN_DIR_PREFIX = "portfolio_engine_run_"
SHM_PREFIX = "pe_"
OWNER_FILE = "owner.json"
HEADER_FILE = "snapshot_header.pkl"
MANIFEST_FILE = "snapshot_buffers.json"
DATA_FILE = "snapshot_data.bin"
BUNDLE_FILE_NAME = "worker_bundle.pkl"
SHM_DIRECTORY = Path("/dev/shm")


class SharedDataError(PortfolioEngineError):
    """Fallo de publicación, integridad o adjunción de los datos compartidos."""


# --------------------------------------------------------------------------- fichero de arranque


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
    with tempfile.TemporaryDirectory(prefix=RUN_DIR_PREFIX) as directory:
        yield write_worker_bundle(Path(directory), context)


# ------------------------------------------------------------------------ buffers fuera de banda


@dataclass(frozen=True, slots=True)
class BufferRef:
    """Posición y hash de un *buffer* dentro del bloque de datos."""

    offset: int
    length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SharedSnapshotHandle:
    """Referencia diminuta a un snapshot publicado con *buffers* fuera de banda.

    Attributes:
        mode: ``FILE_MMAP`` o ``SHARED_MEMORY``.
        header_path: fichero con el ``pickle`` de cabecera (sin los datos de los arrays).
        header_sha256: SHA-256 de la cabecera.
        manifest_path: fichero JSON con la posición y el hash de cada *buffer* (en el orden en que
            el ``pickle`` los consume); su tamaño no viaja en la referencia (tamaño constante).
        manifest_sha256: SHA-256 del manifiesto.
        data_location: ruta del fichero de datos (``FILE_MMAP``) o nombre del segmento.
        data_length: tamaño del bloque de datos en bytes.
    """

    mode: SharedDataMode
    header_path: str
    header_sha256: str
    manifest_path: str
    manifest_sha256: str
    data_location: str
    data_length: int


#: Lo que recibe el *initializer* de un worker.
SnapshotHandle = WorkerBundle | SharedSnapshotHandle


@dataclass(frozen=True, slots=True)
class PublicationInfo:
    """Medidas de la publicación (para benchmarks y trazabilidad)."""

    mode: SharedDataMode
    handle_bytes: int
    header_bytes: int
    data_bytes: int
    n_buffers: int
    publish_seconds: float


@dataclass(frozen=True, slots=True)
class PublishedSnapshot:
    """Referencia publicada y sus medidas."""

    handle: SnapshotHandle
    info: PublicationInfo


def _remove_tree(directory: Path) -> bool:
    """Borra ``directory`` reintentando mientras Windows libera manejadores."""
    for _ in range(REMOVE_RETRIES):
        shutil.rmtree(directory, ignore_errors=True)
        if not directory.exists():
            return True
        time.sleep(REMOVE_DELAY_SECONDS)
    return False


def _aligned(offset: int) -> int:
    return -(-offset // ALIGNMENT) * ALIGNMENT


def _write_owner(directory: Path, mode: SharedDataMode, shm_name: str | None) -> None:
    owner = {"pid": os.getpid(), "created": time.time(), "mode": mode.value, "shm": shm_name}
    (directory / OWNER_FILE).write_text(json.dumps(owner), encoding="utf-8")


def _publish_out_of_band(
    directory: Path, context: ExecutionContext, mode: SharedDataMode, shm_name: str | None
) -> tuple[SharedSnapshotHandle, shared_memory.SharedMemory | None]:
    buffers: list[pickle.PickleBuffer] = []
    header = pickle.dumps(
        context, protocol=PICKLE_OUT_OF_BAND_PROTOCOL, buffer_callback=buffers.append
    )
    raws = [buffer.raw() for buffer in buffers]
    refs: list[BufferRef] = []
    cursor = 0
    for raw in raws:
        cursor = _aligned(cursor)
        refs.append(BufferRef(cursor, raw.nbytes, hashlib.sha256(raw).hexdigest()))
        cursor += raw.nbytes
    total = max(cursor, 1)
    header_path = directory / HEADER_FILE
    header_path.write_bytes(header)
    segment: shared_memory.SharedMemory | None = None
    if mode is SharedDataMode.FILE_MMAP:
        location = str(directory / DATA_FILE)
        with open(location, "wb") as handle:
            handle.truncate(total)
            for ref, raw in zip(refs, raws, strict=True):
                handle.seek(ref.offset)
                handle.write(raw)
    else:
        assert shm_name is not None
        segment = shared_memory.SharedMemory(name=shm_name, create=True, size=total)
        target = segment.buf
        assert target is not None
        for ref, raw in zip(refs, raws, strict=True):
            target[ref.offset : ref.offset + ref.length] = raw
        location = shm_name
    manifest = json.dumps([[ref.offset, ref.length, ref.sha256] for ref in refs]).encode()
    manifest_path = directory / MANIFEST_FILE
    manifest_path.write_bytes(manifest)
    handle_obj = SharedSnapshotHandle(
        mode=mode,
        header_path=str(header_path),
        header_sha256=hashlib.sha256(header).hexdigest(),
        manifest_path=str(manifest_path),
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        data_location=location,
        data_length=total,
    )
    return handle_obj, segment


@contextmanager
def publish_snapshot(
    context: ExecutionContext, mode: SharedDataMode, *, root: Path | None = None
) -> Iterator[PublishedSnapshot]:
    """Publica ``context`` según ``mode`` y lo elimina (fichero, directorio, segmento) al salir.

    La limpieza ocurre en ``finally``: tanto tras un éxito como tras una excepción del llamador.
    """
    started = time.perf_counter()
    directory = Path(tempfile.mkdtemp(prefix=RUN_DIR_PREFIX, dir=root))
    segment: shared_memory.SharedMemory | None = None
    try:
        shm_name = f"{SHM_PREFIX}{os.getpid()}_{secrets.token_hex(SHM_TOKEN_BYTES)}"
        _write_owner(directory, mode, shm_name if mode is SharedDataMode.SHARED_MEMORY else None)
        handle: SnapshotHandle
        if mode is SharedDataMode.BUNDLE_FILE:
            handle = write_worker_bundle(directory, context)
            header_bytes = Path(handle.path).stat().st_size
            data_bytes, n_buffers = 0, 0
        else:
            handle, segment = _publish_out_of_band(directory, context, mode, shm_name)
            header_bytes = Path(handle.header_path).stat().st_size
            data_bytes, n_buffers = handle.data_length, len(read_buffer_table(handle))
        info = PublicationInfo(
            mode=mode,
            handle_bytes=len(pickle.dumps(handle, protocol=pickle.HIGHEST_PROTOCOL)),
            header_bytes=header_bytes,
            data_bytes=data_bytes,
            n_buffers=n_buffers,
            publish_seconds=time.perf_counter() - started,
        )
        yield PublishedSnapshot(handle, info)
    finally:
        if segment is not None:
            segment.close()
            with contextlib.suppress(FileNotFoundError):  # ya eliminado
                segment.unlink()
        _remove_tree(directory)


# ------------------------------------------------------------------------------------ adjuntar


def _attach_segment(name: str) -> shared_memory.SharedMemory:
    """Adjunta un segmento existente sin que el worker pase a ser su propietario."""
    try:  # Python >= 3.13: el worker no registra el segmento en el rastreador de recursos
        return shared_memory.SharedMemory(  # type: ignore[call-arg,unused-ignore]
            name=name, create=False, track=False
        )
    except TypeError:
        # Python < 3.13: adjuntar registra el segmento en el rastreador, compartido con el
        # coordinador. Registrarlo (y anularlo) borraría el registro del propietario y el
        # `unlink` del coordinador daría un KeyError en el rastreador; por eso no se registra.
        original = resource_tracker.register

        def register_except_shared_memory(name: str, rtype: str) -> None:
            if rtype != "shared_memory":
                original(name, rtype)

        resource_tracker.register = register_except_shared_memory  # type: ignore[assignment]
        try:
            return shared_memory.SharedMemory(name=name, create=False)
        finally:
            resource_tracker.register = original


@dataclass(slots=True)
class Attachment:
    """Recursos que deben vivir mientras se usen los arrays adjuntos."""

    resources: list[object]

    def release(self) -> None:
        """Libera la proyección o el segmento. Exige no conservar referencias a los arrays."""
        for resource in reversed(self.resources):
            close = getattr(resource, "close", None) or getattr(resource, "release", None)
            if close is not None:
                close()
        self.resources.clear()


def read_buffer_table(handle: SharedSnapshotHandle) -> tuple[BufferRef, ...]:
    """Tabla de *buffers* del manifiesto, tras verificar su SHA-256."""
    manifest = Path(handle.manifest_path).read_bytes()
    if hashlib.sha256(manifest).hexdigest() != handle.manifest_sha256:
        raise SharedDataError("El manifiesto del snapshot no coincide con su hash (integridad).")
    return tuple(BufferRef(int(o), int(n), str(h)) for o, n, h in json.loads(manifest))


def attach_snapshot(handle: SnapshotHandle) -> tuple[ExecutionContext, Attachment]:
    """Reconstruye el contexto desde ``handle`` tras verificar los hashes (cabecera y *buffers*)."""
    if isinstance(handle, WorkerBundle):
        return load_worker_bundle(handle), Attachment([])
    header = Path(handle.header_path).read_bytes()
    if hashlib.sha256(header).hexdigest() != handle.header_sha256:
        raise SharedDataError("La cabecera del snapshot no coincide con su hash (integridad).")
    table = read_buffer_table(handle)
    attachment = Attachment([])
    try:
        if handle.mode is SharedDataMode.FILE_MMAP:
            with open(handle.data_location, "rb") as data_file:
                mapped = mmap.mmap(data_file.fileno(), 0, access=mmap.ACCESS_READ)
            attachment.resources.append(mapped)
            view = memoryview(mapped)
        else:
            segment = _attach_segment(handle.data_location)
            attachment.resources.append(segment)
            buffer = segment.buf
            assert buffer is not None
            view = buffer.toreadonly()
        attachment.resources.append(view)
        for index, ref in enumerate(table):  # verificación; el trozo se libera al salir
            with view[ref.offset : ref.offset + ref.length] as chunk:
                if hashlib.sha256(chunk).hexdigest() != ref.sha256:
                    raise SharedDataError(
                        f"El buffer {index} del snapshot no coincide con su hash."
                    )
        chunks = [view[ref.offset : ref.offset + ref.length] for ref in table]
        context = pickle.loads(header, buffers=chunks)  # cabecera propia, verificada por hash
        if not isinstance(context, ExecutionContext):
            raise SharedDataError("La cabecera del snapshot no contiene un ExecutionContext.")
    except BaseException:
        with contextlib.suppress(BufferError):  # nada queda en uso si falló la verificación
            attachment.release()
        raise
    return context, attachment


# ------------------------------------------------------------------------------------ huérfanos


def pid_alive(pid: int) -> bool:
    """``True`` si existe un proceso con ese PID (sin matar ni señalizar nada)."""
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        process = kernel.OpenProcess(WIN_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return False
        code = ctypes.c_ulong()
        ok = kernel.GetExitCodeProcess(process, ctypes.byref(code))
        kernel.CloseHandle(process)
        return bool(ok) and code.value == WIN_STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True, slots=True)
class OrphanInventory:
    """Recursos de ejecuciones cuyo coordinador ya no existe."""

    directories: tuple[Path, ...]
    shared_memory: tuple[str, ...]

    @property
    def empty(self) -> bool:
        """``True`` si no hay huérfanos."""
        return not self.directories and not self.shared_memory


def _owner_pid(directory: Path) -> int | None:
    try:
        owner = json.loads((directory / OWNER_FILE).read_text(encoding="utf-8"))
        return int(owner["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def inventory_orphans(root: Path | None = None, *, min_age_seconds: float) -> OrphanInventory:
    """Lista directorios ``portfolio_engine_run_*`` y segmentos ``pe_*`` huérfanos.

    Un directorio es huérfano si su ``owner.json`` apunta a un PID que ya no existe, o si no tiene
    propietario legible y es más antiguo que ``min_age_seconds`` (p. ej. restos de B5.2). Los
    segmentos de ``/dev/shm`` (Linux) se asocian al PID codificado en su nombre.
    """
    base = root if root is not None else Path(tempfile.gettempdir())
    now = time.time()
    directories = []
    for directory in sorted(base.glob(f"{RUN_DIR_PREFIX}*")):
        if not directory.is_dir():
            continue
        pid = _owner_pid(directory)
        if pid is not None:
            orphan = not pid_alive(pid)
        else:
            orphan = now - directory.stat().st_mtime >= min_age_seconds
        if orphan:
            directories.append(directory)
    segments = []
    if SHM_DIRECTORY.is_dir():
        for entry in sorted(SHM_DIRECTORY.glob(f"{SHM_PREFIX}*")):
            parts = entry.name.split("_")
            if len(parts) >= SHM_NAME_PARTS and parts[1].isdigit() and not pid_alive(int(parts[1])):
                segments.append(entry.name)
    return OrphanInventory(tuple(directories), tuple(segments))


def remove_orphans(inventory: OrphanInventory) -> int:
    """Elimina los huérfanos de ``inventory``. Devuelve cuántos recursos se eliminaron."""
    removed = 0
    for directory in inventory.directories:
        shutil.rmtree(directory, ignore_errors=True)
        removed += 0 if directory.exists() else 1
    for name in inventory.shared_memory:
        try:
            segment = shared_memory.SharedMemory(name=name, create=False)
        except FileNotFoundError:
            continue
        segment.close()
        segment.unlink()
        removed += 1
    return removed
