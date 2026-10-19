"""SCN-008 (Definition of Done del Bloque 4): una misma cartera produce diferentes fronteras y
soluciones por ``ScenarioID``, y **todas** las salidas llevan ``ScenarioID``.

Pipeline completo: modelo base → ``ScenarioEngine`` → fronteras continua y global por escenario →
estrategias nombradas (Max Sharpe, CVaR, robusta) → filas de salida.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_engine.frontiers import StrategyOptimizer
from portfolio_engine.models.cvar import build_return_scenario_set
from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    CVaRSource,
    FrontierMethod,
    FrontierScope,
    MuUncertaintyKind,
    ScenarioWeighting,
    StrategyID,
)
from portfolio_engine.optimizers.formulations.robust import MuUncertaintySet
from portfolio_engine.outputs import (
    frontier_dataset,
    frontier_point_rows,
    global_frontier_point_rows,
    scenario_header_rows,
    scenario_metric_rows,
    solver_diagnostics_rows,
    strategy_header_rows,
    strategy_weight_rows,
)
from portfolio_engine.scenarios import MultiScenarioOptimizer, ScenarioEngine
from tests.fixtures.block4 import scenario_definitions
from tests.fixtures.candidates import candidate_config, random_problem

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def setup():  # type: ignore[no-untyped-def]
    config = candidate_config()
    problem = random_problem(8, [0, 1, 2], 21, config, max_weight=0.6)
    # A000/A002/A004/A006 son Tech en el universo sintético: el CRASH actúa sobre ellos
    scenarios = ScenarioEngine(config).build(
        problem.risk_model,
        problem.universe,
        problem.costs,
        config.constraints,
        problem.spec,
        scenario_definitions(),
    )
    optimizer = MultiScenarioOptimizer(config)
    continuous = optimizer.solve_independent(
        problem,
        scenarios,
        CostTreatment.NET,
        FrontierMethod.RISK_AVERSION_GRID,
        include_max_sharpe=True,
    )
    global_scope = optimizer.solve_independent(
        problem,
        scenarios,
        CostTreatment.NET,
        FrontierMethod.RISK_AVERSION_GRID,
        scope=FrontierScope.GLOBAL_CANDIDATE_FRONTIER,
    )
    return config, problem, scenarios, continuous, global_scope


def test_the_same_portfolio_produces_different_frontiers_per_scenario(setup) -> None:  # type: ignore[no-untyped-def]
    _, problem, scenarios, continuous, _ = setup
    assert scenarios.ids == ("BASE", "BEAR", "CRASH")
    frames = [frontier_dataset(continuous.frontier(sid)) for sid in scenarios.ids]
    plot = pd.concat(frames, ignore_index=True)
    assert set(plot["ScenarioID"]) == {"BASE", "BEAR", "CRASH"} and set(plot["PortfolioID"]) == {
        "P1"
    }
    valid = plot[plot["IsValidSolution"]]
    per_scenario = {
        sid: tuple(
            zip(
                valid[valid["ScenarioID"] == sid]["Volatility"].round(8),
                valid[valid["ScenarioID"] == sid]["ExpectedReturnNet"].round(8),
                strict=True,
            )
        )
        for sid in scenarios.ids
    }
    assert all(len(points) >= 5 for points in per_scenario.values())
    assert len({points for points in per_scenario.values()}) == 3  # tres fronteras distintas
    # el BEAR (retornos −5 %, vol ×1,3) queda estrictamente por debajo/derecha del BASE
    base_best = valid[valid["ScenarioID"] == "BASE"]["ExpectedReturnNet"].max()
    bear_best = valid[valid["ScenarioID"] == "BEAR"]["ExpectedReturnNet"].max()
    assert bear_best < base_best - 0.03
    assert problem.state.has_current_portfolio


def test_named_solutions_differ_by_scenario_and_keep_their_ids(setup) -> None:  # type: ignore[no-untyped-def]
    _, _, scenarios, continuous, _ = setup
    strategies = continuous.strategies
    assert [s.scenario_id for s in strategies] == list(scenarios.ids)
    assert all(s.strategy_id is StrategyID.MAX_SHARPE for s in strategies)
    valid = [s for s in strategies if s.weights is not None]
    assert [s.scenario_id for s in valid] == ["BASE", "BEAR"]
    assert len({tuple(np.round(s.weights, 5)) for s in valid if s.weights is not None}) == 2
    # en el CRASH ningún peso factible tiene exceso de retorno positivo: NOT_APPLICABLE (A-13),
    # nunca un Sharpe inventado
    crash = strategies[2]
    assert (
        crash.outcome == "NOT_APPLICABLE" and crash.weights is None and not crash.is_valid_solution
    )
    rows = strategy_header_rows(strategies)
    assert [r.scenario_id for r in rows] == ["BASE", "BEAR", "CRASH"]
    assert all(r.strategy_id == "MAX_SHARPE" for r in rows)
    assert all(r.cvar is None for r in rows)  # sin escenarios de retorno el CVaR es NULL (§63)
    assert rows[0].sharpe_ratio != rows[1].sharpe_ratio and rows[0].solver_names == "CLARABEL"
    assert rows[2].sharpe_ratio is None and rows[2].availability_reason == "NOT_APPLICABLE"
    weight_rows = strategy_weight_rows(strategies[1], {a: a for a in strategies[1].asset_ids})
    assert strategy_weight_rows(crash, {}) == ()
    assert weight_rows and {r.scenario_id for r in weight_rows} == {"BEAR"}
    assert sum(r.optimized_weight for r in weight_rows) == pytest.approx(1.0)


def test_every_output_table_carries_the_scenario_id(setup) -> None:  # type: ignore[no-untyped-def]
    _, _, scenarios, continuous, global_scope = setup
    for sid in scenarios.ids:
        frontier = continuous.frontier(sid)
        assert {r.scenario_id for r in frontier_point_rows(frontier)} == {sid}
        assert {r.scenario_id for r in scenario_header_rows(frontier)} == {sid}
        assert {r.scenario_id for r in solver_diagnostics_rows(frontier)} == {sid}
        global_result = global_scope.frontier(sid)
        assert {r.scenario_id for r in global_frontier_point_rows(global_result)} == {sid}  # type: ignore[arg-type]
        assert global_result.candidate_diagnostics.scenario_id == sid  # type: ignore[union-attr]


def test_global_candidate_frontiers_are_solved_per_scenario_with_their_own_data(setup) -> None:  # type: ignore[no-untyped-def]
    _, _, scenarios, _, global_scope = setup
    for sid in scenarios.ids:
        result = global_scope.frontier(sid)
        assert result.scenario_id == sid and result.diagnostics.candidate_count >= 1  # type: ignore[union-attr]
        assert result.diagnostics.points_valid > 0  # type: ignore[union-attr]
    signatures = {
        sid: tuple(sorted({p.point.composition_id for p in global_scope.frontier(sid).points}))  # type: ignore[union-attr]
        for sid in scenarios.ids
    }
    assert all(signatures.values())
    versions = {s.risk_model.mu_sigma_version for s in scenarios.scenarios}
    assert len(versions) == 3  # cada escenario tiene su MuSigmaVersion


def test_single_solutions_report_the_metrics_under_every_scenario_and_cvar_rows_carry_cvar(
    setup,
) -> None:  # type: ignore[no-untyped-def]
    config, problem, scenarios, _, _ = setup
    optimizer = MultiScenarioOptimizer(config)
    worst = optimizer.solve_worst_case(problem, scenarios, CostTreatment.GROSS, 3.0).single_solution
    assert worst is not None and worst.weights is not None
    rows = scenario_metric_rows(worst)
    assert [r.scenario_id for r in rows] == list(scenarios.ids)
    assert {r.solution_scenario_id for r in rows} == {"MULTI:WORST_CASE"}
    assert len({round(r.volatility, 8) for r in rows}) == 3  # la misma cartera, tres riesgos
    strategy = StrategyOptimizer(config)
    returns = np.random.default_rng(0).multivariate_normal(
        problem.risk_model.mu / 252, problem.risk_model.sigma / 252, size=500
    )
    scenario_set = build_return_scenario_set(
        problem.risk_model.asset_ids,
        returns,
        CVaRSource.SIMULATED,
        ScenarioWeighting.EQUAL,
        None,
        config.scenarios.probability_sum_tolerance,
    )
    cvar_result = strategy.cvar(problem, CostTreatment.GROSS, scenario_set, CVaRObjective.MIN_CVAR)
    header = strategy_header_rows([cvar_result])[0]
    assert header.cvar is not None and header.cvar > 0.0 and header.strategy_id == "MIN_CVAR"
    robust = strategy.robust(
        problem,
        CostTreatment.GROSS,
        3.0,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=np.full(3, 0.01)),  # 3 activos
    )
    robust_row = strategy_header_rows([robust])[0]
    assert robust_row.strategy_id == "ROBUST" and robust_row.is_valid_solution
    assert robust_row.optimality_claim == "CONVEX_GLOBAL" and robust_row.cvar is None
