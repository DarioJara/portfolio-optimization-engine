"""``CandidateEngine``: genera múltiples composiciones desde la cartera actual (MASTER_SPEC §26-31).

Requisitos: CAN-001, CAN-002, CAN-016, CAN-018..022, OPT-002 (selección discreta previa).

Contrato: ``generate_candidate_compositions(current, context) -> list[CandidateComposition]``. Nunca
devuelve una única composición como implementación final: parte de la **composición actual** (que se
conserva como referencia, CAN-022) y, para cada perfil de aversión al riesgo ``λ`` de la
configuración, ejecuta una búsqueda en haz (``BeamSearch``) con sustituciones 1/2/3-swap sobre
listas cortas del screening multiseñal, pule finalistas con ``LocalSearch`` y reparte el cupo
``max_candidates`` entre los perfiles. Una configuración legítima que solo permite la composición
actual (o ninguna) devuelve ese resultado con sus diagnósticos: no se inventan composiciones.

Distinciones que este módulo mantiene explícitas:

* ``CandidateScreeningScore`` (heurístico, para preseleccionar) frente al objetivo optimizado del
  Bloque 2: los valores ``estimated_*`` son estimaciones de la búsqueda, no resultados de
  optimización.
* Cardinalidad: el tamaño objetivo se garantiza en la **generación discreta** (movimientos
  ``SWAP``/``ADD``/``DROP``); no equivale a una formulación MIQP exacta con variables binarias
  (Bloque 4) ni se simula eliminando pesos tras el solver.
* Cada composición devuelta pasa una validación independiente (``validate_candidate_composition``).

Sin cartera actual y con ``cold_start`` activo, la semilla se elige por utilidad individual
``μ_a − λ·σ_aa`` y turnover/costes quedan como no disponibles (§24, decisión A-19).
"""

from __future__ import annotations

import dataclasses
import time
from collections import Counter
from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates.beam_search import BeamSearch, select_survivors
from portfolio_engine.candidates.composition_hash import composition_hash_of
from portfolio_engine.candidates.diagnostics import RejectionLog, build_asset_records
from portfolio_engine.candidates.eligibility import EligibilityFilter
from portfolio_engine.candidates.evaluation import (
    CompositionEvaluator,
    EvaluationRejection,
    MemoizedEvaluator,
    ProjectedWeightsEvaluator,
    current_portfolio_utility,
)
from portfolio_engine.candidates.expansion import (
    EvaluationBudget,
    NeighborhoodExpander,
    SearchNode,
    SearchServices,
)
from portfolio_engine.candidates.exploration import ExplorationPolicy
from portfolio_engine.candidates.local_search import LocalSearch
from portfolio_engine.candidates.prepared import CompositionFactory, PreparedComposition
from portfolio_engine.candidates.screening import CandidateScreening, ScreeningResult
from portfolio_engine.candidates.swap_generator import SwapGenerator
from portfolio_engine.candidates.universe_data import UniverseSnapshot
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.constraints.constraint_set import build_constraint_set
from portfolio_engine.constraints.feasibility import PreFeasibilityChecker, check_cardinality
from portfolio_engine.constraints.integer import CompositionLimits
from portfolio_engine.constraints.liquidity import effective_upper, liquidity_capacity
from portfolio_engine.exceptions import CandidateError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.composition import (
    CandidateComposition,
    CandidateDiagnostics,
    CandidateSearchResult,
    CompositionEstimate,
    StageDiagnostics,
)
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import (
    CandidateOrigin,
    CandidateType,
    EligibilityStatus,
    EvaluationMode,
)
from portfolio_engine.models.portfolio import (
    CurrentPortfolioComposition,
    CurrentPortfolioState,
    PortfolioSpec,
    resolve_effective_weight_bounds,
)
from portfolio_engine.models.risk_model import RiskModel
from portfolio_engine.validation.composition_validator import validate_candidate_composition
from portfolio_engine.validation.solution_validator import SolutionValidator
from portfolio_engine.validation.tolerances import ValidationTolerances

