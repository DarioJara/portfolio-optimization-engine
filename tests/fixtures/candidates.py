"""Escenarios sintéticos deterministas para los tests del Bloque 3 (candidatos y frontera global).

Cada escenario controla ``mu``, ``Sigma``, pesos actuales, metadatos del universo y costes con datos
exactos, de modo que los valores esperados puedan derivarse analíticamente en el propio test.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates import CandidateContext, CandidateEngine
from portfolio_engine.config import EngineConfig
from portfolio_engine.frontiers import FrontierProblem
from portfolio_engine.models.composition import CandidateSearchResult
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem


def candidate_config(**candidate_changes: Any) -> EngineConfig:
    """Configuración de ejemplo con cambios en la sección ``candidates`` (validados de nuevo)."""
    return base_config(candidates=candidate_changes)


def with_candidates(config: EngineConfig, **changes: Any) -> EngineConfig:
    """Copia de ``config`` con campos de ``candidates`` cambiados."""
    return dataclasses.replace(config, candidates=dataclasses.replace(config.candidates, **changes))


def context_of(problem: FrontierProblem) -> CandidateContext:
    """``CandidateContext`` con los mismos datos que un ``FrontierProblem``."""
    return CandidateContext(
        problem.portfolio_id,
        problem.scenario_id,
        problem.risk_model,
        problem.universe,
        problem.state,
        problem.spec,
        problem.costs,
    )


def search(config: EngineConfig, problem: FrontierProblem) -> CandidateSearchResult:
    """Ejecuta el ``CandidateEngine`` real sobre ``problem``."""
    return CandidateEngine(config).search(problem.state.composition(), context_of(problem))


def corr_matrix(n: int, rho: float = 0.0, **pairs: float) -> npt.NDArray[np.float64]:
    """Matriz de correlación con ``rho`` constante y pares ``i_j=valor`` (p. ej. ``0_1=0.9``)."""
    matrix = np.full((n, n), rho, dtype=np.float64)
    np.fill_diagonal(matrix, 1.0)
    for key, value in pairs.items():
        i, j = (int(part) for part in key.split("_"))
        matrix[i, j] = matrix[j, i] = value
    return matrix


def random_problem(
    n: int,
    held: Sequence[int],
    seed: int,
    config: EngineConfig,
    *,
    weights: Sequence[float] | None = None,
    max_weight: float = 0.6,
    universe_overrides: Mapping[str, list[Any]] | None = None,
    **kwargs: Any,
) -> FrontierProblem:
    """Universo aleatorio (semilla explícita) con la cartera ``held`` a pesos iguales (o dados)."""
    rng = np.random.default_rng(seed)
    vols = rng.uniform(0.10, 0.30, n)
    factor = rng.normal(size=(n, n))
    sigma = cov_from_vol_corr(vols, np.corrcoef(factor @ factor.T + n * np.eye(n)))
    mu = rng.uniform(0.02, 0.15, n)
    current = [0.0] * n
    shares = list(weights) if weights is not None else [1.0 / len(held)] * len(held)
    for asset, share in zip(held, shares, strict=True):
        current[asset] = share
    overrides: dict[str, list[Any]] = {"MaxWeight": [max_weight] * n}
    overrides.update(dict(universe_overrides or {}))
    return make_problem(mu, sigma, current, config, universe_overrides=overrides, **kwargs)


def two_region_problem(config: EngineConfig, **kwargs: Any) -> FrontierProblem:
    """Escenario diseñado para que ≥2 composiciones sean globalmente no dominadas.

    ``A000``/``A001`` (actuales, 50 % cada uno) son de bajo riesgo y bajo retorno; ``A002``/``A003``
    son de alto retorno y alto riesgo; ``A004``/``A005`` son activos malos (retorno bajo, riesgo
    alto). Con tamaño objetivo 2 y ``MaxWeight = 1``:

    * la frontera de ``{A000, A001}`` llega a volatilidades (≈ 0,03) que ninguna composición con un
      activo de alto riesgo puede alcanzar, y
    * las composiciones con ``A002``/``A003`` llegan a retornos (≈ 0,20) que ``{A000, A001}`` nunca
      alcanza,

    así que ni la composición actual domina a las alternativas ni al revés.
    """
    vols = [0.03, 0.05, 0.30, 0.28, 0.40, 0.40]
    mu = np.array([0.04, 0.05, 0.20, 0.18, 0.01, 0.01])
    sigma = cov_from_vol_corr(vols, corr_matrix(6, 0.1))
    return make_problem(
        mu,
        sigma,
        [0.5, 0.5, 0.0, 0.0, 0.0, 0.0],
        config,
        universe_overrides={"MaxWeight": [1.0] * 6},
        **kwargs,
    )


def prepared_for(problem: FrontierProblem, config: EngineConfig, asset_ids: Sequence[str]):  # type: ignore[no-untyped-def]
    """``PreparedComposition`` real (restricciones compiladas del Bloque 2) de ``asset_ids``."""
    from portfolio_engine.candidates import CompositionFactory, EligibilityFilter, UniverseSnapshot
    from portfolio_engine.constraints import PreFeasibilityChecker, build_constraint_set

    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    eligibility = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    factory = CompositionFactory(
        snapshot=snapshot,
        eligible=eligibility.enterable,
        universe=problem.universe,
        state=problem.state,
        costs=problem.costs,
        constraint_set=build_constraint_set(
            config.constraints,
            problem.spec,
            problem.portfolio_id,
            config.frontier.min_holding_weight,
            config.candidates.unknown_liquidity_policy,
        ),
        checker=PreFeasibilityChecker(config.solver.constraint_tolerance),
        horizon_years=config.optimization_horizon_years,
    )
    return factory.prepare(snapshot.index.indices_of(asset_ids).tolist())


def exact_net_utility(
    mu: npt.NDArray[np.float64],
    sigma: npt.NDArray[np.float64],
    current: npt.NDArray[np.float64],
    buy: npt.NDArray[np.float64],
    sell: npt.NDArray[np.float64],
    exit_cost_one_off: float,
    horizon: float,
    lower: npt.NDArray[np.float64],
    upper: npt.NDArray[np.float64],
    risk_aversion: float,
) -> tuple[float, npt.NDArray[np.float64]]:
    """Óptimo independiente de ``μᵀw − λ wᵀΣw − TC(w)`` con SciPy SLSQP (variables ``w, b, s``).

    ``current`` son los pesos actuales sobre la composición; ``exit_cost_one_off`` el coste
    constante de liquidar los activos que salen. No usa ninguna clase del motor.
    """
    from scipy.optimize import minimize

    n = mu.shape[0]

    def negative_utility(x: npt.NDArray[np.float64]) -> float:
        w, b, s = x[:n], x[n : 2 * n], x[2 * n :]
        cost = (buy @ b + sell @ s + exit_cost_one_off) / horizon
        return float(-(mu @ w - risk_aversion * w @ sigma @ w - cost))

    constraints = [
        {"type": "eq", "fun": lambda x: x[:n] - x[n : 2 * n] + x[2 * n :] - current},
        {"type": "eq", "fun": lambda x: float(x[:n].sum() - 1.0)},
    ]
    bounds = [(lo, hi) for lo, hi in zip(lower, upper, strict=True)] + [(0.0, None)] * (2 * n)
    start = np.concatenate([np.full(n, 1.0 / n), np.zeros(2 * n)])
    result = minimize(
        negative_utility,
        start,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-14, "maxiter": 500},
    )
    return float(-result.fun), np.asarray(result.x[:n])


def services_for(problem: FrontierProblem, config: EngineConfig, evaluator=None):  # type: ignore[no-untyped-def]
    """``SearchServices`` reales (screening, listas cortas, generador, fábrica y evaluador).

    Permite probar ``BeamSearch`` y ``LocalSearch`` de forma aislada. ``evaluator`` por defecto es
    el ``ProjectedWeightsEvaluator`` de la configuración.
    """
    from portfolio_engine.candidates import (
        CandidateScreening,
        CompositionFactory,
        EligibilityFilter,
        ExplorationPolicy,
        ProjectedWeightsEvaluator,
        RejectionLog,
        SearchServices,
        SwapGenerator,
        UniverseSnapshot,
    )
    from portfolio_engine.constraints import PreFeasibilityChecker, build_constraint_set
    from portfolio_engine.constraints.integer import CompositionLimits
    from portfolio_engine.validation import SolutionValidator, ValidationTolerances

    cfg = config.candidates
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    eligibility = EligibilityFilter(cfg, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
    factory = CompositionFactory(
        snapshot=snapshot,
        eligible=eligibility.enterable,
        universe=problem.universe,
        state=problem.state,
        costs=problem.costs,
        constraint_set=build_constraint_set(
            config.constraints,
            problem.spec,
            problem.portfolio_id,
            config.frontier.min_holding_weight,
            config.candidates.unknown_liquidity_policy,
        ),
        checker=PreFeasibilityChecker(config.solver.constraint_tolerance),
        horizon_years=config.optimization_horizon_years,
    )
    return SearchServices(
        config=cfg,
        snapshot=snapshot,
        eligibility=eligibility,
        screening=CandidateScreening(cfg, config.returns.risk_free_rate),
        exploration=ExplorationPolicy(cfg.exploration),
        generator=SwapGenerator(cfg),
        factory=factory,
        evaluator=evaluator or ProjectedWeightsEvaluator(cfg.refinement_iterations, validator),
        limits=CompositionLimits(
            len(problem.state.asset_ids), cfg.max_new_assets, cfg.max_swaps, frozenset()
        ),
        reference_ids=frozenset(problem.state.asset_ids),
        target_size=len(problem.state.asset_ids),
        seed=config.random_seed,
        portfolio_id=problem.portfolio_id,
        scenario_id=problem.scenario_id,
        rejections=RejectionLog(cfg.max_recorded_rejections),
    )


def root_node(services, problem: FrontierProblem, lam: float):  # type: ignore[no-untyped-def]
    """Nodo raíz (la cartera actual evaluada) y la utilidad de la cartera actual para ``λ``."""
    from portfolio_engine.candidates import SearchNode, current_portfolio_utility
    from portfolio_engine.models.composition import CompositionEstimate
    from portfolio_engine.models.enums import CandidateOrigin

    snapshot = services.snapshot
    positions = tuple(int(p) for p in snapshot.index.indices_of(problem.state.asset_ids).tolist())
    held = np.array(positions)
    baseline = current_portfolio_utility(
        snapshot.mu[held], snapshot.sigma[np.ix_(held, held)], problem.state.weights, lam
    )
    prepared = services.factory.prepare(positions)
    estimate = services.evaluator.evaluate(prepared, lam, baseline)
    assert isinstance(estimate, CompositionEstimate)
    node = SearchNode(positions, prepared, estimate, None, (), 0.0, (), CandidateOrigin.REFERENCE)
    return node, baseline


#: Escenario de 12 activos con todos los roles de elegibilidad (ver ``test_eligibility``).
ROLES_N = 12
ROLES_HELD = (0, 1, 2, 3)


def roles_problem(config: EngineConfig, spec=None) -> FrontierProblem:  # type: ignore[no-untyped-def]
    """Cartera con A000-A003 (25 % cada uno) y un universo con todos los roles de elegibilidad.

    ``A001`` no elegible (mantenido), ``A002`` restringido (mantenido), ``A003`` ilíquido
    (mantenido), ``A004``/``A010``/``A011`` elegibles nuevos, ``A005`` no elegible, ``A006``
    ilíquido, ``A007`` restringido, ``A008`` con ``LiquidityFlag`` desconocido y ``A009`` con
    ``RestrictedAssetFlag`` desconocido (los cinco últimos no están en cartera).
    """
    n = ROLES_N
    eligible = [True] * n
    eligible[1] = eligible[5] = False
    liquid: list[bool | None] = [True] * n
    liquid[3] = liquid[6] = False
    liquid[8] = None
    restricted: list[bool | None] = [False] * n
    restricted[2] = restricted[7] = True
    restricted[9] = None
    sigma = cov_from_vol_corr([0.2] * n, np.full((n, n), 0.3) + 0.7 * np.eye(n))
    return make_problem(
        np.linspace(0.04, 0.12, n),
        sigma,
        [0.25, 0.25, 0.25, 0.25] + [0.0] * (n - 4),
        config,
        universe_overrides={
            "EligibleFlag": eligible,
            "LiquidityFlag": liquid,
            "RestrictedAssetFlag": restricted,
            "MaxWeight": [1.0] * n,
        },
        spec=spec,
    )


def universe_problem(
    n_universe: int, n_held: int, seed: int, config: EngineConfig
) -> FrontierProblem:
    """Universo grande (modelo factorial de rango bajo) con una cartera de ``n_held`` activos.

    Es el generador de ``benchmarks/scripts/candidate_engine.py`` y de los tests de memoria: los
    activos mantenidos se reparten uniformemente por el universo, ``MaxWeight = 0.2`` y costes de
    compra/venta de 5-40 bps.
    """
    rng = np.random.default_rng(seed)
    factors = rng.normal(size=(n_universe, 8))
    covariance = factors @ factors.T + np.diag(rng.uniform(0.5, 2.0, n_universe))
    correlation = covariance / np.sqrt(np.outer(np.diag(covariance), np.diag(covariance)))
    sigma = cov_from_vol_corr(rng.uniform(0.1, 0.4, n_universe), correlation)
    stride = n_universe // n_held
    current = [0.0] * n_universe
    for i in range(n_held):
        current[i * stride] = 1.0 / n_held
    overrides = {
        "MaxWeight": [0.2] * n_universe,
        "BuyCost": rng.uniform(5.0, 40.0, n_universe).tolist(),
        "SellCost": rng.uniform(5.0, 40.0, n_universe).tolist(),
    }
    return make_problem(
        rng.uniform(0.02, 0.15, n_universe), sigma, current, config, universe_overrides=overrides
    )
