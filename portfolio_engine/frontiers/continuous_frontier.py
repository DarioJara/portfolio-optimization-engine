"""``ContinuousFrontierEngine``: frontera eficiente de composición fija (MASTER_SPEC §32-43).

Requisito: FRN-001.

Responde "¿qué conjunto eficiente puede alcanzarse sin cambiar activos?": la composición es la
cartera actual (o una composición explícita) y solo se optimizan los pesos; los activos actuales
que no estén en la composición se liquidan por completo (turnover y coste constantes). Es
un pipeline distinto del futuro ``GLOBAL_CANDIDATE_FRONTIER`` (Bloque 3).

Pipeline (ARCHITECTURE §10.2)::

    ConstraintSet → ConstraintCompiler → PreFeasibilityChecker (si inviable: sin solver)
    → MinVariance y MaxReturn explícitos → malla (theta o retorno objetivo) × {GROSS, NET}
      en un único workspace, secuencial, con arranque en caliente
    → frontera adaptativa (opcional) → SolutionValidator por punto → métricas desde los pesos
    → deduplicación → Pareto (bruto y neto) → CompositionFrontierResult

Tratamientos de coste (no equivalentes, MASTER_SPEC §79):

* ``GROSS``: optimiza retorno bruto.
* ``NET``: los costes ``θ·TC(w)`` (o la restricción neta de retorno objetivo) forman parte de la
  optimización mediante variables de compra/venta.
* ``POST_COST_GROSS``: los pesos de ``GROSS`` evaluados tras costes; nunca se presenta como NET.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import numpy as np

from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.hashing import config_hash
from portfolio_engine.constraints.compiler import CompiledConstraints, ConstraintCompiler
from portfolio_engine.constraints.constraint_set import build_constraint_set
from portfolio_engine.constraints.feasibility import FeasibilityReport, PreFeasibilityChecker
from portfolio_engine.costs.transaction_cost_model import (
    TransactionCostModel,
    UnionAlignment,
    align_union,
)
from portfolio_engine.exceptions import FrontierError
from portfolio_engine.frontiers.adaptive import (
    AdaptiveFrontier,
    ParametrizedPoint,
    ReturnMetric,
    scoring_return,
)
from portfolio_engine.frontiers.dedup import deduplicate
from portfolio_engine.frontiers.pareto import apply_efficiency
from portfolio_engine.frontiers.risk_aversion_grid import RiskAversionGrid
from portfolio_engine.frontiers.session import FrontierContext, FrontierSession
from portfolio_engine.frontiers.target_return_grid import (
    TargetReturnGrid,
    interior_targets,
    target_range,
)
from portfolio_engine.frontiers.theta_calibration import calibrate_theta_from_points
from portfolio_engine.metrics.portfolio_metrics import MetricsTolerances, compute_metrics
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    FrontierScope,
    GridScale,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.models.frontier import (
    CompositionFrontierResult,
    FrontierDiagnostics,
    FrontierPoint,
    PointMetrics,
)
from portfolio_engine.models.portfolio import CurrentPortfolioState, PortfolioSpec
from portfolio_engine.models.risk_model import RiskModel
from portfolio_engine.optimizers.formulations.qp_builder import CompositionInputs
from portfolio_engine.optimizers.router import SolverRouter
from portfolio_engine.validation.solution_validator import SolutionValidator
from portfolio_engine.validation.tolerances import ValidationTolerances

#: Resuelve un punto de frontera para un valor de parámetro (theta o retorno objetivo).
PointSolver = Callable[[float], FrontierPoint]

NOTE_DEGENERATE = "DEGENERATE_FRONTIER_SINGLE_EFFICIENT_PORTFOLIO"
NOTE_MIN_VARIANCE_FAILED = "MIN_VARIANCE_NOT_SOLVED_GRID_SKIPPED"
NOTE_MAX_RETURN_FAILED = "MAX_RETURN_NOT_SOLVED_GRID_SKIPPED"
NOTE_POST_COST = "POST_COST_GROSS_EVALUATED_FROM_GROSS_WEIGHTS"


@dataclass(frozen=True, slots=True)
class PhaseMeasures:
    """Tiempos (s) por fase de una frontera e iteraciones de sus extremos (benchmark, H-1)."""

    min_variance_time: float = 0.0
    max_return_time: float = 0.0
    grid_time: float = 0.0
    endpoint_iterations: int = 0


@dataclass(frozen=True, eq=False, slots=True)
class FrontierProblem:
    """Entradas de una frontera continua para una cartera y un escenario.

    ``composition_asset_ids`` es opcional: por defecto, los activos de la cartera actual. Una
    composición explícita debe estar ordenada por AssetID; los activos actuales que no contenga se
    venden por completo (coste y turnover constantes en la optimización). La generación de
    composiciones candidatas pertenece al Bloque 3.
    """

    portfolio_id: str
    scenario_id: str
    risk_model: RiskModel
    universe: Universe
    state: CurrentPortfolioState
    spec: PortfolioSpec | None
    costs: AssetCostVector | None
    composition_asset_ids: tuple[str, ...] | None = None


class ContinuousFrontierEngine:
    """Genera la frontera eficiente (bruta, neta o post-coste) de una composición fija."""

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._router = SolverRouter(config.solver)
        self._validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
        self._tolerances = MetricsTolerances.from_config(config.solver, config.frontier)
        self._compiler = ConstraintCompiler()
        self._checker = PreFeasibilityChecker(config.solver.constraint_tolerance)

    def solve(
        self,
        problem: FrontierProblem,
        cost_treatment: CostTreatment,
        method: FrontierMethod,
    ) -> CompositionFrontierResult:
        """Frontera de ``problem`` con el tratamiento de costes y el método indicados.

        ``POST_COST_GROSS`` resuelve la frontera ``GROSS`` (mismos pesos) pero, si es adaptativa,
        puntúa los intervalos con el retorno neto de esos pesos: la curva que se publica es
        (volatilidad, retorno tras costes).
        """
        if cost_treatment is CostTreatment.POST_COST_GROSS:
            gross = self._solve(problem, CostTreatment.GROSS, method, cost_treatment)
            return post_cost_evaluation(gross, self._config.frontier.pareto_tolerance)
        return self._solve(problem, cost_treatment, method, cost_treatment)

    def _solve(
        self,
        problem: FrontierProblem,
        cost_treatment: CostTreatment,
        method: FrontierMethod,
        scoring: CostTreatment,
    ) -> CompositionFrontierResult:
        compiled, feasibility = self._compile(problem)
        if not feasibility.feasible:
            return self._pre_check_failure(problem, compiled, feasibility, cost_treatment, method)
        session = self._new_session(problem, compiled, cost_treatment, method)
        context = session.context
        raw_points, notes, phases = self._run(session, method, scoring_return(scoring))
        points = apply_efficiency(
            deduplicate(raw_points, self._config.frontier), self._config.frontier.pareto_tolerance
        )
        return CompositionFrontierResult(
            portfolio_id=problem.portfolio_id,
            scenario_id=problem.scenario_id,
            composition_id=compiled.composition_id,
            asset_ids=compiled.asset_ids,
            scope=FrontierScope.CONTINUOUS_FRONTIER,
            cost_treatment=cost_treatment,
            method=method,
            optimization_horizon_years=self._config.optimization_horizon_years,
            has_current_portfolio=problem.state.has_current_portfolio,
            pre_check_feasible=True,
            infeasibility_causes=(),
            points=points,
            current_metrics=self._current_metrics(problem, context),
            diagnostics=replace(
                session.diagnostics(),
                min_variance_time=phases.min_variance_time,
                max_return_time=phases.max_return_time,
                grid_time=phases.grid_time,
                endpoint_iterations=phases.endpoint_iterations,
            ),
            constraint_hash=compiled.constraint_hash,
            mu_sigma_version=problem.risk_model.mu_sigma_version,
            config_hash=config_hash(self._config),
            notes=notes,
        )

    def open_session(
        self, problem: FrontierProblem, cost_treatment: CostTreatment, method: FrontierMethod
    ) -> FrontierSession:
        """Sesión con workspace reutilizable para resolver puntos sueltos (uso avanzado y tests).

        Lanza :class:`FrontierError` si la factibilidad previa detecta inviabilidad.
        """
        if cost_treatment is CostTreatment.POST_COST_GROSS:
            raise FrontierError("Una sesión resuelve GROSS o NET; POST_COST_GROSS es ex post.")
        compiled, feasibility = self._compile(problem)
        if not feasibility.feasible:
            causes = "; ".join(f"{cause.code}: {cause.detail}" for cause in feasibility.causes)
            raise FrontierError(f"Problema inviable antes del solver: {causes}")
        return self._new_session(problem, compiled, cost_treatment, method)

    def _compile(self, problem: FrontierProblem) -> tuple[CompiledConstraints, FeasibilityReport]:
        asset_ids = self._composition(problem)
        constraint_set = build_constraint_set(
            self._config.constraints,
            problem.spec,
            problem.portfolio_id,
            self._config.frontier.min_holding_weight,
            self._config.candidates.unknown_liquidity_policy,
        )
        compiled = self._compiler.compile(
            constraint_set, problem.universe, asset_ids, problem.state
        )
        return compiled, self._checker.check(compiled)

    def _new_session(
        self,
        problem: FrontierProblem,
        compiled: CompiledConstraints,
        cost_treatment: CostTreatment,
        method: FrontierMethod,
    ) -> FrontierSession:
        alignment = align_union(problem.state, compiled.asset_ids)
        context = self._context(problem, compiled, alignment, cost_treatment)
        return FrontierSession(
            context,
            cost_treatment,
            method,
            self._config.solver,
            self._router,
            self._validator,
            self._tolerances,
        )

    # ------------------------------------------------------------------------------ preparación

    def _composition(self, problem: FrontierProblem) -> tuple[str, ...]:
        if problem.composition_asset_ids is not None:
            return problem.composition_asset_ids
        if not problem.state.has_current_portfolio:
            raise FrontierError(
                "Sin cartera actual la composición debe indicarse explícitamente "
                "(composition_asset_ids)."
            )
        return problem.state.asset_ids

    def _context(
        self,
        problem: FrontierProblem,
        compiled: CompiledConstraints,
        alignment: UnionAlignment,
        cost_treatment: CostTreatment,
    ) -> FrontierContext:
        position = {asset_id: index for index, asset_id in enumerate(problem.risk_model.asset_ids)}
        missing = [asset_id for asset_id in compiled.asset_ids if asset_id not in position]
        if missing:
            raise FrontierError(f"Activos sin mu/Sigma en el modelo de riesgo: {missing}")
        indices = np.array([position[asset_id] for asset_id in compiled.asset_ids], dtype=np.int64)
        mu = np.array(problem.risk_model.mu[indices], dtype=np.float64)
        sigma = np.array(problem.risk_model.sigma[np.ix_(indices, indices)], dtype=np.float64)
        cost_model: TransactionCostModel | None = None
        if alignment.has_current_portfolio and problem.costs is not None:
            cost_model = TransactionCostModel(
                alignment, problem.costs, self._config.optimization_horizon_years
            )
        if cost_treatment is CostTreatment.NET and cost_model is None:
            raise FrontierError("NET exige cartera actual y costes de transacción.")
        return FrontierContext(
            composition_id=compiled.composition_id,
            inputs=CompositionInputs(mu, sigma, compiled, cost_model),
            alignment=alignment,
            risk_free_rate=self._config.returns.risk_free_rate,
        )

    def _current_metrics(
        self, problem: FrontierProblem, context: FrontierContext
    ) -> PointMetrics | None:
        """Métricas de la cartera actual completa (``None`` sin cartera actual).

        Si la composición no contiene todos los activos actuales, se evalúan sobre la unión con
        ``mu``/``Sigma`` del modelo de riesgo (``None`` si falta algún activo en el modelo).
        """
        if not context.alignment.has_current_portfolio:
            return None
        if context.compiled.exited:
            return self._current_metrics_on_union(problem, context)
        table = compute_metrics(
            context.compiled.current_weights,
            mu=context.inputs.mu,
            sigma=context.inputs.sigma,
            risk_free_rate=context.risk_free_rate,
            tolerances=self._tolerances,
            alignment=context.alignment,
            cost_model=context.cost_model,
        )
        return table.row(0)

    def _current_metrics_on_union(
        self, problem: FrontierProblem, context: FrontierContext
    ) -> PointMetrics | None:
        alignment = context.alignment
        position = {asset_id: index for index, asset_id in enumerate(problem.risk_model.asset_ids)}
        if any(asset_id not in position for asset_id in alignment.asset_ids):
            return None
        indices = np.array([position[asset_id] for asset_id in alignment.asset_ids], dtype=np.int64)
        identity = UnionAlignment(
            alignment.asset_ids,
            alignment.current_weights,
            np.arange(alignment.size, dtype=np.int64),
            True,
        )
        cost_model = (
            None
            if problem.costs is None
            else TransactionCostModel(
                identity, problem.costs, self._config.optimization_horizon_years
            )
        )
        table = compute_metrics(
            alignment.current_weights,
            mu=np.array(problem.risk_model.mu[indices], dtype=np.float64),
            sigma=np.array(problem.risk_model.sigma[np.ix_(indices, indices)], dtype=np.float64),
            risk_free_rate=context.risk_free_rate,
            tolerances=self._tolerances,
            alignment=identity,
            cost_model=cost_model,
        )
        return table.row(0)

    # ------------------------------------------------------------------------------- resolución

    def _run(
        self, session: FrontierSession, method: FrontierMethod, score_return: ReturnMetric
    ) -> tuple[list[FrontierPoint], tuple[str, ...], PhaseMeasures]:
        started = time.perf_counter()
        minimum = session.solve_minimum_variance()
        after_minimum = time.perf_counter()
        min_variance_time = after_minimum - started
        if not minimum.is_valid_solution or minimum.metrics is None or minimum.weights is None:
            phases = PhaseMeasures(min_variance_time, 0.0, 0.0, session.total_iterations)
            return [minimum], (NOTE_MIN_VARIANCE_FAILED,), phases
        maximum, notes = session.solve_maximum_return()
        after_maximum = time.perf_counter()
        endpoints = PhaseMeasures(
            min_variance_time, after_maximum - after_minimum, 0.0, session.total_iterations
        )
        if not maximum.is_valid_solution or maximum.metrics is None or maximum.weights is None:
            return [minimum, maximum], (*notes, NOTE_MAX_RETURN_FAILED), endpoints
        ends = (
            (minimum.metrics.variance, session.net_return(minimum.weights)),
            (maximum.metrics.variance, session.net_return(maximum.weights)),
        )
        points, grid_notes = self._grid(
            session, method, score_return, (minimum, maximum), ends, notes
        )
        grid_time = time.perf_counter() - after_maximum
        return points, grid_notes, replace(endpoints, grid_time=grid_time)

    def _grid(
        self,
        session: FrontierSession,
        method: FrontierMethod,
        score_return: ReturnMetric,
        extremes: tuple[FrontierPoint, FrontierPoint],
        ends: tuple[tuple[float, float], tuple[float, float]],
        notes: tuple[str, ...],
    ) -> tuple[list[FrontierPoint], tuple[str, ...]]:
        minimum, maximum = extremes
        config = self._config.frontier
        initial = config.initial_frontier_points if config.adaptive else config.frontier_points
        if initial is None:
            raise FrontierError("initial_frontier_points ausente con adaptive = true.")
        interior = initial - 2
        if method is FrontierMethod.RISK_AVERSION_GRID:
            seeds, insert, scale = self._risk_aversion_seeds(
                session, minimum, maximum, ends, interior
            )
        else:
            seeds, insert, scale = self._target_return_seeds(
                session, minimum, maximum, ends, interior
            )
        if seeds is None or insert is None:
            return [minimum, maximum], (*notes, NOTE_DEGENERATE)
        ordered: Sequence[ParametrizedPoint] = seeds
        if config.adaptive:
            ordered = AdaptiveFrontier(config, scale, score_return).refine(seeds, insert)
        return [item.point for item in ordered], notes

    def _risk_aversion_seeds(
        self,
        session: FrontierSession,
        minimum: FrontierPoint,
        maximum: FrontierPoint,
        ends: tuple[tuple[float, float], tuple[float, float]],
        interior: int,
    ) -> tuple[list[ParametrizedPoint] | None, PointSolver | None, GridScale]:
        config = self._config.frontier
        grid = calibrate_theta_from_points(config, ends[0], ends[1], config.dedup_return_tolerance)
        if grid is None:
            return None, None, config.theta_scale
        runner = RiskAversionGrid(session)
        thetas = grid.values(interior) if interior > 0 else np.empty(0)
        interior_points = runner.solve_grid(thetas)
        seeds = [ParametrizedPoint(grid.theta_min, minimum)]
        seeds += [
            ParametrizedPoint(float(theta), point)
            for theta, point in zip(thetas.tolist(), interior_points, strict=True)
        ]
        seeds.append(ParametrizedPoint(grid.theta_max, maximum))
        return seeds, lambda theta: runner.solve_theta(theta, adaptive=True), grid.scale

    def _target_return_seeds(
        self,
        session: FrontierSession,
        minimum: FrontierPoint,
        maximum: FrontierPoint,
        ends: tuple[tuple[float, float], tuple[float, float]],
        interior: int,
    ) -> tuple[list[ParametrizedPoint] | None, PointSolver | None, GridScale]:
        bounds = target_range(ends[0][1], ends[1][1])
        if bounds is None:
            return None, None, GridScale.LINEAR
        low, high = bounds
        runner = TargetReturnGrid(session)
        targets = interior_targets(low, high, interior)
        interior_points = runner.solve_grid(targets)
        seeds = [ParametrizedPoint(low, minimum)]
        seeds += [
            ParametrizedPoint(float(target), point)
            for target, point in zip(targets.tolist(), interior_points, strict=True)
        ]
        seeds.append(ParametrizedPoint(high, maximum))
        return seeds, lambda target: runner.solve_target(target, adaptive=True), GridScale.LINEAR

    def _pre_check_failure(
        self,
        problem: FrontierProblem,
        compiled: CompiledConstraints,
        feasibility: FeasibilityReport,
        cost_treatment: CostTreatment,
        method: FrontierMethod,
    ) -> CompositionFrontierResult:
        """Resultado sin invocar al solver (decisión A-15): estado ``INFEASIBLE`` con causa."""
        point = FrontierPoint(
            point_id=f"{cost_treatment.value}:{method.value}:PRE_CHECK",
            sequence=0,
            strategy_id=StrategyID.MIN_VARIANCE,
            scope=FrontierScope.CONTINUOUS_FRONTIER,
            cost_treatment=cost_treatment,
            method=method,
            composition_id=compiled.composition_id,
            theta=None,
            target_return=None,
            weights=None,
            metrics=None,
            objective_value=None,
            solve=None,
            validation=None,
            is_valid_solution=False,
            status=SolverStatus.INFEASIBLE,
            status_source=StatusSource.PRE_SOLVER_CHECK,
        )
        empty = FrontierDiagnostics("NONE", "NONE", 0, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0)
        return CompositionFrontierResult(
            portfolio_id=problem.portfolio_id,
            scenario_id=problem.scenario_id,
            composition_id=compiled.composition_id,
            asset_ids=compiled.asset_ids,
            scope=FrontierScope.CONTINUOUS_FRONTIER,
            cost_treatment=cost_treatment,
            method=method,
            optimization_horizon_years=self._config.optimization_horizon_years,
            has_current_portfolio=problem.state.has_current_portfolio,
            pre_check_feasible=False,
            infeasibility_causes=tuple(
                f"{cause.code}: {cause.detail}" for cause in feasibility.causes
            ),
            points=(point,),
            current_metrics=None,
            diagnostics=empty,
            constraint_hash=compiled.constraint_hash,
            mu_sigma_version=problem.risk_model.mu_sigma_version,
            config_hash=config_hash(self._config),
            notes=(),
        )


def post_cost_evaluation(
    gross: CompositionFrontierResult, pareto_tolerance: float
) -> CompositionFrontierResult:
    """``POST_COST_GROSS``: pesos de la frontera ``GROSS`` evaluados tras costes (FRN-012).

    No se resuelve ningún problema nuevo y la etiqueta es siempre ``POST_COST_GROSS``: nunca se
    presenta como ``NET`` (la frontera NET incorpora los costes en la optimización, §37).
    """
    if gross.cost_treatment is not CostTreatment.GROSS:
        raise FrontierError("post_cost_evaluation exige una frontera GROSS.")
    started = time.perf_counter()
    relabelled: list[FrontierPoint] = []
    for point in gross.points:
        if point.is_valid_solution and (
            point.metrics is None or point.metrics.expected_return_net is None
        ):
            raise FrontierError(
                "POST_COST_GROSS exige cartera actual y costes de transacción "
                f"({point.metrics.unavailable_reason if point.metrics else 'sin métricas'})."
            )
        relabelled.append(
            replace(
                point,
                cost_treatment=CostTreatment.POST_COST_GROSS,
                point_id=point.point_id.replace(
                    CostTreatment.GROSS.value, CostTreatment.POST_COST_GROSS.value, 1
                ),
                duplicate_of=(
                    None
                    if point.duplicate_of is None
                    else point.duplicate_of.replace(
                        CostTreatment.GROSS.value, CostTreatment.POST_COST_GROSS.value, 1
                    )
                ),
            )
        )
    points = apply_efficiency(relabelled, pareto_tolerance)
    diagnostics = replace(
        gross.diagnostics,
        frontier_time=gross.diagnostics.frontier_time + time.perf_counter() - started,
    )
    return replace(
        gross,
        cost_treatment=CostTreatment.POST_COST_GROSS,
        points=points,
        diagnostics=diagnostics,
        notes=(*gross.notes, NOTE_POST_COST),
    )
