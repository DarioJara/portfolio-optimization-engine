"""D-DET / P-06: marcas de progreso de los workers (ficheros cuyo nombre es el dato)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from portfolio_engine.parallel import markers

pytestmark = pytest.mark.unit


def test_scan_reads_registered_workers_and_the_latest_task_per_batch(tmp_path: Path) -> None:
    (tmp_path / "w.111").touch()
    (tmp_path / "w.222").touch()
    (tmp_path / "t.5.0.111").touch()
    (tmp_path / "t.5.3.111").touch()  # la tarea en curso es la de mayor posición
    (tmp_path / "t.6.1.222").touch()
    snapshot = markers.scan(tmp_path)
    assert snapshot.workers == frozenset({111, 222})
    assert snapshot.tasks == {
        5: markers.TaskMarker(5, 3, 111),
        6: markers.TaskMarker(6, 1, 222),
    }


@pytest.mark.parametrize("name", ["w.abc", "t.1.2", "t.a.b.c.d", "w.", "otro", "t.1.2.x"])
def test_scan_ignores_malformed_names(tmp_path: Path, name: str) -> None:
    (tmp_path / name).touch()
    snapshot = markers.scan(tmp_path)
    assert snapshot.workers == frozenset() and snapshot.tasks == {}


def test_scan_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert markers.scan(tmp_path / "nope") == markers.MarkerSnapshot(frozenset(), {})


def test_a_batch_marker_replaces_its_previous_mark_and_cleans_up(tmp_path: Path) -> None:
    with markers.BatchMarker(str(tmp_path), 9) as marker:
        marker.start(0)
        marker.start(1)
        names = sorted(p.name for p in tmp_path.iterdir())
        assert names == [f"t.9.1.{os.getpid()}"]
        assert markers.scan(tmp_path).tasks[9].position == 1
    assert list(tmp_path.iterdir()) == []  # fin normal del lote: sin marcas


def test_a_marker_without_a_directory_is_a_no_op() -> None:
    with markers.BatchMarker(None, 1) as marker:
        marker.start(0)


def test_an_abrupt_death_leaves_the_task_mark_and_the_worker_registration(
    tmp_path: Path,
) -> None:
    """Muerte abrupta (sin ``finally`` ni finalizadores): quedan las marcas que la delatan."""
    root = str(Path(__file__).resolve().parents[3])
    code = (
        "import sys, os;"
        "sys.path.insert(0, sys.argv[2]);"
        "from portfolio_engine.parallel import markers;"
        "markers.register_worker(sys.argv[1]);"
        "m = markers.BatchMarker(sys.argv[1], 4); m.__enter__(); m.start(2);"
        "os._exit(1)"
    )
    died = subprocess.run([sys.executable, "-c", code, str(tmp_path), root], timeout=120)
    assert died.returncode == 1  # ``os._exit(1)``: muerte abrupta, sin ``finally`` ni finalizadores
    snapshot = markers.scan(tmp_path)
    assert len(snapshot.workers) == 1
    (pid,) = snapshot.workers
    assert snapshot.tasks[4] == markers.TaskMarker(4, 2, pid)
    assert markers.process_is_gone(pid)


def test_a_live_process_is_not_gone_and_clear_removes_every_mark(tmp_path: Path) -> None:
    assert not markers.process_is_gone(os.getpid())
    (tmp_path / "w.1").touch()
    (tmp_path / "t.1.0.1").touch()
    markers.clear(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_terminate_process_kills_a_real_child_and_ignores_missing_pids() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert not markers.process_is_gone(child.pid)
        markers.terminate_process(child.pid)
        child.wait(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
    assert child.returncode is not None
    markers.terminate_process(child.pid)  # ya no existe: no lanza


# -------------------------------------------------------- L-2: identidad antes de terminar


def _sleeper() -> None:
    import time

    time.sleep(120)


def test_start_tokens_identify_a_process_and_workers_register_theirs(tmp_path: Path) -> None:
    token = markers.start_token(os.getpid())
    assert token is not None and token.isdigit()  # Windows y Linux facilitan la hora de inicio
    assert markers.start_token(os.getpid()) == token  # estable
    markers.register_worker(str(tmp_path))
    snapshot = markers.scan(tmp_path)
    assert snapshot.tokens == {os.getpid(): token}
    assert markers.process_is_gone(os.getpid(), token) is False
    assert markers.process_is_gone(os.getpid(), "0") is True  # mismo PID, otra «identidad»


def test_scan_reads_tokens_and_accepts_marks_without_one(tmp_path: Path) -> None:
    (tmp_path / "w.10.777").touch()
    (tmp_path / "w.11").touch()
    (tmp_path / "w.12.abc").touch()  # token mal formado: ignorada
    snapshot = markers.scan(tmp_path)
    assert snapshot.workers == frozenset({10, 11})
    assert snapshot.tokens == {10: "777"}


def test_a_foreign_process_is_never_terminated_even_with_a_matching_token() -> None:
    """Un proceso vivo que no es hijo del coordinador (PID reutilizado) no se puede terminar."""
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        token = markers.start_token(foreign.pid)
        assert not markers.is_our_worker(foreign.pid, token)
        assert not markers.terminate_owned(foreign.pid, token)
        assert not markers.terminate_owned(foreign.pid)
        assert foreign.poll() is None
    finally:
        foreign.kill()
        foreign.wait(timeout=60)


def test_an_owned_child_is_terminated_only_when_identity_matches() -> None:
    import multiprocessing

    child = multiprocessing.get_context("spawn").Process(target=_sleeper)
    child.start()
    try:
        assert child.pid is not None
        token = markers.start_token(child.pid)
        assert markers.is_our_worker(child.pid, token)
        assert not markers.terminate_owned(child.pid, "1")  # PID reutilizado: otra hora de inicio
        assert child.is_alive()
        assert markers.terminate_owned(child.pid, token)
        child.join(timeout=60)
        assert not child.is_alive()
        assert not markers.terminate_owned(child.pid, token)  # ya no es nuestro
    finally:
        if child.is_alive():
            child.kill()
            child.join(timeout=60)
