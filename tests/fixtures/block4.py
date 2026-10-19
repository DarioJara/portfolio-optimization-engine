"""Oráculos y constructores independientes del Bloque 4 (escenarios, Sharpe, CVaR, robustez).

Los oráculos no usan las formulaciones cónicas bajo prueba: reutilizan el motor validado del
Bloque 2 (frontera de retorno objetivo, QP de composición fija) o herramientas generales de SciPy.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from portfolio_engine.config import (
    AssetShock,
    ConstraintOverrides,
    CorrelationStress,
    CostShock,
    EngineConfig,
    ScenarioDefinition,
    StressLimits,
)
from portfolio_engine.frontiers import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.models.enums import (
    CorrelationTarget,
    CostTreatment,
    FrontierMethod,
    ScenarioType,
    ShockSelector,
    StrategyID,
)
from tests.fixtures.problems import cov_from_vol_corr, make_problem

FloatArray = npt.NDArray[np.float64]

MU4 = np.array([0.08, 0.10, 0.12, 0.06])
VOL4 = np.array([0.15, 0.20, 0.25, 0.10])
CORR4 = np.array(
    [[1.0, 0.3, 0.2, 0.1], [0.3, 1.0, 0.4, 0.2], [0.2, 0.4, 1.0, 0.3], [0.1, 0.2, 0.3, 1.0]]
)


def four_asset_problem(
    config: EngineConfig,
    *,
    current: list[float] | None = None,
    max_weight: float = 1.0,
    **kwargs: object,
) -> FrontierProblem:
    """Cuatro activos con ``μ`` y ``Σ`` conocidas; pesos actuales iguales por defecto."""
    sigma = cov_from_vol_corr(VOL4, CORR4)
    holdings = [0.25, 0.25, 0.25, 0.25] if current is None else current
    overrides = kwargs.pop("universe_overrides", None)
    universe = {"MaxWeight": [max_weight] * 4}
    if isinstance(overrides, dict):
        universe.update(overrides)
    return make_problem(MU4, sigma, holdings, config, universe_overrides=universe, **kwargs)  # type: ignore[arg-type]


def golden_section_max(
    function: Callable[[float], float], low: float, high: float, iterations: int = 60
) -> tuple[float, float]:
    """Máximo de una función unimodal por sección áurea; devuelve ``(argmax, max)``."""
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = low, high
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = function(c), function(d)
    for _ in range(iterations):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = function(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = function(d)
    best = max((low, function(low)), (high, function(high)), (c, fc), (d, fd), key=lambda p: p[1])
    return best


def sharpe_by_target_return_search(
    problem: FrontierProblem, config: EngineConfig, treatment: CostTreatment
) -> tuple[float, FloatArray]:
    """Máximo Sharpe por búsqueda cuasiconvexa sobre la frontera de retorno objetivo (Bloque 2).

    Oráculo independiente de Charnes-Cooper: ``max_R (R − rf)/σ_min(R)`` con ``σ_min(R)`` el óptimo
    de ``min wᵀΣw`` s.a. retorno (bruto o neto) ``>= R`` y **todas** las restricciones. Se maximiza
    por sección áurea sobre ``[R(MinVar), R(MaxReturn)]`` (función unimodal sobre la frontera).
    """
    engine = ContinuousFrontierEngine(config)
    session = engine.open_session(problem, treatment, FrontierMethod.TARGET_RETURN_GRID)
    rf = config.returns.risk_free_rate
    net = treatment is CostTreatment.NET

    def realised(point: object) -> float:
        metrics = point.metrics  # type: ignore[attr-defined]
        return float(metrics.expected_return_net if net else metrics.expected_return_gross)

    minimum = session.solve_minimum_variance()
    maximum, _ = session.solve_maximum_return()
    low, high = realised(minimum), realised(maximum)
    weights: dict[float, FloatArray] = {}

    def sharpe(target: float) -> float:
        point = session.solve_target(target, strategy=StrategyID.FRONTIER_POINT)
        if not point.is_valid_solution or point.metrics is None or point.weights is None:
            return -math.inf
        value = (realised(point) - rf) / point.metrics.volatility
        weights[target] = point.weights
        return value

    target, value = golden_section_max(sharpe, low, high)
    return value, weights[target]


def scenario_definitions() -> tuple[ScenarioDefinition, ...]:
    """BASE, BEAR (mu −5 %, vol ×1,3) y CRASH (tecnología, correlación 0,8, costes ×2, estrés)."""
    return (
        ScenarioDefinition("BASE", ScenarioType.BASE, 0.5, None, (), None, (), None, None, None),
        ScenarioDefinition(
            "BEAR",
            ScenarioType.BEAR,
            0.3,
            None,
            (AssetShock(ShockSelector.ALL, (), None, -0.05, 1.3),),
            None,
            (),
            None,
            None,
            None,
        ),
        ScenarioDefinition(
            "CRASH",
            ScenarioType.EQUITY_CRASH,
            0.2,
            None,
            (AssetShock(ShockSelector.SECTOR, ("Tech",), 0.5, -0.1, 1.8),),
            CorrelationStress(0.5, CorrelationTarget.CONSTANT, 0.8, None, None),
            (CostShock(ShockSelector.ALL, (), 2.0),),
            None,
            StressLimits(0.16, None),
            None,
        ),
    )


def with_overrides(
    definition: ScenarioDefinition, overrides: ConstraintOverrides
) -> ScenarioDefinition:
    """Copia de ``definition`` con overrides de restricciones."""
    return dataclasses.replace(definition, constraint_overrides=overrides)
