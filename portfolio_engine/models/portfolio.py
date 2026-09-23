"""Especificación por cartera y estado actual de cartera (MASTER_SPEC §7, §24, §31).

``CurrentPortfolioState`` preserva explícitamente la composición actual para calcular, en
bloques posteriores, turnover, costes de liquidación, activos nuevos/eliminados y distancia a
la cartera actual. Incluye ``CurrentPortfolioStateHash`` (enmienda E-06).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.asset import AssetMetadata
from portfolio_engine.models.enums import BoundSource, RestrictedExistingPositionPolicy
from portfolio_engine.models.universe_index import AssetIndex
from portfolio_engine.utils.hashing import canonical_float, canonical_json, sha256_hex
from portfolio_engine.utils.numerics import readonly_float_array, readonly_int_array


@dataclass(frozen=True, slots=True)
class WeightBounds:
    """Límites de peso opcionales (``None`` = sin límite en ese extremo)."""

    min_weight: float | None
    max_weight: float | None

    def __post_init__(self) -> None:
        for value in (self.min_weight, self.max_weight):
            if value is not None and not math.isfinite(value):
                raise DataValidationError("Los límites de peso deben ser finitos.")
        if (
            self.min_weight is not None
            and self.max_weight is not None
            and self.min_weight > self.max_weight
        ):
            raise DataValidationError(
                f"Límites incompatibles: MinWeight {self.min_weight} > MaxWeight {self.max_weight}"
            )


@dataclass(frozen=True, slots=True)
class EffectiveWeightBounds:
    """Límites efectivos de un activo en una cartera, con la fuente de cada extremo."""

    min_weight: float | None
    max_weight: float | None
    min_source: BoundSource
    max_source: BoundSource


@dataclass(frozen=True, slots=True)
class PortfolioSpec:
    """Configuración específica de una cartera (MASTER_SPEC §7).

    Los campos ``None`` significan "no configurado" para esa cartera; nunca se sustituyen por
    valores implícitos.
    """

    portfolio_id: str
    target_portfolio_size: int | None
    volatility_limit: float | None
    max_turnover: float | None
    investment_universe: tuple[str, ...] | None
    restricted_existing_position_policy: RestrictedExistingPositionPolicy | None
    nav: float | None
    weight_bound_overrides: Mapping[str, WeightBounds] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not self.portfolio_id:
            raise DataValidationError("PortfolioID vacío.")
        if self.target_portfolio_size is not None and self.target_portfolio_size <= 0:
            raise DataValidationError("TargetPortfolioSize debe ser positivo.")
        _require_positive_finite(self.volatility_limit, "VolatilityLimit")
        _require_positive_finite(self.nav, "NAV")
        if self.max_turnover is not None and (
            not math.isfinite(self.max_turnover) or self.max_turnover < 0
        ):
            raise DataValidationError("MaxTurnover debe ser finito y no negativo.")
        object.__setattr__(
            self, "weight_bound_overrides", MappingProxyType(dict(self.weight_bound_overrides))
        )


def _require_positive_finite(value: float | None, name: str) -> None:
    if value is not None and (not math.isfinite(value) or value <= 0):
        raise DataValidationError(f"{name} debe ser finito y positivo.")


def resolve_effective_weight_bounds(
    asset: AssetMetadata,
    spec: PortfolioSpec | None,
    global_bounds: WeightBounds,
) -> EffectiveWeightBounds:
    """Aplica la precedencia override de cartera > configuración global > universo.

    Cada extremo se resuelve de forma independiente y se registra su fuente.
    """
    override = spec.weight_bound_overrides.get(asset.asset_id) if spec is not None else None
    lower = _first_defined(
        (override.min_weight if override else None, BoundSource.PORTFOLIO_OVERRIDE),
        (global_bounds.min_weight, BoundSource.GLOBAL_CONFIG),
        (asset.min_weight, BoundSource.UNIVERSE),
    )
    upper = _first_defined(
        (override.max_weight if override else None, BoundSource.PORTFOLIO_OVERRIDE),
        (global_bounds.max_weight, BoundSource.GLOBAL_CONFIG),
        (asset.max_weight, BoundSource.UNIVERSE),
    )
    if lower[0] is not None and upper[0] is not None and lower[0] > upper[0]:
        raise DataValidationError(
            f"Límites efectivos incompatibles para {asset.asset_id}: {lower[0]} > {upper[0]}"
        )
    return EffectiveWeightBounds(lower[0], upper[0], lower[1], upper[1])


def _first_defined(
    *candidates: tuple[float | None, BoundSource],
) -> tuple[float | None, BoundSource]:
    for value, source in candidates:
        if value is not None:
            return value, source
    return None, BoundSource.UNSET


def current_portfolio_state_hash(weights: Mapping[str, float]) -> str:
    """``CurrentPortfolioStateHash`` (E-06): SHA-256 de los pares ``(AssetID, CurrentWeight)``.

    Pares ordenados por AssetID; pesos serializados exactamente con ``float.hex`` (``-0.0``
    normalizado); pesos exactamente cero excluidos. Invariante al orden de entrada y sensible
    a cualquier cambio de peso.
    """
    pairs = [
        [asset_id, canonical_float(weight)]
        for asset_id, weight in sorted(weights.items())
        if float(weight) != 0.0
    ]
    return sha256_hex(canonical_json({"CurrentPortfolioState": pairs}))


def composition_hash(asset_ids: frozenset[str]) -> str:
    """Hash determinista de una composición a partir de sus AssetID ordenados (§31)."""
    return sha256_hex(canonical_json({"Composition": sorted(asset_ids)}))


@dataclass(frozen=True, slots=True)
class CurrentPortfolioComposition:
    """Conjunto de activos de la cartera actual (punto de partida del CandidateEngine)."""

    portfolio_id: str
    asset_ids: frozenset[str]
    composition_hash: str


@dataclass(frozen=True, eq=False, slots=True)
class CurrentPortfolioState:
    """Estado actual de una cartera: activos mantenidos (peso ≠ 0), pesos e índices globales.

    Una cartera sin posiciones tiene ``has_current_portfolio = False``; en ese caso turnover y
    costes deberán marcarse como no disponibles (MASTER_SPEC §24).
    """

    portfolio_id: str
    asset_ids: tuple[str, ...]
    weights: npt.NDArray[np.float64]
    global_indices: npt.NDArray[np.int64]
    nav: float | None
    state_hash: str = field(init=False)
    composition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        weights = readonly_float_array(self.weights)
        indices = readonly_int_array(self.global_indices)
        if weights.shape != (len(self.asset_ids),) or indices.shape != weights.shape:
            raise DataValidationError("Dimensiones incoherentes en CurrentPortfolioState.")
        if list(self.asset_ids) != sorted(set(self.asset_ids)):
            raise DataValidationError("CurrentPortfolioState exige AssetID únicos y ordenados.")
        if not np.all(np.isfinite(weights)) or np.any(weights == 0.0):
            raise DataValidationError("Los pesos actuales deben ser finitos y distintos de cero.")
        _require_positive_finite(self.nav, "NAV")
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "global_indices", indices)
        object.__setattr__(
            self,
            "state_hash",
            current_portfolio_state_hash(dict(zip(self.asset_ids, weights.tolist(), strict=True))),
        )
        object.__setattr__(self, "composition_hash", composition_hash(frozenset(self.asset_ids)))

    @classmethod
    def from_weights(
        cls,
        portfolio_id: str,
        weights: Mapping[str, float],
        index: AssetIndex,
        nav: float | None,
    ) -> CurrentPortfolioState:
        """Construye el estado a partir de ``{AssetID: peso}`` (pesos cero no permitidos)."""
        asset_ids = tuple(sorted(weights))
        return cls(
            portfolio_id=portfolio_id,
            asset_ids=asset_ids,
            weights=np.array([weights[asset_id] for asset_id in asset_ids], dtype=np.float64),
            global_indices=index.indices_of(asset_ids),
            nav=nav,
        )

    @property
    def has_current_portfolio(self) -> bool:
        """``True`` si la cartera tiene al menos una posición."""
        return len(self.asset_ids) > 0

    @property
    def total_weight(self) -> float:
        """Suma de pesos actuales."""
        return float(self.weights.sum())

    def weight_of(self, asset_id: str) -> float:
        """Peso actual de ``asset_id`` (0.0 si no se mantiene)."""
        for held, weight in zip(self.asset_ids, self.weights.tolist(), strict=True):
            if held == asset_id:
                return float(weight)
        return 0.0

    def composition(self) -> CurrentPortfolioComposition:
        """Composición actual (conjunto de activos) con su hash determinista."""
        return CurrentPortfolioComposition(
            self.portfolio_id, frozenset(self.asset_ids), self.composition_hash
        )
