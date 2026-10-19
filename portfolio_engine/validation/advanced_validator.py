"""Validación independiente de las formulaciones del Bloque 4 (MASTER_SPEC §44; VAL-003, VAL-007).

Extiende :class:`SolutionValidator` **sin tocarlo**: primero pasa por él (presupuesto, límites,
grupos, turnover, política de restringidos, no comprables, ADV/NAV, retorno objetivo, varianza) y
después comprueba, solo desde los pesos y los datos económicos (nunca desde el estado ni las
variables del solver):

* ``VOLATILITY_LIMIT``: ``√(wᵀΣw) <= σ_max`` con la ``Σ`` del escenario indicado;
* ``CVAR_LIMIT``: ``CVaR_β(w)`` (cálculo directo de :mod:`portfolio_engine.metrics.cvar_metric`,
  no la formulación de Rockafellar-Uryasev) ``<= MaxCVaR`` en el horizonte declarado;
* ``SHARPE``: exceso de retorno ``(μ − rf)ᵀw`` (neto de costes en ``NET``) positivo, volatilidad no
  nula y coherencia del ratio recalculado con el que implica el solver (``1/r*``);
* ``SCENARIO:<id>``: las restricciones compiladas de **cada** escenario (overrides de
  ``constraints_s``), el límite de volatilidad de estrés y el retorno mínimo bajo ese escenario;
* ``CARDINALITY``: integridad de ``z``, ``Σz = K``, nuevos activos y swaps, pertenencia obligatoria,
  semicontinuidad ``l_i z_i <= w_i <= u_i z_i`` y ``w_i = 0`` si ``z_i = 0``.

No relaja ninguna tolerancia económica ni promueve un estado ``OPTIMAL_INACCURATE``: la decisión de
aceptar el estado del solver pertenece a quien llama; este validador solo dice si los pesos cumplen.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.metrics.cvar_metric import conditional_value_at_risk, portfolio_losses
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.models.solution import ValidationReport, Violation
from portfolio_engine.validation.solution_validator import SolutionValidator, ValidationContext
from portfolio_engine.validation.tolerances import ReturnTarget, ValidationTolerances

CHECK_VOLATILITY_LIMIT = "VOLATILITY_LIMIT"
CHECK_CVAR_LIMIT = "CVAR_LIMIT"
CHECK_SHARPE = "SHARPE"
CHECK_SCENARIO = "SCENARIO"
CHECK_CARDINALITY = "CARDINALITY"

#: ``record(check, name, value, bound, excess, tolerance)``: registra una comprobación.
_Record = Callable[[str, str, float, float, float, float], None]


@dataclass(frozen=True, eq=False, slots=True)
class VolatilityLimitCheck:
    """``√(wᵀΣw) <= limit`` con la covarianza ``sigma`` (de la composición)."""

    sigma: npt.NDArray[np.float64]
    limit: float
    label: str


@dataclass(frozen=True, eq=False, slots=True)
class CVaRCheck:
    """``CVaR_β(w) <= max_cvar`` sobre los escenarios de retorno ``returns`` (``T × n``).

    ``max_cvar`` está en el horizonte de ``horizon_factor``
    (``CVaR_horizonte = factor·CVaR_periodo``).
    """

    returns: npt.NDArray[np.float64]
    probabilities: npt.NDArray[np.float64]
    confidence_level: float
    horizon_factor: float
    max_cvar: float | None


@dataclass(frozen=True, eq=False, slots=True)
class SharpeCheck:
    """Comprobación de una solución de Max Sharpe: exceso positivo y ratio coherente.

    ``claimed_sharpe`` es el ratio que implica el óptimo del solver (``1/r*``; ``None`` = no se
    contrasta). ``min_excess_return`` y ``agreement_tolerance`` proceden de ``SharpeConfig``.
    """

    risk_free_rate: float
    treatment: CostTreatment
    min_excess_return: float
    agreement_tolerance: float
    claimed_sharpe: float | None
    zero_volatility_tolerance: float


@dataclass(frozen=True, eq=False, slots=True)
class ScenarioCheck:
    """Restricciones que la solución debe cumplir **bajo un escenario** concreto.

    ``compiled`` son las restricciones compiladas del escenario (``constraints_s``);
    ``context`` su ``μ_s``/``Σ_s``/costes; ``max_volatility`` y ``min_return`` los límites de
    estrés (``min_return`` en el tratamiento ``treatment``).
    """

    scenario_id: str
    compiled: CompiledConstraints
    context: ValidationContext
    max_volatility: float | None
    min_return: float | None
    treatment: CostTreatment


@dataclass(frozen=True, eq=False, slots=True)
class CardinalityCheck:
    """Comprobación de una solución ``EXACT_MIP``: ``z``, cardinalidad, nuevos y swaps."""

    z: npt.NDArray[np.float64]
    integrality_tolerance: float
    target_size: int | None
    max_new_assets: int | None
    max_swaps: int | None
    mandatory: tuple[int, ...]


@dataclass(frozen=True, eq=False, slots=True)
class AdvancedChecks:
    """Comprobaciones adicionales de una solución (todas opcionales, cada una explícita)."""

    volatility: tuple[VolatilityLimitCheck, ...] = ()
    cvar: CVaRCheck | None = None
    sharpe: SharpeCheck | None = None
    scenarios: tuple[ScenarioCheck, ...] = ()
    cardinality: CardinalityCheck | None = None


class AdvancedSolutionValidator:
    """``SolutionValidator`` más las comprobaciones del Bloque 4."""

    def __init__(self, tolerances: ValidationTolerances) -> None:
        self._tol = tolerances
        self._base = SolutionValidator(tolerances)

    def validate(
        self,
        weights: npt.ArrayLike,
        compiled: CompiledConstraints,
        context: ValidationContext,
        checks: AdvancedChecks,
        target: ReturnTarget | None = None,
    ) -> ValidationReport:
        """Informe combinado: validador base y comprobaciones avanzadas."""
        base = self._base.validate(weights, compiled, context, target)
        vector = np.asarray(weights, dtype=np.float64)
        if vector.shape != (compiled.size,) or not np.all(np.isfinite(vector)):
            return base
        violations: list[Violation] = list(base.violations)
        names: list[str] = list(base.checks)
        worst = base.max_violation

        def record(
            check: str, name: str, value: float, bound: float, excess: float, tol: float
        ) -> None:
            nonlocal worst
            magnitude = max(excess, 0.0)
            worst = max(worst, magnitude)
            if magnitude > tol:
                violations.append(Violation(f"{check}:{name}", value, bound, magnitude))

        for item in checks.volatility:
            names.append(CHECK_VOLATILITY_LIMIT)
            volatility = math.sqrt(max(float(vector @ item.sigma @ vector), 0.0))
            record(
                CHECK_VOLATILITY_LIMIT,
                item.label,
                volatility,
                item.limit,
                volatility - item.limit,
                self._tol.constraint,
            )
        if checks.cvar is not None:
            names.append(CHECK_CVAR_LIMIT)
            self._cvar(vector, checks.cvar, record)
        if checks.sharpe is not None:
            names.append(CHECK_SHARPE)
            self._sharpe(vector, context, checks.sharpe, record)
        for scenario in checks.scenarios:
            names.append(f"{CHECK_SCENARIO}:{scenario.scenario_id}")
            self._scenario(vector, scenario, violations, record)
        if checks.cardinality is not None:
            names.append(CHECK_CARDINALITY)
            self._cardinality(vector, compiled, checks.cardinality, record)
        return ValidationReport(not violations, worst, tuple(violations), tuple(names))

    def validate_cardinality(
        self,
        weights: npt.ArrayLike,
        compiled: CompiledConstraints,
        check: CardinalityCheck,
    ) -> ValidationReport:
        """Solo las comprobaciones de cardinalidad sobre el universo del MIQP (``z``).

        Los pesos de un universo ``EXACT_MIP`` incluyen activos que no pertenecen a la composición
        (``w_i = 0`` con ``z_i = 0``); no cumplen las cotas de una composición fija, por lo que el
        resto de restricciones se valida sobre la composición elegida con :meth:`validate`.
        """
        vector = np.asarray(weights, dtype=np.float64)
        violations: list[Violation] = []
        worst = 0.0

        def record(
            check_name: str, name: str, value: float, bound: float, excess: float, tol: float
        ) -> None:
            nonlocal worst
            magnitude = max(excess, 0.0)
            worst = max(worst, magnitude)
            if magnitude > tol:
                violations.append(Violation(f"{check_name}:{name}", value, bound, magnitude))

        if vector.shape != (compiled.size,) or not np.all(np.isfinite(vector)):
            record(CHECK_CARDINALITY, "weights", math.nan, 0.0, math.inf, 0.0)
        else:
            self._cardinality(vector, compiled, check, record)
        return ValidationReport(not violations, worst, tuple(violations), (CHECK_CARDINALITY,))

    def _cvar(self, w: npt.NDArray[np.float64], check: CVaRCheck, record: _Record) -> None:
        losses = portfolio_losses(check.returns, w)
        value = conditional_value_at_risk(losses, check.probabilities, check.confidence_level)
        horizon = check.horizon_factor * value
        record(
            CHECK_CVAR_LIMIT,
            "finite",
            horizon,
            0.0,
            0.0 if math.isfinite(horizon) else math.inf,
            0.0,
        )
        if check.max_cvar is not None:
            record(
                CHECK_CVAR_LIMIT,
                "max",
                horizon,
                check.max_cvar,
                horizon - check.max_cvar,
                self._tol.constraint,
            )

    def _sharpe(
        self,
        w: npt.NDArray[np.float64],
        context: ValidationContext,
        check: SharpeCheck,
        record: _Record,
    ) -> None:
        excess = float(context.mu @ w) - check.risk_free_rate * float(w.sum())
        if check.treatment is CostTreatment.NET:
            if context.cost_model is None:
                record(CHECK_SHARPE, "net_without_costs", 0.0, 0.0, math.inf, 0.0)
                return
            excess -= float(context.cost_model.cost(w))
        record(
            CHECK_SHARPE,
            "positive_excess",
            excess,
            check.min_excess_return,
            check.min_excess_return - excess,
            0.0,
        )
        volatility = math.sqrt(max(float(w @ context.sigma @ w), 0.0))
        record(
            CHECK_SHARPE,
            "defined_volatility",
            volatility,
            check.zero_volatility_tolerance,
            check.zero_volatility_tolerance - volatility,
            0.0,
        )
        if check.claimed_sharpe is not None and volatility > check.zero_volatility_tolerance:
            recomputed = excess / volatility
            gap = abs(recomputed - check.claimed_sharpe) / max(
                abs(recomputed), abs(check.claimed_sharpe)
            )
            record(
                CHECK_SHARPE,
                "consistent_ratio",
                recomputed,
                check.claimed_sharpe,
                gap - check.agreement_tolerance,
                0.0,
            )

    def _scenario(
        self,
        w: npt.NDArray[np.float64],
        check: ScenarioCheck,
        violations: list[Violation],
        record: _Record,
    ) -> None:
        scenario_report = self._base.validate(w, check.compiled, check.context)
        for item in scenario_report.violations:
            violations.append(
                Violation(
                    f"{CHECK_SCENARIO}:{check.scenario_id}:{item.constraint_id}",
                    item.value,
                    item.bound,
                    item.violation,
                )
            )
        if check.max_volatility is not None:
            volatility = math.sqrt(max(float(w @ check.context.sigma @ w), 0.0))
            record(
                CHECK_SCENARIO,
                f"{check.scenario_id}:max_volatility",
                volatility,
                check.max_volatility,
                volatility - check.max_volatility,
                self._tol.constraint,
            )
        if check.min_return is not None:
            achieved = float(check.context.mu @ w)
            if check.treatment is CostTreatment.NET and check.context.cost_model is not None:
                achieved -= float(check.context.cost_model.cost(w))
            record(
                CHECK_SCENARIO,
                f"{check.scenario_id}:min_return",
                achieved,
                check.min_return,
                check.min_return - achieved,
                self._tol.constraint,
            )

    def _cardinality(
        self,
        w: npt.NDArray[np.float64],
        compiled: CompiledConstraints,
        check: CardinalityCheck,
        record: _Record,
    ) -> None:
        z = check.z
        if z.shape != w.shape or not np.all(np.isfinite(z)):
            record(CHECK_CARDINALITY, "z_shape", 0.0, 0.0, math.inf, 0.0)
            return
        distance = np.abs(z - np.round(z))
        record(
            CHECK_CARDINALITY,
            "integrality",
            float(distance.max(initial=0.0)),
            0.0,
            float(distance.max(initial=0.0)),
            check.integrality_tolerance,
        )
        member = np.round(z) > 0.5
        record(
            CHECK_CARDINALITY,
            "binary_range",
            float(z.min()),
            0.0,
            max(-float(z.min()), float(z.max()) - 1.0),
            check.integrality_tolerance,
        )
        if check.target_size is not None:
            size = float(member.sum())
            record(
                CHECK_CARDINALITY,
                "size",
                size,
                float(check.target_size),
                abs(size - check.target_size),
                0.0,
            )
        held = compiled.current_weights > 0.0
        new = float((member & ~held).sum())
        removed = float((~member & held).sum())
        if check.max_new_assets is not None:
            record(
                CHECK_CARDINALITY,
                "max_new_assets",
                new,
                float(check.max_new_assets),
                new - check.max_new_assets,
                0.0,
            )
        if check.max_swaps is not None:
            swaps = max(new, removed)
            record(
                CHECK_CARDINALITY,
                "max_swaps",
                swaps,
                float(check.max_swaps),
                swaps - check.max_swaps,
                0.0,
            )
        for position in check.mandatory:
            record(
                CHECK_CARDINALITY,
                f"mandatory:{compiled.asset_ids[position]}",
                float(member[position]),
                1.0,
                1.0 - float(member[position]),
                0.0,
            )
        tol = self._tol.bound
        outside = np.where(member, 0.0, np.abs(w))
        record(
            CHECK_CARDINALITY,
            "weight_outside_composition",
            float(outside.max(initial=0.0)),
            0.0,
            float(outside.max(initial=0.0)),
            tol,
        )
        below = np.where(member, compiled.lower - w, 0.0)
        above = np.where(member, w - compiled.upper, 0.0)
        record(
            CHECK_CARDINALITY,
            "semicontinuous_lower",
            float(below.max(initial=0.0)),
            0.0,
            float(below.max(initial=0.0)),
            tol,
        )
        record(
            CHECK_CARDINALITY,
            "semicontinuous_upper",
            float(above.max(initial=0.0)),
            0.0,
            float(above.max(initial=0.0)),
            tol,
        )


def combined_checks(*parts: AdvancedChecks) -> AdvancedChecks:
    """Une varias :class:`AdvancedChecks` (las comprobaciones únicas no pueden duplicarse)."""
    volatility: list[VolatilityLimitCheck] = []
    scenarios: list[ScenarioCheck] = []
    cvar = sharpe = cardinality = None
    for part in parts:
        volatility.extend(part.volatility)
        scenarios.extend(part.scenarios)
        cvar = part.cvar if part.cvar is not None else cvar
        sharpe = part.sharpe if part.sharpe is not None else sharpe
        cardinality = part.cardinality if part.cardinality is not None else cardinality
    return AdvancedChecks(tuple(volatility), cvar, sharpe, tuple(scenarios), cardinality)
