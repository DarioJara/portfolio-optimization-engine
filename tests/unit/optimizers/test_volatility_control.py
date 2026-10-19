"""CON-004, OPT-010, VAL-003, FEA-005: control de volatilidad ``√(wᵀΣw) <= VolatilityLimit`` (SOCP).

Oráculo independiente: SLSQP sobre el mismo problema con restricción cuadrática ``σ² <= L²``.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.optimize import minimize

from portfolio_engine.constraints.feasibility import check_volatility, volatility_lower_bound
from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.frontiers import ContinuousFrontierEngine, StrategyOptimizer
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    OptimalityClaim,
    ProblemClass,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.optimizers.formulations.conic import factor_covariance
from portfolio_engine.optimizers.formulations.volatility import build_volatility_problem
from portfolio_engine.validation.advanced_validator import (
    AdvancedChecks,
    AdvancedSolutionValidator,
    VolatilityLimitCheck,
)
from portfolio_engine.validation.solution_validator import ValidationContext
from portfolio_engine.validation.tolerances import ValidationTolerances
from tests.fixtures.block4 import CORR4, MU4, VOL4, four_asset_problem
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem, spec_with

pytestmark = pytest.mark.unit

CONFIG = base_config()
SIGMA4 = cov_from_vol_corr(VOL4, CORR4)


def _slsqp_max_return(limit: float, cap: float = 1.0) -> np.ndarray:
    result = minimize(
        lambda w: -float(MU4 @ w),
        np.full(4, 0.25),
        jac=lambda w: -MU4,
        bounds=[(0.0, cap)] * 4,
        constraints=[
            {"type": "eq", "fun": lambda w: w.sum() - 1.0},
            {"type": "ineq", "fun": lambda w: limit**2 - float(w @ SIGMA4 @ w)},
        ],
        method="SLSQP",
        options={"ftol": 1e-15, "maxiter": 1000},
    )
    assert result.success
    return np.asarray(result.x)


@pytest.mark.parametrize("limit", [0.11, 0.14, 0.18])
def test_the_active_volatility_constraint_matches_the_slsqp_oracle(limit: float) -> None:
    """Restricción activa: ``vol == límite`` y el retorno coincide con el del oráculo."""
    problem = four_asset_problem(CONFIG)
    result = StrategyOptimizer(CONFIG).volatility_target(
        problem, CostTreatment.GROSS, volatility_limit=limit
    )
    assert result.is_valid_solution and result.weights is not None and result.metrics is not None
    assert result.metrics.volatility == pytest.approx(limit, abs=1e-6)  # activa
    oracle = _slsqp_max_return(limit)
    assert result.extra("return") == pytest.approx(float(MU4 @ oracle), abs=1e-7)
    np.testing.assert_allclose(result.weights, oracle, atol=1e-4)
    assert result.solver_names == ("CLARABEL",) and result.strategy_id is StrategyID.VOL_TARGET
    assert result.optimality_claim is OptimalityClaim.CONVEX_GLOBAL
    assert result.validation is not None and "VOLATILITY_LIMIT" in result.validation.checks


def test_a_slack_limit_gives_the_maximum_return_portfolio() -> None:
    """Con el límite inactivo la solución es la de retorno máximo del Bloque 2 (LP)."""
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    result = StrategyOptimizer(CONFIG).volatility_target(
        problem, CostTreatment.GROSS, volatility_limit=0.5
    )
    frontier = ContinuousFrontierEngine(CONFIG).solve(
        problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    maximum = next(p for p in frontier.points if p.strategy_id is StrategyID.MAX_RETURN)
    assert result.metrics is not None and maximum.metrics is not None
    assert result.metrics.volatility < 0.5 - 1e-3  # inactivo
    assert result.extra("return") == pytest.approx(maximum.metrics.expected_return_gross, abs=1e-7)


def test_the_volatility_constraint_is_a_socp_never_a_qp() -> None:
    problem = four_asset_problem(CONFIG)
    optimizer = StrategyOptimizer(CONFIG)
    context, _ = optimizer.prepare(problem, CostTreatment.GROSS)
    assert context is not None
    factor = factor_covariance(context.inputs.sigma, CONFIG.conic)
    extended, base = build_volatility_problem(context.inputs, CostTreatment.GROSS, factor, 0.15)
    assert extended.problem.problem_class is ProblemClass.SOCP
    assert len(extended.problem.cones) == 1  # type: ignore[attr-defined]
    cone = extended.problem.cones[0]  # type: ignore[attr-defined]
    assert cone.c == pytest.approx(0.15) and not cone.a.any()  # ‖Lᵀw‖ <= 0,15
    assert (
        base.problem.n_variables == extended.problem.n_variables
    )  # GROSS: sin variables auxiliares
    with_utility, _ = build_volatility_problem(
        context.inputs, CostTreatment.GROSS, factor, 0.15, risk_aversion=4.0
    )
    assert (
        with_utility.problem.P.nnz > 0 and with_utility.problem.problem_class is ProblemClass.SOCP
    )


def test_a_limit_below_the_minimum_variance_portfolio_is_infeasible_before_the_solver() -> None:
    """FEA-005: ``σ_min > límite`` ⇒ INFEASIBLE con causa registrada y sin llamar a Clarabel."""
    problem = four_asset_problem(CONFIG, max_weight=0.3)
    result = StrategyOptimizer(CONFIG).volatility_target(
        problem, CostTreatment.GROSS, volatility_limit=0.09
    )
    assert result.status is SolverStatus.INFEASIBLE
    assert result.status_source is StatusSource.PRE_SOLVER_CHECK
    assert result.solve is None and result.weights is None
    assert result.notes and "VOLATILITY_LIMIT" in result.notes[0]


def test_the_deterministic_feasibility_rules() -> None:
    bound = volatility_lower_bound(SIGMA4, 1.0)
    expected = 1.0 / np.sqrt(np.ones(4) @ np.linalg.solve(SIGMA4, np.ones(4)))
    assert bound == pytest.approx(float(expected))
    tolerance = CONFIG.solver.constraint_tolerance
    assert check_volatility(SIGMA4, 1.0, bound * 0.9, tolerance)[0].code == (
        "VOLATILITY_LIMIT_BELOW_DETERMINISTIC_BOUND"
    )
    assert check_volatility(SIGMA4, 1.0, bound * 1.1, tolerance) == ()
    assert check_volatility(SIGMA4, 1.0, -0.1, tolerance)[0].code == "VOLATILITY_LIMIT_INVALID"
    assert (
        check_volatility(SIGMA4, 1.0, float("nan"), tolerance)[0].code == "VOLATILITY_LIMIT_INVALID"
    )
    singular = np.array([[0.04, 0.04], [0.04, 0.04]])
    assert volatility_lower_bound(singular, 1.0) == 0.0  # dirección sin riesgo: cota trivial


def test_the_portfolio_volatility_limit_is_used_when_no_argument_is_given() -> None:
    """``PortfolioSpec.volatility_limit`` es la fuente por defecto del límite (DAT-011, CON-004)."""
    problem = four_asset_problem(CONFIG, spec=spec_with(volatility_limit=0.13))
    result = StrategyOptimizer(CONFIG).volatility_target(problem, CostTreatment.GROSS)
    assert result.metrics is not None and result.metrics.volatility == pytest.approx(0.13, abs=1e-6)
    explicit = StrategyOptimizer(CONFIG).volatility_target(
        problem, CostTreatment.GROSS, volatility_limit=0.15
    )
    assert explicit.metrics is not None and explicit.metrics.volatility == pytest.approx(
        0.15, abs=1e-6
    )
    with pytest.raises(UnsupportedCombinationError, match="VolatilityLimit no configurado"):
        StrategyOptimizer(CONFIG).volatility_target(four_asset_problem(CONFIG), CostTreatment.GROSS)
    with pytest.raises(UnsupportedCombinationError, match="finito y > 0"):
        StrategyOptimizer(CONFIG).volatility_target(
            four_asset_problem(CONFIG), CostTreatment.GROSS, volatility_limit=-1.0
        )


def test_net_treatment_places_transaction_costs_inside_the_optimization() -> None:
    holdings = [0.7, 0.1, 0.1, 0.1]
    problem = four_asset_problem(
        CONFIG,
        current=holdings,
        universe_overrides={"BuyCost": [300.0] * 4, "SellCost": [400.0] * 4},
    )
    optimizer = StrategyOptimizer(CONFIG)
    net = optimizer.volatility_target(problem, CostTreatment.NET, volatility_limit=0.14)
    gross = optimizer.volatility_target(problem, CostTreatment.GROSS, volatility_limit=0.14)
    assert net.is_valid_solution and gross.is_valid_solution
    assert net.weights is not None and gross.weights is not None
    context, _ = optimizer.prepare(problem, CostTreatment.NET)
    assert context is not None
    net_of_net = optimizer.treatment_return(context, net.weights, CostTreatment.NET)
    net_of_gross = optimizer.treatment_return(context, gross.weights, CostTreatment.NET)
    assert net_of_net >= net_of_gross - 1e-9  # optimizar los costes dentro nunca es peor ex post
    assert net_of_net > net_of_gross + 1e-6  # y aquí es estrictamente mejor
    assert net.metrics is not None and net.metrics.volatility <= 0.14 + 1e-7


def test_utility_with_a_volatility_cap_reduces_to_the_block_2_utility_when_the_cap_is_slack() -> (
    None
):
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    optimizer = StrategyOptimizer(CONFIG)
    capped = optimizer.volatility_target(
        problem, CostTreatment.GROSS, volatility_limit=0.5, risk_aversion=4.0
    )
    session = ContinuousFrontierEngine(CONFIG).open_session(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    reference = session.solve_risk_aversion(1.0 / 4.0, strategy=StrategyID.FRONTIER_POINT)
    assert capped.weights is not None and reference.weights is not None
    np.testing.assert_allclose(capped.weights, reference.weights, atol=1e-5)


def test_singular_covariance_admits_a_volatility_constraint() -> None:
    sigma = cov_from_vol_corr(
        [0.15, 0.15, 0.25],
        np.array([[1.0, 1.0, 0.2], [1.0, 1.0, 0.2], [0.2, 0.2, 1.0]]),
    )
    mu = np.array([0.08, 0.09, 0.12])
    problem = make_problem(
        mu, sigma, [1 / 3] * 3, CONFIG, universe_overrides={"MaxWeight": [1.0] * 3}
    )
    result = StrategyOptimizer(CONFIG).volatility_target(
        problem, CostTreatment.GROSS, volatility_limit=0.16
    )
    assert result.is_valid_solution and result.metrics is not None
    assert result.metrics.volatility <= 0.16 + 1e-7


def test_the_validator_rejects_a_solution_above_the_limit() -> None:
    """VAL-003: la comprobación de volatilidad se recalcula desde los pesos."""
    problem = four_asset_problem(CONFIG)
    optimizer = StrategyOptimizer(CONFIG)
    context, _ = optimizer.prepare(problem, CostTreatment.GROSS)
    assert context is not None
    validator = AdvancedSolutionValidator(ValidationTolerances.from_config(CONFIG.solver))
    weights = np.array([0.1, 0.2, 0.6, 0.1])  # volatilidad ≈ 0,19
    vol = float(np.sqrt(weights @ SIGMA4 @ weights))
    check = AdvancedChecks(volatility=(VolatilityLimitCheck(SIGMA4, 0.12, "portfolio"),))
    report = validator.validate(
        weights,
        context.compiled,
        ValidationContext(context.inputs.mu, context.inputs.sigma, None),
        check,
    )
    assert vol > 0.12 and not report.is_valid
    assert report.violations[0].constraint_id == "VOLATILITY_LIMIT:portfolio"
    assert report.violations[0].violation == pytest.approx(vol - 0.12)
    ok = validator.validate(
        weights,
        context.compiled,
        ValidationContext(context.inputs.mu, context.inputs.sigma, None),
        AdvancedChecks(volatility=(VolatilityLimitCheck(SIGMA4, vol + 0.01, "portfolio"),)),
    )
    assert ok.is_valid


def test_original_constraints_stay_in_force_under_the_volatility_limit() -> None:
    """La formulación conserva E-09/E-10/bounds/turnover: cualquier cota activa se respeta."""
    problem = four_asset_problem(CONFIG, max_weight=0.35, spec=spec_with(max_turnover=0.2))
    result = StrategyOptimizer(CONFIG).volatility_target(
        problem, CostTreatment.GROSS, volatility_limit=0.2
    )
    assert result.is_valid_solution and result.weights is not None
    assert float(result.weights.max()) <= 0.35 + 1e-7
    assert 0.5 * np.abs(result.weights - 0.25).sum() <= 0.2 + 1e-7
    assert dataclasses.is_dataclass(result) and result.composition_id


def test_qp_frontiers_reject_a_declared_volatility_limit_instead_of_ignoring_it() -> None:
    """MASTER_SPEC §79: la frontera QP no impone conos; un ``VolatilityLimit`` no se ignora."""
    from portfolio_engine.exceptions import FrontierError
    from portfolio_engine.frontiers import GlobalCandidateFrontierEngine

    problem = four_asset_problem(CONFIG, spec=spec_with(volatility_limit=0.13))
    engine = ContinuousFrontierEngine(CONFIG)
    with pytest.raises(FrontierError, match="VolatilityLimit"):
        engine.solve(problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)
    with pytest.raises(FrontierError, match="VolatilityLimit"):
        engine.open_session(problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)
    with pytest.raises(FrontierError, match="VolatilityLimit"):
        GlobalCandidateFrontierEngine(CONFIG).solve(
            problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
        )
    # sin límite la frontera sigue funcionando y la estrategia cónica sí lo impone
    free = four_asset_problem(CONFIG)
    assert engine.solve(free, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID).points
