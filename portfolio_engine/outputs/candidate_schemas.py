"""Esquemas de salida del Bloque 3: composiciones, diagnósticos y frontera global (§26, §33, §66).

Como en el resto de salidas, un valor no disponible es ``None`` con su motivo (nunca se inventa,
§24). Los campos ``estimated_*`` son estimaciones del screening y de la búsqueda, **no** resultados
de la optimización de pesos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CandidateCompositionRow:
    """Fila de ``CandidateCompositions`` (MASTER_SPEC §26; contrato del Bloque 3, OUT-009).

    ``estimate_basis`` indica cómo se estimaron los valores ``estimated_*``;
    ``estimate_unavailable_reason`` explica por qué turnover o coste estimados pueden faltar.
    """

    portfolio_id: str
    scenario_id: str
    composition_id: str
    composition_hash: str
    assets: tuple[str, ...]
    parent_composition_id: str | None
    swap_history: str
    number_of_moves: int
    candidate_score: float
    estimated_utility_gain: float
    estimated_turnover: float | None
    estimated_transaction_cost: float | None
    candidate_type: str
    origin: str
    is_reference: bool
    best_risk_aversion: float | None
    estimate_basis: str | None
    estimate_unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class CandidateDiagnosticsRow:
    """Fila de ``CandidateDiagnostics`` por activo (MASTER_SPEC §66, OUT-004)."""

    portfolio_id: str
    scenario_id: str
    asset_id: str
    ticker: str
    candidate_type: str | None
    candidate_score: float | None
    alpha_score: float | None
    diversification_score: float | None
    marginal_utility: float | None
    liquidity_score: float | None
    transaction_cost_estimate: float | None
    selected_for_optimization: bool
    rejection_reason: str | None
    eligibility_status: str
    eligibility_reasons: tuple[str, ...]
    missing_signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GlobalFrontierPointRow:
    """Punto de la unión de fronteras de composición con su eficiencia global (MASTER_SPEC §33)."""

    portfolio_id: str
    scenario_id: str
    frontier_type: str
    global_frontier_point_id: str
    frontier_point_id: str
    composition_id: str
    strategy_id: str
    volatility: float | None
    expected_return_gross: float | None
    expected_return_net: float | None
    turnover: float | None
    transaction_cost: float | None
    transaction_cost_one_off: float | None
    is_valid_solution: bool
    is_gross_efficient_in_composition: bool | None
    is_net_efficient_in_composition: bool | None
    is_global_gross_efficient: bool | None
    is_global_net_efficient: bool | None
    is_duplicate: bool
    duplicate_of_global_point_id: str | None
    sequence_id: int
