"""Unidad de trabajo por cartera y ejecutor secuencial de referencia (decisiones D-01, D-02, D-13).

:func:`run_portfolio` compone **exclusivamente motores ya implementados** (B1-B4) según el
:class:`~portfolio_engine.parallel.workload.WorkloadSpec` de la cartera y devuelve un
:class:`TaskResult` tipado. No contiene lógica matemática: no cambia algoritmos, tolerancias,
restricciones ni estados de ningún motor. Es la referencia con la que se contrasta el ejecutor
paralelo (equivalencia T1) y la función que ejecutan los workers.

Invariantes de diseño:

* **Aislamiento entre tareas.** Cada tarea crea sus propios motores y objetos de trabajo; lo único
  compartido es el :class:`MarketSnapshot` inmutable y la configuración. Nada sobrevive a la tarea.
* **Estados separados.** ``ExecutionStatus`` describe la *ejecución* de la tarea; los estados de
  solver (``SolverStatus``, ``outcome``) viajan intactos dentro de los resultados de cada motor y
  nunca se reetiquetan (requisito propuesto P-01).
* **Fallos explícitos.** Una entrada inválida se detecta antes de ejecutar nada
  (``FAILED_INPUT_VALIDATION``); una excepción de un motor se registra con su tipo y mensaje
  (``FAILED_EXCEPTION``), conserva lo ya calculado y no afecta a otras carteras.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from portfolio_engine.cache import CacheEvent
from portfolio_engine.config import EngineConfig, ScenarioDefinition, config_hash
from portfolio_engine.exceptions import PortfolioEngineError
from portfolio_engine.frontiers import (
    ContinuousFrontierEngine,
    ExactMIPValidator,
    FrontierProblem,
    GlobalCandidateFrontierEngine,
    HeuristicGapReport,
    StrategyOptimizer,
)
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.composition import CandidateComposition
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.cvar import ReturnScenarioSet
from portfolio_engine.models.enums import FrontierScope, MultiScenarioMode, MuUncertaintyKind
from portfolio_engine.models.frontier import CompositionFrontierResult, GlobalFrontierResult
from portfolio_engine.models.portfolio import CurrentPortfolioState, PortfolioSpec
from portfolio_engine.models.risk_model import RiskModel
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.optimizers.formulations.robust import MuUncertaintySet
from portfolio_engine.parallel.operation_cache import OperationCache, stable_form
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from portfolio_engine.scenarios import MultiScenarioOptimizer, MultiScenarioResult, ScenarioEngine
from portfolio_engine.utils.hashing import canonical_json, hash_float_array, sha256_hex

#: Resultado de una operación: el objeto que devuelve el motor, sin transformar.
OperationResult = (
    CompositionFrontierResult
    | GlobalFrontierResult
    | StrategyResult
    | MultiScenarioResult
    | HeuristicGapReport
)


class ExecutionStatus(StrEnum):
    """Estado de la **ejecución** de una tarea (no del solver; requisito propuesto P-01).

    ``TIMED_OUT``, ``CANCELLED`` y ``SKIPPED_BY_RESUME`` (plazos, cancelación y reanudación)
    pertenecen al Bloque 5.4 y no existen todavía.
    """

    COMPLETED = "COMPLETED"
    FAILED_INPUT_VALIDATION = "FAILED_INPUT_VALIDATION"
    FAILED_EXCEPTION = "FAILED_EXCEPTION"
    WORKER_CRASHED = "WORKER_CRASHED"


@dataclass(frozen=True, eq=False, slots=True)
class MarketSnapshot:
    """Datos de mercado inmutables que comparten todas las carteras de una ejecución.

    Attributes:
        risk_model: ``mu`` y ``Sigma`` globales (``MuSigmaVersion``).
        universe: metadatos del universo (límites por activo, grupos, banderas).
        costs: costes unitarios de compra/venta (``None`` si no hay datos de coste).
        return_scenarios: escenarios de retorno para CVaR (``None`` si no se usa CVaR).
        scenario_definitions: definiciones de escenario del multiescenario (vacío si no se usa).
        base_scenario_id: ``ScenarioID`` del escenario base de las fronteras y estrategias.
        market_data_timestamp: fecha/hora de los datos de mercado (``MarketDataTimestamp``, §31)
            tal como la informa el origen de datos; ``None`` = no informada (la clave de caché lo
            registra de forma explícita).
    """

    risk_model: RiskModel
    universe: Universe
    costs: AssetCostVector | None
    return_scenarios: ReturnScenarioSet | None
    scenario_definitions: tuple[ScenarioDefinition, ...]
    base_scenario_id: str
    market_data_timestamp: str | None = None

    @property
    def snapshot_key(self) -> str:
        """Identidad de contenido del snapshot (hash canónico de todos sus datos)."""
        costs = None
        if self.costs is not None:
            costs = {
                "asset_ids": list(self.costs.asset_ids),
                "buy": hash_float_array(self.costs.buy_costs),
                "sell": hash_float_array(self.costs.sell_costs),
                "sources": [source.name for source in self.costs.sources],
            }
        returns = None
        if self.return_scenarios is not None:
            returns = {
                "asset_ids": list(self.return_scenarios.asset_ids),
                "returns": hash_float_array(self.return_scenarios.returns),
                "weights": hash_float_array(self.return_scenarios.weights),
                "source": self.return_scenarios.source.name,
                "weighting": self.return_scenarios.weighting.name,
            }
        payload = {
            "mu_sigma_version": self.risk_model.mu_sigma_version,
            "universe": [stable_form(asset) for asset in self.universe],
            "costs": costs,
            "return_scenarios": returns,
            "scenario_definitions": [stable_form(d) for d in self.scenario_definitions],
            "base_scenario_id": self.base_scenario_id,
            "market_data_timestamp": self.market_data_timestamp,
        }
        return sha256_hex(canonical_json(payload))


@dataclass(frozen=True, eq=False, slots=True)
class PortfolioRequest:
    """Solicitud de optimización de una cartera (datos de la cartera + qué ejecutar).

    ``composition_asset_ids`` es opcional: ``None`` usa los activos de la cartera actual (las
    operaciones de búsqueda de candidatos exigen ``None``, véase :func:`input_problems`).
    """

    portfolio_id: str
    state: CurrentPortfolioState
    spec: PortfolioSpec | None
    workload: WorkloadSpec
    composition_asset_ids: tuple[str, ...] | None = None

    def request_hash(self) -> str:
        """Hash canónico de la solicitud (cartera, mandato, composición y workload)."""
        spec = None if self.spec is None else stable_form(self.spec)
        payload = {
            "portfolio_id": self.portfolio_id,
            "state_hash": self.state.state_hash,
            "state_nav": self.state.nav,
            "spec": spec,
            "composition": None
            if self.composition_asset_ids is None
            else list(self.composition_asset_ids),
            "workload": self.workload.workload_hash,
        }
        return sha256_hex(canonical_json(payload))


@dataclass(frozen=True, eq=False, slots=True)
class ExecutionContext:
    """Snapshot + configuración de motor + sus hashes, calculados una sola vez por ejecución."""

    config: EngineConfig
    snapshot: MarketSnapshot
    config_hash: str
    snapshot_key: str

    @classmethod
    def create(cls, config: EngineConfig, snapshot: MarketSnapshot) -> ExecutionContext:
        """Contexto de ejecución (calcula ``ConfigHash`` y ``snapshot_key``)."""
        return cls(config, snapshot, config_hash(config), snapshot.snapshot_key)

    def task_id(self, request: PortfolioRequest) -> str:
        """Identidad determinista de la tarea: solicitud + configuración + snapshot."""
        payload = {
            "request": request.request_hash(),
            "config_hash": self.config_hash,
            "snapshot_key": self.snapshot_key,
        }
        return sha256_hex(canonical_json(payload))


@dataclass(frozen=True, eq=False, slots=True)
class TaskError:
    """Error de una tarea u operación (tipo, mensaje y traza; la traza es diagnóstico)."""

    error_type: str
    message: str
    operation_index: int | None
    traceback: str


@dataclass(frozen=True, eq=False, slots=True)
class OperationOutcome:
    """Resultado de una operación: el objeto del motor (sin transformar) o su error."""

    index: int
    kind: OperationKind
    completed: bool
    result: OperationResult | None
    error: TaskError | None
    elapsed_seconds: float
    cache_event: CacheEvent = CacheEvent.DISABLED


@dataclass(frozen=True, eq=False, slots=True)
class TaskResult:
    """Resultado tipado de una cartera.

    Attributes:
        task_id: identidad determinista (solicitud + ``ConfigHash`` + ``snapshot_key``).
        portfolio_id: ``PortfolioID``.
        workload_hash: hash del workload ejecutado.
        sequence_id: posición canónica en la ejecución (la asigna el ejecutor; ``None`` si la
            tarea se ejecutó directamente con :func:`run_portfolio`).
        execution_status: estado de la ejecución de la tarea.
        operations: una entrada por operación intentada, en orden. Las no ejecutadas por un fallo
            anterior no aparecen.
        error: causa de un estado distinto de ``COMPLETED``.
        elapsed_seconds: tiempo de pared de la tarea (diagnóstico; no es parte del cálculo).
        worker_pid: proceso que la ejecutó (diagnóstico; ``None`` fuera de un worker).
    """

    task_id: str
    portfolio_id: str
    workload_hash: str
    sequence_id: int | None
    execution_status: ExecutionStatus
    operations: tuple[OperationOutcome, ...]
    error: TaskError | None
    elapsed_seconds: float
    worker_pid: int | None

    @property
    def completed(self) -> bool:
        """``True`` si todas las operaciones terminaron sin excepción."""
        return self.execution_status is ExecutionStatus.COMPLETED


# ----------------------------------------------------------------- validación de entradas


def _identity_problems(request: PortfolioRequest) -> list[str]:
    found: list[str] = []
    if not request.portfolio_id:
        found.append("PortfolioID vacío.")
    if request.state.portfolio_id != request.portfolio_id:
        found.append(
            f"El estado actual pertenece a '{request.state.portfolio_id}', no a "
            f"'{request.portfolio_id}'."
        )
    if request.spec is not None and request.spec.portfolio_id != request.portfolio_id:
        found.append(
            f"El mandato pertenece a '{request.spec.portfolio_id}', no a '{request.portfolio_id}'."
        )
    return found


def _universe_problems(request: PortfolioRequest, snapshot: MarketSnapshot) -> list[str]:
    found: list[str] = []
    universe_ids = set(snapshot.risk_model.asset_ids)
    unknown_held = sorted(set(request.state.asset_ids) - universe_ids)
    if unknown_held:
        found.append(f"Activos de la cartera actual ausentes del snapshot: {unknown_held}")
    ids = request.composition_asset_ids
    if ids is not None:
        if not ids or list(ids) != sorted(set(ids)):
            found.append("composition_asset_ids debe ser no vacía, única y ordenada.")
        unknown = sorted(set(ids) - universe_ids)
        if unknown:
            found.append(f"composition_asset_ids contiene activos ausentes del snapshot: {unknown}")
    return found


def _workload_data_problems(request: PortfolioRequest, snapshot: MarketSnapshot) -> list[str]:
    found: list[str] = []
    workload = request.workload
    if workload.requires_return_scenarios() and snapshot.return_scenarios is None:
        found.append("El workload usa CVaR y el snapshot no contiene escenarios de retorno.")
    if workload.requires_scenario_definitions() and not snapshot.scenario_definitions:
        found.append("El workload usa multiescenario y el snapshot no define escenarios.")
    for position, operation in enumerate(workload.operations):
        if operation.mu_half_width is not None:
            missing = sorted(
                set(_composition_ids(request)) - {a for a, _ in operation.mu_half_width}
            )
            if missing:
                found.append(
                    f"operations[{position}] ({operation.kind.value}): 'mu_half_width' no cubre "
                    f"los activos de la composición: {missing}"
                )
    if request.composition_asset_ids is not None:
        for position, operation in enumerate(workload.operations):
            searches = operation.kind is OperationKind.GLOBAL_FRONTIER or (
                operation.kind is OperationKind.MULTI_SCENARIO
                and operation.scope is FrontierScope.GLOBAL_CANDIDATE_FRONTIER
            )
            if searches:
                found.append(
                    f"operations[{position}] ({operation.kind.value}): la búsqueda de candidatos "
                    "parte de la cartera actual; composition_asset_ids debe ser None."
                )
    return found


def input_problems(request: PortfolioRequest, snapshot: MarketSnapshot) -> tuple[str, ...]:
    """Problemas que impiden ejecutar ``request`` con ``snapshot`` (vacío si es ejecutable).

    Detecta, sin ejecutar ningún motor: workload inválido, incoherencias de identidad, activos
    fuera del universo y datos de mercado que el workload necesita y el snapshot no contiene.
    """
    return (
        *request.workload.problems(),
        *_identity_problems(request),
        *_universe_problems(request, snapshot),
        *_workload_data_problems(request, snapshot),
    )


# ---------------------------------------------------------------------- ejecución de motores


def _problem(
    request: PortfolioRequest, snapshot: MarketSnapshot, *, with_composition: bool
) -> FrontierProblem:
    """Problema de un escenario base para ``request`` (objetos nuevos por tarea)."""
    return FrontierProblem(
        portfolio_id=request.portfolio_id,
        scenario_id=snapshot.base_scenario_id,
        risk_model=snapshot.risk_model,
        universe=snapshot.universe,
        state=request.state,
        spec=request.spec,
        costs=snapshot.costs,
        composition_asset_ids=request.composition_asset_ids if with_composition else None,
    )


def _run_multi_scenario(
    operation: OperationSpec, request: PortfolioRequest, context: ExecutionContext
) -> MultiScenarioResult:
    config, snapshot = context.config, context.snapshot
    scenarios = ScenarioEngine(config).build(
        snapshot.risk_model,
        snapshot.universe,
        snapshot.costs,
        config.constraints,
        request.spec,
        snapshot.scenario_definitions,
    )
    optimizer = MultiScenarioOptimizer(config)
    mode = operation.mode
    scope = operation.scope or FrontierScope.CONTINUOUS_FRONTIER
    problem = _problem(
        request, snapshot, with_composition=scope is not FrontierScope.GLOBAL_CANDIDATE_FRONTIER
    )
    if mode is MultiScenarioMode.SCENARIO_INDEPENDENT:
        assert operation.method is not None  # garantizado por WorkloadSpec.problems()
        return optimizer.solve_independent(
            problem,
            scenarios,
            operation.treatment,
            operation.method,
            scope=scope,
            include_max_sharpe=operation.include_max_sharpe,
        )
    assert operation.risk_aversion is not None  # garantizado por WorkloadSpec.problems()
    if mode is MultiScenarioMode.EXPECTED_SCENARIO_UTILITY:
        return optimizer.solve_expected_utility(
            problem, scenarios, operation.treatment, operation.risk_aversion
        )
    if mode is MultiScenarioMode.WORST_CASE:
        return optimizer.solve_worst_case(
            problem, scenarios, operation.treatment, operation.risk_aversion
        )
    return optimizer.solve_base_with_stress(
        problem, scenarios, operation.treatment, operation.risk_aversion
    )


def _run_operation(
    operation: OperationSpec,
    request: PortfolioRequest,
    context: ExecutionContext,
    earlier: tuple[OperationOutcome, ...],
) -> OperationResult:
    """Ejecuta una operación con motores nuevos (aislamiento entre tareas)."""
    config, snapshot = context.config, context.snapshot
    kind = operation.kind
    if kind is OperationKind.FRONTIER_FIXED_COMPOSITION:
        assert operation.method is not None
        return ContinuousFrontierEngine(config).solve(
            _problem(request, snapshot, with_composition=True),
            operation.treatment,
            operation.method,
        )
    if kind is OperationKind.GLOBAL_FRONTIER:
        assert operation.method is not None
        return GlobalCandidateFrontierEngine(config).solve(
            _problem(request, snapshot, with_composition=False),
            operation.treatment,
            operation.method,
        )
    if kind is OperationKind.MULTI_SCENARIO:
        return _run_multi_scenario(operation, request, context)
    problem = _problem(request, snapshot, with_composition=True)
    optimizer = StrategyOptimizer(config)
    if kind is OperationKind.STRATEGY_CVAR:
        assert operation.cvar_objective is not None and snapshot.return_scenarios is not None
        return optimizer.cvar(
            problem,
            operation.treatment,
            snapshot.return_scenarios,
            operation.cvar_objective,
            max_cvar=operation.max_cvar,
            risk_aversion=operation.risk_aversion,
        )
    if kind is OperationKind.STRATEGY_ROBUST:
        assert operation.risk_aversion is not None
        return optimizer.robust(
            problem,
            operation.treatment,
            operation.risk_aversion,
            mu_set=_mu_set(operation, request),
            covariance_scale_max=operation.covariance_scale_max,
        )
    if kind is OperationKind.STRATEGY_MAX_SHARPE:
        return optimizer.max_sharpe(
            problem, operation.treatment, volatility_limit=operation.volatility_limit
        )
    if kind is OperationKind.STRATEGY_VOL_TARGET:
        return optimizer.volatility_target(
            problem,
            operation.treatment,
            volatility_limit=operation.volatility_limit,
            risk_aversion=operation.risk_aversion,
        )
    return _run_exact_mip(operation, request, context, earlier)


def _composition_ids(request: PortfolioRequest) -> tuple[str, ...]:
    """Activos de la composición que optimizan las estrategias (explícita o cartera actual)."""
    if request.composition_asset_ids is not None:
        return request.composition_asset_ids
    return tuple(request.state.asset_ids)


def _mu_set(operation: OperationSpec, request: PortfolioRequest) -> MuUncertaintySet | None:
    """Conjunto ``BOX`` de ``μ`` alineado con la composición (``None`` si no se especificó)."""
    if operation.mu_half_width is None:
        return None
    by_asset = dict(operation.mu_half_width)
    half_width = np.array([by_asset[asset_id] for asset_id in _composition_ids(request)])
    return MuUncertaintySet(MuUncertaintyKind.BOX, half_width=half_width)


def _run_exact_mip(
    operation: OperationSpec,
    request: PortfolioRequest,
    context: ExecutionContext,
    earlier: tuple[OperationOutcome, ...],
) -> HeuristicGapReport:
    assert operation.risk_aversion is not None
    candidates: tuple[CandidateComposition, ...] | None = None
    for outcome in earlier:
        if outcome.kind is OperationKind.GLOBAL_FRONTIER and isinstance(
            outcome.result, GlobalFrontierResult
        ):
            candidates = outcome.result.candidates
    if candidates is None:
        raise PortfolioEngineError(
            "EXACT_MIP_VALIDATION requiere las composiciones de una GLOBAL_FRONTIER completada."
        )
    snapshot = context.snapshot
    return ExactMIPValidator(context.config).validate_heuristic(
        _problem(request, snapshot, with_composition=False),
        operation.treatment,
        operation.risk_aversion,
        snapshot.risk_model.asset_ids,
        candidates,
        volatility_limit=operation.volatility_limit,
    )


def _error(error: BaseException, index: int | None) -> TaskError:
    return TaskError(
        error_type=type(error).__name__,
        message=str(error),
        operation_index=index,
        traceback="".join(traceback.format_exception(error)),
    )


def run_portfolio(
    request: PortfolioRequest,
    context: ExecutionContext,
    *,
    cache: OperationCache | None = None,
) -> TaskResult:
    """Ejecuta el workload de ``request`` de forma secuencial y devuelve su :class:`TaskResult`.

    Nunca lanza por fallos de la cartera: los registra en el resultado. Las operaciones se
    ejecutan en orden y comparten únicamente el ``MarketSnapshot`` inmutable y los resultados de
    operaciones anteriores de la **misma** cartera (p. ej. las composiciones candidatas que usa la
    validación EXACT_MIP). Tras la primera excepción no se ejecutan las operaciones restantes.

    Con ``cache`` (por worker; ``None`` = desactivada) cada operación se resuelve a través de la
    caché de resultados: un acierto no invoca ningún motor (véase ``operation_cache``).
    """
    started = time.perf_counter()
    task_id = context.task_id(request)
    workload_hash = request.workload.workload_hash

    def finish(
        status: ExecutionStatus,
        operations: tuple[OperationOutcome, ...],
        error: TaskError | None,
    ) -> TaskResult:
        return TaskResult(
            task_id=task_id,
            portfolio_id=request.portfolio_id,
            workload_hash=workload_hash,
            sequence_id=None,
            execution_status=status,
            operations=operations,
            error=error,
            elapsed_seconds=time.perf_counter() - started,
            worker_pid=None,
        )

    problems = input_problems(request, context.snapshot)
    if problems:
        error = TaskError("InputValidationError", "; ".join(problems), None, "")
        return finish(ExecutionStatus.FAILED_INPUT_VALIDATION, (), error)
    outcomes: list[OperationOutcome] = []
    for index, operation in enumerate(request.workload.operations):
        op_started = time.perf_counter()
        event = CacheEvent.DISABLED
        try:
            if cache is None:
                result = _run_operation(operation, request, context, tuple(outcomes))
            else:
                done = tuple(outcomes)

                def compute(
                    op: OperationSpec = operation, prior: tuple[OperationOutcome, ...] = done
                ) -> OperationResult:
                    return _run_operation(op, request, context, prior)

                result, event = cache.run(request, index, compute)
        except Exception as error:  # límite de aislamiento: un fallo no afecta a otras carteras
            failure = _error(error, index)
            outcomes.append(
                OperationOutcome(
                    index, operation.kind, False, None, failure, time.perf_counter() - op_started
                )
            )
            return finish(ExecutionStatus.FAILED_EXCEPTION, tuple(outcomes), failure)
        outcomes.append(
            OperationOutcome(
                index, operation.kind, True, result, None, time.perf_counter() - op_started, event
            )
        )
    return finish(ExecutionStatus.COMPLETED, tuple(outcomes), None)
