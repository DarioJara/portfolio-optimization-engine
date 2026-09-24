"""Estimación de la utilidad de una composición durante la búsqueda (MASTER_SPEC §16, §26; CAN-021).

La búsqueda compara composiciones con la utilidad de media-varianza neta de costes del §16::

    U(w) = μᵀw − λ·wᵀΣw − TC(w)                       (TC en unidades de retorno, enmienda E-03)

``CompositionEvaluator`` es el contrato de evaluación; este módulo aporta el modo
``PROJECTED_WEIGHTS`` (rápido, sin solver): los pesos de la cartera actual se transfieren a la
composición (el peso de los activos que salen se reparte entre los que entran) y se proyectan sobre
las cotas y el presupuesto compilados; después ``refinement_iterations`` pasos de gradiente
proyectado con paso ``1/L``, ``L = 2·λ·λ_max(Σ_C)`` (subgradiente de los costes) y se conserva el
mejor iterado. Como la proyección solo respeta cotas y presupuesto, ``U`` se evalúa en un punto
factible respecto a ellas: es una **cota inferior** de la utilidad óptima de la composición, no un
óptimo. Las restricciones de grupo y de turnover se comprueban después con el
``SolutionValidator`` y se informan en ``CompositionEstimate.violations``.

El modo exacto ``QP_UTILITY`` (un QP pequeño por composición con el motor del Bloque 2) vive en
``frontiers`` (``QPCompositionEvaluator``) y se inyecta; la utilidad estimada nunca se presenta
como resultado final de la optimización.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates.prepared import PreparedComposition
from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.models.composition import CompositionEstimate
from portfolio_engine.models.enums import EvaluationMode
from portfolio_engine.validation.solution_validator import SolutionValidator, ValidationContext

CODE_UNBOUNDED_RANGE = "UNBOUNDED_WEIGHT_RANGE"


@dataclass(frozen=True, slots=True)
class EvaluationRejection:
    """Composición no evaluable (inviable o sin estimación) con las causas explícitas."""

    reasons: tuple[str, ...]
    details: tuple[str, ...]


class CompositionEvaluator(Protocol):
    """Estima la utilidad de una composición para un perfil de aversión al riesgo ``λ``."""

    @property
    def mode(self) -> EvaluationMode:
        """Modo de evaluación (base de la estimación)."""
        ...

    def evaluate(
        self, prepared: PreparedComposition, risk_aversion: float, baseline_utility: float
    ) -> CompositionEstimate | EvaluationRejection:
        """Estimación de ``prepared`` o rechazo con causa; ``baseline_utility`` es ``U`` actual."""
        ...


def current_portfolio_utility(
    mu: npt.NDArray[np.float64],
    sigma: npt.NDArray[np.float64],
    weights: npt.NDArray[np.float64],
    risk_aversion: float,
) -> float:
    """Utilidad ``μᵀw − λ wᵀΣw`` de una cartera con sus pesos (sin costes: ``w = w_current``)."""
    return float(mu @ weights - risk_aversion * (weights @ (sigma @ weights)))


def project_box_budget(
    target: npt.NDArray[np.float64],
    lower: npt.NDArray[np.float64],
    upper: npt.NDArray[np.float64],
    budget: float,
) -> npt.NDArray[np.float64]:
    """Proyección euclídea de ``target`` sobre ``{lower <= w <= upper, Σw = budget}``.

    Exacta: ``w = clip(target − ν, lower, upper)`` con ``ν`` la raíz de la función lineal a trozos
    y decreciente ``Σ clip(target − ν, lower, upper) − budget``, localizada entre los puntos de
    ruptura ``target − upper`` y ``target − lower`` (todas las cotas deben ser finitas y
    ``Σ lower <= budget <= Σ upper``).
    """
    breakpoints = np.sort(np.concatenate((target - upper, target - lower)))
    shifted = target[np.newaxis, :] - breakpoints[:, np.newaxis]
    totals = np.minimum(np.maximum(shifted, lower), upper).sum(axis=1)
    index = int(np.searchsorted(-totals, -budget, side="left"))
    if index <= 0:
        shift = float(breakpoints[0])
    elif index >= breakpoints.size:
        shift = float(breakpoints[-1])
    else:
        above, below = float(totals[index - 1]), float(totals[index])
        span = float(breakpoints[index] - breakpoints[index - 1])
        shift = float(breakpoints[index - 1]) + (above - budget) / (above - below) * span
    return np.asarray(np.minimum(np.maximum(target - shift, lower), upper), dtype=np.float64)


def tightened_bounds(
    compiled: CompiledConstraints,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]] | None:
    """Cotas finitas equivalentes con el presupuesto, o ``None`` si alguna sigue sin acotar.

    ``w_i <= budget − Σ_{j≠i} lower_j`` y ``w_i >= budget − Σ_{j≠i} upper_j`` se deducen del
    presupuesto y no cambian el conjunto factible.
    """
    lower, upper = compiled.lower.copy(), compiled.upper.copy()
    if np.all(np.isfinite(lower)):
        upper = np.minimum(upper, compiled.budget - (lower.sum() - lower))
    if np.all(np.isfinite(upper)):
        lower = np.maximum(lower, compiled.budget - (upper.sum() - upper))
    if not (np.all(np.isfinite(lower)) and np.all(np.isfinite(upper))):
        return None
    return lower, upper


def build_estimate(
    prepared: PreparedComposition,
    weights: npt.NDArray[np.float64],
    risk_aversion: float,
    baseline_utility: float,
    basis: EvaluationMode,
    validator: SolutionValidator,
) -> CompositionEstimate:
    """Estimación de ``prepared`` evaluada en ``weights`` (métricas recalculadas desde los pesos).

    Sin cartera actual o sin costes, ``turnover`` y los costes son ``None`` y la utilidad no
    descuenta costes (MASTER_SPEC §24). Las violaciones proceden del ``SolutionValidator``.
    """
    if prepared.compiled is None:
        raise ValueError("Una composición sin restricciones compiladas no se puede estimar.")
    mu, sigma = prepared.mu, prepared.sigma
    gross = float(mu @ weights)
    variance = float(weights @ (sigma @ weights))
    utility = gross - risk_aversion * variance
    one_off: float | None = None
    cost: float | None = None
    turnover: float | None = None
    model = prepared.cost_model
    if model is not None:
        one_off = float(model.cost_one_off(weights))
        cost = float(model.cost(weights))
        turnover = float(model.turnover(weights))
        utility -= cost
    report = validator.validate(weights, prepared.compiled, ValidationContext(mu, sigma, model))
    return CompositionEstimate(
        composition_hash=prepared.composition_hash,
        risk_aversion=risk_aversion,
        basis=basis,
        weights=weights,
        utility=utility,
        utility_gain=utility - baseline_utility,
        expected_return_gross=gross,
        variance=variance,
        turnover=turnover,
        transaction_cost_one_off=one_off,
        transaction_cost=cost,
        satisfies_constraints=report.is_valid,
        violations=tuple(violation.constraint_id for violation in report.violations),
    )


class MemoizedEvaluator:
    """Memoriza las evaluaciones de **una** generación de candidatos (cache local intra-run).

    La evaluación es una función determinista de ``(composición, λ, utilidad de la cartera
    actual)``, así que una pareja ya evaluada no se repite: el ensamblado final reevaluaba la
    composición de referencia en cada perfil (ya evaluada como raíz de su búsqueda) y las
    finalistas en los perfiles ajenos donde ya habían sido evaluadas. No es la caché de
    resultados entre ejecuciones (§31), que pertenece al Bloque 5: vive y muere con la búsqueda y
    su clave incluye la utilidad de referencia, de modo que un cambio de esta la invalida.
    """

    def __init__(self, inner: CompositionEvaluator) -> None:
        self._inner = inner
        self._memo: dict[tuple[str, float, float], CompositionEstimate | EvaluationRejection] = {}
        self.hits = 0

    @property
    def mode(self) -> EvaluationMode:
        """Modo del evaluador envuelto."""
        return self._inner.mode

    def evaluate(
        self, prepared: PreparedComposition, risk_aversion: float, baseline_utility: float
    ) -> CompositionEstimate | EvaluationRejection:
        """Resultado memorizado si la pareja ya se evaluó; si no, evalúa y lo memoriza."""
        key = (prepared.composition_hash, risk_aversion, baseline_utility)
        found = self._memo.get(key)
        if found is not None:
            self.hits += 1
            return found
        outcome = self._inner.evaluate(prepared, risk_aversion, baseline_utility)
        self._memo[key] = outcome
        return outcome


class ProjectedWeightsEvaluator:
    """Evaluador ``PROJECTED_WEIGHTS``: pesos transferidos, proyectados y refinados."""

    def __init__(self, iterations: int, validator: SolutionValidator) -> None:
        self._iterations = iterations
        self._validator = validator

    @property
    def mode(self) -> EvaluationMode:
        """``PROJECTED_WEIGHTS``."""
        return EvaluationMode.PROJECTED_WEIGHTS

    def evaluate(
        self, prepared: PreparedComposition, risk_aversion: float, baseline_utility: float
    ) -> CompositionEstimate | EvaluationRejection:
        """Estimación de ``prepared`` o rechazo con las causas de inviabilidad."""
        compiled = prepared.compiled
        if not prepared.feasible or compiled is None:
            return EvaluationRejection(prepared.infeasibility_codes, prepared.infeasibility_details)
        bounds = tightened_bounds(compiled)
        if bounds is None:
            return EvaluationRejection(
                (CODE_UNBOUNDED_RANGE,),
                ("Cotas de peso no finitas: use evaluation_mode = QP_UTILITY.",),
            )
        lower, upper = bounds
        weights = project_box_budget(self._transfer_start(compiled), lower, upper, compiled.budget)
        weights = self._refine(prepared, compiled, weights, (lower, upper), risk_aversion)
        return build_estimate(
            prepared, weights, risk_aversion, baseline_utility, self.mode, self._validator
        )

    def _transfer_start(self, compiled: CompiledConstraints) -> npt.NDArray[np.float64]:
        """Pesos actuales en la composición; el peso liberado se reparte entre los entrantes."""
        start = np.array(compiled.current_weights, dtype=np.float64)
        entering = start == 0.0
        if entering.any():
            start[entering] = (compiled.budget - float(start.sum())) / float(entering.sum())
        return start

    def _refine(
        self,
        prepared: PreparedComposition,
        compiled: CompiledConstraints,
        weights: npt.NDArray[np.float64],
        bounds: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]],
        risk_aversion: float,
    ) -> npt.NDArray[np.float64]:
        """Gradiente proyectado (paso ``1/L``) conservando el mejor iterado."""
        if self._iterations == 0:
            return weights
        lipschitz = 2.0 * risk_aversion * float(np.linalg.eigvalsh(prepared.sigma)[-1])
        if not lipschitz > 0:
            return weights
        objective = _NetUtility(prepared, compiled, risk_aversion)
        current = best = weights
        value, gradient = objective.value_and_gradient(current)
        best_value = value
        for _ in range(self._iterations):
            current = project_box_budget(
                current + gradient / lipschitz, bounds[0], bounds[1], compiled.budget
            )
            value, gradient = objective.value_and_gradient(current)
            if value > best_value:
                best, best_value = current, value
        return best


class _NetUtility:
    """``μᵀw − λ wᵀΣw − TC(w)`` y su (sub)gradiente sobre los pesos de una composición.

    Los costes unitarios de la composición se extraen una vez. El coste constante de liquidar los
    activos que salen no depende de ``w`` y se omite: no cambia el mejor iterado (la utilidad
    publicada de la estimación sí lo incluye: ``build_estimate`` usa el modelo de costes).
    """

    __slots__ = ("_buy", "_held", "_lambda", "_mu", "_scale", "_sell", "_sigma")

    def __init__(
        self, prepared: PreparedComposition, compiled: CompiledConstraints, risk_aversion: float
    ) -> None:
        self._mu, self._sigma, self._lambda = prepared.mu, prepared.sigma, risk_aversion
        model = prepared.cost_model
        self._held = compiled.current_weights
        self._buy: npt.NDArray[np.float64] | None = None
        self._sell: npt.NDArray[np.float64] | None = None
        self._scale = 0.0
        if model is not None:
            positions = prepared.alignment.composition_positions
            self._buy = model.buy_costs[positions]
            self._sell = model.sell_costs[positions]
            self._scale = 1.0 / model.horizon_years

    def value_and_gradient(
        self, weights: npt.NDArray[np.float64]
    ) -> tuple[float, npt.NDArray[np.float64]]:
        """Utilidad y subgradiente en ``weights``."""
        covariance_term = self._sigma @ weights
        value = float(self._mu @ weights - self._lambda * (weights @ covariance_term))
        gradient = self._mu - 2.0 * self._lambda * covariance_term
        if self._buy is not None and self._sell is not None:
            delta = weights - self._held
            value -= self._scale * float(
                self._buy @ np.maximum(delta, 0.0) + self._sell @ np.maximum(-delta, 0.0)
            )
            gradient = gradient - self._scale * (
                self._buy * (delta > 0.0) - self._sell * (delta < 0.0)
            )
        return value, np.asarray(gradient, dtype=np.float64)
