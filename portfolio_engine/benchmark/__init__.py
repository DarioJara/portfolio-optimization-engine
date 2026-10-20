"""Benchmarks de rendimiento (MASTER_SPEC §71): temporizadores, estadísticos, reutilización,
pipeline de candidatos, detección de deterioros (BEN-005) y aritmética de escalado (BEN-004/007)."""

from portfolio_engine.benchmark.candidate_suite import (
    CANDIDATE_STAGES,
    CandidatePipelineReport,
    candidate_pipeline_benchmark,
)
from portfolio_engine.benchmark.regression import (
    BaselineCell,
    RegressionComparison,
    RegressionVerdict,
    compare_to_baseline,
)
from portfolio_engine.benchmark.scaling import (
    CapacityProjection,
    ProjectionInputs,
    project_capacity,
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
    "BaselineCell",
    "BenchmarkRecorder",
    "CandidatePipelineReport",
    "CapacityProjection",
    "ModeReport",
    "ProjectionInputs",
    "RegressionComparison",
    "RegressionVerdict",
    "ReuseMode",
    "SolverReuseReport",
    "TimingSummary",
    "candidate_pipeline_benchmark",
    "compare_to_baseline",
    "project_capacity",
    "solver_reuse_benchmark",
    "summarize",
)
