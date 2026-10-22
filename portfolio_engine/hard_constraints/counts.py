"""Recuento de cambios de componentes entre la cartera original y una propuesta final.

Sea ``C0`` el conjunto de posiciones de la cartera original y ``C`` el de la propuesta
(posiciones = activos con ``w_i > position_weight_threshold``, una sola definición para todo el
módulo). Con ``a = |C ∖ C0|`` (incorporados) y ``r = |C0 ∖ C|`` (retirados)::

    total_changed = a + r                      (max_total_changed_assets)
    replacements  = min(a, r)                  (max_replacements: sustituciones uno a uno)
    pure_additions = a − min(a, r)             (max_pure_additions: altas independientes)
    pure_removals  = r − min(a, r)             (max_pure_removals: bajas independientes)
    swaps          = max(a, r)                 (MaximumSwaps de B3, sin cambios)
    final_size − original_size = a − r

Es una función pura sobre conjuntos de ``AssetID``; la usan el generador de candidatos, el
validador de composiciones y la validación final de propuestas (una única definición).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChangeCounts:
    """Cambios de componentes de una propuesta respecto a la cartera original."""

    original_size: int
    final_size: int
    added: int
    removed: int
    total_changed: int
    replacements: int
    pure_additions: int
    pure_removals: int
    swaps: int


def change_counts(original: Collection[str], final: Collection[str]) -> ChangeCounts:
    """Cambios de ``final`` respecto a ``original`` (conjuntos de ``AssetID``)."""
    before, after = frozenset(original), frozenset(final)
    added, removed = len(after - before), len(before - after)
    paired = min(added, removed)
    return ChangeCounts(
        original_size=len(before),
        final_size=len(after),
        added=added,
        removed=removed,
        total_changed=added + removed,
        replacements=paired,
        pure_additions=added - paired,
        pure_removals=removed - paired,
        swaps=max(added, removed),
    )


def positions_of(weights: Mapping[str, float], threshold: float) -> frozenset[str]:
    """Posiciones realmente mantenidas: activos con peso estrictamente mayor que ``threshold``."""
    return frozenset(asset_id for asset_id, weight in weights.items() if weight > threshold)
