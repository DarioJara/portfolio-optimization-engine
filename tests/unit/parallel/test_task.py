"""D-02, D-13, P-01, P-09: ejecutor secuencial de referencia ``run_portfolio`` y ``TaskResult``.

Comprueba que la tarea solo *compone* los motores existentes (su resultado es idéntico al de
llamarlos directamente), que los estados de ejecución y de solver permanecen separados, que los
fallos se registran de forma explícita y que no hay contaminación entre carteras.
"""

from __future__ import annotations

import dataclasses
import pickle
from typing import Any

import pytest

from portfolio_engine.config import config_hash
from portfolio_engine.frontiers import (
    ContinuousFrontierEngine,
    ExactMIPValidator,
    GlobalCandidateFrontierEngine,
    HeuristicGapReport,
    StrategyOptimizer,
)
from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    FrontierMethod,
    FrontierScope,
    MultiScenarioMode,
    SolverStatus,
)
from portfolio_engine.models.frontier import CompositionFrontierResult, GlobalFrontierResult
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.optimizers import SCIP_AVAILABLE
from portfolio_engine.parallel.task import (
    ExecutionContext,
    ExecutionStatus,
    MarketSnapshot,
    PortfolioRequest,
    TaskResult,
    input_problems,
    run_portfolio,
)
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from portfolio_engine.scenarios import MultiScenarioResult
from tests.fixtures.parallel import (
    class_workloads,
    compare_results,
    reference_requests,
    reference_universes,
    requests_for,
    snapshot_of,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
GROSS, NET = CostTreatment.GROSS, CostTreatment.NET
RISK = FrontierMethod.RISK_AVERSION_GRID
K = OperationKind
EXPECTED_TYPES: dict[str, type] = {
    "W0": CompositionFrontierResult,
    "W1": GlobalFrontierResult,
    "W2": MultiScenarioResult,
    "W3": StrategyResult,
    "W4": StrategyResult,
    "W5": HeuristicGapReport,
}


@pytest.fixture(scope="module")
def reference() -> dict[str, tuple[PortfolioRequest, ExecutionContext, TaskResult]]:
    """Una cartera por workload de referencia, ejecutada una vez con ``run_portfolio``."""
    snapshots, by_universe = reference_requests(CONFIG, 1)
    contexts = {key: ExecutionContext.create(CONFIG, snap) for key, snap in snapshots.items()}
    out: dict[str, tuple[PortfolioRequest, ExecutionContext, TaskResult]] = {}
    for key, requests in by_universe.items():
        for request in requests:
            label = request.portfolio_id.rsplit("-", 1)[0]
            if label.startswith("W5") and not SCIP_AVAILABLE:
                continue
            out[label] = (request, contexts[key], run_portfolio(request, contexts[key]))
    return out


def _labels() -> list[str]:
    return list(class_workloads())


@pytest.mark.parametrize("label", _labels())
def test_every_workload_class_completes_with_typed_results(
    label: str, reference: dict[str, Any]
) -> None:
    if label not in reference:
        pytest.skip("PySCIPOpt (opcional, E-24) no instalado")
    request, _, result = reference[label]
    assert isinstance(result, TaskResult)
    assert result.execution_status is ExecutionStatus.COMPLETED and result.completed
    assert result.error is None
    assert result.portfolio_id == request.portfolio_id
    assert result.workload_hash == request.workload.workload_hash
    assert result.sequence_id is None and result.worker_pid is None  # los asigna el ejecutor
    assert [o.kind for o in result.operations] == [o.kind for o in request.workload.operations]
    assert [o.index for o in result.operations] == list(range(len(result.operations)))
    for outcome, operation in zip(result.operations, request.workload.operations, strict=True):
        assert outcome.completed and outcome.error is None and outcome.result is not None
        assert isinstance(outcome.result, EXPECTED_TYPES[operation.workload_class])
        assert outcome.elapsed_seconds >= 0.0


def test_task_results_carry_the_real_solver_states(reference: dict[str, Any]) -> None:
    """Los estados de solver llegan intactos; un resultado válido tiene un estado aceptado."""
    _, _, result = reference["W4-MAX-SHARPE"]
    strategy = result.operations[0].result
    assert isinstance(strategy, StrategyResult)
    assert strategy.status is SolverStatus.OPTIMAL and strategy.is_valid_solution
    _, _, frontier = reference["W0-GROSS-RISK"]
    points = frontier.operations[0].result.points  # type: ignore[union-attr]
    assert points and all(isinstance(point.status, SolverStatus) for point in points)


# --------------------------------------------------------- la tarea solo compone motores existentes


def _problem(
    request: PortfolioRequest, context: ExecutionContext, *, composition: bool = True
) -> Any:
    from portfolio_engine.frontiers import FrontierProblem

    snapshot = context.snapshot
    return FrontierProblem(
        request.portfolio_id,
        snapshot.base_scenario_id,
        snapshot.risk_model,
        snapshot.universe,
        request.state,
        request.spec,
        snapshot.costs,
        request.composition_asset_ids if composition else None,
    )


def test_a_frontier_task_equals_calling_the_engine_directly(reference: dict[str, Any]) -> None:
    request, context, result = reference["W0-NET-TARGET"]
    direct = ContinuousFrontierEngine(CONFIG).solve(
        _problem(request, context), NET, FrontierMethod.TARGET_RETURN_GRID
    )
    assert compare_results(result.operations[0].result, direct).differences == []


def test_a_global_frontier_task_equals_calling_the_engine_directly(
    reference: dict[str, Any],
) -> None:
    request, context, result = reference["W1-GLOBAL-NET"]
    direct = GlobalCandidateFrontierEngine(CONFIG).solve(
        _problem(request, context, composition=False), NET, RISK
    )
    assert compare_results(result.operations[0].result, direct).differences == []


@pytest.mark.parametrize(
    "label, call",
    [
        (
            "W3-MIN-CVAR",
            lambda opt, problem, context: opt.cvar(
                problem, GROSS, context.snapshot.return_scenarios, CVaRObjective.MIN_CVAR
            ),
        ),
        (
            "W4-MAX-SHARPE",
            lambda opt, problem, context: opt.max_sharpe(problem, NET),
        ),
        (
            "W4-VOL-TARGET",
            lambda opt, problem, context: opt.volatility_target(
                problem, GROSS, volatility_limit=0.2
            ),
        ),
        (
            "W4-ROBUST",
            lambda opt, problem, context: opt.robust(problem, GROSS, 3.0, covariance_scale_max=1.2),
        ),
    ],
)
def test_a_strategy_task_equals_calling_the_optimizer_directly(
    label: str, call: Any, reference: dict[str, Any]
) -> None:
    request, context, result = reference[label]
    direct = call(StrategyOptimizer(CONFIG), _problem(request, context), context)
    assert compare_results(result.operations[0].result, direct).differences == []


def test_a_multi_scenario_task_equals_calling_the_optimizer_directly(
    reference: dict[str, Any],
) -> None:
    from portfolio_engine.scenarios import MultiScenarioOptimizer, ScenarioEngine

    request, context, result = reference["W2-WORST-CASE"]
    snapshot = context.snapshot
    scenarios = ScenarioEngine(CONFIG).build(
        snapshot.risk_model,
        snapshot.universe,
        snapshot.costs,
        CONFIG.constraints,
        request.spec,
        snapshot.scenario_definitions,
    )
    direct = MultiScenarioOptimizer(CONFIG).solve_worst_case(
        _problem(request, context), scenarios, GROSS, 3.0
    )
    assert compare_results(result.operations[0].result, direct).differences == []


@pytest.mark.skipif(not SCIP_AVAILABLE, reason="PySCIPOpt (opcional, E-24) no instalado")
def test_an_exact_mip_task_equals_calling_the_validator_directly(
    reference: dict[str, Any],
) -> None:
    request, context, result = reference["W5-EXACT-MIP"]
    frontier = result.operations[0].result
    assert isinstance(frontier, GlobalFrontierResult)
    direct = ExactMIPValidator(CONFIG).validate_heuristic(
        _problem(request, context, composition=False),
        GROSS,
        4.0,
        context.snapshot.risk_model.asset_ids,
        frontier.candidates,
    )
    assert compare_results(result.operations[1].result, direct).differences == []


# ------------------------------------------------------------------------- validación de entradas


@pytest.fixture(scope="module")
def p8() -> tuple[Any, MarketSnapshot, ExecutionContext]:
    problem, snapshot = reference_universes(CONFIG)["p8"]
    return problem, snapshot, ExecutionContext.create(CONFIG, snapshot)


def _request(problem: Any, workload: WorkloadSpec, **changes: Any) -> PortfolioRequest:
    request = requests_for(problem, workload, 1, holdings=3, seed=2)[0]
    return dataclasses.replace(request, **changes) if changes else request


FRONTIER = WorkloadSpec((OperationSpec(K.FRONTIER_FIXED_COMPOSITION, GROSS, method=RISK),))
GLOBAL = WorkloadSpec((OperationSpec(K.GLOBAL_FRONTIER, GROSS, method=RISK),))


def _assert_rejected(result: TaskResult, fragment: str) -> None:
    assert result.execution_status is ExecutionStatus.FAILED_INPUT_VALIDATION
    assert result.operations == () and result.error is not None
    assert result.error.error_type == "InputValidationError"
    assert fragment in result.error.message
    assert result.error.operation_index is None


def test_input_validation_rejects_without_running_any_engine(p8: Any) -> None:
    problem, _, context = p8
    other_state = requests_for(problem, FRONTIER, 1, holdings=3, prefix="OTHER")[0].state
    cases = {
        "pertenece a 'OTHER0000'": _request(problem, FRONTIER, state=other_state),
        "composition_asset_ids contiene activos ausentes": _request(
            problem, FRONTIER, composition_asset_ids=("NOPE1", "NOPE2")
        ),
        "no vacía, única y ordenada": _request(
            problem, FRONTIER, composition_asset_ids=("A002", "A001")
        ),
        "composition_asset_ids debe ser None": _request(
            problem, GLOBAL, composition_asset_ids=problem.risk_model.asset_ids[:3]
        ),
        "no contiene ninguna operación": _request(problem, WorkloadSpec(())),
        "escenarios de retorno": _request(
            problem,
            WorkloadSpec(
                (OperationSpec(K.STRATEGY_CVAR, GROSS, cvar_objective=CVaRObjective.MIN_CVAR),)
            ),
        ),
    }
    snapshot = context.snapshot
    no_returns = ExecutionContext.create(
        CONFIG, dataclasses.replace(snapshot, return_scenarios=None)
    )
    for fragment, request in cases.items():
        used = no_returns if "retorno" in fragment else context
        _assert_rejected(run_portfolio(request, used), fragment)


def test_a_mandate_of_another_portfolio_is_rejected(p8: Any) -> None:
    from tests.fixtures.problems import spec_with

    problem, _, context = p8
    request = _request(problem, FRONTIER, spec=spec_with(portfolio_id="OTHER"))
    _assert_rejected(run_portfolio(request, context), "El mandato pertenece a 'OTHER'")


def test_multi_scenario_requires_scenario_definitions(p8: Any) -> None:
    problem, snapshot, _ = p8
    workload = WorkloadSpec(
        (
            OperationSpec(
                K.MULTI_SCENARIO,
                GROSS,
                mode=MultiScenarioMode.WORST_CASE,
                risk_aversion=3.0,
            ),
        )
    )
    problems = input_problems(_request(problem, workload), snapshot)
    assert any("no define escenarios" in message for message in problems)


def test_scenario_search_with_an_explicit_composition_is_rejected(p8: Any) -> None:
    problem, snapshot, _ = p8
    workload = WorkloadSpec(
        (
            OperationSpec(
                K.MULTI_SCENARIO,
                GROSS,
                mode=MultiScenarioMode.SCENARIO_INDEPENDENT,
                method=RISK,
                scope=FrontierScope.GLOBAL_CANDIDATE_FRONTIER,
            ),
        )
    )
    request = _request(problem, workload, composition_asset_ids=problem.risk_model.asset_ids[:3])
    snapshot = dataclasses.replace(
        snapshot,
        scenario_definitions=snapshot_of(problem, with_scenarios=True).scenario_definitions,
    )
    assert any("debe ser None" in message for message in input_problems(request, snapshot))


# ------------------------------------------------------------------------- fallos explícitos


def test_an_engine_exception_is_recorded_and_keeps_completed_work(p8: Any) -> None:
    """VolatilityTarget sin límite: ``UnsupportedCombinationError`` del motor, no un fallo mudo."""
    problem, _, context = p8
    workload = WorkloadSpec(
        (
            OperationSpec(K.FRONTIER_FIXED_COMPOSITION, GROSS, method=RISK),
            OperationSpec(K.STRATEGY_VOL_TARGET, GROSS),  # sin volatility_limit en spec ni op
            OperationSpec(K.STRATEGY_MAX_SHARPE, GROSS),  # no debe ejecutarse
        )
    )
    result = run_portfolio(_request(problem, workload), context)
    assert result.execution_status is ExecutionStatus.FAILED_EXCEPTION and not result.completed
    assert result.error is not None
    assert result.error.error_type == "UnsupportedCombinationError"
    assert "VolatilityLimit" in result.error.message
    assert result.error.operation_index == 1 and "Traceback" in result.error.traceback
    assert [o.kind for o in result.operations] == [
        K.FRONTIER_FIXED_COMPOSITION,
        K.STRATEGY_VOL_TARGET,
    ]
    assert result.operations[0].completed and result.operations[0].result is not None
    assert not result.operations[1].completed and result.operations[1].result is None
    assert result.operations[1].error == result.error


def test_solver_states_are_not_execution_failures(p8: Any) -> None:
    """P-01: un problema infactible es un resultado COMPLETED con estado de solver INFEASIBLE."""
    problem, _, context = p8
    workload = WorkloadSpec((OperationSpec(K.STRATEGY_VOL_TARGET, GROSS, volatility_limit=1e-6),))
    result = run_portfolio(_request(problem, workload), context)
    assert result.execution_status is ExecutionStatus.COMPLETED and result.error is None
    strategy = result.operations[0].result
    assert isinstance(strategy, StrategyResult)
    assert strategy.status is SolverStatus.INFEASIBLE and not strategy.is_valid_solution


def test_a_portfolio_without_holdings_reports_the_engine_outcome(p8: Any) -> None:
    """Una cartera sin posiciones no cae en un estado inventado: lo decide el motor."""
    from portfolio_engine.models.portfolio import CurrentPortfolioState
    from portfolio_engine.models.universe_index import AssetIndex

    problem, _, context = p8
    empty = CurrentPortfolioState.from_weights(
        "EMPTY", {}, AssetIndex.from_universe(problem.universe), None
    )
    request = PortfolioRequest("EMPTY", empty, None, GLOBAL)
    result = run_portfolio(request, context)
    assert result.execution_status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED_EXCEPTION}
    assert result.portfolio_id == "EMPTY"


