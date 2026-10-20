"""PAR-004 (B5.3, remediación de la auditoría): ciclo de vida, huérfanos y vivacidad de procesos.

Cubre M-2 (acceso denegado ≠ proceso inexistente en Windows), M-4 (100 ciclos sin fugas y
recuperación tras la muerte del coordinador) y L-2…L-5 de ``AUDIT_BLOCK_5_3.md``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from portfolio_engine.config import SharedDataMode
from portfolio_engine.parallel import shared_data
from portfolio_engine.parallel.shared_data import (
    RUN_DIR_PREFIX,
    WIN_ERROR_ACCESS_DENIED,
    WIN_STILL_ACTIVE,
    SharedDataError,
    inventory_orphans,
    nt_pid_alive,
    pid_alive,
    publish_snapshot,
    remove_orphans,
)
from portfolio_engine.parallel.task import ExecutionContext
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import snapshot_of
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
ALL_MODES = list(SharedDataMode)
OUT_OF_BAND = [SharedDataMode.FILE_MMAP, SharedDataMode.SHARED_MEMORY]
#: Ciclos de la prueba de aceptación del plan («ninguna fuga tras 100 iteraciones»).
LEAK_CYCLES = 100
#: Windows: ``ERROR_INVALID_PARAMETER`` (el PID no existe) y proceso vivo privilegiado (System).
WIN_ERROR_INVALID_PARAMETER = 87
WIN_SYSTEM_PID = 4
REPO_ROOT = Path(__file__).resolve().parents[3]
KILL_TIMEOUT_SECONDS = 120.0
SEGMENT_RELEASE_SECONDS = 15.0
POLL_SECONDS = 0.2


@pytest.fixture(scope="module")
def context() -> ExecutionContext:
    problem = random_problem(12, [0, 1, 2], 3, CONFIG)
    return ExecutionContext.create(CONFIG, snapshot_of(problem, return_periods=60, seed=2))


# ----------------------------------------------------------------------------------- M-2


class _FakeKernel:
    """Doble de ``kernel32`` para probar la decisión sin depender del sistema operativo."""

    def __init__(self, handle: int, exit_code: int = WIN_STILL_ACTIVE) -> None:
        self._handle, self._exit_code = handle, exit_code
        self.closed: list[int] = []

    def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:  # noqa: N802
        return self._handle

    def GetExitCodeProcess(self, handle: int, out: Any) -> int:  # noqa: N802
        out._obj.value = self._exit_code
        return 1

    def CloseHandle(self, handle: int) -> int:  # noqa: N802
        self.closed.append(handle)
        return 1


def test_access_denied_means_the_process_is_alive() -> None:
    kernel = _FakeKernel(handle=0)
    assert nt_pid_alive(kernel, 1234, lambda: WIN_ERROR_ACCESS_DENIED)


def test_any_other_open_failure_means_the_process_does_not_exist() -> None:
    kernel = _FakeKernel(handle=0)
    assert not nt_pid_alive(kernel, 1234, lambda: WIN_ERROR_INVALID_PARAMETER)
    assert not nt_pid_alive(kernel, 1234, lambda: 0)


def test_an_open_handle_is_alive_only_while_the_process_is_active_and_is_always_closed() -> None:
    running = _FakeKernel(handle=7)
    assert nt_pid_alive(running, 1234, lambda: 0) and running.closed == [7]
    finished = _FakeKernel(handle=8, exit_code=0)
    assert not nt_pid_alive(finished, 1234, lambda: 0) and finished.closed == [8]


@pytest.mark.skipif(os.name != "nt", reason="API de procesos de Windows")
def test_a_live_privileged_windows_process_is_not_reported_as_dead() -> None:
    """El proceso System (PID 4) existe pero ``OpenProcess`` devuelve «acceso denegado»."""
    assert pid_alive(WIN_SYSTEM_PID)
    assert not pid_alive(2**31 - 8)  # PID que no existe: error de parámetro


@pytest.mark.skipif(os.name != "nt", reason="API de procesos de Windows")
def test_a_run_directory_owned_by_a_live_privileged_process_is_not_an_orphan(
    tmp_path: Path,
) -> None:
    directory = tmp_path / f"{RUN_DIR_PREFIX}privileged"
    directory.mkdir()
    owner = {"pid": WIN_SYSTEM_PID, "created": time.time(), "mode": "FILE_MMAP", "shm": None}
    (directory / shared_data.OWNER_FILE).write_text(json.dumps(owner), encoding="utf-8")
    assert inventory_orphans(tmp_path, min_age_seconds=0.0).empty


# ----------------------------------------------------------------------------------- M-4


@pytest.mark.parametrize("mode", ALL_MODES, ids=lambda m: m.value)
def test_no_resources_leak_after_100_publish_cycles(
    mode: SharedDataMode,
    context: ExecutionContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    names: list[str] = []
    for cycle in range(LEAK_CYCLES):
        try:
            with publish_snapshot(context, mode) as published:
                handle = published.handle
                if mode is SharedDataMode.SHARED_MEMORY:
                    names.append(handle.data_location)  # type: ignore[union-attr]
                if cycle % 2:  # la mitad de los ciclos termina con una excepción del llamador
                    raise RuntimeError("fallo del llamador")
        except RuntimeError:
            pass
        assert list(tmp_path.iterdir()) == [], f"ciclo {cycle}"
    assert inventory_orphans(tmp_path, min_age_seconds=0.0).empty
    if mode is SharedDataMode.SHARED_MEMORY:
        from multiprocessing import shared_memory

        assert len(set(names)) == LEAK_CYCLES  # un segmento nuevo por ciclo
        for name in names:
            with pytest.raises(FileNotFoundError):
                shared_memory.SharedMemory(name=name)


COORDINATOR = textwrap.dedent(
    """
    import json, sys, time
    from pathlib import Path
    from portfolio_engine.config import SharedDataMode
    from portfolio_engine.parallel.shared_data import publish_snapshot
    from portfolio_engine.parallel.task import ExecutionContext
    from tests.fixtures.candidates import random_problem
    from tests.fixtures.parallel import snapshot_of
    from tests.fixtures.problems import base_config

    config = base_config()
    problem = random_problem(12, [0, 1, 2], 3, config)
    context = ExecutionContext.create(config, snapshot_of(problem, return_periods=60, seed=2))
    mode, root = SharedDataMode(sys.argv[1]), Path(sys.argv[2])
    with publish_snapshot(context, mode, root=root) as published:
        location = getattr(published.handle, "data_location", "")
        print(json.dumps({"location": location}), flush=True)
        time.sleep(600)
    """
)


@pytest.mark.parametrize("mode", OUT_OF_BAND, ids=lambda m: m.value)
def test_resources_of_a_killed_coordinator_are_found_and_recovered(
    mode: SharedDataMode, tmp_path: Path
) -> None:
    """Sin ``finally`` (``kill``): el inventario lo marca huérfano y ``remove_orphans`` lo borra."""
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    process = subprocess.Popen(
        [sys.executable, "-c", COORDINATOR, mode.value, str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    try:
        assert process.stdout is not None
        line = process.stdout.readline()
        assert line, "el coordinador no llegó a publicar"
        location = json.loads(line)["location"]
        directories = [d for d in tmp_path.iterdir() if d.name.startswith(RUN_DIR_PREFIX)]
        assert len(directories) == 1
        live = inventory_orphans(tmp_path, min_age_seconds=0.0)
        assert live.empty  # mientras el coordinador vive no es huérfano
    finally:
        process.kill()
        process.wait(timeout=KILL_TIMEOUT_SECONDS)
    assert directories[0].exists()  # la muerte abrupta no ejecuta la limpieza…
    found = inventory_orphans(tmp_path, min_age_seconds=0.0)
    assert found.directories == (directories[0],)  # …pero se detecta
    assert remove_orphans(found) >= 1
    assert not directories[0].exists()
    assert inventory_orphans(tmp_path, min_age_seconds=0.0).empty
    if mode is SharedDataMode.SHARED_MEMORY:
        from multiprocessing import shared_memory

        # Windows libera el segmento poco después de terminar el proceso; Linux lo elimina el
        # inventario o el rastreador de recursos.
        deadline = time.monotonic() + SEGMENT_RELEASE_SECONDS
        while True:
            try:
                shared_memory.SharedMemory(name=location).close()
            except FileNotFoundError:
                break
            assert time.monotonic() < deadline, "el segmento sigue existiendo"
            time.sleep(POLL_SECONDS)


# ------------------------------------------------------------------------------ L-2 … L-5


def test_a_failure_after_creating_the_segment_does_not_leave_it_behind(
    context: ExecutionContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-2: si falla la publicación tras crear el segmento, éste se libera."""
    from multiprocessing import shared_memory

    created: list[str] = []
    real_init = shared_memory.SharedMemory.__init__

    def recording_init(self: Any, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        if kwargs.get("create"):
            created.append(self.name)

    monkeypatch.setattr(shared_memory.SharedMemory, "__init__", recording_init)
    real_write = Path.write_bytes

    def failing_write(self: Path, data: Any) -> int:
        if self.name == shared_data.MANIFEST_FILE:
            raise OSError("disco lleno simulado")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with (
        pytest.raises(OSError, match="disco lleno"),
        publish_snapshot(context, SharedDataMode.SHARED_MEMORY),
    ):
        pass
    assert len(created) == 1
    monkeypatch.undo()
    with pytest.raises(FileNotFoundError):
        shared_memory.SharedMemory(name=created[0])
    assert list(tmp_path.iterdir()) == []


def test_a_directory_that_cannot_be_removed_is_reported(
    context: ExecutionContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-3: la fuga ya no es silenciosa."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(shared_data, "_remove_tree", lambda directory: False)
    with (
        pytest.warns(ResourceWarning, match="No se pudo eliminar"),
        publish_snapshot(context, SharedDataMode.FILE_MMAP),
    ):
        pass
    monkeypatch.undo()
    for leftover in tmp_path.iterdir():
        shutil.rmtree(leftover, ignore_errors=True)


def test_shared_memory_without_room_fails_before_writing(
    context: ExecutionContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-4: sin espacio en el sistema de ficheros del segmento se rechaza con un error claro."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(shared_data, "SHM_DIRECTORY", tmp_path)
    monkeypatch.setattr(
        shared_data.shutil, "disk_usage", lambda path: SimpleNamespace(total=1, used=1, free=0)
    )
    with (
        pytest.raises(SharedDataError, match="sin espacio"),
        publish_snapshot(context, SharedDataMode.SHARED_MEMORY),
    ):
        pass
    assert [p for p in tmp_path.iterdir() if p.name.startswith(RUN_DIR_PREFIX)] == []


def test_only_segments_with_the_exact_name_shape_are_orphan_candidates() -> None:
    """L-5: ``pe_<pid>_<12 hex>``; otros nombres de ``/dev/shm`` no se tocan."""
    assert shared_data._is_token("deadbeef0000")
    for foreign in ("deadbeef000", "deadbeef00000", "zzzzzzzzzzzz", "DEADBEEF0000x", ""):
        assert not shared_data._is_token(foreign)
