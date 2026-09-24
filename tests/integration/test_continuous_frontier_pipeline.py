"""TST-002, TST-011, FRN-001, FRN-022, VIS-001, OUT-002/003/005/006/007: pipeline completo de
Bloques 1 y 2."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from portfolio_engine.config import EngineConfig, load_engine_config
from portfolio_engine.costs import TransactionCostModel, align_union
from portfolio_engine.data.sources import DataFrameSource
from portfolio_engine.data.validation import (
    MarketDataValidator,
    PortfolioValidator,
    UniverseValidator,
    resolve_asset_costs,
)
from portfolio_engine.frontiers import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.models.enums import CostTreatment, FrontierMethod, StrategyID
from portfolio_engine.outputs import (
    DATASET_COLUMNS,
    WeightContext,
    frontier_dataset,
    frontier_point_rows,
    frontier_weight_rows,
    scenario_header_rows,
    scenario_weight_rows,
    solver_diagnostics_rows,
)
from portfolio_engine.returns import ReturnsEngine
from portfolio_engine.returns.expected import make_expected_return_provider
from portfolio_engine.risk import CovarianceBuilder, build_risk_model
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.synthetic import holdings_frame, price_frame, universe_frame

pytestmark = pytest.mark.integration

HELD = ["A001", "A003", "A004", "A006", "A008", "A010"]
WEIGHTS = [0.25, 0.20, 0.20, 0.15, 0.10, 0.10]
N_UNIVERSE = 12


def _pipeline(config: EngineConfig, *, holdings=None, seed: int = 5) -> FrontierProblem:  # type: ignore[no-untyped-def]
    rows = (
        holdings
        if holdings is not None
        else [("P1", a, w) for a, w in zip(HELD, WEIGHTS, strict=True)]
    )
    source = DataFrameSource(
        prices=price_frame(N_UNIVERSE, 220, seed=seed),
        universe=universe_frame(N_UNIVERSE, MaxWeight=[0.6] * N_UNIVERSE),
        holdings=holdings_frame(rows) if rows else holdings_frame([("P1", "A000", 1.0)]),
    )
    universe = UniverseValidator(config.constraints).validate(source.load_universe()).universe
    prices = MarketDataValidator(config.data).validate(source.load_prices(), universe).prices
    returns = ReturnsEngine(config.returns).compute(prices)
    expected = make_expected_return_provider(config.returns, None).estimate(
        returns.asset_ids, returns
    )
    covariance = CovarianceBuilder(config.risk, config.returns.trading_days_per_year).build(
        returns, returns.asset_ids
    )
    portfolios = PortfolioValidator(config.constraints, config.data).validate(
        source.load_current_portfolios(), universe
    )
    costs = resolve_asset_costs(universe, config.transaction_costs).require_complete()
    return FrontierProblem(
        portfolio_id="P1",
        scenario_id="BASE",
        risk_model=build_risk_model(expected, covariance),
        universe=universe,
        state=portfolios.states["P1"],
        spec=None,
        costs=costs,
    )


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return load_engine_config(DEFAULT_CONFIG_PATH)


@pytest.fixture(scope="module")
def problem(config: EngineConfig) -> FrontierProblem:
    return _pipeline(config)


@pytest.mark.parametrize("method", list(FrontierMethod))
@pytest.mark.parametrize("treatment", list(CostTreatment))
def test_continuous_frontier_keeps_exactly_the_current_assets(
    config: EngineConfig, problem: FrontierProblem, treatment: CostTreatment, method: FrontierMethod
) -> None:
    """TST-011: ``set(CurrentAssets) == set(FrontierAssets)`` en todas las soluciones, y la
    frontera es válida."""
    result = ContinuousFrontierEngine(config).solve(problem, treatment, method)
    assert result.asset_set == set(problem.state.asset_ids) == set(HELD)
    assert (
        len(problem.risk_model.asset_ids) == N_UNIVERSE
    )  # el modelo global es mayor que la composición
    assert result.pre_check_feasible and len(result.points) == config.frontier.frontier_points
    for point in result.points:
        assert point.weights is not None and point.weights.shape == (len(HELD),)
        assert point.weights.sum() == pytest.approx(1.0, abs=1e-7)
        assert point.is_valid_solution and point.composition_id == result.composition_id
    assert (
        result.diagnostics.setup_count == 3  # QP compartido + LP + etapa 2 de MaxReturn
        and result.diagnostics.solve_count == len(result.points) + 1
    )
    assert result.diagnostics.warm_start_count > 0


def test_min_holding_weight_enforces_strictly_positive_holdings(
    config: EngineConfig, problem: FrontierProblem
) -> None:
    """A-08: con ``min_holding_weight`` todos los activos de la composición conservan peso
    positivo."""
    strict = dataclasses.replace(
        config, frontier=dataclasses.replace(config.frontier, min_holding_weight=0.02)
    )
    result = ContinuousFrontierEngine(strict).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert all(p.weights is not None and p.weights.min() >= 0.02 - 1e-7 for p in result.points)
    assert all(
        p.metrics is not None and p.metrics.number_assets == len(HELD) for p in result.points
    )
    loose = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert any(p.weights is not None and p.weights.min() < 0.02 - 1e-3 for p in loose.points)


def test_frontier_dataset_is_plottable(config: EngineConfig, problem: FrontierProblem) -> None:
    """FRN-022 / Definition of Done: dataset Volatility, ExpectedReturnGross, ExpectedReturnNet."""
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID
    )
    dataset = frontier_dataset(result)
    assert list(dataset.columns) == list(DATASET_COLUMNS) and len(dataset) == len(result.points)
    for column in ("Volatility", "ExpectedReturnGross", "ExpectedReturnNet"):
        assert dataset[column].notna().all() and np.isfinite(dataset[column]).all()
    assert (dataset["ExpectedReturnNet"] <= dataset["ExpectedReturnGross"] + 1e-12).all()
    assert (dataset["Volatility"].diff().dropna() >= -1e-9).all()
    assert dataset["FrontierType"].unique().tolist() == ["CONTINUOUS_FRONTIER:NET"]
    assert set(dataset["StrategyID"]) == {"MIN_VARIANCE", "FRONTIER_POINT", "MAX_RETURN"}
    assert isinstance(dataset, pd.DataFrame)


def test_output_rows(config: EngineConfig, problem: FrontierProblem) -> None:
    """OUT-002/003/005/007, OPT-014: filas de frontera, pesos (unión), diagnósticos y estrategias
    nombradas."""
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    points = frontier_point_rows(result)
    assert len(points) == len(result.points) and {r.frontier_type for r in points} == {
        "CONTINUOUS_FRONTIER:NET"
    }
    assert all(r.expected_return_net is not None and r.availability_reason is None for r in points)
    assert points[0].optimization_horizon_years == config.optimization_horizon_years
    ids = result.asset_ids
    position = {a: i for i, a in enumerate(problem.risk_model.asset_ids)}
    idx = [position[a] for a in ids]
    alignment = align_union(problem.state, ids)
    context = WeightContext(
        tickers={a.asset_id: a.ticker for a in problem.universe},
        mu=problem.risk_model.mu[idx],
        sigma=problem.risk_model.sigma[np.ix_(idx, idx)],
        alignment=alignment,
        cost_model=TransactionCostModel(
            alignment, problem.costs, config.optimization_horizon_years
        ),  # type: ignore[arg-type]
        zero_volatility_tolerance=config.frontier.zero_volatility_tolerance,
        zero_weight_tolerance=config.frontier.zero_weight_tolerance,
    )
    all_weights = frontier_weight_rows(result, context)
    assert len(all_weights) == len(result.points) * len(ids)  # unión current ∪ composición
    first = [w for w in all_weights if w.frontier_point_id == result.points[0].point_id]
    assert sum(w.optimized_weight for w in first) == pytest.approx(1.0, abs=1e-7)
    assert sum(w.transaction_cost_asset or 0.0 for w in first) == pytest.approx(
        result.points[0].metrics.transaction_cost_one_off,
        abs=1e-12,  # type: ignore[union-attr]
    )
    assert all(
        w.weight_change == pytest.approx(w.optimized_weight - w.current_weight) for w in first
    )
    named = scenario_weight_rows(result, context)
    assert {w.strategy_id for w in named} == {"MIN_VARIANCE", "MAX_RETURN"} and len(named) < len(
        all_weights
    )
    headers = scenario_header_rows(result)
    assert [h.strategy_id for h in headers] == ["CURRENT", "MIN_VARIANCE", "MAX_RETURN"]
    current = headers[0]
    assert (
        current.turnover == 0.0
        and current.transaction_cost == 0.0
        and current.solver_name == "NONE"
    )
    diagnostics = solver_diagnostics_rows(result)
    assert len(diagnostics) == len(result.points)
    assert all(d.solver_name == "OSQP" and d.solver_status == "OPTIMAL" for d in diagnostics)
    assert all(
        d.maximum_constraint_violation is not None and d.maximum_constraint_violation < 1e-6
        for d in diagnostics
    )
    assert any(d.warm_start_used for d in diagnostics)


def test_frontier_is_reproducible_and_sensitive_to_the_current_weights(
    config: EngineConfig,
) -> None:
    """§70: mismas entradas ⇒ mismos bits y hashes; otros pesos actuales ⇒ otro
    ``ConstraintHash``."""
    engine = ContinuousFrontierEngine(config)
    first = engine.solve(_pipeline(config), CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)
    second = engine.solve(_pipeline(config), CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)
    assert (
        first.config_hash == second.config_hash and first.constraint_hash == second.constraint_hash
    )
    assert first.mu_sigma_version == second.mu_sigma_version
    for a, b in zip(first.points, second.points, strict=True):
        assert (
            a.weights is not None and b.weights is not None and np.array_equal(a.weights, b.weights)
        )
    other = [("P1", a, w) for a, w in zip(HELD, [0.20, 0.20, 0.20, 0.15, 0.15, 0.10], strict=True)]
    changed = engine.solve(
        _pipeline(config, holdings=other), CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    assert changed.constraint_hash != first.constraint_hash


def test_no_current_portfolio_marks_unavailable_metrics_in_outputs(config: EngineConfig) -> None:
    """TC-007/OUT-006: sin cartera actual las filas llevan NULL con motivo (y el dataset, NaN)."""
    base = _pipeline(config)
    empty = dataclasses.replace(
        base,
        state=dataclasses.replace(
            base.state,
            asset_ids=(),
            weights=np.empty(0),
            global_indices=np.empty(0, dtype=np.int64),
        ),
        composition_asset_ids=tuple(HELD),
    )
    result = ContinuousFrontierEngine(config).solve(
        empty, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert not result.has_current_portfolio and result.current_metrics is None
    rows = frontier_point_rows(result)
    assert all(
        r.turnover is None and r.transaction_cost is None and r.expected_return_net is None
        for r in rows
    )
    assert {r.availability_reason for r in rows} == {"NO_CURRENT_PORTFOLIO"}
    assert scenario_header_rows(result)[0].strategy_id == StrategyID.MIN_VARIANCE.value
    dataset = frontier_dataset(result)
    assert (
        dataset["ExpectedReturnNet"].isna().all() and dataset["ExpectedReturnGross"].notna().all()
    )
