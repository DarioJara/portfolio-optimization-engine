"""``EXACT_MIP`` como modo de **validación** de heurísticas (MASTER_SPEC §49).

Requisitos: MIP-001, MIP-003, MIP-004.

Resuelve el MIQP de cardinalidad exacto (``MinWeight·z <= w <= MaxWeight·z``, ``Σz = K``) sobre un
universo pequeño con SCIP y lo compara con las composiciones que propone el ``CandidateEngine``
(heurístico), evaluadas cada una con su utilidad óptima exacta de composición fija (QP validado del
Bloque 2). Sirve para medir cuánto se aleja la heurística del óptimo y calibrarla; **nunca** se
ejecuta dentro del bucle interno de producción (el ``SolverRouter`` lo rechaza con
``inner_loop=True`` y los módulos del bucle interno no importan este).

Integridad de lo que se afirma:

* La solución del MIQP se **valida de forma independiente**: se toma la composición que elige
  (``z = 1``), se compilan de nuevo sus restricciones y se pasa por el
  ``AdvancedSolutionValidator``;
  además se comprueban integridad, cardinalidad, nuevos activos y swaps sobre ``z``. La utilidad se
  recalcula desde los pesos.
* Un ``optimality gap`` solo se informa si el solver aporta una **cota dual válida**. Sin ella
  ``gap_to_optimum_bound`` es ``None``: no se inventa. Con la brecha del solver abierta, el gap del
  heurístico frente a la cota dual es un **límite superior** de su distancia al óptimo, no el gap
  exacto.
* Solo con optimalidad probada (``MIP_PROVEN``) se dice que el heurístico es óptimo.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.constraints.integer import CompositionLimits, membership_rules
from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.frontiers.continuous_frontier import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.frontiers.session import FrontierContext
from portfolio_engine.frontiers.strategy_optimizer import StrategyOptimizer
from portfolio_engine.models.composition import CandidateComposition
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    OptimalityClaim,
    SolverStatus,
    StrategyID,
)
from portfolio_engine.models.solution import SolveResult, ValidationReport
from portfolio_engine.optimizers.formulations.conic import factor_covariance
from portfolio_engine.optimizers.formulations.miqp import build_cardinality_miqp
from portfolio_engine.validation.advanced_validator import AdvancedChecks, CardinalityCheck
from portfolio_engine.validation.solution_validator import ValidationContext

NOTE_NO_DUAL_BOUND = "NO_VALID_DUAL_BOUND_NO_GAP_CLAIMED"
NOTE_MIP_NOT_PROVEN = "MIP_NOT_PROVEN_OPTIMAL_GAP_IS_AN_UPPER_BOUND"


@dataclass(frozen=True, eq=False, slots=True)
class HeuristicGapReport:
    """Comparación de la mejor composición heurística con el MIQP exacto (MIP-003).

    Las utilidades son ``μᵀw − TC(w) − λ wᵀΣw`` (netas en ``NET``), recalculadas desde los pesos.

    Attributes:
        mip_status: estado del solver mixto entero.
        mip_claim: qué garantiza el solver (``MIP_PROVEN``, ``MIP_INCUMBENT``, ``FEASIBLE_ONLY``…).
        mip_valid: la solución del MIQP superó la validación independiente.
        mip_asset_ids: composición elegida por el MIQP (``z = 1``).
        mip_utility: utilidad recalculada de la solución del MIQP (``None`` sin solución).
        mip_utility_upper_bound: cota superior válida de la utilidad óptima (``−λ·cota dual``);
            ``None`` si el solver no aporta cota dual.
        mip_relative_gap: brecha relativa del solver (``None`` sin cota dual).
        heuristic_asset_ids: mejor composición heurística.
        heuristic_utility: utilidad exacta de la mejor composición heurística.
        heuristic_utilities: utilidad exacta de cada composición evaluada.
        gap_to_incumbent: ``mip_utility − heuristic_utility`` (``>= 0`` cuando el MIP es óptimo).
        gap_to_optimum_bound: ``mip_utility_upper_bound − heuristic_utility``: límite superior de
            la distancia del heurístico al óptimo (``None`` sin cota dual).
        heuristic_matches_optimum: ``True`` solo con óptimo probado y utilidad heurística igual a
            la del MIP (dentro de la tolerancia de brecha); ``None`` si no se puede afirmar.
        notes: limitaciones de la comparación.
    """

    portfolio_id: str
    scenario_id: str
    risk_aversion: float
    cost_treatment: CostTreatment
    universe_size: int
    mip_status: SolverStatus
    mip_claim: OptimalityClaim
    mip_valid: bool
    mip_asset_ids: tuple[str, ...]
    mip_utility: float | None
    mip_utility_upper_bound: float | None
    mip_relative_gap: float | None
    mip_nodes: int | None
    mip_solve_time: float | None
    heuristic_asset_ids: tuple[str, ...]
    heuristic_utility: float | None
    heuristic_utilities: tuple[tuple[tuple[str, ...], float], ...]
    gap_to_incumbent: float | None
    gap_to_optimum_bound: float | None
    heuristic_matches_optimum: bool | None
    validation: ValidationReport | None
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalibrationSummary:
    """Ajuste del ``CandidateEngine`` frente al MIQP exacto en varias instancias (MIP-004)."""

    instances: int
    proven_instances: int
    heuristic_optimal_count: int
    heuristic_optimal_share: float | None
    mean_gap_to_incumbent: float | None
    max_gap_to_incumbent: float | None
    unproven_instances: int


def calibration_summary(reports: Sequence[HeuristicGapReport]) -> CalibrationSummary:
    """Agrega informes de gap: cuántas instancias el heurístico igualó al óptimo **probado**.

    Solo las instancias con optimalidad probada y solución válida cuentan para la proporción; las
    demás se declaran ``unproven_instances`` (no se les atribuye ningún gap).
    """
    proven = [r for r in reports if r.mip_claim is OptimalityClaim.MIP_PROVEN and r.mip_valid]
    gaps = [r.gap_to_incumbent for r in proven if r.gap_to_incumbent is not None]
    optimal = sum(1 for r in proven if r.heuristic_matches_optimum)
    return CalibrationSummary(
        instances=len(reports),
        proven_instances=len(proven),
        heuristic_optimal_count=optimal,
        heuristic_optimal_share=(optimal / len(proven)) if proven else None,
        mean_gap_to_incumbent=(sum(gaps) / len(gaps)) if gaps else None,
        max_gap_to_incumbent=max(gaps) if gaps else None,
        unproven_instances=len(reports) - len(proven),
    )


@dataclass(frozen=True, eq=False, slots=True)
class _MipOutcome:
    """Resultado del MIQP ya validado (uso interno del informe)."""

    solve: SolveResult
    valid: bool
    members: tuple[str, ...]
    utility: float | None
    upper_bound: float | None
    relative_gap: float | None
    nodes: int | None
    validation: ValidationReport | None


class ExactMIPValidator:
    """Valida heurísticas de composición con el MIQP exacto (modo validación de ``EXACT_MIP``)."""

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._engine = ContinuousFrontierEngine(config)
        self._optimizer = StrategyOptimizer(config)

    def validate_heuristic(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        universe_asset_ids: Sequence[str],
        candidates: Sequence[CandidateComposition],
        *,
        limits: CompositionLimits | None = None,
        volatility_limit: float | None = None,
    ) -> HeuristicGapReport:
        """Gap de ``candidates`` frente al MIQP de cardinalidad sobre ``universe_asset_ids``.

        ``limits`` por defecto: ``TargetPortfolioSize`` de la especificación y ``max_new_assets`` /
        ``max_swaps`` de ``[candidates]`` (las mismas restricciones enteras que la heurística).
        """
        universe = tuple(sorted(universe_asset_ids))
        exact = self._config.exact_mip
        if len(universe) > exact.max_universe_size:
            raise UnsupportedCombinationError(
                f"El universo del MIP ({len(universe)}) supera exact_mip.max_universe_size "
                f"({exact.max_universe_size}): EXACT_MIP no es apto para universos grandes."
            )
        if not math.isfinite(risk_aversion) or risk_aversion <= 0.0:
            raise UnsupportedCombinationError("risk_aversion debe ser finito y > 0.")
        rules = limits or self._default_limits(problem)
        if volatility_limit is None and problem.spec is not None:
            volatility_limit = problem.spec.volatility_limit  # misma fuente que las estrategias
        heuristic = self._heuristic_utilities(
            problem, treatment, risk_aversion, candidates, volatility_limit
        )
        universe_problem = dataclasses.replace(problem, composition_asset_ids=universe)
        context, feasibility = self._optimizer.prepare(universe_problem, treatment)
        if context is None:
            causes = tuple(f"{c.code}: {c.detail}" for c in feasibility.causes)
            return self._report(
                problem, treatment, risk_aversion, universe, heuristic, None, causes
            )
        factor = (
            None
            if volatility_limit is None
            else factor_covariance(context.inputs.sigma, self._config.conic)
        )
        extended, _ = build_cardinality_miqp(
            context.inputs,
            treatment,
            risk_aversion,
            rules,
            volatility_factor=factor,
            volatility_limit=volatility_limit,
        )
        backend = self._optimizer.router.route(extended.problem)
        backend.setup(extended.problem)
        solve = backend.solve()
        outcome = self._outcome(
            problem, treatment, risk_aversion, universe, extended.role("z"), context, rules, solve
        )
        return self._report(problem, treatment, risk_aversion, universe, heuristic, outcome, ())

    # ------------------------------------------------------------------------------ internos

    def _default_limits(self, problem: FrontierProblem) -> CompositionLimits:
        candidates = self._config.candidates
        target = None if problem.spec is None else problem.spec.target_portfolio_size
        return CompositionLimits(
            target, candidates.max_new_assets, candidates.max_swaps, frozenset()
        )

    def _utility(
        self,
        context: FrontierContext,
        weights: npt.NDArray[np.float64],
        risk_aversion: float,
        treatment: CostTreatment,
    ) -> float:
        """``μᵀw − TC(w) − λ wᵀΣw`` recalculada desde los pesos."""
        ret = self._optimizer.treatment_return(context, weights, treatment)
        return ret - risk_aversion * float(weights @ context.inputs.sigma @ weights)

    def _heuristic_utilities(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        candidates: Sequence[CandidateComposition],
        volatility_limit: float | None,
    ) -> tuple[tuple[tuple[str, ...], float], ...]:
        """Utilidad óptima exacta de cada composición candidata, con las mismas restricciones que el
        MIQP: QP validado del Bloque 2 o, con ``VolatilityLimit``, el SOCP de volatilidad."""
        out: list[tuple[tuple[str, ...], float]] = []
        for candidate in candidates:
            sub = dataclasses.replace(problem, composition_asset_ids=candidate.asset_ids)
            context, _ = self._optimizer.prepare(sub, treatment)
            if context is None:
                continue
            weights = self._composition_optimum(sub, treatment, risk_aversion, volatility_limit)
            if weights is not None:
                value = self._utility(context, weights, risk_aversion, treatment)
                out.append((candidate.asset_ids, value))
        return tuple(out)

    def _composition_optimum(
        self,
        sub: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        volatility_limit: float | None,
    ) -> npt.NDArray[np.float64] | None:
        """Pesos óptimos validados de una composición fija (``None`` si no hay solución válida)."""
        if volatility_limit is not None:
            result = self._optimizer.volatility_target(
                sub, treatment, volatility_limit=volatility_limit, risk_aversion=risk_aversion
            )
            return result.weights if result.is_valid_solution else None
        session = self._engine.open_session(sub, treatment, FrontierMethod.RISK_AVERSION_GRID)
        point = session.solve_risk_aversion(1.0 / risk_aversion, strategy=StrategyID.FRONTIER_POINT)
        return point.weights if point.is_valid_solution else None

    def _outcome(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        universe: tuple[str, ...],
        z_start: int,
        context: FrontierContext,
        limits: CompositionLimits,
        solve: SolveResult,
    ) -> _MipOutcome:
        n = len(universe)
        mip = solve.mip
        vector = solve.x if solve.x is not None else (None if mip is None else mip.incumbent)
        members: tuple[str, ...] = ()
        utility: float | None = None
        report: ValidationReport | None = None
        valid = False
        if vector is not None:
            weights = np.array(vector[:n], dtype=np.float64)
            z = np.array(vector[z_start : z_start + n], dtype=np.float64)
            flags = np.round(z) > 0.5
            members = tuple(a for a, flag in zip(universe, flags.tolist(), strict=True) if flag)
            report, utility = self._validate_solution(
                problem, treatment, risk_aversion, universe, weights, z, members, context, limits
            )
            valid = report.is_valid and solve.status is SolverStatus.OPTIMAL
        upper: float | None = None
        gap: float | None = None
        if mip is not None and mip.has_valid_dual_bound and mip.dual_bound is not None:
            # objetivo del MIQP = wᵀΣw − θ(μᵀw − TC) = −(utilidad)/λ (θ = 1/λ): una cota dual
            # inferior del objetivo es una cota superior de la utilidad
            upper = -risk_aversion * mip.dual_bound
            gap = mip.relative_gap
        return _MipOutcome(
            solve, valid, members, utility, upper, gap, None if mip is None else mip.nodes, report
        )

    def _validate_solution(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        universe: tuple[str, ...],
        weights: npt.NDArray[np.float64],
        z: npt.NDArray[np.float64],
        members: tuple[str, ...],
        context: FrontierContext,
        limits: CompositionLimits,
    ) -> tuple[ValidationReport, float | None]:
        """Validación independiente: composición recompilada y comprobaciones sobre ``z``."""
        cardinality = CardinalityCheck(
            z=z,
            integrality_tolerance=self._config.exact_mip.integrality_tolerance,
            target_size=limits.target_size,
            max_new_assets=limits.max_new_assets,
            max_swaps=limits.max_swaps,
            mandatory=membership_rules(context.compiled).mandatory,
        )
        union = self._optimizer.validator.validate_cardinality(
            weights, context.compiled, cardinality
        )
        if not members:
            return union, None
        selected = dataclasses.replace(problem, composition_asset_ids=members)
        member_context, feasibility = self._optimizer.prepare(selected, treatment)
        if member_context is None:
            causes = tuple(f"{c.code}: {c.detail}" for c in feasibility.causes)
            failed = ValidationReport(False, math.inf, union.violations, (*union.checks, *causes))
            return failed, None
        member_weights = np.array([weights[universe.index(a)] for a in members], dtype=np.float64)
        composition = self._optimizer.validator.validate(
            member_weights,
            member_context.compiled,
            ValidationContext(
                member_context.inputs.mu, member_context.inputs.sigma, member_context.cost_model
            ),
            AdvancedChecks(),
        )
        merged = ValidationReport(
            union.is_valid and composition.is_valid,
            max(union.max_violation, composition.max_violation),
            (*union.violations, *composition.violations),
            (*union.checks, *composition.checks),
        )
        return merged, self._utility(member_context, member_weights, risk_aversion, treatment)

    def _report(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        risk_aversion: float,
        universe: tuple[str, ...],
        heuristic: tuple[tuple[tuple[str, ...], float], ...],
        outcome: _MipOutcome | None,
        causes: tuple[str, ...],
    ) -> HeuristicGapReport:
        best_assets: tuple[str, ...] = ()
        best_utility: float | None = None
        if heuristic:
            best_assets, best_utility = max(heuristic, key=lambda item: item[1])
        notes = list(causes)
        status = SolverStatus.INFEASIBLE
        claim = OptimalityClaim.NOT_ASSESSED
        if outcome is not None:
            status, claim = outcome.solve.status, outcome.solve.optimality_claim
            if outcome.upper_bound is None:
                notes.append(NOTE_NO_DUAL_BOUND)
            if claim is not OptimalityClaim.MIP_PROVEN:
                notes.append(NOTE_MIP_NOT_PROVEN)
        utility = None if outcome is None else outcome.utility
        upper = None if outcome is None else outcome.upper_bound
        gap_incumbent = None if utility is None or best_utility is None else utility - best_utility
        gap_bound = None if upper is None or best_utility is None else upper - best_utility
        matches: bool | None = None
        if (
            outcome is not None
            and claim is OptimalityClaim.MIP_PROVEN
            and outcome.valid
            and gap_incumbent is not None
        ):
            exact = self._config.exact_mip
            tolerance = exact.absolute_gap_tolerance + exact.relative_gap_tolerance * abs(
                utility or 0.0
            )
            matches = gap_incumbent <= max(tolerance, self._config.solver.constraint_tolerance)
        return HeuristicGapReport(
            portfolio_id=problem.portfolio_id,
            scenario_id=problem.scenario_id,
            risk_aversion=risk_aversion,
            cost_treatment=treatment,
            universe_size=len(universe),
            mip_status=status,
            mip_claim=claim,
            mip_valid=bool(outcome is not None and outcome.valid),
            mip_asset_ids=() if outcome is None else outcome.members,
            mip_utility=utility,
            mip_utility_upper_bound=upper,
            mip_relative_gap=None if outcome is None else outcome.relative_gap,
            mip_nodes=None if outcome is None else outcome.nodes,
            mip_solve_time=None if outcome is None else outcome.solve.solve_time,
            heuristic_asset_ids=best_assets,
            heuristic_utility=best_utility,
            heuristic_utilities=heuristic,
            gap_to_incumbent=gap_incumbent,
            gap_to_optimum_bound=gap_bound,
            heuristic_matches_optimum=matches,
            validation=None if outcome is None else outcome.validation,
            notes=tuple(notes),
        )
