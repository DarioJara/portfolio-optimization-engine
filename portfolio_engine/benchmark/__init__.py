"""Benchmarks de rendimiento (MASTER_SPEC §71): temporizadores, estadísticos, reutilización
y pipeline de candidatos."""

from portfolio_engine.benchmark.candidate_suite import (
    CANDIDATE_STAGES,
    CandidatePipelineReport,
    candidate_pipeline_benchmark,
)
from portfolio_engine.benchmark.stats import TimingSummary, summarize
from portfolio_engine.benchmark.suite import (
    ModeReport,
    ReuseMode,
    SolverReuseReport,
    solver_reuse_benchmark,
)
from portfolio_engine.benchmark.timers import BenchmarkRecorder

__all__ = (
    "CANDIDATE_STAGES",
    "BenchmarkRecorder",
    "CandidatePipelineReport",
    "ModeReport",
    "ReuseMode",
    "SolverReuseReport",
    "TimingSummary",
    "candidate_pipeline_benchmark",
    "solver_reuse_benchmark",
    "summarize",
)
