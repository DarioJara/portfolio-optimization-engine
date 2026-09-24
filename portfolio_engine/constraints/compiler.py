"""Compilación de restricciones para una composición fija (MASTER_SPEC §12, §15).

Requisitos: CON-001..009, CON-013, CON-018, CON-022.

``ConstraintCompiler`` traduce un :class:`ConstraintSet` y una composición a los datos que
consumen el constructor del problema y el validador de soluciones:

* presupuesto ``Σw = 1`` (CON-001);
* límites de peso por activo (``LongOnly`` CON-002, ``MinWeight``/``MaxWeight`` CON-003);
* filas de grupo sector/país/clase de activo/divisa (CON-006..009);
* turnover máximo ``0.5·(Σ_composición |w − w_current| + Σ_retirados |w_current|) <= MaxTurnover``
  (CON-005): los activos actuales que no están en la composición se liquidan por completo y su
  turnover es una constante de la optimización (``exit_turnover``);
* traducción de ``RestrictedExistingPositionPolicy`` a límites efectivos (CON-013, CON-022, E-09):

  ==================  ==========================================
  HOLD_OR_REDUCE      ``0 <= w_i <= min(w_current_i, MaxWeight_i)``
  FREEZE_WEIGHT       ``w_i = w_current_i``
  FORCE_LIQUIDATE     ``w_i = 0``
  restringido nuevo   ``w_i = 0`` (nunca se incorpora ni se compra)
  ==================  ==========================================

Un activo restringido actual que sale de la composición cumple ``HOLD_OR_REDUCE`` (se reduce a
cero) y ``FORCE_LIQUIDATE`` (la venta completa es la liquidación); con ``FREEZE_WEIGHT`` no puede
salir: la composición es incompatible y se rechaza antes del solver (factibilidad previa).

Los valores del enum se consumen solo aquí y en el validador; ni los backends ni el constructor del
problema los referencian (test de arquitectura).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import numpy.typing as npt

from portfolio_engine.constraints.constraint_set import ConstraintSet
from portfolio_engine.exceptions import ConstraintCompilationError
from portfolio_engine.models.asset import AssetMetadata, Universe
from portfolio_engine.models.enums import GroupDimension, RestrictedExistingPositionPolicy
from portfolio_engine.models.portfolio import (
    CurrentPortfolioState,
    composition_hash,
    resolve_effective_weight_bounds,
)
from portfolio_engine.utils.hashing import (
    canonical_float,
    canonical_json,
    hash_float_array,
    sha256_hex,
)
from portfolio_engine.utils.numerics import readonly_float_array

#: Atributo de :class:`AssetMetadata` que define cada dimensión de grupo.
GROUP_ATTRIBUTE: Mapping[GroupDimension, str] = MappingProxyType(
    {
        GroupDimension.SECTOR: "sector",
        GroupDimension.COUNTRY: "country",
        GroupDimension.ASSET_CLASS: "asset_class",
        GroupDimension.CURRENCY: "currency",
    }
)


@dataclass(frozen=True, slots=True)
class RestrictedPositionRule:
    """Regla aplicada a un activo restringido de la composición.

    ``policy`` es ``None`` para un activo restringido que no está en la cartera actual (nunca se
    incorpora). ``config_lower``/``config_upper`` son los límites previos a la política, usados
    por la factibilidad previa para detectar conflictos (E-09).
    """

    position: int
    asset_id: str
    policy: RestrictedExistingPositionPolicy | None
    current_weight: float
    is_held: bool
    config_lower: float
    config_upper: float


@dataclass(frozen=True, slots=True)
class ExitedPosition:
    """Posición actual que no está en la composición y se liquida por completo (MASTER_SPEC §23).

    ``policy`` es la política efectiva si el activo es restringido y está en cartera; ``None`` si
    no es restringido.
    """

    asset_id: str
    current_weight: float
    is_restricted: bool
    policy: RestrictedExistingPositionPolicy | None


@dataclass(frozen=True, eq=False, slots=True)
class CompiledConstraints:
    """Restricciones lineales compiladas sobre las variables ``w`` de la composición.

    Los arrays usan ``±inf`` para "sin límite". ``lower``/``upper`` ya incorporan la política de
    activos restringidos; ``group_matrix`` tiene una fila indicadora por límite de grupo.
    """

    asset_ids: tuple[str, ...]
    composition_id: str
    budget: float
    long_only: bool
    lower: npt.NDArray[np.float64]
    upper: npt.NDArray[np.float64]
    group_labels: tuple[str, ...]
    group_matrix: npt.NDArray[np.float64]
    group_min: npt.NDArray[np.float64]
    group_max: npt.NDArray[np.float64]
    current_weights: npt.NDArray[np.float64]
    has_current_portfolio: bool
    max_turnover: float | None
    restricted_rules: tuple[RestrictedPositionRule, ...]
    constraint_hash: str
    exited: tuple[ExitedPosition, ...] = ()

    @property
    def exit_turnover(self) -> float:
        """Turnover constante de las liquidaciones completas: ``0.5·Σ|w_current|`` retirados."""
        return 0.5 * sum(abs(position.current_weight) for position in self.exited)

    @property
    def size(self) -> int:
        """Número de variables de peso (activos de la composición)."""
        return len(self.asset_ids)

    @property
    def needs_turnover_lifting(self) -> bool:
        """``True`` si hay ``MaxTurnover``: exige variables auxiliares de compra/venta."""
        return self.max_turnover is not None


class ConstraintCompiler:
    """Compila un :class:`ConstraintSet` para una composición fija (sin estado)."""

    def compile(
        self,
        constraint_set: ConstraintSet,
        universe: Universe,
        composition_asset_ids: Sequence[str],
        state: CurrentPortfolioState,
    ) -> CompiledConstraints:
        """Restricciones compiladas de ``composition_asset_ids`` respecto a ``state``.

        Los activos actuales que no están en la composición se liquidan por completo: se recogen en
        ``exited`` (con su política de restringidos) y aportan un turnover y un coste constantes.
        La generación de composiciones alternativas pertenece al Bloque 3.
        """
        asset_ids = tuple(composition_asset_ids)
        _check_composition(asset_ids)
        assets = [universe.get(asset_id) for asset_id in asset_ids]
        current = np.array([state.weight_of(asset_id) for asset_id in asset_ids], dtype=np.float64)
        if constraint_set.max_turnover is not None and not state.has_current_portfolio:
            raise ConstraintCompilationError(
                "MaxTurnover configurado sin cartera actual: el turnover no está definido."
            )
        lower, upper, rules = self._bounds(constraint_set, assets, current)
        labels, matrix, group_min, group_max = self._groups(constraint_set, assets)
        exited = self._exited(constraint_set, universe, asset_ids, state)
        digest = _constraint_hash(
            constraint_set, asset_ids, lower, upper, matrix, group_min, group_max, current, exited
        )
        return CompiledConstraints(
            asset_ids=asset_ids,
            composition_id=composition_hash(frozenset(asset_ids)),
            budget=1.0,
            long_only=constraint_set.long_only,
            lower=readonly_float_array(lower),
            upper=readonly_float_array(upper),
            group_labels=labels,
            group_matrix=readonly_float_array(matrix),
            group_min=readonly_float_array(group_min),
            group_max=readonly_float_array(group_max),
            current_weights=readonly_float_array(current),
            has_current_portfolio=state.has_current_portfolio,
            max_turnover=constraint_set.max_turnover,
            restricted_rules=rules,
            constraint_hash=digest,
            exited=exited,
        )

    def _exited(
        self,
        constraint_set: ConstraintSet,
        universe: Universe,
        asset_ids: tuple[str, ...],
        state: CurrentPortfolioState,
    ) -> tuple[ExitedPosition, ...]:
        kept = set(asset_ids)
        positions: list[ExitedPosition] = []
        for asset_id in state.asset_ids:
            if asset_id in kept:
                continue
            weight = state.weight_of(asset_id)
            restricted = _restricted_flag(universe.get(asset_id), weight)
            policy = constraint_set.restricted_policy if restricted else None
            if restricted and policy is None:
                raise ConstraintCompilationError(
                    f"{asset_id}: activo restringido en cartera sin "
                    "RestrictedExistingPositionPolicy."
                )
            positions.append(ExitedPosition(asset_id, weight, restricted, policy))
        return tuple(positions)

    def _bounds(
        self,
        constraint_set: ConstraintSet,
        assets: Sequence[AssetMetadata],
        current: npt.NDArray[np.float64],
    ) -> tuple[
        npt.NDArray[np.float64], npt.NDArray[np.float64], tuple[RestrictedPositionRule, ...]
    ]:
        lower = np.empty(len(assets), dtype=np.float64)
        upper = np.empty(len(assets), dtype=np.float64)
        rules: list[RestrictedPositionRule] = []
        for position, asset in enumerate(assets):
            effective = resolve_effective_weight_bounds(
                asset, constraint_set.spec, constraint_set.global_bounds
            )
            low = -np.inf if effective.min_weight is None else effective.min_weight
            high = np.inf if effective.max_weight is None else effective.max_weight
            if constraint_set.long_only:
                low = max(low, 0.0)
            if constraint_set.min_holding_weight is not None:
                low = max(low, constraint_set.min_holding_weight)
            weight = float(current[position])
            restricted = _restricted_flag(asset, weight)
            if restricted:
                rule = RestrictedPositionRule(
                    position=position,
                    asset_id=asset.asset_id,
                    policy=constraint_set.restricted_policy if weight > 0.0 else None,
                    current_weight=weight,
                    is_held=weight > 0.0,
                    config_lower=low,
                    config_upper=high,
                )
                rules.append(rule)
                low, high = _apply_policy(rule)
            lower[position], upper[position] = low, high
        return lower, upper, tuple(rules)

    def _groups(
        self, constraint_set: ConstraintSet, assets: Sequence[AssetMetadata]
    ) -> tuple[
        tuple[str, ...],
        npt.NDArray[np.float64],
        npt.NDArray[np.float64],
        npt.NDArray[np.float64],
    ]:
        limits = sorted(constraint_set.group_limits, key=lambda item: (item.dimension, item.group))
        matrix = np.zeros((len(limits), len(assets)), dtype=np.float64)
        group_min = np.full(len(limits), -np.inf, dtype=np.float64)
        group_max = np.full(len(limits), np.inf, dtype=np.float64)
        labels: list[str] = []
        for row, limit in enumerate(limits):
            attribute = GROUP_ATTRIBUTE[limit.dimension]
            missing = [asset.asset_id for asset in assets if getattr(asset, attribute) is None]
            if missing:
                raise ConstraintCompilationError(
                    f"Límite de grupo {limit.dimension}/{limit.group} sin el atributo "
                    f"{attribute!r} en los activos {missing}."
                )
            for column, asset in enumerate(assets):
                matrix[row, column] = float(getattr(asset, attribute) == limit.group)
            if limit.min_weight is not None:
                group_min[row] = limit.min_weight
            if limit.max_weight is not None:
                group_max[row] = limit.max_weight
            labels.append(f"{limit.dimension.value}:{limit.group}")
        return tuple(labels), matrix, group_min, group_max


def _check_composition(asset_ids: tuple[str, ...]) -> None:
    if not asset_ids:
        raise ConstraintCompilationError("La composición no puede estar vacía.")
    if len(set(asset_ids)) != len(asset_ids):
        raise ConstraintCompilationError("La composición contiene AssetID repetidos.")
    if list(asset_ids) != sorted(asset_ids):
        raise ConstraintCompilationError("La composición debe estar ordenada por AssetID.")


def _restricted_flag(asset: AssetMetadata, current_weight: float) -> bool:
    if asset.restricted is None:
        if current_weight > 0.0:
            return False
        raise ConstraintCompilationError(
            f"{asset.asset_id}: RestrictedAssetFlag desconocido y el activo no está en la cartera."
        )
    return asset.restricted


def _apply_policy(rule: RestrictedPositionRule) -> tuple[float, float]:
    """Límites efectivos ``(lower, upper)`` de un activo restringido (E-09)."""
    if not rule.is_held:
        return 0.0, 0.0
    policy = rule.policy
    if policy is None:
        raise ConstraintCompilationError(
            f"{rule.asset_id}: activo restringido en cartera sin RestrictedExistingPositionPolicy."
        )
    if policy is RestrictedExistingPositionPolicy.HOLD_OR_REDUCE:
        return 0.0, min(rule.current_weight, rule.config_upper)
    if policy is RestrictedExistingPositionPolicy.FREEZE_WEIGHT:
        return rule.current_weight, rule.current_weight
    return 0.0, 0.0


def _constraint_hash(
    constraint_set: ConstraintSet,
    asset_ids: tuple[str, ...],
    lower: npt.NDArray[np.float64],
    upper: npt.NDArray[np.float64],
    matrix: npt.NDArray[np.float64],
    group_min: npt.NDArray[np.float64],
    group_max: npt.NDArray[np.float64],
    current: npt.NDArray[np.float64],
    exited: tuple[ExitedPosition, ...],
) -> str:
    payload = {
        "constraint_set": constraint_set.constraint_hash,
        "asset_ids": list(asset_ids),
        "lower": hash_float_array(lower),
        "upper": hash_float_array(upper),
        "groups": hash_float_array(matrix),
        "group_min": hash_float_array(group_min),
        "group_max": hash_float_array(group_max),
        "current": hash_float_array(current),
        "exited": [
            [position.asset_id, canonical_float(position.current_weight)] for position in exited
        ],
    }
    return sha256_hex(canonical_json(payload))
