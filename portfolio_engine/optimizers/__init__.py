"""Backends de optimización, routing y formulaciones (MASTER_SPEC §14-22, §45-47)."""

from portfolio_engine.optimizers.base import (
    BackendCapabilities,
    OptimizationBackend,
    SetupInfo,
    UpdateInfo,
)
from portfolio_engine.optimizers.highs_backend import HiGHSLPBackend
from portfolio_engine.optimizers.osqp_backend import OSQPBackend
from portfolio_engine.optimizers.problem import CanonicalProblem
from portfolio_engine.optimizers.router import SolverRouter, solve_with_policy
from portfolio_engine.optimizers.status import (
    AMBIGUOUS_STATUSES,
    map_highs_status,
    map_osqp_status,
)

__all__ = (
    "AMBIGUOUS_STATUSES",
    "BackendCapabilities",
    "CanonicalProblem",
    "HiGHSLPBackend",
    "OSQPBackend",
    "OptimizationBackend",
    "SetupInfo",
    "SolverRouter",
    "UpdateInfo",
    "map_highs_status",
    "map_osqp_status",
    "solve_with_policy",
)
