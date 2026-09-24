"""Capacidad de liquidez ADV/NAV (A-11, MASTER_SPEC §12-§13; CON-012, FEA-006).

::

    LiquidityCapacity_i = max_adv_participation · ADVNotionalPerDay_i · liquidation_days / NAV

Dimensionalmente: ``ADVNotionalPerDay`` es un **importe por día** (divisa/día) y
``liquidation_days`` son días, así que ``participación · ADV · días`` es un importe (divisa);
dividido por ``NAV`` (importe, misma divisa) resulta un **peso adimensional**. Por eso la fórmula
solo es válida si:

* ``ADV`` es un importe monetario medio negociado por día (``AdvUnit.NOTIONAL_PER_DAY``); un ``ADV``
  en títulos o contratos por día se **rechaza** (sin conversión implícita: convertirlo exigiría un
  precio y una política de valoración aprobados que no existen en B3) y una unidad ausente también;
* ``ADVCurrency`` y ``NAVCurrency`` están **ambas** declaradas (su ausencia es un error: no se
  supone que coincidan) y, si difieren, existe un tipo de cambio explícito del par exacto con la
  orientación ``unidades de NAVCurrency por unidad de ADVCurrency``:
  ``ADV_en_NAVCurrency = ADV · FXRate`` (sin inversión ni inferencia de pares);
* el activo declara la procedencia del dato (``ADVSource``).

* posición nueva: ``w_i <= LiquidityCapacity_i``;
* posición existente: ``w_i <= max(w_current_i, LiquidityCapacity_i)`` (política de posición
  existente protegida: no se obliga a vender una posición que ya supera el límite, pero tampoco
  puede aumentar por encima de su peso actual).

Es un límite de **tamaño de posición**: no garantiza que una venta pueda ejecutarse y es distinto de
una futura restricción de volumen negociable por operación. Con la restricción activada, cualquier
dato requerido ausente o inválido lanza :class:`ConstraintCompilationError` (nunca se desactiva en
silencio), también para activos restringidos (E-09 no exime de tener los datos).

Esta es la única implementación de la fórmula: la consumen el compilador y la generación de
candidatos; la factibilidad previa y el validador usan la ``LiquidityCapRule`` resultante.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from portfolio_engine.config.constraint_config import LiquidityConfig
from portfolio_engine.exceptions import ConstraintCompilationError
from portfolio_engine.models.asset import AssetMetadata
from portfolio_engine.models.enums import AdvUnit


@dataclass(frozen=True, slots=True)
class LiquidityCapacity:
    """Capacidad de un activo y datos con los que se calculó (trazabilidad).

    ``fx_rate`` es ``None`` si ``ADV`` y ``NAV`` ya estaban en la misma divisa.
    """

    capacity: float
    adv: float
    adv_in_nav_currency: float
    fx_rate: float | None
    adv_unit: AdvUnit
    adv_currency: str
    nav_currency: str
    adv_source: str


def validate_nav(nav: float | None) -> float:
    """``NAV`` finito y ``> 0`` o :class:`ConstraintCompilationError`."""
    if nav is None or not math.isfinite(nav) or not nav > 0:
        raise ConstraintCompilationError(
            f"Restricción ADV/NAV activada con NAV inválido o ausente: {nav!r} (debe ser > 0)."
        )
    return float(nav)


def check_adv_unit(asset: AssetMetadata) -> AdvUnit:
    """Unidad de ``ADV`` verificada: solo importe monetario diario es utilizable."""
    unit = asset.adv_unit
    if unit is None:
        raise ConstraintCompilationError(
            f"{asset.asset_id}: restricción ADV/NAV activada sin unidad de ADV (ADVUnit); "
            "debe ser NOTIONAL_PER_DAY."
        )
    if not isinstance(unit, AdvUnit):
        raise ConstraintCompilationError(f"{asset.asset_id}: unidad de ADV desconocida {unit!r}.")
    if unit is not AdvUnit.NOTIONAL_PER_DAY:
        raise ConstraintCompilationError(
            f"{asset.asset_id}: ADV expresado en {unit.value}: no es un importe monetario y no se "
            "convierte implícitamente (requeriría un precio y una política de valoración "
            "aprobados); la restricción ADV/NAV solo admite NOTIONAL_PER_DAY."
        )
    return unit


def check_currencies(
    asset: AssetMetadata, config: LiquidityConfig, nav_currency: str | None
) -> tuple[str, float | None]:
    """``(ADVCurrency, tipo de cambio o None)``; ambas divisas son obligatorias."""
    adv_currency = asset.adv_currency
    if adv_currency is None or not nav_currency:
        raise ConstraintCompilationError(
            f"{asset.asset_id}: divisa de ADV ({adv_currency!r}) y de NAV ({nav_currency!r}) son "
            "obligatorias con la restricción ADV/NAV activada (no se supone que coincidan)."
        )
    if adv_currency == nav_currency:
        return adv_currency, None
    rate = config.rate_for(adv_currency, nav_currency)
    if rate is None:
        raise ConstraintCompilationError(
            f"{asset.asset_id}: ADV en {adv_currency} y NAV en {nav_currency} requieren un tipo de "
            f"cambio explícito {adv_currency}->{nav_currency} (unidades de {nav_currency} por "
            f"unidad de {adv_currency}) en constraints.liquidity.fx_rates."
        )
    return adv_currency, rate


def liquidity_capacity(
    asset: AssetMetadata,
    config: LiquidityConfig,
    nav: float | None,
    nav_currency: str | None,
) -> LiquidityCapacity:
    """``LiquidityCapacity`` de ``asset`` (la restricción debe estar activada y completa)."""
    participation, days = config.max_adv_participation, config.liquidation_days
    if not config.enabled or participation is None or days is None:
        raise ConstraintCompilationError("La restricción ADV/NAV no está activada.")
    nav_value = validate_nav(nav)
    unit = check_adv_unit(asset)
    adv = asset.adv
    if adv is None or not math.isfinite(adv) or adv < 0:
        raise ConstraintCompilationError(
            f"{asset.asset_id}: restricción ADV/NAV activada con ADV inválido o ausente: {adv!r}."
        )
    if asset.adv_source is None:
        raise ConstraintCompilationError(
            f"{asset.asset_id}: ADV sin procedencia declarada (ADVSource)."
        )
    adv_currency, fx = check_currencies(asset, config, nav_currency)
    adv_nav = adv * (1.0 if fx is None else fx)
    return LiquidityCapacity(
        participation * adv_nav * days / nav_value,
        adv,
        adv_nav,
        fx,
        unit,
        adv_currency,
        str(nav_currency),
        asset.adv_source,
    )


def effective_upper(current_weight: float, capacity: float) -> float:
    """Tope de la posición: ``max(w_current, capacidad)`` (``capacidad`` si no está en cartera)."""
    return max(current_weight, capacity)
