"""``SwapGenerator``: vecindario de sustituciones 1-swap, 2-swap y 3-swap (MASTER_SPEC §26).

Requisitos: CAN-003, CAN-004, CAN-005, CAN-019 (movimientos ``ADD``/``DROP`` para corregir el
tamaño hacia ``TargetPortfolioSize``, decisión A-19).

Cada movimiento es un conjunto de posiciones globales: un cambio de orden no crea una composición
nueva y no hay duplicados dentro de un mismo nodo. El vecindario de orden ``r`` se construye sobre
las listas cortas (top-K de salidas y de entradas por screening, decisión A-18) con arrays de
combinaciones; su *prior* es la suma de scores de entrada menos la de mantenimiento de las salidas.
Si el vecindario supera ``max_neighbors_per_order`` se conservan los de mayor prior (desempate
estable por orden lexicográfico); si cabe, es exhaustivo sobre las listas cortas.

Los límites de la búsqueda (``MaximumNewAssets``, ``MaximumSwaps``, activos obligatorios) los
aplica el expansor a cada vecino; este módulo solo genera el vecindario.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.candidate_config import CandidateConfig
from portfolio_engine.models.enums import MoveKind


@dataclass(frozen=True, eq=False, slots=True)
class Shortlist:
    """Lista corta de activos (posiciones globales) con su score de screening."""

    positions: npt.NDArray[np.int64]
    scores: npt.NDArray[np.float64]

    @property
    def size(self) -> int:
        """Número de activos de la lista."""
        return int(self.positions.size)


@dataclass(frozen=True, slots=True)
class Neighbor:
    """Composición vecina y el movimiento que la produce."""

    positions: frozenset[int]
    kind: MoveKind
    out_positions: tuple[int, ...]
    in_positions: tuple[int, ...]
    prior: float


def _top_indices(prior: npt.NDArray[np.float64], limit: int) -> npt.NDArray[np.int64]:
    """Índices de los ``limit`` mayores priors, de mayor a menor (empates por posición)."""
    return np.asarray(np.argsort(-prior, kind="stable")[:limit], dtype=np.int64)


class SwapGenerator:
    """Genera los vecinos de una composición según los órdenes de sustitución configurados."""

    def __init__(self, config: CandidateConfig) -> None:
        self._orders = config.swap_orders
        self._limit = config.max_neighbors_per_order

    def neighbors(
        self,
        node: frozenset[int],
        target_size: int,
        outs: Shortlist,
        ins: Shortlist,
    ) -> tuple[Neighbor, ...]:
        """Vecinos de ``node``: sustituciones si su tamaño es el objetivo; ``ADD``/``DROP`` si no.

        ``outs`` son los activos de ``node`` que pueden salir (peor mantenimiento primero) e
        ``ins`` los que pueden entrar (los de ``node`` ya están excluidos por el llamador).
        """
        if len(node) < target_size:
            return self._adds(node, ins)
        if len(node) > target_size:
            return self._drops(node, outs)
        found: list[Neighbor] = []
        for order in self._orders:
            if order <= outs.size and order <= ins.size:
                found.extend(self._swaps(node, order, outs, ins))
        return tuple(found)

    def _adds(self, node: frozenset[int], ins: Shortlist) -> tuple[Neighbor, ...]:
        chosen = _top_indices(ins.scores, self._limit)
        return tuple(
            Neighbor(
                node | {int(ins.positions[i])},
                MoveKind.ADD,
                (),
                (int(ins.positions[i]),),
                float(ins.scores[i]),
            )
            for i in chosen.tolist()
        )

    def _drops(self, node: frozenset[int], outs: Shortlist) -> tuple[Neighbor, ...]:
        chosen = _top_indices(-outs.scores, self._limit)
        return tuple(
            Neighbor(
                node - {int(outs.positions[i])},
                MoveKind.DROP,
                (int(outs.positions[i]),),
                (),
                -float(outs.scores[i]),
            )
            for i in chosen.tolist()
        )

    def _swaps(
        self, node: frozenset[int], order: int, outs: Shortlist, ins: Shortlist
    ) -> tuple[Neighbor, ...]:
        out_sets = np.array(
            list(itertools.combinations(range(outs.size), order)), dtype=np.int64
        ).reshape(-1, order)
        in_sets = np.array(
            list(itertools.combinations(range(ins.size), order)), dtype=np.int64
        ).reshape(-1, order)
        keep = outs.scores[out_sets].sum(axis=1)
        gain = ins.scores[in_sets].sum(axis=1)
        prior = gain[np.newaxis, :] - keep[:, np.newaxis]
        chosen = _top_indices(prior.ravel(), self._limit)
        rows, columns = np.divmod(chosen, in_sets.shape[0])
        neighbors: list[Neighbor] = []
        for row, column in zip(rows.tolist(), columns.tolist(), strict=True):
            out_positions = tuple(int(p) for p in outs.positions[out_sets[row]])
            in_positions = tuple(int(p) for p in ins.positions[in_sets[column]])
            neighbors.append(
                Neighbor(
                    (node - set(out_positions)) | set(in_positions),
                    MoveKind.SWAP,
                    out_positions,
                    in_positions,
                    float(prior[row, column]),
                )
            )
        return tuple(neighbors)
