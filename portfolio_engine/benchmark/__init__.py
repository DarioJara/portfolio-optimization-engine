"""Benchmarks de rendimiento (MASTER_SPEC §71): temporizadores, estadísticos y reutilización."""

from portfolio_engine.benchmark.stats import TimingSummary, summarize
from portfolio_engine.benchmark.suite import (
    ModeReport,
    ReuseMode,
    SolverReuseReport,
    solver_reuse_benchmark,
)
from portfolio_engine.benchmark.timers import BenchmarkRecorder

__all__ = (
    "BenchmarkRecorder",
    "ModeReport",
    "ReuseMode",
    "SolverReuseReport",
    "TimingSummary",
    "solver_reuse_benchmark",
    "summarize",
)
