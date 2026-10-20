"""Diario local de ejecución: recuperación y reanudación sin ``pickle`` (Bloque 5.4; P-05, P-08).

Un diario es un **directorio local** con formato no ejecutable (JSON, véase ``parallel.codec``):

```
<directorio>/
  manifest.json          identidad de la ejecución (hashes, versiones) + suma SHA-256
  shards/s-*.json        un fichero por grupo de resultados finales restaurables (append-only)
  events.jsonl           eventos de recuperación (una línea JSON con suma SHA-256 por evento)
  .lock                  bloqueo del sistema operativo mientras la ejecución está abierta
```

Garantías (cada una con su prueba):

* **Escritura atómica**: cada fichero se escribe en un temporal del mismo directorio, se sincroniza
  y se renombra (``os.replace``); un fallo a mitad deja o el fichero completo o ninguno. Los
  temporales huérfanos se eliminan al abrir.
* **Detección de corrupción**: cada *shard* lleva longitud y SHA-256 de su cuerpo en una cabecera
  propia; uno truncado o alterado se detecta, se aparta (``.corrupt``) y sus tareas se vuelven a
  ejecutar; el resto se conserva.
* **Reanudación verificada**: el manifiesto fija formato, ``ConfigHash``, ``snapshot_key``, hash del
  código (``portfolio_engine``), versiones de librerías y hash del conjunto de tareas; cualquier
  diferencia rechaza la reanudación **sin tocar el diario**.
* **Una sola ejecución por diario**: un bloqueo del sistema operativo (se libera si el proceso
  muere) impide dos coordinadores simultáneos sobre el mismo directorio.
* **Nunca ``pickle``**: el módulo no importa ``pickle``; los resultados se decodifican con una lista
  blanca de tipos (``parallel.codec``).

Solo se restauran los estados que describen un resultado **determinista de la tarea**
(``COMPLETED`` y ``FAILED_INPUT_VALIDATION``). Una caída, un plazo, una cancelación o una
excepción pueden deberse al entorno: esas tareas se vuelven a ejecutar al reanudar y solo dejan un
evento (sin datos de cartera).

Datos sensibles: el diario contiene **resultados de optimización** (pesos por activo e
identificadores de cartera), no las solicitudes ni la configuración completa; nunca contiene
credenciales. Es opt-in doble (``recovery.journal_enabled`` y un directorio explícito) y, en POSIX,
se crea con permisos ``0700``/``0600``; en Windows hereda las ACL del directorio padre.
La integridad es contra corrupción accidental, no contra un atacante con acceso de escritura.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import os
import secrets
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import portfolio_engine
from portfolio_engine.exceptions import PortfolioEngineError
from portfolio_engine.parallel.codec import decode, encode
from portfolio_engine.parallel.task import ExecutionContext, ExecutionStatus, TaskResult
from portfolio_engine.utils.hashing import canonical_json, sha256_hex

JOURNAL_FORMAT_VERSION = 1
MANIFEST_FILE = "manifest.json"
SHARD_DIRECTORY = "shards"
SHARD_PREFIX = "s-"
SHARD_SUFFIX = ".json"
CORRUPT_SUFFIX = ".corrupt"
TEMP_SUFFIX = ".tmp"
EVENTS_FILE = "events.jsonl"
LOCK_FILE = ".lock"
SEQUENCE_DIGITS = 10
SHA_PREFIX_CHARS = 16
TOKEN_BYTES = 6
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
#: Librerías cuyo cambio de versión invalida una reanudación (afectan a la numérica).
TRACKED_LIBRARIES = ("numpy", "scipy", "osqp", "clarabel", "pyscipopt", "threadpoolctl")
#: Estados cuyo resultado es una función determinista de la tarea: se restauran al reanudar.
RESTORABLE_STATUSES = frozenset(
    {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED_INPUT_VALIDATION}
)


class JournalError(PortfolioEngineError):
    """Error del diario (formato, estado del directorio o escritura)."""


class JournalIncompatibleError(JournalError):
    """La reanudación se rechaza: el diario pertenece a otra ejecución."""


class JournalLockedError(JournalError):
    """Otro proceso mantiene abierto el diario."""


def bounded(text: str, limit: int) -> str:
    """Recorta ``text`` a ``limit`` caracteres (observabilidad acotada)."""
    return text if len(text) <= limit else text[:limit]


# -------------------------------------------------------------------------------- identidad


def code_hash() -> str:
    """SHA-256 del código fuente de ``portfolio_engine`` (rutas relativas y contenido ordenados)."""
    root = Path(portfolio_engine.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def library_versions() -> tuple[tuple[str, str], ...]:
    """Versiones instaladas de las librerías numéricas relevantes."""
    versions = []
    for name in TRACKED_LIBRARIES:
        try:
            versions.append((name, importlib.metadata.version(name)))
        except importlib.metadata.PackageNotFoundError:
            versions.append((name, "NOT_INSTALLED"))
    return tuple(versions)


@dataclass(frozen=True, slots=True)
class JournalIdentity:
    """Lo que debe coincidir para que una reanudación sea válida.

    Attributes:
        format_version: versión del formato del diario.
        config_hash: ``ConfigHash`` del motor.
        snapshot_key: identidad de contenido del ``MarketSnapshot``.
        code_hash: hash del código de ``portfolio_engine``.
        request_set_hash: hash del conjunto de ``TaskID`` (solicitudes + configuración + datos).
        n_tasks: número de tareas.
        python_version: versión de Python.
        library_versions: versiones de las librerías numéricas.
    """

    format_version: int
    config_hash: str
    snapshot_key: str
    code_hash: str
    request_set_hash: str
    n_tasks: int
    python_version: str
    library_versions: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        """Representación JSON-able."""
        return {
            "format_version": self.format_version,
            "config_hash": self.config_hash,
            "snapshot_key": self.snapshot_key,
            "code_hash": self.code_hash,
            "request_set_hash": self.request_set_hash,
            "n_tasks": self.n_tasks,
            "python_version": self.python_version,
            "library_versions": [list(item) for item in self.library_versions],
        }

    @classmethod
    def from_dict(cls, data: object) -> JournalIdentity:
        """Reconstruye la identidad; ``JournalError`` si el documento está mal formado."""
        try:
            if not isinstance(data, dict):
                raise TypeError("identidad no es un objeto")
            return cls(
                format_version=int(data["format_version"]),
                config_hash=str(data["config_hash"]),
                snapshot_key=str(data["snapshot_key"]),
                code_hash=str(data["code_hash"]),
                request_set_hash=str(data["request_set_hash"]),
                n_tasks=int(data["n_tasks"]),
                python_version=str(data["python_version"]),
                library_versions=tuple((str(a), str(b)) for a, b in data["library_versions"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise JournalError("El manifiesto del diario está mal formado.") from error


def build_identity(
    context: ExecutionContext, task_ids: Sequence[str], *, code: str | None = None
) -> JournalIdentity:
    """Identidad esperada de una ejecución con ``context`` y las tareas ``task_ids``."""
    return JournalIdentity(
        format_version=JOURNAL_FORMAT_VERSION,
        config_hash=context.config_hash,
        snapshot_key=context.snapshot_key,
        code_hash=code_hash() if code is None else code,
        request_set_hash=sha256_hex(canonical_json(sorted(task_ids))),
        n_tasks=len(task_ids),
        python_version=sys.version.split()[0],
        library_versions=library_versions(),
    )


def incompatibilities(stored: JournalIdentity, expected: JournalIdentity) -> list[str]:
    """Campos que impiden reanudar (lista vacía = compatible)."""
    found = []
    for name in stored.as_dict():
        if getattr(stored, name) != getattr(expected, name):
            found.append(name)
    return found


# ------------------------------------------------------------------------- E/S segura


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return  # Windows no permite abrir directorios para sincronizarlos
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, data: bytes) -> None:
    """Escribe ``data`` en ``path`` de forma atómica (temporal + fsync + ``os.replace``)."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(TOKEN_BYTES)}{TEMP_SUFFIX}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise
    _fsync_directory(path.parent)


