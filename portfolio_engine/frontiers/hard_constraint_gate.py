"""Puerta de restricciones obligatorias sobre la frontera global (HC-009, HC-011).

Aplica :class:`~portfolio_engine.hard_constraints.validator.FinalProposalValidator` a **cada punto**
de la ``GLOBAL_CANDIDATE_FRONTIER`` y construye el :class:`HardConstraintAudit`:

* los resultados originales del solver (``GlobalFrontierResult.points``) no se modifican; el
  veredicto de cada punto se publica aparte, con **todas** sus causas de rechazo;
* un punto es *aceptado* solo si el solver lo dio por válido (estado admisible y validación
  independiente B1–B4) **y** supera todas las restricciones obligatorias; los pesos nunca se
  retocan después del solver (no hay recortes ni renormalizaciones);
* la envolvente de los aceptados se recalcula solo entre aceptados (``pareto``), de modo que un
  punto eficiente pero rechazado no oculta a uno admisible;
* ``NO_FEASIBLE_SOLUTION`` si nada cumple tras buscar; ``INFEASIBLE`` si la factibilidad previa lo
  demuestra. Nunca se relaja un límite para devolver «algo».

Alcance matemático (``optimality_scope``): aceptar garantiza **admisibilidad** de lo devuelto; no
garantiza completitud de la búsqueda ni optimalidad global bajo la banda de volatilidad (véase
``HARD_CONSTRAINTS_DESIGN.md`` §5).
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Callable, Sequence

from portfolio_engine.candidates.candidate_engine import NOTE_MANDATE_INFEASIBLE
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.constraints.constraint_set import build_constraint_set
from portfolio_engine.frontiers.continuous_frontier import FrontierProblem
from portfolio_engine.frontiers.volatility_band import VolatilityBandSolver
from portfolio_engine.hard_constraints.validator import (
    EligibilityContext,
    FinalProposalValidator,
    ProposalContext,
)
from portfolio_engine.models.composition import CandidateComposition
from portfolio_engine.models.enums import AuditStatus, CostTreatment
from portfolio_engine.models.frontier import GlobalFrontierPoint
from portfolio_engine.models.hard_constraints import (
    BandProposal,
    EffectiveHardConstraints,
    FinalProposalReport,
    HardConstraintAudit,
    PointVerdict,
)
from portfolio_engine.models.portfolio import resolve_restricted_policy

OPTIMALITY_SCOPE = (
    "ADMISSIBILITY_ONLY: las propuestas aceptadas cumplen todas las restricciones obligatorias "
    "(recalculadas desde los pesos finales); no se garantiza completitud de la búsqueda ni "
    "optimalidad global con volatilidad mínima (restricción no convexa)."
)
CODE_SOLVER_REJECTED = "HC_REJECTED:SOLVER_VALIDITY"
CODE_NO_SOLUTION = "HC_REJECTED:NO_SOLUTION"


class HardConstraintGate:
    """Valida los puntos de una frontera global contra las restricciones obligatorias."""

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._validator = FinalProposalValidator()

    def context(
        self, problem: FrontierProblem, effective: EffectiveHardConstraints
    ) -> ProposalContext:
        """Datos oficiales contra los que se valida cualquier propuesta de ``problem``."""
        config = self._config
        constraint_set = build_constraint_set(
            config.constraints,
            problem.spec,
            problem.portfolio_id,
            config.frontier.min_holding_weight,
            config.candidates.unknown_liquidity_policy,
        )
        return ProposalContext(
            effective=effective,
            risk_model=problem.risk_model,
            current_weights=dict(
                zip(problem.state.asset_ids, problem.state.weights.tolist(), strict=True)
            ),
            costs=problem.costs,
            horizon_years=config.optimization_horizon_years,
            long_only=config.constraints.long_only,
            budget=1.0,
            max_turnover=constraint_set.max_turnover,
            turnover_tolerance=config.solver.constraint_tolerance,
            accept_inaccurate=config.solver.accept_inaccurate_solutions,
            eligibility=EligibilityContext(
                universe=problem.universe,
                state=problem.state,
                spec=problem.spec,
                restricted_policy=resolve_restricted_policy(
                    problem.spec, config.constraints.restricted_existing_position_policy
                ),
                unknown_liquidity_policy=config.candidates.unknown_liquidity_policy,
            ),
        )

    def audit(
        self,
        problem: FrontierProblem,
        effective: EffectiveHardConstraints,
        points: Sequence[GlobalFrontierPoint],
        candidate_notes: Sequence[str],
        candidate_count: int,
        envelope: Callable[[Sequence[GlobalFrontierPoint]], Sequence[GlobalFrontierPoint]],
        cost_treatment: CostTreatment = CostTreatment.GROSS,
    ) -> HardConstraintAudit:
        """Auditoría de ``points``; ``envelope`` calcula la envolvente Pareto de los aceptados."""
        context = self.context(problem, effective)
        verdicts = tuple(self._verdict(point, context) for point in points)
        accepted_ids = {v.global_point_id for v in verdicts if v.report.accepted}
        accepted = [point for point in points if point.global_point_id in accepted_ids]
        envelope_ids = tuple(point.global_point_id for point in envelope(accepted))
        causes = tuple(note for note in candidate_notes if note.startswith(NOTE_MANDATE_INFEASIBLE))
        counts: Counter[str] = Counter(
            code for verdict in verdicts for code in verdict.report.rejection_codes
        )
        if accepted_ids:
            status = AuditStatus.FEASIBLE
        elif candidate_count == 0 and causes:
            status = AuditStatus.INFEASIBLE
        else:
            status = AuditStatus.NO_FEASIBLE_SOLUTION
        return HardConstraintAudit(
            portfolio_id=problem.portfolio_id,
            effective=effective,
            status=status,
            preflight_causes=causes,
            verdicts=verdicts,
            accepted_point_ids=tuple(
                point.global_point_id for point in points if point.global_point_id in accepted_ids
            ),
            accepted_envelope_ids=envelope_ids,
            rejections_by_code=tuple(sorted(counts.items())),
            optimality_scope=OPTIMALITY_SCOPE,
            notes=tuple(candidate_notes),
            ranked_point_ids=self._ranking(verdicts, envelope_ids, effective, cost_treatment),
        )

    @staticmethod
    def _ranking(
        verdicts: Sequence[PointVerdict],
        envelope_ids: Sequence[str],
        effective: EffectiveHardConstraints,
        cost_treatment: CostTreatment,
    ) -> tuple[str, ...]:
        """Envolvente aceptada ordenada por ``retorno − penalización·Σw²`` (objetivo secundario)."""
        penalty = effective.diversification_penalty_weight or 0.0
        wanted = set(envelope_ids)
        scored: list[tuple[float, str]] = []
        for verdict in verdicts:
            metrics = verdict.report.metrics
            if verdict.global_point_id not in wanted or metrics is None:
                continue
            chosen = metrics.expected_return_gross
            if (
                cost_treatment is not CostTreatment.GROSS
                and metrics.expected_return_net is not None
            ):
                chosen = metrics.expected_return_net
            scored.append((-(chosen - penalty * metrics.hhi), verdict.global_point_id))
        return tuple(point_id for _, point_id in sorted(scored))

    def _verdict(self, point: GlobalFrontierPoint, context: ProposalContext) -> PointVerdict:
        weights = point.point.weights
        if weights is None:
            report = FinalProposalReport(
                point.global_point_id,
                False,
                (CODE_NO_SOLUTION,),
                (),
                None,
                context.effective.effective_hash,
            )
            return PointVerdict(point.global_point_id, point.composition_id, report)
        by_asset = dict(zip(point.asset_ids, weights.tolist(), strict=True))
        report = self._validator.validate(
            by_asset,
            context,
            label=point.global_point_id,
            solver_status=point.point.status,
        )
        if not point.is_valid_solution:
            report = FinalProposalReport(
                report.label,
                False,
                (CODE_SOLVER_REJECTED, *report.rejection_codes),
                report.checks,
                report.metrics,
                report.effective_hash,
            )
        return PointVerdict(point.global_point_id, point.composition_id, report)

    def with_band_proposals(
        self,
        audit: HardConstraintAudit,
        problem: FrontierProblem,
        compositions: Sequence[CandidateComposition],
        cost_treatment: CostTreatment,
    ) -> HardConstraintAudit:
        """Añade a ``audit`` la propuesta de máximo retorno con banda de cada composición.

        Cada propuesta se calcula con :class:`VolatilityBandSolver` (convexa con solo
        ``max_volatility``; no convexa con ``min_volatility``) y se valida con la validación final
        igual que cualquier punto. Si alguna es aceptada, el estado global es ``FEASIBLE``.
        """
        effective = audit.effective
        treatment = (
            CostTreatment.GROSS
            if cost_treatment is CostTreatment.POST_COST_GROSS
            else cost_treatment
        )
        solver = VolatilityBandSolver(self._config)
        context = self.context(problem, effective)
        proposals: list[BandProposal] = []
        for candidate in compositions:
            sub = dataclasses.replace(problem, composition_asset_ids=candidate.asset_ids)
            result = solver.solve(sub, treatment, effective)
            report = None
            weights = None
            if result.weights is not None:
                weights = tuple(float(w) for w in result.weights.tolist())
                report = self._validator.validate(
                    dict(zip(result.asset_ids, weights, strict=True)),
                    context,
                    label=f"BAND:{candidate.composition_id}",
                )
            proposals.append(
                BandProposal(
                    composition_id=candidate.composition_id,
                    asset_ids=candidate.asset_ids,
                    outcome=result.outcome.value,
                    weights=weights,
                    objective_value=result.objective_value,
                    upper_bound=result.upper_bound,
                    gap=result.gap,
                    starts_tried=result.starts_tried,
                    iterations=result.iterations,
                    notes=result.notes,
                    report=report,
                )
            )
        status = audit.status
        if any(proposal.accepted for proposal in proposals):
            status = AuditStatus.FEASIBLE
        return dataclasses.replace(audit, band_proposals=tuple(proposals), status=status)
