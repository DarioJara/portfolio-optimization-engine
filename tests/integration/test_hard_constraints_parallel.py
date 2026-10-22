"""Criterios 11 y 12: equivalencia secuencial/paralela y persistencia/reanudación con el mandato.

Con procesos reales (``spawn``, 2 workers): el resultado de cada cartera, **incluida la auditoría de
restricciones obligatorias** (veredictos por punto, propuestas de banda, hash de parámetros
efectivos), coincide campo a campo bajo T1 con la ejecución secuencial. El diario conserva el
mandato: reanudar con el mismo mandato restaura los resultados idénticos sin ejecutar nada y
reanudar con **otro** mandato (otro ``ConfigHash``) se rechaza sin tocar el diario. Las operaciones
que no pasan por la validación final se rechazan antes de ejecutar ningún motor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.models.frontier import GlobalFrontierResult
from portfolio_engine.parallel import codec
from portfolio_engine.parallel.executor import JournalSpec, ParallelExecutor, SequentialExecutor
from portfolio_engine.parallel.journal import JournalIncompatibleError
from portfolio_engine.parallel.task import (
    ExecutionContext,
    ExecutionStatus,
    PortfolioRequest,
    run_portfolio,
)
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.faults import fault_config
from tests.fixtures.hard_constraints import BAND_PARAMS, with_mandate
from tests.fixtures.parallel import compare_results, requests_for, snapshot_of
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.integration

WORKLOAD = WorkloadSpec(
    (
        OperationSpec(
            OperationKind.GLOBAL_FRONTIER,
            CostTreatment.GROSS,
            method=FrontierMethod.RISK_AVERSION_GRID,
        ),
    )
)
N_REQUESTS = 4


def _mandate(**changes: Any) -> Any:
    fields: dict[str, Any] = {
        "max_replacements": 1,
        "max_concentration_hhi": 0.60,
        "min_volatility": 0.05,
        "max_volatility": 0.25,
        **BAND_PARAMS,
    }
    fields.update(changes)
    return with_mandate(**fields)


@pytest.fixture(scope="module")
def problem() -> Any:
    return random_problem(10, [0, 1, 2, 3], 5, base_config(), max_weight=0.6)


@pytest.fixture(scope="module")
def snapshot(problem: Any) -> Any:
    return snapshot_of(problem)


@pytest.fixture(scope="module")
def requests(problem: Any) -> list[PortfolioRequest]:
    return requests_for(problem, WORKLOAD, N_REQUESTS, holdings=4, seed=9)


@pytest.fixture(scope="module")
def sequential(snapshot: Any, requests: list[PortfolioRequest]) -> Any:
    return SequentialExecutor(_mandate(), snapshot).run(requests)


def _results(run: Any) -> list[GlobalFrontierResult]:
    return [r.operations[0].result for r in run.results]


def test_sequential_runs_carry_a_mandate_audit_with_nontrivial_verdicts(sequential: Any) -> None:
    for task in sequential.results:
        assert task.execution_status is ExecutionStatus.COMPLETED, task.error
    results = _results(sequential)
    assert all(isinstance(r, GlobalFrontierResult) for r in results)
    audits = [r.hard_constraint_audit for r in results]
    assert all(audit is not None for audit in audits)
    assert any(audit.accepted_point_ids for audit in audits if audit is not None)
    assert any(audit.band_proposals for audit in audits if audit is not None)


def test_parallel_results_and_audits_match_sequential_under_t1(
    snapshot: Any, requests: list[PortfolioRequest], sequential: Any
) -> None:
    run = ParallelExecutor(_mandate(), snapshot, fault_config(2, 2)).run(requests)
    assert [r.portfolio_id for r in run.results] == [r.portfolio_id for r in sequential.results]
    for expected, got in zip(sequential.results, run.results, strict=True):
        assert got.execution_status is ExecutionStatus.COMPLETED, got.error
        comparison = compare_results(expected, got)
        assert comparison.differences == [], expected.portfolio_id
        assert comparison.float_comparisons > 0
    for a, b in zip(_results(sequential), _results(run), strict=True):
        assert a.hard_constraint_audit is not None and b.hard_constraint_audit is not None
        assert (
            a.hard_constraint_audit.accepted_point_ids == b.hard_constraint_audit.accepted_point_ids
        )
        assert (
            a.hard_constraint_audit.effective.effective_hash
            == b.hard_constraint_audit.effective.effective_hash
        )


def test_resuming_with_the_same_mandate_restores_identical_results_and_audits(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest], sequential: Any
) -> None:
    config = fault_config(2, 1)
    mandate = _mandate()
    first = ParallelExecutor(mandate, snapshot, config).run(
        requests, journal=JournalSpec(tmp_path / "j")
    )
    second = ParallelExecutor(mandate, snapshot, config).run(
        requests, journal=JournalSpec(tmp_path / "j", resume=True)
    )
    assert second.accounting is not None and second.accounting.resumed == N_REQUESTS
    for original, restored in zip(first.results, second.results, strict=True):
        assert compare_results(original, restored, tolerance=0.0).differences == []
    for a, b in zip(_results(first), _results(second), strict=True):
        assert a.hard_constraint_audit == b.hard_constraint_audit or (
            compare_results(a.hard_constraint_audit, b.hard_constraint_audit, 0.0).differences == []
        )
        assert b.hard_constraint_audit is not None
        assert b.hard_constraint_audit.effective.max_replacements == 1  # restricciones intactas
    for expected, got in zip(sequential.results, second.results, strict=True):
        assert compare_results(expected, got).differences == []


def test_resuming_with_a_different_mandate_is_rejected_and_the_journal_is_untouched(
    tmp_path: Path, snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    config = fault_config(2, 1)
    ParallelExecutor(_mandate(), snapshot, config).run(
        requests, journal=JournalSpec(tmp_path / "j")
    )
    journal = tmp_path / "j"
    before = {p: p.read_bytes() for p in journal.rglob("*") if p.is_file()}
    before.pop(journal / ".lock", None)
    for relaxed in (_mandate(max_replacements=2), _mandate(max_volatility=0.30)):
        with pytest.raises(JournalIncompatibleError):
            ParallelExecutor(relaxed, snapshot, config).run(
                requests, journal=JournalSpec(journal, resume=True)
            )
    with pytest.raises(JournalIncompatibleError):  # quitar el mandato también cambia el ConfigHash
        ParallelExecutor(base_config(), snapshot, config).run(
            requests, journal=JournalSpec(journal, resume=True)
        )
    after = {p: p.read_bytes() for p in journal.rglob("*") if p.is_file()}
    after.pop(journal / ".lock", None)
    assert after == before


def test_the_audit_survives_the_json_journal_codec_exactly(sequential: Any) -> None:
    audit = _results(sequential)[0].hard_constraint_audit
    restored = codec.decode(codec.encode(audit))
    assert compare_results(audit, restored, tolerance=0.0).differences == []
    assert restored.effective.effective_hash == audit.effective.effective_hash


def test_operations_outside_the_global_frontier_are_rejected_before_any_engine_runs(
    snapshot: Any, requests: list[PortfolioRequest]
) -> None:
    config = _mandate()
    workload = WorkloadSpec(
        (
            OperationSpec(
                OperationKind.FRONTIER_FIXED_COMPOSITION,
                CostTreatment.GROSS,
                method=FrontierMethod.RISK_AVERSION_GRID,
            ),
        )
    )
    fixed = PortfolioRequest(
        requests[0].portfolio_id,
        requests[0].state,
        None,
        workload,
        requests[0].composition_asset_ids,
    )
    result = run_portfolio(fixed, ExecutionContext.create(config, snapshot))
    assert result.execution_status is ExecutionStatus.FAILED_INPUT_VALIDATION
    assert result.operations == ()
    assert result.error is not None and "hard_constraints" in result.error.message
    # sin mandato la misma operación se ejecuta con normalidad (no hay regresión)
    plain = run_portfolio(fixed, ExecutionContext.create(base_config(), snapshot))
    assert plain.execution_status is ExecutionStatus.COMPLETED
