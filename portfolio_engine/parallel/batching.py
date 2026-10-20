"""Lotes de carteras y orden canónico (MASTER_SPEC §56-57, §61; PAR-001, PAR-003, PAR-010).

La unidad de paralelización es la cartera (agrupada en lotes), nunca un ``FrontierPoint``: todos
los puntos de todas las operaciones de una cartera se calculan en el mismo worker (PAR-001/002).

* ``SequenceID``: posición de la cartera en el orden canónico (por ``PortfolioID``). Los resultados
  se ordenan siempre por él, de modo que no dependen del orden de envío ni del de finalización.
* Tamaño de lote: fijo (``batch_size``) o AUTO (``ceil(n / (workers × auto_batches_per_worker))``
  acotado a ``[1, max_batch_size]``). AUTO es una heurística de equilibrio de carga sin calibrar
  (BEN-004/E13 la calibrará con mediciones); no usa costes estimados.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from portfolio_engine.config.parallel_config import ParallelConfig
from portfolio_engine.exceptions import PortfolioEngineError
from portfolio_engine.parallel.task import PortfolioRequest


class ParallelExecutionError(PortfolioEngineError):
    """Error de planificación o de integridad del ejecutor (no de una cartera concreta)."""


@dataclass(frozen=True, eq=False, slots=True)
class SequencedRequest:
    """Solicitud con su ``SequenceID`` canónico."""

    sequence_id: int
    request: PortfolioRequest


@dataclass(frozen=True, eq=False, slots=True)
class PortfolioBatch:
    """Lote de carteras que se ejecutan en el mismo worker, en orden de ``SequenceID``."""

    batch_id: int
    items: tuple[SequencedRequest, ...]

    @property
    def sequence_ids(self) -> tuple[int, ...]:
        """``SequenceID`` de las carteras del lote."""
        return tuple(item.sequence_id for item in self.items)


def canonical_order(requests: Sequence[PortfolioRequest]) -> tuple[SequencedRequest, ...]:
    """Asigna ``SequenceID`` ordenando por ``PortfolioID`` (único); no depende del orden de entrada.

    Lanza :class:`ParallelExecutionError` si hay ``PortfolioID`` duplicados.
    """
    ordered = sorted(requests, key=lambda request: request.portfolio_id)
    for first, second in pairwise(ordered):
        if first.portfolio_id == second.portfolio_id:
            raise ParallelExecutionError(f"PortfolioID duplicado: {first.portfolio_id!r}.")
    return tuple(SequencedRequest(position, request) for position, request in enumerate(ordered))


def resolve_batch_size(config: ParallelConfig, n_portfolios: int) -> int:
    """Tamaño de lote efectivo (fijo o AUTO), siempre en ``[1, max_batch_size]``."""
    if n_portfolios < 1:
        raise ParallelExecutionError("No hay carteras que agrupar en lotes.")
    if config.batch_size is not None:
        return config.batch_size
    target_batches = config.workers * config.auto_batches_per_worker
    return max(1, min(config.max_batch_size, math.ceil(n_portfolios / target_batches)))


def make_batches(
    items: Sequence[SequencedRequest], config: ParallelConfig
) -> tuple[PortfolioBatch, ...]:
    """Agrupa ``items`` (ya ordenados) en lotes consecutivos del tamaño resuelto."""
    if not items:
        return ()
    size = resolve_batch_size(config, len(items))
    return tuple(
        PortfolioBatch(batch_id, tuple(items[start : start + size]))
        for batch_id, start in enumerate(range(0, len(items), size))
    )
