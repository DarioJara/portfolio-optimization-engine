"""Puntos y resultados de fronteras eficientes (MASTER_SPEC §34, §63-65).

Las métricas no disponibles (p. ej. turnover sin cartera actual, MASTER_SPEC §24) son ``None``
con su motivo en ``unavailable_reason``: nunca se inventan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

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
