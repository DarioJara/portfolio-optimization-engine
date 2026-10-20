"""Evidencia Linux de B5.4 (auditoría L-3): forkserver, flock, permisos, zombis y limpieza.

Solo se ejecuta en Linux (la CI ``ubuntu-22.04`` y cualquier contenedor Linux). Cada prueba cubre
un mecanismo que en Windows no existe o se implementa distinto: ``forkserver`` como método de
arranque bajo caídas y plazos, ``fcntl.flock`` entre procesos, permisos POSIX, detección de
procesos zombi por ``/proc`` y ausencia de procesos hijo residuales (``/proc/<pid>/stat``).
"""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from portfolio_engine.config.parallel_config import ProcessStartMethod
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.parallel import markers
from portfolio_engine.parallel.executor import JournalSpec, SequentialExecutor
from portfolio_engine.parallel.journal import (
    JournalLockedError,
    RunJournal,
    build_identity,
)
from portfolio_engine.parallel.shared_data import scratch_directory
from portfolio_engine.parallel.task import ExecutionStatus
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.faults import FaultSpec, FaultyExecutor, fault_config
from tests.fixtures.parallel import compare_results, requests_for, snapshot_of
from tests.fixtures.problems import base_config

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="evidencia específica de Linux"),
]

CONFIG = base_config()
WORKLOAD = WorkloadSpec(
    (
        OperationSpec(
            OperationKind.FRONTIER_FIXED_COMPOSITION,
            CostTreatment.NET,
            method=FrontierMethod.RISK_AVERSION_GRID,
        ),
    )
)
PRIVATE_BITS = stat.S_IRWXG | stat.S_IRWXO


@pytest.fixture(scope="module")
def data() -> tuple[Any, list[Any], Any]:
    problem = random_problem(8, [0, 1, 2], 3, CONFIG)
    snapshot = snapshot_of(problem)
    requests = requests_for(problem, WORKLOAD, 6, seed=21)
    return snapshot, requests, SequentialExecutor(CONFIG, snapshot).run(requests)


def _forkserver(**recovery: Any) -> Any:
    config = fault_config(2, 2, **recovery)
    return dataclasses.replace(config, start_method=ProcessStartMethod.FORKSERVER)