# ------------------------------------------------------------------------------- identidad


def test_task_identity_is_deterministic_and_sensitive_to_every_input(p8: Any) -> None:
    problem, snapshot, context = p8
    request = _request(problem, FRONTIER)
    twin = _request(problem, FRONTIER)
    assert (
        context.task_id(request) == context.task_id(twin) == run_portfolio(request, context).task_id
    )

    other_holdings = requests_for(problem, FRONTIER, 1, holdings=3, seed=99)[0]
    changed = {
        "cartera actual": other_holdings,
        "workload": _request(problem, GLOBAL),
        "composición": _request(
            problem, FRONTIER, composition_asset_ids=problem.risk_model.asset_ids[:4]
        ),
    }
    for name, other in changed.items():
        assert context.task_id(other) != context.task_id(request), name

    tighter = dataclasses.replace(
        CONFIG, solver=dataclasses.replace(CONFIG.solver, eps_abs=CONFIG.solver.eps_abs / 10)
    )
    other_config = ExecutionContext.create(tighter, snapshot)
    assert other_config.config_hash != context.config_hash == config_hash(CONFIG)
    assert other_config.task_id(request) != context.task_id(request)

    other_snapshot = ExecutionContext.create(CONFIG, snapshot_of(problem))
    assert other_snapshot.snapshot_key != context.snapshot_key  # sin escenarios de retorno
    assert other_snapshot.task_id(request) != context.task_id(request)


