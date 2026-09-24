"""Validación independiente de soluciones y composiciones (MASTER_SPEC §44, VAL-010)."""

from portfolio_engine.validation.composition_validator import validate_candidate_composition
from portfolio_engine.validation.solution_validator import SolutionValidator, ValidationContext
from portfolio_engine.validation.tolerances import ReturnTarget, ValidationTolerances

__all__ = (
    "ReturnTarget",
    "SolutionValidator",
    "ValidationContext",
    "ValidationTolerances",
    "validate_candidate_composition",
)
