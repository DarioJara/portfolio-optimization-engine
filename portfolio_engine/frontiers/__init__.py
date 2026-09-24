"""Fronteras eficientes: continua (composición fija) y global con sustitución (§32-43)."""

from portfolio_engine.frontiers.adaptive import AdaptiveFrontier, ParametrizedPoint
from portfolio_engine.frontiers.candidate_evaluator import QPCompositionEvaluator
from portfolio_engine.frontiers.continuous_frontier import (
    ContinuousFrontierEngine,
    FrontierProblem,
    post_cost_evaluation,
)
from portfolio_engine.frontiers.dedup import deduplicate, is_equivalent
from portfolio_engine.frontiers.explicit_portfolios import (
    solve_maximum_return,
    solve_minimum_variance,
)
from portfolio_engine.frontiers.global_frontier import (
    GlobalCandidateFrontierEngine,
    global_pareto,
    relabel_scope,
)
from portfolio_engine.frontiers.pareto import apply_efficiency, pareto_mask
from portfolio_engine.frontiers.risk_aversion_grid import RiskAversionGrid
from portfolio_engine.frontiers.session import FrontierContext, FrontierSession
from portfolio_engine.frontiers.target_return_grid import (
    TargetReturnGrid,
    interior_targets,
    target_range,
)
from portfolio_engine.frontiers.theta_calibration import (
    ThetaGrid,
    calibrate_theta_from_points,
    calibrate_theta_grid,
    grid_values,
    midpoint,
)

__all__ = (
    "AdaptiveFrontier",
    "ContinuousFrontierEngine",
    "FrontierContext",
    "FrontierProblem",
    "FrontierSession",
    "GlobalCandidateFrontierEngine",
    "ParametrizedPoint",
    "QPCompositionEvaluator",
    "RiskAversionGrid",
    "TargetReturnGrid",
    "ThetaGrid",
    "apply_efficiency",
    "calibrate_theta_from_points",
    "calibrate_theta_grid",
    "deduplicate",
    "global_pareto",
    "grid_values",
    "interior_targets",
    "is_equivalent",
    "midpoint",
    "pareto_mask",
    "post_cost_evaluation",
    "relabel_scope",
    "solve_maximum_return",
    "solve_minimum_variance",
    "target_range",
)
