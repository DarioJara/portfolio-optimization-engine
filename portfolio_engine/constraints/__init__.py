"""Restricciones: representación declarativa, compilación y factibilidad (MASTER_SPEC §12-13)."""

from portfolio_engine.constraints.compiler import (
    CompiledConstraints,
    ConstraintCompiler,
    ExitedPosition,
    RestrictedPositionRule,
)
from portfolio_engine.constraints.constraint_set import ConstraintSet, build_constraint_set
from portfolio_engine.constraints.feasibility import (
    FeasibilityCause,
    FeasibilityReport,
    PreFeasibilityChecker,
    check_cardinality,
    minimum_forced_turnover,
)
from portfolio_engine.constraints.integer import (
    CompositionLimits,
    limit_violations,
    move_violations,
    new_assets,
    removed_assets,
    swap_count,
)

__all__ = (
    "CompiledConstraints",
    "CompositionLimits",
    "ConstraintCompiler",
    "ConstraintSet",
    "ExitedPosition",
    "FeasibilityCause",
    "FeasibilityReport",
    "PreFeasibilityChecker",
    "RestrictedPositionRule",
    "build_constraint_set",
    "check_cardinality",
    "limit_violations",
    "minimum_forced_turnover",
    "move_violations",
    "new_assets",
    "removed_assets",
    "swap_count",
)
