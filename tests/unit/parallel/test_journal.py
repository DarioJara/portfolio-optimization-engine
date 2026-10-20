"""P-05, P-08, C-12/C-13: diario local (atomicidad, corrupción, reanudación y bloqueo)."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.parallel import cli
from portfolio_engine.parallel.executor import RunResult, SequentialExecutor
from portfolio_engine.parallel.journal import (
    CORRUPT_SUFFIX,
    EVENTS_FILE,
    MANIFEST_FILE,
    RESTORABLE_STATUSES,
    SHARD_DIRECTORY,
    JournalError,
    JournalIdentity,
    JournalIncompatibleError,
    JournalLockedError,
    RunJournal,
    build_identity,
    incompatibilities,
    inspect_journal,
)
from portfolio_engine.parallel.task import ExecutionStatus, PortfolioRequest
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import Comparison, requests_for, snapshot_of
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

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
BAD = WorkloadSpec((OperationSpec(OperationKind.STRATEGY_VOL_TARGET, CostTreatment.GROSS),))


@pytest.fixture(scope="module")
def reference() -> tuple[Any, list[PortfolioRequest], RunResult]:
    problem = random_problem(8, [0, 1, 2], 3, CONFIG)
    snapshot = snapshot_of(problem)
    requests = requests_for(problem, WORKLOAD, 6, seed=5)
    requests += requests_for(problem, BAD, 1, seed=6, prefix="BAD")  # FAILED_EXCEPTION
    invalid = requests_for(problem, WORKLOAD, 1, seed=7, prefix="INVALID")[0]
    requests.append(dataclasses.replace(invalid, composition_asset_ids=("NO-SUCH-ASSET",)))
    run = SequentialExecutor(CONFIG, snapshot).run(requests)
    assert {r.execution_status for r in run.results} == {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED_EXCEPTION,  # no restaurable: puede deberse al entorno
        ExecutionStatus.FAILED_INPUT_VALIDATION,
    }
    return snapshot, requests, run


def _setup(
    reference: tuple[Any, list[PortfolioRequest], RunResult],
) -> tuple[JournalIdentity, dict[str, tuple[int, str]], RunResult]:
    snapshot, _, run = reference
    context = SequentialExecutor(CONFIG, snapshot).context
    task_ids = [r.task_id for r in run.results]
    identity = build_identity(context, task_ids)
    expected = {r.task_id: (r.sequence_id or 0, r.portfolio_id) for r in run.results}
    return identity, expected, run


def _restorable(run: RunResult) -> list[Any]:
    return [r for r in run.results if r.execution_status in RESTORABLE_STATUSES]


def _digest(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != ".lock"
    }


def _write(directory: Path, reference: Any, *, split: int = 3) -> RunResult:
    identity, expected, run = _setup(reference)
    journal = RunJournal.open(directory, identity, expected, resume=False)
    try:
        journal.record(run.results[:split])
        journal.record(run.results[split:])
    finally:
        journal.close()
    return run


def test_a_journal_restores_every_result_exactly(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    run = _write(tmp_path / "j", reference)
    identity, expected, _ = _setup(reference)
    journal = RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    try:
        assert journal.scan.corrupt_shards == ()
        assert set(journal.restored) == {r.task_id for r in _restorable(run)}
        for original in _restorable(run):
            comparison = Comparison(tolerance=0.0)
            comparison.compare(original, journal.restored[original.task_id])
            assert comparison.differences == [] and comparison.inexact_floats == 0
        statuses = {r.execution_status for r in journal.restored.values()}
        assert statuses == {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED_INPUT_VALIDATION}
        failed = next(
            r for r in run.results if r.execution_status is ExecutionStatus.FAILED_EXCEPTION
        )
        assert failed.task_id not in journal.restored  # se re-ejecutaría al reanudar
    finally:
        journal.close()


def test_only_deterministic_task_outcomes_are_restorable(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    """Caída, plazo, cancelación o excepción pueden ser del entorno: se re-ejecutan al reanudar."""
    identity, expected, run = _setup(reference)
    journal = RunJournal.open(tmp_path / "j", identity, expected, resume=False)
    try:
        crashed = dataclasses.replace(
            run.results[0], execution_status=ExecutionStatus.WORKER_CRASHED
        )
        journal.record([crashed])
    finally:
        journal.close()
    assert list((tmp_path / "j" / SHARD_DIRECTORY).iterdir()) == []  # ningún shard
    info = inspect_journal(tmp_path / "j")
    assert info["restorable_records"] == 0 and info["events_valid"] >= 2


@pytest.mark.parametrize(
    "field",
    [
        "format_version",
        "config_hash",
        "snapshot_key",
        "code_hash",
        "request_set_hash",
        "n_tasks",
        "python_version",
        "library_versions",
    ],
)
def test_resume_is_rejected_when_any_identity_field_differs_and_nothing_is_modified(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult], field: str
) -> None:
    """C-12: config/snapshot/código/conjunto de tareas/versiones distintos ⇒ rechazo explícito."""
    _write(tmp_path / "j", reference)
    identity, expected, _ = _setup(reference)
    current = getattr(identity, field)
    changed: Any
    if isinstance(current, int):
        changed = current + 1
    elif isinstance(current, tuple):
        changed = (*current, ("extra", "1"))
    else:
        changed = current + "x"
    other = dataclasses.replace(identity, **{field: changed})
    before = _digest(tmp_path / "j")
    with pytest.raises(JournalIncompatibleError, match=field):
        RunJournal.open(tmp_path / "j", other, expected, resume=True)
    assert _digest(tmp_path / "j") == before  # sin tocar el diario (ni siquiera los eventos)
    assert incompatibilities(identity, other) == [field]


def test_a_foreign_request_source_is_rejected(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    snapshot, requests, _ = reference
    _write(tmp_path / "j", reference)
    context = SequentialExecutor(CONFIG, snapshot).context
    problem = random_problem(8, [0, 1, 2], 3, CONFIG)
    others = requests_for(problem, WORKLOAD, 6, seed=99, prefix="OTHER")
    identity = build_identity(context, [context.task_id(r) for r in others])
    with pytest.raises(JournalIncompatibleError, match="request_set_hash"):
        RunJournal.open(tmp_path / "j", identity, {}, resume=True)
    assert len(requests) > 0


def test_a_truncated_shard_is_detected_and_only_its_tasks_are_lost(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    """C-13: truncar un shard se detecta; el resto se conserva y se aparta el dañado."""
    run = _write(tmp_path / "j", reference)
    shards = sorted((tmp_path / "j" / SHARD_DIRECTORY).glob("s-*.json"))
    assert len(shards) == 2  # un shard por llamada a record() con resultados restaurables
    damaged = shards[0]
    damaged.write_bytes(damaged.read_bytes()[: damaged.stat().st_size // 2])
    identity, expected, _ = _setup(reference)
    journal = RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    try:
        assert journal.scan.corrupt_shards == (damaged.name,)
        assert journal.scan.valid_shards == 1
        lost = {r.task_id for r in run.results[:3]}
        assert set(journal.restored) == {r.task_id for r in _restorable(run)} - lost
        assert (damaged.parent / (damaged.name + CORRUPT_SUFFIX)).exists()
    finally:
        journal.close()
    again = RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    try:
        assert again.scan.corrupt_shards == ()  # ya apartado: no se vuelve a informar
    finally:
        again.close()


def test_a_flipped_byte_in_a_shard_is_detected(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    _write(tmp_path / "j", reference)
    shard = sorted((tmp_path / "j" / SHARD_DIRECTORY).glob("s-*.json"))[0]
    raw = bytearray(shard.read_bytes())
    raw[-10] ^= 0x01
    shard.write_bytes(bytes(raw))
    identity, expected, _ = _setup(reference)
    journal = RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    try:
        assert journal.scan.corrupt_shards == (shard.name,)
    finally:
        journal.close()


def test_a_shard_with_a_forged_record_is_rejected_even_with_a_valid_checksum(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    """La suma no basta: el registro debe corresponder a una tarea de ESTA ejecución."""
    _write(tmp_path / "j", reference)
    identity, expected, _ = _setup(reference)
    shard = sorted((tmp_path / "j" / SHARD_DIRECTORY).glob("s-*.json"))[0]
    header_line, _, body = shard.read_bytes().partition(b"\n")
    records = json.loads(body)
    records[0]["task_id"] = "f" * 64
    forged = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    header = json.loads(header_line)
    header["body_bytes"] = len(forged)
    header["body_sha256"] = hashlib.sha256(forged).hexdigest()
    shard.write_bytes(json.dumps(header, sort_keys=True).encode() + b"\n" + forged)
    journal = RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    try:
        assert journal.scan.corrupt_shards == (shard.name,)
    finally:
        journal.close()


def test_orphan_temporaries_from_an_interrupted_write_are_removed(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    run = _write(tmp_path / "j", reference)
    leftover = tmp_path / "j" / SHARD_DIRECTORY / ".s-0000000000-aaaa.json.123456.tmp"
    leftover.write_bytes(b"{escritura a medias")
    identity, expected, _ = _setup(reference)
    journal = RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    try:
        assert journal.scan.temporaries_removed == 1 and not leftover.exists()
        assert len(journal.restored) == len(_restorable(run))
    finally:
        journal.close()


def test_a_missing_manifest_or_a_tampered_one_is_an_error(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    identity, expected, _ = _setup(reference)
    with pytest.raises(JournalError, match="No hay un diario"):
        RunJournal.open(tmp_path / "missing", identity, expected, resume=True)
    _write(tmp_path / "j", reference)
    manifest = tmp_path / "j" / MANIFEST_FILE
    document = json.loads(manifest.read_bytes())
    document["body"]["identity"]["n_tasks"] = 999
    manifest.write_bytes(json.dumps(document).encode())
    with pytest.raises(JournalError, match="suma de verificación"):
        RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    manifest.write_bytes(b"{truncado")
    with pytest.raises(JournalError, match="ilegible"):
        RunJournal.open(tmp_path / "j", identity, expected, resume=True)


def test_a_new_journal_never_overwrites_an_existing_one(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    _write(tmp_path / "j", reference)
    identity, expected, _ = _setup(reference)
    before = _digest(tmp_path / "j")
    with pytest.raises(JournalError, match="no está vacío"):
        RunJournal.open(tmp_path / "j", identity, expected, resume=False)
    assert _digest(tmp_path / "j") == before


def test_two_runs_cannot_share_a_journal_and_the_lock_is_released_on_close(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    identity, expected, _ = _setup(reference)
    first = RunJournal.open(tmp_path / "j", identity, expected, resume=False)
    with pytest.raises(JournalLockedError):
        RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    first.close()
    first.close()  # idempotente
    RunJournal.open(tmp_path / "j", identity, expected, resume=True).close()
    # dos diarios en directorios distintos no colisionan
    a = RunJournal.open(tmp_path / "a", identity, expected, resume=False)
    b = RunJournal.open(tmp_path / "b", identity, expected, resume=False)
    assert a.run_id != b.run_id
    a.close()
    b.close()


def test_a_run_dying_with_the_lock_does_not_block_a_later_resume(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    """El bloqueo es del sistema operativo: si el proceso muere, se libera solo."""
    import subprocess
    import sys

    code = (
        "import sys,os;"
        "sys.path.insert(0, sys.argv[2]);"
        "from pathlib import Path;"
        "from portfolio_engine.parallel.journal import _FileLock;"
        "l=_FileLock(Path(sys.argv[1])/'.lock');l.acquire();os._exit(0)"
    )
    directory = tmp_path / "j"
    directory.mkdir()
    root = str(Path(__file__).resolve().parents[3])
    subprocess.run([sys.executable, "-c", code, str(directory), root], check=True)
    identity, expected, _ = _setup(reference)
    RunJournal.open(directory, identity, expected, resume=False).close()


def test_the_journal_never_uses_pickle_and_only_contains_json(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    """Formato no ejecutable: sin ``pickle`` en el código y todo fichero se parsea como JSON."""
    _write(tmp_path / "j", reference)
    root = Path(__file__).resolve().parents[3] / "portfolio_engine" / "parallel"
    for module in ("journal.py", "codec.py", "cli.py"):
        tree = ast.parse((root / module).read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not imported & {"pickle", "marshal", "shelve", "dill", "cloudpickle"}, module
    for path in (tmp_path / "j").rglob("*"):
        if not path.is_file() or path.name == ".lock":
            continue
        if path.suffix == ".json":
            first, _, rest = path.read_bytes().partition(b"\n")
            json.loads(first)
            if rest:
                json.loads(rest)
        else:
            for line in path.read_bytes().splitlines():
                json.loads(line)


@pytest.mark.skipif(os.name == "nt", reason="permisos POSIX")
def test_posix_permissions_are_private(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    _write(tmp_path / "j", reference)
    assert (tmp_path / "j").stat().st_mode & 0o077 == 0
    for path in (tmp_path / "j").rglob("*.json"):
        assert path.stat().st_mode & 0o077 == 0


def test_events_are_checksummed_and_a_truncated_tail_is_tolerated(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    _write(tmp_path / "j", reference)
    events = tmp_path / "j" / EVENTS_FILE
    valid = inspect_journal(tmp_path / "j")["events_valid"]
    assert valid >= 1
    events.write_bytes(events.read_bytes() + b'{"seq":99,"kind":"x"')  # línea truncada
    info = inspect_journal(tmp_path / "j")
    assert info["events_valid"] == valid and info["events_invalid"] == 1


def test_the_event_log_never_contains_portfolio_content(
    tmp_path: Path, reference: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    run = _write(tmp_path / "j", reference)
    text = (tmp_path / "j" / EVENTS_FILE).read_text(encoding="utf-8")
    assert not any(r.portfolio_id in text for r in run.results)
    manifest = (tmp_path / "j" / MANIFEST_FILE).read_text(encoding="utf-8")
    assert not any(r.portfolio_id in manifest for r in run.results)


# ------------------------------------------------------------------------------------- CLI


def test_the_cli_prints_one_stable_json_object_and_does_not_modify_the_journal(
    tmp_path: Path,
    reference: tuple[Any, list[PortfolioRequest], RunResult],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(tmp_path / "j", reference)
    before = _digest(tmp_path / "j")
    assert cli.main(["journal-info", str(tmp_path / "j")]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1
    document = json.loads(out)
    assert list(document) == sorted(document)  # claves ordenadas: salida estable
    assert document["shards_corrupt"] == []
    assert document["restorable_records"] == len(_restorable(reference[2]))
    assert document["complete"] is False  # hay tareas no restaurables (se re-ejecutarían)
    assert document["identity"]["n_tasks"] == len(reference[2].results)
    assert cli.main(["journal-info", str(tmp_path / "j")]) == cli.EXIT_OK
    assert capsys.readouterr().out == out  # determinista
    assert _digest(tmp_path / "j") == before


def test_the_cli_reports_unreadable_journals_with_exit_code_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["journal-info", str(tmp_path / "nope")]) == cli.EXIT_UNREADABLE
    assert "error" in json.loads(capsys.readouterr().out)


def test_the_cli_flags_an_incomplete_journal(
    tmp_path: Path,
    reference: tuple[Any, list[PortfolioRequest], RunResult],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(tmp_path / "j", reference)
    shard = sorted((tmp_path / "j" / SHARD_DIRECTORY).glob("s-*.json"))[0]
    shard.write_bytes(shard.read_bytes()[:20])
    assert cli.main(["journal-info", str(tmp_path / "j")]) == cli.EXIT_OK
    document = json.loads(capsys.readouterr().out)
    assert document["complete"] is False and document["shards_corrupt"] == [shard.name]


# ----------------------------------------- L-1: contenido inválido con suma válida (hostil)


def _replace_first_result(directory: Path, result_json: str) -> str:
    """Sustituye el resultado del primer registro del primer shard conservando una suma válida."""
    shard = sorted((directory / SHARD_DIRECTORY).glob("s-*.json"))[0]
    header_line, _, body = shard.read_bytes().partition(b"\n")
    records = json.loads(body)
    head = json.dumps({k: v for k, v in records[0].items() if k != "result"}, sort_keys=True)
    rest = json.dumps(records[1:], sort_keys=True)
    forged = (
        "["
        + head[:-1]
        + ',"result":'
        + result_json
        + "}"
        + ("," + rest[1:] if rest != "[]" else "]")
    ).encode()
    header = json.loads(header_line)
    header["body_bytes"] = len(forged)
    header["body_sha256"] = hashlib.sha256(forged).hexdigest()
    shard.write_bytes(json.dumps(header, sort_keys=True).encode() + b"\n" + forged)
    return shard.name


@pytest.mark.parametrize(
    "result_json",
    [
        "[" * 5000 + "]" * 5000,  # supera el límite de recursión del parser JSON
        "[" * 300 + "]" * 300,  # supera MAX_DEPTH del códec pero no la recursión de JSON
        '{"$dc":["portfolio_engine.config.parallel_config:CacheConfig",'
        '{"enabled":true,"max_entries":0,"max_bytes":1}]}',  # ``__post_init__`` lanza ConfigError
        '{"$dc":["os:system",{}]}',
        '{"$unknown":1}',
    ],
    ids=["json-recursion", "codec-depth", "post-init-error", "foreign-type", "unknown-tag"],
)
def test_a_shard_with_valid_checksum_but_invalid_content_is_set_aside_not_fatal(
    tmp_path: Path,
    reference: tuple[Any, list[PortfolioRequest], RunResult],
    result_json: str,
) -> None:
    """Auditoría L-1: no bloquea la reanudación completa; sus tareas se re-ejecutan."""
    run = _write(tmp_path / "j", reference)
    name = _replace_first_result(tmp_path / "j", result_json)
    identity, expected, _ = _setup(reference)
    journal = RunJournal.open(tmp_path / "j", identity, expected, resume=True)
    try:
        assert journal.scan.corrupt_shards == (name,)
        assert (tmp_path / "j" / SHARD_DIRECTORY / (name + CORRUPT_SUFFIX)).exists()
        kept = set(journal.restored)
        assert kept and kept < {r.task_id for r in _restorable(run)}  # el otro shard se conserva
    finally:
        journal.close()
    again = RunJournal.open(tmp_path / "j", identity, expected, resume=True)  # ya no falla
    try:
        assert again.scan.corrupt_shards == ()
    finally:
        again.close()
