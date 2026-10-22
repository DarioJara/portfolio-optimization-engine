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

Restricciones duras de carteras finales (``hard_constraints``): ``CompositionLimits`` admite además
intervalo de cardinalidad (``min_size`` / ``max_size``), activos retirados, cambios totales,
sustituciones uno a uno y altas/bajas independientes. Con ``a = nuevos`` y ``r = retirados``:
``total = a + r``, ``replacements = min(a, r)``, ``pure_additions = a − min(a, r)`` y
``pure_removals = r − min(a, r)`` (:mod:`portfolio_engine.hard_constraints.counts` es la misma
definición para la validación final). ``max_new_assets`` es el límite de ``a`` (alias de
``max_added_assets``).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

import numpy as np

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy

CARDINALITY = "CARDINALITY"
MAX_NEW_ASSETS = "MAX_NEW_ASSETS"
MAX_SWAPS = "MAX_SWAPS"
MANDATORY_ASSET_REMOVED = "MANDATORY_ASSET_REMOVED"
CARDINALITY_BELOW_MIN = "CARDINALITY_BELOW_MIN"
CARDINALITY_ABOVE_MAX = "CARDINALITY_ABOVE_MAX"
MAX_REMOVED_ASSETS = "MAX_REMOVED_ASSETS"
MAX_TOTAL_CHANGED_ASSETS = "MAX_TOTAL_CHANGED_ASSETS"
MAX_REPLACEMENTS = "MAX_REPLACEMENTS"
MAX_PURE_ADDITIONS = "MAX_PURE_ADDITIONS"
MAX_PURE_REMOVALS = "MAX_PURE_REMOVALS"


@dataclass(frozen=True, slots=True)
class CompositionLimits:
    """Límites discretos de una composición respecto a la cartera actual.

    Attributes:
        target_size: ``TargetPortfolioSize`` efectivo (``None`` = no se exige).
        max_new_assets: ``MaximumNewAssets`` (``None`` = sin límite).
        max_swaps: ``MaximumSwaps`` (``None`` = sin límite).
        mandatory: activos que no pueden abandonar la composición (p. ej. ``FREEZE_WEIGHT``).
        min_size: tamaño mínimo de la composición final (``None`` = sin mínimo).
        max_size: tamaño máximo de la composición final (``None`` = sin máximo).
        max_removed_assets: activos retirados como máximo (``None`` = sin límite).
        max_total_changed: altas más bajas como máximo (``None`` = sin límite).
        max_replacements: sustituciones uno a uno (``min(a, r)``) como máximo.
        max_pure_additions: altas independientes (``a − min(a, r)``) como máximo.
        max_pure_removals: bajas independientes (``r − min(a, r)``) como máximo.
    """

    target_size: int | None
    max_new_assets: int | None
    max_swaps: int | None
    mandatory: frozenset[str]
    min_size: int | None = None
    max_size: int | None = None
    max_removed_assets: int | None = None
    max_total_changed: int | None = None
    max_replacements: int | None = None
    max_pure_additions: int | None = None
    max_pure_removals: int | None = None


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
    violations.extend(_component_violations(limits, current, candidate))
    if not limits.mandatory <= frozenset(candidate):
        violations.append(MANDATORY_ASSET_REMOVED)
    return tuple(violations)


def _component_violations(
    limits: CompositionLimits, current: Collection[str], candidate: Collection[str]
) -> list[str]:
    """Límites de retirados, cambios totales, sustituciones y altas/bajas independientes."""
    added = len(new_assets(current, candidate))
    removed = len(removed_assets(current, candidate))
    paired = min(added, removed)
    checks = (
        (limits.max_removed_assets, removed, MAX_REMOVED_ASSETS),
        (limits.max_total_changed, added + removed, MAX_TOTAL_CHANGED_ASSETS),
        (limits.max_replacements, paired, MAX_REPLACEMENTS),
        (limits.max_pure_additions, added - paired, MAX_PURE_ADDITIONS),
        (limits.max_pure_removals, removed - paired, MAX_PURE_REMOVALS),
    )
    return [code for limit, value, code in checks if limit is not None and value > limit]


def limit_violations(
    limits: CompositionLimits, current: Collection[str], candidate: Collection[str]
) -> tuple[str, ...]:
    """Todas las violaciones de una composición final: cardinalidad y movimientos."""
    violations = list(move_violations(limits, current, candidate))
    size = len(frozenset(candidate))
    if limits.target_size is not None and size != limits.target_size:
        violations.insert(0, CARDINALITY)
    if limits.min_size is not None and size < limits.min_size:
        violations.append(CARDINALITY_BELOW_MIN)
    if limits.max_size is not None and size > limits.max_size:
        violations.append(CARDINALITY_ABOVE_MAX)
    return tuple(violations)


@dataclass(frozen=True, slots=True)
class MembershipRules:
    """Pertenencia forzada a la composición derivada de las restricciones compiladas.

    ``mandatory`` son las posiciones que no pueden salir (política ``FREEZE_WEIGHT`` de un activo
    restringido en cartera: el peso queda congelado) y ``forbidden`` las que no pueden entrar ni
    mantenerse con peso (cota superior efectiva nula: restringidos nuevos, ``FORCE_LIQUIDATE`` y
    activos no comprables ausentes de la cartera). Son las mismas reglas de E-09 y E-10 que aplica
    el compilador, leídas de las restricciones compiladas y no reinterpretadas.
    """

    mandatory: tuple[int, ...]
    forbidden: tuple[int, ...]


def membership_rules(compiled: CompiledConstraints) -> MembershipRules:
    """Posiciones de ``compiled`` cuya pertenencia a la composición está forzada."""
    mandatory = tuple(
        rule.position
        for rule in compiled.restricted_rules
        if rule.is_held and rule.policy is RestrictedExistingPositionPolicy.FREEZE_WEIGHT
    )
    forbidden = tuple(int(i) for i in np.flatnonzero(compiled.upper <= 0.0).tolist())
    return MembershipRules(mandatory=mandatory, forbidden=forbidden)
