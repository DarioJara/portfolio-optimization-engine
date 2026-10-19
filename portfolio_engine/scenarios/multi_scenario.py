"""``MultiScenarioOptimizer``: optimización multiescenario (MASTER_SPEC §54; SCN-004..008).

Distingue dos tipos de problema que **no** son equivalentes:

* ``SCENARIO_INDEPENDENT``: **una solución (y una frontera) distinta por escenario**. Cada
  ``ScenarioID`` se resuelve con el motor de fronteras de los Bloques 2 y 3 sobre su propio
  ``μ_s``, ``Σ_s``, ``cost_s`` y ``constraints_s``; es la definición de aceptación del Bloque 4:
  una misma cartera produce fronteras y soluciones distintas por escenario.
* ``EXPECTED_SCENARIO_UTILITY``, ``WORST_CASE`` y ``BASE_WITH_STRESS_CONSTRAINTS``: **una única
  cartera** que responde simultáneamente a varios escenarios (formulaciones P12-P14). Deben cumplir
  a la vez las restricciones de **todos** los escenarios (``constraints_s``): se optimiza bajo su
  intersección y la solución se valida además contra cada escenario por separado.

Las probabilidades de ``EXPECTED_SCENARIO_UTILITY`` deben estar declaradas y sumar 1 (no se suponen
iguales ni se normalizan). ``WORST_CASE`` y ``SCENARIO_INDEPENDENT`` no las usan.

Costes: cada escenario aporta su ``cost_s``; ``ExpectedScenarioUtility`` optimiza el coste esperado
``Σ p_s c_s`` (lineal en las variables de compra/venta), ``WorstCase`` y ``BaseWithStress`` usan el
coste de cada escenario en su propia restricción.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.constraint_config import ConstraintConfig, GroupLimit
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.constraints.compiler import ConstraintCompiler
from portfolio_engine.constraints.constraint_set import build_constraint_set
from portfolio_engine.costs.transaction_cost_model import TransactionCostModel
from portfolio_engine.exceptions import ConfigError, ScenarioError, UnsupportedCombinationError
from portfolio_engine.frontiers.continuous_frontier import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.frontiers.global_frontier import GlobalCandidateFrontierEngine
from portfolio_engine.frontiers.session import FrontierContext
from portfolio_engine.frontiers.strategy_optimizer import StrategyOptimizer
from portfolio_engine.metrics.portfolio_metrics import compute_metrics
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    FrontierScope,
    MultiScenarioMode,
    StrategyID,
)
from portfolio_engine.models.frontier import CompositionFrontierResult, GlobalFrontierResult
from portfolio_engine.models.portfolio import PortfolioSpec
from portfolio_engine.models.risk_model import ExpectedReturns, RiskModel
from portfolio_engine.models.strategy import ScenarioMetrics, StrategyResult
from portfolio_engine.optimizers.formulations.conic import factor_covariance
from portfolio_engine.optimizers.formulations.multi_scenario import (
    ScenarioSlice,
    StressSpec,
    build_base_with_stress_problem,
    build_worst_case_problem,
    validated_probabilities,
)
from portfolio_engine.risk.risk_model_builder import CovarianceBuilder
from portfolio_engine.scenarios.data import ScenarioData, ScenarioSet
from portfolio_engine.validation.advanced_validator import (
    AdvancedChecks,
    ScenarioCheck,
    VolatilityLimitCheck,
)
from portfolio_engine.validation.solution_validator import ValidationContext


@dataclass(frozen=True, eq=False, slots=True)
class MultiScenarioResult:
    """Resultado de una optimización multiescenario.

    ``SCENARIO_INDEPENDENT`` rellena ``frontiers`` (una por ``ScenarioID``) y, si se pidió,
    ``strategies`` (p. ej. Max Sharpe por escenario); los demás modos rellenan ``single_solution``
    (una cartera única) y ``probabilities`` cuando se usaron.
    """

    mode: MultiScenarioMode
    portfolio_id: str
    scenario_ids: tuple[str, ...]
    frontiers: tuple[tuple[str, CompositionFrontierResult | GlobalFrontierResult], ...]
    strategies: tuple[StrategyResult, ...]
    single_solution: StrategyResult | None
    probabilities: tuple[tuple[str, float], ...] | None
    notes: tuple[str, ...]

    def frontier(self, scenario_id: str) -> CompositionFrontierResult | GlobalFrontierResult:
        """Frontera del escenario ``scenario_id`` (``KeyError`` si no existe)."""
        for key, value in self.frontiers:
            if key == scenario_id:
                return value
        raise KeyError(scenario_id)


def intersect_constraint_configs(configs: Sequence[ConstraintConfig]) -> ConstraintConfig:
    """Restricciones que cumplen **todas** las ``configs`` (intersección de conjuntos factibles).

    Límites de peso globales: el mayor mínimo y el menor máximo; turnover: el menor; límites de
    grupo con la misma clave: el mayor mínimo y el menor máximo, y los demás se conservan.
    ``long_only``, política de restringidos y liquidez son los del primero (no son overrides de
    escenario). Un conjunto vacío (mínimo mayor que el máximo) es :class:`ScenarioError`.
    """
    first = configs[0]
    mins = [c.global_min_weight for c in configs if c.global_min_weight is not None]
    maxs = [c.global_max_weight for c in configs if c.global_max_weight is not None]
    turnovers = [c.global_max_turnover for c in configs if c.global_max_turnover is not None]
    merged: dict[tuple[object, str], tuple[float | None, float | None]] = {}
    for config in configs:
        for limit in config.group_limits:
            key = (limit.dimension, limit.group)
            low, high = merged.get(key, (None, None))
            merged[key] = (
                _tighter(low, limit.min_weight, max),
                _tighter(high, limit.max_weight, min),
            )
    groups = tuple(
        GroupLimit(dimension, group, low, high)  # type: ignore[arg-type]
        for (dimension, group), (low, high) in merged.items()
    )
    try:
        return dataclasses.replace(
            first,
            global_min_weight=max(mins) if mins else None,
            global_max_weight=min(maxs) if maxs else None,
            global_max_turnover=min(turnovers) if turnovers else None,
            group_limits=groups,
        )
    except ConfigError as error:
        raise ScenarioError(f"constraints_s incompatibles entre escenarios: {error}") from error


def _tighter(current: float | None, new: float | None, pick: object) -> float | None:
    if current is None:
        return new
    if new is None:
        return current
    return float(pick(current, new))  # type: ignore[operator]


class MultiScenarioOptimizer:
    """Optimiza una cartera bajo varios escenarios (``MultiScenarioMode``)."""

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._compiler = ConstraintCompiler()
        self._covariance = CovarianceBuilder(config.risk, config.returns.trading_days_per_year)

    # ------------------------------------------------------------------ SCENARIO_INDEPENDENT

    def solve_independent(
        self,
        problem: FrontierProblem,
        scenarios: ScenarioSet,
        treatment: CostTreatment,
        method: FrontierMethod,
        *,
        scope: FrontierScope = FrontierScope.CONTINUOUS_FRONTIER,
        include_max_sharpe: bool = False,
    ) -> MultiScenarioResult:
        """Una frontera (y opcionalmente Max Sharpe) por ``ScenarioID``, cada una con sus datos."""
        frontiers: list[tuple[str, CompositionFrontierResult | GlobalFrontierResult]] = []
        strategies: list[StrategyResult] = []
        for scenario in scenarios.scenarios:
            config_s = self._scenario_config(scenario)
            problem_s = self.scenario_problem(problem, scenario)
            if scope is FrontierScope.GLOBAL_CANDIDATE_FRONTIER:
                frontier: CompositionFrontierResult | GlobalFrontierResult = (
                    GlobalCandidateFrontierEngine(config_s).solve(problem_s, treatment, method)
                )
            else:
                frontier = ContinuousFrontierEngine(config_s).solve(problem_s, treatment, method)
            frontiers.append((scenario.scenario_id, frontier))
            if include_max_sharpe:
                strategies.append(StrategyOptimizer(config_s).max_sharpe(problem_s, treatment))
        return MultiScenarioResult(
            mode=MultiScenarioMode.SCENARIO_INDEPENDENT,
            portfolio_id=problem.portfolio_id,
            scenario_ids=scenarios.ids,
            frontiers=tuple(frontiers),
            strategies=tuple(strategies),
            single_solution=None,
            probabilities=None,
            notes=(),
        )

    def scenario_problem(self, problem: FrontierProblem, scenario: ScenarioData) -> FrontierProblem:
        """``problem`` con los datos del escenario: ``ScenarioID``, ``μ_s``/``Σ_s``, ``cost_s``."""
        return dataclasses.replace(
            problem,
            scenario_id=scenario.scenario_id,
            risk_model=scenario.risk_model,
            costs=scenario.costs,
            spec=scenario.constraints.spec,
        )

    def _scenario_config(self, scenario: ScenarioData) -> EngineConfig:
        return dataclasses.replace(self._config, constraints=scenario.constraints.constraints)

    # --------------------------------------------------------------- soluciones únicas (P12-14)

    def solve_expected_utility(
        self,
        problem: FrontierProblem,
        scenarios: ScenarioSet,
        treatment: CostTreatment,
        risk_aversion: float,
    ) -> MultiScenarioResult:
        """Una cartera que maximiza ``Σ p_s (μ_sᵀw − λ wᵀΣ_s w) − Σ p_s TC_s(w)`` (QP → OSQP)."""
        probabilities = validated_probabilities(
            [s.probability for s in scenarios.scenarios],
            self._config.scenarios.probability_sum_tolerance,
        )
        config_i, problem_i = self._intersection(problem, scenarios)
        optimizer = StrategyOptimizer(config_i)
        strategy = StrategyID.EXPECTED_SCENARIO_UTILITY
        context, report = optimizer.prepare(problem_i, treatment)
        if context is None:
            result = optimizer.infeasible(problem_i, treatment, strategy, report)
        else:
            problem_bar = dataclasses.replace(
                problem_i,
                risk_model=self._aggregate_model(scenarios, probabilities, problem),
                costs=self._expected_costs(scenarios, probabilities),
                scenario_id="EXPECTED",
            )
            result = self._solve_expected(
                optimizer, problem, problem_bar, treatment, risk_aversion, scenarios, probabilities
            )
        return self._single(
            MultiScenarioMode.EXPECTED_SCENARIO_UTILITY,
            problem,
            scenarios,
            result,
            tuple(zip(scenarios.ids, probabilities.tolist(), strict=True)),
        )

    def _solve_expected(
        self,
        optimizer: StrategyOptimizer,
        problem: FrontierProblem,
        problem_bar: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        scenarios: ScenarioSet,
        probabilities: npt.NDArray[np.float64],
    ) -> StrategyResult:
        engine = ContinuousFrontierEngine(optimizer.config)
        session = engine.open_session(problem_bar, treatment, FrontierMethod.RISK_AVERSION_GRID)
        point = session.solve_risk_aversion(1.0 / risk_aversion, strategy=StrategyID.FRONTIER_POINT)
        context = session.context
        if point.solve is None:
            raise ScenarioError("La resolución de la utilidad esperada no produjo resultado.")
        weights = point.weights
        checks = self._scenario_checks(problem, context, scenarios, treatment)
        slices = self._slices(context, scenarios, treatment)
        extras: list[tuple[str, float]] = []
        scenario_metrics: tuple[ScenarioMetrics, ...] = ()
        if weights is not None:
            utilities = [
                _scenario_utility(
                    s, weights, risk_aversion, self._scenario_net(s, context, weights, treatment)
                )
                for s in slices
            ]
            extras.append(("expected_utility", float(np.dot(probabilities, utilities))))
            scenario_metrics = self._scenario_metrics(
                context, scenarios, weights, risk_aversion, treatment
            )
        return dataclasses.replace(
            optimizer.assemble(
                problem=problem_bar,
                treatment=treatment,
                strategy=StrategyID.EXPECTED_SCENARIO_UTILITY,
                context=context,
                solve=point.solve,
                weights=weights,
                checks=checks,
                objective_value=None if weights is None else -float(extras[0][1]),
                outcome=None,
                extras=extras,
            ),
            scenario_metrics=scenario_metrics,
        )

    def solve_worst_case(
        self,
        problem: FrontierProblem,
        scenarios: ScenarioSet,
        treatment: CostTreatment,
        risk_aversion: float,
    ) -> MultiScenarioResult:
        """Una cartera que maximiza ``min_s U_s(w)`` (SOCP → Clarabel) con ``μ_s, Σ_s, c_s``."""
        config_i, problem_i = self._intersection(problem, scenarios)
        optimizer = StrategyOptimizer(config_i)
        strategy = StrategyID.WORST_CASE
        context, report = optimizer.prepare(problem_i, treatment)
        if context is None:
            result = optimizer.infeasible(problem_i, treatment, strategy, report)
            return self._single(MultiScenarioMode.WORST_CASE, problem, scenarios, result, None)
        mandate, cap = optimizer.volatility_mandate(problem_i, treatment, strategy, context)
        if mandate is not None:
            return self._single(MultiScenarioMode.WORST_CASE, problem, scenarios, mandate, None)
        slices = self._slices(context, scenarios, treatment)
        factors = [factor_covariance(s.sigma, self._config.conic) for s in slices]
        extended, _ = build_worst_case_problem(
            context.inputs, treatment, slices, factors, risk_aversion, volatility_cap=cap
        )
        solve = optimizer.solve_problem(extended.problem)
        weights = None if solve.x is None else extended.weights(solve.x)
        extras: list[tuple[str, float]] = []
        scenario_metrics: tuple[ScenarioMetrics, ...] = ()
        objective = None
        if weights is not None and solve.x is not None:
            utilities = {
                s.scenario_id: _scenario_utility(
                    s, weights, risk_aversion, self._scenario_net(s, context, weights, treatment)
                )
                for s in slices
            }
            worst_id = min(utilities, key=lambda key: utilities[key])
            extras = [
                ("worst_case_utility", utilities[worst_id]),
                ("solver_t", float(solve.x[extended.role("t")])),
            ]
            objective = -utilities[worst_id]
            scenario_metrics = self._scenario_metrics(
                context, scenarios, weights, risk_aversion, treatment
            )
        result = dataclasses.replace(
            optimizer.assemble(
                problem=problem_i,
                treatment=treatment,
                strategy=strategy,
                context=context,
                solve=solve,
                weights=weights,
                checks=self._with_mandate(
                    self._scenario_checks(problem, context, scenarios, treatment),
                    optimizer.volatility_checks(context, cap),
                ),
                objective_value=objective,
                outcome=None,
                extras=extras,
            ),
            scenario_metrics=scenario_metrics,
        )
        return self._single(MultiScenarioMode.WORST_CASE, problem, scenarios, result, None)

    def solve_base_with_stress(
        self,
        problem: FrontierProblem,
        scenarios: ScenarioSet,
        treatment: CostTreatment,
        risk_aversion: float,
    ) -> MultiScenarioResult:
        """Utilidad del escenario BASE con los ``stress_limits`` de los demás escenarios (P14)."""
        stress_ids = tuple(
            s.scenario_id for s in scenarios.scenarios if s.stress_limits is not None
        )
        if not stress_ids:
            raise UnsupportedCombinationError(
                "BaseWithStressConstraints exige al menos un escenario con stress_limits; sin "
                "límites de estrés equivaldría al escenario BASE."
            )
        config_i, problem_i = self._intersection(problem, scenarios)
        optimizer = StrategyOptimizer(config_i)
        strategy = StrategyID.BASE_WITH_STRESS
        base = scenarios.base
        base_problem = (
            problem_i
            if base is None
            else dataclasses.replace(problem_i, risk_model=base.risk_model, costs=base.costs)
        )
        context, report = optimizer.prepare(base_problem, treatment)
        if context is None:
            result = optimizer.infeasible(base_problem, treatment, strategy, report)
            return self._single(
                MultiScenarioMode.BASE_WITH_STRESS_CONSTRAINTS, problem, scenarios, result, None
            )
        mandate, cap = optimizer.volatility_mandate(base_problem, treatment, strategy, context)
        if mandate is not None:
            return self._single(
                MultiScenarioMode.BASE_WITH_STRESS_CONSTRAINTS, problem, scenarios, mandate, None
            )
        stresses: list[StressSpec] = []
        for scenario, slice_ in zip(
            scenarios.scenarios, self._slices(context, scenarios, treatment), strict=True
        ):
            limits = scenario.stress_limits
            if limits is None:
                continue
            factor = (
                factor_covariance(slice_.sigma, self._config.conic)
                if limits.max_volatility is not None
                else None
            )
            stresses.append(StressSpec(slice_, factor, limits.max_volatility, limits.min_return))
        extended, _ = build_base_with_stress_problem(
            context.inputs, treatment, risk_aversion, stresses, volatility_cap=cap
        )
        solve = optimizer.solve_problem(extended.problem)
        weights = None if solve.x is None else extended.weights(solve.x)
        extras: list[tuple[str, float]] = []
        objective = None
        scenario_metrics: tuple[ScenarioMetrics, ...] = ()
        if weights is not None:
            base_utility = optimizer.treatment_return(
                context, weights, treatment
            ) - risk_aversion * float(weights @ context.inputs.sigma @ weights)
            extras = [("base_utility", base_utility)]
            objective = -base_utility
            scenario_metrics = self._scenario_metrics(
                context, scenarios, weights, risk_aversion, treatment
            )
        result = dataclasses.replace(
            optimizer.assemble(
                problem=base_problem,
                treatment=treatment,
                strategy=strategy,
                context=context,
                solve=solve,
                weights=weights,
                checks=self._with_mandate(
                    self._scenario_checks(problem, context, scenarios, treatment, stress=True),
                    optimizer.volatility_checks(context, cap),
                ),
                objective_value=objective,
                outcome=None,
                extras=extras,
                notes=tuple(f"stress:{s}" for s in stress_ids),
            ),
            scenario_metrics=scenario_metrics,
        )
        return self._single(
            MultiScenarioMode.BASE_WITH_STRESS_CONSTRAINTS, problem, scenarios, result, None
        )

    # ----------------------------------------------------------------------------- internos

    @staticmethod
    def _with_mandate(
        checks: AdvancedChecks, volatility: tuple[VolatilityLimitCheck, ...]
    ) -> AdvancedChecks:
        """Añade el mandato de volatilidad de la cartera a las comprobaciones por escenario."""
        return dataclasses.replace(checks, volatility=volatility)

    def _single(
        self,
        mode: MultiScenarioMode,
        problem: FrontierProblem,
        scenarios: ScenarioSet,
        result: StrategyResult,
        probabilities: tuple[tuple[str, float], ...] | None,
    ) -> MultiScenarioResult:
        return MultiScenarioResult(
            mode=mode,
            portfolio_id=problem.portfolio_id,
            scenario_ids=scenarios.ids,
            frontiers=(),
            strategies=(),
            single_solution=dataclasses.replace(result, scenario_id=f"MULTI:{mode.value}"),
            probabilities=probabilities,
            notes=(),
        )

    def _intersection(
        self, problem: FrontierProblem, scenarios: ScenarioSet
    ) -> tuple[EngineConfig, FrontierProblem]:
        """Configuración y problema con las restricciones de **todos** los escenarios a la vez."""
        constraint_configs = [self._config.constraints]
        constraint_configs += [s.constraints.constraints for s in scenarios.scenarios]
        merged = intersect_constraint_configs(constraint_configs)
        config = dataclasses.replace(self._config, constraints=merged)
        specs = [s.constraints.spec for s in scenarios.scenarios]
        spec = self._intersect_specs(problem.spec, specs)
        return config, dataclasses.replace(problem, spec=spec)

    @staticmethod
    def _intersect_specs(
        base: PortfolioSpec | None, specs: Sequence[PortfolioSpec | None]
    ) -> PortfolioSpec | None:
        if base is None:
            return None
        turnovers = [
            s.max_turnover for s in [base, *specs] if s is not None and s.max_turnover is not None
        ]
        if not turnovers:
            return base
        return dataclasses.replace(base, max_turnover=min(turnovers))

    def _slices(
        self, context: FrontierContext, scenarios: ScenarioSet, treatment: CostTreatment
    ) -> list[ScenarioSlice]:
        ids = context.compiled.asset_ids
        slices = []
        for scenario in scenarios.scenarios:
            model = scenario.risk_model
            position = {asset_id: index for index, asset_id in enumerate(model.asset_ids)}
            indices = np.array([position[a] for a in ids], dtype=np.int64)
            model_cost = self._cost_model(context, scenario.costs)
            buy = sell = None
            exit_cost = 0.0
            if treatment is CostTreatment.NET:
                if model_cost is None:
                    raise ScenarioError(f"{scenario.scenario_id}: NET exige costes del escenario.")
                positions = context.alignment.composition_positions
                buy = np.array(model_cost.buy_costs[positions], dtype=np.float64)
                sell = np.array(model_cost.sell_costs[positions], dtype=np.float64)
                exit_cost = model_cost.exit_cost_one_off()
            slices.append(
                ScenarioSlice(
                    scenario.scenario_id,
                    np.array(model.mu[indices], dtype=np.float64),
                    np.array(model.sigma[np.ix_(indices, indices)], dtype=np.float64),
                    buy,
                    sell,
                    exit_cost,
                )
            )
        return slices

    def _cost_model(
        self, context: FrontierContext, costs: AssetCostVector | None
    ) -> TransactionCostModel | None:
        if costs is None or not context.alignment.has_current_portfolio:
            return None
        return TransactionCostModel(
            context.alignment, costs, self._config.optimization_horizon_years
        )

    def _scenario_net(
        self,
        scenario: ScenarioSlice,
        context: FrontierContext,
        weights: npt.NDArray[np.float64],
        treatment: CostTreatment,
    ) -> float:
        gross = float(scenario.mu @ weights)
        if (
            treatment is not CostTreatment.NET
            or scenario.buy_costs is None
            or scenario.sell_costs is None
        ):
            return gross
        delta = context.alignment.expand(weights) - context.alignment.current_weights
        positions = context.alignment.composition_positions
        buy, sell = np.zeros(context.alignment.size), np.zeros(context.alignment.size)
        buy[positions], sell[positions] = scenario.buy_costs, scenario.sell_costs
        exit_mask = np.ones(context.alignment.size, dtype=bool)
        exit_mask[positions] = False
        buy[exit_mask] = 0.0  # los costes de los retirados se recogen en exit_cost_one_off
        cost = float(buy @ np.maximum(delta, 0.0) + sell @ np.maximum(-delta, 0.0))
        return gross - (cost + scenario.exit_cost_one_off) / self._config.optimization_horizon_years

    def _scenario_checks(
        self,
        problem: FrontierProblem,
        context: FrontierContext,
        scenarios: ScenarioSet,
        treatment: CostTreatment,
        *,
        stress: bool = False,
    ) -> AdvancedChecks:
        """Comprobaciones por escenario: **sus propias** restricciones compiladas y sus datos
        económicos (independientes de la intersección optimizada); con ``stress`` (solo
        ``BaseWithStress``) también sus ``stress_limits``, que ningún otro modo impone."""
        checks: list[ScenarioCheck] = []
        ids = context.compiled.asset_ids
        for scenario in scenarios.scenarios:
            model = scenario.risk_model
            position = {asset_id: index for index, asset_id in enumerate(model.asset_ids)}
            indices = np.array([position[a] for a in ids], dtype=np.int64)
            constraint_set = build_constraint_set(
                scenario.constraints.constraints,
                scenario.constraints.spec,
                problem.portfolio_id,
                self._config.frontier.min_holding_weight,
                self._config.candidates.unknown_liquidity_policy,
            )
            compiled = self._compiler.compile(constraint_set, problem.universe, ids, problem.state)
            limits = scenario.stress_limits if stress else None
            checks.append(
                ScenarioCheck(
                    scenario.scenario_id,
                    compiled,
                    ValidationContext(
                        np.array(model.mu[indices], dtype=np.float64),
                        np.array(model.sigma[np.ix_(indices, indices)], dtype=np.float64),
                        self._cost_model(context, scenario.costs),
                    ),
                    None if limits is None else limits.max_volatility,
                    None if limits is None else limits.min_return,
                    treatment,
                )
            )
        return AdvancedChecks(scenarios=tuple(checks))

    def _scenario_metrics(
        self,
        context: FrontierContext,
        scenarios: ScenarioSet,
        weights: npt.NDArray[np.float64],
        risk_aversion: float,
        treatment: CostTreatment,
    ) -> tuple[ScenarioMetrics, ...]:
        tolerances = StrategyOptimizer(self._config).metrics_tolerances
        out = []
        ids = context.compiled.asset_ids
        for scenario, slice_ in zip(
            scenarios.scenarios, self._slices(context, scenarios, treatment), strict=True
        ):
            model = scenario.risk_model
            position = {asset_id: index for index, asset_id in enumerate(model.asset_ids)}
            indices = np.array([position[a] for a in ids], dtype=np.int64)
            table = compute_metrics(
                weights,
                mu=np.array(model.mu[indices], dtype=np.float64),
                sigma=np.array(model.sigma[np.ix_(indices, indices)], dtype=np.float64),
                risk_free_rate=self._config.returns.risk_free_rate,
                tolerances=tolerances,
                alignment=context.alignment,
                cost_model=self._cost_model(context, scenario.costs),
            )
            out.append(
                ScenarioMetrics(
                    scenario.scenario_id,
                    table.row(0),
                    _scenario_utility(
                        slice_,
                        weights,
                        risk_aversion,
                        self._scenario_net(slice_, context, weights, treatment),
                    ),
                )
            )
        return tuple(out)

    def _aggregate_model(
        self,
        scenarios: ScenarioSet,
        probabilities: npt.NDArray[np.float64],
        problem: FrontierProblem,
    ) -> RiskModel:
        """Modelo de riesgo del escenario esperado sobre el universo completo del modelo base:
        ``μ̄ = Σ p_s μ_s`` y ``Σ̄ = Σ p_s Σ_s`` (SCN-005)."""
        base = problem.risk_model
        mu_all = np.zeros(len(base.asset_ids))
        sigma_all = np.zeros((len(base.asset_ids), len(base.asset_ids)))
        for scenario, probability in zip(scenarios.scenarios, probabilities.tolist(), strict=True):
            mu_all += probability * scenario.risk_model.mu
            sigma_all += probability * scenario.risk_model.sigma
        covariance = self._covariance.validate(
            (sigma_all + sigma_all.T) / 2.0,
            base.asset_ids,
            base.covariance.method,
            base.covariance.shrinkage,
            base.covariance.n_observations,
        )
        expected = ExpectedReturns(
            base.asset_ids, mu_all, base.expected_returns.mode, base.expected_returns.method
        )
        return RiskModel(expected, covariance)

    def _expected_costs(
        self, scenarios: ScenarioSet, probabilities: npt.NDArray[np.float64]
    ) -> AssetCostVector | None:
        vectors = [s.costs for s in scenarios.scenarios]
        if any(v is None for v in vectors):
            return None
        first = vectors[0]
        if first is None:
            return None
        buy = np.zeros_like(first.buy_costs)
        sell = np.zeros_like(first.sell_costs)
        for vector, probability in zip(vectors, probabilities.tolist(), strict=True):
            if vector is None or vector.asset_ids != first.asset_ids:
                raise ScenarioError("Los costes de los escenarios deben cubrir los mismos activos.")
            buy += probability * vector.buy_costs
            sell += probability * vector.sell_costs
        return AssetCostVector(first.asset_ids, buy, sell, first.sources)


def _scenario_utility(
    scenario: ScenarioSlice, weights: npt.NDArray[np.float64], risk_aversion: float, net: float
) -> float:
    """``U_s(w) = retorno_s(w) − λ wᵀΣ_s w`` (retorno neto de costes si ``net`` lo incluye)."""
    return net - risk_aversion * float(weights @ scenario.sigma @ weights)
