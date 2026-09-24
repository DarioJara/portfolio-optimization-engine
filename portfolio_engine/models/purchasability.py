"""Regla única de «activo no comprable» (E-10, MASTER_SPEC §12).

Un activo **no comprable** es el que no puede recibir nuevas compras: ``EligibleFlag`` falso,
``LiquidityFlag`` falso (o desconocido con una política conservadora) o fuera del
``InvestmentUniverse`` de la cartera. Si el activo ya está en cartera puede mantenerse o reducirse,
pero nunca incrementarse (``0 <= w <= min(w_current, MaxWeight)``); si no está, no puede entrar
(``w = 0``). Esta función es la única definición del predicado y la consumen el compilador de
restricciones y el filtro de elegibilidad de candidatos.

La precedencia de :class:`RestrictedExistingPositionPolicy` (E-09) no se toca aquí: un activo
restringido se trata siempre por su propia política, que es igual o más estricta.
"""

from __future__ import annotations

from collections.abc import Collection

from portfolio_engine.exceptions import ConstraintCompilationError
from portfolio_engine.models.asset import AssetMetadata
from portfolio_engine.models.enums import EligibilityReason, UnknownFlagPolicy


def purchase_block_reasons(
    asset: AssetMetadata,
    investment_universe: Collection[str] | None,
    unknown_liquidity_policy: UnknownFlagPolicy,
) -> tuple[EligibilityReason, ...]:
    """Causas por las que ``asset`` no puede comprarse (vacío = comprable).

    ``investment_universe`` es el ``InvestmentUniverse`` de la cartera (``None`` = todo el
    universo). Un ``LiquidityFlag`` desconocido sigue ``unknown_liquidity_policy``: ``EXCLUDE``
    impide comprar, ``ALLOW`` permite y ``ERROR`` detiene la ejecución (sin sustitución
    silenciosa; solo se exige para un activo con ``EligibleFlag`` verdadero, como el filtro).
    """
    reasons: list[EligibilityReason] = []
    if not asset.eligible:
        reasons.append(EligibilityReason.NOT_ELIGIBLE)
    if asset.liquidity_flag is False:
        reasons.append(EligibilityReason.NOT_LIQUID)
    elif asset.liquidity_flag is None:
        if unknown_liquidity_policy is UnknownFlagPolicy.ERROR and asset.eligible:
            raise ConstraintCompilationError(
                f"{asset.asset_id}: LiquidityFlag desconocido con política ERROR."
            )
        if unknown_liquidity_policy is not UnknownFlagPolicy.ALLOW:
            reasons.append(EligibilityReason.UNKNOWN_LIQUIDITY_FLAG)
    if investment_universe is not None and asset.asset_id not in investment_universe:
        reasons.append(EligibilityReason.OUTSIDE_INVESTMENT_UNIVERSE)
    return tuple(reasons)
