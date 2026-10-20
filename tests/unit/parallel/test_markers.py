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
