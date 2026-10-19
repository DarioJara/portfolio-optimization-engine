"""OPT-011, OPT-012, MET-004: CVaR de Rockafellar-Uryasev sobre escenarios de retorno.

La solución de cada LP/QP se contrasta con el cálculo directo de CVaR
(:mod:`portfolio_engine.metrics.cvar_metric`), independiente de la formulación.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.exceptions import DataValidationError, UnsupportedCombinationError
from portfolio_engine.frontiers import StrategyOptimizer
from portfolio_engine.metrics import conditional_value_at_risk, portfolio_losses
from portfolio_engine.models.cvar import ReturnScenarioSet, build_return_scenario_set
from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    CVaRSource,
    HorizonScaling,
    OptimalityClaim,
    ScenarioWeighting,
    SolverStatus,
    StrategyID,
)
from portfolio_engine.validation.advanced_validator import (
    AdvancedChecks,
    AdvancedSolutionValidator,
    CVaRCheck,
)
from portfolio_engine.validation.solution_validator import ValidationContext
from portfolio_engine.validation.tolerances import ValidationTolerances
from tests.fixtures.block4 import CORR4, MU4, VOL4, four_asset_problem
from tests.fixtures.problems import base_config, cov_from_vol_corr, spec_with

pytestmark = pytest.mark.unit

CONFIG = base_config()
SIGMA4 = cov_from_vol_corr(VOL4, CORR4)
TOL = 1e-9


def _scenarios(
    seed: int = 0, periods: int = 400, weighting: ScenarioWeighting = ScenarioWeighting.EQUAL
) -> ReturnScenarioSet:
    rng = np.random.default_rng(seed)
    returns = rng.multivariate_normal(MU4 / 252, SIGMA4 / 252, size=periods)
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    return build_return_scenario_set(ids, returns, CVaRSource.HISTORICAL, weighting, None, TOL)


def _direct_cvar(weights: np.ndarray, scenarios: ReturnScenarioSet) -> float:
    losses = portfolio_losses(scenarios.returns, weights)
    return conditional_value_at_risk(losses, scenarios.weights, CONFIG.cvar.confidence_level)


def test_min_cvar_equals_the_direct_cvar_of_its_solution() -> None:
    """test_min_cvar: el valor del LP es el CVaR directo de la solución; α* es su VaR."""
    scenarios = _scenarios()
    result = StrategyOptimizer(CONFIG).cvar(
        four_asset_problem(CONFIG, max_weight=0.6),
        CostTreatment.GROSS,
        scenarios,
        CVaRObjective.MIN_CVAR,
    )
    assert result.is_valid_solution and result.weights is not None and result.solve is not None
    direct = _direct_cvar(result.weights, scenarios)
    assert result.solve.objective_value == pytest.approx(direct, abs=1e-9)
    assert result.extra("cvar_period") == pytest.approx(direct, abs=1e-12)
    assert result.extra("alpha") == pytest.approx(result.extra("var_period"), abs=1e-9)
    assert result.strategy_id is StrategyID.MIN_CVAR and result.solver_names == ("HiGHS",)
    assert result.optimality_claim is OptimalityClaim.CONVEX_GLOBAL
    assert result.validation is not None and "CVAR_LIMIT" in result.validation.checks


def test_no_random_feasible_portfolio_beats_the_min_cvar_solution() -> None:
    """Optimalidad frente a un oráculo independiente: miles de carteras factibles aleatorias."""
    scenarios = _scenarios(seed=3)
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    result = StrategyOptimizer(CONFIG).cvar(
        problem, CostTreatment.GROSS, scenarios, CVaRObjective.MIN_CVAR
    )
    assert result.weights is not None
    optimum = _direct_cvar(result.weights, scenarios)
    rng = np.random.default_rng(11)
    candidates = rng.dirichlet(np.ones(4) * 0.8, size=20000)
    candidates = candidates[candidates.max(axis=1) <= 0.6]
    best_random = min(_direct_cvar(w, scenarios) for w in candidates[:3000])
    assert candidates.shape[0] > 3000 and best_random >= optimum - 1e-10
    # y las perturbaciones factibles locales tampoco lo mejoran
    for _ in range(300):
        step = rng.normal(scale=0.02, size=4)
        step -= step.mean()
        neighbour = result.weights + step
        if neighbour.min() >= 0.0 and neighbour.max() <= 0.6:
            assert _direct_cvar(neighbour, scenarios) >= optimum - 1e-10


def test_a_symmetric_case_has_an_analytic_minimum_cvar() -> None:
    """Dos activos con pérdidas que se compensan: el mínimo es ``w = (½, ½)`` y CVaR = 0,025."""
    config = base_config(cvar={"confidence_level": 0.5, "min_tail_observations": 2})
    returns = np.array(
        [
            [-0.10, 0.05, 0.0, 0.0],
            [0.05, -0.10, 0.0, 0.0],
            [-0.10, 0.05, 0.0, 0.0],
            [0.05, -0.10, 0.0, 0.0],
        ]
    )
    ids = four_asset_problem(config).risk_model.asset_ids
    scenarios = build_return_scenario_set(
        ids, returns, CVaRSource.SIMULATED, ScenarioWeighting.EQUAL, None, TOL
    )
    problem = four_asset_problem(config, max_weight=1.0)  # los dos últimos activos no pierden nada
    result = StrategyOptimizer(config).cvar(
        problem, CostTreatment.GROSS, scenarios, CVaRObjective.MIN_CVAR
    )
    assert result.weights is not None
    # con activos de retorno nulo disponibles el mínimo posible es 0
    assert result.extra("cvar_period") == pytest.approx(0.0, abs=1e-9)
    two = four_asset_problem(
        config, max_weight=1.0, universe_overrides={"MaxWeight": [1.0, 1.0, 0.0, 0.0]}
    )
    constrained = StrategyOptimizer(config).cvar(
        two, CostTreatment.GROSS, scenarios, CVaRObjective.MIN_CVAR
    )
    assert constrained.weights is not None
    np.testing.assert_allclose(constrained.weights[:2], [0.5, 0.5], atol=1e-7)
    assert constrained.extra("cvar_period") == pytest.approx(0.025, abs=1e-9)


def test_the_cvar_constraint_is_active_and_respected() -> None:
    """test_cvar_constraint: ``CVaR <= MaxCVaR`` activo ⇒ igualdad; la utilidad baja."""
    scenarios = _scenarios(seed=5)
    problem = four_asset_problem(CONFIG, max_weight=0.7)
    optimizer = StrategyOptimizer(CONFIG)
    minimum = optimizer.cvar(problem, CostTreatment.GROSS, scenarios, CVaRObjective.MIN_CVAR)
    free = optimizer.cvar(
        problem,
        CostTreatment.GROSS,
        scenarios,
        CVaRObjective.UTILITY_WITH_LIMIT,
        max_cvar=1.0,
        risk_aversion=3.0,
    )
    assert minimum.weights is not None and free.weights is not None
    free_cvar = _direct_cvar(free.weights, scenarios)
    limit = 0.5 * (_direct_cvar(minimum.weights, scenarios) + free_cvar)
    limited = optimizer.cvar(
        problem,
        CostTreatment.GROSS,
        scenarios,
        CVaRObjective.UTILITY_WITH_LIMIT,
        max_cvar=limit,
        risk_aversion=3.0,
    )
    assert limited.is_valid_solution and limited.weights is not None
    assert _direct_cvar(limited.weights, scenarios) == pytest.approx(limit, abs=1e-7)  # activa
    assert limited.solver_names == ("OSQP",)  # CVaR lineal + objetivo cuadrático: QP, no cónico
    mu_free = float(MU4 @ free.weights) - 3.0 * float(free.weights @ SIGMA4 @ free.weights)
    mu_limited = float(MU4 @ limited.weights) - 3.0 * float(
        limited.weights @ SIGMA4 @ limited.weights
    )
    assert mu_limited <= mu_free + 1e-9  # restringir no puede mejorar la utilidad
    max_return = optimizer.cvar(
        problem, CostTreatment.GROSS, scenarios, CVaRObjective.MAX_RETURN_WITH_LIMIT, max_cvar=limit
    )
    assert max_return.is_valid_solution and max_return.solver_names == ("HiGHS",)  # LP
    assert max_return.weights is not None
    assert _direct_cvar(max_return.weights, scenarios) <= limit + 1e-7
    assert float(MU4 @ max_return.weights) >= float(MU4 @ limited.weights) - 1e-9


def test_a_limit_below_the_minimum_achievable_cvar_is_infeasible() -> None:
    scenarios = _scenarios(seed=7)
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    optimizer = StrategyOptimizer(CONFIG)
    minimum = optimizer.cvar(problem, CostTreatment.GROSS, scenarios, CVaRObjective.MIN_CVAR)
    assert minimum.weights is not None
    floor = _direct_cvar(minimum.weights, scenarios)
    result = optimizer.cvar(
        problem,
        CostTreatment.GROSS,
        scenarios,
        CVaRObjective.MAX_RETURN_WITH_LIMIT,
        max_cvar=0.5 * floor,
    )
    assert result.status is SolverStatus.INFEASIBLE and not result.is_valid_solution


def test_the_horizon_scaling_is_declared_and_applied_to_the_limit() -> None:
    """A-35: ``CVaR_horizonte = √h · CVaR_periodo`` y el límite está en el horizonte."""
    scaled = base_config(cvar={"horizon_periods": 4, "horizon_scaling": HorizonScaling.SQRT_TIME})
    assert scaled.cvar.horizon_factor == pytest.approx(2.0)
    scenarios = _scenarios(seed=9)
    problem = four_asset_problem(scaled, max_weight=0.7)
    optimizer = StrategyOptimizer(scaled)
    free = optimizer.cvar(
        problem, CostTreatment.GROSS, scenarios, CVaRObjective.MAX_RETURN_WITH_LIMIT, max_cvar=1.0
    )
    assert free.weights is not None
    horizon_limit = 0.9 * 2.0 * _direct_cvar(free.weights, scenarios)
    limited = optimizer.cvar(
        problem,
        CostTreatment.GROSS,
        scenarios,
        CVaRObjective.MAX_RETURN_WITH_LIMIT,
        max_cvar=horizon_limit,
    )
    assert limited.weights is not None and limited.is_valid_solution
    period = _direct_cvar(limited.weights, scenarios)
    assert limited.extra("cvar_horizon") == pytest.approx(2.0 * period, abs=1e-12)
    assert 2.0 * period == pytest.approx(horizon_limit, abs=1e-7)
    linear = base_config(cvar={"horizon_periods": 5, "horizon_scaling": HorizonScaling.LINEAR})
    assert linear.cvar.horizon_factor == 5.0


def test_net_costs_and_turnover_stay_inside_the_cvar_problem() -> None:
    scenarios = _scenarios(seed=13)
    holdings = [0.7, 0.1, 0.1, 0.1]
    problem = four_asset_problem(
        CONFIG,
        current=holdings,
        spec=spec_with(max_turnover=0.15),
        universe_overrides={"BuyCost": [200.0] * 4, "SellCost": [300.0] * 4},
    )
    result = StrategyOptimizer(CONFIG).cvar(
        problem, CostTreatment.NET, scenarios, CVaRObjective.MAX_RETURN_WITH_LIMIT, max_cvar=1.0
    )
    assert result.is_valid_solution and result.weights is not None
    assert 0.5 * np.abs(result.weights - np.array(holdings)).sum() <= 0.15 + 1e-7
    assert result.metrics is not None and result.metrics.transaction_cost is not None


def test_scenario_data_is_validated_and_never_imputed() -> None:
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    good = np.random.default_rng(0).normal(0, 0.01, size=(300, 4))
    with pytest.raises(DataValidationError, match="no se imputan"):
        bad = good.copy()
        bad[10, 2] = np.nan
        build_return_scenario_set(
            ids, bad, CVaRSource.HISTORICAL, ScenarioWeighting.EQUAL, None, TOL
        )
    with pytest.raises(DataValidationError, match="EQUAL no admite"):
        build_return_scenario_set(
            ids, good, CVaRSource.HISTORICAL, ScenarioWeighting.EQUAL, np.full(300, 1 / 300), TOL
        )
    with pytest.raises(DataValidationError, match="EXPLICIT exige"):
        build_return_scenario_set(
            ids, good, CVaRSource.HISTORICAL, ScenarioWeighting.EXPLICIT, None, TOL
        )
    with pytest.raises(DataValidationError, match="sumar 1"):
        build_return_scenario_set(
            ids,
            good,
            CVaRSource.HISTORICAL,
            ScenarioWeighting.EXPLICIT,
            np.full(300, 0.5 / 300),
            TOL,
        )
    with pytest.raises(DataValidationError, match="no negativos"):
        weights = np.full(300, 1 / 300)
        weights[0] = -weights[0]
        weights[1] += 2 / 300
        build_return_scenario_set(
            ids, good, CVaRSource.HISTORICAL, ScenarioWeighting.EXPLICIT, weights, TOL
        )
    with pytest.raises(DataValidationError, match="T × n"):
        build_return_scenario_set(
            ids, good[:, :3], CVaRSource.HISTORICAL, ScenarioWeighting.EQUAL, None, TOL
        )
    with pytest.raises(DataValidationError, match="ordenados"):
        build_return_scenario_set(
            tuple(reversed(ids)), good, CVaRSource.HISTORICAL, ScenarioWeighting.EQUAL, None, TOL
        )
    with pytest.raises(DataValidationError, match="al menos dos"):
        build_return_scenario_set(
            ids, good[:1], CVaRSource.HISTORICAL, ScenarioWeighting.EQUAL, None, TOL
        )


def test_explicit_scenario_weights_change_the_tail() -> None:
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    rng = np.random.default_rng(1)
    returns = rng.normal(0.0002, 0.01, size=(200, 4))
    weights = rng.dirichlet(np.ones(200))
    explicit = build_return_scenario_set(
        ids, returns, CVaRSource.SIMULATED, ScenarioWeighting.EXPLICIT, weights, TOL
    )
    uniform = build_return_scenario_set(
        ids, returns, CVaRSource.SIMULATED, ScenarioWeighting.EQUAL, None, TOL
    )
    w = np.full(4, 0.25)
    assert _direct_cvar(w, explicit) != pytest.approx(_direct_cvar(w, uniform), abs=1e-6)
    result = StrategyOptimizer(CONFIG).cvar(
        four_asset_problem(CONFIG, max_weight=0.6),
        CostTreatment.GROSS,
        explicit,
        CVaRObjective.MIN_CVAR,
    )
    assert result.is_valid_solution and result.weights is not None
    assert result.solve is not None and result.solve.objective_value == pytest.approx(
        _direct_cvar(result.weights, explicit), abs=1e-9
    )


def test_a_thin_tail_missing_assets_and_inconsistent_parameters_are_rejected() -> None:
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    thin = build_return_scenario_set(
        ids,
        np.random.default_rng(0).normal(0, 0.01, size=(50, 4)),
        CVaRSource.HISTORICAL,
        ScenarioWeighting.EQUAL,
        None,
        TOL,
    )
    optimizer = StrategyOptimizer(CONFIG)
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    with pytest.raises(DataValidationError, match="cola del CVaR"):
        optimizer.cvar(problem, CostTreatment.GROSS, thin, CVaRObjective.MIN_CVAR)
    missing = build_return_scenario_set(
        ids[:3],
        np.random.default_rng(0).normal(0, 0.01, size=(300, 3)),
        CVaRSource.HISTORICAL,
        ScenarioWeighting.EQUAL,
        None,
        TOL,
    )
    with pytest.raises(DataValidationError, match="sin escenarios de retorno"):
        optimizer.cvar(problem, CostTreatment.GROSS, missing, CVaRObjective.MIN_CVAR)
    scenarios = _scenarios()
    with pytest.raises(UnsupportedCombinationError, match=r"exige max_cvar|MaxCVaR"):
        optimizer.cvar(problem, CostTreatment.GROSS, scenarios, CVaRObjective.MAX_RETURN_WITH_LIMIT)
    with pytest.raises(UnsupportedCombinationError, match="risk_aversion"):
        optimizer.cvar(
            problem, CostTreatment.GROSS, scenarios, CVaRObjective.UTILITY_WITH_LIMIT, max_cvar=1.0
        )
    with pytest.raises(UnsupportedCombinationError, match="risk_aversion"):
        optimizer.cvar(
            problem, CostTreatment.GROSS, scenarios, CVaRObjective.MIN_CVAR, risk_aversion=2.0
        )
    with pytest.raises(UnsupportedCombinationError, match="no negativo"):
        optimizer.cvar(
            problem,
            CostTreatment.GROSS,
            scenarios,
            CVaRObjective.MAX_RETURN_WITH_LIMIT,
            max_cvar=-1.0,
        )


def test_the_validator_recomputes_cvar_and_rejects_a_solution_above_the_limit() -> None:
    scenarios = _scenarios(seed=17)
    problem = four_asset_problem(CONFIG)
    optimizer = StrategyOptimizer(CONFIG)
    context, _ = optimizer.prepare(problem, CostTreatment.GROSS)
    assert context is not None
    weights = np.array([0.0, 0.2, 0.7, 0.1])
    period = _direct_cvar(weights, scenarios)
    validator = AdvancedSolutionValidator(ValidationTolerances.from_config(CONFIG.solver))
    ctx = ValidationContext(context.inputs.mu, context.inputs.sigma, None)
    returns = scenarios.columns_for(context.compiled.asset_ids)
    rejected = validator.validate(
        weights,
        context.compiled,
        ctx,
        AdvancedChecks(cvar=CVaRCheck(returns, scenarios.weights, 0.95, 1.0, period - 0.001)),
    )
    assert not rejected.is_valid
    assert rejected.violations[0].constraint_id == "CVAR_LIMIT:max"
    assert rejected.violations[0].violation == pytest.approx(0.001, abs=1e-9)
    accepted = validator.validate(
        weights,
        context.compiled,
        ctx,
        AdvancedChecks(cvar=CVaRCheck(returns, scenarios.weights, 0.95, 1.0, period + 0.001)),
    )
    assert accepted.is_valid


def test_cvar_is_not_confused_with_var_volatility_or_maximum_loss_in_the_result() -> None:
    scenarios = _scenarios(seed=19)
    result = StrategyOptimizer(CONFIG).cvar(
        four_asset_problem(CONFIG, max_weight=0.6),
        CostTreatment.GROSS,
        scenarios,
        CVaRObjective.MIN_CVAR,
    )
    assert result.weights is not None and result.metrics is not None
    losses = portfolio_losses(scenarios.returns, result.weights)
    cvar = result.extra("cvar_period")
    var = result.extra("var_period")
    assert cvar is not None and var is not None and cvar > var
    assert cvar < float(losses.max()) and result.metrics.volatility != pytest.approx(cvar)
