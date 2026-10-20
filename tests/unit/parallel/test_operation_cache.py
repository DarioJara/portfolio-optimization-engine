"""CCH-001…CCH-005 a nivel de operación: claves por componente, aciertos sin solver, límites.

Las pruebas con motores reales cuentan las llamadas efectivas a ``solve()`` de los backends y al LP
de HiGHS: un acierto debe dejar el contador intacto (cero llamadas al solver).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from portfolio_engine.cache import CacheEvent, ResultCache
from portfolio_engine.config import CacheConfig
from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    FrontierMethod,
    SolverStatus,
)
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.parallel.executor import SequentialExecutor
from portfolio_engine.parallel.operation_cache import FINAL_STATUSES, OperationCache
from portfolio_engine.parallel.task import (
    ExecutionContext,
    PortfolioRequest,
    run_portfolio,
)
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.fixtures.candidates import random_problem
from tests.fixtures.parallel import (
    cache_config,
    compare_results,
    count_solver_calls,
    requests_for,
    snapshot_of,
)
from tests.fixtures.problems import base_config, spec_with

pytestmark = pytest.mark.unit

CONFIG = base_config()
NET, GROSS = CostTreatment.NET, CostTreatment.GROSS
RISK = FrontierMethod.RISK_AVERSION_GRID
K = OperationKind
FRONTIER = OperationSpec(K.FRONTIER_FIXED_COMPOSITION, NET, method=RISK)


def workload(*operations: OperationSpec) -> WorkloadSpec:
    return WorkloadSpec(tuple(operations))


@pytest.fixture(scope="module")
def problem() -> Any:
    return random_problem(8, [0, 1, 2], 3, CONFIG)


@pytest.fixture(scope="module")
def snapshot(problem: Any) -> Any:
    return snapshot_of(problem, return_periods=120, seed=2)


def context_of(snapshot: Any, config: Any = CONFIG) -> ExecutionContext:
    return ExecutionContext.create(config, snapshot)


def key_of(request: PortfolioRequest, context: ExecutionContext, index: int = 0) -> Any:
    return OperationCache(context, ResultCache(4, 10**6)).key(request, index)


def base_request(problem: Any, ops: WorkloadSpec | None = None, **kw: Any) -> PortfolioRequest:
    request = requests_for(problem, ops or workload(FRONTIER), 1, seed=5, **kw)[0]
    return request


# ---------------------------------------------------------------------- claves (CCH-002/004)


def test_the_key_is_deterministic_and_covers_all_official_components(
    problem: Any, snapshot: Any
) -> None:
    request, context = base_request(problem), context_of(snapshot)
    first, second = key_of(request, context), key_of(request, context)
    assert first.digest == second.digest
    from portfolio_engine.cache import OFFICIAL_COMPONENTS

    names = {name for name, _ in first.components}
    assert set(OFFICIAL_COMPONENTS) <= names
    assert dict(first.components)["market_data_timestamp"] == "UNSPECIFIED"  # explícito, no omitido
    assert dict(first.components)["config_hash"] == context.config_hash


def _changed(base: Any, other: Any) -> set[str]:
    """Componentes cuyo valor difiere entre dos claves."""
    left, right = dict(base.components), dict(other.components)
    return {name for name in left if left[name] != right[name]}


def test_every_input_that_determines_a_result_changes_the_key(problem: Any, snapshot: Any) -> None:
    request, context = base_request(problem), context_of(snapshot)
    base = key_of(request, context)
    ids = problem.risk_model.asset_ids
    weights = request.state.weights.copy()
    shifted = np.array([weights[0] * 0.9, weights[1] * 1.1, *weights[2:]])
    shifted_state = type(request.state)(
        request.state.portfolio_id,
        request.state.asset_ids,
        shifted / shifted.sum(),
        request.state.global_indices,
        request.state.nav,
    )
    cases: dict[str, tuple[Any, set[str]]] = {
        # misma composición, distinto peso actual ⇒ solo cambia el estado actual (CCH-004)
        "pesos actuales": (
            key_of(dataclasses.replace(request, state=shifted_state), context),
            {"current_portfolio_state_hash"},
        ),
        "composición explícita": (
            key_of(dataclasses.replace(request, composition_asset_ids=tuple(ids[:4])), context),
            {"composition_hash", "constraint_hash"},
        ),
        "mandato": (
            key_of(
                dataclasses.replace(
                    request, spec=spec_with(portfolio_id=request.portfolio_id, max_turnover=0.3)
                ),
                context,
            ),
            {"constraint_hash"},
        ),
        "cartera": (
            key_of(dataclasses.replace(request, portfolio_id="OTRA"), context),
            {"portfolio_id"},
        ),
        "operación (tratamiento)": (
            key_of(
                dataclasses.replace(
                    request, workload=workload(dataclasses.replace(FRONTIER, treatment=GROSS))
                ),
                context,
            ),
            {"operation_hash"},
        ),
        "operación (método)": (
            key_of(
                dataclasses.replace(
                    request,
                    workload=workload(
                        dataclasses.replace(FRONTIER, method=FrontierMethod.TARGET_RETURN_GRID)
                    ),
                ),
                context,
            ),
            {"operation_hash"},
        ),
        "fecha de los datos": (
            key_of(
                request,
                context_of(dataclasses.replace(snapshot, market_data_timestamp="2026-10-20")),
            ),
            {"market_data_timestamp", "snapshot_key"},
        ),
        "escenario base": (
            key_of(request, context_of(dataclasses.replace(snapshot, base_scenario_id="STRESS"))),
            {"scenario_id", "snapshot_key"},
        ),
    }
    for name, (key, expected) in cases.items():
        assert _changed(base, key) >= expected, name
        assert key.digest != base.digest, name


def test_configuration_costs_and_market_data_change_the_key(problem: Any, snapshot: Any) -> None:
    request = base_request(problem)
    context = context_of(snapshot)
    base = key_of(request, context)

    def frontier_changed(config: Any) -> Any:
        return dataclasses.replace(
            config, frontier=dataclasses.replace(config.frontier, pareto_tolerance=1e-9)
        )

    horizon = dataclasses.replace(CONFIG, optimization_horizon_years=2.0)
    constraints = dataclasses.replace(
        CONFIG,
        constraints=dataclasses.replace(CONFIG.constraints, global_max_turnover=0.4),
    )
    other_model = snapshot_of(random_problem(8, [0, 1, 2], 4, CONFIG), return_periods=120, seed=2)
    cheaper = dataclasses.replace(snapshot.costs, buy_costs=snapshot.costs.buy_costs * 2.0)
    cases = {
        "ConfigHash (horizonte)": (
            context_of(snapshot, horizon),
            {"config_hash", "transaction_cost_hash"},
        ),
        "ConfigHash (restricciones)": (
            context_of(snapshot, constraints),
            {"config_hash", "constraint_hash"},
        ),
        "FrontierConfigHash": (
            context_of(snapshot, frontier_changed(CONFIG)),
            {"config_hash", "frontier_config_hash"},
        ),
        "MuSigmaVersion": (
            context_of(dataclasses.replace(snapshot, risk_model=other_model.risk_model)),
            {"mu_sigma_version", "snapshot_key"},
        ),
        "TransactionCostHash": (
            context_of(dataclasses.replace(snapshot, costs=cheaper)),
            {"transaction_cost_hash", "snapshot_key"},
        ),
    }
    for name, (other, expected) in cases.items():
        key = key_of(request, other)
        assert _changed(base, key) >= expected, (name, _changed(base, key))


def test_scenario_hash_only_applies_to_operations_that_use_scenarios_or_returns(
    problem: Any, snapshot: Any
) -> None:
    cvar_op = OperationSpec(K.STRATEGY_CVAR, GROSS, cvar_objective=CVaRObjective.MIN_CVAR)
    plain = key_of(base_request(problem), context_of(snapshot))
    cvar = key_of(base_request(problem, workload(cvar_op)), context_of(snapshot))
    assert dict(plain.components)["scenario_hash"] == "NONE"
    assert dict(cvar.components)["scenario_hash"] != "NONE"
    other_returns = snapshot_of(problem, return_periods=120, seed=3)  # otros retornos simulados
    changed = key_of(base_request(problem, workload(cvar_op)), context_of(other_returns))
    assert dict(changed.components)["scenario_hash"] != dict(cvar.components)["scenario_hash"]


def test_exact_mip_keys_depend_on_the_global_frontier_that_feeds_them(
    problem: Any, snapshot: Any
) -> None:
    glob = OperationSpec(K.GLOBAL_FRONTIER, GROSS, method=RISK)
    mip = OperationSpec(K.EXACT_MIP_VALIDATION, GROSS, risk_aversion=4.0)
    other_glob = OperationSpec(K.GLOBAL_FRONTIER, NET, method=RISK)
    context = context_of(snapshot)
    first = key_of(base_request(problem, workload(glob, mip)), context, 1)
    second = key_of(base_request(problem, workload(other_glob, mip)), context, 1)
    assert dict(first.components)["operation_hash"] != dict(second.components)["operation_hash"]


# ------------------------------------------------------------- aciertos y solver (CCH-003)


def test_a_hit_returns_the_same_result_with_zero_solver_calls(problem: Any, snapshot: Any) -> None:
    request = base_request(problem, workload(FRONTIER, FRONTIER))  # misma operación dos veces
    context = context_of(snapshot)
    cache = OperationCache(context, ResultCache(8, 10**8))
    with count_solver_calls() as calls:
        result = run_portfolio(request, context, cache=cache)
    first, second = result.operations
    assert (first.cache_event, second.cache_event) == (CacheEvent.MISS, CacheEvent.HIT)
    with count_solver_calls() as single:
        run_portfolio(
            dataclasses.replace(request, workload=workload(FRONTIER)), context, cache=None
        )
    assert calls.count == single.count > 0  # la segunda operación no llamó al solver (0 llamadas)
    assert first.result is not second.result  # copias independientes
    assert compare_results(first.result, second.result).differences == []
    weights_a = first.result.points[0].weights  # type: ignore[union-attr]
    weights_b = second.result.points[0].weights  # type: ignore[union-attr]
    assert weights_a is not weights_b and not np.shares_memory(weights_a, weights_b)
    metrics = cache.metrics
    assert (metrics.hits, metrics.misses, metrics.stores) == (1, 1, 1)


def test_results_with_the_cache_equal_results_without_it(problem: Any, snapshot: Any) -> None:
    requests = requests_for(problem, workload(FRONTIER, FRONTIER), 3, seed=8)
    plain = SequentialExecutor(CONFIG, snapshot).run(requests)
    cached = SequentialExecutor(CONFIG, snapshot, cache_config()).run(requests)
    assert cached.manifest.cache_enabled and not plain.manifest.cache_enabled
    assert cached.cache_metrics.hits == 3 and cached.cache_metrics.misses == 3
    assert plain.cache_metrics.hits == plain.cache_metrics.misses == 0  # desactivada: sin consultas
    for left, right in zip(plain.results, cached.results, strict=True):
        assert compare_results(left, right).differences == []
        assert [o.cache_event for o in left.operations] == [CacheEvent.DISABLED] * 2
        assert [o.cache_event for o in right.operations] == [CacheEvent.MISS, CacheEvent.HIT]


def test_distinct_portfolios_never_share_entries(problem: Any, snapshot: Any) -> None:
    """Misma operación y mismos datos, carteras distintas ⇒ ningún acierto entre ellas."""
    requests = requests_for(problem, workload(FRONTIER), 4, seed=21)
    run = SequentialExecutor(CONFIG, snapshot, cache_config()).run(requests)
    assert run.cache_metrics.hits == 0 and run.cache_metrics.misses == 4


def test_the_cache_is_disabled_by_default_and_has_no_effect_when_disabled(
    problem: Any, snapshot: Any
) -> None:
    from tests.fixtures.parallel import parallel_config

    assert parallel_config().cache.enabled is False  # rollback inmediato: enabled = false
    off = SequentialExecutor(CONFIG, snapshot, dataclasses.replace(cache_config(), enabled=False))
    run = off.run(requests_for(problem, workload(FRONTIER, FRONTIER), 2, seed=1))
    assert run.cache_metrics.hits == 0 and run.cache_metrics.entries == 0
    assert not run.manifest.cache_enabled


def test_capacity_is_bounded_and_evictions_are_reported(problem: Any, snapshot: Any) -> None:
    other = dataclasses.replace(FRONTIER, treatment=GROSS)
    request = base_request(problem, workload(FRONTIER, other))
    cache = OperationCache(context_of(snapshot), ResultCache(max_entries=1, max_bytes=10**8))
    run_portfolio(request, context_of(snapshot), cache=cache)
    assert cache.metrics.entries == 1 and cache.metrics.evictions == 1
    small = OperationCache(context_of(snapshot), ResultCache(max_entries=10, max_bytes=100))
    again = run_portfolio(request, context_of(snapshot), cache=small)
    assert small.metrics.entries == 0 and small.metrics.rejected == 2  # mayores que max_bytes
    assert all(o.cache_event is CacheEvent.MISS for o in again.operations)


# --------------------------------------------------------------- qué no se guarda (estados)


def _strategy(problem: Any, snapshot: Any) -> StrategyResult:
    ops = workload(OperationSpec(K.STRATEGY_MAX_SHARPE, NET))
    result = run_portfolio(base_request(problem, ops), context_of(snapshot))
    strategy = result.operations[0].result
    assert isinstance(strategy, StrategyResult)
    return strategy


def test_only_final_solver_states_are_cacheable(problem: Any, snapshot: Any) -> None:
    context = context_of(snapshot)
    op = OperationSpec(K.STRATEGY_MAX_SHARPE, NET)
    predicate = OperationCache(context, ResultCache(2, 10**6)).cacheable(op)
    strategy = _strategy(problem, snapshot)
    assert predicate(strategy)
    for status in SolverStatus:
        verdict = predicate(dataclasses.replace(strategy, status=status))
        assert verdict is (status in FINAL_STATUSES), status
    assert {
        SolverStatus.OPTIMAL,
        SolverStatus.OPTIMAL_INACCURATE,
        SolverStatus.INFEASIBLE,
    } == FINAL_STATUSES


def test_wall_clock_limits_and_mip_reports_are_never_cached(problem: Any, snapshot: Any) -> None:
    limited = dataclasses.replace(
        CONFIG, solver=dataclasses.replace(CONFIG.solver, time_limit_seconds=30.0)
    )
    context = context_of(snapshot, limited)
    op = OperationSpec(K.STRATEGY_MAX_SHARPE, NET)
    assert not OperationCache(context, ResultCache(2, 10**6)).cacheable(op)(
        _strategy(problem, snapshot)
    )
    mip = OperationSpec(K.EXACT_MIP_VALIDATION, GROSS, risk_aversion=4.0)
    assert not OperationCache(context_of(snapshot), ResultCache(2, 10**6)).cacheable(mip)(
        _strategy(problem, snapshot)
    )


def test_a_failing_operation_is_not_cached_and_keeps_its_error(problem: Any, snapshot: Any) -> None:
    ops = workload(OperationSpec(K.STRATEGY_VOL_TARGET, GROSS))  # sin límite de volatilidad
    request = base_request(problem, ops)
    context = context_of(snapshot)
    cache = OperationCache(context, ResultCache(4, 10**6))
    first = run_portfolio(request, context, cache=cache)
    second = run_portfolio(request, context, cache=cache)
    assert first.error is not None and second.error is not None
    assert first.error.error_type == second.error.error_type == "UnsupportedCombinationError"
    assert cache.metrics.stores == 0 and cache.metrics.misses == 2 and cache.metrics.hits == 0


def test_cache_config_validation() -> None:
    from portfolio_engine.exceptions import ConfigError

    assert CacheConfig(enabled=False, max_entries=1, max_bytes=1).enabled is False
    for bad in (
        {"max_entries": 0},
        {"max_bytes": 0},
        {"enabled": 1},
    ):
        with pytest.raises(ConfigError):
            dataclasses.replace(cache_config(), **bad)
