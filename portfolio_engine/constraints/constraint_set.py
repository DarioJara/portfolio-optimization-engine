"""Representación declarativa de las restricciones de una cartera (MASTER_SPEC §12).

Requisitos: CON-018, CON-020.

``ConstraintSet`` fusiona la configuración global (``ConstraintConfig``) con la especificación de
la cartera (``PortfolioSpec``) aplicando la precedencia documentada en ARCHITECTURE §6.4:
**override por cartera > configuración global > campo del universo**. Es inmutable y produce
``ConstraintHash`` determinista (MASTER_SPEC §31).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from portfolio_engine.config.constraint_config import ConstraintConfig, GroupLimit, LiquidityConfig
from portfolio_engine.models.enums import (
    BoundSource,
    RestrictedExistingPositionPolicy,
    UnknownFlagPolicy,
)
from portfolio_engine.models.portfolio import (
    PortfolioSpec,
    WeightBounds,
    resolve_restricted_policy,
)
from portfolio_engine.utils.hashing import canonical_float, canonical_json, sha256_hex


@dataclass(frozen=True, eq=False, slots=True)
class ConstraintSet:
    """Restricciones efectivas de una cartera, antes de compilarlas para una composición.

    Attributes:
        portfolio_id: cartera a la que se aplican.
        long_only: prohíbe pesos negativos.
        global_bounds: límites de peso globales (segundo en precedencia).
        spec: especificación de la cartera (overrides de límites), o ``None``.
        group_limits: límites de peso agregado por grupo.
        max_turnover: turnover máximo efectivo (``None`` = sin límite).
        max_turnover_source: origen del límite de turnover.
        restricted_policy: política efectiva para activos restringidos ya en cartera (E-09).
        min_holding_weight: peso mínimo estricto de todo activo de la composición (A-08).
        liquidity: restricción ADV/NAV de A-11 (``enabled = False`` = no se aplica).
        unknown_liquidity_policy: tratamiento de un ``LiquidityFlag`` desconocido al decidir si un
            activo puede comprarse (E-10).
        constraint_hash: ``ConstraintHash`` determinista del conjunto.
    """

    portfolio_id: str
    long_only: bool
    global_bounds: WeightBounds
    spec: PortfolioSpec | None
    group_limits: tuple[GroupLimit, ...]
    max_turnover: float | None
    max_turnover_source: BoundSource
    restricted_policy: RestrictedExistingPositionPolicy | None
    min_holding_weight: float | None
    unknown_liquidity_policy: UnknownFlagPolicy
    liquidity: LiquidityConfig
    constraint_hash: str = field(init=False)

    def __post_init__(self) -> None:
        overrides = (
            {}
            if self.spec is None
            else {
                asset_id: [bounds.min_weight, bounds.max_weight]
                for asset_id, bounds in sorted(self.spec.weight_bound_overrides.items())
            }
        )
        payload = {
            "portfolio_id": self.portfolio_id,
            "long_only": self.long_only,
            "global_bounds": [self.global_bounds.min_weight, self.global_bounds.max_weight],
            "overrides": overrides,
            "groups": [
                [limit.dimension, limit.group, limit.min_weight, limit.max_weight]
                for limit in sorted(
                    self.group_limits, key=lambda item: (item.dimension, item.group)
                )
            ],
            "max_turnover": (
                None if self.max_turnover is None else canonical_float(self.max_turnover)
            ),
            "policy": self.restricted_policy,
            "min_holding_weight": self.min_holding_weight,
            "unknown_liquidity_policy": self.unknown_liquidity_policy,
            "liquidity": [
                self.liquidity.enabled,
                self.liquidity.max_adv_participation,
                self.liquidity.liquidation_days,
                [[r.from_currency, r.to_currency, r.rate] for r in self.liquidity.fx_rates],
            ],
        }
        object.__setattr__(self, "constraint_hash", sha256_hex(canonical_json(payload)))


def build_constraint_set(
    constraints: ConstraintConfig,
    spec: PortfolioSpec | None,
    portfolio_id: str,
    min_holding_weight: float | None,
    unknown_liquidity_policy: UnknownFlagPolicy,
) -> ConstraintSet:
    """Resuelve las restricciones efectivas de ``portfolio_id`` (CON-020).

    ``PortfolioSpec.max_turnover`` y ``restricted_existing_position_policy`` prevalecen sobre los
    valores globales; los overrides de límites de peso se aplican por activo al compilar.
    ``unknown_liquidity_policy`` (``candidates.unknown_liquidity_policy``) decide, junto con
    ``EligibleFlag``, ``LiquidityFlag`` e ``InvestmentUniverse``, qué activos no pueden comprarse
    (E-10).
    """
    if spec is not None and spec.max_turnover is not None:
        max_turnover, source = spec.max_turnover, BoundSource.PORTFOLIO_OVERRIDE
    elif constraints.global_max_turnover is not None:
        max_turnover, source = constraints.global_max_turnover, BoundSource.GLOBAL_CONFIG
    else:
        max_turnover, source = None, BoundSource.UNSET
    policy = resolve_restricted_policy(spec, constraints.restricted_existing_position_policy)
    return ConstraintSet(
        portfolio_id=portfolio_id,
        long_only=constraints.long_only,
        global_bounds=WeightBounds(constraints.global_min_weight, constraints.global_max_weight),
        spec=spec,
        group_limits=constraints.group_limits,
        max_turnover=max_turnover,
        max_turnover_source=source,
        restricted_policy=policy,
        min_holding_weight=min_holding_weight,
        unknown_liquidity_policy=unknown_liquidity_policy,
        liquidity=constraints.liquidity,
    )
