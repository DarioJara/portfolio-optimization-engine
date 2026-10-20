"""Caché de resultados de operaciones de cartera (MASTER_SPEC §62; CCH-001…CCH-005).

Nivel elegido: **por worker y por operación** del ``WorkloadSpec``. Es el nivel donde el resultado
es
un objeto completo (``CompositionFrontierResult``, ``GlobalFrontierResult``, ``StrategyResult``,
``MultiScenarioResult``) y donde todas las entradas que lo determinan son conocidas antes de
resolver.

* La clave (:class:`~portfolio_engine.cache.keys.CacheKey`) reúne los componentes oficiales de
  CCH-002 más ``PortfolioID``, la operación (con sus parámetros) y la huella de contenido de los
  datos
  de mercado. Se calcula **solo** con la caché activada.
* ``ConstraintHash``: el ``ConstraintHash`` compilado depende de la composición y no existe antes de
  resolver; aquí identifica las **entradas** de las restricciones (configuración de restricciones,
  mandato de la cartera, composición explícita y NAV). Dos carteras o dos mandatos distintos nunca
  comparten clave.
* Un acierto sustituye por completo la llamada al motor (cero llamadas al solver); el objeto
  devuelto
  es una copia nueva (véase ``ResultCache``).
* No se guardan resultados con estados no definitivos (límite de iteraciones o de tiempo, error
  numérico…), ni nada cuando algún límite de **tiempo de pared** del solver está configurado (el
  resultado dependería de la carga de la máquina), ni los informes de ``EXACT_MIP`` (cota, nodos y
  *gap* dependen de límites de tiempo).
* Expectativa realista: como ``CurrentPortfolioStateHash`` y ``PortfolioID`` forman parte de la
  clave
  y los ``PortfolioID`` de una ejecución son únicos, los aciertos solo aparecen con operaciones
  repetidas dentro de un workload o con reejecuciones en un worker de larga vida; no se espera
  acierto
  entre carteras distintas.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Any, Protocol, TypeVar

from portfolio_engine.cache import UNSPECIFIED, CacheEvent, CacheKey, ResultCache
from portfolio_engine.cache.result_cache import CacheMetrics
from portfolio_engine.models.enums import FrontierScope, SolverStatus
from portfolio_engine.models.frontier import CompositionFrontierResult, GlobalFrontierResult
from portfolio_engine.models.portfolio import composition_hash
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.parallel.workload import OperationKind, OperationSpec
from portfolio_engine.scenarios import MultiScenarioResult
from portfolio_engine.utils.hashing import (
    canonical_float,
    canonical_json,
    hash_float_array,
    sha256_hex,
)


class _Request(Protocol):
    """Lo que la caché necesita de una ``PortfolioRequest`` (evita importar ``task``)."""

    @property
    def portfolio_id(self) -> str: ...

    @property
    def state(self) -> Any: ...

    @property
    def spec(self) -> Any: ...

    @property
    def workload(self) -> Any: ...

    @property
    def composition_asset_ids(self) -> tuple[str, ...] | None: ...


class _Context(Protocol):
    """Lo que la caché necesita de un ``ExecutionContext``."""

    @property
    def config(self) -> Any: ...

    @property
    def snapshot(self) -> Any: ...

    @property
    def config_hash(self) -> str: ...

    @property
    def snapshot_key(self) -> str: ...


T = TypeVar("T")

#: Estados definitivos: el motor decidió (óptimo, óptimo impreciso o infactible). Los demás
#: (límites, errores numéricos, desconocido) pueden depender de la carga o de reintentos.
FINAL_STATUSES = frozenset(
    {SolverStatus.OPTIMAL, SolverStatus.OPTIMAL_INACCURATE, SolverStatus.INFEASIBLE}
)
NOT_USED = "NONE"


def stable_form(value: object) -> object:
    """Forma canónica de un dato de entrada para hashing (admite ``NaN`` e infinitos).

    Dataclasses → diccionarios; enums → nombre; tuplas y mapeos → estructuras ordenadas; floats →
    ``float.hex`` exacto (a diferencia de ``canonical_json``, no rechaza ``NaN``, que en los
    metadatos del universo significa «dato ausente»).
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: stable_form(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, float):
        return canonical_float(value)
    if isinstance(value, Mapping):
        return {str(key): stable_form(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [stable_form(item) for item in value]
    return value


def hash_of(value: object) -> str:
    """SHA-256 canónico de ``stable_form(value)``."""
    return sha256_hex(canonical_json(stable_form(value)))


def _statuses_final(result: object) -> bool:
    """``True`` si todos los estados de solver del resultado son definitivos."""
    if isinstance(result, CompositionFrontierResult):
        return all(point.status in FINAL_STATUSES for point in result.points)
    if isinstance(result, GlobalFrontierResult):
        # ``continuous`` no forma parte de ``composition_results``: se comprueba aparte.
        return (
            all(point.point.status in FINAL_STATUSES for point in result.points)
            and all(_statuses_final(inner) for inner in result.composition_results)
            and (result.continuous is None or _statuses_final(result.continuous))
        )
    if isinstance(result, StrategyResult):
        return result.status in FINAL_STATUSES
    if isinstance(result, MultiScenarioResult):
        singles = [] if result.single_solution is None else [result.single_solution]
        return all(_statuses_final(frontier) for _, frontier in result.frontiers) and all(
            _statuses_final(item) for item in (*singles, *result.strategies)
        )
    return False  # tipos desconocidos (p. ej. HeuristicGapReport): no se guardan


class OperationCache:
    """Caché de operaciones de un worker: claves + ``ResultCache`` + política de cacheabilidad."""

    def __init__(self, context: _Context, cache: ResultCache) -> None:
        config, snapshot = context.config, context.snapshot
        self._context = context
        self._cache = cache
        wall_clock_limits = (
            config.solver.time_limit_seconds,
            config.conic.time_limit_seconds,
        )
        self._time_dependent = any(limit is not None for limit in wall_clock_limits)
        returns = snapshot.return_scenarios
        self._scenario_hash = hash_of(
            {
                "definitions": snapshot.scenario_definitions,
                "returns": None
                if returns is None
                else {
                    "asset_ids": returns.asset_ids,
                    "returns": hash_float_array(returns.returns),
                    "weights": hash_float_array(returns.weights),
                    "source": returns.source,
                    "weighting": returns.weighting,
                },
            }
        )
        costs = snapshot.costs
        self._cost_hash = hash_of(
            {
                "costs": None
                if costs is None
                else {
                    "asset_ids": costs.asset_ids,
                    "buy": hash_float_array(costs.buy_costs),
                    "sell": hash_float_array(costs.sell_costs),
                    "sources": costs.sources,
                },
                "config": config.transaction_costs,
                "optimization_horizon_years": config.optimization_horizon_years,
            }
        )
        self._frontier_hash = hash_of(
            {"frontier": config.frontier, "candidates": config.candidates}
        )
        self._constraints_hash = hash_of(config.constraints)

    @property
    def metrics(self) -> CacheMetrics:
        """Contadores del worker."""
        return self._cache.metrics

    def key(self, request: _Request, index: int) -> CacheKey:
        """Clave completa de la operación ``index`` de ``request`` (véase el módulo)."""
        context, snapshot = self._context, self._context.snapshot
        operations = request.workload.operations
        operation = operations[index]
        searches = operation.kind in (
            OperationKind.GLOBAL_FRONTIER,
            OperationKind.EXACT_MIP_VALIDATION,
        )
        searches = searches or (
            operation.kind is OperationKind.MULTI_SCENARIO
            and operation.scope is FrontierScope.GLOBAL_CANDIDATE_FRONTIER
        )
        if searches or request.composition_asset_ids is None:
            composition = tuple(request.state.asset_ids)
        else:
            composition = request.composition_asset_ids
        dependencies = [
            earlier
            for earlier in operations[:index]
            if operation.kind is OperationKind.EXACT_MIP_VALIDATION
            and earlier.kind is OperationKind.GLOBAL_FRONTIER
        ]
        uses_data = operation.kind in (OperationKind.MULTI_SCENARIO, OperationKind.STRATEGY_CVAR)
        return CacheKey(
            portfolio_id=request.portfolio_id,
            operation_hash=hash_of({"operation": operation, "depends_on": dependencies}),
            composition_hash=composition_hash(frozenset(composition)),
            scenario_id=snapshot.base_scenario_id,
            scenario_hash=self._scenario_hash if uses_data else NOT_USED,
            constraint_hash=hash_of(
                {
                    "constraints": self._constraints_hash,
                    "spec": request.spec,
                    "composition": request.composition_asset_ids,
                    "nav": request.state.nav,
                }
            ),
            mu_sigma_version=snapshot.risk_model.mu_sigma_version,
            transaction_cost_hash=self._cost_hash,
            frontier_config_hash=self._frontier_hash,
            config_hash=context.config_hash,
            market_data_timestamp=snapshot.market_data_timestamp or UNSPECIFIED,
            current_portfolio_state_hash=request.state.state_hash,
            snapshot_key=context.snapshot_key,
        )

    def cacheable(self, operation: OperationSpec) -> Callable[[Any], bool]:
        """Predicado de cacheabilidad de un resultado de ``operation``."""

        def predicate(result: object) -> bool:
            if self._time_dependent or operation.kind is OperationKind.EXACT_MIP_VALIDATION:
                return False
            return _statuses_final(result)

        return predicate

    def run(
        self,
        request: _Request,
        index: int,
        compute: Callable[[], T],
    ) -> tuple[T, CacheEvent]:
        """Resultado de la operación: de la caché (sin invocar ``compute``) o calculado y
        guardado."""
        operation = request.workload.operations[index]
        return self._cache.get_or_compute(
            self.key(request, index), compute, cacheable=self.cacheable(operation)
        )
