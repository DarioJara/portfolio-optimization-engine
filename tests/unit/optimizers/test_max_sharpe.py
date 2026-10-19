"""OPT-009, SOL-005: Maximum Sharpe por Charnes-Cooper (SOCP), contrastado con oráculos
independientes.

Oráculos: fórmula cerrada de la cartera tangente; búsqueda cuasiconvexa sobre la frontera de
retorno objetivo del Bloque 2 (bisección por sección áurea); Sharpe de todos los puntos de la
frontera; SLSQP directo. Ninguno usa la transformación de Charnes-Cooper.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.optimize import minimize

from portfolio_engine.frontiers import ContinuousFrontierEngine, StrategyOptimizer
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    OptimalityClaim,
    RestrictedExistingPositionPolicy,
    SharpeOutcome,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.optimizers.formulations.conic import factor_covariance
from portfolio_engine.optimizers.formulations.sharpe import build_maximum_sharpe_problem
from portfolio_engine.validation.advanced_validator import (
    AdvancedChecks,
    AdvancedSolutionValidator,
    SharpeCheck,
)
from portfolio_engine.validation.solution_validator import ValidationContext
from portfolio_engine.validation.tolerances import ValidationTolerances
from tests.fixtures.block4 import (
    CORR4,
    MU4,
    VOL4,
    four_asset_problem,
    sharpe_by_target_return_search,
)
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    make_problem,
    restricted_universe,
    spec_with,
)

pytestmark = pytest.mark.unit

CONFIG = base_config()
RF = CONFIG.returns.risk_free_rate
SIGMA4 = cov_from_vol_corr(VOL4, CORR4)


def _sharpe(weights: np.ndarray, mu: np.ndarray, sigma: np.ndarray, rf: float = RF) -> float:
    return float((mu @ weights - rf) / np.sqrt(weights @ sigma @ weights))


def test_the_tangency_portfolio_has_a_closed_form_when_no_bound_binds() -> None:
    """Sin cotas activas el óptimo es ``w ∝ Σ⁻¹(μ − rf)`` (fórmula cerrada de la tangente)."""
    problem = four_asset_problem(CONFIG)
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    z = np.linalg.solve(SIGMA4, MU4 - RF)
    tangent = z / z.sum()
    assert np.all(tangent > 0)  # la cartera tangente es long-only: ninguna cota es activa
    assert result.is_valid_solution and result.weights is not None
    np.testing.assert_allclose(result.weights, tangent, atol=1e-5)
    assert result.extra("sharpe") == pytest.approx(_sharpe(tangent, MU4, SIGMA4), abs=1e-8)
    assert result.extra("implied_sharpe") == pytest.approx(result.extra("sharpe"), rel=1e-5)
    assert result.outcome == SharpeOutcome.OPTIMAL.value


def test_the_result_is_routed_to_clarabel_and_reports_solver_diagnostics() -> None:
    result = StrategyOptimizer(CONFIG).max_sharpe(four_asset_problem(CONFIG), CostTreatment.GROSS)
    assert result.solver_names == ("CLARABEL",)
    solve = result.solve
    assert solve is not None and solve.status is SolverStatus.OPTIMAL
    assert solve.iterations > 0 and solve.solve_time >= 0.0
    assert solve.primal_residual is not None and solve.dual_residual is not None
    assert result.optimality_claim is OptimalityClaim.CONVEX_GLOBAL
    assert result.strategy_id is StrategyID.MAX_SHARPE and result.scenario_id == "BASE"
    assert result.validation is not None and "SHARPE" in result.validation.checks


@pytest.mark.parametrize("cap", [0.35, 0.40])
def test_it_matches_the_quasiconvex_search_with_binding_bounds(cap: float) -> None:
    """Con MaxWeight activo el óptimo coincide con la búsqueda cuasiconvexa del Bloque 2."""
    problem = four_asset_problem(CONFIG, max_weight=cap)
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    oracle_value, oracle_weights = sharpe_by_target_return_search(
        problem, CONFIG, CostTreatment.GROSS
    )
    assert result.weights is not None and result.is_valid_solution
    assert float(result.weights.max()) == pytest.approx(cap, abs=1e-6)  # la cota está activa
    assert result.extra("sharpe") == pytest.approx(oracle_value, abs=1e-6)
    np.testing.assert_allclose(result.weights, oracle_weights, atol=5e-4)


def test_the_max_sharpe_is_at_least_the_sharpe_of_every_frontier_point() -> None:
    """Contrato de aceptación: ningún punto de la frontera continua supera el máximo Sharpe."""
    problem = four_asset_problem(CONFIG, max_weight=0.5)
    engine = ContinuousFrontierEngine(CONFIG)
    frontier = engine.solve(problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID)
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    sharpes = [
        p.metrics.sharpe_ratio
        for p in frontier.points
        if p.is_valid_solution and p.metrics is not None and p.metrics.sharpe_ratio is not None
    ]
    assert len(sharpes) >= 10
    best = result.extra("sharpe")
    assert best is not None and best >= max(sharpes) - 1e-7


def test_slsqp_maximization_of_the_ratio_agrees() -> None:
    """Un tercer oráculo: SLSQP sobre el cociente con cotas, desde varios puntos iniciales."""
    problem = four_asset_problem(CONFIG, max_weight=0.4)
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    best = -np.inf
    for seed in range(5):
        start = np.random.default_rng(seed).dirichlet(np.ones(4))
        solved = minimize(
            lambda w: -_sharpe(w, MU4, SIGMA4),
            start,
            bounds=[(0.0, 0.4)] * 4,
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
            method="SLSQP",
            options={"ftol": 1e-14, "maxiter": 500},
        )
        if solved.success:
            best = max(best, -float(solved.fun))
    assert result.extra("sharpe") == pytest.approx(best, abs=1e-7)


def test_net_sharpe_includes_transaction_costs_in_the_optimization() -> None:
    """``NET`` optimiza el Sharpe neto (costes dentro), no el bruto menos los costes ex post."""
    holdings = [0.7, 0.1, 0.1, 0.1]
    problem = four_asset_problem(
        CONFIG,
        current=holdings,
        universe_overrides={"BuyCost": [400.0] * 4, "SellCost": [500.0] * 4},
    )
    optimizer = StrategyOptimizer(CONFIG)
    net = optimizer.max_sharpe(problem, CostTreatment.NET)
    gross = optimizer.max_sharpe(problem, CostTreatment.GROSS)
    assert net.is_valid_solution and gross.is_valid_solution
    assert net.weights is not None and gross.weights is not None
    assert not np.allclose(net.weights, gross.weights, atol=1e-3)
    oracle_value, oracle_weights = sharpe_by_target_return_search(
        problem, CONFIG, CostTreatment.NET
    )
    net_sharpe = net.extra("sharpe")
    assert net_sharpe == pytest.approx(oracle_value, abs=1e-6)
    np.testing.assert_allclose(net.weights, oracle_weights, atol=5e-4)
    # el NET conserva más de la cartera actual (los costes desincentivan operar)
    assert np.abs(net.weights - holdings).sum() < np.abs(gross.weights - holdings).sum()
    # y su Sharpe neto supera al de la cartera bruta evaluada tras costes (post-coste)
    gross_context, _ = optimizer.prepare(problem, CostTreatment.NET)
    assert gross_context is not None
    post_cost = (
        optimizer.treatment_return(gross_context, gross.weights, CostTreatment.NET) - RF
    ) / np.sqrt(gross.weights @ SIGMA4 @ gross.weights)
    assert net_sharpe is not None and net_sharpe >= post_cost - 1e-9


def test_turnover_limit_and_group_constraints_are_respected_and_match_the_oracle() -> None:
    from portfolio_engine.config import GroupLimit
    from portfolio_engine.models.enums import GroupDimension
    from tests.fixtures.problems import with_group_limits

    config = with_group_limits(CONFIG, [GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.4)])
    # límite de grupo activo (Tech = A000 + A002 <= 0,4) y turnover holgado
    grouped = four_asset_problem(config, spec=spec_with(max_turnover=0.5))
    result = StrategyOptimizer(config).max_sharpe(grouped, CostTreatment.GROSS)
    assert result.is_valid_solution and result.weights is not None
    assert result.weights[[0, 2]].sum() == pytest.approx(0.4, abs=1e-6)  # el grupo está activo
    oracle_value, _ = sharpe_by_target_return_search(grouped, config, CostTreatment.GROSS)
    assert result.extra("sharpe") == pytest.approx(oracle_value, abs=1e-6)
    # turnover activo (0,05 < el necesario para llegar a la tangente)
    tight = four_asset_problem(CONFIG, spec=spec_with(max_turnover=0.05))
    limited = StrategyOptimizer(CONFIG).max_sharpe(tight, CostTreatment.GROSS)
    assert limited.is_valid_solution and limited.weights is not None
    assert 0.5 * np.abs(limited.weights - 0.25).sum() == pytest.approx(0.05, abs=1e-6)
    oracle_value, _ = sharpe_by_target_return_search(tight, CONFIG, CostTreatment.GROSS)
    assert limited.extra("sharpe") == pytest.approx(oracle_value, abs=1e-6)


def test_liquidated_assets_enter_the_costs_of_the_homogeneous_problem() -> None:
    """Composición que excluye un activo actual: su liquidación completa es coste y turnover."""
    problem = dataclasses.replace(
        four_asset_problem(
            CONFIG,
            current=[0.25, 0.25, 0.25, 0.25],
            universe_overrides={"BuyCost": [80.0] * 4, "SellCost": [120.0] * 4},
        ),
        composition_asset_ids=("A000", "A001", "A002"),
    )
    optimizer = StrategyOptimizer(CONFIG)
    result = optimizer.max_sharpe(problem, CostTreatment.NET)
    assert result.is_valid_solution and result.asset_ids == ("A000", "A001", "A002")
    oracle_value, oracle_weights = sharpe_by_target_return_search(
        problem, CONFIG, CostTreatment.NET
    )
    assert result.extra("sharpe") == pytest.approx(oracle_value, abs=1e-6)
    assert result.weights is not None
    np.testing.assert_allclose(result.weights, oracle_weights, atol=5e-4)


def test_no_positive_excess_return_is_not_applicable_and_no_sharpe_is_invented() -> None:
    """A-13: si ``max (μ − rf)ᵀw <= 0`` el problema es NOT_APPLICABLE (con motivo)."""
    config = base_config(returns={"risk_free_rate": 0.5})
    result = StrategyOptimizer(config).max_sharpe(four_asset_problem(config), CostTreatment.GROSS)
    assert result.outcome == SharpeOutcome.NOT_APPLICABLE.value
    assert result.weights is None and not result.is_valid_solution
    assert result.status_source is StatusSource.PRE_SOLVER_CHECK
    assert (
        result.extra("sharpe") is None and result.optimality_claim is OptimalityClaim.NOT_ASSESSED
    )
    assert result.notes and result.notes[0].startswith("MAX_ACHIEVABLE_EXCESS_RETURN")
    assert result.solver_names == ("HiGHS",)  # solo el LP de aplicabilidad; ningún SOCP


def test_a_maximum_excess_return_of_exactly_zero_is_not_applicable() -> None:
    config = base_config(returns={"risk_free_rate": 0.12})  # = max μ
    result = StrategyOptimizer(config).max_sharpe(four_asset_problem(config), CostTreatment.GROSS)
    assert result.outcome == SharpeOutcome.NOT_APPLICABLE.value and result.weights is None


def test_incompatible_constraints_are_infeasible_and_not_confused_with_not_applicable() -> None:
    """Sin ningún ``w`` factible el veredicto es INFEASIBLE, no NOT_APPLICABLE."""
    problem = four_asset_problem(CONFIG, max_weight=0.2)  # 4 × 0,2 < 1
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.status_source is StatusSource.PRE_SOLVER_CHECK
    assert result.outcome is None and result.weights is None and result.notes


def test_a_zero_volatility_portfolio_with_positive_excess_is_reported_as_unbounded() -> None:
    """Σ singular con un activo sin riesgo y ``μ > rf``: Sharpe no acotado, no un número falso."""
    sigma = np.diag([0.04, 0.09, 0.0])
    mu = np.array([0.08, 0.10, 0.05])
    problem = make_problem(
        mu, sigma, [0.3, 0.3, 0.4], CONFIG, universe_overrides={"MaxWeight": [1.0] * 3}
    )
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    assert result.outcome == SharpeOutcome.UNBOUNDED_ZERO_VOLATILITY.value
    assert result.extra("sharpe") is None
    assert "ZERO_VOLATILITY_POSITIVE_EXCESS_RETURN" in result.notes
    assert result.weights is not None and result.weights[2] == pytest.approx(1.0, abs=1e-6)


def test_singular_covariance_with_a_risky_frontier_still_solves() -> None:
    """Σ singular (activo duplicado): la representación cónica funciona donde Cholesky fallaría."""
    vols = np.array([0.15, 0.15, 0.25, 0.10])
    corr = np.array([[1, 1, 0.2, 0.1], [1, 1, 0.2, 0.1], [0.2, 0.2, 1, 0.3], [0.1, 0.1, 0.3, 1.0]])
    sigma = cov_from_vol_corr(vols, corr)
    assert np.linalg.matrix_rank(sigma) == 3
    mu = np.array([0.08, 0.08, 0.12, 0.06])
    problem = make_problem(
        mu, sigma, [0.25] * 4, CONFIG, universe_overrides={"MaxWeight": [1.0] * 4}
    )
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    assert result.is_valid_solution and result.weights is not None
    oracle_value, _ = sharpe_by_target_return_search(problem, CONFIG, CostTreatment.GROSS)
    assert result.extra("sharpe") == pytest.approx(oracle_value, abs=1e-5)


def test_a_volatility_limit_caps_the_sharpe_portfolio() -> None:
    problem = four_asset_problem(CONFIG)
    optimizer = StrategyOptimizer(CONFIG)
    free = optimizer.max_sharpe(problem, CostTreatment.GROSS)
    session = ContinuousFrontierEngine(CONFIG).open_session(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    minimum = session.solve_minimum_variance().metrics
    assert free.metrics is not None and minimum is not None
    limit = 0.5 * (minimum.volatility + free.metrics.volatility)  # entre la mínima y la tangente
    tight = optimizer.max_sharpe(problem, CostTreatment.GROSS, volatility_limit=limit)
    assert tight.metrics is not None
    assert tight.is_valid_solution and tight.metrics.volatility == pytest.approx(limit, abs=1e-6)
    assert tight.extra("sharpe") < free.extra("sharpe")  # type: ignore[operator]
    assert tight.validation is not None and "VOLATILITY_LIMIT" in tight.validation.checks
    # un límite por encima de la volatilidad de la tangente no altera la solución
    loose = optimizer.max_sharpe(problem, CostTreatment.GROSS, volatility_limit=0.5)
    assert loose.extra("sharpe") == pytest.approx(free.extra("sharpe"), abs=1e-8)
    # FEA-005, regla determinista: por debajo de B/√(1ᵀΣ⁻¹1) ninguna cartera puede cumplirlo
    impossible = optimizer.max_sharpe(problem, CostTreatment.GROSS, volatility_limit=0.02)
    assert impossible.status is SolverStatus.INFEASIBLE
    assert impossible.status_source is StatusSource.PRE_SOLVER_CHECK
    assert impossible.notes and "BELOW_DETERMINISTIC_BOUND" in impossible.notes[0]
    # FEA-005, certificado de MinVariance: con cotas activas la mínima volatilidad real es mayor
    # que la cota determinista, y un límite entre ambas solo lo detecta el certificado
    capped = four_asset_problem(CONFIG, max_weight=0.3)
    capped_session = ContinuousFrontierEngine(CONFIG).open_session(
        capped, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    constrained_minimum = capped_session.solve_minimum_variance().metrics
    assert constrained_minimum is not None
    deterministic = float(1.0 / np.sqrt(np.ones(4) @ np.linalg.solve(SIGMA4, np.ones(4))))
    assert deterministic < constrained_minimum.volatility - 1e-4
    between = 0.5 * (deterministic + constrained_minimum.volatility)
    certified = StrategyOptimizer(CONFIG).max_sharpe(
        capped, CostTreatment.GROSS, volatility_limit=between
    )
    assert certified.status is SolverStatus.INFEASIBLE
    assert certified.notes and "VOLATILITY_LIMIT_BELOW_MINIMUM_VARIANCE" in certified.notes[0]


def test_restricted_and_non_buyable_positions_are_preserved_by_max_sharpe() -> None:
    """E-09/E-10: el activo restringido en cartera no puede crecer; se contrasta con el oráculo."""
    problem = make_problem(
        MU4,
        SIGMA4,
        [0.25] * 4,
        CONFIG,
        universe_overrides={
            "MaxWeight": [1.0] * 4,
            **restricted_universe(4, [2]),  # A002 (el de mayor retorno) restringido
        },
    )
    result = StrategyOptimizer(CONFIG).max_sharpe(problem, CostTreatment.GROSS)
    assert CONFIG.constraints.restricted_existing_position_policy is (
        RestrictedExistingPositionPolicy.HOLD_OR_REDUCE
    )
    assert result.is_valid_solution and result.weights is not None
    assert result.weights[2] <= 0.25 + 1e-7  # no puede crecer
    oracle_value, _ = sharpe_by_target_return_search(problem, CONFIG, CostTreatment.GROSS)
    assert result.extra("sharpe") == pytest.approx(oracle_value, abs=1e-6)


def test_an_inaccurate_solver_state_is_never_promoted_to_a_valid_solution() -> None:
    optimizer = StrategyOptimizer(CONFIG)
    real = optimizer.solve_problem

    def degraded(problem: object) -> object:
        result = real(problem)  # type: ignore[arg-type]
        return dataclasses.replace(result, status=SolverStatus.OPTIMAL_INACCURATE)

    optimizer.solve_problem = degraded  # type: ignore[method-assign]
    result = optimizer.max_sharpe(four_asset_problem(CONFIG), CostTreatment.GROSS)
    assert result.status is SolverStatus.OPTIMAL_INACCURATE
    assert not result.is_valid_solution and result.optimality_claim is OptimalityClaim.NOT_ASSESSED
    assert result.validation is not None and result.validation.is_valid  # los pesos sí cumplen
    assert not CONFIG.solver.accept_inaccurate_solutions


def test_the_validator_rejects_a_tampered_sharpe_solution() -> None:
    """VAL: el validador recalcula el Sharpe y el exceso; no confía en lo que diga el solver."""
    validator = AdvancedSolutionValidator(ValidationTolerances.from_config(CONFIG.solver))
    problem = four_asset_problem(CONFIG)
    optimizer = StrategyOptimizer(CONFIG)
    context, _ = optimizer.prepare(problem, CostTreatment.GROSS)
    assert context is not None
    check = SharpeCheck(
        RF,
        CostTreatment.GROSS,
        CONFIG.sharpe.min_excess_return,
        CONFIG.sharpe.agreement_tolerance,
        claimed_sharpe=5.0,
        zero_volatility_tolerance=CONFIG.frontier.zero_volatility_tolerance,
    )
    weights = np.array([0.4, 0.3, 0.2, 0.1])
    validation_context = ValidationContext(context.inputs.mu, context.inputs.sigma, None)
    report = validator.validate(
        weights, context.compiled, validation_context, AdvancedChecks(sharpe=check)
    )
    assert not report.is_valid
    assert any("consistent_ratio" in v.constraint_id for v in report.violations)
    negative = SharpeCheck(0.5, CostTreatment.GROSS, 1e-8, 1e-5, None, 1e-12)
    report = validator.validate(
        weights, context.compiled, validation_context, AdvancedChecks(sharpe=negative)
    )
    assert any("positive_excess" in v.constraint_id for v in report.violations)


def test_the_homogeneous_problem_is_a_true_socp_with_the_documented_layout() -> None:
    """Estructura: ``x = [y; κ; r]`` (GROSS sin lifting) y conos con ``κ`` y ``r`` bien situados."""
    problem = four_asset_problem(CONFIG)
    context, _ = StrategyOptimizer(CONFIG).prepare(problem, CostTreatment.GROSS)
    assert context is not None
    factor = factor_covariance(context.inputs.sigma, CONFIG.conic)
    built = build_maximum_sharpe_problem(context.inputs, CostTreatment.GROSS, factor, RF)
    assert built.problem.n_variables == 4 + 1 + 1
    assert built.kappa_index == 4 and built.r_index == 5 and not built.net
    assert built.problem.problem_class.value == "SOCP" and len(built.problem.cones) == 1
    assert built.problem.q.tolist() == [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]  # min r
    limited = build_maximum_sharpe_problem(
        context.inputs, CostTreatment.GROSS, factor, RF, volatility_limit=0.2
    )
    assert len(limited.problem.cones) == 2
    homogeneous_cone = limited.problem.cones[1]
    assert homogeneous_cone.a[limited.kappa_index] == pytest.approx(0.2)  # σ_max·κ
    assert homogeneous_cone.c == 0.0
    net_context, _ = StrategyOptimizer(CONFIG).prepare(problem, CostTreatment.NET)
    assert net_context is not None
    net_problem = build_maximum_sharpe_problem(net_context.inputs, CostTreatment.NET, factor, RF)
    assert net_problem.problem.n_variables == 3 * 4 + 2 and net_problem.net


def test_optimal_is_never_claimed_without_an_accepted_status_and_a_passing_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUDIT_BLOCK_4 F-03: sin estado aceptable el veredicto es un fallo, no ``OPTIMAL``."""
    optimizer = StrategyOptimizer(CONFIG)
    problem = four_asset_problem(CONFIG)
    sound = optimizer.max_sharpe(problem, CostTreatment.GROSS)
    assert sound.outcome == SharpeOutcome.OPTIMAL.value and sound.is_valid_solution
    monkeypatch.setattr(StrategyOptimizer, "accepts", lambda self, status: False)
    result = optimizer.max_sharpe(problem, CostTreatment.GROSS)
    assert not result.is_valid_solution
    assert result.outcome == SharpeOutcome.SOLVER_FAILURE.value
    assert "SHARPE_SOLUTION_NOT_VALIDATED" in result.notes
    assert result.optimality_claim is OptimalityClaim.NOT_ASSESSED
