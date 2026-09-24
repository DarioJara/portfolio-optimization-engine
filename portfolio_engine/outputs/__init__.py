"""Esquemas y constructores de salida (MASTER_SPEC §63-67, §82)."""

from portfolio_engine.outputs.builders import (
    DATASET_COLUMNS,
    WeightContext,
    frontier_dataset,
    frontier_point_rows,
    frontier_weight_rows,
    scenario_header_rows,
    scenario_weight_rows,
    solver_diagnostics_rows,
    weight_rows,
)
from portfolio_engine.outputs.schemas import (
    FrontierPointRow,
    ScenarioHeaderRow,
    SolverDiagnosticsRow,
    WeightRow,
)

__all__ = (
    "DATASET_COLUMNS",
    "FrontierPointRow",
    "ScenarioHeaderRow",
    "SolverDiagnosticsRow",
    "WeightContext",
    "WeightRow",
    "frontier_dataset",
    "frontier_point_rows",
    "frontier_weight_rows",
    "scenario_header_rows",
    "scenario_weight_rows",
    "solver_diagnostics_rows",
    "weight_rows",
)