NOTE_ONLY_REFERENCE = "ONLY_REFERENCE_COMPOSITION_POSSIBLE"
NOTE_COLD_START_DISABLED = "COLD_START_DISABLED_NO_CURRENT_PORTFOLIO"
NOTE_INSUFFICIENT_ASSETS = "INSUFFICIENT_ELIGIBLE_ASSETS_FOR_TARGET_SIZE"
NOTE_ESTIMATES_NOT_OPTIMIZED = "ESTIMATES_ARE_NOT_OPTIMIZED_RESULTS"
NOTE_NON_BUYABLE_CAPPED = "E10_NON_BUYABLE_POSITIONS_CAPPED_AT_CURRENT_WEIGHT"
NOTE_LIQUIDITY_ACTIVE = "A11_ADV_NAV_LIQUIDITY_CAPS_ACTIVE"
STAGE_VALIDATION = "INDEPENDENT_VALIDATION"
REASON_NO_CURRENT = "NO_CURRENT_PORTFOLIO"
REASON_NO_COSTS = "NO_TRANSACTION_COST_DATA"
REASON_REFERENCE_NOT_ESTIMABLE = "REFERENCE_NOT_ESTIMABLE"

#: Prioridad de los tipos de entrante para desempatar el tipo dominante de una composición.
_TYPE_PRIORITY = (
    CandidateType.HIGH_CONVICTION,
    CandidateType.DIVERSIFICATION,
    CandidateType.EXPLORATION,
)


@dataclass(frozen=True, eq=False, slots=True)
class CandidateContext:
    """Datos de una cartera y un escenario para generar composiciones.

    ``snapshot`` es opcional: si falta se construye a partir de ``risk_model``, ``universe`` y
    ``costs``; puede reutilizarse entre carteras que comparten universo y modelo de riesgo.
    """

    portfolio_id: str
    scenario_id: str
    risk_model: RiskModel
    universe: Universe
    state: CurrentPortfolioState
    spec: PortfolioSpec | None
    costs: AssetCostVector | None
    snapshot: UniverseSnapshot | None = None


@dataclass(frozen=True, eq=False, slots=True)
class _ProfileResult:
    """Resultado de la búsqueda de un perfil de aversión al riesgo."""

    risk_aversion: float
    finalists: tuple[SearchNode, ...]
    stages: tuple[StageDiagnostics, ...]
    stop_reason: str
    root_screening: ScreeningResult | None
    root_shortlist: dict[int, CandidateType]


class CandidateEngine:
    """Genera composiciones candidatas alternativas a la cartera actual."""

    def __init__(self, config: EngineConfig, evaluator: CompositionEvaluator | None = None) -> None:
        self._config = config
        self._evaluator = evaluator

    def generate_candidate_compositions(
        self, current: CurrentPortfolioComposition, context: CandidateContext
    ) -> list[CandidateComposition]:
        """Composiciones candidatas (la actual como referencia, más las alternativas)."""
        return list(self.search(current, context).compositions)

    def search(
        self, current: CurrentPortfolioComposition, context: CandidateContext
    ) -> CandidateSearchResult:
        """Composiciones candidatas junto con los diagnósticos completos de la generación."""
        return _Search(self._config, self._evaluator, current, context).run()


