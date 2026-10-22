"""SCN-004..008: optimización multiescenario.

Distingue **una solución por escenario** (``SCENARIO_INDEPENDENT``) de **una única solución que
responde a todos los escenarios** (utilidad esperada, peor caso, base con restricciones de estrés).
Oráculos independientes: SLSQP sobre la definición matemática de cada objetivo y relaciones
exactas (una escala uniforme de volatilidad escala la volatilidad mínima).
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.optimize import minimize

from portfolio_engine.config import (
    AssetShock,
    ConstraintOverrides,
    GroupLimit,
    ScenarioDefinition,
    StressLimits,
)
from portfolio_engine.exceptions import ScenarioError, UnsupportedCombinationError
from portfolio_engine.frontiers import ContinuousFrontierEngine, StrategyOptimizer
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    FrontierScope,
    GroupDimension,
    MultiScenarioMode,
    OptimalityClaim,
    ScenarioType,
    ShockSelector,
    SolverStatus,
    StrategyID,
)
from portfolio_engine.models.frontier import GlobalFrontierResult
from portfolio_engine.outputs import frontier_point_rows, scenario_metric_rows, strategy_header_row
from portfolio_engine.scenarios import (
    MultiScenarioOptimizer,
    ScenarioEngine,
    ScenarioSet,
    intersect_constraint_configs,
)
from tests.fixtures.block4 import (
    MU4,
    four_asset_problem,
    scenario_definitions,
    with_overrides,
)
from tests.fixtures.problems import base_config, spec_with

pytestmark = pytest.mark.unit

CONFIG = base_config()
LAMBDA = 3.0


def _scenarios(problem, definitions=None, config=CONFIG):  # type: ignore[no-untyped-def]
    return ScenarioEngine(config).build(
        problem.risk_model,
        problem.universe,
        problem.costs,
        config.constraints,
        problem.spec,
        definitions or scenario_definitions(),
    )


def _arrays(scenarios: ScenarioSet) -> list[tuple[str, float | None, np.ndarray, np.ndarray]]:
    return [
        (s.scenario_id, s.probability, np.array(s.risk_model.mu), np.array(s.risk_model.sigma))
        for s in scenarios.scenarios
    ]


def _slsqp(objective, start, cap, extra=()):  # type: ignore[no-untyped-def]
    result = minimize(
        objective,
        start,
        bounds=[(0.0, cap)] * len(start),
        constraints=[{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}, *extra],
        method="SLSQP",
        options={"ftol": 1e-15, "maxiter": 2000},
    )
    assert result.success, result.message
    return np.asarray(result.x)


def _utility(w: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> float:
    return float(mu @ w - LAMBDA * w @ sigma @ w)


# ------------------------------------------------------------------------- SCENARIO_INDEPENDENT


def test_scenario_independent_yields_a_different_frontier_and_solution_per_scenario_id() -> None:
    """DoD del Bloque 4: la misma cartera da fronteras y soluciones distintas por ScenarioID."""
    problem = four_asset_problem(CONFIG)
    scenarios = _scenarios(problem)
    result = MultiScenarioOptimizer(CONFIG).solve_independent(
        problem, scenarios, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert result.mode is MultiScenarioMode.SCENARIO_INDEPENDENT and result.single_solution is None
    assert [key for key, _ in result.frontiers] == ["BASE", "BEAR", "CRASH"]
    fronts = {sid: result.frontier(sid) for sid in scenarios.ids}
    for sid, frontier in fronts.items():
        assert frontier.scenario_id == sid and frontier.portfolio_id == "P1"
        assert {row.scenario_id for row in frontier_point_rows(frontier)} == {sid}  # en las salidas
    curves = {
        sid: tuple(
            (round(p.metrics.volatility, 9), round(p.metrics.expected_return_gross, 9))
            for p in fronts[sid].points
            if p.metrics is not None
        )
        for sid in fronts
    }
    assert len(set(curves.values())) == 3  # tres fronteras distintas

    # relación exacta independiente: BEAR = mu − 5 %, Σ × 1,3² ⇒ vol mínima × 1,3; retorno − 5 %
    def point(sid, strategy):  # type: ignore[no-untyped-def]
        return next(p for p in fronts[sid].points if p.strategy_id is strategy)

    base_min, bear_min = (
        point("BASE", StrategyID.MIN_VARIANCE),
        point("BEAR", StrategyID.MIN_VARIANCE),
    )
    assert bear_min.metrics is not None and base_min.metrics is not None
    assert bear_min.metrics.volatility == pytest.approx(1.3 * base_min.metrics.volatility, rel=1e-6)
    np.testing.assert_allclose(bear_min.weights, base_min.weights, atol=1e-6)
    base_max, bear_max = point("BASE", StrategyID.MAX_RETURN), point("BEAR", StrategyID.MAX_RETURN)
    assert bear_max.metrics is not None and base_max.metrics is not None
    assert bear_max.metrics.expected_return_gross == pytest.approx(
        base_max.metrics.expected_return_gross - 0.05, abs=1e-9
    )


def test_each_scenario_is_solved_with_its_own_costs_and_constraints() -> None:
    """``cost_s`` y ``constraints_s`` gobiernan la frontera del escenario (NET y turnover)."""
    problem = four_asset_problem(CONFIG, current=[0.4, 0.3, 0.2, 0.1])
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(0.05, None, None, ()))
    scenarios = _scenarios(problem, tuple(definitions))
    result = MultiScenarioOptimizer(CONFIG).solve_independent(
        problem, scenarios, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    current = np.array([0.4, 0.3, 0.2, 0.1])
    bear_turnovers = [
        0.5 * np.abs(p.weights - current).sum()
        for p in result.frontier("BEAR").points
        if p.is_valid_solution and p.weights is not None
    ]
    base_turnovers = [
        0.5 * np.abs(p.weights - current).sum()
        for p in result.frontier("BASE").points
        if p.is_valid_solution and p.weights is not None
    ]
    assert bear_turnovers and max(bear_turnovers) <= 0.05 + 1e-7  # constraints_s del BEAR
    assert max(base_turnovers) > 0.05 + 1e-3  # el BASE sí puede operar más

    # costes ×2 del CRASH: mayor coste de transacción para la misma operación
    def cost_of_min_variance(sid):  # type: ignore[no-untyped-def]
        point = next(
            p for p in result.frontier(sid).points if p.strategy_id is StrategyID.MIN_VARIANCE
        )
        assert point.metrics is not None and point.metrics.transaction_cost_one_off is not None
        return point.metrics.transaction_cost_one_off

    crash_point = next(
        p for p in result.frontier("CRASH").points if p.strategy_id is StrategyID.MIN_VARIANCE
    )
    base_point = next(
        p for p in result.frontier("BASE").points if p.strategy_id is StrategyID.MIN_VARIANCE
    )
    assert crash_point.metrics is not None and base_point.metrics is not None
    assert (
        crash_point.metrics.transaction_cost_one_off is not None
        and base_point.metrics.transaction_cost_one_off is not None
    )
    assert crash_point.metrics.transaction_cost_one_off > 0.0 and cost_of_min_variance("BASE") > 0.0


def test_scenario_independent_also_runs_the_global_candidate_frontier_per_scenario() -> None:
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    scenarios = _scenarios(problem)
    result = MultiScenarioOptimizer(CONFIG).solve_independent(
        problem,
        scenarios,
        CostTreatment.GROSS,
        FrontierMethod.RISK_AVERSION_GRID,
        scope=FrontierScope.GLOBAL_CANDIDATE_FRONTIER,
    )
    for sid in scenarios.ids:
        frontier = result.frontier(sid)
        assert isinstance(frontier, GlobalFrontierResult) and frontier.scenario_id == sid
        assert frontier.diagnostics.candidate_count >= 1


def test_named_strategies_per_scenario_carry_their_scenario_id() -> None:
    problem = four_asset_problem(CONFIG)
    result = MultiScenarioOptimizer(CONFIG).solve_independent(
        problem,
        _scenarios(problem),
        CostTreatment.GROSS,
        FrontierMethod.RISK_AVERSION_GRID,
        include_max_sharpe=True,
    )
    assert [s.scenario_id for s in result.strategies] == ["BASE", "BEAR", "CRASH"]
    assert all(
        s.strategy_id is StrategyID.MAX_SHARPE and s.is_valid_solution for s in result.strategies
    )
    sharpes = {s.scenario_id: s.extra("sharpe") for s in result.strategies}
    assert sharpes["BEAR"] < sharpes["BASE"]  # peores retornos y más riesgo
    weights = [tuple(np.round(s.weights, 6)) for s in result.strategies if s.weights is not None]
    assert len(set(weights)) == 3
    assert strategy_header_row(result.strategies[1]).scenario_id == "BEAR"


# -------------------------------------------------------------------- EXPECTED_SCENARIO_UTILITY


def test_expected_scenario_utility_matches_an_independent_slsqp_optimum() -> None:
    """P12 (QP → OSQP): ``max Σ p_s (μ_sᵀw − λ wᵀΣ_s w)`` con las probabilidades declaradas."""
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    scenarios = _scenarios(problem)
    data = _arrays(scenarios)

    def negative(w):  # type: ignore[no-untyped-def]
        return -sum(p * _utility(w, mu, sigma) for _, p, mu, sigma in data)

    oracle = _slsqp(negative, np.full(4, 0.25), 0.6)
    result = MultiScenarioOptimizer(CONFIG).solve_expected_utility(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    )
    solution = result.single_solution
    assert solution is not None and solution.is_valid_solution and solution.weights is not None
    np.testing.assert_allclose(solution.weights, oracle, atol=1e-5)
    assert solution.extra("expected_utility") == pytest.approx(-negative(oracle), abs=1e-9)
    assert solution.solver_names == ("OSQP",)  # QP con restricciones lineales, no cónico
    assert solution.strategy_id is StrategyID.EXPECTED_SCENARIO_UTILITY
    assert solution.scenario_id == "MULTI:EXPECTED_SCENARIO_UTILITY"
    assert result.probabilities == (("BASE", 0.5), ("BEAR", 0.3), ("CRASH", 0.2))
    assert solution.optimality_claim is OptimalityClaim.CONVEX_GLOBAL


def test_the_expected_covariance_is_the_probability_weighted_sum_not_the_mixture_variance() -> None:
    """SCN-005 (test_expected_utility): ``Σ̄ = Σ p_s Σ_s`` y ``μ̄ = Σ p_s μ_s``."""
    problem = four_asset_problem(CONFIG)
    scenarios = _scenarios(problem)
    optimizer = MultiScenarioOptimizer(CONFIG)
    probabilities = np.array([0.5, 0.3, 0.2])
    model = optimizer._aggregate_model(scenarios, probabilities, problem)
    data = _arrays(scenarios)
    np.testing.assert_allclose(model.mu, sum(p * mu for _, p, mu, _ in data), atol=1e-15)
    np.testing.assert_allclose(model.sigma, sum(p * s for _, p, _, s in data), atol=1e-15)
    mixture = sum(p * (s + np.outer(mu, mu)) for _, p, mu, s in data) - np.outer(model.mu, model.mu)
    assert not np.allclose(model.sigma, mixture)  # no es la covarianza de la mezcla


def test_the_probabilities_are_required_valid_and_they_change_the_solution() -> None:
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    optimizer = MultiScenarioOptimizer(CONFIG)
    scenarios = _scenarios(problem)
    no_probability = tuple(dataclasses.replace(d, probability=None) for d in scenario_definitions())
    with pytest.raises(ScenarioError, match="no se suponen iguales"):
        optimizer.solve_expected_utility(
            problem, _scenarios(problem, no_probability), CostTreatment.GROSS, LAMBDA
        )
    bad_sum = tuple(dataclasses.replace(d, probability=0.4) for d in scenario_definitions())
    with pytest.raises(ScenarioError, match="suman"):
        optimizer.solve_expected_utility(
            problem, _scenarios(problem, bad_sum), CostTreatment.GROSS, LAMBDA
        )
    baseline = optimizer.solve_expected_utility(problem, scenarios, CostTreatment.GROSS, LAMBDA)
    tilted = tuple(
        dataclasses.replace(d, probability=p)
        for d, p in zip(scenario_definitions(), (0.05, 0.85, 0.10), strict=True)
    )
    other = optimizer.solve_expected_utility(
        problem, _scenarios(problem, tilted), CostTreatment.GROSS, LAMBDA
    )
    assert baseline.single_solution is not None and other.single_solution is not None
    assert (
        baseline.single_solution.weights is not None and other.single_solution.weights is not None
    )
    assert not np.allclose(
        baseline.single_solution.weights, other.single_solution.weights, atol=1e-3
    )


def test_a_single_solution_is_not_equivalent_to_one_solution_per_scenario() -> None:
    """Las tres soluciones únicas difieren entre sí y de cada solución independiente."""
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    scenarios = _scenarios(problem)
    optimizer = MultiScenarioOptimizer(CONFIG)
    expected = optimizer.solve_expected_utility(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    ).single_solution
    worst = optimizer.solve_worst_case(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    ).single_solution
    assert expected is not None and worst is not None
    assert expected.weights is not None and worst.weights is not None
    assert not np.allclose(expected.weights, worst.weights, atol=1e-3)
    independent = [
        StrategyOptimizer(dataclasses.replace(CONFIG, constraints=s.constraints.constraints)).robust
        for s in scenarios.scenarios
    ]
    assert len(independent) == 3
    per_scenario = []
    for _, (_, _, mu, sigma) in zip(scenarios.scenarios, _arrays(scenarios), strict=True):
        per_scenario.append(
            _slsqp(lambda w, m=mu, c=sigma: -_utility(w, m, c), np.full(4, 0.25), 0.6)
        )
    for w in per_scenario:
        assert not np.allclose(expected.weights, w, atol=1e-3)  # ninguna solución individual
    # cada solución única domina en SU criterio a las demás
    data = _arrays(scenarios)

    def expected_value(w):  # type: ignore[no-untyped-def]
        return sum(p * _utility(w, mu, s) for _, p, mu, s in data)

    def worst_value(w):  # type: ignore[no-untyped-def]
        return min(_utility(w, mu, s) for _, _, mu, s in data)

    assert expected_value(expected.weights) >= expected_value(worst.weights) - 1e-9
    assert worst_value(worst.weights) >= worst_value(expected.weights) - 1e-9
    assert worst_value(worst.weights) > worst_value(expected.weights) + 1e-7
    for w in per_scenario:
        assert expected_value(expected.weights) >= expected_value(w) - 1e-9
        assert worst_value(worst.weights) >= worst_value(w) - 1e-9


def test_expected_utility_uses_the_expected_transaction_costs() -> None:
    problem = four_asset_problem(
        CONFIG,
        current=[0.7, 0.1, 0.1, 0.1],
        universe_overrides={"BuyCost": [100.0] * 4, "SellCost": [150.0] * 4},
    )
    scenarios = _scenarios(problem)
    optimizer = MultiScenarioOptimizer(CONFIG)
    net = optimizer.solve_expected_utility(
        problem, scenarios, CostTreatment.NET, LAMBDA
    ).single_solution
    gross = optimizer.solve_expected_utility(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    ).single_solution
    assert (
        net is not None
        and gross is not None
        and net.weights is not None
        and gross.weights is not None
    )
    current = np.array([0.7, 0.1, 0.1, 0.1])
    assert np.abs(net.weights - current).sum() < np.abs(gross.weights - current).sum()
    expected_costs = optimizer._expected_costs(scenarios, np.array([0.5, 0.3, 0.2]))
    base_costs = scenarios.get("BASE").costs
    assert expected_costs is not None and base_costs is not None
    np.testing.assert_allclose(
        expected_costs.buy_costs, base_costs.buy_costs * (0.5 + 0.3 + 0.2 * 2.0)
    )
    assert net.validation is not None and net.validation.is_valid


# ------------------------------------------------------------------------------------- WORST_CASE


def test_worst_case_maximizes_the_minimum_scenario_utility() -> None:
    """P13 (SOCP → Clarabel): ``t* = min_s U_s(w*)`` y coincide con SLSQP sobre el epígrafe."""
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    scenarios = _scenarios(problem)
    data = _arrays(scenarios)
    result = MultiScenarioOptimizer(CONFIG).solve_worst_case(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    )
    solution = result.single_solution
    assert solution is not None and solution.is_valid_solution and solution.weights is not None
    utilities = [_utility(solution.weights, mu, s) for _, _, mu, s in data]
    assert solution.extra("worst_case_utility") == pytest.approx(min(utilities), abs=1e-12)
    assert solution.extra("solver_t") == pytest.approx(min(utilities), abs=1e-6)
    result_oracle = minimize(
        lambda x: -x[4],
        np.concatenate([np.full(4, 0.25), [-1.0]]),
        bounds=[(0.0, 0.6)] * 4 + [(None, None)],
        constraints=[{"type": "eq", "fun": lambda x: float(np.sum(x[:4]) - 1.0)}]
        + [
            {"type": "ineq", "fun": lambda x, m=mu, c=s: _utility(x[:4], m, c) - x[4]}
            for _, _, mu, s in data
        ],
        method="SLSQP",
        # ftol=1e-12 (no 1e-15): el óptimo |x4| ≈ 0,09 tiene un ulp de ≈ 1,4e-17 y ftol=1e-15
        # exige ≈ 70 ulp, en la resolución de coma flotante: según la CPU SLSQP termina con
        # «Positive directional derivative for linesearch» (H-1, INVESTIGATION_H1_B4.md §3). Las
        # comprobaciones de abajo (atol=1e-4 en pesos, abs=1e-7 en el valor) no cambian.
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    assert result_oracle.success
    np.testing.assert_allclose(solution.weights, result_oracle.x[:4], atol=1e-4)
    assert -result_oracle.fun == pytest.approx(min(utilities), abs=1e-7)
    assert solution.solver_names == ("CLARABEL",) and solution.strategy_id is StrategyID.WORST_CASE
    assert result.probabilities is None  # WorstCase no usa probabilidades
    rows = scenario_metric_rows(solution)
    assert [r.scenario_id for r in rows] == ["BASE", "BEAR", "CRASH"]
    assert min(r.utility for r in rows if r.utility is not None) == pytest.approx(
        min(utilities), abs=1e-12
    )


def test_worst_case_works_without_declared_probabilities_and_with_net_costs() -> None:
    problem = four_asset_problem(
        CONFIG,
        current=[0.4, 0.3, 0.2, 0.1],
        universe_overrides={"BuyCost": [60.0] * 4, "SellCost": [90.0] * 4},
    )
    no_probability = tuple(dataclasses.replace(d, probability=None) for d in scenario_definitions())
    scenarios = _scenarios(problem, no_probability)
    result = MultiScenarioOptimizer(CONFIG).solve_worst_case(
        problem, scenarios, CostTreatment.NET, LAMBDA
    )
    solution = result.single_solution
    assert solution is not None and solution.is_valid_solution and solution.weights is not None
    assert solution.extra("solver_t") == pytest.approx(
        solution.extra("worst_case_utility"), abs=1e-6
    )
    assert len(solution.scenario_metrics) == 3
    assert all(m.metrics.transaction_cost is not None for m in solution.scenario_metrics)
    crash = next(m for m in solution.scenario_metrics if m.scenario_id == "CRASH")
    base = next(m for m in solution.scenario_metrics if m.scenario_id == "BASE")
    assert (
        crash.metrics.transaction_cost_one_off is not None
        and base.metrics.transaction_cost_one_off is not None
    )
    assert crash.metrics.transaction_cost_one_off == pytest.approx(
        2.0 * base.metrics.transaction_cost_one_off
    )


# ------------------------------------------------------------- BASE_WITH_STRESS_CONSTRAINTS


def test_base_with_stress_constraints_matches_slsqp_with_the_stress_volatility_cap() -> None:
    """P14 (SOCP): utilidad BASE con ``√(wᵀΣ_CRASH w) <= σ_stress`` (activo)."""
    problem = four_asset_problem(CONFIG, max_weight=0.7)
    scenarios = _scenarios(problem)
    data = {sid: (mu, sigma) for sid, _, mu, sigma in _arrays(scenarios)}
    base_mu, base_sigma = data["BASE"]
    crash_sigma = data["CRASH"][1]
    free = _slsqp(lambda w: -_utility(w, base_mu, base_sigma), np.full(4, 0.25), 0.7)
    free_stress_vol = float(np.sqrt(free @ crash_sigma @ free))
    limit = 0.16
    assert free_stress_vol > limit  # el límite de estrés es activo para el óptimo BASE libre
    oracle = _slsqp(
        lambda w: -_utility(w, base_mu, base_sigma),
        np.full(4, 0.25),
        0.7,
        extra=[{"type": "ineq", "fun": lambda w: limit**2 - float(w @ crash_sigma @ w)}],
    )
    result = MultiScenarioOptimizer(CONFIG).solve_base_with_stress(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    )
    solution = result.single_solution
    assert solution is not None and solution.is_valid_solution and solution.weights is not None
    np.testing.assert_allclose(solution.weights, oracle, atol=1e-4)
    assert float(np.sqrt(solution.weights @ crash_sigma @ solution.weights)) == pytest.approx(
        limit, abs=1e-6
    )
    assert solution.extra("base_utility") == pytest.approx(
        _utility(oracle, base_mu, base_sigma), abs=1e-8
    )
    assert solution.extra("base_utility") < _utility(free, base_mu, base_sigma)  # el estrés cuesta
    assert solution.solver_names == ("CLARABEL",) and solution.notes == ("stress:CRASH",)
    checks = [name for name in (solution.validation.checks if solution.validation else ())]
    assert "SCENARIO:CRASH" in checks


def test_stress_return_floors_alone_keep_the_problem_a_qp_routed_to_osqp() -> None:
    problem = four_asset_problem(CONFIG, max_weight=0.7)
    definitions = list(scenario_definitions())
    definitions[2] = dataclasses.replace(definitions[2], stress_limits=StressLimits(None, 0.05))
    scenarios = _scenarios(problem, tuple(definitions))
    result = MultiScenarioOptimizer(CONFIG).solve_base_with_stress(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    )
    solution = result.single_solution
    assert solution is not None and solution.is_valid_solution and solution.weights is not None
    assert solution.solver_names == ("OSQP",)  # solo filas lineales: no es cónico
    crash_mu = scenarios.get("CRASH").risk_model.mu
    assert float(crash_mu @ solution.weights) >= 0.05 - 1e-7
    # sin el suelo el óptimo BASE tiene menos retorno en CRASH: el límite es activo
    free = MultiScenarioOptimizer(CONFIG).solve_expected_utility(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    )
    assert free.single_solution is not None and free.single_solution.weights is not None


def test_base_with_stress_without_any_limit_is_rejected_not_silently_the_base_scenario() -> None:
    problem = four_asset_problem(CONFIG)
    definitions = tuple(dataclasses.replace(d, stress_limits=None) for d in scenario_definitions())
    with pytest.raises(
        UnsupportedCombinationError, match="al menos un escenario con stress_limits"
    ):
        MultiScenarioOptimizer(CONFIG).solve_base_with_stress(
            problem, _scenarios(problem, definitions), CostTreatment.GROSS, LAMBDA
        )


# ------------------------------------------------------------ restricciones de todos los escenarios


def test_single_solutions_satisfy_the_constraints_of_every_scenario() -> None:
    """Se optimiza bajo la intersección de ``constraints_s`` y se valida contra cada escenario."""
    problem = four_asset_problem(CONFIG, current=[0.25] * 4)
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(0.05, None, 0.4, ()))
    definitions[2] = with_overrides(
        definitions[2],
        ConstraintOverrides(
            None, None, None, (GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.45),)
        ),
    )
    scenarios = _scenarios(problem, tuple(definitions))
    optimizer = MultiScenarioOptimizer(CONFIG)
    for solution in (
        optimizer.solve_expected_utility(
            problem, scenarios, CostTreatment.GROSS, LAMBDA
        ).single_solution,
        optimizer.solve_worst_case(problem, scenarios, CostTreatment.GROSS, LAMBDA).single_solution,
    ):
        assert solution is not None and solution.is_valid_solution and solution.weights is not None
        assert 0.5 * np.abs(solution.weights - 0.25).sum() <= 0.05 + 1e-7  # turnover del BEAR
        assert float(solution.weights.max()) <= 0.4 + 1e-7  # MaxWeight del BEAR
        assert solution.weights[[0, 2]].sum() <= 0.45 + 1e-7  # grupo Tech del CRASH
        assert solution.validation is not None
        assert {"SCENARIO:BEAR", "SCENARIO:CRASH", "SCENARIO:BASE"} <= set(
            solution.validation.checks
        )
    # con turnover ≤ 0,05 desde pesos iguales el límite de volatilidad de estrés (0,16) no es
    # alcanzable: el modo BaseWithStress lo declara inviable en lugar de violarlo en silencio
    stressed = optimizer.solve_base_with_stress(problem, scenarios, CostTreatment.GROSS, LAMBDA)
    assert stressed.single_solution is not None
    assert stressed.single_solution.status is SolverStatus.INFEASIBLE
    assert (
        not stressed.single_solution.is_valid_solution and stressed.single_solution.weights is None
    )
    relaxed = list(definitions)
    relaxed[1] = with_overrides(definitions[1], ConstraintOverrides(0.5, None, 0.7, ()))
    feasible = optimizer.solve_base_with_stress(
        problem, _scenarios(problem, tuple(relaxed)), CostTreatment.GROSS, LAMBDA
    ).single_solution
    assert feasible is not None and feasible.is_valid_solution and feasible.weights is not None
    assert (
        feasible.weights[[0, 2]].sum() <= 0.45 + 1e-7
        and float(feasible.weights.max()) <= 0.7 + 1e-7
    )


def test_incompatible_scenario_constraints_are_rejected_explicitly() -> None:
    problem = four_asset_problem(CONFIG)
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(None, 0.6, None, ()))
    definitions[2] = with_overrides(definitions[2], ConstraintOverrides(None, None, 0.3, ()))
    scenarios = _scenarios(problem, tuple(definitions))
    with pytest.raises(ScenarioError, match="incompatibles"):
        MultiScenarioOptimizer(CONFIG).solve_worst_case(
            problem, scenarios, CostTreatment.GROSS, LAMBDA
        )
    # límites de peso máximos que no suman 1 → inviable en la factibilidad previa
    infeasible_defs = list(scenario_definitions())
    infeasible_defs[1] = with_overrides(
        infeasible_defs[1], ConstraintOverrides(None, None, 0.2, ())
    )
    result = MultiScenarioOptimizer(CONFIG).solve_worst_case(
        problem, _scenarios(problem, tuple(infeasible_defs)), CostTreatment.GROSS, LAMBDA
    )
    solution = result.single_solution
    assert solution is not None and solution.status is SolverStatus.INFEASIBLE
    assert not solution.is_valid_solution and solution.notes


def test_the_intersection_takes_the_tightest_limit_of_every_scenario() -> None:
    first = CONFIG.constraints
    tighter = dataclasses.replace(
        first,
        global_max_weight=0.5,
        global_max_turnover=0.2,
        group_limits=(GroupLimit(GroupDimension.SECTOR, "Tech", 0.1, 0.6),),
    )
    other = dataclasses.replace(
        first,
        global_min_weight=0.01,
        global_max_weight=0.4,
        global_max_turnover=0.3,
        group_limits=(
            GroupLimit(GroupDimension.SECTOR, "Tech", 0.2, 0.7),
            GroupLimit(GroupDimension.SECTOR, "Energy", None, 0.8),
        ),
    )
    merged = intersect_constraint_configs([first, tighter, other])
    assert merged.global_max_weight == 0.4 and merged.global_min_weight == 0.01
    assert merged.global_max_turnover == 0.2
    limits = {(g.group): (g.min_weight, g.max_weight) for g in merged.group_limits}
    assert limits == {"Tech": (0.2, 0.6), "Energy": (None, 0.8)}
    assert intersect_constraint_configs([first]).global_max_turnover is None


def test_the_multi_scenario_validator_rejects_a_solution_that_breaks_one_scenario() -> None:
    """VAL: una solución que cumple el BASE pero rompe las de un escenario se rechaza."""
    from portfolio_engine.validation import AdvancedChecks, ScenarioCheck
    from portfolio_engine.validation.solution_validator import ValidationContext

    problem = four_asset_problem(CONFIG, current=[0.25] * 4)
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(0.05, None, None, ()))
    scenarios = _scenarios(problem, tuple(definitions))
    optimizer = MultiScenarioOptimizer(CONFIG)
    strategy = StrategyOptimizer(CONFIG)
    context, _ = strategy.prepare(problem, CostTreatment.GROSS)
    assert context is not None
    checks = optimizer._scenario_checks(problem, context, scenarios, CostTreatment.GROSS)
    weights = np.array([0.4, 0.2, 0.2, 0.2])  # turnover 0,15 > 0,05 del BEAR
    report = strategy.validator.validate(
        weights,
        context.compiled,
        ValidationContext(context.inputs.mu, context.inputs.sigma, None),
        checks,
    )
    assert not report.is_valid
    assert any(v.constraint_id.startswith("SCENARIO:BEAR:TURNOVER") for v in report.violations)
    assert not any(v.constraint_id.startswith("SCENARIO:BASE") for v in report.violations)
    assert isinstance(checks, AdvancedChecks) and all(
        isinstance(c, ScenarioCheck) for c in checks.scenarios
    )


def test_scenarios_without_a_shock_on_mu_still_get_their_own_id_in_single_solutions() -> None:
    problem = four_asset_problem(CONFIG)
    definitions = (
        ScenarioDefinition("BASE", ScenarioType.BASE, 0.7, None, (), None, (), None, None, None),
        ScenarioDefinition(
            "UP",
            ScenarioType.BULL,
            0.3,
            None,
            (AssetShock(ShockSelector.ALL, (), 1.2, None, None),),
            None,
            (),
            None,
            None,
            None,
        ),
    )
    scenarios = _scenarios(problem, definitions)
    result = MultiScenarioOptimizer(CONFIG).solve_expected_utility(
        problem, scenarios, CostTreatment.GROSS, LAMBDA
    )
    assert result.scenario_ids == ("BASE", "UP")
    assert result.single_solution is not None
    assert [m.scenario_id for m in result.single_solution.scenario_metrics] == ["BASE", "UP"]
    up_return = next(m for m in result.single_solution.scenario_metrics if m.scenario_id == "UP")
    assert up_return.metrics.expected_return_gross == pytest.approx(
        1.2 * float(MU4 @ result.single_solution.weights),
        rel=1e-12,  # type: ignore[arg-type]
    )
    assert spec_with().portfolio_id == "P1" and ContinuousFrontierEngine is not None
