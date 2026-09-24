"""Constructores de problemas de frontera con ``mu``/``Sigma`` explícitos (semilla y datos exactos).

Los tests analíticos necesitan controlar ``mu``, ``Sigma``, pesos actuales, costes y límites; estos
helpers construyen un :class:`FrontierProblem` completo con los validadores reales del Bloque 1.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from portfolio_engine.config import EngineConfig, GroupLimit, load_engine_config
from portfolio_engine.constraints import (
    CompiledConstraints,
    ConstraintCompiler,
    build_constraint_set,
)
from portfolio_engine.costs import TransactionCostModel, align_union
from portfolio_engine.data.validation import UniverseValidator, resolve_asset_costs
from portfolio_engine.frontiers import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import (
    CostTreatment,
    CovarianceMethod,
    ExpectedReturnMode,
    FrontierMethod,
    InternalEstimationMethod,
    RestrictedExistingPositionPolicy,
    StrategyID,
)
from portfolio_engine.models.frontier import CompositionFrontierResult, FrontierPoint
from portfolio_engine.models.portfolio import CurrentPortfolioState, PortfolioSpec
from portfolio_engine.models.risk_model import ExpectedReturns, RiskModel
from portfolio_engine.models.universe_index import AssetIndex
from portfolio_engine.optimizers.formulations import CompositionInputs
from portfolio_engine.risk import CovarianceBuilder
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.synthetic import asset_ids, universe_frame


def base_config(**section_changes: Mapping[str, Any]) -> EngineConfig:
    """Configuración de ejemplo con cambios por sección: ``solver={"eps_abs": 1e-10}``."""
    config = load_engine_config(DEFAULT_CONFIG_PATH)
    for section, changes in section_changes.items():
        if section == "engine":
            config = dataclasses.replace(config, **changes)
        else:
            config = dataclasses.replace(
                config, **{section: dataclasses.replace(getattr(config, section), **changes)}
            )
    return config


def with_group_limits(config: EngineConfig, limits: Sequence[GroupLimit]) -> EngineConfig:
    """Copia de ``config`` con ``limits`` como límites de grupo."""
    constraints = dataclasses.replace(config.constraints, group_limits=tuple(limits))
    return dataclasses.replace(config, constraints=constraints)


def risk_model(
    mu: npt.ArrayLike, sigma: npt.ArrayLike, config: EngineConfig, ids: Sequence[str] | None = None
) -> RiskModel:
    """``RiskModel`` con ``mu`` y ``Sigma`` exactos (la covarianza pasa la validación PSD real)."""
    mu_array = np.asarray(mu, dtype=np.float64)
    sigma_array = np.asarray(sigma, dtype=np.float64)
    names = tuple(ids) if ids is not None else tuple(asset_ids(mu_array.shape[0]))
    covariance = CovarianceBuilder(config.risk, config.returns.trading_days_per_year).validate(
        sigma_array, names, CovarianceMethod.EMPIRICAL, None, mu_array.shape[0]
    )
    expected = ExpectedReturns(
        names,
        mu_array,
        ExpectedReturnMode.INTERNAL_ESTIMATION,
        InternalEstimationMethod.HISTORICAL_MEAN.value,
    )
    return RiskModel(expected, covariance)


def make_problem(
    mu: npt.ArrayLike,
    sigma: npt.ArrayLike,
    current: Sequence[float] | None,
    config: EngineConfig,
    *,
    universe_overrides: Mapping[str, list[Any]] | None = None,
    spec: PortfolioSpec | None = None,
    with_costs: bool = True,
    portfolio_id: str = "P1",
    composition: tuple[str, ...] | None = None,
) -> FrontierProblem:
    """Problema con ``mu``, ``Sigma`` y pesos actuales exactos (``current=None``: sin cartera)."""
    mu_array = np.asarray(mu, dtype=np.float64)
    n_assets = mu_array.shape[0]
    universe = build_universe(n_assets, config, universe_overrides)
    ids = universe.asset_ids
    index = AssetIndex.from_universe(universe)
    weights = (
        {}
        if current is None
        else {asset: float(w) for asset, w in zip(ids, current, strict=True) if w != 0.0}
    )
    state = CurrentPortfolioState.from_weights(portfolio_id, weights, index, None)
    costs: AssetCostVector | None = (
        resolve_asset_costs(universe, config.transaction_costs).require_complete()
        if with_costs
        else None
    )
    return FrontierProblem(
        portfolio_id=portfolio_id,
        scenario_id="BASE",
        risk_model=risk_model(mu_array, sigma, config, ids),
        universe=universe,
        state=state,
        spec=spec,
        costs=costs,
        composition_asset_ids=composition,
    )


def build_universe(
    n_assets: int, config: EngineConfig, overrides: Mapping[str, list[Any]] | None = None
) -> Universe:
    """Universo sintético validado (columnas sobrescribibles)."""
    frame = universe_frame(n_assets, **dict(overrides or {}))
    return UniverseValidator(config.constraints).validate(frame).universe


def restricted_universe(
    n_assets: int, restricted: Sequence[int], **overrides: list[Any]
) -> dict[str, list[Any]]:
    """Overrides de universo que marcan como restringidos los activos ``restricted`` (índices)."""
    flags = [i in set(restricted) for i in range(n_assets)]
    return {"RestrictedAssetFlag": flags, **overrides}


def spec_with(**fields: Any) -> PortfolioSpec:
    """``PortfolioSpec`` de la cartera ``P1`` con campos opcionales (los no dados son ``None``)."""
    values: dict[str, Any] = {
        "portfolio_id": "P1",
        "target_portfolio_size": None,
        "volatility_limit": None,
        "max_turnover": None,
        "investment_universe": None,
        "restricted_existing_position_policy": None,
        "nav": None,
    }
    values.update(fields)
    return PortfolioSpec(**values)


def policy_config(config: EngineConfig, policy: RestrictedExistingPositionPolicy) -> EngineConfig:
    """Copia de ``config`` con la política de restringidos indicada."""
    constraints = dataclasses.replace(
        config.constraints, restricted_existing_position_policy=policy
    )
    return dataclasses.replace(config, constraints=constraints)


def cov_from_vol_corr(vols: Sequence[float], corr: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """``Σ = diag(σ) · C · diag(σ)``."""
    scale = np.asarray(vols, dtype=np.float64)
    return np.asarray(np.diag(scale) @ np.asarray(corr, dtype=np.float64) @ np.diag(scale))


def frontier_result(
    problem: FrontierProblem,
    config: EngineConfig,
    treatment: CostTreatment = CostTreatment.GROSS,
    method: FrontierMethod = FrontierMethod.RISK_AVERSION_GRID,
) -> CompositionFrontierResult:
    """Resuelve una frontera con el motor real."""
    return ContinuousFrontierEngine(config).solve(problem, treatment, method)


def point_of(result: CompositionFrontierResult, strategy: StrategyID) -> FrontierPoint:
    """Primer punto de ``result`` con la estrategia indicada (MinVariance o MaxReturn)."""
    return next(point for point in result.points if point.strategy_id is strategy)


def weights_of(point: FrontierPoint) -> npt.NDArray[np.float64]:
    """Pesos de un punto (el punto debe tener solución)."""
    if point.weights is None:
        raise AssertionError(f"El punto {point.point_id} no tiene pesos ({point.status}).")
    return point.weights


def compiled_for(problem: FrontierProblem, config: EngineConfig) -> CompiledConstraints:
    """Restricciones compiladas de la composición del problema."""
    constraint_set = build_constraint_set(
        config.constraints, problem.spec, problem.portfolio_id, config.frontier.min_holding_weight
    )
    composition = problem.composition_asset_ids or problem.state.asset_ids
    return ConstraintCompiler().compile(
        constraint_set, problem.universe, composition, problem.state
    )


def composition_inputs(problem: FrontierProblem, config: EngineConfig) -> CompositionInputs:
    """``CompositionInputs`` (mu, Sigma, restricciones y costes) de la composición."""
    compiled = compiled_for(problem, config)
    position = {a: i for i, a in enumerate(problem.risk_model.asset_ids)}
    idx = np.array([position[a] for a in compiled.asset_ids])
    cost_model = None
    if problem.state.has_current_portfolio and problem.costs is not None:
        alignment = align_union(problem.state, compiled.asset_ids)
        cost_model = TransactionCostModel(
            alignment, problem.costs, config.optimization_horizon_years
        )
    return CompositionInputs(
        problem.risk_model.mu[idx], problem.risk_model.sigma[np.ix_(idx, idx)], compiled, cost_model
    )


def synthetic_problem(n_assets: int, seed: int, config: EngineConfig) -> FrontierProblem:
    """Problema sintético reproducible (semilla explícita) con cartera actual y costes.

    Es el generador de ``benchmarks/scripts`` (H-1, solver_reuse): ``Σ = FFᵀ + D`` con factor
    aleatorio, retornos en [3 %, 12 %], pesos actuales aleatorios, ``MaxWeight = 0.25`` y costes
    de compra/venta de 5-40 bps.
    """
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n_assets, n_assets)) * 0.05
    sigma = factor @ factor.T + np.diag(rng.uniform(0.02, 0.05, n_assets))
    mu = rng.uniform(0.03, 0.12, n_assets)
    raw = rng.uniform(0.5, 1.5, n_assets)
    current = (raw / raw.sum()).tolist()
    overrides = {
        "MaxWeight": [0.25] * n_assets,
        "BuyCost": rng.uniform(5.0, 40.0, n_assets).tolist(),
        "SellCost": rng.uniform(5.0, 40.0, n_assets).tolist(),
    }
    return make_problem(mu, sigma, current, config, universe_overrides=overrides)
