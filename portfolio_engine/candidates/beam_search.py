"""``BeamSearch``: búsqueda en haz de composiciones (MASTER_SPEC §26, §29; CAN-007).

Mantiene las mejores ``B`` composiciones **por nivel** (``BeamWidth``) en lugar de conservar solo el
máximo: cada superviviente se expande con screening y sustituciones (``NeighborhoodExpander``), los
vecinos duplicados se eliminan por ``CompositionHash`` y los supervivientes se eligen por la
utilidad estimada con una distancia mínima entre ellos (``diversity_min_distance``). Todo lo
evaluado queda en el ``pool``, de modo que la búsqueda devuelve varias composiciones finalistas y
no una sola.

Criterios de parada (con la causa registrada): ``MAX_LEVELS``, ``NO_NEIGHBORS`` (ningún vecino
nuevo y válido), ``STAGNATION`` (``stagnation_levels`` niveles sin mejorar la mejor composición de
tamaño objetivo en más de ``improvement_tolerance``) y ``BUDGET_EXHAUSTED`` (``max_evaluations``
de la fase de haz del perfil; el pulido con búsqueda local tiene su propio presupuesto, ver
``EvaluationBudget``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from portfolio_engine.candidates.expansion import (
    EvaluationBudget,
    NeighborhoodExpander,
    SearchNode,
    SearchServices,
    StageAccumulator,
)
from portfolio_engine.candidates.screening import ScreeningResult
from portfolio_engine.constraints.integer import swap_count
from portfolio_engine.models.composition import StageDiagnostics
from portfolio_engine.models.enums import CandidateOrigin, CandidateType

STOP_MAX_LEVELS = "MAX_LEVELS"
STOP_NO_NEIGHBORS = "NO_NEIGHBORS"
STOP_STAGNATION = "STAGNATION"
STOP_BUDGET = "BUDGET_EXHAUSTED"
STOP_LOCAL_OPTIMUM = "LOCAL_OPTIMUM"


@dataclass(frozen=True, eq=False, slots=True)
class SearchOutcome:
    """Resultado de una búsqueda para un perfil: nodos evaluados, etapas y causa de parada."""

    pool: tuple[SearchNode, ...]
    stages: tuple[StageDiagnostics, ...]
    stop_reason: str
    root_screening: ScreeningResult | None
    root_shortlist: dict[int, CandidateType]


def select_survivors(
    nodes: Sequence[SearchNode], width: int, min_distance: int
) -> list[SearchNode]:
    """Hasta ``width`` nodos por orden de búsqueda con distancia mínima entre ellos.

    La distancia entre dos composiciones es ``swap_count`` (activos sustituidos); con
    ``min_distance = 1`` solo se descartan duplicados.
    """
    kept: list[SearchNode] = []
    for node in sorted(nodes, key=SearchNode.ranking_key):
        if len(kept) == width:
            break
        ids = frozenset(node.prepared.asset_ids)
        if all(
            swap_count(frozenset(other.prepared.asset_ids), ids) >= min_distance for other in kept
        ):
            kept.append(node)
    return kept


class BeamSearch:
    """Búsqueda en haz sobre composiciones de un perfil de aversión al riesgo."""

    def __init__(self, services: SearchServices, expander: NeighborhoodExpander) -> None:
        self._s = services
        self._expander = expander

    def run(
        self,
        root: SearchNode,
        risk_aversion: float,
        baseline: float,
        visited: set[str],
        budget: EvaluationBudget,
    ) -> SearchOutcome:
        """Recorre hasta ``max_levels`` niveles desde ``root`` y devuelve todo lo evaluado."""
        config = self._s.config
        target = self._s.target_size
        pool: dict[str, SearchNode] = {root.composition_hash: root}
        stages: list[StageDiagnostics] = []
        beam = [root]
        best = root.gain if len(root.positions) == target else None
        stagnant = 0
        stop = STOP_MAX_LEVELS
        root_screening: ScreeningResult | None = None
        root_shortlist: dict[int, CandidateType] = {}
        for level in range(1, config.max_levels + 1):
            accumulator = StageAccumulator()
            children: list[SearchNode] = []
            for node in beam:
                if budget.exhausted:
                    break
                expansion = self._expander.expand(
                    node,
                    risk_aversion,
                    level,
                    visited,
                    budget,
                    baseline,
                    CandidateOrigin.BEAM_SEARCH,
                )
                accumulator.add(expansion)
                children.extend(expansion.children)
                if root_screening is None:
                    root_screening, root_shortlist = expansion.screening, expansion.shortlisted
            survivors = select_survivors(children, config.beam_width, config.diversity_min_distance)
            pool.update({child.composition_hash: child for child in children})
            finals = [node.gain for node in survivors if len(node.positions) == target]
            level_best = max(finals) if finals else None
            stages.append(
                accumulator.build(
                    CandidateOrigin.BEAM_SEARCH, risk_aversion, level, len(survivors), level_best
                )
            )
            if not children:
                stop = STOP_BUDGET if budget.exhausted else STOP_NO_NEIGHBORS
                break
            if level_best is not None and (
                best is None or level_best > best + config.improvement_tolerance
            ):
                best, stagnant = level_best, 0
            else:
                stagnant += 1
            beam = survivors
            if budget.exhausted:
                stop = STOP_BUDGET
                break
            if stagnant >= config.stagnation_levels:
                stop = STOP_STAGNATION
                break
        return SearchOutcome(
            tuple(pool.values()), tuple(stages), stop, root_screening, root_shortlist
        )
