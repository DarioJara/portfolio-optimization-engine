"""Sesión de resolución de los puntos de una frontera (MASTER_SPEC §35-38, §47, §56).

Requisito: SOL-009.

Una ``FrontierSession`` posee **un** workspace QP por (composición, tratamiento de costes) y
resuelve secuencialmente todos los puntos de la frontera reutilizándolo: ``P`` y ``A`` fijos,
actualización de ``q`` (malla de theta) o de ``lower`` de la fila de retorno (malla de retorno
objetivo) y arranque en caliente desde el punto vecino. Con ``workspace_reuse = false`` cada
punto crea su propio workspace (referencia "cold setup" del benchmark).

Cada solución del solver se valida de forma independiente (``SolutionValidator``) y sus métricas
se recalculan desde los pesos; el estado del solver nunca basta para aceptarla (§44).
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.costs.transaction_cost_model import TransactionCostModel, UnionAlignment
from portfolio_engine.exceptions import FrontierError
from portfolio_engine.frontiers.numerical_recovery import NumericalRecovery
from portfolio_engine.metrics.portfolio_metrics import MetricsTolerances, compute_metrics
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    FrontierScope,
    ProblemClass,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.models.frontier import FrontierDiagnostics, FrontierPoint, PointMetrics
from portfolio_engine.models.solution import SolveResult, ValidationReport, sum_iterations_by_solver
from portfolio_engine.optimizers.base import OptimizationBackend
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.router import SolverRouter, solve_with_policy
from portfolio_engine.validation.solution_validator import SolutionValidator, ValidationContext
from portfolio_engine.validation.tolerances import ReturnTarget

#: Nota cuando la etapa 2 (desempate de mínima varianza) falla y se devuelve la etapa 1.
NOTE_MAX_RETURN_STAGE_2_FAILED = "MAX_RETURN_STAGE_2_FAILED_STAGE_1_SOLUTION_RETURNED"


@dataclass(frozen=True, eq=False, slots=True)
class FrontierContext:
    """Datos de una composición fija sobre los que se resuelve la frontera."""

    composition_id: str
    inputs: CompositionInputs
    alignment: UnionAlignment
    risk_free_rate: float

    @property
    def compiled(self) -> CompiledConstraints:
        """Restricciones compiladas de la composición."""
        return self.inputs.compiled

    @property
    def cost_model(self) -> TransactionCostModel | None:
        """Modelo de costes (``None`` sin cartera actual o sin datos de coste)."""
        return self.inputs.cost_model


class FrontierSession:
    """Resuelve puntos de una frontera con un workspace reutilizable (composición, tratamiento)."""

    def __init__(
        self,
        context: FrontierContext,
        cost_treatment: CostTreatment,
        method: FrontierMethod,
        solver_config: SolverConfig,
        router: SolverRouter,
        validator: SolutionValidator,
        tolerances: MetricsTolerances,
    ) -> None:
        if cost_treatment is CostTreatment.POST_COST_GROSS:
            raise FrontierError("Una sesión resuelve GROSS o NET; POST_COST_GROSS es ex post.")
        self._context = context
        self._treatment = cost_treatment
        self._method = method
        self._solver_config = solver_config
        self._router = router
        self._validator = validator
        self._tolerances = tolerances
        self._recovery = NumericalRecovery(solver_config)
        self._variance = build_fixed_composition_problem(
            context.inputs, cost_treatment, quadratic=True
        )
        self._shared: OptimizationBackend | None = None
        self._state_q = self._variance.problem.q
        self._state_lower = self._variance.problem.lower
        self._backends: list[OptimizationBackend] = []
        self._results: list[SolveResult] = []
        self._sequence = 0
        self._started = time.perf_counter()

    # ----------------------------------------------------------------------------- propiedades

    @property
    def context(self) -> FrontierContext:
        """Datos de la composición."""
        return self._context

    @property
    def cost_treatment(self) -> CostTreatment:
        """Tratamiento de costes optimizado (``GROSS`` o ``NET``)."""
        return self._treatment

    @property
    def variance_problem(self) -> BuiltProblem:
        """Problema de varianza (``P = 2Σ`` constante, ``A`` fija) del workspace compartido."""
        return self._variance

    @property
    def shared_backend(self) -> OptimizationBackend | None:
        """Backend del workspace compartido (``None`` antes del primer punto)."""
        return self._shared

    @property
    def total_iterations(self) -> int:
        """Iteraciones de todas las resoluciones (LP, etapa 2 y oráculo de recuperación incluidos).

        Métrica agregada de actividad de varios solvers; el desglose está en
        :attr:`iterations_by_solver`.
        """
        return sum(result.iterations for result in self._results)

    @property
    def iterations_by_solver(self) -> tuple[tuple[str, int], ...]:
        """Iteraciones por solver (OSQP, HiGHS) de todas las resoluciones, sin doble cómputo."""
        return sum_iterations_by_solver(
            item for result in self._results for item in result.iterations_by_solver
        )

    def net_return(self, weights: npt.NDArray[np.float64]) -> float:
        """Retorno del tratamiento optimizado: neto en ``NET``, bruto en ``GROSS``."""
        gross = float(self._context.inputs.mu @ weights)
        if self._treatment is CostTreatment.NET and self._context.cost_model is not None:
            return gross - float(self._context.cost_model.cost(weights))
        return gross

    # ---------------------------------------------------------------------- resolución de puntos

    def solve_risk_aversion(
        self, theta: float, *, strategy: StrategyID, adaptive: bool = False
    ) -> FrontierPoint:
        """``min wᵀΣw − θ μᵀw (+ θ TC(w) si NET)`` con ``q(θ) = θ·q1`` (``θ = 0``: MinVariance)."""
        q = self._variance.q_risk_aversion(theta)
        lower = self._variance.lower_free_return()
        result = self._run_variance(q, lower)
        return self._finish(
            result, self._variance, strategy, theta=theta, target=None, adaptive=adaptive
        )

    def solve_target(
        self, target: float, *, strategy: StrategyID, adaptive: bool = False
    ) -> FrontierPoint:
        """``min wᵀΣw`` s.a. retorno (bruto o neto) ``>= target``: solo cambia ``lower``."""
        q = self._variance.q_zero()
        lower = self._variance.lower_for_target(target)
        result = self._run_variance(q, lower, target)
        return self._finish(
            result, self._variance, strategy, theta=None, target=target, adaptive=adaptive
        )

    def solve_minimum_variance(self) -> FrontierPoint:
        """``min wᵀΣw`` sujeto a las restricciones (sin objetivo de retorno)."""
        result = self._run_variance(self._variance.q_zero(), self._variance.lower_free_return())
        return self._finish(
            result, self._variance, StrategyID.MIN_VARIANCE, theta=None, target=None, adaptive=False
        )

    def solve_maximum_return(self) -> tuple[FrontierPoint, tuple[str, ...]]:
        """Retorno máximo lexicográfico (A-14): ``max`` retorno y luego mínima varianza.

        Etapa 1: LP con ``P = 0`` (HiGHS, remediación R2-01); en NET maximiza el retorno neto
        ``μᵀw − TC(w)`` (incluida la liquidación de los activos retirados de la composición).

        Etapa 2: ``min wᵀΣw`` sobre la **cara óptima** del LP: por complementariedad, con un dual
        óptimo ``y`` del LP las soluciones óptimas son exactamente las factibles que dejan activas
        las filas con ``|y_i| > lp_feasibility_tolerance`` (se fijan como igualdades), y además
        ``retorno >= R* − tol`` con ``tol = SolverConfig.max_return_tie_tolerance(R*)`` (única
        fuente de esa holgura numérica). Una franja ``retorno >= R* − ε`` sin fijar la cara es un
        conjunto casi degenerado en el que OSQP declara inviabilidad espuria (AUDIT_BLOCK_2, H-1).
        La etapa 2 usa un workspace propio (no contamina el ``rho`` del compartido). Si no produce
        una solución válida se devuelve la de la etapa 1 con
        :data:`NOTE_MAX_RETURN_STAGE_2_FAILED`.
        """
        lp = build_fixed_composition_problem(self._context.inputs, self._treatment, quadratic=False)
        backend = self._router.route(lp.problem)
        self._backends.append(backend)
        backend.setup(lp.problem)
        first_result = solve_with_policy(backend, self._solver_config.ambiguous_status_policy)
        first = self._finish(
            first_result, lp, StrategyID.MAX_RETURN, theta=None, target=None, adaptive=False
        )
        if not first.is_valid_solution or first.weights is None:
            return first, ()
        best_return = self.net_return(first.weights)
        target = best_return - self._solver_config.max_return_tie_tolerance(best_return)
        second = self._solve_on_optimal_face(target, first_result.y)
        if second.is_valid_solution:
            return second, ()
        return first, (NOTE_MAX_RETURN_STAGE_2_FAILED,)

    # ----------------------------------------------------------------------------- diagnósticos

    def diagnostics(self) -> FrontierDiagnostics:
        """Contadores y tiempos agregados de todas las resoluciones de la sesión."""
        backends = self._backends
        first = backends[0] if backends else None
        return FrontierDiagnostics(
            solver_name=first.name if first else "NONE",
            solver_version=first.version if first else "NONE",
            setup_count=sum(backend.setup_count for backend in backends),
            update_count=sum(backend.update_count for backend in backends),
            solve_count=len(self._results),
            warm_start_count=sum(result.warm_start_used for result in self._results),
            cold_retry_count=sum(result.cold_retries for result in self._results),
            setup_time=sum(result.setup_time for result in self._results),
            update_time=sum(result.update_time for result in self._results),
            solve_time=sum(result.solve_time for result in self._results),
            frontier_time=time.perf_counter() - self._started,
            total_iterations=self.total_iterations,
            iterations_by_solver=self.iterations_by_solver,
        )

    def backends(self) -> Sequence[OptimizationBackend]:
        """Backends utilizados (para instrumentación y tests de reutilización de workspace)."""
        return tuple(self._backends)

    # -------------------------------------------------------------------------------- internos

    def _solve_on_optimal_face(
        self, target: float, duals: npt.NDArray[np.float64] | None
    ) -> FrontierPoint:
        """Etapa 2: mínima varianza con ``retorno >= target`` y la cara óptima del LP fijada."""
        built = self._variance
        base = built.problem
        lower = built.lower_for_target(target)
        upper = np.array(base.upper, dtype=np.float64)
        if duals is not None:
            binding = np.flatnonzero(np.abs(duals) > self._solver_config.lp_feasibility_tolerance)
            active = np.where(duals[binding] > 0.0, upper[binding], lower[binding])
            finite = np.isfinite(active)
            lower[binding[finite]] = upper[binding[finite]] = active[finite]
        problem = dataclasses.replace(
            base,
            name="fixed_composition_max_return_stage2",
            q=built.q_zero(),
            lower=lower,
            upper=upper,
        )
        backend = self._router.route(problem)
        self._backends.append(backend)
        backend.setup(problem)
        result = solve_with_policy(backend, self._solver_config.ambiguous_status_policy)
        return self._finish(
            result, built, StrategyID.MAX_RETURN, theta=None, target=target, adaptive=False
        )

    def _run_variance(
        self,
        q: npt.NDArray[np.float64],
        lower: npt.NDArray[np.float64],
        target: float | None = None,
    ) -> SolveResult:
        """Resuelve el problema de varianza con ``q`` y ``lower``, actualizando solo lo que
        cambia. Con ``target`` un estado no óptimo se somete a la recuperación numérica (F-3)."""
        problem = self._variance.problem
        reuse = self._solver_config.workspace_reuse
        if reuse and self._shared is not None:
            backend = self._shared
            previous_q, previous_lower = self._state_q, self._state_lower
        else:
            backend = self._router.route(problem)
            self._backends.append(backend)
            backend.setup(problem)
            previous_q, previous_lower = problem.q, problem.lower
            if reuse:
                self._shared = backend
        changed_q = None if np.array_equal(q, previous_q) else q
        changed_lower = None if np.array_equal(lower, previous_lower) else lower
        if changed_q is not None or changed_lower is not None:
            backend.update(q=changed_q, lower=changed_lower)
        self._state_q, self._state_lower = q, lower
        result = solve_with_policy(backend, self._solver_config.ambiguous_status_policy)
        if target is not None and self._recovery.applies(self._variance, lower, result):
            result = self._recovery.recover(
                self._variance,
                q,
                lower,
                result,
                self._backends,
                lambda retried: self._passes_validation(retried, target),
            )
        return result

    def _passes_validation(self, result: SolveResult, target: float) -> bool:
        """``True`` si la solución del solver supera el validador independiente (``target``)."""
        if result.x is None:
            return False
        return self._validate(self._variance.weights(result.x), target).is_valid

    def _finish(
        self,
        result: SolveResult,
        built: BuiltProblem,
        strategy: StrategyID,
        *,
        theta: float | None,
        target: float | None,
        adaptive: bool,
    ) -> FrontierPoint:
        self._results.append(result)
        sequence = self._sequence
        self._sequence += 1
        point_id = f"{self._treatment.value}:{self._method.value}:{sequence:04d}"
        weights: npt.NDArray[np.float64] | None = None
        report: ValidationReport | None = None
        metrics: PointMetrics | None = None
        objective: float | None = None
        valid = False
        source = result.status_source
        if result.x is not None:
            weights = built.weights(result.x)
            report = self._validate(weights, target)
            metrics = self._metrics(weights)
            objective = self._objective(weights, metrics, theta, built)
            valid = report.is_valid and self._status_accepted(result.status)
            if not report.is_valid:
                source = StatusSource.VALIDATOR
        return FrontierPoint(
            point_id=point_id,
            sequence=sequence,
            strategy_id=strategy,
            scope=FrontierScope.CONTINUOUS_FRONTIER,
            cost_treatment=self._treatment,
            method=self._method,
            composition_id=self._context.composition_id,
            theta=theta,
            target_return=target,
            weights=weights,
            metrics=metrics,
            objective_value=objective,
            solve=result,
            validation=report,
            is_valid_solution=valid,
            status=result.status,
            status_source=source,
            is_adaptive_insertion=adaptive,
        )

    def _status_accepted(self, status: SolverStatus) -> bool:
        if status is SolverStatus.OPTIMAL:
            return True
        return status is SolverStatus.OPTIMAL_INACCURATE and (
            self._solver_config.accept_inaccurate_solutions
        )

    def _validate(self, weights: npt.NDArray[np.float64], target: float | None) -> ValidationReport:
        context = ValidationContext(
            self._context.inputs.mu, self._context.inputs.sigma, self._context.cost_model
        )
        return_target = None
        if target is not None:
            treatment = (
                CostTreatment.NET if self._treatment is CostTreatment.NET else CostTreatment.GROSS
            )
            return_target = ReturnTarget(treatment, target)
        return self._validator.validate(weights, self._context.compiled, context, return_target)

    def _metrics(self, weights: npt.NDArray[np.float64]) -> PointMetrics:
        table = compute_metrics(
            weights,
            mu=self._context.inputs.mu,
            sigma=self._context.inputs.sigma,
            risk_free_rate=self._context.risk_free_rate,
            tolerances=self._tolerances,
            alignment=self._context.alignment,
            cost_model=self._context.cost_model,
        )
        return table.row(0)

    def _objective(
        self,
        weights: npt.NDArray[np.float64],
        metrics: PointMetrics,
        theta: float | None,
        built: BuiltProblem,
    ) -> float:
        """Valor del objetivo del punto, calculado desde los pesos (no desde el solver)."""
        if built.problem.problem_class is ProblemClass.LP:
            return -self.net_return(weights)
        if theta is None:
            return metrics.variance
        return metrics.variance - theta * self.net_return(weights)
