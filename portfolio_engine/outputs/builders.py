"""Constructores de filas de salida y del dataset de la frontera (MASTER_SPEC §63-67, §82).

* ``frontier_point_rows``: ``EfficientFrontierPoints`` (OUT-003).
* ``weight_rows``: pesos sobre la unión current ∪ nueva composición, con coste, contribución al
  riesgo y al retorno por activo (OUT-002, TC-012, MET-003).
* ``scenario_weight_rows`` / ``frontier_weight_rows``: ``ScenarioWeights`` (estrategias nombradas)
  frente a ``EfficientFrontierWeights`` (todos los puntos) (OUT-007, decisión A-21).
* ``solver_diagnostics_rows``: ``SolverDiagnostics`` (OUT-005).
* ``scenario_header_rows``: ``ScenarioHeader`` de las estrategias nombradas Current, MinVariance y
  MaxReturn (OPT-014, OUT-001 parcial).
* ``frontier_dataset``: tabla ``Volatility``, ``ExpectedReturnGross``, ``ExpectedReturnNet`` que
  permite graficar la frontera de una cartera (FRN-022, Definition of Done del Bloque 2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from portfolio_engine.costs.transaction_cost_model import TransactionCostModel, UnionAlignment
from portfolio_engine.metrics.contributions import marginal_risk_contribution, return_contribution
from portfolio_engine.models.enums import StrategyID
from portfolio_engine.models.frontier import CompositionFrontierResult, FrontierPoint, PointMetrics
from portfolio_engine.outputs.schemas import (
    FrontierPointRow,
    ScenarioHeaderRow,
    SolverDiagnosticsRow,
    WeightRow,
)

DATASET_COLUMNS = (
    "PortfolioID",
    "ScenarioID",
    "FrontierType",
    "FrontierPointID",
    "StrategyID",
    "Volatility",
    "ExpectedReturnGross",
    "ExpectedReturnNet",
    "IsValidSolution",
    "IsGrossEfficient",
    "IsNetEfficient",
    "IsDuplicate",
)


@dataclass(frozen=True, eq=False, slots=True)
class WeightContext:
    """Datos para construir las filas de pesos de una composición.

    Attributes:
        tickers: ``AssetID`` → ``Ticker``.
        mu: retornos esperados de la composición (orden de ``result.asset_ids``).
        sigma: covarianza de la composición.
        alignment: unión current ∪ composición.
        cost_model: modelo de costes (``None`` si no hay costes o cartera actual).
        zero_volatility_tolerance: volatilidad mínima para definir contribuciones al riesgo.
        zero_weight_tolerance: peso mínimo para considerar mantenido un activo.
    """

    tickers: Mapping[str, str]
    mu: npt.NDArray[np.float64]
    sigma: npt.NDArray[np.float64]
    alignment: UnionAlignment
    cost_model: TransactionCostModel | None
    zero_volatility_tolerance: float
    zero_weight_tolerance: float


def frontier_point_rows(result: CompositionFrontierResult) -> tuple[FrontierPointRow, ...]:
    """Una fila de ``EfficientFrontierPoints`` por punto de ``result`` (válido o no)."""
    return tuple(_frontier_row(result, point) for point in result.points)


def _frontier_row(result: CompositionFrontierResult, point: FrontierPoint) -> FrontierPointRow:
    metrics = point.metrics
    return FrontierPointRow(
        portfolio_id=result.portfolio_id,
        scenario_id=result.scenario_id,
        frontier_type=result.frontier_type,
        frontier_point_id=point.point_id,
        composition_id=point.composition_id,
        strategy_id=point.strategy_id.value,
        target_return=point.target_return,
        theta=point.theta,
        expected_return_gross=None if metrics is None else metrics.expected_return_gross,
        expected_return_net=None if metrics is None else metrics.expected_return_net,
        volatility=None if metrics is None else metrics.volatility,
        sharpe_ratio=None if metrics is None else metrics.sharpe_ratio,
        turnover=None if metrics is None else metrics.turnover,
        transaction_cost=None if metrics is None else metrics.transaction_cost,
        transaction_cost_one_off=None if metrics is None else metrics.transaction_cost_one_off,
        is_gross_efficient=point.is_gross_efficient,
        is_net_efficient=point.is_net_efficient,
        is_valid_solution=point.is_valid_solution,
        frontier_scope=result.scope.value,
        cost_treatment=result.cost_treatment.value,
        frontier_method=point.method.value,
        is_duplicate=point.is_duplicate,
        duplicate_of_point_id=point.duplicate_of,
        is_adaptive_insertion=point.is_adaptive_insertion,
        sequence_id=point.sequence,
        optimization_horizon_years=result.optimization_horizon_years,
        availability_reason=None if metrics is None else metrics.unavailable_reason,
    )


def weight_rows(
    result: CompositionFrontierResult,
    points: tuple[FrontierPoint, ...],
    context: WeightContext,
) -> tuple[WeightRow, ...]:
    """Filas de pesos de ``points`` sobre la unión current ∪ composición (OUT-002).

    Los activos liquidados (``IsRemovedAsset``) aparecen con peso optimizado 0 y su coste de venta.
    Sin cartera actual, ``IsNewAsset``, ``IsRemovedAsset`` y el coste por activo son ``None``.
    """
    rows: list[WeightRow] = []
    for point in points:
        if point.weights is not None:
            rows.extend(_point_weight_rows(result, point, point.weights, context))
    return tuple(rows)


def _point_weight_rows(
    result: CompositionFrontierResult,
    point: FrontierPoint,
    weights: npt.NDArray[np.float64],
    context: WeightContext,
) -> list[WeightRow]:
    alignment = context.alignment
    optimized = alignment.expand(weights)
    current = alignment.current_weights
    contribution = marginal_risk_contribution(
        weights, context.sigma, context.zero_volatility_tolerance
    )[0]
    returns = return_contribution(weights, context.mu)[0]
    asset_costs = (
        None
        if context.cost_model is None
        else context.cost_model.asset_costs_one_off(np.atleast_2d(weights))
    )
    position_in_composition = {
        int(position): index for index, position in enumerate(alignment.composition_positions)
    }
    rows: list[WeightRow] = []
    for position, asset_id in enumerate(alignment.asset_ids):
        local = position_in_composition.get(position)
        held_before = bool(current[position] > 0.0)
        held_after = bool(optimized[position] > context.zero_weight_tolerance)
        has_current = alignment.has_current_portfolio
        rows.append(
            WeightRow(
                portfolio_id=result.portfolio_id,
                scenario_id=result.scenario_id,
                strategy_id=point.strategy_id.value,
                frontier_point_id=point.point_id,
                composition_id=point.composition_id,
                asset_id=asset_id,
                ticker=context.tickers.get(asset_id, asset_id),
                current_weight=float(current[position]),
                optimized_weight=float(optimized[position]),
                weight_change=float(optimized[position] - current[position]),
                is_new_asset=(not held_before and held_after) if has_current else None,
                is_removed_asset=(held_before and not held_after) if has_current else None,
                transaction_cost_asset=(
                    None if asset_costs is None else float(asset_costs[0, position])
                ),
                marginal_risk_contribution=(
                    None
                    if local is None or np.isnan(contribution[local])
                    else float(contribution[local])
                ),
                expected_return_contribution=0.0 if local is None else float(returns[local]),
            )
        )
    return rows


def scenario_weight_rows(
    result: CompositionFrontierResult, context: WeightContext
) -> tuple[WeightRow, ...]:
    """``ScenarioWeights``: pesos de las estrategias nombradas (MinVariance y MaxReturn)."""
    named = tuple(
        point
        for point in result.points
        if point.strategy_id in (StrategyID.MIN_VARIANCE, StrategyID.MAX_RETURN)
    )
    return weight_rows(result, named, context)


def frontier_weight_rows(
    result: CompositionFrontierResult, context: WeightContext
) -> tuple[WeightRow, ...]:
    """``EfficientFrontierWeights``: pesos de todos los puntos de la frontera, por punto."""
    return weight_rows(result, result.points, context)


def solver_diagnostics_rows(
    result: CompositionFrontierResult,
) -> tuple[SolverDiagnosticsRow, ...]:
    """Una fila de ``SolverDiagnostics`` por punto (pre-chequeo: solver ``NONE``)."""
    rows: list[SolverDiagnosticsRow] = []
    for point in result.points:
        solve = point.solve
        rows.append(
            SolverDiagnosticsRow(
                portfolio_id=result.portfolio_id,
                scenario_id=result.scenario_id,
                composition_id=point.composition_id,
                frontier_point_id=point.point_id,
                solver_name="NONE" if solve is None else solve.solver_name,
                solver_version="NONE" if solve is None else solve.solver_version,
                solver_status=point.status.value,
                status_source=point.status_source.value,
                native_status=None if solve is None else solve.native_status,
                problem_class=None if solve is None else solve.problem_class.value,
                iterations=None if solve is None else solve.iterations,
                setup_time=None if solve is None else solve.setup_time,
                update_time=None if solve is None else solve.update_time,
                solve_time=None if solve is None else solve.solve_time,
                objective_value=point.objective_value,
                primal_residual=None if solve is None else solve.primal_residual,
                dual_residual=None if solve is None else solve.dual_residual,
                maximum_constraint_violation=(
                    None if point.validation is None else point.validation.max_violation
                ),
                warm_start_used=None if solve is None else solve.warm_start_used,
                cold_retries=None if solve is None else solve.cold_retries,
            )
        )
    return tuple(rows)


def scenario_header_rows(result: CompositionFrontierResult) -> tuple[ScenarioHeaderRow, ...]:
    """``ScenarioHeader`` de Current (si hay cartera actual), MinVariance y MaxReturn (OPT-014)."""
    rows: list[ScenarioHeaderRow] = []
    if result.current_metrics is not None:
        rows.append(
            _header(result, StrategyID.CURRENT, result.composition_id, result.current_metrics)
        )
    for point in result.points:
        if point.strategy_id in (StrategyID.MIN_VARIANCE, StrategyID.MAX_RETURN):
            rows.append(
                _header(result, point.strategy_id, point.composition_id, point.metrics, point)
            )
    return tuple(rows)


def _header(
    result: CompositionFrontierResult,
    strategy: StrategyID,
    composition_id: str,
    metrics: PointMetrics | None,
    point: FrontierPoint | None = None,
) -> ScenarioHeaderRow:
    solve = None if point is None else point.solve
    return ScenarioHeaderRow(
        portfolio_id=result.portfolio_id,
        scenario_id=result.scenario_id,
        strategy_id=strategy.value,
        composition_id=composition_id,
        expected_return_gross=None if metrics is None else metrics.expected_return_gross,
        expected_return_net=None if metrics is None else metrics.expected_return_net,
        volatility=None if metrics is None else metrics.volatility,
        sharpe_ratio=None if metrics is None else metrics.sharpe_ratio,
        turnover=None if metrics is None else metrics.turnover,
        transaction_cost=None if metrics is None else metrics.transaction_cost,
        transaction_cost_one_off=None if metrics is None else metrics.transaction_cost_one_off,
        herfindahl_index=None if metrics is None else metrics.herfindahl_index,
        number_assets=None if metrics is None else metrics.number_assets,
        number_new_assets=None if metrics is None else metrics.number_new_assets,
        number_removed_assets=None if metrics is None else metrics.number_removed_assets,
        objective_value=None if point is None else point.objective_value,
        is_gross_efficient=None if point is None else point.is_gross_efficient,
        is_net_efficient=None if point is None else point.is_net_efficient,
        is_valid_solution=True if point is None else point.is_valid_solution,
        solver_status="NOT_APPLICABLE" if point is None else point.status.value,
        solver_name="NONE" if solve is None else solve.solver_name,
        solver_iterations=None if solve is None else solve.iterations,
        solver_time=None if solve is None else solve.solve_time,
        total_optimization_time=None if point is None else result.diagnostics.frontier_time,
        optimization_horizon_years=result.optimization_horizon_years,
        availability_reason=None if metrics is None else metrics.unavailable_reason,
    )


def frontier_dataset(result: CompositionFrontierResult) -> pd.DataFrame:
    """Tabla graficable ``Volatility`` / ``ExpectedReturnGross`` / ``ExpectedReturnNet`` (FRN-022).

    Incluye todos los puntos (también inválidos y duplicados, con sus flags); las métricas no
    disponibles son ``NaN`` (``ExpectedReturnNet`` sin cartera actual o sin costes).
    """
    records = [
        {
            "PortfolioID": result.portfolio_id,
            "ScenarioID": result.scenario_id,
            "FrontierType": result.frontier_type,
            "FrontierPointID": point.point_id,
            "StrategyID": point.strategy_id.value,
            "Volatility": np.nan if point.metrics is None else point.metrics.volatility,
            "ExpectedReturnGross": (
                np.nan if point.metrics is None else point.metrics.expected_return_gross
            ),
            "ExpectedReturnNet": (
                np.nan
                if point.metrics is None or point.metrics.expected_return_net is None
                else point.metrics.expected_return_net
            ),
            "IsValidSolution": point.is_valid_solution,
            "IsGrossEfficient": point.is_gross_efficient,
            "IsNetEfficient": point.is_net_efficient,
            "IsDuplicate": point.is_duplicate,
        }
        for point in result.points
    ]
    return pd.DataFrame.from_records(records, columns=list(DATASET_COLUMNS))
