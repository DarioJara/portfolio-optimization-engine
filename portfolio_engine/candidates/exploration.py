"""``ExplorationPolicy``: reparto explotación / diversificación / exploración (MASTER_SPEC §28).

Requisito: CAN-008.

Reparte los ``k`` puestos de la lista corta de activos entrantes entre tres componentes con los
pesos relativos de ``ExplorationMix`` (método del resto mayor; sin proporciones fijas en el
código):

* **alta convicción** (``HIGH_CONVICTION``): mejor ``CandidateScreeningScore``;
* **diversificación** (``DIVERSIFICATION``): mayor score de diversificación (menor correlación y
  covarianza con la cartera) entre los no elegidos;
* **exploración** (``EXPLORATION``): muestra aleatoria sin reemplazo del resto, con un generador
  cuya semilla deriva de forma determinista de la semilla del motor (``derive_seed``).

Si un componente no tiene candidatos suficientes, su cupo pasa a alta convicción.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.candidate_config import ExplorationMix
from portfolio_engine.models.enums import CandidateType


def component_counts(mix: ExplorationMix, k: int) -> tuple[int, int, int]:
    """Puestos de ``(alta convicción, diversificación, exploración)`` para ``k`` elementos.

    Método del resto mayor con desempate por el orden de los componentes.
    """
    shares = np.array([mix.exploit_share, mix.diversify_share, mix.explore_share], dtype=np.float64)
    quotas = shares / shares.sum() * k
    counts = np.floor(quotas).astype(np.int64)
    remainder = int(k - counts.sum())
    order = np.argsort(-(quotas - counts), kind="stable")
    counts[order[:remainder]] += 1
    return int(counts[0]), int(counts[1]), int(counts[2])


def _top(
    scores: npt.NDArray[np.float64], candidates: npt.NDArray[np.int64], count: int
) -> npt.NDArray[np.int64]:
    """Los ``count`` índices de ``candidates`` de mayor score (empates por índice)."""
    if count <= 0 or candidates.size == 0:
        return np.empty(0, dtype=np.int64)
    order = np.argsort(-scores[candidates], kind="stable")
    return np.asarray(candidates[order[:count]], dtype=np.int64)


class ExplorationPolicy:
    """Selecciona la lista corta de entrantes según el reparto configurado."""

    def __init__(self, mix: ExplorationMix) -> None:
        self._mix = mix

    def select(
        self,
        score: npt.NDArray[np.float64],
        diversification: npt.NDArray[np.float64],
        usable: npt.NDArray[np.bool_],
        k: int,
        rng: np.random.Generator,
    ) -> tuple[npt.NDArray[np.int64], tuple[CandidateType, ...]]:
        """Índices (ascendentes) y tipo de los ``k`` activos elegidos entre los ``usable``.

        ``score`` y ``diversification`` tienen un valor por activo entrante; ``NaN`` en el
        segundo componente descarta al activo de la diversificación pero no de las demás.
        """
        available = np.flatnonzero(usable).astype(np.int64)
        k = min(k, available.size)
        exploit, diversify, explore = component_counts(self._mix, k)
        chosen: dict[int, CandidateType] = {}
        for index in _top(score, available, exploit).tolist():
            chosen[index] = CandidateType.HIGH_CONVICTION
        rest = np.array([i for i in available.tolist() if i not in chosen], dtype=np.int64)
        divers = rest[np.isfinite(diversification[rest])] if rest.size else rest
        for index in _top(diversification, divers, diversify).tolist():
            chosen[index] = CandidateType.DIVERSIFICATION
        rest = np.array([i for i in available.tolist() if i not in chosen], dtype=np.int64)
        take = min(explore, rest.size)
        if take > 0:
            for index in rng.choice(rest, size=take, replace=False).tolist():
                chosen[int(index)] = CandidateType.EXPLORATION
        # Cupos no cubiertos por falta de candidatos: pasan a alta convicción.
        missing = k - len(chosen)
        if missing > 0:
            rest = np.array([i for i in available.tolist() if i not in chosen], dtype=np.int64)
            for index in _top(score, rest, missing).tolist():
                chosen[index] = CandidateType.HIGH_CONVICTION
        indices = np.array(sorted(chosen), dtype=np.int64)
        return indices, tuple(chosen[int(index)] for index in indices)
