"""Validación final obligatoria de propuestas (HC-009; MASTER_SPEC §44).

Se ejecuta **antes** de aceptar cualquier propuesta y la decide solo desde los *pesos finales* y los
datos oficiales (``RiskModel``: ``μ`` y ``Σ`` anualizados; cartera original; costes), sin leer
ninguna variable ni estado del solver. Una propuesta que viole cualquier restricción obligatoria se
rechaza con **todas** sus causas (no solo la primera) y nunca puede etiquetarse como solución
óptima válida; los resultados originales del solver se conservan fuera de este módulo.

Comprobaciones (cada una produce un :class:`CheckResult` con valor, límite y exceso):

``SOLVER_STATUS``  estado admisible (``OPTIMAL``; ``OPTIMAL_INACCURATE`` solo si se autoriza).
``FINITE`` · ``BUDGET`` · ``LONG_ONLY``  pesos finitos, ``Σw = 1`` y no negativos.
``CARDINALITY``  posiciones realmente mantenidas (``w_i > position_weight_threshold``) dentro de
                 los tamaños admisibles; ``DUST_MASS``: la masa de pesos positivos por debajo del
                 umbral no supera la tolerancia (no se esconde cardinalidad en pesos diminutos).
``MAX_ADDED`` · ``MAX_REMOVED`` · ``MAX_TOTAL_CHANGED`` · ``MAX_REPLACEMENTS`` ·
``MAX_PURE_ADDITIONS`` · ``MAX_PURE_REMOVALS`` · ``MAX_SWAPS``  respecto a la cartera original.
``MIN_ACTIVE_WEIGHT`` · ``MAX_ACTIVE_WEIGHT``  por posición (con excepciones por activo).
``MAX_HHI`` · ``MIN_EFFECTIVE_POSITIONS``  concentración ``Σ w²`` y ``N_eff = 1 / Σ w²``.
``MIN_VOLATILITY`` · ``MAX_VOLATILITY``  ``σ = √(wᵀΣw)`` recalculada con la ``Σ`` oficial.
``MIN_EXPECTED_RETURN``  suelo absoluto y/o ``μᵀw >= μᵀw0``, bruto o neto de costes.
``MAX_TURNOVER`` · ``MAX_TRANSACTION_COST``  rotación ``0.5·Σ|w − w0|`` (incluye liquidaciones
                 completas) y coste único de la transición.
``ELIGIBILITY``  elegibilidad y mandato de la composición (``validate_candidate_composition``).
``SOLVER_CONTRACT``  restricciones B1–B4 compiladas (``SolutionValidator``), si se proporcionan.

La tolerancia de cada comprobación procede de :class:`EffectiveHardConstraints` y nunca supera
``TOLERANCE_CEILING``; además la tolerancia de volatilidad se acota a la centésima parte del ancho
de la banda, de modo que una tolerancia numérica no puede volver aceptable una violación material.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.constraints.integer import CompositionLimits
from portfolio_engine.hard_constraints.counts import change_counts, positions_of
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import (
    CostTreatment,
    RestrictedExistingPositionPolicy,
    SolverStatus,
    UnknownFlagPolicy,
)
from portfolio_engine.models.hard_constraints import (
    CheckResult,
    EffectiveHardConstraints,
    FinalProposalReport,
    ProposalMetrics,
)
from portfolio_engine.models.portfolio import CurrentPortfolioState, PortfolioSpec
from portfolio_engine.models.risk_model import RiskModel
from portfolio_engine.validation.composition_validator import validate_candidate_composition
from portfolio_engine.validation.solution_validator import SolutionValidator, ValidationContext

#: La tolerancia de volatilidad no puede superar esta fracción del ancho de la banda (materialidad).
BAND_TOLERANCE_FRACTION = 0.01

CHECK_SOLVER_STATUS = "SOLVER_STATUS"
CHECK_FINITE = "FINITE"
CHECK_BUDGET = "BUDGET"
CHECK_LONG_ONLY = "LONG_ONLY"
CHECK_CARDINALITY = "CARDINALITY"
CHECK_DUST = "DUST_MASS"
CHECK_MAX_ADDED = "MAX_ADDED"
CHECK_MAX_REMOVED = "MAX_REMOVED"
CHECK_MAX_TOTAL = "MAX_TOTAL_CHANGED"
CHECK_MAX_REPLACEMENTS = "MAX_REPLACEMENTS"
CHECK_MAX_PURE_ADDITIONS = "MAX_PURE_ADDITIONS"
CHECK_MAX_PURE_REMOVALS = "MAX_PURE_REMOVALS"
CHECK_MAX_SWAPS = "MAX_SWAPS"
CHECK_MIN_ACTIVE = "MIN_ACTIVE_WEIGHT"
CHECK_MAX_ACTIVE = "MAX_ACTIVE_WEIGHT"
CHECK_MAX_HHI = "MAX_HHI"
CHECK_MIN_NEFF = "MIN_EFFECTIVE_POSITIONS"
CHECK_MIN_VOLATILITY = "MIN_VOLATILITY"
CHECK_MAX_VOLATILITY = "MAX_VOLATILITY"
CHECK_MIN_RETURN = "MIN_EXPECTED_RETURN"
CHECK_MAX_TURNOVER = "MAX_TURNOVER"
CHECK_MAX_COST = "MAX_TRANSACTION_COST"
CHECK_ELIGIBILITY = "ELIGIBILITY"
CHECK_SOLVER_CONTRACT = "SOLVER_CONTRACT"
REJECTION_PREFIX = "HC_REJECTED"


@dataclass(frozen=True, eq=False, slots=True)
class EligibilityContext:
    """Datos crudos para comprobar elegibilidad y mandato de la composición final."""

    universe: Universe
    state: CurrentPortfolioState
    spec: PortfolioSpec | None
    restricted_policy: RestrictedExistingPositionPolicy | None
    unknown_liquidity_policy: UnknownFlagPolicy


@dataclass(frozen=True, eq=False, slots=True)
class ProposalContext:
    """Datos oficiales contra los que se valida una propuesta.

    Attributes:
        effective: restricciones obligatorias efectivas de la cartera.
        risk_model: ``μ`` y ``Σ`` anualizados oficiales (se extraen submatrices por ``AssetID``).
        current_weights: cartera original (``AssetID → peso``).
        costs: costes unitarios de compra/venta (``None`` = no disponibles).
        horizon_years: horizonte para anualizar el coste (``OptimizationHorizonYears``).
        long_only: si se exigen pesos no negativos.
        budget: presupuesto ``Σ w``.
        max_turnover: turnover máximo efectivo (``None`` = no configurado).
        turnover_tolerance: tolerancia de la comprobación de turnover y coste.
        accept_inaccurate: si ``OPTIMAL_INACCURATE`` es un estado admisible.
        eligibility: datos de elegibilidad (``None`` = no se comprueba aquí).
    """

    effective: EffectiveHardConstraints
    risk_model: RiskModel
    current_weights: Mapping[str, float]
    costs: AssetCostVector | None
    horizon_years: float
    long_only: bool
    budget: float
    max_turnover: float | None
    turnover_tolerance: float
    accept_inaccurate: bool
    eligibility: EligibilityContext | None = None


class _Recorder:
    def __init__(self) -> None:
        self.checks: list[CheckResult] = []

    def record(
        self,
        check: str,
        value: float,
        limit: float | None,
        excess: float,
        tolerance: float,
        detail: str = "",
    ) -> None:
        passed = math.isfinite(excess) and excess <= tolerance
        self.checks.append(CheckResult(check, passed, value, limit, excess, tolerance, detail))

    def upper(
        self, check: str, value: float, limit: float | None, tolerance: float, detail: str = ""
    ) -> None:
        """``value <= limit`` (sin límite: comprobación omitida)."""
        if limit is not None:
            self.record(check, value, limit, value - limit, tolerance, detail)

    def lower(
        self, check: str, value: float, limit: float | None, tolerance: float, detail: str = ""
    ) -> None:
        """``value >= limit`` (sin límite: comprobación omitida)."""
        if limit is not None:
            self.record(check, value, limit, limit - value, tolerance, detail)


def volatility_tolerance(effective: EffectiveHardConstraints) -> float:
    """Tolerancia de volatilidad efectiva: la configurada, acotada por la banda (materialidad)."""
    tolerance = effective.volatility_tolerance
    low, high = effective.min_volatility, effective.max_volatility
    if low is not None and high is not None and high > low:
        tolerance = min(tolerance, BAND_TOLERANCE_FRACTION * (high - low))
    return tolerance


def official_moments(risk_model: RiskModel, weights: Mapping[str, float]) -> tuple[float, float]:
    """``(μᵀw, wᵀΣw)`` desde el ``RiskModel`` oficial (submatriz por ``AssetID``).

    Lanza ``KeyError`` si un activo con peso no está en el modelo de riesgo.
    """
    index = {asset_id: i for i, asset_id in enumerate(risk_model.asset_ids)}
    held = [asset_id for asset_id, weight in weights.items() if weight != 0.0]
    positions = np.array([index[asset_id] for asset_id in held], dtype=np.int64)
    vector = np.array([weights[asset_id] for asset_id in held], dtype=np.float64)
    if vector.size == 0:
        return 0.0, 0.0
    mean = float(risk_model.mu[positions] @ vector)
    variance = float(vector @ risk_model.sigma[np.ix_(positions, positions)] @ vector)
    return mean, variance


class FinalProposalValidator:
    """Valida propuestas finales contra las restricciones obligatorias efectivas."""

    def validate(
        self,
        weights: Mapping[str, float],
        context: ProposalContext,
        *,
        label: str = "",
        solver_status: SolverStatus | None = None,
        compiled: CompiledConstraints | None = None,
        compiled_weights: npt.ArrayLike | None = None,
        solution_validator: SolutionValidator | None = None,
    ) -> FinalProposalReport:
        """Informe de ``weights`` (pesos finales por ``AssetID``; los activos ausentes pesan 0).

        ``solver_status`` ``None`` se interpreta como «sin solver» (validación de pesos dados);
        un estado no admisible rechaza la propuesta. ``compiled`` junto con ``compiled_weights``
        y ``solution_validator`` añade el contrato B1–B4 (``SOLVER_CONTRACT``).
        """
        effective = context.effective
        recorder = _Recorder()
        self._status(recorder, solver_status, context)
        finite = all(math.isfinite(w) for w in weights.values())
        recorder.record(CHECK_FINITE, 0.0 if finite else 1.0, 0.0, 0.0 if finite else math.inf, 0.0)
        if not finite:
            return self._report(label, recorder, None, effective)
        try:
            metrics = self._checks(recorder, weights, context, effective)
        except KeyError as error:
            recorder.record(
                CHECK_ELIGIBILITY, 1.0, 0.0, math.inf, 0.0, f"activo sin datos oficiales: {error}"
            )
            return self._report(label, recorder, None, effective)
        self._eligibility(recorder, weights, context, effective)
        if compiled is not None and compiled_weights is not None and solution_validator is not None:
            self._solver_contract(recorder, compiled, compiled_weights, context, solution_validator)
        return self._report(label, recorder, metrics, effective)

    # --------------------------------------------------------------------------------- pasos

    def _status(
        self, recorder: _Recorder, status: SolverStatus | None, context: ProposalContext
    ) -> None:
        if status is None:
            return
        acceptable = status is SolverStatus.OPTIMAL or (
            status is SolverStatus.OPTIMAL_INACCURATE and context.accept_inaccurate
        )
        recorder.record(
            CHECK_SOLVER_STATUS,
            0.0 if acceptable else 1.0,
            0.0,
            0.0 if acceptable else math.inf,
            0.0,
            status.value,
        )

    def _checks(
        self,
        recorder: _Recorder,
        weights: Mapping[str, float],
        context: ProposalContext,
        effective: EffectiveHardConstraints,
    ) -> ProposalMetrics:
        threshold = effective.position_weight_threshold
        w_tol, b_tol = effective.weight_tolerance, effective.budget_tolerance
        total = float(sum(weights.values()))
        recorder.record(CHECK_BUDGET, total, context.budget, abs(total - context.budget), b_tol)
        if context.long_only:
            worst = min(weights.values(), default=0.0)
            recorder.record(CHECK_LONG_ONLY, worst, 0.0, -worst, w_tol)
        held = positions_of(weights, threshold)
        original = positions_of(context.current_weights, threshold)
        counts = change_counts(original, held)
        self._cardinality(recorder, counts.final_size, effective)
        dust = float(sum(w for w in weights.values() if 0.0 < w <= threshold))
        recorder.upper(CHECK_DUST, dust, 0.0, w_tol)
        for check, value, limit in (
            (CHECK_MAX_ADDED, counts.added, effective.max_added_assets),
            (CHECK_MAX_REMOVED, counts.removed, effective.max_removed_assets),
            (CHECK_MAX_TOTAL, counts.total_changed, effective.max_total_changed_assets),
            (CHECK_MAX_REPLACEMENTS, counts.replacements, effective.max_replacements),
            (CHECK_MAX_PURE_ADDITIONS, counts.pure_additions, effective.max_pure_additions),
            (CHECK_MAX_PURE_REMOVALS, counts.pure_removals, effective.max_pure_removals),
            (CHECK_MAX_SWAPS, counts.swaps, effective.max_swaps),
        ):
            recorder.upper(check, float(value), None if limit is None else float(limit), 0.0)
        position_weights = {asset_id: weights[asset_id] for asset_id in held}
        self._weights(recorder, position_weights, effective)
        squares = float(sum(w * w for w in position_weights.values()))
        self._concentration(recorder, squares, effective)
        mean, variance = official_moments(context.risk_model, weights)
        volatility = math.sqrt(max(variance, 0.0)) if math.isfinite(variance) else math.nan
        v_tol = volatility_tolerance(effective)
        recorder.lower(CHECK_MIN_VOLATILITY, volatility, effective.min_volatility, v_tol)
        recorder.upper(CHECK_MAX_VOLATILITY, volatility, effective.max_volatility, v_tol)
        base_mean, _ = official_moments(context.risk_model, context.current_weights)
        cost_one_off = self._cost(context, weights)
        net = None if cost_one_off is None else mean - cost_one_off / context.horizon_years
        self._returns(recorder, effective, mean, net, base_mean)
        turnover = self._turnover(recorder, weights, context)
        recorder.upper(
            CHECK_MAX_COST,
            math.nan if cost_one_off is None else cost_one_off,
            effective.max_transaction_cost,
            context.turnover_tolerance,
            "costes no disponibles" if cost_one_off is None else "",
        )
        return ProposalMetrics(
            size=counts.final_size,
            added=counts.added,
            removed=counts.removed,
            total_changed=counts.total_changed,
            replacements=counts.replacements,
            pure_additions=counts.pure_additions,
            pure_removals=counts.pure_removals,
            swaps=counts.swaps,
            weight_sum=total,
            min_position_weight=min(position_weights.values(), default=None),
            max_position_weight=max(position_weights.values(), default=None),
            hhi=squares,
            effective_positions=None if squares <= 0.0 else 1.0 / squares,
            volatility=volatility,
            expected_return_gross=mean,
            expected_return_net=net,
            original_expected_return=base_mean,
            turnover=turnover,
            transaction_cost_one_off=cost_one_off,
        )

    def _cardinality(
        self, recorder: _Recorder, size: int, effective: EffectiveHardConstraints
    ) -> None:
        allowed = effective.allowed_sizes
        if allowed:
            below, above = max(min(allowed) - size, 0), max(size - max(allowed), 0)
            gap = float(below + above)
            if size not in allowed and gap == 0.0:
                gap = 1.0  # tamaño dentro del rango pero excluido (objetivo exacto)
        else:
            gap = math.inf
        recorder.record(
            CHECK_CARDINALITY,
            float(size),
            None if not allowed else float(min(allowed)),
            gap,
            0.0,
            f"tamaños admisibles {list(allowed)}",
        )

    def _weights(
        self,
        recorder: _Recorder,
        position_weights: Mapping[str, float],
        effective: EffectiveHardConstraints,
    ) -> None:
        tolerance = effective.weight_tolerance
        for asset_id, weight in sorted(position_weights.items()):
            exception = effective.exception_for(asset_id)
            low = effective.min_active_weight
            high = effective.max_active_weight
            if exception is not None:
                low = exception.min_weight if exception.min_weight is not None else low
                high = exception.max_weight if exception.max_weight is not None else high
            if low is not None and weight < low - tolerance:
                recorder.lower(CHECK_MIN_ACTIVE, weight, low, tolerance, asset_id)
            if high is not None and weight > high + tolerance:
                recorder.upper(CHECK_MAX_ACTIVE, weight, high, tolerance, asset_id)
        if position_weights and not any(
            check.check in {CHECK_MIN_ACTIVE, CHECK_MAX_ACTIVE} for check in recorder.checks
        ):
            if effective.min_active_weight is not None:
                recorder.lower(
                    CHECK_MIN_ACTIVE,
                    min(position_weights.values()),
                    effective.min_active_weight,
                    tolerance,
                )
            if effective.max_active_weight is not None:
                recorder.upper(
                    CHECK_MAX_ACTIVE,
                    max(position_weights.values()),
                    effective.max_active_weight,
                    tolerance,
                )

    def _concentration(
        self, recorder: _Recorder, squares: float, effective: EffectiveHardConstraints
    ) -> None:
        tolerance = effective.hhi_tolerance
        recorder.upper(CHECK_MAX_HHI, squares, effective.max_concentration_hhi, tolerance)
        minimum = effective.min_effective_number_of_positions
        if minimum is not None:
            effective_positions = math.inf if squares <= 0.0 else 1.0 / squares
            recorder.lower(CHECK_MIN_NEFF, effective_positions, minimum, tolerance)

    def _cost(self, context: ProposalContext, weights: Mapping[str, float]) -> float | None:
        if context.costs is None:
            return None
        index = {asset_id: i for i, asset_id in enumerate(context.costs.asset_ids)}
        total = 0.0
        for asset_id in sorted(set(weights) | set(context.current_weights)):
            delta = weights.get(asset_id, 0.0) - context.current_weights.get(asset_id, 0.0)
            if delta == 0.0:
                continue
            if asset_id not in index:
                return None
            position = index[asset_id]
            unit = (
                context.costs.buy_costs[position]
                if delta > 0
                else context.costs.sell_costs[position]
            )
            total += float(unit) * abs(delta)
        return total

    def _returns(
        self,
        recorder: _Recorder,
        effective: EffectiveHardConstraints,
        gross: float,
        net: float | None,
        original: float,
    ) -> None:
        floors = []
        if effective.min_expected_return is not None:
            floors.append(effective.min_expected_return)
        if effective.preserve_original_expected_return:
            floors.append(original)
        if not floors:
            return
        use_net = effective.expected_return_treatment is CostTreatment.NET
        value = net if use_net else gross
        tolerance = effective.return_tolerance
        if value is None:
            recorder.record(
                CHECK_MIN_RETURN,
                math.nan,
                max(floors),
                math.inf,
                tolerance,
                "retorno neto sin costes",
            )
            return
        recorder.lower(CHECK_MIN_RETURN, value, max(floors), tolerance)

    def _turnover(
        self, recorder: _Recorder, weights: Mapping[str, float], context: ProposalContext
    ) -> float:
        union = set(weights) | set(context.current_weights)
        value = 0.5 * float(
            sum(abs(weights.get(a, 0.0) - context.current_weights.get(a, 0.0)) for a in union)
        )
        recorder.upper(CHECK_MAX_TURNOVER, value, context.max_turnover, context.turnover_tolerance)
        return value

    def _eligibility(
        self,
        recorder: _Recorder,
        weights: Mapping[str, float],
        context: ProposalContext,
        effective: EffectiveHardConstraints,
    ) -> None:
        eligibility = context.eligibility
        if eligibility is None:
            return
        held = sorted(positions_of(weights, effective.position_weight_threshold))
        limits = CompositionLimits(
            target_size=None,
            max_new_assets=effective.max_added_assets,
            max_swaps=effective.max_swaps,
            mandatory=frozenset(),
            max_removed_assets=effective.max_removed_assets,
            max_total_changed=effective.max_total_changed_assets,
            max_replacements=effective.max_replacements,
            max_pure_additions=effective.max_pure_additions,
            max_pure_removals=effective.max_pure_removals,
        )
        codes = validate_candidate_composition(
            held,
            universe=eligibility.universe,
            state=eligibility.state,
            spec=eligibility.spec,
            restricted_policy=eligibility.restricted_policy,
            unknown_liquidity_policy=eligibility.unknown_liquidity_policy,
            target_size=None,
            max_new_assets=None,
            max_swaps=None,
            is_reference=False,
            limits=limits,
        )
        recorder.record(
            CHECK_ELIGIBILITY,
            float(len(codes)),
            0.0,
            float(len(codes)),
            0.0,
            ",".join(codes),
        )

    def _solver_contract(
        self,
        recorder: _Recorder,
        compiled: CompiledConstraints,
        compiled_weights: npt.ArrayLike,
        context: ProposalContext,
        validator: SolutionValidator,
    ) -> None:
        index = {asset_id: i for i, asset_id in enumerate(context.risk_model.asset_ids)}
        positions = np.array([index[a] for a in compiled.asset_ids], dtype=np.int64)
        validation = ValidationContext(
            context.risk_model.mu[positions],
            context.risk_model.sigma[np.ix_(positions, positions)],
            None,
        )
        report = validator.validate(compiled_weights, compiled, validation)
        names = ",".join(v.constraint_id for v in report.violations)
        recorder.record(
            CHECK_SOLVER_CONTRACT,
            float(len(report.violations)),
            0.0,
            0.0 if report.is_valid else math.inf,
            0.0,
            names,
        )

    def _report(
        self,
        label: str,
        recorder: _Recorder,
        metrics: ProposalMetrics | None,
        effective: EffectiveHardConstraints,
    ) -> FinalProposalReport:
        codes = tuple(
            dict.fromkeys(
                f"{REJECTION_PREFIX}:{check.check}" for check in recorder.checks if not check.passed
            )
        )
        return FinalProposalReport(
            label=label,
            accepted=not codes,
            rejection_codes=codes,
            checks=tuple(recorder.checks),
            metrics=metrics,
            effective_hash=effective.effective_hash,
        )
