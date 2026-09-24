"""BEN-001, BEN-002, BEN-006 (evidencia B3): benchmark descriptivo del pipeline de candidatos."""

from __future__ import annotations

import dataclasses

import pytest

from portfolio_engine.benchmark import CANDIDATE_STAGES, candidate_pipeline_benchmark
from portfolio_engine.frontiers import GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from tests.fixtures.candidates import two_region_problem
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def _config():  # type: ignore[no-untyped-def]
    config = base_config()
    return dataclasses.replace(
        config, benchmark=dataclasses.replace(config.benchmark, repetitions=2, warmup_runs=0)
    )


def test_the_benchmark_reports_real_stages_and_counts_consistent_with_the_engine() -> None:
    config = _config()
    problem = two_region_problem(config)
    report = candidate_pipeline_benchmark(
        config, problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    direct = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert set(report.timings) == set(CANDIDATE_STAGES)
    assert report.repetitions == 2 and all(s.count == 2 for s in report.timings.values())
    # los contadores proceden de una ejecución real (el motor es determinista)
    assert report.n_compositions == len(direct.candidates) > 1
    assert report.n_evaluated == direct.candidate_diagnostics.total_evaluated
    assert report.n_generated == direct.candidate_diagnostics.total_generated
    assert report.n_frontier_points == len(direct.points)
    assert report.n_envelope_points == len(direct.envelope)
    assert report.n_envelope_compositions == len(direct.envelope_composition_ids) > 1
    assert report.n_universe_assets == 6


def test_stage_times_are_positive_and_nested() -> None:
    config = _config()
    report = candidate_pipeline_benchmark(
        config, two_region_problem(config), CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    timings = report.timings
    assert all(summary.mean > 0 for summary in timings.values())
    assert (
        timings["screening"].mean <= timings["candidate_generation"].mean
    )  # el screening es parte
    parts = (
        timings["candidate_generation"].mean
        + timings["frontier_evaluation"].mean
        + timings["pareto"].mean
    )
    assert timings["total"].mean == pytest.approx(parts, rel=0.05)
    assert timings["total"].maximum >= timings["total"].mean
    assert {level for level, _ in timings["total"].percentiles} == set(config.benchmark.percentiles)
