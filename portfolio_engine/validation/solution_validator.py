"""Validación independiente de soluciones (MASTER_SPEC §44; VAL-001..005, 007, 009).

El validador recibe **solo pesos** y las restricciones compiladas; no conoce el estado nativo del
solver ni las variables auxiliares del lifting. Cada comprobación se calcula directamente con
NumPy desde los pesos (por ejemplo, el turnover como ``0.5·Σ|w − w0|`` y no desde ``b + s``), de
modo que una solución que el solver marque como resuelta pero que viole el contrato se rechaza:

``FINITE``, ``BUDGET``, ``BOUNDS`` (y ``LONG_ONLY``), ``GROUPS`` (sector, país, clase de activo,
divisa), ``TURNOVER`` (``0.5·(Σ_composición|w − w0| + Σ_retirados|w0|)``), ``RESTRICTED_POLICY``
(evaluada desde la política y ``w_current``, no desde los límites compilados, incluidos los
restringidos retirados de la composición), ``NON_BUYABLE_POLICY`` (E-10: un activo que no puede
comprarse no supera ``w_current``; se evalúa desde ``w_current``, no desde los límites compilados),
``LIQUIDITY_CAP`` (A-11: ``w <= max(w_current, capacidad ADV/NAV)``, desde la capacidad y
``w_current`` de la regla, no desde los límites compilados), ``RETURN_TARGET`` (bruto o neto)
y ``VARIANCE``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.costs.transaction_cost_model import TransactionCostModel
from portfolio_engine.models.enums import AdvUnit, CostTreatment, RestrictedExistingPositionPolicy
from portfolio_engine.models.solution import ValidationReport, Violation
from portfolio_engine.validation.tolerances import ReturnTarget, ValidationTolerances

CHECK_FINITE = "FINITE"
CHECK_BUDGET = "BUDGET"
CHECK_BOUNDS = "BOUNDS"
CHECK_LONG_ONLY = "LONG_ONLY"
CHECK_GROUPS = "GROUPS"
CHECK_TURNOVER = "TURNOVER"
CHECK_RESTRICTED = "RESTRICTED_POLICY"
CHECK_NON_BUYABLE = "NON_BUYABLE_POLICY"
CHECK_LIQUIDITY = "LIQUIDITY_CAP"
CHECK_TARGET = "RETURN_TARGET"
CHECK_VARIANCE = "VARIANCE"


@dataclass(frozen=True, eq=False, slots=True)
class ValidationContext:
    """Datos económicos necesarios para validar retorno objetivo y varianza."""

    mu: npt.NDArray[np.float64]
    sigma: npt.NDArray[np.float64]
    cost_model: TransactionCostModel | None


class _Collector:
    """Acumula violaciones por encima de tolerancia y la mayor violación absoluta observada."""

    def __init__(self) -> None:
        self.violations: list[Violation] = []
        self.max_violation = 0.0
        self.checks: list[str] = []

    def record(
        self, check: str, name: str, value: float, bound: float, excess: float, tolerance: float
    ) -> None:
        """Registra una comprobación con su exceso (``<= 0`` = cumple)."""
        magnitude = max(excess, 0.0)
        self.max_violation = max(self.max_violation, magnitude)
        if magnitude > tolerance:
            self.violations.append(Violation(f"{check}:{name}", value, bound, magnitude))


class SolutionValidator:
    """Valida un vector de pesos contra las restricciones compiladas y el retorno objetivo."""

    def __init__(self, tolerances: ValidationTolerances) -> None:
        self._tol = tolerances

    def validate(
        self,
        weights: npt.ArrayLike,
        compiled: CompiledConstraints,
        context: ValidationContext,
        target: ReturnTarget | None = None,
    ) -> ValidationReport:
        """Informe de validez de ``weights`` (pesos de la composición, orden de ``compiled``)."""
        vector = np.asarray(weights, dtype=np.float64)
        collector = _Collector()
        collector.checks.append(CHECK_FINITE)
        if vector.shape != (compiled.size,) or not np.all(np.isfinite(vector)):
            collector.violations.append(
                Violation(f"{CHECK_FINITE}:weights", float("nan"), 0.0, float("inf"))
            )
            return ValidationReport(
                False, float("inf"), tuple(collector.violations), tuple(collector.checks)
            )
        self._budget(vector, compiled, collector)
        self._bounds(vector, compiled, collector)
        self._groups(vector, compiled, collector)
        self._turnover(vector, compiled, collector)
        self._restricted(vector, compiled, collector)
        self._non_buyable(vector, compiled, collector)
        self._liquidity(vector, compiled, collector)
        self._variance(vector, context, collector)
        if target is not None:
            self._target(vector, context, target, collector)
        return ValidationReport(
            not collector.violations,
            collector.max_violation,
            tuple(collector.violations),
            tuple(collector.checks),
        )

    def _budget(
        self, w: npt.NDArray[np.float64], compiled: CompiledConstraints, out: _Collector
    ) -> None:
        out.checks.append(CHECK_BUDGET)
        total = float(w.sum())
        out.record(
            CHECK_BUDGET,
            "sum",
            total,
            compiled.budget,
            abs(total - compiled.budget),
            self._tol.budget,
        )

    def _bounds(
        self, w: npt.NDArray[np.float64], compiled: CompiledConstraints, out: _Collector
    ) -> None:
        out.checks.extend([CHECK_BOUNDS, CHECK_LONG_ONLY])
        tol = self._tol.bound
        below = compiled.lower - w
        above = w - compiled.upper
        negative = -w if compiled.long_only else np.full(w.shape, -np.inf)
        worst = max(float(below.max()), float(above.max()), float(negative.max()), 0.0)
        out.max_violation = max(out.max_violation, worst)
        # solo se recorren en orden los activos con alguna violación; el resto no registra nada
        for index in np.flatnonzero((below > tol) | (above > tol) | (negative > tol)).tolist():
            asset_id, value = compiled.asset_ids[index], float(w[index])
            low, high = float(compiled.lower[index]), float(compiled.upper[index])
            out.record(CHECK_BOUNDS, f"{asset_id}:lower", value, low, low - value, tol)
            out.record(CHECK_BOUNDS, f"{asset_id}:upper", value, high, value - high, tol)
            if compiled.long_only:
                out.record(CHECK_LONG_ONLY, asset_id, value, 0.0, -value, tol)

    def _groups(
        self, w: npt.NDArray[np.float64], compiled: CompiledConstraints, out: _Collector
    ) -> None:
        out.checks.append(CHECK_GROUPS)
        for row, label in enumerate(compiled.group_labels):
            total = float(compiled.group_matrix[row] @ w)
            low, high = float(compiled.group_min[row]), float(compiled.group_max[row])
            out.record(CHECK_GROUPS, f"{label}:min", total, low, low - total, self._tol.constraint)
            out.record(
                CHECK_GROUPS, f"{label}:max", total, high, total - high, self._tol.constraint
            )

    def _turnover(
        self, w: npt.NDArray[np.float64], compiled: CompiledConstraints, out: _Collector
    ) -> None:
        out.checks.append(CHECK_TURNOVER)
        if compiled.max_turnover is None:
            return
        removed = sum(abs(position.current_weight) for position in compiled.exited)
        value = float(0.5 * (np.abs(w - compiled.current_weights).sum() + removed))
        out.record(
            CHECK_TURNOVER,
            "max",
            value,
            compiled.max_turnover,
            value - compiled.max_turnover,
            self._tol.constraint,
        )

    def _restricted(
        self, w: npt.NDArray[np.float64], compiled: CompiledConstraints, out: _Collector
    ) -> None:
        out.checks.append(CHECK_RESTRICTED)
        tol = self._tol.bound
        for rule in compiled.restricted_rules:
            value = float(w[rule.position])
            held = rule.current_weight
            name = rule.asset_id
            if not rule.is_held or rule.policy is RestrictedExistingPositionPolicy.FORCE_LIQUIDATE:
                out.record(CHECK_RESTRICTED, f"{name}:zero", value, 0.0, abs(value), tol)
            elif rule.policy is RestrictedExistingPositionPolicy.FREEZE_WEIGHT:
                out.record(CHECK_RESTRICTED, f"{name}:frozen", value, held, abs(value - held), tol)
            else:
                out.record(CHECK_RESTRICTED, f"{name}:no_increase", value, held, value - held, tol)
        for position in compiled.exited:
            if position.policy is RestrictedExistingPositionPolicy.FREEZE_WEIGHT:
                held = position.current_weight
                out.record(
                    CHECK_RESTRICTED,
                    f"{position.asset_id}:frozen_exited",
                    0.0,
                    held,
                    abs(held),
                    tol,
                )

    def _non_buyable(
        self, w: npt.NDArray[np.float64], compiled: CompiledConstraints, out: _Collector
    ) -> None:
        """E-10: un activo no comprable no supera su peso actual (``0`` si no está)."""
        out.checks.append(CHECK_NON_BUYABLE)
        for rule in compiled.non_buyable_rules:
            value = float(w[rule.position])
            held = rule.current_weight
            name = f"{rule.asset_id}:no_increase" if rule.is_held else f"{rule.asset_id}:no_entry"
            out.record(CHECK_NON_BUYABLE, name, value, held, value - held, self._tol.bound)

    def _liquidity(
        self, w: npt.NDArray[np.float64], compiled: CompiledConstraints, out: _Collector
    ) -> None:
        """A-11: ``w <= max(w_current, capacidad)``; una posición que ya la supera no crece."""
        out.checks.append(CHECK_LIQUIDITY)
        for rule in compiled.liquidity_rules:
            value = float(w[rule.position])
            # contrato de datos comprobado de nuevo desde la regla (independiente del compilador)
            contract_ok = (
                rule.adv_unit is AdvUnit.NOTIONAL_PER_DAY
                and bool(rule.adv_currency)
                and bool(rule.nav_currency)
                and (rule.adv_currency == rule.nav_currency or (rule.fx_rate or 0.0) > 0.0)
                and np.isfinite(rule.capacity)
                and rule.capacity >= 0.0
            )
            out.record(
                CHECK_LIQUIDITY,
                f"{rule.asset_id}:data_contract",
                0.0 if contract_ok else 1.0,
                0.0,
                0.0 if contract_ok else float("inf"),
                0.0,
            )
            limit = max(rule.current_weight, rule.capacity)
            name = f"{rule.asset_id}:{'no_increase_above_capacity' if rule.is_held else 'capacity'}"
            out.record(CHECK_LIQUIDITY, name, value, limit, value - limit, self._tol.bound)

    def _variance(
        self, w: npt.NDArray[np.float64], context: ValidationContext, out: _Collector
    ) -> None:
        out.checks.append(CHECK_VARIANCE)
        variance = float(w @ context.sigma @ w)
        excess = float("inf") if not np.isfinite(variance) else -variance
        out.record(CHECK_VARIANCE, "non_negative", variance, 0.0, excess, self._tol.variance)

    def _target(
        self,
        w: npt.NDArray[np.float64],
        context: ValidationContext,
        target: ReturnTarget,
        out: _Collector,
    ) -> None:
        out.checks.append(CHECK_TARGET)
        achieved = float(context.mu @ w)
        if target.treatment is CostTreatment.NET:
            if context.cost_model is None:
                out.record(CHECK_TARGET, "net_without_costs", 0.0, 0.0, float("inf"), 0.0)
                return
            achieved -= float(context.cost_model.cost(w))
        out.record(
            CHECK_TARGET,
            target.treatment.value.lower(),
            achieved,
            target.value,
            target.value - achieved,
            self._tol.constraint,
        )
