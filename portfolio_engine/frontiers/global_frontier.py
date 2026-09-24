"""``GlobalCandidateFrontierEngine``: frontera eficiente con sustitución de activos (§33).

Requisitos: FRN-002, FRN-003, FRN-017, OPT-002 (pipeline ``FAST_PRODUCTION`` secuencial).

Responde "¿qué conjunto eficiente puede alcanzarse permitiendo selección/sustitución de activos?".
Es un pipeline **distinto** de ``CONTINUOUS_FRONTIER`` (composición actual fija)::

    CurrentPortfolio
      → CandidateEngine → varias CandidateComposition (la actual como referencia)
      → ContinuousFrontierEngine por composición (MinVariance, MaxReturn, malla θ / retorno
        objetivo, NET con liquidación de los activos que salen, SolutionValidator por punto)
      → unión de puntos válidos → deduplicación numérica → envolvente de Pareto global

El motor del Bloque 2 se reutiliza tal cual (mismas formulaciones); aquí solo se relabelan los
resultados con ``GLOBAL_CANDIDATE_FRONTIER``. La frontera de la composición actual se resuelve una
sola vez y aparece como ``continuous`` (alcance ``CONTINUOUS_FRONTIER``) y, relabelada, como
referencia dentro de la unión global: no se recalcula ni se confunde con la global.

Pareto global: dominancia sobre puntos válidos con **una sola magnitud de retorno por bandera**
(bruta para ``is_global_gross_efficient``, neta para ``is_global_net_efficient``); la envolvente
publicada usa la magnitud del tratamiento (``GROSS`` bruta; ``NET`` y ``POST_COST_GROSS`` neta, este
último con su semántica de evaluación post-coste). Los puntos dominados o duplicados no se borran.
La deduplicación entre composiciones (tolerancias de ``FrontierConfig``) marca el duplicado y
conserva la trazabilidad (``duplicate_of``).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import replace

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates.candidate_engine import CandidateContext, CandidateEngine
from portfolio_engine.candidates.evaluation import CompositionEvaluator
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.exceptions import FrontierError
from portfolio_engine.frontiers.candidate_evaluator import QPCompositionEvaluator
from portfolio_engine.frontiers.continuous_frontier import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.frontiers.pareto import pareto_mask
from portfolio_engine.models.enums import (
    CostTreatment,
    EvaluationMode,
    FrontierMethod,
    FrontierScope,
)
from portfolio_engine.models.frontier import (
    CompositionFrontierResult,
    GlobalFrontierDiagnostics,
    GlobalFrontierPoint,
    GlobalFrontierResult,
)
from portfolio_engine.parallel.determinism import sequence_key


def relabel_scope(
    result: CompositionFrontierResult, scope: FrontierScope
) -> CompositionFrontierResult:
    """Copia de ``result`` con el alcance ``scope`` en la frontera y en cada punto.

    No resuelve nada: es la misma solución vista como parte de otra frontera.
    """
    points = tuple(replace(point, scope=scope) for point in result.points)
    return replace(result, scope=scope, points=points)


def _weights_close(
    first: GlobalFrontierPoint, second: GlobalFrontierPoint, tolerance: float
) -> bool:
    """Equivalencia de pesos sobre la unión de activos (0 donde un punto no tiene el activo)."""
    weights_a, weights_b = first.point.weights, second.point.weights
    if weights_a is None or weights_b is None:
        return False
    a = dict(zip(first.asset_ids, weights_a.tolist(), strict=True))
    b = dict(zip(second.asset_ids, weights_b.tolist(), strict=True))
    union = set(a) | set(b)
    return all(abs(a.get(asset, 0.0) - b.get(asset, 0.0)) <= tolerance for asset in union)


def _metric_arrays(
    points: Sequence[GlobalFrontierPoint],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.bool_],
]:
    """Volatilidad, retorno bruto, retorno neto (``NaN`` si falta) y validez de cada punto."""
    vol = np.full(len(points), np.nan)
    gross = np.full(len(points), np.nan)
    net = np.full(len(points), np.nan)
    valid = np.zeros(len(points), dtype=np.bool_)
    for index, point in enumerate(points):
        metrics = point.point.metrics
        if not point.is_valid_solution or metrics is None:
            continue
        valid[index] = True
        vol[index], gross[index] = metrics.volatility, metrics.expected_return_gross
        if metrics.expected_return_net is not None:
            net[index] = metrics.expected_return_net
    return vol, gross, net, valid


def _find_duplicates(
    points: Sequence[GlobalFrontierPoint],
    vol: npt.NDArray[np.float64],
    gross: npt.NDArray[np.float64],
    valid: npt.NDArray[np.bool_],
    config: FrontierConfig,
) -> list[int | None]:
    """Índice del primer punto equivalente (peso, retorno bruto y volatilidad) o ``None``."""
    close = (
        (np.abs(vol[:, np.newaxis] - vol[np.newaxis, :]) <= config.dedup_volatility_tolerance)
        & (np.abs(gross[:, np.newaxis] - gross[np.newaxis, :]) <= config.dedup_return_tolerance)
        & valid[:, np.newaxis]
        & valid[np.newaxis, :]
    )
    original: list[int | None] = [None] * len(points)
    for later in range(len(points)):
        for earlier in np.flatnonzero(close[:later, later]).tolist():
            if original[earlier] is None and _weights_close(
                points[earlier], points[later], config.dedup_weight_tolerance
            ):
                original[later] = earlier
                break
    return original


def global_pareto(
    points: Sequence[GlobalFrontierPoint], config: FrontierConfig
) -> tuple[GlobalFrontierPoint, ...]:
    """Deduplica y marca la eficiencia global de la unión de puntos de varias composiciones.

    ``points`` debe venir en el orden canónico (``SequenceID``): el primero de cada grupo de
    duplicados es el representante y los demás lo heredan. Los puntos inválidos no participan y
    los dominados no se eliminan (FRN-016). ``is_global_net_efficient`` es ``None`` si algún punto
    válido no tiene retorno neto (p. ej. sin cartera actual).
    """
    if not points:
        return ()
    vol, gross, net, valid = _metric_arrays(points)
    original = _find_duplicates(points, vol, gross, valid, config)
    eligible = valid & np.array([index is None for index in original], dtype=np.bool_)
    gross_flags = pareto_mask(vol, gross, eligible, config.pareto_tolerance)
    net_flags: npt.NDArray[np.bool_] | None = None
    if not np.isnan(net[valid]).any():
        net_flags = pareto_mask(vol, net, eligible, config.pareto_tolerance)
    result: list[GlobalFrontierPoint] = []
    for index, point in enumerate(points):
        origin = original[index]
        source = index if origin is None else origin
        duplicate_of = None if origin is None else points[origin].global_point_id
        result.append(
            replace(
                point,
                is_global_gross_efficient=bool(gross_flags[source]),
                is_global_net_efficient=None if net_flags is None else bool(net_flags[source]),
                is_duplicate=origin is not None,
                duplicate_of=duplicate_of,
            )
        )
    return tuple(result)


class GlobalCandidateFrontierEngine:
    """Construye la ``GLOBAL_CANDIDATE_FRONTIER`` de una cartera y un escenario."""

    def __init__(self, config: EngineConfig, evaluator: CompositionEvaluator | None = None) -> None:
        self._config = config
        self._continuous = ContinuousFrontierEngine(config)
        if evaluator is None and config.candidates.evaluation_mode is EvaluationMode.QP_UTILITY:
            evaluator = QPCompositionEvaluator(config)
        self._candidates = CandidateEngine(config, evaluator)

    def solve(
        self,
        problem: FrontierProblem,
        cost_treatment: CostTreatment,
        method: FrontierMethod,
    ) -> GlobalFrontierResult:
        """Frontera global de ``problem`` con el tratamiento de costes y el método indicados.

        ``problem.composition_asset_ids`` debe ser ``None``: la composición de partida es la
        cartera actual.
        """
        if problem.composition_asset_ids is not None:
            raise FrontierError(
                "La frontera global parte de la cartera actual: "
                "composition_asset_ids debe ser None."
            )
        started = time.perf_counter()
        context = CandidateContext(
            problem.portfolio_id,
            problem.scenario_id,
            problem.risk_model,
            problem.universe,
            problem.state,
            problem.spec,
            problem.costs,
        )
        search = self._candidates.search(problem.state.composition(), context)
        searched = time.perf_counter()
        continuous = (
            self._continuous.solve(problem, cost_treatment, method)
            if problem.state.has_current_portfolio
            else None
        )
        results = tuple(
            self._composition_result(
                problem, candidate.asset_ids, cost_treatment, method, continuous
            )
            for candidate in search.compositions
        )
        solved = time.perf_counter()
        points = self._global_points(problem, cost_treatment, results)
        finished = time.perf_counter()
        return GlobalFrontierResult(
            portfolio_id=problem.portfolio_id,
            scenario_id=problem.scenario_id,
            cost_treatment=cost_treatment,
            method=method,
            optimization_horizon_years=self._config.optimization_horizon_years,
            has_current_portfolio=problem.state.has_current_portfolio,
            current_composition_id=(
                problem.state.composition_hash if problem.state.has_current_portfolio else None
            ),
            current_metrics=None if continuous is None else continuous.current_metrics,
            continuous=continuous,
            candidates=search.compositions,
            candidate_diagnostics=search.diagnostics,
            composition_results=results,
            points=points,
            diagnostics=GlobalFrontierDiagnostics(
                candidate_count=len(search.compositions),
                frontiers_solved=len(results),
                points_total=len(points),
                points_valid=sum(1 for point in points if point.is_valid_solution),
                points_duplicate=sum(1 for point in points if point.is_duplicate),
                points_efficient=sum(
                    1
                    for point in points
                    if point.is_valid_solution
                    and not point.is_duplicate
                    and self._primary_flag(point, cost_treatment)
                ),
                candidate_time=searched - started,
                frontier_time=solved - searched,
                pareto_time=finished - solved,
                total_time=finished - started,
            ),
        )

    # -------------------------------------------------------------------------------- pasos

    def _composition_result(
        self,
        problem: FrontierProblem,
        asset_ids: tuple[str, ...],
        cost_treatment: CostTreatment,
        method: FrontierMethod,
        continuous: CompositionFrontierResult | None,
    ) -> CompositionFrontierResult:
        """Frontera de una composición; la actual reutiliza la frontera continua ya resuelta."""
        if continuous is not None and set(asset_ids) == set(continuous.asset_ids):
            solved = continuous
        else:
            solved = self._continuous.solve(
                replace(problem, composition_asset_ids=asset_ids), cost_treatment, method
            )
        return relabel_scope(solved, FrontierScope.GLOBAL_CANDIDATE_FRONTIER)

    def _global_points(
        self,
        problem: FrontierProblem,
        cost_treatment: CostTreatment,
        results: Sequence[CompositionFrontierResult],
    ) -> tuple[GlobalFrontierPoint, ...]:
        """Unión de los puntos de todas las composiciones en el orden canónico y con Pareto."""
        scope = FrontierScope.GLOBAL_CANDIDATE_FRONTIER
        entries = [
            (
                sequence_key(
                    problem.portfolio_id,
                    problem.scenario_id,
                    scope.value,
                    cost_treatment.value,
                    result.composition_id,
                    point.point_id,
                ),
                result,
                point,
            )
            for result in results
            for point in result.points
        ]
        entries.sort(key=lambda entry: entry[0])
        ordered = [
            GlobalFrontierPoint(
                global_point_id=f"{result.composition_id}:{point.point_id}",
                sequence_id=position,
                composition_id=result.composition_id,
                asset_ids=result.asset_ids,
                point=point,
            )
            for position, (_, result, point) in enumerate(entries)
        ]
        return global_pareto(ordered, self._config.frontier)

    def _primary_flag(self, point: GlobalFrontierPoint, cost_treatment: CostTreatment) -> bool:
        flag = (
            point.is_global_gross_efficient
            if cost_treatment is CostTreatment.GROSS
            else point.is_global_net_efficient
        )
        return flag is True
