"""Puntos y resultados de fronteras eficientes (MASTER_SPEC §33-34, §63-65).

Las métricas no disponibles (p. ej. turnover sin cartera actual, MASTER_SPEC §24) son ``None``
con su motivo en ``unavailable_reason``: nunca se inventan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from portfolio_engine.models.composition import CandidateComposition, CandidateDiagnostics
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    FrontierScope,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.models.solution import SolveResult, ValidationReport
from portfolio_engine.utils.numerics import readonly_float_array


@dataclass(frozen=True, slots=True)
class PointMetrics:
    """Métricas de una cartera, calculadas desde sus pesos (nunca desde el solver)."""

    expected_return_gross: float
    variance: float
    volatility: float
    sharpe_ratio: float | None
    herfindahl_index: float
    number_assets: int
    turnover: float | None
    transaction_cost_one_off: float | None
    transaction_cost: float | None
    expected_return_net: float | None
    number_new_assets: int | None
    number_removed_assets: int | None
    unavailable_reason: str | None


@dataclass(frozen=True, eq=False, slots=True)
class FrontierPoint:
    """Un punto de frontera con su solución, métricas, validación y flags de eficiencia."""

    point_id: str
    sequence: int
    strategy_id: StrategyID
    scope: FrontierScope
    cost_treatment: CostTreatment
    method: FrontierMethod
    composition_id: str
    theta: float | None
    target_return: float | None
    weights: npt.NDArray[np.float64] | None
    metrics: PointMetrics | None
    objective_value: float | None
    solve: SolveResult | None
    validation: ValidationReport | None
    is_valid_solution: bool
    status: SolverStatus
    status_source: StatusSource
    is_gross_efficient: bool | None = None
    is_net_efficient: bool | None = None
    is_duplicate: bool = False
    duplicate_of: str | None = None
    is_adaptive_insertion: bool = False

    def __post_init__(self) -> None:
        if self.weights is not None:
            object.__setattr__(self, "weights", readonly_float_array(self.weights))


@dataclass(frozen=True, slots=True)
class FrontierDiagnostics:
    """Contadores y tiempos agregados de la resolución de una frontera (MASTER_SPEC §67, §71).

    ``min_variance_time`` y ``max_return_time`` (extremos de la frontera, MaximumReturn incluye el
    LP y la etapa 2) y ``grid_time`` (malla y refinado adaptativo) desglosan ``frontier_time``;
    ``total_iterations`` suma las iteraciones de **todas** las resoluciones (extremos incluidos) y
    ``endpoint_iterations`` las de los extremos, de modo que la malla es la diferencia.
    """

    solver_name: str
    solver_version: str
    setup_count: int
    update_count: int
    solve_count: int
    warm_start_count: int
    cold_retry_count: int
    setup_time: float
    update_time: float
    solve_time: float
    frontier_time: float
    min_variance_time: float = 0.0
    max_return_time: float = 0.0
    grid_time: float = 0.0
    total_iterations: int = 0
    endpoint_iterations: int = 0


@dataclass(frozen=True, eq=False, slots=True)
class CompositionFrontierResult:
    """Frontera de una composición: puntos, factibilidad previa y diagnósticos.

    ``pre_check_feasible = False`` significa que el solver no se invocó (decisión A-15) y que
    ``infeasibility_causes`` recoge las causas deterministas.
    """

    portfolio_id: str
    scenario_id: str
    composition_id: str
    asset_ids: tuple[str, ...]
    scope: FrontierScope
    cost_treatment: CostTreatment
    method: FrontierMethod
    optimization_horizon_years: float
    has_current_portfolio: bool
    pre_check_feasible: bool
    infeasibility_causes: tuple[str, ...]
    points: tuple[FrontierPoint, ...]
    current_metrics: PointMetrics | None
    diagnostics: FrontierDiagnostics
    constraint_hash: str
    mu_sigma_version: str
    config_hash: str
    notes: tuple[str, ...] = field(default=())

    @property
    def frontier_type(self) -> str:
        """``FrontierType`` compuesto de las salidas: ``"{scope}:{treatment}"`` (decisión A-05)."""
        return f"{self.scope.value}:{self.cost_treatment.value}"

    @property
    def asset_set(self) -> frozenset[str]:
        """Conjunto de activos de la composición (TST-011)."""
        return frozenset(self.asset_ids)

    @property
    def valid_points(self) -> tuple[FrontierPoint, ...]:
        """Puntos con solución válida (los inválidos se conservan en ``points``)."""
        return tuple(point for point in self.points if point.is_valid_solution)


@dataclass(frozen=True, eq=False, slots=True)
class GlobalFrontierPoint:
    """Punto de la unión de las fronteras de todas las composiciones (MASTER_SPEC §33).

    Conserva la composición de origen (``composition_id``, ``asset_ids``) y el punto completo de la
    frontera de composición (pesos optimizados, métricas, diagnósticos del solver y validación).
    Las banderas ``is_global_*`` son distintas de las de eficiencia dentro de su propia
    composición (``FrontierPoint.is_gross_efficient``): comparan contra todas las composiciones y
    cada una usa una única magnitud de retorno (nunca se mezclan brutos y netos).
    """

    global_point_id: str
    sequence_id: int
    composition_id: str
    asset_ids: tuple[str, ...]
    point: FrontierPoint
    is_global_gross_efficient: bool | None = None
    is_global_net_efficient: bool | None = None
    is_duplicate: bool = False
    duplicate_of: str | None = None

    @property
    def is_valid_solution(self) -> bool:
        """``True`` si el punto tiene una solución válida (los inválidos se conservan)."""
        return self.point.is_valid_solution and self.point.metrics is not None


@dataclass(frozen=True, slots=True)
class GlobalFrontierDiagnostics:
    """Contadores y tiempos de la construcción de la frontera global (descriptivos)."""

    candidate_count: int
    frontiers_solved: int
    points_total: int
    points_valid: int
    points_duplicate: int
    points_efficient: int
    candidate_time: float
    frontier_time: float
    pareto_time: float
    total_time: float


@dataclass(frozen=True, eq=False, slots=True)
class GlobalFrontierResult:
    """``GLOBAL_CANDIDATE_FRONTIER``: fronteras de varias composiciones y su envolvente Pareto.

    ``continuous`` es la ``CONTINUOUS_FRONTIER`` de la cartera actual (composición fija) y
    ``composition_results`` las fronteras de **todas** las composiciones candidatas (la actual
    incluida, como referencia); ambas son entidades distintas y quedan disponibles para graficar
    junto a ``current_metrics`` sin recalcular nada.
    """

    portfolio_id: str
    scenario_id: str
    cost_treatment: CostTreatment
    method: FrontierMethod
    optimization_horizon_years: float
    has_current_portfolio: bool
    current_composition_id: str | None
    current_metrics: PointMetrics | None
    continuous: CompositionFrontierResult | None
    candidates: tuple[CandidateComposition, ...]
    candidate_diagnostics: CandidateDiagnostics
    composition_results: tuple[CompositionFrontierResult, ...]
    points: tuple[GlobalFrontierPoint, ...]
    diagnostics: GlobalFrontierDiagnostics

    @property
    def frontier_type(self) -> str:
        """``FrontierType`` compuesto ``"{scope}:{treatment}"`` (decisión A-05)."""
        return f"{FrontierScope.GLOBAL_CANDIDATE_FRONTIER.value}:{self.cost_treatment.value}"

    @property
    def valid_points(self) -> tuple[GlobalFrontierPoint, ...]:
        """Puntos válidos de todas las composiciones (incluye los dominados y duplicados)."""
        return tuple(point for point in self.points if point.is_valid_solution)

    @property
    def envelope(self) -> tuple[GlobalFrontierPoint, ...]:
        """Envolvente Pareto global: puntos válidos, no duplicados y globalmente eficientes.

        La magnitud es la del tratamiento: bruto para ``GROSS``; neto para ``NET`` y
        ``POST_COST_GROSS`` (evaluación tras costes de los pesos brutos).
        """
        flags = (
            "is_global_gross_efficient"
            if self.cost_treatment is CostTreatment.GROSS
            else "is_global_net_efficient"
        )
        return tuple(
            point
            for point in self.points
            if point.is_valid_solution and not point.is_duplicate and getattr(point, flags) is True
        )

    @property
    def composition_ids(self) -> frozenset[str]:
        """``CompositionID`` distintos con al menos un punto válido (antes del filtro Pareto)."""
        return frozenset(point.composition_id for point in self.valid_points)

    @property
    def envelope_composition_ids(self) -> frozenset[str]:
        """``CompositionID`` distintos con al menos un punto en la envolvente global."""
        return frozenset(point.composition_id for point in self.envelope)
