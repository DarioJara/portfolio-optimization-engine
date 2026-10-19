"""``StrategyOptimizer``: estrategias nombradas del Bloque 4 sobre una composición fija.

Requisitos: OPT-009..012, OPT-014, ROB-002..006, SOL-005, VAL-003.

Reutiliza el motor continuo del Bloque 2 (``ContinuousFrontierEngine.prepare``: restricciones
compiladas, factibilidad previa, submatrices por índices y modelo de costes; ``SolverRouter``;
``compute_metrics``) y **no** duplica su optimización: cada estrategia construye su problema con las
formulaciones de ``optimizers.formulations`` sobre el mismo :class:`CompositionInputs`, lo envía al
backend que le corresponde por su estructura matemática (QP→OSQP, LP→HiGHS, SOCP→Clarabel) y
valida la solución con el ``AdvancedSolutionValidator``, que la recalcula desde los pesos.

Estrategias: ``MAX_SHARPE`` (Charnes-Cooper, SOCP), ``VOL_TARGET`` (SOCP), ``MIN_CVAR`` /
``CVAR_LIMITED`` (Rockafellar-Uryasev, LP/QP) y ``ROBUST`` (peor caso de conjuntos de
incertidumbre, QP/SOCP). Las estrategias de solución única multiescenario viven en
:mod:`portfolio_engine.scenarios`.

Un resultado solo es ``is_valid_solution`` si el estado del solver es aceptable (``OPTIMAL``;
``OPTIMAL_INACCURATE`` solo con ``accept_inaccurate_solutions``) **y** el validador independiente lo
aprueba. Ninguna combinación no admitida se ignora: se rechaza con
:class:`UnsupportedCombinationError`.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from scipy.stats import chi2

from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.constraints.feasibility import FeasibilityReport, check_volatility
from portfolio_engine.exceptions import DataValidationError, UnsupportedCombinationError
from portfolio_engine.frontiers.continuous_frontier import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.frontiers.session import FrontierContext
from portfolio_engine.metrics.cvar_metric import (
    conditional_value_at_risk,
    portfolio_losses,
    value_at_risk,
)
from portfolio_engine.metrics.portfolio_metrics import MetricsTolerances, compute_metrics
from portfolio_engine.metrics.robust_metric import (
    worst_case_box_return,
    worst_case_ellipsoid_return,
    worst_case_variance,
)
from portfolio_engine.models.cvar import ReturnScenarioSet
from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    ExpectedReturnMode,
    FrontierMethod,
    MuUncertaintyKind,
    OptimalityClaim,
    SharpeOutcome,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.models.frontier import PointMetrics
from portfolio_engine.models.solution import SolveResult, ValidationReport
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.optimizers.formulations.conic import PSDFactor, factor_covariance
from portfolio_engine.optimizers.formulations.cvar import build_cvar_problem
from portfolio_engine.optimizers.formulations.model_builder import ExtendedProblem
from portfolio_engine.optimizers.formulations.qp_builder import (
    CompositionInputs,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.formulations.robust import (
    MuUncertaintySet,
    build_robust_problem,
)
from portfolio_engine.optimizers.formulations.sharpe import build_maximum_sharpe_problem
from portfolio_engine.optimizers.formulations.volatility import (
    VolatilityCap,
    build_volatility_problem,
    require_volatility_limit,
)
from portfolio_engine.optimizers.problem import CanonicalProblem
from portfolio_engine.optimizers.router import SolverRouter, solve_with_policy
from portfolio_engine.validation.advanced_validator import (
    AdvancedChecks,
    AdvancedSolutionValidator,
    CVaRCheck,
    SharpeCheck,
    VolatilityLimitCheck,
)
from portfolio_engine.validation.solution_validator import ValidationContext
from portfolio_engine.validation.tolerances import ValidationTolerances

NOTE_SHARPE_NOT_VALIDATED = "SHARPE_SOLUTION_NOT_VALIDATED"
NOTE_MIN_VARIANCE_CERTIFICATE_SKIPPED = "MIN_VARIANCE_CERTIFICATE_NOT_AVAILABLE"
CAUSE_VOLATILITY_BELOW_MINIMUM = "VOLATILITY_LIMIT_BELOW_MINIMUM_VARIANCE"


class StrategyOptimizer:
    """Resuelve estrategias nombradas de una cartera (un escenario, una composición fija)."""

    def __init__(self, config: EngineConfig, router: SolverRouter | None = None) -> None:
        self._config = config
        self._engine = ContinuousFrontierEngine(config)
        self._router = router or SolverRouter.from_engine_config(config)
        self._validator = AdvancedSolutionValidator(ValidationTolerances.from_config(config.solver))
        self._tolerances = MetricsTolerances.from_config(config.solver, config.frontier)

    # ------------------------------------------------------------------ infraestructura común

    @property
    def config(self) -> EngineConfig:
        """Configuración del motor."""
        return self._config

    @property
    def metrics_tolerances(self) -> MetricsTolerances:
        """Tolerancias de las métricas (de configuración)."""
        return self._tolerances

    @property
    def router(self) -> SolverRouter:
        """Router de backends (para instrumentación y tests)."""
        return self._router

    @property
    def validator(self) -> AdvancedSolutionValidator:
        """Validador independiente de las formulaciones del Bloque 4."""
        return self._validator

    def prepare(
        self, problem: FrontierProblem, treatment: CostTreatment
    ) -> tuple[FrontierContext | None, FeasibilityReport]:
        """Contexto de la composición y factibilidad previa (``None`` si es inviable)."""
        return self._engine.prepare(problem, treatment)

    def solve_problem(self, problem: CanonicalProblem) -> SolveResult:
        """Enruta ``problem`` por su estructura matemática y lo resuelve con la política vigente."""
        backend = self._router.route(problem)
        backend.setup(problem)
        return solve_with_policy(backend, self._config.solver.ambiguous_status_policy)

    def accepts(self, status: SolverStatus) -> bool:
        """``True`` si el estado es aceptable (``OPTIMAL``; inaccurate solo si se autoriza)."""
        if status is SolverStatus.OPTIMAL:
            return True
        return status is SolverStatus.OPTIMAL_INACCURATE and (
            self._config.solver.accept_inaccurate_solutions
        )

    def metrics_of(
        self, context: FrontierContext, weights: npt.NDArray[np.float64]
    ) -> PointMetrics:
        """Métricas de ``weights`` recalculadas desde los pesos con ``μ_C``/``Σ_C`` del contexto."""
        table = compute_metrics(
            weights,
            mu=context.inputs.mu,
            sigma=context.inputs.sigma,
            risk_free_rate=context.risk_free_rate,
            tolerances=self._tolerances,
            alignment=context.alignment,
            cost_model=context.cost_model,
        )
        return table.row(0)

    def treatment_return(
        self,
        context: FrontierContext,
        weights: npt.NDArray[np.float64],
        treatment: CostTreatment,
    ) -> float:
        """Retorno del tratamiento optimizado: ``μᵀw − TC(w)`` en ``NET``, ``μᵀw`` en ``GROSS``."""
        gross = float(context.inputs.mu @ weights)
        if treatment is CostTreatment.NET and context.cost_model is not None:
            return gross - float(context.cost_model.cost(weights))
        return gross

    def infeasible(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        strategy: StrategyID,
        report: FeasibilityReport,
    ) -> StrategyResult:
        """Resultado ``INFEASIBLE`` por factibilidad previa (el solver no se invocó, A-15)."""
        causes = tuple(f"{cause.code}: {cause.detail}" for cause in report.causes)
        return self._empty(
            problem,
            treatment,
            strategy,
            SolverStatus.INFEASIBLE,
            StatusSource.PRE_SOLVER_CHECK,
            None,
            causes,
        )

    def _empty(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        strategy: StrategyID,
        status: SolverStatus,
        source: StatusSource,
        outcome: str | None,
        notes: tuple[str, ...],
        solve: SolveResult | None = None,
    ) -> StrategyResult:
        return StrategyResult(
            portfolio_id=problem.portfolio_id,
            scenario_id=problem.scenario_id,
            strategy_id=strategy,
            composition_id="",
            asset_ids=(),
            cost_treatment=treatment,
            weights=None,
            metrics=None,
            scenario_metrics=(),
            objective_value=None,
            solve=solve,
            validation=None,
            is_valid_solution=False,
            status=status,
            status_source=source,
            outcome=outcome,
            optimality_claim=OptimalityClaim.NOT_ASSESSED,
            extras=(),
            notes=notes,
            solver_names=()
            if solve is None
            else tuple(name for name, _ in solve.iterations_by_solver),
        )

    def assemble(
        self,
        *,
        problem: FrontierProblem,
        treatment: CostTreatment,
        strategy: StrategyID,
        context: FrontierContext,
        solve: SolveResult,
        weights: npt.NDArray[np.float64] | None,
        checks: AdvancedChecks,
        objective_value: float | None,
        outcome: str | None,
        extras: Sequence[tuple[str, float]] = (),
        notes: Sequence[str] = (),
        scenario_metrics: tuple[object, ...] = (),
    ) -> StrategyResult:
        """Valida ``weights`` de forma independiente y arma el :class:`StrategyResult`."""
        report: ValidationReport | None = None
        metrics: PointMetrics | None = None
        source = solve.status_source
        valid = False
        if weights is not None:
            report = self._validator.validate(
                weights,
                context.compiled,
                ValidationContext(context.inputs.mu, context.inputs.sigma, context.cost_model),
                checks,
            )
            metrics = self.metrics_of(context, weights)
            valid = report.is_valid and self.accepts(solve.status)
            if not report.is_valid:
                source = StatusSource.VALIDATOR
        claim = solve.optimality_claim if valid else OptimalityClaim.NOT_ASSESSED
        return StrategyResult(
            portfolio_id=problem.portfolio_id,
            scenario_id=problem.scenario_id,
            strategy_id=strategy,
            composition_id=context.composition_id,
            asset_ids=context.compiled.asset_ids,
            cost_treatment=treatment,
            weights=weights,
            metrics=metrics,
            scenario_metrics=tuple(scenario_metrics),  # type: ignore[arg-type]
            objective_value=objective_value,
            solve=solve,
            validation=report,
            is_valid_solution=valid,
            status=solve.status,
            status_source=source,
            outcome=outcome,
            optimality_claim=claim,
            extras=tuple(extras),
            notes=tuple(notes),
            solver_names=tuple(name for name, _ in solve.iterations_by_solver),
        )

    # ------------------------------------------------------------------------------ Max Sharpe

    def max_sharpe(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        *,
        volatility_limit: float | None = None,
    ) -> StrategyResult:
        """Carteras de máximo ratio de Sharpe (bruto o neto) por Charnes-Cooper (SOCP, A-13)."""
        strategy = StrategyID.MAX_SHARPE
        context, report = self.prepare(problem, treatment)
        if context is None:
            return self.infeasible(problem, treatment, strategy, report)
        limit = self._volatility_limit(problem, volatility_limit)
        certificate = self._volatility_certificate(problem, treatment, limit, strategy, context)
        if certificate is not None:
            return certificate
        applicability = self._sharpe_applicability(problem, treatment, context)
        if applicability is not None:
            return applicability
        inputs = context.inputs
        factor = factor_covariance(inputs.sigma, self._config.conic)
        rf = context.risk_free_rate
        built = build_maximum_sharpe_problem(inputs, treatment, factor, rf, volatility_limit=limit)
        solve = self.solve_problem(built.problem)
        if solve.x is None:
            outcome = (
                SharpeOutcome.INFEASIBLE
                if solve.status is SolverStatus.INFEASIBLE
                else SharpeOutcome.SOLVER_FAILURE
            )
            return self._empty(
                problem,
                treatment,
                strategy,
                solve.status,
                solve.status_source,
                outcome.value,
                (),
                solve,
            )
        weights = built.weights(solve.x)
        if weights is None:
            return self._empty(
                problem,
                treatment,
                strategy,
                SolverStatus.NUMERICAL_ERROR,
                StatusSource.VALIDATOR,
                SharpeOutcome.SOLVER_FAILURE.value,
                ("KAPPA_NOT_POSITIVE",),
                solve,
            )
        sharpe = self._config.sharpe
        vol = math.sqrt(max(float(weights @ inputs.sigma @ weights), 0.0))
        zero = vol <= self._config.frontier.zero_volatility_tolerance
        outcome = SharpeOutcome.UNBOUNDED_ZERO_VOLATILITY if zero else SharpeOutcome.OPTIMAL
        checks = AdvancedChecks(
            volatility=self._limit_checks(inputs.sigma, limit),
            sharpe=SharpeCheck(
                rf,
                treatment,
                sharpe.min_excess_return,
                sharpe.agreement_tolerance,
                built.implied_sharpe(solve.x),
                self._config.frontier.zero_volatility_tolerance,
            ),
        )
        excess = self.treatment_return(context, weights, treatment) - rf
        ratio = None if zero else excess / vol
        extras = [("excess_return", excess)]
        if ratio is not None:
            extras.append(("sharpe", ratio))
        implied = built.implied_sharpe(solve.x)
        if implied is not None:
            extras.append(("implied_sharpe", implied))
        result = self.assemble(
            problem=problem,
            treatment=treatment,
            strategy=strategy,
            context=context,
            solve=solve,
            weights=weights,
            checks=checks,
            objective_value=None if ratio is None else -ratio,
            outcome=outcome.value,
            extras=extras,
            notes=(() if not zero else ("ZERO_VOLATILITY_POSITIVE_EXCESS_RETURN",)),
        )
        if outcome is SharpeOutcome.OPTIMAL and not result.is_valid_solution:
            # AUDIT_BLOCK_4 F-03: ``OPTIMAL`` solo se afirma con estado aceptable Y validación
            # independiente superada; si no (p. ej. Σ singular con ruido numérico en su núcleo)
            # el veredicto es un fallo, nunca un óptimo etiquetado como tal.
            return dataclasses.replace(
                result,
                outcome=SharpeOutcome.SOLVER_FAILURE.value,
                notes=(*result.notes, NOTE_SHARPE_NOT_VALIDATED),
            )
        return result

    def _sharpe_applicability(
        self, problem: FrontierProblem, treatment: CostTreatment, context: FrontierContext
    ) -> StrategyResult | None:
        """Precondición A-13: existe ``w`` factible con exceso de retorno positivo.

        Resuelve el LP de máximo exceso ``max (μ−rf)ᵀw − TC(w)`` (HiGHS). ``INFEASIBLE`` →
        restricciones incompatibles; exceso máximo ``<= min_excess_return`` → ``NOT_APPLICABLE``.
        """
        inputs = context.inputs
        shifted = CompositionInputs(
            inputs.mu - context.risk_free_rate, inputs.sigma, inputs.compiled, inputs.cost_model
        )
        lp = build_fixed_composition_problem(shifted, treatment, quadratic=False)
        solve = self.solve_problem(lp.problem)
        strategy = StrategyID.MAX_SHARPE
        if solve.x is None:
            outcome = (
                SharpeOutcome.INFEASIBLE
                if solve.status is SolverStatus.INFEASIBLE
                else SharpeOutcome.SOLVER_FAILURE
            )
            return self._empty(
                problem,
                treatment,
                strategy,
                solve.status,
                solve.status_source,
                outcome.value,
                (),
                solve,
            )
        best = lp.weights(solve.x)
        gross = float((inputs.mu - context.risk_free_rate) @ best)
        cost = (
            0.0
            if inputs.cost_model is None or not lp.cost_in_objective
            else float(inputs.cost_model.cost(best))
        )
        maximum = gross - cost
        if maximum <= self._config.sharpe.min_excess_return:
            return self._empty(
                problem,
                treatment,
                strategy,
                solve.status,
                StatusSource.PRE_SOLVER_CHECK,
                SharpeOutcome.NOT_APPLICABLE.value,
                (f"MAX_ACHIEVABLE_EXCESS_RETURN={maximum!r}",),
                solve,
            )
        return None

    # ------------------------------------------------------------------- control de volatilidad

    def volatility_target(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        *,
        volatility_limit: float | None = None,
        risk_aversion: float | None = None,
    ) -> StrategyResult:
        """``max`` retorno (o utilidad) con ``√(wᵀΣw) <= VolatilityLimit`` (SOCP, OPT-010)."""
        strategy = StrategyID.VOL_TARGET
        context, report = self.prepare(problem, treatment)
        if context is None:
            return self.infeasible(problem, treatment, strategy, report)
        limit = self._volatility_limit(problem, volatility_limit)
        if limit is None:
            raise UnsupportedCombinationError(
                "VolatilityLimit no configurado (ni argumento ni PortfolioSpec.volatility_limit)."
            )
        certificate = self._volatility_certificate(problem, treatment, limit, strategy, context)
        if certificate is not None:
            return certificate
        inputs = context.inputs
        factor = factor_covariance(inputs.sigma, self._config.conic)
        extended, _ = build_volatility_problem(
            inputs, treatment, factor, limit, risk_aversion=risk_aversion
        )
        solve = self.solve_problem(extended.problem)
        weights = None if solve.x is None else extended.weights(solve.x)
        checks = AdvancedChecks(volatility=self._limit_checks(inputs.sigma, limit))
        objective = None if weights is None else -self.treatment_return(context, weights, treatment)
        return self.assemble(
            problem=problem,
            treatment=treatment,
            strategy=strategy,
            context=context,
            solve=solve,
            weights=weights,
            checks=checks,
            objective_value=objective,
            outcome=None,
            extras=self._level_extras(context, weights, limit, treatment),
        )

    def _volatility_limit(self, problem: FrontierProblem, explicit: float | None) -> float | None:
        if explicit is not None:
            return require_volatility_limit(explicit)
        if problem.spec is not None and problem.spec.volatility_limit is not None:
            return require_volatility_limit(problem.spec.volatility_limit)
        return None

    def volatility_mandate(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        strategy: StrategyID,
        context: FrontierContext,
    ) -> tuple[StrategyResult | None, VolatilityCap | None]:
        """Mandato ``PortfolioSpec.volatility_limit`` de una estrategia que no lo optimiza.

        Ninguna formulación lo ignora: devuelve ``(resultado inviable, None)`` si el límite es
        incompatible (FEA-005), ``(None, cono)`` para añadir ``‖Lᵀw‖ <= σ_max`` a la formulación, o
        ``(None, None)`` si la cartera no declara límite. El validador recibe además el límite
        (:meth:`volatility_checks`) y recalcula la volatilidad desde los pesos.
        """
        limit = self._volatility_limit(problem, None)
        if limit is None:
            return None, None
        certificate = self._volatility_certificate(problem, treatment, limit, strategy, context)
        if certificate is not None:
            return certificate, None
        factor = factor_covariance(context.inputs.sigma, self._config.conic)
        return None, VolatilityCap(factor, limit)

    def volatility_checks(
        self, context: FrontierContext, cap: VolatilityCap | None
    ) -> tuple[VolatilityLimitCheck, ...]:
        """Comprobación independiente del mandato de volatilidad (vacía sin mandato)."""
        return self._limit_checks(context.inputs.sigma, None if cap is None else cap.limit)

    def _limit_checks(
        self, sigma: npt.NDArray[np.float64], limit: float | None
    ) -> tuple[VolatilityLimitCheck, ...]:
        if limit is None:
            return ()
        return (VolatilityLimitCheck(sigma, limit, "portfolio"),)

    def _level_extras(
        self,
        context: FrontierContext,
        weights: npt.NDArray[np.float64] | None,
        limit: float,
        treatment: CostTreatment,
    ) -> tuple[tuple[str, float], ...]:
        if weights is None:
            return ()
        vol = math.sqrt(max(float(weights @ context.inputs.sigma @ weights), 0.0))
        return (
            ("volatility", vol),
            ("volatility_limit", limit),
            ("return", self.treatment_return(context, weights, treatment)),
        )

    def _volatility_certificate(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        limit: float | None,
        strategy: StrategyID,
        context: FrontierContext,
    ) -> StrategyResult | None:
        """Inviabilidad de un ``VolatilityLimit`` antes del solver cónico (FEA-005).

        1. Reglas deterministas (:func:`check_volatility`): límite inválido o menor que la cota
           inferior de la volatilidad con solo el presupuesto.
        2. Certificado de MinVariance: si ``σ_min > VolatilityLimit`` es inviable, con ``σ_min`` la
           volatilidad de la cartera de mínima varianza validada del Bloque 2 (OSQP) bajo **todas**
           las restricciones. Si esa cartera no es válida el certificado no está disponible y se
           deja decidir al solver cónico (no se asume nada).
        """
        if limit is None:
            return None
        tolerance = self._config.solver.constraint_tolerance
        rules = check_volatility(context.inputs.sigma, context.compiled.budget, limit, tolerance)
        if rules:
            return self._empty(
                problem,
                treatment,
                strategy,
                SolverStatus.INFEASIBLE,
                StatusSource.PRE_SOLVER_CHECK,
                None,
                tuple(f"{cause.code}: {cause.detail}" for cause in rules),
            )
        session = self._engine.open_session(
            problem,
            treatment,
            FrontierMethod.RISK_AVERSION_GRID,
            volatility_limit_handled=True,  # solo MinVariance; el límite es de esta estrategia
        )
        point = session.solve_minimum_variance()
        if not point.is_valid_solution or point.metrics is None:
            return None
        if limit + tolerance >= point.metrics.volatility:
            return None
        return self._empty(
            problem,
            treatment,
            strategy,
            SolverStatus.INFEASIBLE,
            StatusSource.PRE_SOLVER_CHECK,
            None,
            (
                f"{CAUSE_VOLATILITY_BELOW_MINIMUM}: VolatilityLimit={limit!r} < "
                f"σ_min={point.metrics.volatility!r} (cartera de mínima varianza validada)",
            ),
        )

    # ------------------------------------------------------------------------------------ CVaR

    def cvar(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        scenarios: ReturnScenarioSet,
        objective: CVaRObjective,
        *,
        max_cvar: float | None = None,
        risk_aversion: float | None = None,
    ) -> StrategyResult:
        """Mínimo CVaR o ``CVaR <= MaxCVaR`` con Rockafellar-Uryasev (OPT-011, OPT-012)."""
        strategy = (
            StrategyID.MIN_CVAR if objective is CVaRObjective.MIN_CVAR else StrategyID.CVAR_LIMITED
        )
        context, report = self.prepare(problem, treatment)
        if context is None:
            return self.infeasible(problem, treatment, strategy, report)
        limit = self._config.cvar.max_cvar if max_cvar is None else max_cvar
        mandate, cap = self.volatility_mandate(problem, treatment, strategy, context)
        if mandate is not None:
            return mandate
        if objective is not CVaRObjective.MIN_CVAR and limit is None:
            raise UnsupportedCombinationError(
                "El objetivo con límite exige MaxCVaR (argumento o [cvar])."
            )
        extended, _ = build_cvar_problem(
            context.inputs,
            scenarios,
            self._config.cvar,
            treatment,
            objective,
            max_cvar=limit,
            risk_aversion=risk_aversion,
            volatility_cap=cap,
        )
        solve = self.solve_problem(extended.problem)
        weights = None if solve.x is None else extended.weights(solve.x)
        returns = scenarios.columns_for(context.compiled.asset_ids)
        checks = AdvancedChecks(
            volatility=self.volatility_checks(context, cap),
            cvar=CVaRCheck(
                returns,
                scenarios.weights,
                self._config.cvar.confidence_level,
                self._config.cvar.horizon_factor,
                limit,
            ),
        )
        extras, objective_value = self._cvar_extras(
            context, scenarios, weights, solve, extended, objective, treatment
        )
        return self.assemble(
            problem=problem,
            treatment=treatment,
            strategy=strategy,
            context=context,
            solve=solve,
            weights=weights,
            checks=checks,
            objective_value=objective_value,
            outcome=None,
            extras=extras,
        )

    def _cvar_extras(
        self,
        context: FrontierContext,
        scenarios: ReturnScenarioSet,
        weights: npt.NDArray[np.float64] | None,
        solve: SolveResult,
        extended: ExtendedProblem,
        objective: CVaRObjective,
        treatment: CostTreatment,
    ) -> tuple[tuple[tuple[str, float], ...], float | None]:
        if weights is None or solve.x is None:
            return (), None
        config = self._config.cvar
        losses = portfolio_losses(scenarios.columns_for(context.compiled.asset_ids), weights)
        cvar_period = conditional_value_at_risk(losses, scenarios.weights, config.confidence_level)
        var_period = value_at_risk(losses, scenarios.weights, config.confidence_level)
        extras = [
            ("cvar_period", cvar_period),
            ("cvar_horizon", cvar_period * config.horizon_factor),
            ("var_period", var_period),
            ("alpha", float(solve.x[extended.role("alpha")])),
        ]
        value = (
            cvar_period
            if objective is CVaRObjective.MIN_CVAR
            else -self.treatment_return(context, weights, treatment)
        )
        return tuple(extras), value

    # ---------------------------------------------------------------------------------- robusta

    def robust(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        *,
        mu_set: MuUncertaintySet | None = None,
        covariance_scale_max: float | None = None,
    ) -> StrategyResult:
        """Utilidad del peor caso con conjuntos de incertidumbre de ``μ`` y/o ``Σ`` (ROB-005).

        Sin ``mu_set`` ni ``covariance_scale_max`` se derivan de ``[robust]`` (solo con estimación
        interna: el error de muestreo no describe la incertidumbre de un alpha externo).
        """
        strategy = StrategyID.ROBUST
        context, report = self.prepare(problem, treatment)
        if context is None:
            return self.infeasible(problem, treatment, strategy, report)
        mandate, cap = self.volatility_mandate(problem, treatment, strategy, context)
        if mandate is not None:
            return mandate
        inputs = context.inputs
        set_mu = mu_set if mu_set is not None else self._mu_set(problem, inputs)
        scale = (
            covariance_scale_max
            if covariance_scale_max is not None
            else self._config.robust.covariance_scale_max
        )
        factors: tuple[PSDFactor, ...] = ()
        if scale is not None:
            factors = (factor_covariance(scale * inputs.sigma, self._config.conic),)
        extended, _ = build_robust_problem(
            inputs, treatment, risk_aversion, set_mu, factors, volatility_cap=cap
        )
        solve = self.solve_problem(extended.problem)
        weights = None if solve.x is None else extended.weights(solve.x)
        checks = AdvancedChecks(volatility=self.volatility_checks(context, cap))
        extras: list[tuple[str, float]] = []
        objective = None
        if weights is not None:
            nominal = self._nominal_utility(context, weights, risk_aversion, treatment)
            worst = self._worst_case_utility(
                context, weights, risk_aversion, set_mu, scale, treatment
            )
            extras = [("nominal_utility", nominal), ("worst_case_utility", worst)]
            objective = -worst
        return self.assemble(
            problem=problem,
            treatment=treatment,
            strategy=strategy,
            context=context,
            solve=solve,
            weights=weights,
            checks=checks,
            objective_value=objective,
            outcome=None,
            extras=extras,
            notes=(
                set_mu.kind.value,
                "covariance_scale" if scale is not None else "no_covariance_set",
            ),
        )

    def _mu_set(self, problem: FrontierProblem, inputs: CompositionInputs) -> MuUncertaintySet:
        config = self._config.robust
        kind = config.mu_uncertainty
        if kind is MuUncertaintyKind.NONE:
            return MuUncertaintySet(MuUncertaintyKind.NONE)
        if problem.risk_model.expected_returns.mode is not ExpectedReturnMode.INTERNAL_ESTIMATION:
            raise UnsupportedCombinationError(
                "La incertidumbre de μ derivada del error de muestreo no describe un alpha "
                "externo: suministre un MuUncertaintySet explícito."
            )
        years = (
            problem.risk_model.covariance.n_observations
            / self._config.returns.trading_days_per_year
        )
        if years <= 0.0:
            raise DataValidationError("La estimación no informa el número de observaciones.")
        variance_of_mean = np.diag(inputs.sigma) / years
        if kind is MuUncertaintyKind.BOX:
            return MuUncertaintySet(
                kind,
                half_width=float(config.box_z or 0.0) * np.sqrt(variance_of_mean),
            )
        omega = inputs.sigma / years
        radius = math.sqrt(
            float(chi2.ppf(float(config.ellipsoid_confidence or 0.0), inputs.mu.shape[0]))
        )
        return MuUncertaintySet(
            kind,
            radius=radius,
            omega_factor=factor_covariance(omega, self._config.conic),
            omega=omega,
        )

    def _nominal_utility(
        self,
        context: FrontierContext,
        w: npt.NDArray[np.float64],
        risk_aversion: float,
        treatment: CostTreatment,
    ) -> float:
        return self.treatment_return(context, w, treatment) - risk_aversion * float(
            w @ context.inputs.sigma @ w
        )

    def _worst_case_utility(
        self,
        context: FrontierContext,
        w: npt.NDArray[np.float64],
        risk_aversion: float,
        mu_set: MuUncertaintySet,
        scale: float | None,
        treatment: CostTreatment,
    ) -> float:
        """Utilidad del peor caso recalculada con las fórmulas cerradas (independiente)."""
        inputs = context.inputs
        mu_hat = inputs.mu
        cost = 0.0
        if treatment is CostTreatment.NET and context.cost_model is not None:
            cost = float(context.cost_model.cost(w))
        if mu_set.kind is MuUncertaintyKind.BOX and mu_set.half_width is not None:
            ret = worst_case_box_return(w, mu_hat, mu_set.half_width)
        elif mu_set.kind is MuUncertaintyKind.ELLIPSOIDAL and mu_set.omega is not None:
            ret = worst_case_ellipsoid_return(w, mu_hat, mu_set.omega, float(mu_set.radius or 0.0))
        else:
            ret = float(mu_hat @ w)
        sigma = inputs.sigma if scale is None else scale * inputs.sigma
        return ret - cost - risk_aversion * worst_case_variance(w, [sigma])
