"""Esquemas y constructores de salida (MASTER_SPEC §26, §33, §63-67, §82)."""

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
from portfolio_engine.outputs.candidate_builders import (
    LAYER_CONTINUOUS,
    LAYER_CURRENT,
    LAYER_GLOBAL,
    VISUALIZATION_COLUMNS,
    candidate_composition_rows,
    candidate_diagnostics_rows,
    global_frontier_point_rows,
    visualization_dataset,
)
from portfolio_engine.outputs.candidate_schemas import (
    CandidateCompositionRow,
    CandidateDiagnosticsRow,
    GlobalFrontierPointRow,
)
from portfolio_engine.outputs.schemas import (
    FrontierPointRow,
    ScenarioHeaderRow,
    SolverDiagnosticsRow,
    WeightRow,
)

__all__ = (
    "DATASET_COLUMNS",
    "LAYER_CONTINUOUS",
    "LAYER_CURRENT",
    "LAYER_GLOBAL",
    "VISUALIZATION_COLUMNS",
    "CandidateCompositionRow",
    "CandidateDiagnosticsRow",
    "FrontierPointRow",
    "GlobalFrontierPointRow",
    "ScenarioHeaderRow",
    "SolverDiagnosticsRow",
    "WeightContext",
    "WeightRow",
    "candidate_composition_rows",
    "candidate_diagnostics_rows",
    "frontier_dataset",
    "frontier_point_rows",
    "frontier_weight_rows",
    "global_frontier_point_rows",
    "scenario_header_rows",
    "scenario_weight_rows",
    "solver_diagnostics_rows",
    "visualization_dataset",
    "weight_rows",
)
