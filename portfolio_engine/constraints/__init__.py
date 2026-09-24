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
    minimum_forced_turnover,
)

__all__ = (
    "CompiledConstraints",
    "ConstraintCompiler",
    "ConstraintSet",
    "ExitedPosition",
    "FeasibilityCause",
    "FeasibilityReport",
    "PreFeasibilityChecker",
    "RestrictedPositionRule",
    "build_constraint_set",
    "minimum_forced_turnover",
)
