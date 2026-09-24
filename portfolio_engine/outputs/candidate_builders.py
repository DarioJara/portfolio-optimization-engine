"""Constructores de salida del Bloque 3 y dataset de visualización (§26, §33, §66, §82).

* ``candidate_composition_rows``: tabla ``CandidateCompositions`` (OUT-009).
* ``candidate_diagnostics_rows``: ``CandidateDiagnostics`` por activo (OUT-004).
* ``global_frontier_point_rows``: puntos de la unión global con su ``CompositionID`` y eficiencia.
* ``visualization_dataset``: las tres capas graficables —cartera actual, frontera continua y
  frontera global de candidatos— sin recalcular nada (VIS-002, Definition of Done del Bloque 3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from portfolio_engine.models.composition import CandidateComposition, CandidateDiagnostics
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.models.frontier import GlobalFrontierResult, PointMetrics
from portfolio_engine.outputs.candidate_schemas import (
    CandidateCompositionRow,
    CandidateDiagnosticsRow,
    GlobalFrontierPointRow,
)
from portfolio_engine.utils.hashing import canonical_json

#: Capas del dataset de visualización.
LAYER_CURRENT = "CURRENT_PORTFOLIO"
LAYER_CONTINUOUS = "CONTINUOUS_FRONTIER"
LAYER_GLOBAL = "GLOBAL_CANDIDATE_FRONTIER"

VISUALIZATION_COLUMNS = (
    "PortfolioID",
    "ScenarioID",
    "Layer",
    "FrontierType",
    "FrontierPointID",
    "CompositionID",
    "StrategyID",
    "Volatility",
    "ExpectedReturnGross",
    "ExpectedReturnNet",
    "IsValidSolution",
    "IsEfficient",
    "IsDuplicate",
)


def candidate_composition_rows(
    portfolio_id: str, scenario_id: str, candidates: Sequence[CandidateComposition]
) -> tuple[CandidateCompositionRow, ...]:
    """Una fila de ``CandidateCompositions`` por composición candidata (OUT-009)."""
    return tuple(_composition_row(portfolio_id, scenario_id, candidate) for candidate in candidates)


def _composition_row(
    portfolio_id: str, scenario_id: str, candidate: CandidateComposition
) -> CandidateCompositionRow:
    history = canonical_json(
        [
            {
                "kind": move.kind,
                "out": list(move.out_asset_ids),
                "in": list(move.in_asset_ids),
                "level": move.level,
                "risk_aversion": move.risk_aversion,
                "screening_prior": move.screening_prior,
            }
            for move in candidate.swap_history
        ]
    )
    return CandidateCompositionRow(
        portfolio_id=portfolio_id,
        scenario_id=scenario_id,
        composition_id=candidate.composition_id,
        composition_hash=candidate.composition_hash,
        assets=candidate.asset_ids,
        parent_composition_id=candidate.parent_composition_id,
        swap_history=history,
        number_of_moves=len(candidate.swap_history),
        candidate_score=candidate.candidate_score,
        estimated_utility_gain=candidate.estimated_utility_gain,
        estimated_turnover=candidate.estimated_turnover,
        estimated_transaction_cost=candidate.estimated_transaction_cost,
        candidate_type=candidate.candidate_type.value,
        origin=candidate.origin.value,
        is_reference=candidate.is_reference,
        best_risk_aversion=candidate.best_risk_aversion,
        estimate_basis=candidate.estimates[0].basis.value if candidate.estimates else None,
        estimate_unavailable_reason=candidate.estimate_unavailable_reason,
    )


def candidate_diagnostics_rows(
    diagnostics: CandidateDiagnostics, tickers: Mapping[str, str]
) -> tuple[CandidateDiagnosticsRow, ...]:
    """Una fila de ``CandidateDiagnostics`` por activo del screening (OUT-004).

    ``tickers`` traduce ``AssetID`` a ``Ticker`` (un activo sin ticker conserva su ``AssetID``).
    """
    return tuple(
        CandidateDiagnosticsRow(
            portfolio_id=diagnostics.portfolio_id,
            scenario_id=diagnostics.scenario_id,
            asset_id=record.asset_id,
            ticker=tickers.get(record.asset_id, record.asset_id),
            candidate_type=None if record.candidate_type is None else record.candidate_type.value,
            candidate_score=record.candidate_score,
            alpha_score=record.alpha_score,
            diversification_score=record.diversification_score,
            marginal_utility=record.marginal_utility,
            liquidity_score=record.liquidity_score,
            transaction_cost_estimate=record.transaction_cost_estimate,
            selected_for_optimization=record.selected_for_optimization,
            rejection_reason=record.rejection_reason,
            eligibility_status=record.status.value,
            eligibility_reasons=record.eligibility_reasons,
            missing_signals=record.missing_signals,
        )
        for record in diagnostics.asset_records
    )


def global_frontier_point_rows(result: GlobalFrontierResult) -> tuple[GlobalFrontierPointRow, ...]:
    """Una fila por punto de la unión global, con su composición y su eficiencia global."""
    rows: list[GlobalFrontierPointRow] = []
    for entry in result.points:
        point, metrics = entry.point, entry.point.metrics
        rows.append(
            GlobalFrontierPointRow(
                portfolio_id=result.portfolio_id,
                scenario_id=result.scenario_id,
                frontier_type=result.frontier_type,
                global_frontier_point_id=entry.global_point_id,
                frontier_point_id=point.point_id,
                composition_id=entry.composition_id,
                strategy_id=point.strategy_id.value,
                volatility=None if metrics is None else metrics.volatility,
                expected_return_gross=None if metrics is None else metrics.expected_return_gross,
                expected_return_net=None if metrics is None else metrics.expected_return_net,
                turnover=None if metrics is None else metrics.turnover,
                transaction_cost=None if metrics is None else metrics.transaction_cost,
                transaction_cost_one_off=(
                    None if metrics is None else metrics.transaction_cost_one_off
                ),
                is_valid_solution=entry.is_valid_solution,
                is_gross_efficient_in_composition=point.is_gross_efficient,
                is_net_efficient_in_composition=point.is_net_efficient,
                is_global_gross_efficient=entry.is_global_gross_efficient,
                is_global_net_efficient=entry.is_global_net_efficient,
                is_duplicate=entry.is_duplicate,
                duplicate_of_global_point_id=entry.duplicate_of,
                sequence_id=entry.sequence_id,
            )
        )
    return tuple(rows)


def visualization_dataset(result: GlobalFrontierResult) -> pd.DataFrame:
    """Tabla con las tres capas graficables: cartera actual, frontera continua y global (VIS-002).

    ``Layer`` distingue ``CURRENT_PORTFOLIO`` (un punto), ``CONTINUOUS_FRONTIER`` (composición
    actual fija) y ``GLOBAL_CANDIDATE_FRONTIER`` (unión de composiciones, con su ``CompositionID``).
    ``Volatility``, ``ExpectedReturnGross`` y ``ExpectedReturnNet`` proceden de las métricas ya
    calculadas desde los pesos: no hay que recalcular nada. ``IsEfficient`` usa la magnitud del
    tratamiento (bruta en ``GROSS``; neta en ``NET`` y ``POST_COST_GROSS``): en la capa continua es
    la eficiencia dentro de su composición y en la global la eficiencia global.
    """
    gross = result.cost_treatment is CostTreatment.GROSS
    records: list[dict[str, object]] = []
    if result.current_metrics is not None:
        records.append(
            _record(
                result,
                LAYER_CURRENT,
                "CURRENT",
                result.current_composition_id or "",
                "CURRENT",
                result.current_metrics,
                True,
                None,
                False,
            )
        )
    if result.continuous is not None:
        for point in result.continuous.points:
            records.append(
                _record(
                    result,
                    LAYER_CONTINUOUS,
                    point.point_id,
                    point.composition_id,
                    point.strategy_id.value,
                    point.metrics,
                    point.is_valid_solution,
                    point.is_gross_efficient if gross else point.is_net_efficient,
                    point.is_duplicate,
                )
            )
    for entry in result.points:
        records.append(
            _record(
                result,
                LAYER_GLOBAL,
                entry.global_point_id,
                entry.composition_id,
                entry.point.strategy_id.value,
                entry.point.metrics,
                entry.is_valid_solution,
                entry.is_global_gross_efficient if gross else entry.is_global_net_efficient,
                entry.is_duplicate,
            )
        )
    return pd.DataFrame.from_records(records, columns=list(VISUALIZATION_COLUMNS))


def _record(
    result: GlobalFrontierResult,
    layer: str,
    point_id: str,
    composition_id: str,
    strategy: str,
    metrics: PointMetrics | None,
    valid: bool,
    efficient: bool | None,
    duplicate: bool,
) -> dict[str, object]:
    net = None if metrics is None else metrics.expected_return_net
    return {
        "PortfolioID": result.portfolio_id,
        "ScenarioID": result.scenario_id,
        "Layer": layer,
        "FrontierType": layer
        if layer == LAYER_CURRENT
        else f"{layer}:{result.cost_treatment.value}",
        "FrontierPointID": point_id,
        "CompositionID": composition_id,
        "StrategyID": strategy,
        "Volatility": np.nan if metrics is None else metrics.volatility,
        "ExpectedReturnGross": np.nan if metrics is None else metrics.expected_return_gross,
        "ExpectedReturnNet": np.nan if net is None else net,
        "IsValidSolution": valid,
        "IsEfficient": efficient,
        "IsDuplicate": duplicate,
    }
