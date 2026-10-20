"""PAR-004, PAR-005, CCH-003/005: equivalencia T1 con cada modo de datos y con caché.

Cada modo (``BUNDLE_FILE``, ``FILE_MMAP``, ``SHARED_MEMORY``) corre con un pool real y se compara
con la referencia secuencial (T1, tolerancias existentes, estados exactos). En Linux se repite con
``forkserver``. No quedan recursos residuales (directorios ni segmentos) tras cada ejecución.
"""

from __future__ import annotations

import dataclasses
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from portfolio_engine.config import ProcessStartMethod, SharedDataMode
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.optimizers import SCIP_AVAILABLE
from portfolio_engine.parallel.executor import ParallelExecutor, RunResult, SequentialExecutor
from portfolio_engine.parallel.shared_data import inventory_orphans
from portfolio_engine.parallel.task import ExecutionStatus, PortfolioRequest
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.parallel import (
    cache_config,
    class_workloads,
    compare_results,
    parallel_config,
    reference_universes,
    requests_for,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.integration

CONFIG = base_config()
#: Cota de la referencia que viaja por el pipe de arranque.
MAX_HANDLE_BYTES = 2048
LABELS = ("W0-GROSS-RISK", "W1-GLOBAL-NET", "W3-MIN-CVAR", "W4-MAX-SHARPE", "W4-ROBUST", "PIPELINE")
START_METHODS = [ProcessStartMethod.SPAWN] + (
    [ProcessStartMethod.FORKSERVER] if sys.platform == "linux" else []
)


@pytest.fixture(scope="module")
def setup() -> tuple[Any, list[PortfolioRequest], RunResult]:
    problem, snapshot = reference_universes(CONFIG)["p8"]
    requests: list[PortfolioRequest] = []
    for label in LABELS:
        _, workload = class_workloads()[label]
        requests.extend(requests_for(problem, workload, 2, seed=len(label), prefix=f"{label}-"))
    return snapshot, requests, SequentialExecutor(CONFIG, snapshot).run(requests)


def _assert_equivalent(run: RunResult, reference: RunResult) -> None:
    assert [r.portfolio_id for r in run.results] == [r.portfolio_id for r in reference.results]
    for got, expected in zip(run.results, reference.results, strict=True):
        assert got.execution_status is expected.execution_status
        assert compare_results(expected, got).differences == [], got.portfolio_id


@pytest.mark.parametrize("start", START_METHODS, ids=lambda m: m.value)
@pytest.mark.parametrize("mode", list(SharedDataMode), ids=lambda m: m.value)
def test_every_shared_data_mode_matches_the_sequential_reference(
    mode: SharedDataMode,
    start: ProcessStartMethod,
    setup: tuple[Any, list[PortfolioRequest], RunResult],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, requests, reference = setup
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    config = dataclasses.replace(
        parallel_config(workers=2, batch_size=3), shared_data_mode=mode, start_method=start
    )
    run = ParallelExecutor(CONFIG, snapshot, config).run(requests)
    _assert_equivalent(run, reference)
    assert all(r.execution_status is ExecutionStatus.COMPLETED for r in run.results)
    assert run.manifest.shared_data_mode == mode.value and run.manifest.start_method == start.value
    assert run.publication is not None and run.publication.mode is mode
    assert run.publication.handle_bytes < MAX_HANDLE_BYTES  # el pipe solo recibe la referencia
    assert list(tmp_path.iterdir()) == []  # directorio y segmento eliminados
    assert inventory_orphans(tmp_path, min_age_seconds=0.0).empty


MULTI_SCENARIO_LABELS = ("W2-INDEPENDENT", "W2-EXPECTED", "W2-WORST-CASE", "W2-STRESS")


@pytest.fixture(scope="module")
def multi_scenario_setup() -> tuple[Any, list[PortfolioRequest], RunResult]:
    """Auditoría B5.3 (L-6): la clase W2 (multiescenario) también viaja por los modos de datos."""
    problem, snapshot = reference_universes(CONFIG)["p4"]
    requests: list[PortfolioRequest] = []
    for label in MULTI_SCENARIO_LABELS:
        _, workload = class_workloads()[label]
        requests.extend(requests_for(problem, workload, 2, seed=len(label), prefix=f"{label}-"))
    return snapshot, requests, SequentialExecutor(CONFIG, snapshot).run(requests)


@pytest.mark.parametrize("mode", list(SharedDataMode), ids=lambda m: m.value)
def test_multi_scenario_results_match_in_every_shared_data_mode(
    mode: SharedDataMode,
    multi_scenario_setup: tuple[Any, list[PortfolioRequest], RunResult],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, requests, reference = multi_scenario_setup
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    config = dataclasses.replace(parallel_config(workers=2, batch_size=2), shared_data_mode=mode)
    run = ParallelExecutor(CONFIG, snapshot, config).run(requests)
    _assert_equivalent(run, reference)
    assert all(r.execution_status is ExecutionStatus.COMPLETED for r in run.results)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not SCIP_AVAILABLE, reason="PySCIPOpt (opcional, E-24) no instalado")
@pytest.mark.parametrize("mode", [SharedDataMode.FILE_MMAP, SharedDataMode.SHARED_MEMORY])
def test_exact_mip_works_over_shared_arrays(
    mode: SharedDataMode, setup: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    snapshot, _, _ = setup
    problem, _ = reference_universes(CONFIG)["p8"]
    _, workload = class_workloads()["W5-EXACT-MIP"]
    requests = requests_for(problem, workload, 2, seed=5, prefix="MIP-")
    expected = SequentialExecutor(CONFIG, snapshot).run(requests)
    config = dataclasses.replace(parallel_config(workers=2), shared_data_mode=mode)
    _assert_equivalent(ParallelExecutor(CONFIG, snapshot, config).run(requests), expected)


@pytest.mark.parametrize("mode", [SharedDataMode.BUNDLE_FILE, SharedDataMode.FILE_MMAP])
def test_the_cache_is_exact_and_hits_are_counted_across_workers(
    mode: SharedDataMode, setup: tuple[Any, list[PortfolioRequest], RunResult]
) -> None:
    """Con caché activada, las operaciones repetidas no se calculan y el resultado no cambia."""
    snapshot, _, _ = setup
    problem, _ = reference_universes(CONFIG)["p8"]
    frontier = OperationSpec(
        OperationKind.FRONTIER_FIXED_COMPOSITION,
        CostTreatment.NET,
        method=FrontierMethod.RISK_AVERSION_GRID,
    )
    sharpe = OperationSpec(OperationKind.STRATEGY_MAX_SHARPE, CostTreatment.NET)
    workload = WorkloadSpec((frontier, sharpe, frontier, sharpe, frontier))
    requests = requests_for(problem, workload, 6, seed=14, prefix="DUP-")
    reference = SequentialExecutor(CONFIG, snapshot).run(requests)
    config = dataclasses.replace(
        parallel_config(workers=2, batch_size=2), shared_data_mode=mode, cache=cache_config()
    )
    run = ParallelExecutor(CONFIG, snapshot, config).run(requests)
    _assert_equivalent(run, reference)
    metrics = run.cache_metrics
    assert (metrics.misses, metrics.hits) == (12, 18)  # 2 operaciones distintas × 6 carteras
    assert metrics.stores == 12 and metrics.evictions == 0 and metrics.rejected == 0
    assert run.manifest.cache_enabled
    for result in run.results:
        events = [o.cache_event.value for o in result.operations]
        assert events == ["MISS", "MISS", "HIT", "HIT", "HIT"]


def test_the_cache_is_off_by_default_in_parallel_runs(
    setup: tuple[Any, list[PortfolioRequest], RunResult],
) -> None:
    snapshot, requests, _ = setup
    run = ParallelExecutor(CONFIG, snapshot, parallel_config(workers=1)).run(requests[:2])
    assert not run.manifest.cache_enabled
    assert run.cache_metrics.hits == run.cache_metrics.misses == 0
    assert all(o.cache_event.value == "DISABLED" for r in run.results for o in r.operations)