class _Search:
    """Estado y pasos de una generación de composiciones para una cartera."""

    def __init__(
        self,
        config: EngineConfig,
        evaluator: CompositionEvaluator | None,
        current: CurrentPortfolioComposition,
        context: CandidateContext,
    ) -> None:
        state = context.state
        if current.portfolio_id != context.portfolio_id or current.asset_ids != frozenset(
            state.asset_ids
        ):
            raise CandidateError(
                "La composición actual no coincide con la cartera del contexto "
                f"({current.portfolio_id!r} vs {context.portfolio_id!r})."
            )
        self._config = config
        self._cfg = config.candidates
        self._context = context
        self._started = time.perf_counter()
        self._cold = not state.has_current_portfolio
        self._snapshot = context.snapshot or UniverseSnapshot.build(
            context.risk_model, context.universe, context.costs
        )
        self._eligibility = EligibilityFilter(self._cfg, config.constraints).apply(
            self._snapshot, state, context.spec
        )
        self._constraint_set = build_constraint_set(
            config.constraints,
            context.spec,
            context.portfolio_id,
            config.frontier.min_holding_weight,
            self._cfg.unknown_liquidity_policy,
        )
        self._validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
        self._evaluator = MemoizedEvaluator(evaluator or self._default_evaluator())
        self._reference = tuple(
            int(position) for position in self._snapshot.index.indices_of(state.asset_ids).tolist()
        )
        self._reference_ids = frozenset(state.asset_ids)
        self._rejections = RejectionLog(self._cfg.max_recorded_rejections)
        self._notes: list[str] = []
        capped = [
            self._snapshot.index.asset_id_at(int(position))
            for position in self._eligibility.positions_with(EligibilityStatus.LIQUIDATE_ONLY)
        ]
        if capped:
            self._notes.append(f"{NOTE_NON_BUYABLE_CAPPED}: {sorted(capped)}")
        self._liquidity_entry_cap = self._apply_liquidity()
        self._baselines: dict[float, float] = {}

    def _apply_liquidity(self) -> npt.NDArray[np.float64] | None:
        """Topes ADV/NAV (A-11) de los activos elegibles y actuales, con los datos validados.

        Un dato requerido ausente o inválido lanza el error de datos ya aquí (no se descartan
        composiciones en silencio). El tope ``max(w_current, capacidad)`` (``capacidad`` si el
        activo no está en cartera) limita también el peso de entrada que supone el screening.
        """
        liquidity = self._config.constraints.liquidity
        if not liquidity.enabled:
            return None
        context, state, index = self._context, self._context.state, self._snapshot.index
        spec = context.spec
        nav = None if spec is None else spec.nav
        nav_currency = None if spec is None else spec.nav_currency
        entry = np.full(self._snapshot.size, np.inf, dtype=np.float64)
        positions = {*self._eligibility.enterable.global_indices.tolist(), *self._reference}
        protected: list[str] = []
        for position in sorted(positions):
            asset_id = index.asset_id_at(position)
            capacity = liquidity_capacity(
                context.universe.get(asset_id), liquidity, nav, nav_currency
            )
            current = state.weight_of(asset_id)
            entry[position] = effective_upper(current, capacity.capacity)
            if current > capacity.capacity:
                protected.append(asset_id)
        self._eligibility = dataclasses.replace(
            self._eligibility, weight_cap=np.minimum(self._eligibility.weight_cap, entry)
        )
        self._notes.append(
            f"{NOTE_LIQUIDITY_ACTIVE}: max_adv_participation={liquidity.max_adv_participation}, "
            f"liquidation_days={liquidity.liquidation_days}, "
            f"positions_above_capacity_protected={sorted(protected)}"
        )
        return entry

    def _default_evaluator(self) -> CompositionEvaluator:
        if self._cfg.evaluation_mode is EvaluationMode.QP_UTILITY:
            raise CandidateError(
                "evaluation_mode = QP_UTILITY exige inyectar un evaluador exacto "
                "(frontiers.QPCompositionEvaluator)."
            )
        return ProjectedWeightsEvaluator(self._cfg.refinement_iterations, self._validator)

    # ------------------------------------------------------------------------------ pipeline

    def run(self) -> CandidateSearchResult:
        """Ejecuta la generación completa."""
        target = self._target_size()
        if target is None:
            self._notes.append(NOTE_COLD_START_DISABLED)
            return self._finish([], [], None)
        causes = self._cardinality_causes(target)
        if causes:
            self._notes.extend(causes)
            return self._only_reference(target)
        services = self._services(target)
        results = [
            result
            for result in (self._run_profile(services, lam) for lam in self._profiles)
            if result is not None
        ]
        candidates = self._assemble(services, results)
        return self._finish(candidates, results, results[len(results) // 2] if results else None)

    @property
    def _profiles(self) -> tuple[float, ...]:
        return self._cfg.utility_risk_aversions

    def _target_size(self) -> int | None:
        spec = self._context.spec
        if spec is not None and spec.target_portfolio_size is not None:
            return spec.target_portfolio_size
        if not self._cold:
            return len(self._reference)
        if not self._cfg.cold_start:
            return None
        raise CandidateError(
            "Sin cartera actual la generación en frío exige TargetPortfolioSize (CAN-020)."
        )

    def _cardinality_causes(self, target: int) -> tuple[str, ...]:
        """FEA-002 sobre los activos que pueden formar parte de una composición."""
        constraint_set = self._constraint_set
        lows: list[float] = []
        highs: list[float] = []
        for position in self._eligibility.enterable.global_indices.tolist():
            asset = self._context.universe.get(self._snapshot.index.asset_id_at(position))
            bounds = resolve_effective_weight_bounds(
                asset, self._context.spec, constraint_set.global_bounds
            )
            low = -np.inf if bounds.min_weight is None else bounds.min_weight
            lows.append(max(low, 0.0) if constraint_set.long_only else low)
            high = np.inf if bounds.max_weight is None else bounds.max_weight
            if self._liquidity_entry_cap is not None:
                high = min(high, float(self._liquidity_entry_cap[position]))
            highs.append(high)
        causes = check_cardinality(
            target,
            np.array(lows, dtype=np.float64),
            np.array(highs, dtype=np.float64),
            1.0,
            self._config.solver.constraint_tolerance,
        )
        return tuple(f"{cause.code}: {cause.detail}" for cause in causes)

    def _services(self, target: int) -> SearchServices:
        cfg = self._cfg
        index = self._snapshot.index
        limits = CompositionLimits(
            target_size=target,
            max_new_assets=None if self._cold else cfg.max_new_assets,
            max_swaps=None if self._cold else cfg.max_swaps,
            mandatory=frozenset(index.asset_id_at(p) for p in self._eligibility.mandatory_hold),
        )
        factory = CompositionFactory(
            snapshot=self._snapshot,
            eligible=self._eligibility.enterable,
            universe=self._context.universe,
            state=self._context.state,
            costs=self._context.costs,
            constraint_set=self._constraint_set,
            checker=PreFeasibilityChecker(self._config.solver.constraint_tolerance),
            horizon_years=self._config.optimization_horizon_years,
        )
        return SearchServices(
            config=cfg,
            snapshot=self._snapshot,
            eligibility=self._eligibility,
            screening=CandidateScreening(cfg, self._config.returns.risk_free_rate),
            exploration=ExplorationPolicy(cfg.exploration),
            generator=SwapGenerator(cfg),
            factory=factory,
            evaluator=self._evaluator,
            limits=limits,
            reference_ids=self._reference_ids,
            target_size=target,
            seed=self._config.random_seed,
            portfolio_id=self._context.portfolio_id,
            scenario_id=self._context.scenario_id,
            rejections=self._rejections,
        )

    # ------------------------------------------------------------------------------ perfiles

    def _baseline(self, lam: float) -> float:
        """Utilidad ``μᵀw − λ wᵀΣw`` de la cartera actual con sus pesos (sin costes)."""
        held = np.array(self._reference, dtype=np.int64)
        return current_portfolio_utility(
            self._snapshot.mu[held],
            self._snapshot.sigma[np.ix_(held, held)],
            self._context.state.weights,
            lam,
        )

    def _kept_reference(self) -> tuple[int, ...]:
        """La cartera actual sin los activos que deben liquidarse (``FORCE_LIQUIDATE``)."""
        exits = self._eligibility.mandatory_exit
        return tuple(position for position in self._reference if position not in exits)

    def _root_positions(
        self, services: SearchServices, lam: float
    ) -> tuple[tuple[int, ...], CandidateOrigin] | None:
        """Composición de arranque: la actual ajustada, o la semilla si no hay nada que ajustar."""
        kept = self._kept_reference()
        if kept:
            origin = (
                CandidateOrigin.REFERENCE
                if kept == self._reference
                else CandidateOrigin.REFERENCE_ADJUSTED
            )
            return kept, origin
        entrants = self._eligibility.enterable.global_indices
        target = services.target_size
        if entrants.size < target:
            self._notes.append(NOTE_INSUFFICIENT_ASSETS)
            return None
        standalone = self._snapshot.mu[entrants] - lam * self._snapshot.sigma[entrants, entrants]
        order = np.argsort(-standalone, kind="stable")[:target]
        seed = tuple(sorted(int(position) for position in entrants[order].tolist()))
        return seed, CandidateOrigin.COLD_START_SEED

    def _root(self, services: SearchServices, lam: float) -> SearchNode | None:
        start = self._root_positions(services, lam)
        if start is None:
            return None
        positions, origin = start
        baseline = 0.0 if self._cold else self._baseline(lam)
        prepared = services.factory.prepare(positions)
        outcome = services.evaluator.evaluate(prepared, lam, baseline)
        estimate = (
            self._fallback_estimate(prepared, lam, baseline, outcome)
            if isinstance(outcome, EvaluationRejection)
            else outcome
        )
        if self._cold:
            baseline = estimate.utility
            estimate = replace(estimate, utility_gain=0.0)
        self._baselines[lam] = baseline
        return SearchNode(positions, prepared, estimate, None, (), 0.0, (), origin)

    def _fallback_estimate(
        self,
        prepared: PreparedComposition,
        lam: float,
        baseline: float,
        rejection: EvaluationRejection,
    ) -> CompositionEstimate:
        """Estimación de arranque con los pesos actuales cuando el nodo raíz no es evaluable."""
        weights = np.array(prepared.alignment.current_on_composition(), dtype=np.float64)
        total = float(weights.sum())
        weights = weights / total if total > 0 else np.full(weights.shape, 1.0 / weights.size)
        gross = float(prepared.mu @ weights)
        variance = float(weights @ (prepared.sigma @ weights))
        utility = gross - lam * variance
        return CompositionEstimate(
            composition_hash=prepared.composition_hash,
            risk_aversion=lam,
            basis=self._evaluator.mode,
            weights=weights,
            utility=utility,
            utility_gain=utility - baseline,
            expected_return_gross=gross,
            variance=variance,
            turnover=None,
            transaction_cost_one_off=None,
            transaction_cost=None,
            satisfies_constraints=False,
            violations=rejection.reasons,
        )

    def _run_profile(self, services: SearchServices, lam: float) -> _ProfileResult | None:
        root = self._root(services, lam)
        if root is None:
            return None
        cfg = self._cfg
        baseline = self._baselines[lam]
        expander = NeighborhoodExpander(services)
        reference_hash = None if self._cold else composition_hash_of(self._reference_ids)
        visited = {root.composition_hash}
        if reference_hash is not None:
            visited.add(reference_hash)
        budget = EvaluationBudget(cfg.max_evaluations)
        outcome = BeamSearch(services, expander).run(root, lam, baseline, visited, budget)
        pool = {node.composition_hash: node for node in outcome.pool}
        stages = list(outcome.stages)
        starts = select_survivors(
            self._finals(pool, services.target_size, reference_hash),
            cfg.local_search_starts,
            cfg.diversity_min_distance,
        )
        local = LocalSearch(services, expander)
        polishing_budget = EvaluationBudget(cfg.max_evaluations)
        for start in starts:
            polished = local.run(start, lam, baseline, visited, polishing_budget)
            pool.update({node.composition_hash: node for node in polished.evaluated})
            stages.extend(polished.stages)
        finalists = select_survivors(
            self._finals(pool, services.target_size, reference_hash),
            cfg.beam_width,
            cfg.diversity_min_distance,
        )
        return _ProfileResult(
            lam,
            tuple(finalists),
            tuple(stages),
            outcome.stop_reason,
            outcome.root_screening,
            outcome.root_shortlist,
        )

    def _finals(
        self, pool: dict[str, SearchNode], target: int, reference_hash: str | None
    ) -> list[SearchNode]:
        """Nodos de tamaño objetivo distintos de la composición de referencia."""
        return [
            node
            for node in pool.values()
            if len(node.positions) == target and node.composition_hash != reference_hash
        ]

    # ------------------------------------------------------------------------------- salida

    def _assemble(
        self, services: SearchServices, results: list[_ProfileResult]
    ) -> list[CandidateComposition]:
        candidates: list[CandidateComposition] = []
        if not self._cold:
            candidates.append(self._reference_candidate(services))
        slots = self._cfg.max_candidates - len(candidates)
        for node, lam in self._round_robin(results, slots):
            candidates.append(self._candidate(services, node, lam))
        return self._validated(candidates)

    def _round_robin(
        self, results: list[_ProfileResult], slots: int
    ) -> list[tuple[SearchNode, float]]:
        """Reparte el cupo entre los perfiles por rango (el mejor de cada perfil primero)."""
        chosen: list[tuple[SearchNode, float]] = []
        seen: set[str] = set()
        depth = max((len(result.finalists) for result in results), default=0)
        for rank in range(depth):
            for result in results:
                if rank >= len(result.finalists) or len(chosen) >= slots:
                    continue
                node = result.finalists[rank]
                if node.composition_hash not in seen:
                    seen.add(node.composition_hash)
                    chosen.append((node, result.risk_aversion))
        return chosen

    def _estimates(
        self, services: SearchServices, node: SearchNode, source: float
    ) -> tuple[CompositionEstimate, ...]:
        """Estimaciones de una composición en todos los perfiles (la de origen ya existe)."""
        estimates: list[CompositionEstimate] = []
        for lam in self._profiles:
            if lam == source:
                estimates.append(node.estimate)
                continue
            outcome = services.evaluator.evaluate(node.prepared, lam, self._baselines[lam])
            if isinstance(outcome, CompositionEstimate):
                estimates.append(outcome)
        return tuple(estimates)

    def _unavailable_reason(self) -> str | None:
        if self._cold:
            return REASON_NO_CURRENT
        return REASON_NO_COSTS if self._context.costs is None else None

    def _dominant_type(self, node: SearchNode) -> CandidateType:
        if not node.entrant_types:
            return CandidateType.CURRENT_HOLDING
        counts = Counter(node.entrant_types)
        return max(_TYPE_PRIORITY, key=lambda kind: (counts[kind], -_TYPE_PRIORITY.index(kind)))

    def _candidate(
        self, services: SearchServices, node: SearchNode, source: float
    ) -> CandidateComposition:
        estimate = node.estimate
        return CandidateComposition(
            composition_id=node.composition_hash,
            global_indices=np.array(node.positions, dtype=np.int64),
            asset_ids=node.prepared.asset_ids,
            parent_composition_id=node.parent_hash,
            swap_history=node.moves,
            candidate_score=node.prior,
            estimated_utility_gain=estimate.utility_gain,
            estimated_turnover=estimate.turnover,
            estimated_transaction_cost=estimate.transaction_cost,
            candidate_type=self._dominant_type(node),
            origin=node.origin,
            estimates=self._estimates(services, node, source),
            best_risk_aversion=source,
            estimate_unavailable_reason=self._unavailable_reason(),
        )

    def _reference_candidate(self, services: SearchServices) -> CandidateComposition:
        """La cartera actual como composición de referencia (CAN-022)."""
        prepared = services.factory.prepare(self._reference)
        source = self._profiles[len(self._profiles) // 2]
        estimates: list[CompositionEstimate] = []
        reasons: tuple[str, ...] = ()
        for lam in self._profiles:
            baseline = self._baselines.get(lam)
            outcome = services.evaluator.evaluate(
                prepared, lam, self._baseline(lam) if baseline is None else baseline
            )
            if isinstance(outcome, CompositionEstimate):
                estimates.append(outcome)
            else:
                reasons = outcome.reasons
        at_source = next((e for e in estimates if e.risk_aversion == source), None)
        gain, turnover, cost, best = 0.0, None, None, None
        unavailable = self._unavailable_reason()
        if at_source is None:
            unavailable = f"{REASON_REFERENCE_NOT_ESTIMABLE}: {', '.join(reasons)}"
        else:
            gain, turnover, cost, best = (
                at_source.utility_gain,
                at_source.turnover,
                at_source.transaction_cost,
                source,
            )
        return CandidateComposition(
            composition_id=prepared.composition_hash,
            global_indices=np.array(self._reference, dtype=np.int64),
            asset_ids=prepared.asset_ids,
            parent_composition_id=None,
            swap_history=(),
            candidate_score=0.0,
            estimated_utility_gain=gain,
            estimated_turnover=turnover,
            estimated_transaction_cost=cost,
            candidate_type=CandidateType.CURRENT_HOLDING,
            origin=CandidateOrigin.REFERENCE,
            estimates=tuple(estimates),
            best_risk_aversion=best,
            estimate_unavailable_reason=unavailable,
        )

    def _validated(self, candidates: list[CandidateComposition]) -> list[CandidateComposition]:
        """Descarta (y registra) toda composición que no supere la validación independiente."""
        context, cfg = self._context, self._cfg
        spec = context.spec
        target = None if self._cold else len(self._reference)
        if spec is not None and spec.target_portfolio_size is not None:
            target = spec.target_portfolio_size
        accepted: list[CandidateComposition] = []
        for candidate in candidates:
            codes = validate_candidate_composition(
                candidate.asset_ids,
                universe=context.universe,
                state=context.state,
                spec=spec,
                restricted_policy=self._eligibility.restricted_policy,
                unknown_liquidity_policy=cfg.unknown_liquidity_policy,
                target_size=target,
                max_new_assets=None if self._cold else cfg.max_new_assets,
                max_swaps=None if self._cold else cfg.max_swaps,
                is_reference=candidate.is_reference,
            )
            if codes:
                self._rejections.record(
                    candidate.composition_hash,
                    candidate.asset_ids,
                    STAGE_VALIDATION,
                    codes,
                    0,
                    None,
                )
            else:
                accepted.append(candidate)
        return accepted

    def _only_reference(self, target: int) -> CandidateSearchResult:
        """Sin espacio de composiciones: solo la referencia (si existe), sin inventar más."""
        candidates: list[CandidateComposition] = []
        if not self._cold:
            self._notes.append(NOTE_ONLY_REFERENCE)
            services = self._services(target)
            candidates = self._validated([self._reference_candidate(services)])
        return self._finish(candidates, [], None)

    # ------------------------------------------------------------------------- diagnósticos

    def _finish(
        self,
        candidates: list[CandidateComposition],
        results: list[_ProfileResult],
        profile: _ProfileResult | None,
    ) -> CandidateSearchResult:
        stages = [stage for result in results for stage in result.stages]
        selected = {int(p) for candidate in candidates for p in candidate.global_indices.tolist()}
        records = build_asset_records(
            None if profile is None else profile.root_screening,
            self._eligibility,
            self._snapshot.index.asset_ids,
            {} if profile is None else profile.root_shortlist,
            selected,
        )
        diagnostics = CandidateDiagnostics(
            portfolio_id=self._context.portfolio_id,
            scenario_id=self._context.scenario_id,
            cold_start=self._cold,
            eligibility_counts=self._eligibility.counts(),
            asset_records=records,
            stages=tuple(stages),
            rejected_compositions=self._rejections.records,
            rejections_by_reason=self._rejections.by_reason(),
            stop_reasons=tuple((result.risk_aversion, result.stop_reason) for result in results),
            total_generated=sum(stage.neighbors_generated for stage in stages),
            total_evaluated=sum(stage.evaluated for stage in stages),
            screening_time=sum(stage.screening_time for stage in stages),
            search_time=sum(
                stage.screening_time + stage.generation_time + stage.evaluation_time
                for stage in stages
            ),
            total_time=time.perf_counter() - self._started,
            notes=(*self._notes, NOTE_ESTIMATES_NOT_OPTIMIZED),
            evaluation_cache_hits=self._evaluator.hits,
        )
        return CandidateSearchResult(tuple(candidates), diagnostics)
