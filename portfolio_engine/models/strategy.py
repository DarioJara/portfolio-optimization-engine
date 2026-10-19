"""Resultado de una estrategia nombrada del Bloque 4 (MASTER_SPEC §54, §63, §82; OPT-014, SCN-008).

Una :class:`StrategyResult` es una **solución** (no una frontera): Max Sharpe, control de
volatilidad, CVaR, robusta, o una cartera única multiescenario. Conserva ``ScenarioID``,
``StrategyID``, ``CompositionID`` y el veredicto del validador independiente; el estado del solver
nunca basta para considerarla válida (§44) y la afirmación de optimalidad (``optimality_claim``) es
la del backend, jamás una etiqueta global sin evidencia.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.models.enums import (
    CostTreatment,
    OptimalityClaim,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.models.frontier import PointMetrics
from portfolio_engine.models.solution import SolveResult, ValidationReport
from portfolio_engine.utils.numerics import readonly_float_array


@dataclass(frozen=True, slots=True)
class ScenarioMetrics:
    """Métricas de una solución bajo un escenario concreto (recalculadas desde los pesos)."""

    scenario_id: str
    metrics: PointMetrics
    utility: float | None


@dataclass(frozen=True, eq=False, slots=True)
class StrategyResult:
    """Solución de una estrategia nombrada para una cartera.

    Attributes:
        portfolio_id: cartera.
        scenario_id: escenario de la solución (``MULTI:<modo>`` si es una cartera única para varios
            escenarios; entonces ``scenario_metrics`` la evalúa bajo cada uno).
        strategy_id: estrategia (``MAX_SHARPE``, ``VOL_TARGET``…).
        composition_id: ``CompositionHash`` de la composición optimizada.
        asset_ids: activos de la composición (orden de ``weights``).
        cost_treatment: ``GROSS`` o ``NET`` (el coste dentro de la optimización, no ex post).
        weights: pesos (``None`` si no hay solución utilizable).
        metrics: métricas bajo el escenario de la solución (``None`` sin pesos).
        scenario_metrics: métricas bajo cada escenario evaluado (solución única multiescenario).
        objective_value: valor del objetivo recalculado desde los pesos (no el del solver).
        solve: resultado del backend (estado nativo, residuales, tiempos, iteraciones).
        validation: informe del validador independiente (``None`` sin pesos).
        is_valid_solution: estado aceptable **y** validación superada.
        status: estado normalizado del solver (o ``INFEASIBLE`` de la factibilidad previa).
        status_source: quién determinó el estado (solver, validador o comprobación previa).
        outcome: veredicto propio de la estrategia (p. ej. ``SharpeOutcome``) o ``None``.
        optimality_claim: qué garantiza el backend sobre la optimalidad.
        extras: magnitudes específicas (Sharpe, CVaR, utilidad del peor caso…) recalculadas
            independientemente.
        notes: observaciones y limitaciones de la resolución.
        solver_names: solvers que intervinieron (orden de uso).
    """

    portfolio_id: str
    scenario_id: str
    strategy_id: StrategyID
    composition_id: str
    asset_ids: tuple[str, ...]
    cost_treatment: CostTreatment
    weights: npt.NDArray[np.float64] | None
    metrics: PointMetrics | None
    scenario_metrics: tuple[ScenarioMetrics, ...]
    objective_value: float | None
    solve: SolveResult | None
    validation: ValidationReport | None
    is_valid_solution: bool
    status: SolverStatus
    status_source: StatusSource
    outcome: str | None
    optimality_claim: OptimalityClaim
    extras: tuple[tuple[str, float], ...]
    notes: tuple[str, ...]
    solver_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.weights is not None:
            object.__setattr__(self, "weights", readonly_float_array(self.weights))

    def extra(self, name: str) -> float | None:
        """Magnitud ``name`` de :attr:`extras` (``None`` si no existe)."""
        for key, value in self.extras:
            if key == name:
                return value
        return None