def test_the_snapshot_key_is_a_content_hash(p8: Any) -> None:
    problem, snapshot, _ = p8
    rebuilt = snapshot_of(problem, return_periods=300, seed=11)
    assert rebuilt.snapshot_key == snapshot.snapshot_key
    assert snapshot_of(problem, return_periods=300, seed=12).snapshot_key != snapshot.snapshot_key


# --------------------------------------------------------------- aislamiento y serialización


def test_running_other_portfolios_in_between_does_not_change_a_result(p8: Any) -> None:
    """Ausencia de contaminación: A, B, A ⇒ las dos A son idénticas y el snapshot no cambia."""
    problem, snapshot, context = p8
    key_before = context.snapshot.snapshot_key
    a = _request(problem, GLOBAL)
    b = requests_for(problem, GLOBAL, 1, holdings=3, seed=77)[0]
    first = run_portfolio(a, context)
    run_portfolio(b, context)
    second = run_portfolio(a, context)
    assert compare_results(first, second).differences == []
    assert snapshot.snapshot_key == key_before


def test_requests_snapshot_and_results_survive_pickle(reference: dict[str, Any]) -> None:
    """Los workers reciben solicitudes y snapshot y devuelven resultados por ``pickle``."""
    for label, (request, context, result) in reference.items():
        restored = pickle.loads(pickle.dumps(result))
        assert compare_results(result, restored).differences == [], label
        assert pickle.loads(pickle.dumps(request)).request_hash() == request.request_hash()
        assert pickle.loads(pickle.dumps(context.snapshot)).snapshot_key == context.snapshot_key


