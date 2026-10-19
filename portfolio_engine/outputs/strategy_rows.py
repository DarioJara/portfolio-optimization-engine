"""Filas de salida de las estrategias nombradas del Bloque 4 (MASTER_SPEC §63-64; OUT-001, SCN-008).

Todas las filas llevan ``ScenarioID`` y ``StrategyID``: una misma cartera produce filas distintas
por escenario. Las magnitudes no disponibles son ``None`` con su motivo (nunca se inventan); el
``CVaR`` es ``None`` si la estrategia no lo calculó (§63, MET-004). ``BatchRunID`` es del Bloque 6.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from portfolio_engine.models.enums import SolverStatus
from portfolio_engine.models.strategy import StrategyResult


@dataclass(frozen=True, slots=True)
class StrategyHeaderRow:
    """Fila de ``ScenarioHeader`` de una estrategia del Bloque 4 (con ``CVaR`` y ``Sharpe``)."""

    portfolio_id: str
    scenario_id: str
    strategy_id: str
    composition_id: str
    cost_treatment: str
    expected_return_gross: float | None
    expected_return_net: float | None
    volatility: float | None
    sharpe_ratio: float | None
    cvar: float | None
    turnover: float | None
    transaction_cost: float | None
    transaction_cost_one_off: float | None
    herfindahl_index: float | None
    number_assets: int | None
    number_new_assets: int | None
    number_removed_assets: int | None
    objective_value: float | None
    is_valid_solution: bool
    solver_status: str
    status_source: str
    solver_names: str
    solver_iterations: int | None
    solver_time: float | None
    optimality_claim: str
    outcome: str | None
    availability_reason: str | None


@dataclass(frozen=True, slots=True)
class StrategyWeightRow:
    """Fila de pesos de una estrategia (composición optimizada)."""

    portfolio_id: str
    scenario_id: str
    strategy_id: str
    composition_id: str
    asset_id: str
    ticker: str
    optimized_weight: float


@dataclass(frozen=True, slots=True)
class ScenarioMetricRow:
    """Métricas de una solución única evaluada bajo un escenario (``ScenarioID`` del escenario)."""

    portfolio_id: str
    solution_scenario_id: str
    strategy_id: str
    scenario_id: str
    expected_return_gross: float
    expected_return_net: float | None
    volatility: float
    sharpe_ratio: float | None
    utility: float | None


def strategy_header_row(result: StrategyResult) -> StrategyHeaderRow:
    """Fila de cabecera de ``result``; sin solución, las métricas son ``None`` con su motivo."""
    metrics = result.metrics
    solve = result.solve
    reason: str | None = None
    if metrics is None:
        reason = result.outcome or f"NO_SOLUTION_{result.status.value}"
    elif metrics.unavailable_reason is not None:
        reason = metrics.unavailable_reason
    return StrategyHeaderRow(
        portfolio_id=result.portfolio_id,
        scenario_id=result.scenario_id,
        strategy_id=result.strategy_id.value,
        composition_id=result.composition_id,
        cost_treatment=result.cost_treatment.value,
        expected_return_gross=None if metrics is None else metrics.expected_return_gross,
        expected_return_net=None if metrics is None else metrics.expected_return_net,
        volatility=None if metrics is None else metrics.volatility,
        sharpe_ratio=None if metrics is None else metrics.sharpe_ratio,
        cvar=result.extra("cvar_horizon"),
        turnover=None if metrics is None else metrics.turnover,
        transaction_cost=None if metrics is None else metrics.transaction_cost,
        transaction_cost_one_off=None if metrics is None else metrics.transaction_cost_one_off,
        herfindahl_index=None if metrics is None else metrics.herfindahl_index,
        number_assets=None if metrics is None else metrics.number_assets,
        number_new_assets=None if metrics is None else metrics.number_new_assets,
        number_removed_assets=None if metrics is None else metrics.number_removed_assets,
        objective_value=result.objective_value,
        is_valid_solution=result.is_valid_solution,
        solver_status=result.status.value,
        status_source=result.status_source.value,
        solver_names="+".join(result.solver_names),
        solver_iterations=None if solve is None else solve.iterations,
        solver_time=None if solve is None else solve.solve_time,
        optimality_claim=result.optimality_claim.value,
        outcome=result.outcome,
        availability_reason=reason,
    )


def strategy_header_rows(results: Sequence[StrategyResult]) -> tuple[StrategyHeaderRow, ...]:
    """Una fila de cabecera por estrategia, en el orden recibido."""
    return tuple(strategy_header_row(result) for result in results)


def strategy_weight_rows(
    result: StrategyResult, tickers: Mapping[str, str]
) -> tuple[StrategyWeightRow, ...]:
    """Pesos de la composición de ``result`` (vacío si la estrategia no tiene solución)."""
    if result.weights is None or result.status not in (
        SolverStatus.OPTIMAL,
        SolverStatus.OPTIMAL_INACCURATE,
    ):
        return ()
    return tuple(
        StrategyWeightRow(
            result.portfolio_id,
            result.scenario_id,
            result.strategy_id.value,
            result.composition_id,
            asset_id,
            tickers.get(asset_id, asset_id),
            float(weight),
        )
        for asset_id, weight in zip(result.asset_ids, result.weights.tolist(), strict=True)
    )


def scenario_metric_rows(result: StrategyResult) -> tuple[ScenarioMetricRow, ...]:
    """Métricas de la solución única bajo cada escenario (una fila por ``ScenarioID``)."""
    return tuple(
        ScenarioMetricRow(
            result.portfolio_id,
            result.scenario_id,
            result.strategy_id.value,
            item.scenario_id,
            item.metrics.expected_return_gross,
            item.metrics.expected_return_net,
            item.metrics.volatility,
            item.metrics.sharpe_ratio,
            item.utility,
        )
        for item in result.scenario_metrics
    )