def _child_pids() -> list[int]:
    """Procesos cuyo padre es éste (cualquier estado, también zombis), leídos de ``/proc``."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="utf-8").rsplit(")", 1)[-1].split()
        except OSError:
            continue
        if int(fields[1]) == os.getpid():  # campo 4 (ppid) = índice 1 tras el estado
            found.append(int(entry.name))
    return found


def _settle_children(seconds: float = 30.0) -> list[int]:
    """Espera a que no queden hijos (el servidor forkserver es un hijo permanente del proceso)."""
    deadline = time.monotonic() + seconds
    forkserver = _forkserver_pid()
    while time.monotonic() < deadline:
        left = [pid for pid in _child_pids() if pid != forkserver]
        if not left:
            return []
        time.sleep(0.2)
    return [pid for pid in _child_pids() if pid != forkserver]


def _forkserver_pid() -> int | None:
    from multiprocessing import forkserver

    return getattr(forkserver._forkserver, "_forkserver_pid", None)  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------ forkserver


def test_forkserver_recovers_a_killed_worker_and_isolates_a_poison_task(
    tmp_path: Path, data: tuple[Any, list[Any], Any]
) -> None:
    snapshot, requests, sequential = data
    ids = sorted(r.portfolio_id for r in requests)
    spec = FaultSpec(die_once=(ids[1],), die=(ids[4],), flag_dir=str(tmp_path))
    run = FaultyExecutor(CONFIG, snapshot, _forkserver(), spec=spec).run(requests)
    assert run.manifest.start_method == "forkserver"
    for got, expected in zip(run.results, sequential.results, strict=True):
        if got.portfolio_id == ids[4]:
            assert got.execution_status is ExecutionStatus.WORKER_CRASHED
        else:
            assert got.execution_status is ExecutionStatus.COMPLETED, got.portfolio_id
            assert compare_results(expected, got).differences == []
    assert run.recovery.poisoned_tasks == 1 and run.accounting is not None
    assert run.accounting.balanced
    assert multiprocessing.active_children() == []
    assert _settle_children() == []


def test_forkserver_enforces_task_deadlines_and_leaves_no_children(
    data: tuple[Any, list[Any], Any],
) -> None:
    snapshot, requests, sequential = data
    hung = sorted(r.portfolio_id for r in requests)[2]
    config = _forkserver(task_timeout_seconds=3.0)
    run = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec(hang=(hung,))).run(requests)
    assert run.by_portfolio()[hung].execution_status is ExecutionStatus.TIMED_OUT
    for got, expected in zip(run.results, sequential.results, strict=True):
        if got.portfolio_id != hung:
            assert got.execution_status is ExecutionStatus.COMPLETED
            assert compare_results(expected, got).differences == []
    assert run.recovery.deadline_rebuilds >= 1 and not run.recovery.aborted
    assert _settle_children() == []


def test_forkserver_resumes_a_journal(tmp_path: Path, data: tuple[Any, list[Any], Any]) -> None:
    snapshot, requests, sequential = data
    config = _forkserver()
    first = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec()).run(
        requests, journal=JournalSpec(tmp_path / "j")
    )
    again = FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec()).run(
        requests, journal=JournalSpec(tmp_path / "j", resume=True)
    )
    assert again.accounting is not None and again.accounting.resumed == len(requests)
    for a, b, c in zip(first.results, again.results, sequential.results, strict=True):
        assert compare_results(a, b, tolerance=0.0).differences == []
        assert compare_results(c, b).differences == []


# --------------------------------------------------------------------------------- flock


def test_flock_excludes_a_second_process_and_is_released_when_the_holder_dies(
    tmp_path: Path, data: tuple[Any, list[Any], Any]
) -> None:
    snapshot, requests, _ = data
    context = SequentialExecutor(CONFIG, snapshot).context
    task_ids = [context.task_id(r) for r in requests]
    identity = build_identity(context, task_ids)
    expected = {context.task_id(r): (i, r.portfolio_id) for i, r in enumerate(requests)}
    directory = tmp_path / "j"
    directory.mkdir()
    root = str(Path(__file__).resolve().parents[2])
    code = (
        "import sys, time;"
        "sys.path.insert(0, sys.argv[2]);"
        "from pathlib import Path;"
        "from portfolio_engine.parallel.journal import _FileLock;"
        "lock = _FileLock(Path(sys.argv[1]) / '.lock'); lock.acquire();"
        "print('locked', flush=True); time.sleep(120)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", code, str(directory), root], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "locked"
        with pytest.raises(JournalLockedError):
            RunJournal.open(directory, identity, expected, resume=False)
    finally:
        holder.kill()
        holder.wait(timeout=60)
    RunJournal.open(directory, identity, expected, resume=False).close()  # liberado al morir


# ------------------------------------------------------------------------------ permisos


def test_journal_and_scratch_permissions_are_private(
    tmp_path: Path, data: tuple[Any, list[Any], Any]
) -> None:
    snapshot, requests, _ = data
    config = fault_config(1, 3)
    FaultyExecutor(CONFIG, snapshot, config, spec=FaultSpec()).run(
        requests, journal=JournalSpec(tmp_path / "j")
    )
    entries = [tmp_path / "j", *(tmp_path / "j").rglob("*")]
    assert len(entries) > 4
    for entry in entries:
        assert entry.stat().st_mode & PRIVATE_BITS == 0, f"{entry} no es privado"
    with scratch_directory() as scratch:
        assert scratch.stat().st_mode & PRIVATE_BITS == 0


# -------------------------------------------------------------------------------- zombis


def test_a_zombie_is_reported_as_gone_before_it_is_reaped() -> None:
    """``kill(pid, 0)`` tiene éxito sobre un zombi; la vigilancia debe tratarlo como caído."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    deadline = time.monotonic() + 60
    while not markers._is_zombie(child.pid):  # termina sin que nadie lo recoja
        assert time.monotonic() < deadline, "el hijo no llegó a ser zombi"
        time.sleep(0.05)
    assert markers.pid_alive(child.pid)  # lo que engañaría a una comprobación ingenua
    assert markers.process_is_gone(child.pid)
    child.wait(timeout=60)
    assert markers.process_is_gone(child.pid)


def test_start_token_matches_proc_and_distinguishes_processes() -> None:
    token = markers.start_token(os.getpid())
    assert token is not None
    fields = Path("/proc/self/stat").read_text(encoding="utf-8").rsplit(")", 1)[-1].split()
    assert token == fields[markers.LINUX_STARTTIME_INDEX]
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert markers.start_token(other.pid) not in (None, token)
    finally:
        other.kill()
        other.wait(timeout=60)