def _json_bytes(document: object) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _is_blank(root: Path) -> bool:
    """``True`` si ``root`` no contiene un diario (ni siquiera uno interrumpido con datos).

    El bloqueo y un directorio de *shards* vacío no cuentan: son lo único que deja una ejecución
    que murió antes de escribir su manifiesto.
    """
    if (root / MANIFEST_FILE).exists():
        return False
    entries = [entry for entry in root.iterdir() if entry.name != LOCK_FILE]
    return all(entry.name == SHARD_DIRECTORY and not any(entry.iterdir()) for entry in entries)


class _FileLock:
    """Bloqueo exclusivo del sistema operativo sobre un fichero (se libera al morir el proceso)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._descriptor: int | None = None

    def acquire(self) -> None:
        descriptor = os.open(self._path, os.O_RDWR | os.O_CREAT, PRIVATE_FILE_MODE)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(descriptor)
            raise JournalLockedError(
                f"El diario {self._path.parent} está abierto por otra ejecución."
            ) from error
        self._descriptor = descriptor

    def release(self) -> None:
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        try:
            if sys.platform == "win32":
                import msvcrt

                with contextlib.suppress(OSError):
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


# ---------------------------------------------------------------------------- manifiesto


def _read_manifest(directory: Path) -> tuple[dict[str, Any], JournalIdentity]:
    path = directory / MANIFEST_FILE
    try:
        document = json.loads(path.read_bytes())
        body = document["body"]
        checksum = document["sha256"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise JournalError(f"Manifiesto del diario ilegible o ausente: {path}.") from error
    if sha256_hex(canonical_json(body)) != checksum:
        raise JournalError("El manifiesto del diario no supera su suma de verificación.")
    return body, JournalIdentity.from_dict(body.get("identity"))


# ---------------------------------------------------------------------------- resultados


@dataclass(frozen=True, slots=True)
class JournalScan:
    """Resultado de revisar el diario al abrirlo.

    Attributes:
        valid_shards: ficheros íntegros leídos.
        corrupt_shards: ficheros que no superaron la verificación (se apartan como ``.corrupt``).
        restorable_tasks: tareas distintas con resultado restaurable.
        duplicate_tasks: tareas presentes en más de un fichero íntegro (se conserva la primera).
        temporaries_removed: temporales huérfanos eliminados.
    """

    valid_shards: int
    corrupt_shards: tuple[str, ...]
    restorable_tasks: int
    duplicate_tasks: int
    temporaries_removed: int


def _shard_name(first_sequence: int, body_hash: str) -> str:
    position = f"{first_sequence:0{SEQUENCE_DIGITS}d}"
    return f"{SHARD_PREFIX}{position}-{body_hash[:SHA_PREFIX_CHARS]}{SHARD_SUFFIX}"


def _read_shard(
    path: Path, run_id: str, expected: Mapping[str, tuple[int, str]]
) -> list[TaskResult]:
    """Lee y verifica un *shard*; ``JournalError`` ante cualquier inconsistencia."""
    try:
        raw = path.read_bytes()
        header_line, _, body = raw.partition(b"\n")
        header = json.loads(header_line)
        if (
            header["format"] != JOURNAL_FORMAT_VERSION
            or header["run_id"] != run_id
            or header["body_bytes"] != len(body)
            or header["body_sha256"] != hashlib.sha256(body).hexdigest()
        ):
            raise JournalError("cabecera, longitud o suma de verificación incorrectas")
        records = json.loads(body)
        results = []
        for record in records:
            result = decode(record["result"])
            known = expected.get(record["task_id"])
            if (
                not isinstance(result, TaskResult)
                or known is None
                or result.task_id != record["task_id"]
                or result.sequence_id != known[0]
                or result.portfolio_id != known[1]
                or result.execution_status not in RESTORABLE_STATUSES
            ):
                raise JournalError("registro ajeno a esta ejecución o no restaurable")
            results.append(result)
        return results
    except JournalError:
        raise
    except Exception as error:  # cualquier fallo al leer un shard lo aparta (L-1)
        # Un shard con suma válida pero contenido inválido (dataclass que no valida, anidamiento
        # excesivo, tipo desconocido…) es un shard corrupto: se aparta y sus tareas se re-ejecutan.
        raise JournalError(f"{path.name}: {type(error).__name__}") from error


class RunJournal:
    """Diario abierto de una ejecución (use :meth:`open` y cierre con :meth:`close`)."""

    def __init__(
        self,
        directory: Path,
        run_id: str,
        identity: JournalIdentity,
        lock: _FileLock,
        scan: JournalScan,
        restored: dict[str, TaskResult],
    ) -> None:
        self._directory = directory
        self._run_id = run_id
        self._identity = identity
        self._lock = lock
        self._scan = scan
        self._restored = restored
        self._events: IO[bytes] | None = None
        self._event_count = 0

    # ------------------------------------------------------------------------- apertura

    @classmethod
    def open(
        cls,
        directory: str | Path,
        identity: JournalIdentity,
        expected: Mapping[str, tuple[int, str]],
        *,
        resume: bool,
    ) -> RunJournal:
        """Abre (``resume=False``: crea) el diario de ``directory``.

        Args:
            directory: carpeta local del diario.
            identity: identidad de la ejecución actual.
            expected: ``TaskID`` → (``SequenceID``, ``PortfolioID``) de todas las tareas.
            resume: ``True`` reanuda un diario existente y compatible; ``False`` exige un
                directorio vacío o inexistente (nunca se sobrescribe un diario).

        Raises:
            JournalIncompatibleError: la reanudación no es compatible (el diario no se modifica).
            JournalLockedError: otra ejecución tiene abierto el diario.
            JournalError: otro problema de formato o de estado del directorio.
        """
        root = Path(directory)
        if resume:
            if not (root / MANIFEST_FILE).is_file():
                raise JournalError(f"No hay un diario que reanudar en {root}.")
        elif root.exists() and not _is_blank(root):
            raise JournalError(
                f"{root} no está vacío: use resume=True para reanudar o elija otro directorio."
            )
        root.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
        lock = _FileLock(root / LOCK_FILE)
        lock.acquire()
        try:
            return cls._open_locked(root, identity, expected, resume, lock)
        except BaseException:
            lock.release()
            raise

    @classmethod
    def _open_locked(
        cls,
        root: Path,
        identity: JournalIdentity,
        expected: Mapping[str, tuple[int, str]],
        resume: bool,
        lock: _FileLock,
    ) -> RunJournal:
        shards = root / SHARD_DIRECTORY
        if resume:
            body, stored = _read_manifest(root)
            differences = incompatibilities(stored, identity)
            if differences:
                raise JournalIncompatibleError(
                    f"La reanudación se rechaza: el diario difiere en {sorted(differences)}."
                )
            run_id = str(body["run_id"])
            restored, scan = cls._scan_shards(shards, run_id, expected)
            journal = cls(root, run_id, identity, lock, scan, restored)
            journal.event("resumed", restored=len(restored), corrupt=len(scan.corrupt_shards))
            return journal
        run_id = uuid.uuid4().hex
        shards.mkdir(exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
        body = {
            "run_id": run_id,
            "created_utc": datetime.now(UTC).isoformat(),
            "identity": identity.as_dict(),
        }
        document = {"body": body, "sha256": sha256_hex(canonical_json(body))}
        _atomic_write(root / MANIFEST_FILE, _json_bytes(document))
        scan = JournalScan(0, (), 0, 0, 0)
        journal = cls(root, run_id, identity, lock, scan, {})
        journal.event("created", n_tasks=identity.n_tasks)
        return journal

    @staticmethod
    def _scan_shards(
        shards: Path, run_id: str, expected: Mapping[str, tuple[int, str]]
    ) -> tuple[dict[str, TaskResult], JournalScan]:
        removed = 0
        for temporary in shards.glob(f".*{TEMP_SUFFIX}"):
            with contextlib.suppress(OSError):
                temporary.unlink()
                removed += 1
        restored: dict[str, TaskResult] = {}
        corrupt: list[str] = []
        duplicates = 0
        valid = 0
        for path in sorted(shards.glob(f"{SHARD_PREFIX}*{SHARD_SUFFIX}")):
            try:
                results = _read_shard(path, run_id, expected)
            except JournalError:
                corrupt.append(path.name)
                with contextlib.suppress(OSError):
                    os.replace(path, path.with_name(path.name + CORRUPT_SUFFIX))
                continue
            valid += 1
            for result in results:
                if result.task_id in restored:
                    duplicates += 1
                else:
                    restored[result.task_id] = result
        scan = JournalScan(valid, tuple(corrupt), len(restored), duplicates, removed)
        return restored, scan

    # ---------------------------------------------------------------------------- uso

    @property
    def run_id(self) -> str:
        """Identificador único de esta ejecución (fijado al crear el diario)."""
        return self._run_id

    @property
    def scan(self) -> JournalScan:
        """Resumen de la revisión del diario al abrirlo."""
        return self._scan

    @property
    def restored(self) -> Mapping[str, TaskResult]:
        """Resultados restaurables encontrados al abrir (``TaskID`` → resultado)."""
        return self._restored

    def record(self, results: Sequence[TaskResult]) -> None:
        """Anota resultados finales: los restaurables en un *shard*; el resto, solo como evento."""
        keep = [result for result in results if result.execution_status in RESTORABLE_STATUSES]
        dropped = [
            result for result in results if result.execution_status not in RESTORABLE_STATUSES
        ]
        if keep:
            records = [
                {
                    "task_id": result.task_id,
                    "sequence_id": result.sequence_id,
                    "portfolio_id": result.portfolio_id,
                    "status": result.execution_status.value,
                    "result": encode(result),
                }
                for result in keep
            ]
            body = _json_bytes(records)
            body_hash = hashlib.sha256(body).hexdigest()
            header = _json_bytes(
                {
                    "format": JOURNAL_FORMAT_VERSION,
                    "run_id": self._run_id,
                    "records": len(records),
                    "body_bytes": len(body),
                    "body_sha256": body_hash,
                }
            )
            first = min(result.sequence_id for result in keep if result.sequence_id is not None)
            name = _shard_name(first, body_hash)
            _atomic_write(self._directory / SHARD_DIRECTORY / name, header + b"\n" + body)
        if dropped:
            statuses: dict[str, int] = {}
            for result in dropped:
                key = result.execution_status.value
                statuses[key] = statuses.get(key, 0) + 1
            self.event("not_restorable", **statuses)

    def event(self, kind: str, **data: str | int | float | bool) -> None:
        """Añade un evento de recuperación (sin datos de cartera)."""
        if self._events is None:
            self._events = open(  # noqa: SIM115 - se cierra en close()
                self._directory / EVENTS_FILE, "ab"
            )
        self._event_count += 1
        body = {
            "seq": self._event_count,
            "time": datetime.now(UTC).isoformat(),
            "kind": kind,
            "data": data,
        }
        line = {**body, "sha256": sha256_hex(canonical_json(body))}
        self._events.write(_json_bytes(line) + b"\n")
        self._events.flush()
        os.fsync(self._events.fileno())

    def close(self) -> None:
        """Cierra el diario y libera el bloqueo (idempotente)."""
        try:
            if self._events is not None:
                self._events.close()
                self._events = None
        finally:
            self._lock.release()


# --------------------------------------------------------------------------- inspección


def inspect_journal(directory: str | Path) -> dict[str, Any]:
    """Resumen verificable de un diario **sin modificarlo** (lo usa la CLI local).

    Devuelve manifiesto, número de *shards* íntegros/corruptos (sin decodificar resultados), y
    eventos íntegros/inválidos. Lanza :class:`JournalError` si el manifiesto es ilegible.
    """
    root = Path(directory)
    body, identity = _read_manifest(root)
    valid = []
    corrupt = []
    tasks = 0
    for path in sorted((root / SHARD_DIRECTORY).glob(f"{SHARD_PREFIX}*{SHARD_SUFFIX}")):
        try:
            header_line, _, shard_body = path.read_bytes().partition(b"\n")
            header = json.loads(header_line)
            if (
                header["body_bytes"] != len(shard_body)
                or header["body_sha256"] != hashlib.sha256(shard_body).hexdigest()
                or header["run_id"] != body["run_id"]
            ):
                raise JournalError("suma de verificación")
            valid.append(path.name)
            tasks += int(header["records"])
        except (OSError, ValueError, KeyError, TypeError, JournalError):
            corrupt.append(path.name)
    events_ok = 0
    events_bad = 0
    events_path = root / EVENTS_FILE
    if events_path.is_file():
        for line in events_path.read_bytes().splitlines():
            try:
                document = json.loads(line)
                checksum = document.pop("sha256")
                events_ok += 1 if sha256_hex(canonical_json(document)) == checksum else 0
                events_bad += 0 if sha256_hex(canonical_json(document)) == checksum else 1
            except (ValueError, KeyError, AttributeError, TypeError):
                events_bad += 1
    return {
        "run_id": body["run_id"],
        "created_utc": body["created_utc"],
        "identity": identity.as_dict(),
        "shards_valid": len(valid),
        "shards_corrupt": corrupt,
        "restorable_records": tasks,
        "events_valid": events_ok,
        "events_invalid": events_bad,
        "complete": tasks >= identity.n_tasks and not corrupt,
    }
