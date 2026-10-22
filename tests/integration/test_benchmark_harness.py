"""B5.5 (BEN-004, BEN-006, BEN-007, C-01, C-07, C-08, C-27): el harness de benchmarks.

Comprueba que el generador sintético es determinista y diverso, que las carteras degeneradas
ejercitan las rutas de error sin romper el lote, que el auditor independiente de restricciones
detecta violaciones (prueba de mutación del propio auditor) y que una ejecución paralela con
procesos reales equivale a la secuencial bajo T1 con histogramas de estados idénticos.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest

from portfolio_engine.config.scaling_config import (
    ClassShare,
    WorkloadMix,
    load_scaling_benchmark_config,
)
from portfolio_engine.models.enums import SolverStatus
from portfolio_engine.parallel.executor import ParallelExecutor, SequentialExecutor
from portfolio_engine.parallel.task import ExecutionStatus
from tests.conftest import REPO_ROOT
from tests.fixtures.benchmark_scripts import load_script
from tests.fixtures.parallel import compare_results, parallel_config

pytestmark = pytest.mark.integration

CONFIG_PATH = REPO_ROOT / "config" / "default_benchmark.toml"
SCALING = load_scaling_benchmark_config(CONFIG_PATH)
SYNTHETIC = load_script("synthetic_portfolios")
COMMON = load_script("_common")


def _pure(label: str) -> WorkloadMix:
    return WorkloadMix("TEST", (ClassShare(label, 1.0),))


def test_class_counts_sum_to_the_requested_total_for_every_configured_mix() -> None:
    for mix in SCALING.mixes:
        for total in (1, 7, 10, 33, 100, 1200, 22000):
            counts = SYNTHETIC.allocate_counts(mix, total)
            assert sum(counts.values()) == total and min(counts.values()) >= 0
            for share in mix.shares:  # el mayor resto se desvía menos de 1 cartera de lo exacto
                assert abs(counts[share.label] - share.fraction * total) < 1.0


def test_generation_is_deterministic_by_seed_and_changes_with_it() -> None:
    mix = SCALING.mix("ENG-MIX-BASE")
    first = SYNTHETIC.generate(SCALING, mix, 12, 7)
    again = SYNTHETIC.generate(SCALING, mix, 12, 7)
    other = SYNTHETIC.generate(SCALING, mix, 12, 8)
    assert first.labels == again.labels and first.counts == again.counts
    for a, b in zip(first.requests, again.requests, strict=True):
        assert a.portfolio_id == b.portfolio_id and a.state.state_hash == b.state.state_hash
    assert first.labels != other.labels or any(
        a.state.state_hash != b.state.state_hash
        for a, b in zip(first.requests, other.requests, strict=True)
    )
    ids = [r.portfolio_id for r in first.requests]
    assert len(set(ids)) == len(ids)
    assert len({r.state.state_hash for r in first.requests}) > len(ids) // 2  # carteras distintas


def test_degenerate_portfolios_exercise_error_paths_without_breaking_the_batch() -> None:
    config = dataclasses.replace(SCALING, degenerate_fraction=0.5)
    batch = SYNTHETIC.generate(config, _pure("W0-NET-TARGET"), 8, 3)
    run = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    assert run.accounting is not None and run.accounting.balanced
    failed = [
        r for r in run.results if r.execution_status is ExecutionStatus.FAILED_INPUT_VALIDATION
    ]
    infeasible = [
        r
        for r in run.results
        if r.execution_status is ExecutionStatus.COMPLETED
        and any(getattr(o.result, "status", None) is SolverStatus.INFEASIBLE for o in r.operations)
    ]
    healthy = [r for r in run.results if r.execution_status is ExecutionStatus.COMPLETED]
    assert len(failed) + len(infeasible) >= 1  # al menos una ruta de error ejercitada
    assert len(healthy) >= 4  # el lote sigue produciendo resultados


def test_the_independent_constraint_audit_detects_violations_in_mutated_results() -> None:
    """Mutación del auditor: pesos corrompidos a propósito deben ser detectados."""
    batch = SYNTHETIC.generate(SCALING, _pure("W0-GROSS-RISK"), 2, 5)
    run = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    clean = COMMON.audit_constraints(run.results, batch.snapshot, batch.config)
    assert clean.clean and clean.solutions > 0

    point = run.results[0].operations[0].result.points[0]  # type: ignore[union-attr]
    original = np.array(point.weights)

    def audit_with(weights: np.ndarray) -> object:  # type: ignore[type-arg]
        object.__setattr__(point, "weights", weights)
        try:
            return COMMON.audit_constraints(run.results, batch.snapshot, batch.config)
        finally:
            object.__setattr__(point, "weights", original)

    broken_budget = original.copy()
    broken_budget[0] += 1e-3
    assert audit_with(broken_budget).budget_violations >= 1  # type: ignore[attr-defined]
    over_cap = original.copy()
    over_cap[0] = 5.0
    assert audit_with(over_cap).bound_violations >= 1  # type: ignore[attr-defined]
    negative = original.copy()
    negative[0] = -0.01
    negative[1] += 0.01
    assert audit_with(negative).bound_violations >= 1  # type: ignore[attr-defined]
    assert audit_with(original).clean  # type: ignore[attr-defined]


def test_a_mixed_batch_in_a_real_pool_equals_the_sequential_run_under_t1() -> None:
    """C-01/C-08: spawn con 2 workers ≡ secuencial (T1), mismos estados, restricciones intactas."""
    config = dataclasses.replace(SCALING, degenerate_fraction=0.2)
    batch = SYNTHETIC.generate(config, SCALING.mix("ENG-MIX-LIGHT"), 10, 11)
    reference = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    run = ParallelExecutor(batch.config, batch.snapshot, parallel_config(workers=2)).run(
        batch.requests
    )
    assert run.accounting is not None and run.accounting.balanced
    assert [r.portfolio_id for r in run.results] == [r.portfolio_id for r in reference.results]
    for got, expected in zip(run.results, reference.results, strict=True):
        assert compare_results(expected, got).differences == [], got.portfolio_id
    seq_audit = COMMON.audit_constraints(reference.results, batch.snapshot, batch.config)
    par_audit = COMMON.audit_constraints(run.results, batch.snapshot, batch.config)
    assert par_audit.clean and seq_audit.clean
    assert par_audit.status_histogram == seq_audit.status_histogram  # C-08
    assert COMMON.status_counts(run.results) == COMMON.status_counts(reference.results)
    assert COMMON.frontier_iterations(run.results) == COMMON.frontier_iterations(reference.results)


def test_the_scale_runner_refuses_mass_loads_without_authorization() -> None:
    """D-12: ninguna escala >= 1.000 carteras se ejecuta sin ``--authorized-by``."""
    scale_run = load_script("scale_run")
    args = SimpleNamespace(
        config=CONFIG_PATH,
        scales=[10, 1200],
        mix="ENG-MIX-BASE",
        workers=[1],
        methods=["sequential"],
        authorized_by=None,
        out=REPO_ROOT / "benchmarks" / "results",
    )
    with pytest.raises(SystemExit, match="autorización"):
        scale_run._run(args)
    scaling_script = load_script("scaling")
    with pytest.raises(SystemExit, match="autorización"):
        import sys

        sys.argv = ["scaling.py", "--scales", "1200", "--mix", "ENG-MIX-BASE"]
        scaling_script.main()


def test_the_watchdog_cancels_once_on_the_wall_limit_and_on_a_worker_rss_limit() -> None:
    """Los topes ``--max-wall`` y ``--max-rss-mb`` cancelan una sola vez y dejan su causa."""
    import subprocess
    import sys
    import time

    calls: list[int] = []
    with COMMON.Watchdog(lambda: calls.append(1), COMMON.Limits(max_wall_seconds=0.3), 0.05) as dog:
        time.sleep(1.0)
    assert calls == [1] and dog.reason is not None and "max-wall" in dog.reason

    calls.clear()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; blob = bytearray(80_000_000); time.sleep(10)"]
    )
    try:
        limits = COMMON.Limits(max_worker_rss_bytes=40_000_000)
        with COMMON.Watchdog(lambda: calls.append(1), limits, 0.05) as dog:
            deadline = time.perf_counter() + 20.0
            while not calls and time.perf_counter() < deadline:
                time.sleep(0.05)
        assert calls == [1] and dog.reason is not None and "RSS" in dog.reason
    finally:
        child.kill()
        child.wait()

    calls.clear()
    with COMMON.Watchdog(lambda: calls.append(1), COMMON.Limits(), 0.05) as dog:
        time.sleep(0.3)  # sin topes no se cancela nada
    assert calls == [] and dog.reason is None


def test_a_parallel_cell_that_exceeds_its_wall_limit_is_aborted_and_never_valid() -> None:
    """Una celda cancelada por el tope se marca ``aborted`` y no es una medición válida."""
    scaling_script = load_script("scaling")
    batch = SYNTHETIC.generate(SCALING, _pure("W0-GROSS-RISK"), 4, 2)
    reference = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    cell = scaling_script._parallel_cell(
        batch, reference, "spawn", 2, 1, 0, 0, None, 1, "BUNDLE_FILE", COMMON.Limits(0.5, None)
    )
    assert cell["valid_measurement"] is False and "max-wall" in cell["aborted"]
    assert "wall" not in cell  # sin cifras de rendimiento de una ejecución abortada


def test_throughput_rates_divide_the_deterministic_work_by_the_wall_time() -> None:
    """BEN-002: carteras/s, fronteras/s y llamadas al solver/s = trabajo determinista ÷ tiempo."""
    scaling_script = load_script("scaling")
    batch = SYNTHETIC.generate(SCALING, _pure("W0-GROSS-RISK"), 3, 4)
    run = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    frontiers = COMMON.frontier_count(run.results)
    assert frontiers == 3  # una frontera de composición fija por cartera W0
    cells = [
        {"mode": "sequential", "workers": 1, "wall": {"min": 2.0}},
        {"mode": "spawn", "workers": 4, "batch_size": "AUTO", "wall": {"min": 0.5}},
    ]
    rates = scaling_script._rates(cells, run, 60)
    assert rates["sequential:w1:b-"] == {
        "portfolios_per_second": 1.5,
        "frontiers_per_second": 1.5,
        "solver_calls_per_second": 30.0,
    }
    assert rates["spawn:w4:bAUTO"]["portfolios_per_second"] == 6.0
    assert (
        scaling_script._rates(cells, run, None)["sequential:w1:b-"]["solver_calls_per_second"]
        is None
    )


def test_valid_weights_rejected_by_status_invalidate_the_audit() -> None:
    """A-03 / H-1: pesos correctos con ``is_valid_solution`` falso (p. ej. ``OPTIMAL_INACCURATE``)
    ya no pasan inadvertidos: el contador sube y la celda dejaría de ser válida."""
    batch = SYNTHETIC.generate(SCALING, _pure("W0-GROSS-RISK"), 2, 6)
    run = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    assert COMMON.audit_constraints(run.results, batch.snapshot, batch.config).clean
    point = run.results[0].operations[0].result.points[0]  # type: ignore[union-attr]
    assert point.validation is not None and point.validation.is_valid
    object.__setattr__(point, "is_valid_solution", False)
    try:
        audit = COMMON.audit_constraints(run.results, batch.snapshot, batch.config)
    finally:
        object.__setattr__(point, "is_valid_solution", True)
    assert audit.valid_weights_but_rejected == 1 and not audit.clean
    assert audit.to_json()["valid_weights_but_rejected"] == 1
