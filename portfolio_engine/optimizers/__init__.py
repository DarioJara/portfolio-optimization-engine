"""Backends de optimización, routing y formulaciones (MASTER_SPEC §14-22, §45-47)."""

from portfolio_engine.optimizers.base import (
    BackendCapabilities,
    OptimizationBackend,
    SetupInfo,
    UpdateInfo,
)
from portfolio_engine.optimizers.clarabel_backend import ClarabelBackend
from portfolio_engine.optimizers.feasibility_oracle import FeasibilityVerdict, lp_feasibility
from portfolio_engine.optimizers.highs_backend import HiGHSLPBackend
from portfolio_engine.optimizers.mixed_integer_backend import (
    BackendAvailability,
    MixedIntegerBackend,
    mixed_integer_availability,
)
from portfolio_engine.optimizers.nonconvex_backend import (
    NonConvexAlgorithm,
    NonConvexBackend,
    NonConvexOutcome,
)
from portfolio_engine.optimizers.osqp_backend import OSQPBackend
from portfolio_engine.optimizers.problem import (
    CanonicalProblem,
    ConicProblem,
    MixedIntegerProblem,
    NonConvexProblem,
    SecondOrderCone,
)
from portfolio_engine.optimizers.router import (
    CrossCheckReport,
    SolverRouter,
    cross_check_with_second_solver,
    solve_with_policy,
)
from portfolio_engine.optimizers.scip_backend import SCIP_AVAILABLE, SCIPBackend
from portfolio_engine.optimizers.status import (
    AMBIGUOUS_STATUSES,
    map_clarabel_status,
    map_highs_status,
    map_osqp_status,
    map_scip_status,
)

__all__ = (
    "AMBIGUOUS_STATUSES",
    "SCIP_AVAILABLE",
    "BackendAvailability",
    "BackendCapabilities",
    "CanonicalProblem",
    "ClarabelBackend",
    "ConicProblem",
    "CrossCheckReport",
    "FeasibilityVerdict",
    "HiGHSLPBackend",
    "MixedIntegerBackend",
    "MixedIntegerProblem",
    "NonConvexAlgorithm",
    "NonConvexBackend",
    "NonConvexOutcome",
    "NonConvexProblem",
    "OSQPBackend",
    "OptimizationBackend",
    "SCIPBackend",
    "SecondOrderCone",
    "SetupInfo",
    "SolverRouter",
    "UpdateInfo",
    "cross_check_with_second_solver",
    "lp_feasibility",
    "map_clarabel_status",
    "map_highs_status",
    "map_osqp_status",
    "map_scip_status",
    "mixed_integer_availability",
    "solve_with_policy",
)
