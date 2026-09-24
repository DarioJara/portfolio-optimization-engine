"""Expansión de un nodo de la búsqueda: screening → listas cortas → vecinos → evaluación.

Es la primitiva que comparten ``BeamSearch`` y ``LocalSearch`` (una sola implementación del
vecindario, sin duplicación). Para un nodo (composición con sus pesos estimados) y un perfil de
aversión ``λ``:

1. el screening puntúa los activos entrantes y los de mantenimiento **respecto a los pesos del
   nodo** (no respecto a un ranking individual de alpha);
2. ``ExplorationPolicy`` construye la lista corta de entrantes y las salidas son las de peor
   mantenimiento (los activos ``FREEZE_WEIGHT`` no pueden salir);
3. ``SwapGenerator`` genera los vecinos; se descartan los duplicados por ``CompositionHash`` y los
   que violan ``MaximumNewAssets``/``MaximumSwaps``/activos obligatorios (con causa registrada);
4. cada vecino se prepara (restricciones del Bloque 2 y factibilidad previa) y se evalúa; una
   composición inviable se rechaza con su causa, nunca se relaja.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates.diagnostics import RejectionLog
from portfolio_engine.candidates.eligibility import EligibilityResult
from portfolio_engine.candidates.evaluation import CompositionEvaluator, EvaluationRejection
from portfolio_engine.candidates.exploration import ExplorationPolicy
from portfolio_engine.candidates.prepared import CompositionFactory, PreparedComposition
from portfolio_engine.candidates.screening import CandidateScreening, ScreeningResult
from portfolio_engine.candidates.swap_generator import Neighbor, Shortlist, SwapGenerator
from portfolio_engine.candidates.universe_data import UniverseSnapshot
from portfolio_engine.config.candidate_config import CandidateConfig
from portfolio_engine.constraints.integer import CompositionLimits, move_violations
from portfolio_engine.models.composition import CompositionEstimate, StageDiagnostics, SwapMove
from portfolio_engine.models.enums import CandidateOrigin, CandidateType
from portfolio_engine.parallel.determinism import derive_seed

STAGE_EVALUATION = "EVALUATION"
STAGE_GENERATION = "GENERATION"


@dataclass(frozen=True, eq=False, slots=True)
class SearchNode:
    """Composición evaluada de la búsqueda con el camino de movimientos que la generó."""

    positions: tuple[int, ...]
    prepared: PreparedComposition
    estimate: CompositionEstimate
    parent_hash: str | None
    moves: tuple[SwapMove, ...]
    prior: float
    entrant_types: tuple[CandidateType, ...]
    origin: CandidateOrigin

    @property
    def composition_hash(self) -> str:
        """``CompositionHash`` del nodo."""
        return self.prepared.composition_hash

    @property
    def gain(self) -> float:
        """Mejora de utilidad estimada respecto a la cartera actual."""
        return self.estimate.utility_gain

    def ranking_key(self) -> tuple[int, float, str]:
        """Orden de la búsqueda: estimaciones válidas primero, mayor mejora, luego hash."""
        return (0 if self.estimate.satisfies_constraints else 1, -self.gain, self.composition_hash)


class EvaluationBudget:
    """Contador de composiciones evaluadas: un presupuesto ``max_evaluations`` por **fase**.

    ``CandidateConfig.max_evaluations`` acota las evaluaciones de cada fase (búsqueda en haz o
    pulido con búsqueda local) de cada perfil de aversión al riesgo; el motor crea un contador
    para cada una (el haz no puede dejar sin presupuesto al pulido). El tope total es
    ``len(utility_risk_aversions) × 2 × max_evaluations`` más la evaluación de la raíz de cada
    perfil, que no consume presupuesto.
    """

    def __init__(self, limit: int) -> None:
        self._remaining = limit

    @property
    def exhausted(self) -> bool:
        """``True`` si no quedan evaluaciones."""
        return self._remaining <= 0

    def consume(self) -> None:
        """Descuenta una evaluación."""
        self._remaining -= 1


@dataclass(frozen=True, eq=False, slots=True)
class SearchServices:
    """Dependencias inmutables compartidas por el expansor y los algoritmos de búsqueda."""

    config: CandidateConfig
    snapshot: UniverseSnapshot
    eligibility: EligibilityResult
    screening: CandidateScreening
    exploration: ExplorationPolicy
    generator: SwapGenerator
    factory: CompositionFactory
    evaluator: CompositionEvaluator
    limits: CompositionLimits
    reference_ids: frozenset[str]
    target_size: int
    seed: int
    portfolio_id: str
    scenario_id: str
    rejections: RejectionLog


@dataclass(frozen=True, eq=False, slots=True)
class Expansion:
    """Resultado de expandir un nodo."""

    children: tuple[SearchNode, ...]
    generated: int
    duplicates: int
    rejected: tuple[tuple[str, int], ...]
    evaluated: int
    screening_time: float
    generation_time: float
    evaluation_time: float
    screening: ScreeningResult | None
    shortlisted: dict[int, CandidateType]


class NeighborhoodExpander:
    """Expande nodos con screening, listas cortas, ``SwapGenerator`` y evaluación."""

    def __init__(self, services: SearchServices) -> None:
        self._s = services

    def expand(
        self,
        node: SearchNode,
        risk_aversion: float,
        level: int,
        visited: set[str],
        budget: EvaluationBudget,
        baseline: float,
        algorithm: CandidateOrigin,
    ) -> Expansion:
        """Vecinos evaluados de ``node``; ``visited`` acumula los ``CompositionHash`` ya vistos."""
        services = self._s
        started = time.perf_counter()
        positions = np.array(node.positions, dtype=np.int64)
        entrants = np.setdiff1d(
            services.eligibility.enterable.global_indices, positions, assume_unique=True
        )
        screening = services.screening.screen(
            services.snapshot,
            positions,
            node.estimate.weights,
            entrants,
            risk_aversion,
            1.0 / services.target_size,
            services.eligibility.weight_cap[entrants],
        )
        outs, ins, types = self._shortlists(
            node, entrants, positions, screening, risk_aversion, level
        )
        screened = time.perf_counter()
        neighbors = services.generator.neighbors(
            frozenset(node.positions), services.target_size, outs, ins
        )
        generated = time.perf_counter()
        children: list[SearchNode] = []
        rejected: Counter[str] = Counter()
        duplicates = evaluated = 0
        for neighbor in neighbors:
            digest = services.factory.digest(neighbor.positions)
            if digest in visited:
                duplicates += 1
                continue
            ids = tuple(
                services.snapshot.index.asset_id_at(position)
                for position in sorted(neighbor.positions)
            )
            violations = move_violations(services.limits, services.reference_ids, ids)
            if violations:
                visited.add(digest)
                self._reject(
                    digest, ids, STAGE_GENERATION, violations, level, risk_aversion, rejected
                )
                continue
            if budget.exhausted:
                break
            visited.add(digest)
            budget.consume()
            evaluated += 1
            prepared = services.factory.prepare(neighbor.positions)
            outcome = services.evaluator.evaluate(prepared, risk_aversion, baseline)
            if isinstance(outcome, EvaluationRejection):
                self._reject(
                    digest, ids, STAGE_EVALUATION, outcome.reasons, level, risk_aversion, rejected
                )
                continue
            children.append(self._child(node, prepared, outcome, neighbor, types, level, algorithm))
        finished = time.perf_counter()
        return Expansion(
            children=tuple(children),
            generated=len(neighbors),
            duplicates=duplicates,
            rejected=tuple(sorted(rejected.items())),
            evaluated=evaluated,
            screening_time=screened - started,
            generation_time=generated - screened,
            evaluation_time=finished - generated,
            screening=screening,
            shortlisted=types,
        )

    # -------------------------------------------------------------------------------- internos

    def _shortlists(
        self,
        node: SearchNode,
        entrants: npt.NDArray[np.int64],
        positions: npt.NDArray[np.int64],
        screening: ScreeningResult,
        risk_aversion: float,
        level: int,
    ) -> tuple[Shortlist, Shortlist, dict[int, CandidateType]]:
        services = self._s
        config = services.config
        table = screening.entrants
        rng = np.random.default_rng(
            derive_seed(
                services.seed,
                services.portfolio_id,
                services.scenario_id,
                node.composition_hash,
                str(level),
                repr(risk_aversion),
            )
        )
        chosen, kinds = services.exploration.select(
            table.score, table.diversification, ~table.excluded, config.shortlist_in, rng
        )
        ins = Shortlist(entrants[chosen], table.score[chosen])
        types = {int(entrants[i]): kind for i, kind in zip(chosen.tolist(), kinds, strict=True)}
        held = screening.held
        mandatory = np.array(
            [int(p) in services.eligibility.mandatory_hold for p in positions.tolist()], dtype=bool
        )
        removable = np.flatnonzero(~held.excluded & ~mandatory)
        order = removable[np.argsort(held.score[removable], kind="stable")][: config.shortlist_out]
        outs = Shortlist(positions[order], held.score[order])
        return outs, ins, types

    def _reject(
        self,
        digest: str,
        ids: tuple[str, ...],
        stage: str,
        reasons: Sequence[str],
        level: int,
        risk_aversion: float,
        counter: Counter[str],
    ) -> None:
        for reason in reasons:
            counter[reason] += 1
        self._s.rejections.record(digest, ids, stage, reasons, level, risk_aversion)

    def _child(
        self,
        parent: SearchNode,
        prepared: PreparedComposition,
        estimate: CompositionEstimate,
        neighbor: Neighbor,
        types: dict[int, CandidateType],
        level: int,
        algorithm: CandidateOrigin,
    ) -> SearchNode:
        index = self._s.snapshot.index
        move = SwapMove(
            kind=neighbor.kind,
            out_asset_ids=tuple(index.asset_id_at(p) for p in neighbor.out_positions),
            in_asset_ids=tuple(index.asset_id_at(p) for p in neighbor.in_positions),
            level=level,
            risk_aversion=estimate.risk_aversion,
            screening_prior=neighbor.prior,
        )
        return SearchNode(
            positions=tuple(sorted(neighbor.positions)),
            prepared=prepared,
            estimate=estimate,
            parent_hash=parent.composition_hash,
            moves=(*parent.moves, move),
            prior=parent.prior + neighbor.prior,
            entrant_types=(*parent.entrant_types, *(types[p] for p in neighbor.in_positions)),
            origin=algorithm,
        )


class StageAccumulator:
    """Agrega las expansiones de un nivel en un :class:`StageDiagnostics`."""

    def __init__(self) -> None:
        self._nodes = 0
        self._generated = 0
        self._duplicates = 0
        self._evaluated = 0
        self._rejected: Counter[str] = Counter()
        self._times = [0.0, 0.0, 0.0]

    def add(self, expansion: Expansion) -> None:
        """Suma los contadores y tiempos de ``expansion``."""
        self._nodes += 1
        self._generated += expansion.generated
        self._duplicates += expansion.duplicates
        self._evaluated += expansion.evaluated
        self._rejected.update(dict(expansion.rejected))
        self._times[0] += expansion.screening_time
        self._times[1] += expansion.generation_time
        self._times[2] += expansion.evaluation_time

    def build(
        self,
        algorithm: CandidateOrigin,
        risk_aversion: float,
        level: int,
        survivors: int,
        best_gain: float | None,
    ) -> StageDiagnostics:
        """Diagnóstico del nivel con los supervivientes y la mejor mejora estimada."""
        return StageDiagnostics(
            algorithm=algorithm,
            risk_aversion=risk_aversion,
            level=level,
            nodes_expanded=self._nodes,
            neighbors_generated=self._generated,
            duplicates_skipped=self._duplicates,
            rejected_by_reason=tuple(sorted(self._rejected.items())),
            evaluated=self._evaluated,
            survivors=survivors,
            best_utility_gain=best_gain,
            screening_time=self._times[0],
            generation_time=self._times[1],
            evaluation_time=self._times[2],
        )