def test_task_dataclasses_are_immutable(reference: dict[str, Any]) -> None:
    request, _, result = reference["W0-GROSS-RISK"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.execution_status = ExecutionStatus.FAILED_EXCEPTION
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.portfolio_id = "X"


def test_request_hash_covers_mandate_and_state(p8: Any) -> None:
    from tests.fixtures.problems import spec_with

    problem, _, _ = p8
    base = _request(problem, FRONTIER)
    with_spec = dataclasses.replace(base, spec=spec_with(portfolio_id=base.portfolio_id))
    tighter = dataclasses.replace(
        base, spec=spec_with(portfolio_id=base.portfolio_id, max_turnover=0.2)
    )
    hashes = {base.request_hash(), with_spec.request_hash(), tighter.request_hash()}
    assert len(hashes) == 3


def test_hashing_accepts_missing_data_marked_as_nan(p8: Any) -> None:
    """``NaN`` en los metadatos del universo (dato ausente) no puede romper la identidad."""
    from portfolio_engine.models.asset import Universe
    from portfolio_engine.parallel.task import stable_form
    from portfolio_engine.utils.hashing import canonical_json

    problem, snapshot, _ = p8
    assets = list(problem.universe)
    with_nan = Universe([dataclasses.replace(assets[0], adv=float("nan")), *assets[1:]])
    changed = dataclasses.replace(snapshot, universe=with_nan)
    assert (
        changed.snapshot_key != snapshot.snapshot_key
    )  # el dato ausente forma parte de la identidad
    assert changed.snapshot_key == dataclasses.replace(snapshot, universe=with_nan).snapshot_key
    form = stable_form({"a": float("nan"), "b": (1.5, float("inf")), "c": SolverStatus.OPTIMAL})
    assert canonical_json(form)  # serializable sin NaN literal
    assert stable_form(float("nan")) != stable_form(0.0)
