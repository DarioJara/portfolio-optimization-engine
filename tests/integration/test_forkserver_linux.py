"""Smoke test real de forkserver en Linux para PAR-013 (datos sintéticos)."""
from __future__ import annotations

import dataclasses
import sys

import pytest

from portfolio_engine.config.parallel_config import ProcessStartMethod
from portfolio_engine.parallel.executor import ParallelExecutor, SequentialExecutor
from tests.fixtures.parallel import compare_results, parallel_config, requests_for, snapshot_of
from tests.fixtures.candidates import random_problem
from tests.fixtures.problems import base_config
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from portfolio_engine.models.enums import CostTreatment, FrontierMethod

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="forkserver Linux-only CI test"),
]


def test_forkserver_results_match_sequential_and_use_workers() -> None:
    config = base_config()
    problem = random_problem(8, [0, 1, 2], 3, config)
    snapshot = snapshot_of(problem)
    workload = WorkloadSpec(
        (OperationSpec(
            OperationKind.FRONTIER_FIXED_COMPOSITION,
            CostTreatment.NET,
            method=FrontierMethod.RISK_AVERSION_GRID,
        ),)
    )
    requests = requests_for(problem, workload, 4, seed=73)
    expected = SequentialExecutor(config, snapshot).run(requests)
    parallel = dataclasses.replace(
        parallel_config(workers=2, batch_size=2),
        start_method=ProcessStartMethod.FORKSERVER,
    )
    actual = ParallelExecutor(config, snapshot, parallel).run(requests)
    assert len(actual.results) == len(expected.results)
    assert actual.manifest.start_method == "forkserver"
    assert len({r.worker_pid for r in actual.results}) >= 1
    for left, right in zip(expected.results, actual.results, strict=True):
        assert compare_results(left, right).differences == []
