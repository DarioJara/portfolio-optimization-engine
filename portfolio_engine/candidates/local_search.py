"""``LocalSearch``: ascenso de mejor mejora sobre el vecindario de sustituciones (§26; CAN-006).

Desde una composición inicial evalúa su vecindario completo (mismo ``NeighborhoodExpander`` que la
búsqueda en haz) y se mueve al mejor vecino solo si mejora la utilidad estimada en más de
``improvement_tolerance``; la utilidad de la trayectoria es por tanto estrictamente creciente.
Se detiene en un óptimo local (``LOCAL_OPTIMUM``), en ``max_levels`` o al agotar el presupuesto.
No es una alternativa al haz: pule finalistas cuyo vecindario no llegó a expandirse.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.candidates.beam_search import STOP_BUDGET, STOP_LOCAL_OPTIMUM, STOP_MAX_LEVELS
from portfolio_engine.candidates.expansion import (
    EvaluationBudget,
    NeighborhoodExpander,
    SearchNode,
    SearchServices,
    StageAccumulator,
)
from portfolio_engine.models.composition import StageDiagnostics
from portfolio_engine.models.enums import CandidateOrigin


@dataclass(frozen=True, eq=False, slots=True)
class LocalSearchOutcome:
    """Trayectoria de la búsqueda local y todos los vecinos evaluados."""

    path: tuple[SearchNode, ...]
    evaluated: tuple[SearchNode, ...]
    stages: tuple[StageDiagnostics, ...]
    stop_reason: str


class LocalSearch:
    """Ascenso de mejor mejora desde una composición inicial."""

    def __init__(self, services: SearchServices, expander: NeighborhoodExpander) -> None:
        self._s = services
        self._expander = expander

    def run(
        self,
        start: SearchNode,
        risk_aversion: float,
        baseline: float,
        visited: set[str],
        budget: EvaluationBudget,
    ) -> LocalSearchOutcome:
        """Sube desde ``start`` mientras exista un vecino que mejore la utilidad estimada."""
        config = self._s.config
        current = start
        path = [start]
        evaluated: dict[str, SearchNode] = {}
        stages: list[StageDiagnostics] = []
        stop = STOP_MAX_LEVELS
        for level in range(1, config.max_levels + 1):
            if budget.exhausted:
                stop = STOP_BUDGET
                break
            accumulator = StageAccumulator()
            expansion = self._expander.expand(
                current,
                risk_aversion,
                level,
                visited,
                budget,
                baseline,
                CandidateOrigin.LOCAL_SEARCH,
            )
            accumulator.add(expansion)
            evaluated.update({child.composition_hash: child for child in expansion.children})
            better = [
                child
                for child in expansion.children
                if len(child.positions) == self._s.target_size
                and child.estimate.satisfies_constraints
                and child.gain > current.gain + config.improvement_tolerance
            ]
            best = min(better, key=SearchNode.ranking_key) if better else None
            stages.append(
                accumulator.build(
                    CandidateOrigin.LOCAL_SEARCH,
                    risk_aversion,
                    level,
                    0 if best is None else 1,
                    None if best is None else best.gain,
                )
            )
            if best is None:
                stop = STOP_LOCAL_OPTIMUM
                break
            current = best
            path.append(best)
        return LocalSearchOutcome(tuple(path), tuple(evaluated.values()), tuple(stages), stop)
