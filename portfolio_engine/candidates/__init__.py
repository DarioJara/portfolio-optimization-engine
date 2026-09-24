"""Generación de composiciones candidatas (MASTER_SPEC §26-31; Bloque 3)."""

from portfolio_engine.candidates.beam_search import BeamSearch, SearchOutcome, select_survivors
from portfolio_engine.candidates.candidate_engine import CandidateContext, CandidateEngine
from portfolio_engine.candidates.composition_hash import composition_hash_of
from portfolio_engine.candidates.diagnostics import RejectionLog, build_asset_records
from portfolio_engine.candidates.eligibility import (
    EligibilityFilter,
    EligibilityResult,
)
from portfolio_engine.candidates.evaluation import (
    CompositionEvaluator,
    EvaluationRejection,
    MemoizedEvaluator,
    ProjectedWeightsEvaluator,
    build_estimate,
    current_portfolio_utility,
    project_box_budget,
    tightened_bounds,
)
from portfolio_engine.candidates.expansion import (
    EvaluationBudget,
    NeighborhoodExpander,
    SearchNode,
    SearchServices,
)
from portfolio_engine.candidates.exploration import ExplorationPolicy, component_counts
from portfolio_engine.candidates.local_search import LocalSearch, LocalSearchOutcome
from portfolio_engine.candidates.prepared import CompositionFactory, PreparedComposition
from portfolio_engine.candidates.screening import (
    CandidateScreening,
    ScreeningResult,
    SignalTable,
    average_rank_percentile,
)
from portfolio_engine.candidates.swap_generator import Neighbor, Shortlist, SwapGenerator
from portfolio_engine.candidates.universe_data import UniverseSnapshot

__all__ = (
    "BeamSearch",
    "CandidateContext",
    "CandidateEngine",
    "CandidateScreening",
    "CompositionEvaluator",
    "CompositionFactory",
    "EligibilityFilter",
    "EligibilityResult",
    "EvaluationBudget",
    "EvaluationRejection",
    "ExplorationPolicy",
    "LocalSearch",
    "LocalSearchOutcome",
    "MemoizedEvaluator",
    "Neighbor",
    "NeighborhoodExpander",
    "PreparedComposition",
    "ProjectedWeightsEvaluator",
    "RejectionLog",
    "ScreeningResult",
    "SearchNode",
    "SearchOutcome",
    "SearchServices",
    "Shortlist",
    "SignalTable",
    "SwapGenerator",
    "UniverseSnapshot",
    "average_rank_percentile",
    "build_asset_records",
    "build_estimate",
    "component_counts",
    "composition_hash_of",
    "current_portfolio_utility",
    "project_box_budget",
    "select_survivors",
    "tightened_bounds",
)
