"""Factibilidad previa de las restricciones obligatorias (HC-008; MASTER_SPEC §13).

Reglas deterministas evaluadas **antes** de optimizar. Son condiciones *necesarias*: cada fallo es
una prueba de inviabilidad (no se llama a ningún solver y la causa queda registrada); que todas se
cumplan no garantiza la existencia de una solución (eso lo decide la búsqueda y la validación
final). Los códigos usan el prefijo ``HC_``.

Cardinalidad y cambios (para cada tamaño admisible ``k``, con ``n0`` posiciones originales y
``f`` salidas forzosas): el menor número de retiros es ``r = max(f, n0 − k)`` y el de altas
``a = k − n0 + r``; ese par minimiza a la vez ``a``, ``r``, ``a + r``, ``max(a, r)``, ``min(a, r)``,
las altas independientes (``max(k − n0, 0)``) y las bajas independientes (``max(n0 − k, 0)``), de
modo que ``k`` es alcanzable solo si ese par cumple todos los presupuestos de cambio.

Pesos y concentración: ``k`` posiciones con pesos en ``[m, M]`` que suman 1 exigen
``k·m <= 1 <= k·M``; ``Σ w² >= 1/k`` (Cauchy-Schwarz, igualdad en pesos iguales) exige
``1/k <= cap_hhi``; ``N_eff = 1/Σ w² <= k`` hace que ``min_effective_number`` equivalga a la cota
``Σ w² <= 1/N_eff`` (se combina con ``max_concentration_hhi`` en :attr:`hhi_cap`).

Volatilidad y retorno (solo con ``long_only`` y presupuesto 1, donde la región factible está
contenida en el símplex): ``σ(w) <= sqrt(max_i Σ_ii)`` (una función convexa alcanza su máximo en un
vértice) y ``μᵀw <= max_i μ_i``; un ``min_volatility`` o ``min_expected_return`` por encima de esas
cotas es inalcanzable. La cota inferior de ``σ`` frente a ``max_volatility`` es la de
:func:`~portfolio_engine.constraints.feasibility.volatility_lower_bound`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.constraints.feasibility import FeasibilityCause, check_volatility
from portfolio_engine.models.hard_constraints import EffectiveHardConstraints

HC_CARDINALITY_UNDEFINED = "HC_CARDINALITY_UNDEFINED"
HC_CARDINALITY_TARGET_OUTSIDE_POLICY = "HC_CARDINALITY_TARGET_OUTSIDE_POLICY"
HC_SIZE_EXCEEDS_AVAILABLE_ASSETS = "HC_SIZE_EXCEEDS_AVAILABLE_ASSETS"
HC_MANDATORY_EXCEEDS_SIZE = "HC_MANDATORY_EXCEEDS_SIZE"
HC_CHANGE_BUDGET_INSUFFICIENT = "HC_CHANGE_BUDGET_INSUFFICIENT"
HC_WEIGHT_BOUNDS_VS_CARDINALITY = "HC_WEIGHT_BOUNDS_VS_CARDINALITY"
HC_HHI_VS_CARDINALITY = "HC_HHI_VS_CARDINALITY"
HC_ACTIVE_WEIGHT_RANGE_EMPTY = "HC_ACTIVE_WEIGHT_RANGE_EMPTY"
HC_VOLATILITY_BAND_EMPTY = "HC_VOLATILITY_BAND_EMPTY"
HC_VOLATILITY_MAX_BELOW_DETERMINISTIC_BOUND = "HC_VOLATILITY_MAX_BELOW_DETERMINISTIC_BOUND"
HC_VOLATILITY_MIN_ABOVE_ATTAINABLE = "HC_VOLATILITY_MIN_ABOVE_ATTAINABLE"
HC_RETURN_FLOOR_UNATTAINABLE = "HC_RETURN_FLOOR_UNATTAINABLE"
HC_ALL_SIZES_INFEASIBLE = "HC_ALL_SIZES_INFEASIBLE"


@dataclass(frozen=True, eq=False, slots=True)
class PreflightData:
    """Datos deterministas del problema que necesita la factibilidad previa.

    Attributes:
        original_size: posiciones de la cartera original (``n0``).
        enterable_count: activos que pueden incorporarse (elegibles y no restringidos).
        forced_exits: posiciones originales que deben salir (``FORCE_LIQUIDATE``, cota superior 0).
        mandatory_holds: posiciones originales que no pueden salir (``FREEZE_WEIGHT``).
        long_only: ``True`` si no se admiten pesos negativos.
        mu: expected returns anualizados del conjunto de activos que puede formar la cartera.
        sigma: covarianza anualizada de ese mismo conjunto.
        budget: presupuesto (``Σ w``), normalmente 1.
    """

    original_size: int
    enterable_count: int
    forced_exits: int
    mandatory_holds: int
    long_only: bool
    mu: npt.NDArray[np.float64]
    sigma: npt.NDArray[np.float64]
    budget: float


def _size_causes(
    effective: EffectiveHardConstraints, data: PreflightData
) -> list[FeasibilityCause]:
    causes: list[FeasibilityCause] = []
    policy_low, policy_high = effective.size_min, effective.size_max
    target = effective.target_size
    if target is not None and policy_low is not None and policy_high is not None:
        if not policy_low <= target <= policy_high:
            causes.append(
                FeasibilityCause(
                    HC_CARDINALITY_TARGET_OUTSIDE_POLICY,
                    f"target_size {target} fuera del intervalo [{policy_low}, {policy_high}] que "
                    f"permite la política {effective.cardinality_policy.value} con "
                    f"{effective.original_size} posiciones originales",
                )
            )
    elif target is None and (policy_low is None or policy_high is None):
        causes.append(
            FeasibilityCause(
                HC_CARDINALITY_UNDEFINED,
                "sin cartera original y sin target_size ni intervalo min_size/max_size: la "
                "cardinalidad no está definida",
            )
        )
    elif policy_low is not None and policy_high is not None and policy_low > policy_high:
        causes.append(
            FeasibilityCause(
                HC_CARDINALITY_UNDEFINED,
                f"intervalo de cardinalidad vacío [{policy_low}, {policy_high}]",
            )
        )
    return causes


def _size_reason(effective: EffectiveHardConstraints, data: PreflightData, size: int) -> str | None:
    """Motivo por el que el tamaño ``size`` no es alcanzable (``None`` si lo es)."""
    n0 = data.original_size
    available = n0 + data.enterable_count - data.forced_exits
    if size > available:
        return f"{HC_SIZE_EXCEEDS_AVAILABLE_ASSETS}: {size} > {available} activos disponibles"
    if data.mandatory_holds > size:
        return (
            f"{HC_MANDATORY_EXCEEDS_SIZE}: {data.mandatory_holds} posiciones obligatorias > {size}"
        )
    removed = max(data.forced_exits, n0 - size)
    added = size - n0 + removed
    if added > data.enterable_count:
        return (
            f"{HC_CHANGE_BUDGET_INSUFFICIENT}: se necesitan {added} altas y solo hay "
            f"{data.enterable_count} activos incorporables"
        )
    paired = min(added, removed)
    needs = (
        ("max_added_assets", effective.max_added_assets, added),
        ("max_removed_assets", effective.max_removed_assets, removed),
        ("max_total_changed_assets", effective.max_total_changed_assets, added + removed),
        ("max_replacements", effective.max_replacements, paired),
        ("max_pure_additions", effective.max_pure_additions, added - paired),
        ("max_pure_removals", effective.max_pure_removals, removed - paired),
        ("max_swaps", effective.max_swaps, max(added, removed)),
    )
    for name, limit, required in needs:
        if limit is not None and required > limit:
            return (
                f"{HC_CHANGE_BUDGET_INSUFFICIENT}: el tamaño {size} exige al menos {required} en "
                f"{name} (límite {limit})"
            )
    return None


def _weight_reason(
    effective: EffectiveHardConstraints, data: PreflightData, size: int
) -> str | None:
    lower, upper = effective.min_active_weight, effective.max_active_weight
    tolerance = effective.budget_tolerance
    if lower is not None and size * lower > data.budget + tolerance:
        return (
            f"{HC_WEIGHT_BOUNDS_VS_CARDINALITY}: {size}·min_active_weight {size * lower!r} > "
            f"presupuesto {data.budget!r}"
        )
    if upper is not None and size * upper < data.budget - tolerance:
        return (
            f"{HC_WEIGHT_BOUNDS_VS_CARDINALITY}: {size}·max_active_weight {size * upper!r} < "
            f"presupuesto {data.budget!r}"
        )
    cap = effective.hhi_cap
    if cap is not None and data.budget**2 / size > cap + effective.hhi_tolerance:
        return (
            f"{HC_HHI_VS_CARDINALITY}: con {size} posiciones Σw² >= {data.budget**2 / size!r} > "
            f"cota {cap!r}"
        )
    return None


def _value_causes(
    effective: EffectiveHardConstraints, data: PreflightData
) -> list[FeasibilityCause]:
    causes: list[FeasibilityCause] = []
    lower, upper = effective.min_active_weight, effective.max_active_weight
    if lower is not None and upper is not None and lower > upper:
        causes.append(
            FeasibilityCause(
                HC_ACTIVE_WEIGHT_RANGE_EMPTY,
                f"min_active_weight {lower!r} > max_active_weight {upper!r}",
            )
        )
    low_vol, high_vol = effective.min_volatility, effective.max_volatility
    if low_vol is not None and high_vol is not None and low_vol > high_vol:
        causes.append(
            FeasibilityCause(
                HC_VOLATILITY_BAND_EMPTY,
                f"min_volatility {low_vol!r} > max_volatility {high_vol!r}",
            )
        )
    if high_vol is not None and data.sigma.size:
        for cause in check_volatility(
            data.sigma, data.budget, high_vol, effective.volatility_tolerance
        ):
            causes.append(
                FeasibilityCause(HC_VOLATILITY_MAX_BELOW_DETERMINISTIC_BOUND, cause.detail)
            )
    if data.long_only and data.sigma.size:
        if low_vol is not None:
            ceiling = abs(data.budget) * math.sqrt(float(np.max(np.diag(data.sigma))))
            if low_vol > ceiling + effective.volatility_tolerance:
                causes.append(
                    FeasibilityCause(
                        HC_VOLATILITY_MIN_ABOVE_ATTAINABLE,
                        f"min_volatility {low_vol!r} > cota superior alcanzable {ceiling!r} "
                        "(máximo de σ sobre el símplex: el mayor σ_ii)",
                    )
                )
        if effective.min_expected_return is not None:
            best = data.budget * float(np.max(data.mu))
            if effective.min_expected_return > best + effective.return_tolerance:
                causes.append(
                    FeasibilityCause(
                        HC_RETURN_FLOOR_UNATTAINABLE,
                        f"min_expected_return {effective.min_expected_return!r} > mejor retorno "
                        f"alcanzable {best!r} (μ máximo con presupuesto {data.budget!r})",
                    )
                )
    return causes


def check_preflight(
    effective: EffectiveHardConstraints,
    data: PreflightData,
    sizes: tuple[int, ...] | None = None,
) -> tuple[FeasibilityCause, ...]:
    """Causas deterministas de inviabilidad de las restricciones obligatorias (vacío = no hay).

    ``sizes`` limita la comprobación a esos tamaños (p. ej. el de una ejecución de la búsqueda);
    por defecto, todos los tamaños admisibles. Si ningún tamaño es alcanzable se añade
    ``HC_ALL_SIZES_INFEASIBLE`` con el motivo de cada uno.
    """
    causes = _size_causes(effective, data)
    causes.extend(_value_causes(effective, data))
    candidates = effective.allowed_sizes if sizes is None else sizes
    if not candidates:
        if not causes:
            causes.append(FeasibilityCause(HC_CARDINALITY_UNDEFINED, "ningún tamaño admisible"))
        return tuple(causes)
    reasons: list[str] = []
    for size in candidates:
        reason = _size_reason(effective, data, size) or _weight_reason(effective, data, size)
        if reason is None:
            return tuple(causes)
        reasons.append(f"k={size}: {reason}")
    causes.append(FeasibilityCause(HC_ALL_SIZES_INFEASIBLE, "; ".join(reasons)))
    return tuple(causes)
