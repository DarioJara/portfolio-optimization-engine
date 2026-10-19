"""Escenarios y optimización multiescenario (MASTER_SPEC §53-54; Bloque 4)."""

from portfolio_engine.scenarios.data import ScenarioConstraints, ScenarioData, ScenarioSet
from portfolio_engine.scenarios.multi_scenario import (
    MultiScenarioOptimizer,
    MultiScenarioResult,
    intersect_constraint_configs,
)
from portfolio_engine.scenarios.scenario_engine import ScenarioEngine, scenario_hash

__all__ = (
    "MultiScenarioOptimizer",
    "MultiScenarioResult",
    "ScenarioConstraints",
    "ScenarioData",
    "ScenarioEngine",
    "ScenarioSet",
    "intersect_constraint_configs",
    "scenario_hash",
)
