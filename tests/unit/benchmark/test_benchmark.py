"""BEN-001, BEN-002, BEN-003 (subconjunto B2): temporizadores, estadísticos y benchmark de
reutilización."""

from __future__ import annotations

import time

import numpy as np
import pytest

from portfolio_engine.benchmark import (
    BenchmarkRecorder,
    ReuseMode,
    solver_reuse_benchmark,
    summarize,
)
from portfolio_engine.exceptions import PortfolioEngineError
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from tests.fixtures.problems import base_config, make_problem

pytestmark = pytest.mark.unit


def test_recorder_measures_stages_and_accepts_external_samples() -> None:
    recorder = BenchmarkRecorder()
    with recorder.stage("work"):
        time.sleep(0.01)
    with pytest.raises(RuntimeError), recorder.stage("failing"):
        raise RuntimeError("boom")  # la muestra se registra igualmente
    recorder.record("solve", 0.5)
    samples = recorder.samples()
    assert (
        samples["work"][0] >= 0.01 and len(samples["failing"]) == 1 and samples["solve"] == (0.5,)
    )


def test_summary_statistics_match_a_manual_calculation() -> None:
    """BEN-002: media, percentiles configurados y máximo frente a NumPy sobre datos conocidos."""
    config = base_config().benchmark
    values = [0.5, 1.0, 1.5, 2.0, 10.0]
    summary = summarize(values, config)
    assert summary.count == 5 and summary.mean == pytest.approx(3.0) and summary.maximum == 10.0
    for level in config.percentiles:
        assert summary.percentile(level) == pytest.approx(float(np.percentile(values, level)))
    assert summary.percentile(50.0) == 1.5
    with pytest.raises(PortfolioEngineError, match="no configurado"):
        summary.percentile(12.5)
    with pytest.raises(PortfolioEngineError, match="No hay muestras"):
        summarize([], config)


def test_solver_reuse_benchmark_compares_the_three_modes() -> None:
    """BEN-003: cold setup vs workspace reuse vs warm start, con contadores reales y mismas
    soluciones."""
    config = base_config(benchmark={"repetitions": 2, "warmup_runs": 0})
    n = 8
    rng = np.random.default_rng(3)
    factor = rng.normal(size=(n, n)) * 0.05
    sigma = factor @ factor.T + np.diag(rng.uniform(0.02, 0.05, n))
    problem = make_problem(
        rng.uniform(0.03, 0.12, n),
        sigma,
        [1 / n] * n,
        config,
        universe_overrides={"MaxWeight": [0.4] * n},
    )
    report = solver_reuse_benchmark(
        config, problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    by_mode = {mode.mode: mode for mode in report.modes}
    assert set(by_mode) == set(ReuseMode) and report.repetitions == 2
    cold, reuse, warm = (
        by_mode[m] for m in (ReuseMode.COLD_SETUP, ReuseMode.WORKSPACE_REUSE, ReuseMode.WARM_START)
    )
    assert (
        cold.setup_count > reuse.setup_count == warm.setup_count == 3
    )  # workspace QP compartido + LP y etapa 2 de MaxReturn
    assert cold.warm_start_count == 0 and reuse.warm_start_count == 0 and warm.warm_start_count > 0
    assert cold.solve_count == reuse.solve_count == warm.solve_count
    assert report.max_weight_difference < 1e-6  # los tres modos producen la misma frontera
    for mode in report.modes:
        assert set(mode.timings) == {
            "setup",
            "update",
            "solve",
            "frontier_total",
            "min_variance",
            "max_return",
            "grid",
        }
        assert mode.timings["frontier_total"].count == 2 and mode.iterations > 0
        assert mode.timings["frontier_total"].mean >= mode.timings["solve"].mean
        # M-2: extremos y malla se miden por separado y suman (aprox.) el total de la frontera
        phases = sum(mode.timings[name].mean for name in ("min_variance", "max_return", "grid"))
        assert phases <= mode.timings["frontier_total"].mean * 1.01
        assert mode.timings["grid"].mean > 0.0 and mode.timings["max_return"].mean > 0.0
        assert 0 < mode.endpoint_iterations < mode.iterations
        assert mode.grid_iterations == mode.iterations - mode.endpoint_iterations
    assert (
        cold.timings["setup"].mean > reuse.timings["setup"].mean
    )  # menos setups ⇒ menos tiempo de setup
    assert report.frontier_points == config.frontier.frontier_points
