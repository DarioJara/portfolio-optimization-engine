"""Validación independiente de composiciones candidatas (MASTER_SPEC §12, §26, §44; VAL-010).

Comprueba una composición **desde los datos crudos** (universo, cartera actual, especificación,
política de restringidos y límites discretos), sin usar el ``EligibilityFilter`` ni el estado de la
búsqueda: una composición que el motor de candidatos considere válida pero que viole el contrato se
rechaza aquí. Reglas:

* todos los activos existen en el universo y no hay duplicados;
* un activo **nuevo** (no está en la cartera actual) debe ser elegible, líquido (o con
  ``LiquidityFlag`` desconocido y política ``ALLOW``), no restringido y pertenecer al
  ``InvestmentUniverse`` (si existe);
* un restringido ya en cartera cumple ``RestrictedExistingPositionPolicy`` (``FREEZE_WEIGHT`` no
  puede desaparecer; ``FORCE_LIQUIDATE`` no puede conservarse, salvo en la composición de
  referencia que representa la cartera actual);
* cardinalidad, ``MaximumNewAssets`` y ``MaximumSwaps`` (``constraints.integer``).
"""

from __future__ import annotations

from collections.abc import Collection

from portfolio_engine.constraints.integer import (
    CompositionLimits,
    limit_violations,
    move_violations,
)
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy, UnknownFlagPolicy
from portfolio_engine.models.portfolio import CurrentPortfolioState, PortfolioSpec

UNKNOWN_ASSET = "UNKNOWN_ASSET"
DUPLICATE_ASSET = "DUPLICATE_ASSET"
NEW_NOT_ELIGIBLE = "NEW_ASSET_NOT_ELIGIBLE"
NEW_NOT_LIQUID = "NEW_ASSET_NOT_LIQUID"
NEW_RESTRICTED = "NEW_ASSET_RESTRICTED"
NEW_UNKNOWN_RESTRICTED = "NEW_ASSET_UNKNOWN_RESTRICTED_FLAG"
NEW_OUTSIDE_UNIVERSE = "NEW_ASSET_OUTSIDE_INVESTMENT_UNIVERSE"
FREEZE_REMOVED = "FREEZE_WEIGHT_REMOVED"
FORCE_LIQUIDATE_RETAINED = "FORCE_LIQUIDATE_RETAINED"


def validate_candidate_composition(
    asset_ids: Collection[str],
    *,
    universe: Universe,
    state: CurrentPortfolioState,
    spec: PortfolioSpec | None,
    restricted_policy: RestrictedExistingPositionPolicy | None,
    unknown_liquidity_policy: UnknownFlagPolicy,
    target_size: int | None,
    max_new_assets: int | None,
    max_swaps: int | None,
    is_reference: bool,
) -> tuple[str, ...]:
    """Códigos de violación de ``asset_ids`` (vacío si la composición es válida).

    ``is_reference`` marca la composición que representa la cartera actual: no se le exige
    cardinalidad ni salida de los ``FORCE_LIQUIDATE`` (su peso es cero en la optimización).
    """
    ids = list(asset_ids)
    violations: list[str] = []
    if len(set(ids)) != len(ids):
        violations.append(DUPLICATE_ASSET)
    unknown = [asset_id for asset_id in ids if asset_id not in universe]
    if unknown:
        return (*violations, UNKNOWN_ASSET)
    held = set(state.asset_ids)
    violations.extend(_new_asset_violations(ids, held, universe, spec, unknown_liquidity_policy))
    violations.extend(_held_violations(set(ids), held, universe, restricted_policy, is_reference))
    limits = CompositionLimits(
        target_size=None if is_reference else target_size,
        max_new_assets=None if is_reference else max_new_assets,
        max_swaps=None if is_reference else max_swaps,
        mandatory=frozenset(),
    )
    checker = move_violations if is_reference else limit_violations
    violations.extend(checker(limits, held, ids))
    return tuple(dict.fromkeys(violations))


def _new_asset_violations(
    ids: list[str],
    held: set[str],
    universe: Universe,
    spec: PortfolioSpec | None,
    liquidity_policy: UnknownFlagPolicy,
) -> list[str]:
    allowed = (
        None if spec is None or spec.investment_universe is None else set(spec.investment_universe)
    )
    violations: list[str] = []
    for asset_id in ids:
        if asset_id in held:
            continue
        asset = universe.get(asset_id)
        if not asset.eligible:
            violations.append(NEW_NOT_ELIGIBLE)
        liquid = asset.liquidity_flag or (
            asset.liquidity_flag is None and liquidity_policy is UnknownFlagPolicy.ALLOW
        )
        if not liquid:
            violations.append(NEW_NOT_LIQUID)
        if asset.restricted is None:
            violations.append(NEW_UNKNOWN_RESTRICTED)
        elif asset.restricted:
            violations.append(NEW_RESTRICTED)
        if allowed is not None and asset_id not in allowed:
            violations.append(NEW_OUTSIDE_UNIVERSE)
    return violations


def _held_violations(
    members: set[str],
    held: set[str],
    universe: Universe,
    policy: RestrictedExistingPositionPolicy | None,
    is_reference: bool,
) -> list[str]:
    violations: list[str] = []
    for asset_id in sorted(held):
        if universe.get(asset_id).restricted is not True:
            continue
        if policy is RestrictedExistingPositionPolicy.FREEZE_WEIGHT and asset_id not in members:
            violations.append(FREEZE_REMOVED)
        if (
            policy is RestrictedExistingPositionPolicy.FORCE_LIQUIDATE
            and asset_id in members
            and not is_reference
        ):
            violations.append(FORCE_LIQUIDATE_RETAINED)
    return violations
