"""Formulaciones matemáticas de los problemas de optimización (MASTER_SPEC §15-22, §35-38)."""

from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)

__all__ = ("BuiltProblem", "CompositionInputs", "build_fixed_composition_problem")
