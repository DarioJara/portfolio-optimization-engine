"""PAR-008, PAR-010: los resultados no dependen de workers, tamaño de lote, orden ni repeticiones.

Criterio T1 (D-07): equivalencia dentro de las tolerancias existentes con estados idénticos; la
igualdad bit a bit (T0) se registra como diagnóstico (``record_property``) sin exigirse.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from portfolio_engine.config.parallel_config import ParallelConfig
from portfolio_engine.parallel.executor import ParallelExecutor, RunResult, SequentialExecutor
from portfolio_engine.parallel.task import ExecutionStatus, PortfolioRequest
from tests.fixtures.parallel import (
    Comparison,
    class_workloads,
    parallel_config,
    reference_universes,
    requests_for,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.integration

CONFIG = base_config()
LABELS = ("W0-NET-TARGET", "W4-MAX-SHARPE", "W3-MIN-CVAR")
N_PER_LABEL = 3

#: (workers, batch_size) — ``None`` = AUTO.
SCHEDULES: dict[str, tuple[int, int | None]] = {
    "1 worker, lotes de 1": (1, 1),
    "3 workers, lotes de 2": (3, 2),
    "2 workers, AUTO": (2, None),
    "2 workers, un único lote": (2, 9),
}


@pytest.fixture(scope="module")
def setup() -> tuple[Any, list[PortfolioRequest], RunResult]:
    problem, snapshot = reference_universes(CONFIG)["p8"]
    requests: list[PortfolioRequest] = []
    for label in LABELS:
        _, workload = class_workloads()[label]
        requests.extend(
            requests_for(problem, workload, N_PER_LABEL, seed=len(label), prefix=f"{label}-")
        )
    reference = SequentialExecutor(CONFIG, snapshot).run(requests)
    return snapshot, requests, reference


def _compare(run: RunResult, reference: RunResult) -> Comparison:
    assert [r.portfolio_id for r in run.results] == [r.portfolio_id for r in reference.results]
    assert [r.sequence_id for r in run.results] == list(range(len(reference.results)))
    comparison = Comparison()
    comparison.compare(reference.results, run.results)
    return comparison


def test_the_reference_run_covers_all_requested_classes(
    setup: tuple[Any, list[PortfolioRequest], RunResult],
) -> None:
    _, requests, reference = setup
    assert len(reference.results) == len(LABELS) * N_PER_LABEL == len(requests)
    assert all(r.execution_status is ExecutionStatus.COMPLETED for r in reference.results)


@pytest.mark.parametrize("schedule", list(SCHEDULES))
def test_results_do_not_depend_on_workers_or_batch_size(
    schedule: str,
    setup: tuple[Any, list[PortfolioRequest], RunResult],
    record_property: Any,
) -> None:
    snapshot, requests, reference = setup
    workers, batch_size = SCHEDULES[schedule]
    config: ParallelConfig = parallel_config(workers=workers, batch_size=batch_size)
    shuffled = list(requests)
    random.Random(workers * 7 + (batch_size or 0)).shuffle(shuffled)  # orden de envío distinto
    run = ParallelExecutor(CONFIG, snapshot, config).run(shuffled)
    comparison = _compare(run, reference)
    assert comparison.differences == [], schedule
    assert comparison.float_comparisons > 0
    record_property("t0_diagnostic_inexact_floats", comparison.inexact_floats)
    record_property("t0_diagnostic_max_abs_difference", comparison.max_abs_difference)


def test_repeating_the_same_parallel_run_gives_the_same_results(
    setup: tuple[Any, list[PortfolioRequest], RunResult],
) -> None:
    snapshot, requests, _ = setup
    config = parallel_config(workers=2, batch_size=2)
    first = ParallelExecutor(CONFIG, snapshot, config).run(requests)
    second = ParallelExecutor(CONFIG, snapshot, config).run(requests)
    assert _compare(second, first).differences == []
    assert first.manifest.run_hash == second.manifest.run_hash  # misma identidad de ejecución


def test_task_identities_are_the_same_across_schedules(
    setup: tuple[Any, list[PortfolioRequest], RunResult],
) -> None:
    snapshot, requests, reference = setup
    run = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=2, batch_size=3)).run(requests)
    assert [r.task_id for r in run.results] == [r.task_id for r in reference.results]
    assert len({r.task_id for r in run.results}) == len(requests)
