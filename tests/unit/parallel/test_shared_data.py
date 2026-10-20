"""PAR-004, PAR-005, L-3: publicación, adjunción, integridad y limpieza de los datos compartidos."""

from __future__ import annotations

import contextlib
import gc
import json
import multiprocessing
import os
import pickle
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from portfolio_engine.config import SharedDataMode
from portfolio_engine.parallel.shared_data import (
    ALIGNMENT,
    OWNER_FILE,
    RUN_DIR_PREFIX,
    SharedDataError,
    SharedSnapshotHandle,
    attach_snapshot,
    inventory_orphans,
    pid_alive,
    publish_snapshot,
    read_buffer_table,
    remove_orphans,
)
from portfolio_engine.parallel.task import ExecutionContext
from portfolio_engine.parallel.worker import array_backing, initialize_worker, worker_context
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import snapshot_of
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
#: Cota de la referencia que viaja por el pipe de arranque (muy inferior a cualquier matriz real).
MAX_HANDLE_BYTES = 2048
OUT_OF_BAND = [SharedDataMode.FILE_MMAP, SharedDataMode.SHARED_MEMORY]
ALL_MODES = [SharedDataMode.BUNDLE_FILE, *OUT_OF_BAND]


@pytest.fixture(scope="module")
def context() -> ExecutionContext:
    problem = random_problem(30, [0, 1, 2], 3, CONFIG)
    return ExecutionContext.create(CONFIG, snapshot_of(problem, return_periods=120, seed=4))


def _probe() -> dict[str, Any]:
    """Tarea del worker: inspecciona los arrays adjuntos (se ejecuta en el proceso hijo)."""
    ctx = worker_context().execution
    risk = ctx.snapshot.risk_model
    outcome: dict[str, Any] = {
        "pid": os.getpid(),
        "snapshot_key": ctx.snapshot_key,
        "config_hash": ctx.config_hash,
        "sigma_backing": array_backing(risk.sigma),
        "mu_backing": array_backing(risk.mu),
        "writeable": [bool(risk.sigma.flags.writeable), bool(risk.mu.flags.writeable)],
    }
    try:
        risk.sigma[0, 0] = 0.0
        outcome["write_error"] = None
    except ValueError as error:
        outcome["write_error"] = str(error)
    return outcome


def _run_probe(handle: Any) -> dict[str, Any]:
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=initialize_worker,
        initargs=(handle, 1),
    ) as pool:
        return pool.submit(_probe).result()


@pytest.mark.parametrize("mode", ALL_MODES, ids=lambda m: m.value)
def test_a_real_worker_attaches_verified_read_only_arrays(
    mode: SharedDataMode, context: ExecutionContext
) -> None:
    with publish_snapshot(context, mode) as published:
        probe = _run_probe(published.handle)
    assert probe["pid"] != os.getpid()
    assert probe["snapshot_key"] == context.snapshot_key
    assert probe["config_hash"] == context.config_hash
    assert probe["writeable"] == [False, False]
    assert "read-only" in str(probe["write_error"])
    expected = "bytes" if mode is SharedDataMode.BUNDLE_FILE else "mmap"
    # Sin copia fuera de banda: el array es una vista sobre la proyección o el segmento.
    assert probe["sigma_backing"] == expected and probe["mu_backing"] == expected


@pytest.mark.parametrize("mode", ALL_MODES, ids=lambda m: m.value)
def test_the_reference_sent_to_workers_is_tiny_and_matrices_are_not_in_it(
    mode: SharedDataMode, context: ExecutionContext
) -> None:
    """PAR-005: el pipe de arranque recibe una referencia, no las matrices."""
    sigma_bytes = int(context.snapshot.risk_model.sigma.nbytes)
    with publish_snapshot(context, mode) as published:
        sent = len(pickle.dumps(published.handle))
        assert sent == published.info.handle_bytes
        assert sent < MAX_HANDLE_BYTES < sigma_bytes
        if mode is not SharedDataMode.BUNDLE_FILE:
            assert published.info.data_bytes >= sigma_bytes
            assert published.info.n_buffers >= 2  # al menos mu y Σ fuera de banda
            assert isinstance(published.handle, SharedSnapshotHandle)
            assert all(ref.offset % ALIGNMENT == 0 for ref in read_buffer_table(published.handle))
        assert published.info.mode is mode and published.info.publish_seconds >= 0.0


