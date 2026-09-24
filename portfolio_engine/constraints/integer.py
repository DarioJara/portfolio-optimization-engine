"""Restricciones enteras sobre el conjunto de activos: cardinalidad, nuevos activos y swaps.

Requisitos: CON-010, CON-011, CON-019 (representación y comprobación para la heurística del
Bloque 3; la formulación MIQP exacta de ``TargetPortfolioSize`` con variables binarias es del
Bloque 4 y no se simula aquí eliminando pesos tras el solver).

Definiciones sobre conjuntos de ``AssetID`` respecto a la composición actual ``C0`` y una
composición candidata ``C``::

    nuevos       = |C \\ C0|                    (MaximumNewAssets)
    retirados    = |C0 \\ C|
    swaps        = max(nuevos, retirados)       (MaximumSwaps: activos sustituidos)
    cardinalidad = |C| = TargetPortfolioSize

Las comprobaciones devuelven códigos de violación explícitos; nada se relaja en silencio.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

CARDINALITY = "CARDINALITY"
MAX_NEW_ASSETS = "MAX_NEW_ASSETS"
MAX_SWAPS = "MAX_SWAPS"
MANDATORY_ASSET_REMOVED = "MANDATORY_ASSET_REMOVED"


@dataclass(frozen=True, slots=True)
class CompositionLimits:
    """Límites discretos de una composición respecto a la cartera actual.

    Attributes:
        target_size: ``TargetPortfolioSize`` efectivo (``None`` = no se exige).
        max_new_assets: ``MaximumNewAssets`` (``None`` = sin límite).
        max_swaps: ``MaximumSwaps`` (``None`` = sin límite).
        mandatory: activos que no pueden abandonar la composición (p. ej. ``FREEZE_WEIGHT``).
    """

    target_size: int | None
    max_new_assets: int | None
    max_swaps: int | None
    mandatory: frozenset[str]


def new_assets(current: Collection[str], candidate: Collection[str]) -> frozenset[str]:
    """Activos de ``candidate`` que no están en ``current``."""
    return frozenset(candidate) - frozenset(current)


def removed_assets(current: Collection[str], candidate: Collection[str]) -> frozenset[str]:
    """Activos de ``current`` que no están en ``candidate``."""
    return frozenset(current) - frozenset(candidate)


def swap_count(current: Collection[str], candidate: Collection[str]) -> int:
    """Activos sustituidos: ``max(|nuevos|, |retirados|)``."""
    return max(len(new_assets(current, candidate)), len(removed_assets(current, candidate)))


def move_violations(
    limits: CompositionLimits, current: Collection[str], candidate: Collection[str]
) -> tuple[str, ...]:
    """Violaciones de nuevos activos, swaps y activos obligatorios (no de cardinalidad).

    Es la comprobación de una composición intermedia de la búsqueda, que puede tener un tamaño
    distinto del objetivo mientras se corrige.
    """
    violations: list[str] = []
    if limits.max_new_assets is not None and len(new_assets(current, candidate)) > (
        limits.max_new_assets
    ):
        violations.append(MAX_NEW_ASSETS)
    if limits.max_swaps is not None and swap_count(current, candidate) > limits.max_swaps:
        violations.append(MAX_SWAPS)
    if not limits.mandatory <= frozenset(candidate):
        violations.append(MANDATORY_ASSET_REMOVED)
    return tuple(violations)


def limit_violations(
    limits: CompositionLimits, current: Collection[str], candidate: Collection[str]
) -> tuple[str, ...]:
    """Todas las violaciones de una composición final: cardinalidad y movimientos."""
    violations = list(move_violations(limits, current, candidate))
    if limits.target_size is not None and len(frozenset(candidate)) != limits.target_size:
        violations.insert(0, CARDINALITY)
    return tuple(violations)
