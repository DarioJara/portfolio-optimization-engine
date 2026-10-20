"""PAR-013, PAR-002: ``WorkerContext`` y ejecución de un lote dentro de un worker (en proceso).

No se llama a ``initialize_worker`` en el proceso de pytest (instala ``SIG_IGN`` para ``SIGINT``);
se construye el ``WorkerContext`` que aquel crearía. El ``initializer`` real se prueba en un
proceso hijo en ``test_executor.py``.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

import pytest

from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.parallel import worker
from portfolio_engine.parallel.batching import PortfolioBatch, canonical_order
from portfolio_engine.parallel.task import ExecutionContext, ExecutionStatus, run_portfolio
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import compare_results, requests_for, snapshot_of
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
WORKLOAD = WorkloadSpec(
    (
        OperationSpec(
            OperationKind.FRONTIER_FIXED_COMPOSITION,
            CostTreatment.GROSS,
            method=FrontierMethod.RISK_AVERSION_GRID,
        ),
    )
)


@pytest.fixture()
def context(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, worker.WorkerContext]:
    problem = random_problem(8, [0, 1, 2], 3, CONFIG)
    execution = ExecutionContext.create(CONFIG, snapshot_of(problem))
    ctx = worker.WorkerContext(
        execution, worker.snapshot_fingerprint(execution.snapshot), blas_threads=1
    )
    monkeypatch.setattr(worker, "_CONTEXT", ctx)
    return problem, ctx


def test_an_uninitialized_worker_refuses_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "_CONTEXT", None)
    with pytest.raises(RuntimeError, match="no está inicializado"):
        worker.worker_context()
    batch = PortfolioBatch(0, ())
    with pytest.raises(RuntimeError, match="no está inicializado"):
        worker.run_batch(batch)


def test_run_batch_returns_one_result_per_portfolio_in_batch_order(
    context: tuple[Any, worker.WorkerContext],
) -> None:
    problem, _ = context
    items = canonical_order(requests_for(problem, WORKLOAD, 4, seed=8))
    result = worker.run_batch(PortfolioBatch(3, items))
    assert result.batch_id == 3 and result.worker_pid == os.getpid()
    assert [r.sequence_id for r in result.results] == [item.sequence_id for item in items]
    assert [r.portfolio_id for r in result.results] == [i.request.portfolio_id for i in items]
    assert all(r.execution_status is ExecutionStatus.COMPLETED for r in result.results)
    assert all(r.worker_pid == os.getpid() for r in result.results)
    assert result.elapsed_seconds >= 0.0


def test_a_batch_gives_the_same_results_as_running_each_portfolio_alone(
    context: tuple[Any, worker.WorkerContext],
) -> None:
    """Un lote no influye en sus carteras: cada resultado es el de la ejecución individual."""
    problem, ctx = context
    items = canonical_order(requests_for(problem, WORKLOAD, 4, seed=9))
    batched = worker.run_batch(PortfolioBatch(0, items)).results
    for item, got in zip(items, batched, strict=True):
        alone = run_portfolio(item.request, ctx.execution)
        anonymous = dataclasses.replace(got, sequence_id=None, worker_pid=None)
        assert compare_results(alone, anonymous).differences == []


def test_the_snapshot_is_checked_against_contamination(
    context: tuple[Any, worker.WorkerContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    problem, _ = context
    items = canonical_order(requests_for(problem, WORKLOAD, 1, seed=1))
    monkeypatch.setattr(worker, "snapshot_fingerprint", lambda snapshot: "alterado")
    with pytest.raises(RuntimeError, match="cambió antes"):
        worker.run_batch(PortfolioBatch(0, items))


def test_a_snapshot_altered_during_the_batch_is_detected(
    context: tuple[Any, worker.WorkerContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    problem, _ = context
    items = canonical_order(requests_for(problem, WORKLOAD, 1, seed=1))
    real = worker.snapshot_fingerprint
    calls: list[int] = []

    def fingerprint(snapshot: Any) -> str:
        calls.append(1)
        return real(snapshot) if len(calls) == 1 else "alterado-durante-el-lote"

    monkeypatch.setattr(worker, "snapshot_fingerprint", fingerprint)
    with pytest.raises(RuntimeError, match="contaminación"):
        worker.run_batch(PortfolioBatch(0, items))


def test_shared_market_arrays_are_read_only(context: tuple[Any, worker.WorkerContext]) -> None:
    """Los arrays compartidos no se pueden escribir (PAR-004, nivel de objeto)."""
    _, ctx = context
    risk = ctx.execution.snapshot.risk_model
    for array in (risk.mu, risk.sigma):
        assert not array.flags.writeable
        with pytest.raises(ValueError, match="read-only"):
            array.flat[0] = 0.0


def test_the_fingerprint_changes_with_the_data(context: tuple[Any, worker.WorkerContext]) -> None:
    _, ctx = context
    other = snapshot_of(random_problem(8, [0, 1, 2], 4, CONFIG))
    assert worker.snapshot_fingerprint(other) != ctx.fingerprint
    assert worker.snapshot_fingerprint(ctx.execution.snapshot) == ctx.fingerprint
