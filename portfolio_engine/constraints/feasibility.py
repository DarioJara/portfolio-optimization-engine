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
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

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
        checks = ("BOUNDS", "BUDGET", "RESTRICTED_POLICY", "EXITED_POSITIONS", "GROUPS", "TURNOVER")
        causes.extend(self._bounds(compiled))
        causes.extend(self._budget(compiled))
        causes.extend(self._restricted_policy(compiled))
        causes.extend(self._exited(compiled))
        causes.extend(self._groups(compiled))
        causes.extend(self._turnover(compiled))
        return FeasibilityReport(not causes, tuple(causes), checks)

    def _bounds(self, compiled: CompiledConstraints) -> list[FeasibilityCause]:
        crossed = np.flatnonzero(compiled.lower > compiled.upper + self._tolerance)
        return [
            FeasibilityCause(
                "BOUNDS_CROSSED",
                f"{compiled.asset_ids[i]}: lower {compiled.lower[i]!r} > "
                f"upper {compiled.upper[i]!r}",
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
