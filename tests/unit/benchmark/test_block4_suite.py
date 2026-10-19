"""BEN-001, BEN-002: el benchmark del Bloque 4 mide etapas reales (sin umbrales)."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.benchmark.block4_suite import block4_benchmark
from portfolio_engine.models.cvar import build_return_scenario_set
from portfolio_engine.models.enums import CostTreatment, CVaRSource, ScenarioWeighting
from tests.fixtures.block4 import scenario_definitions
from tests.fixtures.candidates import random_problem
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def test_the_block_4_benchmark_reports_every_stage_of_every_formulation() -> None:
    config = base_config(benchmark={"repetitions": 2, "warmup_runs": 0})
    problem = random_problem(6, [0, 1, 2], 5, config, max_weight=0.6)
    model = problem.risk_model
    returns = np.random.default_rng(1).multivariate_normal(
        model.mu / 252, model.sigma / 252, size=400
    )
    scenarios = build_return_scenario_set(
        model.asset_ids,
        returns,
        CVaRSource.SIMULATED,
        ScenarioWeighting.EQUAL,
        None,
        config.scenarios.probability_sum_tolerance,
    )
    report = block4_benchmark(
        config,
        problem,
        CostTreatment.NET,
        scenario_definitions(),
        scenarios,
        risk_aversion=4.0,
        volatility_limit=0.3,
    )
    names = [item.name for item in report.formulations]
    assert names == [
        "MAX_SHARPE",
        "VOL_TARGET",
        "MIN_CVAR",
        "SCENARIO_BUILD",
        "EXPECTED_SCENARIO_UTILITY",
        "WORST_CASE",
        "BASE_WITH_STRESS",
        "SCENARIO_INDEPENDENT_FRONTIERS",
    ]
    sharpe = report.formulations[0]
    assert {"prepare", "formulation_build", "solver_solve", "validation", "total"} <= set(
        sharpe.timings
    )
    assert sharpe.timings["total"].count == 2 and sharpe.solver_names == ("CLARABEL",)
    assert sharpe.timings["total"].mean >= sharpe.timings["solver_solve"].mean >= 0.0
    assert report.n_scenarios == 3 and report.repetitions == 2
