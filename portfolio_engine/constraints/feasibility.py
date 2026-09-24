"""Factibilidad previa determinista (MASTER_SPEC §13; FEA-001, FEA-003, FEA-004, FEA-007).

Reglas evaluadas **antes** de llamar a ningún solver. Si alguna falla, el problema se declara
``INFEASIBLE`` con ``StatusSource.PRE_SOLVER_CHECK`` y el solver no se ejecuta (decisión A-15).
Las reglas son condiciones necesarias; que todas se cumplan no garantiza la factibilidad (eso lo
decide el solver), pero cualquier fallo es una prueba de inviabilidad.

* FEA-001: ``lower_i <= upper_i``; ``Σ lower <= 1 <= Σ upper``.
* E-09: ``FREEZE_WEIGHT`` exige ``w_current`` dentro de los límites de configuración.
* FEA-003: por grupo, ``min <= max``, ``Σ lower_members <= max`` y ``Σ upper_members >= min``; por
  dimensión, la suma de mínimos efectivos no supera el presupuesto.
* FEA-004: turnover mínimo forzado por los límites ``<= MaxTurnover``. Con ``F+ = Σ max(lower −
  w0, 0)``, ``F− = Σ max(w0 − upper, 0)`` y ``r = 1 − Σw0`` (sobre la composición), el menor
  turnover alcanzable es ``max(F+, F− + r) − r/2`` (con ``r = 0``, ``max(F+, F−)``) más el
  turnover constante de los activos actuales retirados de la composición,
  ``0.5·Σ|w0_retirados|``; si este último supera por sí solo ``MaxTurnover`` el problema es
  inviable sin llamar al solver.
* E-09 (activos retirados): un restringido actual con ``FREEZE_WEIGHT`` no puede salir de la
  composición (``FREEZE_WEIGHT_EXITED``); con ``HOLD_OR_REDUCE`` o ``FORCE_LIQUIDATE`` la venta
  completa es compatible con la política.
* E-10 (activos no comprables): los límites ya incorporan ``0 <= w <= min(w_current, MaxWeight)``;
  si esos topes hacen imposible el presupuesto, además de ``SUM_UPPER_BELOW_BUDGET`` se registra
  ``NON_BUYABLE_CAPS_BELOW_BUDGET`` con los activos que lo limitan (diagnóstico de liquidez y
  elegibilidad, parte por ``LiquidityFlag`` de FEA-006).
* FEA-006 (A-11, ``check_liquidity``): con la restricción ADV/NAV activada,
  ``LIQUIDITY_CAP_BELOW_MIN_WEIGHT`` (un mínimo efectivo por encima de
  ``max(w_current, capacidad)``) y ``LIQUIDITY_CAPS_BELOW_BUDGET`` (los topes de liquidez
  impiden ``Σw = 1``), con los activos implicados.
* FEA-002 (Bloque 3): cardinalidad frente a pesos, ``check_cardinality`` (regla necesaria sobre el
  universo disponible: los ``K`` menores ``MinWeight`` no superan el presupuesto y los ``K``
  mayores ``MaxWeight`` lo alcanzan, decisión A-30).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy


@dataclass(frozen=True, slots=True)
class FeasibilityCause:
    """Causa determinista de inviabilidad."""

    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class FeasibilityReport:
    """Resultado de la factibilidad previa. ``feasible = False`` implica no invocar al solver."""

    feasible: bool
    causes: tuple[FeasibilityCause, ...]
    checks: tuple[str, ...]


class PreFeasibilityChecker:
    """Reglas deterministas previas al solver, con la tolerancia de configuración."""

    def __init__(self, tolerance: float) -> None:
        self._tolerance = tolerance

    def check(self, compiled: CompiledConstraints) -> FeasibilityReport:
        """Aplica todas las reglas a ``compiled`` y recoge cada causa de inviabilidad."""
        causes: list[FeasibilityCause] = []
        checks = (
            "BOUNDS",
            "BUDGET",
            "RESTRICTED_POLICY",
            "NON_BUYABLE_CAPS",
            "LIQUIDITY",
            "EXITED_POSITIONS",
            "GROUPS",
            "TURNOVER",
        )
        causes.extend(self._bounds(compiled))
        causes.extend(self._budget(compiled))
        causes.extend(self._restricted_policy(compiled))
        causes.extend(self._non_buyable(compiled))
        causes.extend(self.check_liquidity(compiled))
        causes.extend(self._exited(compiled))
        causes.extend(self._groups(compiled))
        causes.extend(self._turnover(compiled))
        return FeasibilityReport(not causes, tuple(causes), checks)

    def _bounds(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        crossed = np.flatnonzero(compiled.lower > compiled.upper + self._tolerance)
        return [
            FeasibilityCause(
                "BOUNDS_CROSSED",
                f"{compiled.asset_ids[i]}: lower {float(compiled.lower[i])!r} > "
                f"upper {float(compiled.upper[i])!r}",
            )
            for i in crossed.tolist()
        ]

    def _budget(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        causes: list[FeasibilityCause] = []
        total_lower = float(compiled.lower.sum())
        total_upper = float(compiled.upper.sum())
        if total_lower > compiled.budget + self._tolerance:
            causes.append(
                FeasibilityCause(
                    "SUM_LOWER_EXCEEDS_BUDGET",
                    f"Σ lower = {total_lower!r} > presupuesto {compiled.budget!r}",
                )
            )
        if total_upper < compiled.budget - self._tolerance:
            causes.append(
                FeasibilityCause(
                    "SUM_UPPER_BELOW_BUDGET",
                    f"Σ upper = {total_upper!r} < presupuesto {compiled.budget!r}",
                )
            )
        return causes

    def _restricted_policy(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        causes: list[FeasibilityCause] = []
        for rule in compiled.restricted_rules:
            if rule.policy is not RestrictedExistingPositionPolicy.FREEZE_WEIGHT:
                continue
            outside = (
                rule.current_weight > rule.config_upper + self._tolerance
                or rule.current_weight < rule.config_lower - self._tolerance
            )
            if outside:
                causes.append(
                    FeasibilityCause(
                        "FREEZE_WEIGHT_CONFLICT",
                        f"{rule.asset_id}: peso actual {rule.current_weight!r} fuera de "
                        f"[{rule.config_lower!r}, {rule.config_upper!r}]",
                    )
                )
        return causes

    def _non_buyable(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        """E-10: los topes de los activos no comprables no pueden impedir el presupuesto."""
        if not compiled.non_buyable_rules:
            return []
        total_upper = float(compiled.upper.sum())
        if total_upper >= compiled.budget - self._tolerance:
            return []
        capped = ", ".join(
            f"{rule.asset_id} (tope {compiled.upper[rule.position]!r}: "
            f"{'/'.join(reason.value for reason in rule.reasons)})"
            for rule in compiled.non_buyable_rules
        )
        return [
            FeasibilityCause(
                "NON_BUYABLE_CAPS_BELOW_BUDGET",
                f"Σ upper = {total_upper!r} < presupuesto {compiled.budget!r} con activos "
                f"no comprables limitados a su peso actual: {capped}",
            )
        ]

    def check_liquidity(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        """FEA-006: incompatibilidades de la restricción ADV/NAV con mínimos y presupuesto."""
        if not compiled.liquidity_rules:
            return []
        causes: list[FeasibilityCause] = []
        for rule in compiled.liquidity_rules:
            minimum = float(compiled.lower[rule.position])
            if minimum > rule.upper + self._tolerance:
                causes.append(
                    FeasibilityCause(
                        "LIQUIDITY_CAP_BELOW_MIN_WEIGHT",
                        f"{rule.asset_id}: peso mínimo {minimum!r} > max(w_current "
                        f"{rule.current_weight!r}, capacidad ADV/NAV {rule.capacity!r})",
                    )
                )
        total_upper = float(compiled.upper.sum())
        binding = [rule for rule in compiled.liquidity_rules if rule.binding]
        if binding and total_upper < compiled.budget - self._tolerance:
            detail = ", ".join(f"{rule.asset_id} (tope {rule.upper!r})" for rule in binding)
            causes.append(
                FeasibilityCause(
                    "LIQUIDITY_CAPS_BELOW_BUDGET",
                    f"Σ upper = {total_upper!r} < presupuesto {compiled.budget!r} con topes "
                    f"ADV/NAV vinculantes: {detail}",
                )
            )
        return causes

    def _exited(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        return [
            FeasibilityCause(
                "FREEZE_WEIGHT_EXITED",
                f"{position.asset_id}: FREEZE_WEIGHT con peso actual {position.current_weight!r} "
                "no puede salir de la composición",
            )
            for position in compiled.exited
            if position.policy is RestrictedExistingPositionPolicy.FREEZE_WEIGHT
            and position.current_weight != 0.0
        ]

    def _groups(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        causes: list[FeasibilityCause] = []
        effective_min: dict[str, float] = {}
        for row, label in enumerate(compiled.group_labels):
            members = compiled.group_matrix[row] > 0.0
            low = float(compiled.group_min[row])
            high = float(compiled.group_max[row])
            member_lower = float(compiled.lower[members].sum())
            member_upper = float(compiled.upper[members].sum())
            if low > high + self._tolerance:
                causes.append(
                    FeasibilityCause("GROUP_MIN_ABOVE_MAX", f"{label}: {low!r} > {high!r}")
                )
            if member_lower > high + self._tolerance:
                causes.append(
                    FeasibilityCause(
                        "GROUP_LOWER_EXCEEDS_MAX",
                        f"{label}: Σ lower de los miembros {member_lower!r} > max {high!r}",
                    )
                )
            if member_upper < low - self._tolerance:
                causes.append(
                    FeasibilityCause(
                        "GROUP_UPPER_BELOW_MIN",
                        f"{label}: Σ upper de los miembros {member_upper!r} < min {low!r}",
                    )
                )
            dimension = label.split(":", 1)[0]
            effective_min[dimension] = effective_min.get(dimension, 0.0) + max(
                low, member_lower, 0.0
            )
        for dimension, total in sorted(effective_min.items()):
            if total > compiled.budget + self._tolerance:
                causes.append(
                    FeasibilityCause(
                        "GROUP_MINIMUMS_EXCEED_BUDGET",
                        f"{dimension}: Σ mínimos efectivos {total!r} > presupuesto",
                    )
                )
        return causes

    def _turnover(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        if compiled.max_turnover is None:
            return []
        exit_turnover = compiled.exit_turnover
        if exit_turnover > compiled.max_turnover + self._tolerance:
            return [
                FeasibilityCause(
                    "REMOVED_ASSETS_TURNOVER_ABOVE_MAX",
                    f"turnover de liquidar los activos retirados {exit_turnover!r} > "
                    f"MaxTurnover {compiled.max_turnover!r}",
                )
            ]
        minimum = minimum_forced_turnover(compiled)
        if minimum > compiled.max_turnover + self._tolerance:
            return [
                FeasibilityCause(
                    "TURNOVER_FORCED_ABOVE_MAX",
                    f"turnover mínimo forzado {minimum!r} > MaxTurnover {compiled.max_turnover!r}",
                )
            ]
        return []


def minimum_forced_turnover(compiled: CompiledConstraints) -> float:
    """Menor turnover compatible con los límites y el presupuesto (FEA-004).

    Incluye el turnover constante de las liquidaciones completas de los activos retirados.
    """
    current = compiled.current_weights
    forced_up = float(np.maximum(compiled.lower - current, 0.0).sum())
    forced_down = float(np.maximum(current - compiled.upper, 0.0).sum())
    residual = compiled.budget - float(current.sum())
    increases = max(forced_up, forced_down + residual)
    return increases - residual * 0.5 + compiled.exit_turnover


def check_cardinality(
    target_size: int,
    lower: npt.NDArray[np.float64],
    upper: npt.NDArray[np.float64],
    budget: float,
    tolerance: float,
) -> tuple[FeasibilityCause, ...]:
    """Reglas necesarias de cardinalidad ``K`` sobre los límites de los activos disponibles.

    ``lower``/``upper`` son los límites de peso de cada activo que puede formar parte de una
    composición (``MinWeight`` es condicional a tener posición, decisión A-30): debe haber al
    menos ``K`` activos, la suma de los ``K`` menores ``MinWeight`` no puede superar el
    presupuesto y la de los ``K`` mayores ``MaxWeight`` debe alcanzarlo.
    """
    available = lower.shape[0]
    if target_size > available:
        return (
            FeasibilityCause(
                "TARGET_SIZE_EXCEEDS_AVAILABLE_ASSETS",
                f"TargetPortfolioSize {target_size} > {available} activos disponibles",
            ),
        )
    causes: list[FeasibilityCause] = []
    smallest_lower = float(np.sort(np.maximum(lower, 0.0))[:target_size].sum())
    largest_upper = float(np.sort(upper)[::-1][:target_size].sum())
    if smallest_lower > budget + tolerance:
        causes.append(
            FeasibilityCause(
                "CARDINALITY_MIN_WEIGHTS_EXCEED_BUDGET",
                f"Σ de los {target_size} menores MinWeight {smallest_lower!r} > presupuesto "
                f"{budget!r}",
            )
        )
    if largest_upper < budget - tolerance:
        causes.append(
            FeasibilityCause(
                "CARDINALITY_MAX_WEIGHTS_BELOW_BUDGET",
                f"Σ de los {target_size} mayores MaxWeight {largest_upper!r} < presupuesto "
                f"{budget!r}",
            )
        )
    return tuple(causes)
