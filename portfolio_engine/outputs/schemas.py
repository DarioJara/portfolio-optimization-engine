"""Esquemas de salida de un bloque de fronteras (MASTER_SPEC §63-67; OUT-001..003, 005, 006).

Cada campo no disponible es ``None`` y la fila lleva su ``availability_reason``: las métricas que
dependen de la cartera actual o de los costes nunca se inventan (§24). Se publican en base
anualizada; ``transaction_cost_one_off`` permite pasar a base horizonte (enmienda E-03).
``BatchRunID`` y ``CVaR`` pertenecen a los Bloques 6 y 4 respectivamente y no se incluyen todavía.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrontierPointRow:
    """Fila de ``EfficientFrontierPoints`` (MASTER_SPEC §65)."""

    portfolio_id: str
    scenario_id: str
    frontier_type: str
    frontier_point_id: str
    composition_id: str
    strategy_id: str
    target_return: float | None
    theta: float | None
    expected_return_gross: float | None
    expected_return_net: float | None
    volatility: float | None
    sharpe_ratio: float | None
    turnover: float | None
    transaction_cost: float | None
    transaction_cost_one_off: float | None
    is_gross_efficient: bool | None
    is_net_efficient: bool | None
    is_valid_solution: bool
    frontier_scope: str
    cost_treatment: str
    frontier_method: str
    is_duplicate: bool
    duplicate_of_point_id: str | None
    is_adaptive_insertion: bool
    sequence_id: int
    optimization_horizon_years: float
    availability_reason: str | None


@dataclass(frozen=True, slots=True)
class WeightRow:
    """Fila de pesos sobre la unión current ∪ nueva composición (MASTER_SPEC §64)."""

    portfolio_id: str
    scenario_id: str
    strategy_id: str
    frontier_point_id: str
    composition_id: str
    asset_id: str
    ticker: str
    current_weight: float
    optimized_weight: float
    weight_change: float
    is_new_asset: bool | None
    is_removed_asset: bool | None
    transaction_cost_asset: float | None
    marginal_risk_contribution: float | None
    expected_return_contribution: float


@dataclass(frozen=True, slots=True)
class SolverDiagnosticsRow:
    """Fila de ``SolverDiagnostics`` (MASTER_SPEC §67)."""

    portfolio_id: str
    scenario_id: str
    composition_id: str
    frontier_point_id: str
    solver_name: str
    solver_version: str
    solver_status: str
    status_source: str
    native_status: str | None
    problem_class: str | None
    iterations: int | None
    setup_time: float | None
    update_time: float | None
    solve_time: float | None
    objective_value: float | None
    primal_residual: float | None
    dual_residual: float | None
    maximum_constraint_violation: float | None
    warm_start_used: bool | None
    cold_retries: int | None


@dataclass(frozen=True, slots=True)
class ScenarioHeaderRow:
    """Fila de ``ScenarioHeader`` de una estrategia nombrada (MASTER_SPEC §63; subconjunto B2)."""

    portfolio_id: str
    scenario_id: str
    strategy_id: str
    composition_id: str
    expected_return_gross: float | None
    expected_return_net: float | None
    volatility: float | None
    sharpe_ratio: float | None
    turnover: float | None
    transaction_cost: float | None
    transaction_cost_one_off: float | None
    herfindahl_index: float | None
    number_assets: int | None
    number_new_assets: int | None
    number_removed_assets: int | None
    objective_value: float | None
    is_gross_efficient: bool | None
    is_net_efficient: bool | None
    is_valid_solution: bool
    solver_status: str
    solver_name: str
    solver_iterations: int | None
    solver_time: float | None
    total_optimization_time: float | None
    optimization_horizon_years: float
    availability_reason: str | None