@pytest.mark.parametrize("mode", OUT_OF_BAND, ids=lambda m: m.value)
def test_in_process_attachment_is_zero_copy_and_equal_to_the_original(
    mode: SharedDataMode, context: ExecutionContext
) -> None:
    with publish_snapshot(context, mode) as published:
        assert isinstance(published.handle, SharedSnapshotHandle)
        attached, attachment = attach_snapshot(published.handle)
        try:
            risk = attached.snapshot.risk_model
            original = context.snapshot.risk_model
            assert np.array_equal(risk.sigma, original.sigma)
            assert np.array_equal(risk.mu, original.mu)
            assert risk.mu_sigma_version == original.mu_sigma_version
            assert attached.snapshot_key == context.snapshot_key
            assert array_backing(risk.sigma) == "mmap"
            assert not np.shares_memory(risk.sigma, original.sigma)  # no es el array del origen
            with pytest.raises(ValueError, match="read-only"):
                risk.sigma[0, 0] = 1.0
        finally:
            del attached, risk
            gc.collect()
            attachment.release()


@pytest.mark.parametrize("mode", ALL_MODES, ids=lambda m: m.value)
def test_resources_are_removed_after_success_and_after_an_exception(
    mode: SharedDataMode, context: ExecutionContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with publish_snapshot(context, mode) as published:
        assert any(tmp_path.iterdir())
        handle = published.handle
    assert list(tmp_path.iterdir()) == []
    with (
        pytest.raises(RuntimeError, match="fallo del llamador"),
        publish_snapshot(context, mode),
    ):
        assert any(tmp_path.iterdir())
        raise RuntimeError("fallo del llamador")
    assert list(tmp_path.iterdir()) == []
    if mode is SharedDataMode.SHARED_MEMORY:
        assert isinstance(handle, SharedSnapshotHandle)
        from multiprocessing import shared_memory

        with pytest.raises(FileNotFoundError):  # el segmento ya no existe
            shared_memory.SharedMemory(name=handle.data_location)


@pytest.mark.parametrize("mode", OUT_OF_BAND, ids=lambda m: m.value)
def test_a_tampered_header_or_buffer_is_rejected_before_unpickling(
    mode: SharedDataMode, context: ExecutionContext
) -> None:
    with publish_snapshot(context, mode) as published:
        handle = published.handle
        assert isinstance(handle, SharedSnapshotHandle)
        header = Path(handle.header_path)
        original = header.read_bytes()
        header.write_bytes(original + b"x")
        with pytest.raises(SharedDataError, match="cabecera"):
            attach_snapshot(handle)
        header.write_bytes(original)
        if mode is SharedDataMode.FILE_MMAP:
            data = Path(handle.data_location)
            raw = bytearray(data.read_bytes())
            raw[read_buffer_table(handle)[0].offset] ^= 0xFF
            data.write_bytes(bytes(raw))
        else:
            from multiprocessing import shared_memory

            segment = shared_memory.SharedMemory(name=handle.data_location)
            assert segment.buf is not None
            segment.buf[read_buffer_table(handle)[0].offset] ^= 0xFF
            segment.close()
        with pytest.raises(SharedDataError, match="buffer 0"):
            attach_snapshot(handle)


def test_a_worker_with_a_tampered_reference_fails_to_start(context: ExecutionContext) -> None:
    """La verificación ocurre en el worker: un initializer con hash erróneo no deja trabajar."""
    from concurrent.futures.process import BrokenProcessPool

    with publish_snapshot(context, SharedDataMode.FILE_MMAP) as published:
        handle = published.handle
        assert isinstance(handle, SharedSnapshotHandle)
        Path(handle.header_path).write_bytes(Path(handle.header_path).read_bytes() + b"x")
        with pytest.raises(BrokenProcessPool):
            _run_probe(handle)


# ------------------------------------------------------------------------------- huérfanos


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-I", "-c", "pass"])
    process.wait()
    return process.pid


def test_pid_liveness_distinguishes_running_and_finished_processes() -> None:
    assert pid_alive(os.getpid())
    assert not pid_alive(_dead_pid())


def test_orphan_inventory_lists_only_runs_whose_owner_is_gone(tmp_path: Path) -> None:
    def make(name: str, pid: int | None) -> Path:
        directory = tmp_path / f"{RUN_DIR_PREFIX}{name}"
        directory.mkdir()
        if pid is not None:
            owner = {"pid": pid, "created": time.time(), "mode": "FILE_MMAP", "shm": None}
            (directory / OWNER_FILE).write_text(json.dumps(owner), encoding="utf-8")
        return directory

    alive, dead, unowned = (
        make("alive", os.getpid()),
        make("dead", _dead_pid()),
        make("unowned", None),
    )
    young = inventory_orphans(tmp_path, min_age_seconds=3600.0)
    assert young.directories == (dead,)  # la sin propietario es reciente: no se toca
    old = inventory_orphans(tmp_path, min_age_seconds=0.0)
    assert set(old.directories) == {dead, unowned} and alive not in old.directories
    assert remove_orphans(old) == 2
    assert alive.exists() and not dead.exists() and not unowned.exists()
    assert inventory_orphans(tmp_path, min_age_seconds=0.0).empty


def test_a_live_publication_is_never_reported_as_an_orphan(context: ExecutionContext) -> None:
    with publish_snapshot(context, SharedDataMode.FILE_MMAP) as published:
        assert isinstance(published.handle, SharedSnapshotHandle)
        directory = Path(published.handle.header_path).parent
        owner = json.loads((directory / OWNER_FILE).read_text(encoding="utf-8"))
        assert owner["pid"] == os.getpid() and owner["mode"] == "FILE_MMAP"
        assert directory not in inventory_orphans(min_age_seconds=0.0).directories


@pytest.mark.skipif(sys.platform != "linux", reason="inventario de /dev/shm solo en Linux")
def test_shared_memory_orphans_are_found_in_dev_shm(context: ExecutionContext) -> None:
    from multiprocessing import shared_memory

    name = f"pe_{_dead_pid()}_deadbeef0000"
    segment = shared_memory.SharedMemory(name=name, create=True, size=16)
    try:
        assert name in inventory_orphans(min_age_seconds=0.0).shared_memory
        assert remove_orphans(inventory_orphans(min_age_seconds=0.0)) >= 1
    finally:
        segment.close()
        with contextlib.suppress(FileNotFoundError):
            segment.unlink()


@pytest.mark.parametrize("mode", OUT_OF_BAND, ids=lambda m: m.value)
def test_the_reference_size_does_not_grow_with_the_universe(mode: SharedDataMode) -> None:
    """La tabla de buffers vive en un manifiesto: la referencia tiene tamaño constante."""
    sizes = []
    for assets in (20, 120):
        problem = random_problem(assets, [0, 1, 2], 3, CONFIG)
        ctx = ExecutionContext.create(CONFIG, snapshot_of(problem, return_periods=60, seed=1))
        with publish_snapshot(ctx, mode) as published:
            sizes.append((published.info.handle_bytes, published.info.data_bytes))
    assert sizes[1][1] > 10 * sizes[0][1]  # los datos sí crecen…
    assert abs(sizes[1][0] - sizes[0][0]) <= 64  # …la referencia no
