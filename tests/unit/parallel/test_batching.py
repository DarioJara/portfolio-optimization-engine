"""PAR-001, PAR-003, PAR-010: lotes de carteras, ``SequenceID`` y tamaño AUTO."""

from __future__ import annotations

import random

import pytest

from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.parallel.batching import (
    ParallelExecutionError,
    canonical_order,
    make_batches,
    resolve_batch_size,
)
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import parallel_config, requests_for
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

WORKLOAD = WorkloadSpec(
    (
        OperationSpec(
            OperationKind.FRONTIER_FIXED_COMPOSITION,
            CostTreatment.GROSS,
            method=FrontierMethod.RISK_AVERSION_GRID,
        ),
    )
)


@pytest.fixture(scope="module")
def requests() -> list:  # type: ignore[type-arg]
    problem = random_problem(8, [0, 1, 2], 3, base_config())
    return requests_for(problem, WORKLOAD, 23, seed=5)


def test_sequence_ids_follow_the_portfolio_id_not_the_input_order(requests: list) -> None:  # type: ignore[type-arg]
    shuffled = list(requests)
    random.Random(1).shuffle(shuffled)
    reference = canonical_order(requests)
    permuted = canonical_order(shuffled)
    assert [item.sequence_id for item in permuted] == list(range(len(requests)))
    assert [i.request.portfolio_id for i in permuted] == [i.request.portfolio_id for i in reference]
    assert [i.request.portfolio_id for i in reference] == sorted(r.portfolio_id for r in requests)


def test_duplicate_portfolio_ids_are_rejected(requests: list) -> None:  # type: ignore[type-arg]
    with pytest.raises(ParallelExecutionError, match="duplicado"):
        canonical_order([*requests, requests[3]])


@pytest.mark.parametrize("size", [1, 2, 5, 7, 23, 50])
def test_fixed_batches_partition_the_portfolios_exactly_once(requests: list, size: int) -> None:  # type: ignore[type-arg]
    config = parallel_config(batch_size=size)
    batches = make_batches(canonical_order(requests), config)
    flattened = [sid for batch in batches for sid in batch.sequence_ids]
    assert flattened == list(range(len(requests)))  # sin pérdida, sin duplicados, en orden
    assert all(1 <= len(batch.items) <= size for batch in batches)
    assert [batch.batch_id for batch in batches] == list(range(len(batches)))
    assert all(len(batch.items) == size for batch in batches[:-1])


def test_auto_batch_size_balances_load_and_respects_the_bounds() -> None:
    config = parallel_config(workers=2, auto_batches_per_worker=4, max_batch_size=50)
    assert config.batch_size is None
    assert resolve_batch_size(config, 80) == 10  # ceil(80 / 8)
    assert resolve_batch_size(config, 81) == 11
    assert resolve_batch_size(config, 3) == 1  # nunca menos de 1
    assert resolve_batch_size(config, 10_000) == 50  # acotado por max_batch_size


def test_a_fixed_batch_size_wins_over_auto() -> None:
    assert resolve_batch_size(parallel_config(batch_size=7), 1000) == 7


def test_no_portfolios_cannot_be_batched() -> None:
    with pytest.raises(ParallelExecutionError):
        resolve_batch_size(parallel_config(), 0)
    assert make_batches((), parallel_config()) == ()


def test_batching_is_a_pure_function_of_the_inputs(requests: list) -> None:  # type: ignore[type-arg]
    config = parallel_config(batch_size=4)
    first = make_batches(canonical_order(requests), config)
    second = make_batches(canonical_order(list(reversed(requests))), config)
    assert [b.sequence_ids for b in first] == [b.sequence_ids for b in second]
