"""Equivalencia T1 entre ejecución secuencial y paralela, clases W0-W5 (D-07).

Contrato T1 aprobado: se comparan **restricciones, estados, pesos, resultados y métricas** con las
tolerancias ya existentes (``T1_ABS_TOLERANCE`` es la de la regresión dorada; no se introduce
ninguna nueva). Los estados de solver se comparan por igualdad exacta y una diferencia de estado
nunca se acepta automáticamente. El comparador recorre **todos** los campos de los resultados
(dataclasses, arrays, enums) salvo los relojes de pared y el PID del worker.

Una sola ejecución secuencial y una sola paralela (spawn, 2 workers) por universo cubren todas las
clases; cada prueba extrae las carteras de su clase. La igualdad bit a bit (T0) solo se registra
como diagnóstico (``record_property``); no se exige.
"""

from __future__ import annotations

from typing import Any

import pytest

from portfolio_engine.config.parallel_config import ParallelConfig
from portfolio_engine.frontiers import HeuristicGapReport
from portfolio_engine.models.enums import SolverStatus
from portfolio_engine.models.frontier import CompositionFrontierResult, GlobalFrontierResult
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.optimizers import SCIP_AVAILABLE
from portfolio_engine.parallel.executor import ParallelExecutor, RunResult, SequentialExecutor
from portfolio_engine.parallel.task import ExecutionStatus, TaskResult
from portfolio_engine.scenarios import MultiScenarioResult
from tests.fixtures.parallel import (
    PROCESS_NAMES,
    T1_ABS_TOLERANCE,
    TIMING_NAMES,
    TIMING_SUFFIXES,
    Comparison,
    class_workloads,
    compare_results,
    parallel_config,
    reference_requests,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.integration

CONFIG = base_config()
PER_CLASS = 3
PARALLEL: ParallelConfig = parallel_config(workers=2, batch_size=4)


@pytest.fixture(scope="module")
def runs() -> dict[str, tuple[RunResult, RunResult]]:
    """``{universo: (secuencial, paralelo)}`` con las mismas solicitudes."""
    snapshots, by_universe = reference_requests(CONFIG, PER_CLASS)
    out: dict[str, tuple[RunResult, RunResult]] = {}
    for key, requests in by_universe.items():
        sequential = SequentialExecutor(CONFIG, snapshots[key]).run(requests)
        parallel = ParallelExecutor(CONFIG, snapshots[key], PARALLEL).run(requests)
        out[key] = (sequential, parallel)
    return out


def _pairs(
    runs: dict[str, tuple[RunResult, RunResult]], label: str
) -> list[tuple[TaskResult, TaskResult]]:
    universe, _ = class_workloads()[label]
    sequential, parallel = runs[universe]
    seq = {
        r.portfolio_id: r for r in sequential.results if r.portfolio_id.rsplit("-", 1)[0] == label
    }
    par = parallel.by_portfolio()
    assert len(seq) == PER_CLASS
    return [(seq[pid], par[pid]) for pid in sorted(seq)]


def _skip_without_scip(label: str) -> None:
    if label.startswith("W5") and not SCIP_AVAILABLE:
        pytest.skip("PySCIPOpt (opcional, E-24) no instalado")


@pytest.mark.parametrize("label", list(class_workloads()))
def test_parallel_results_match_sequential_results_under_t1(
    label: str, runs: dict[str, Any], record_property: Any
) -> None:
    _skip_without_scip(label)
    worst = 0.0
    for sequential, parallel in _pairs(runs, label):
        assert sequential.execution_status is ExecutionStatus.COMPLETED, sequential.error
        assert parallel.execution_status is sequential.execution_status
        assert parallel.sequence_id == sequential.sequence_id
        assert parallel.worker_pid is not None and sequential.worker_pid is None
        comparison = compare_results(sequential, parallel)
        assert comparison.differences == [], (label, sequential.portfolio_id)
        assert comparison.float_comparisons > 0
        worst = max(worst, comparison.max_abs_difference)
    record_property("t0_diagnostic_max_abs_difference", worst)  # T0: solo diagnóstico


def _results(runs: dict[str, Any], label: str, kind: type) -> list[tuple[Any, Any]]:
    pairs = []
    for sequential, parallel in _pairs(runs, label):
        for a, b in zip(sequential.operations, parallel.operations, strict=True):
            assert isinstance(a.result, kind) and isinstance(b.result, kind)
            pairs.append((a.result, b.result))
    return pairs


def test_w0_frontier_points_states_weights_and_metrics_match(runs: dict[str, Any]) -> None:
    pairs = _results(runs, "W0-GROSS-RISK", CompositionFrontierResult)
    assert pairs
    for expected, got in pairs:
        assert len(expected.points) == len(got.points) > 0
        for a, b in zip(expected.points, got.points, strict=True):
            assert a.status is b.status and a.status_source is b.status_source
            assert a.is_valid_solution == b.is_valid_solution
            assert (
                a.validation == b.validation
                or compare_results(a.validation, b.validation).differences == []
            )
            if a.weights is not None:
                assert b.weights is not None
                assert abs(a.weights - b.weights).max() <= T1_ABS_TOLERANCE
            if a.metrics is not None:
                assert b.metrics is not None
                assert compare_results(a.metrics, b.metrics).differences == []
        assert expected.constraint_hash == got.constraint_hash
        assert expected.composition_id == got.composition_id
        assert expected.diagnostics.total_iterations == got.diagnostics.total_iterations


def test_w1_candidate_search_and_global_pareto_match(runs: dict[str, Any]) -> None:
    for expected, got in _results(runs, "W1-GLOBAL-NET", GlobalFrontierResult):
        assert [c.composition_hash for c in expected.candidates] == [
            c.composition_hash for c in got.candidates
        ]
        assert [p.is_duplicate for p in expected.points] == [p.is_duplicate for p in got.points]
        assert expected.diagnostics.candidate_count == got.diagnostics.candidate_count
        assert expected.diagnostics.points_efficient == got.diagnostics.points_efficient


@pytest.mark.parametrize("label", ["W2-INDEPENDENT", "W2-EXPECTED", "W2-WORST-CASE", "W2-STRESS"])
def test_w2_scenario_results_match(label: str, runs: dict[str, Any]) -> None:
    for expected, got in _results(runs, label, MultiScenarioResult):
        assert expected.mode is got.mode and expected.scenario_ids == got.scenario_ids
        assert expected.probabilities == got.probabilities
        assert [s for s, _ in expected.frontiers] == [s for s, _ in got.frontiers]
        if expected.single_solution is not None:
            assert got.single_solution is not None
            assert expected.single_solution.status is got.single_solution.status
            assert (
                expected.single_solution.is_valid_solution == got.single_solution.is_valid_solution
            )


@pytest.mark.parametrize("label", ["W3-MIN-CVAR", "W4-ROBUST", "W4-MAX-SHARPE", "W4-VOL-TARGET"])
def test_w3_w4_strategies_match_including_cvar_and_claims(label: str, runs: dict[str, Any]) -> None:
    for expected, got in _results(runs, label, StrategyResult):
        assert expected.status is got.status
        assert expected.outcome == got.outcome
        assert expected.optimality_claim is got.optimality_claim
        assert expected.is_valid_solution == got.is_valid_solution
        assert expected.weights is not None and got.weights is not None
        assert abs(expected.weights - got.weights).max() <= T1_ABS_TOLERANCE
        assert expected.metrics is not None and got.metrics is not None
        assert compare_results(expected.metrics, got.metrics).differences == []
        assert expected.status in {SolverStatus.OPTIMAL, SolverStatus.OPTIMAL_INACCURATE}


def test_w3_cvar_metric_is_compared(runs: dict[str, Any]) -> None:
    """El CVaR de la solución (métrica del Bloque 4) coincide entre ejecuciones."""
    for expected, got in _results(runs, "W3-MIN-CVAR", StrategyResult):
        assert compare_results(expected, got).differences == []
        for name in ("cvar_period", "cvar_horizon"):
            a, b = expected.extra(name), got.extra(name)
            assert a is not None and b is not None, name
            assert abs(a - b) <= T1_ABS_TOLERANCE


@pytest.mark.skipif(not SCIP_AVAILABLE, reason="PySCIPOpt (opcional, E-24) no instalado")
def test_w5_mip_results_match(runs: dict[str, Any]) -> None:
    for sequential, parallel in _pairs(runs, "W5-EXACT-MIP"):
        a, b = sequential.operations[1].result, parallel.operations[1].result
        assert isinstance(a, HeuristicGapReport) and isinstance(b, HeuristicGapReport)
        assert compare_results(a, b).differences == []
        assert a.mip_claim is b.mip_claim and a.mip_valid == b.mip_valid


def test_pipeline_workloads_match_operation_by_operation(runs: dict[str, Any]) -> None:
    for sequential, parallel in _pairs(runs, "PIPELINE"):
        assert [o.kind for o in sequential.operations] == [o.kind for o in parallel.operations]
        assert len(sequential.operations) == 3
        assert compare_results(sequential.operations, parallel.operations).differences == []


# ------------------------------------------------------------- el propio comparador T1


def test_the_comparator_only_excludes_clocks_and_the_worker_pid(runs: dict[str, Any]) -> None:
    """Garantiza que el comparador no descarta en silencio campos del cálculo."""
    comparison = Comparison()
    for label in class_workloads():
        if label.startswith("W5") and not SCIP_AVAILABLE:
            continue
        for sequential, parallel in _pairs(runs, label):
            comparison.compare(sequential, parallel)
    assert comparison.excluded
    for excluded in comparison.excluded:
        name = excluded.split(".", 1)[1]
        assert name in TIMING_NAMES or name.endswith(TIMING_SUFFIXES) or name in PROCESS_NAMES, (
            excluded
        )


def test_the_comparator_detects_real_differences(runs: dict[str, Any]) -> None:
    import dataclasses

    import numpy as np

    sequential, parallel = _pairs(runs, "W0-GROSS-RISK")[0]
    frontier = parallel.operations[0].result
    assert isinstance(frontier, CompositionFrontierResult)
    point = next(p for p in frontier.points if p.weights is not None)

    def with_point(new_point: Any) -> TaskResult:
        points = tuple(new_point if p is point else p for p in frontier.points)
        outcome = dataclasses.replace(
            parallel.operations[0], result=dataclasses.replace(frontier, points=points)
        )
        return dataclasses.replace(parallel, operations=(outcome,))

    shifted = dataclasses.replace(point, weights=point.weights + 1e-3)
    assert compare_results(sequential, with_point(shifted)).differences  # fuera de T1
    tiny = dataclasses.replace(point, weights=point.weights + T1_ABS_TOLERANCE / 10)
    assert compare_results(sequential, with_point(tiny)).differences == []  # dentro de T1
    other_status = dataclasses.replace(point, status=SolverStatus.INFEASIBLE)
    assert any(
        "status" in d for d in compare_results(sequential, with_point(other_status)).differences
    )
    assert not np.array_equal(shifted.weights, point.weights)


def _has_valid_solution(result: Any) -> bool:
    if isinstance(result, CompositionFrontierResult):
        return any(point.is_valid_solution for point in result.points)
    if isinstance(result, GlobalFrontierResult):
        return any(point.is_valid_solution for point in result.points)
    if isinstance(result, StrategyResult):
        return result.is_valid_solution
    if isinstance(result, MultiScenarioResult):
        if result.single_solution is not None:
            return result.single_solution.is_valid_solution
        return all(_has_valid_solution(frontier) for _, frontier in result.frontiers)
    return bool(result.mip_valid)


@pytest.mark.parametrize("label", list(class_workloads()))
def test_equivalence_is_not_vacuous_every_class_produces_valid_solutions(
    label: str, runs: dict[str, Any]
) -> None:
    """Cada clase contiene soluciones válidas (no se compara solo «nada con nada»).

    Algunas carteras de ``W2-STRESS`` son legítimamente ``INFEASIBLE`` (el límite de estrés del
    escenario CRASH no admite su cartera actual): esa ruta no óptima también se compara (estado
    exacto), y basta con que la clase tenga al menos una solución válida.
    """
    _skip_without_scip(label)
    valid = [
        _has_valid_solution(outcome.result)
        for sequential, _ in _pairs(runs, label)
        for outcome in sequential.operations
    ]
    assert any(valid), label
