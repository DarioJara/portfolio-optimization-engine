"""Formulaciones multiescenario de solución única (MASTER_SPEC §54; SCN-005, SCN-006, SCN-007).

Distinción esencial (no son equivalentes):

* ``SCENARIO_INDEPENDENT`` resuelve **un problema por escenario** y devuelve una solución distinta
  para cada ``ScenarioID`` (lo orquesta :mod:`portfolio_engine.scenarios`; no es una formulación).
* Las tres formulaciones de este módulo devuelven **una única cartera** que responde
  simultáneamente a varios escenarios:

  ``ExpectedScenarioUtility`` (QP)::

      maximize   Σ_s p_s (μ_sᵀw − λ wᵀΣ_s w) − Σ_s p_s TC_s(w)
                 = μ̄ᵀw − λ wᵀΣ̄w − TC̄(w),     μ̄ = Σ p_s μ_s,  Σ̄ = Σ p_s Σ_s,  c̄ = Σ p_s c_s

  Es la utilidad esperada de la utilidad cuadrática **de cada escenario**; ``Σ̄`` no es la varianza
  de la mezcla (que añadiría la dispersión entre las medias de los escenarios).

  ``WorstCase`` (SOCP)::

      maximize   t     s.a.  t <= μ_sᵀw − λ wᵀΣ_s w − TC_s(w)   ∀ s

  cada restricción es una cuadrática convexa ``λ‖L_sᵀw‖² <= μ_sᵀw − TC_s(w) − t`` escrita como cono
  de segundo orden (``‖z‖² <= h`` ⇔ ``‖(2z, h−1)‖ <= h+1``). En el óptimo ``t* = min_s U_s(w*)``.

  ``BaseWithStressConstraints`` (QP o SOCP)::

      maximize   μ_bᵀw − λ wᵀΣ_b w − TC_b(w)                   (escenario BASE)
      s.a.       √(wᵀΣ_s w) <= σ_s            (cono)          para cada escenario de estrés con
                 μ_sᵀw − TC_s(w) >= r_s       (lineal)         límites declarados

  Solo con límites de retorno el problema sigue siendo un QP (OSQP); un límite de volatilidad de
  estrés lo convierte en SOCP (Clarabel).

Las probabilidades no se suponen iguales ni se renormalizan: deben venir declaradas y sumar 1.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.exceptions import ScenarioError, UnsupportedCombinationError
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.optimizers.formulations.conic import (
    PSDFactor,
    quadratic_cone,
    volatility_cone,
)
from portfolio_engine.optimizers.formulations.model_builder import ExtendedProblem, ModelBuilder
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.formulations.volatility import VolatilityCap, add_volatility_cap


@dataclass(frozen=True, eq=False, slots=True)
class ScenarioSlice:
    """Datos de un escenario sobre la composición: ``μ_s``, ``Σ_s`` y costes ``c_s``.

    ``buy_costs``, ``sell_costs`` (unitarios, composición) y ``exit_cost_one_off`` (``K_E,s``,
    liquidación de los activos retirados) son ``None``/``0`` si no hay costes (``GROSS``).
    """

    scenario_id: str
    mu: npt.NDArray[np.float64]
    sigma: npt.NDArray[np.float64]
    buy_costs: npt.NDArray[np.float64] | None
    sell_costs: npt.NDArray[np.float64] | None
    exit_cost_one_off: float


@dataclass(frozen=True, eq=False, slots=True)
class StressSpec:
    """Escenario de estrés y los límites que debe cumplir la solución única bajo él."""

    slice: ScenarioSlice
    factor: PSDFactor | None
    max_volatility: float | None
    min_return: float | None

    def __post_init__(self) -> None:
        if self.max_volatility is None and self.min_return is None:
            raise UnsupportedCombinationError(
                f"El escenario de estrés {self.slice.scenario_id} no declara ningún límite."
            )
        if self.max_volatility is not None and self.factor is None:
            raise UnsupportedCombinationError("Un límite de volatilidad exige el factor de Σ_s.")


def validated_probabilities(
    probabilities: Sequence[float | None], tolerance: float
) -> npt.NDArray[np.float64]:
    """Probabilidades declaradas, no negativas, con ``|Σp − 1| <= tolerance`` (sin normalizar)."""
    if any(p is None for p in probabilities):
        raise ScenarioError(
            "Faltan probabilidades: no se suponen iguales; declare la de cada escenario."
        )
    values = np.array([float(p) for p in probabilities if p is not None], dtype=np.float64)
    if values.size == 0 or not np.all(np.isfinite(values)) or np.any(values < 0.0):
        raise ScenarioError("Las probabilidades deben ser finitas y no negativas.")
    if abs(float(values.sum()) - 1.0) > tolerance:
        raise ScenarioError(
            f"Las probabilidades suman {float(values.sum()):.12g}, no 1 (tolerancia {tolerance})."
        )
    return values


def expected_moments(
    slices: Sequence[ScenarioSlice], probabilities: npt.NDArray[np.float64]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """``μ̄ = Σ p_s μ_s`` y ``Σ̄ = Σ p_s Σ_s`` (SCN-005)."""
    if len(slices) != probabilities.shape[0] or not slices:
        raise ScenarioError("Un escenario por probabilidad.")
    mu = np.zeros_like(slices[0].mu)
    sigma = np.zeros_like(slices[0].sigma)
    for scenario, probability in zip(slices, probabilities.tolist(), strict=True):
        mu += probability * scenario.mu
        sigma += probability * scenario.sigma
    return mu, (sigma + sigma.T) / 2.0


def _net_return_terms(
    scenario: ScenarioSlice, base: BuiltProblem, n_variables: int
) -> tuple[npt.NDArray[np.float64], float]:
    """Retorno del escenario como función afín de ``x``: ``aᵀx + c`` (neto en NET, bruto si no)."""
    n = base.n_weights
    coefficients = np.zeros(n_variables)
    coefficients[:n] = scenario.mu
    constant = 0.0
    if base.cost_in_objective:
        if scenario.buy_costs is None or scenario.sell_costs is None or base.horizon_years is None:
            raise UnsupportedCombinationError(
                f"{scenario.scenario_id}: NET exige costes del escenario y horizonte."
            )
        scale = 1.0 / base.horizon_years
        coefficients[n : n + n] = -scenario.buy_costs * scale
        coefficients[n + n : n + n + n] = -scenario.sell_costs * scale
        constant = -scenario.exit_cost_one_off * scale
    return coefficients, constant


def _check_risk_aversion(risk_aversion: float) -> float:
    if not math.isfinite(risk_aversion) or risk_aversion <= 0.0:
        raise UnsupportedCombinationError("risk_aversion debe ser finito y > 0.")
    return float(risk_aversion)


def build_worst_case_problem(
    inputs: CompositionInputs,
    cost_treatment: CostTreatment,
    slices: Sequence[ScenarioSlice],
    factors: Sequence[PSDFactor],
    risk_aversion: float,
    volatility_cap: VolatilityCap | None = None,
) -> tuple[ExtendedProblem, BuiltProblem]:
    """SOCP ``max t`` s.a. ``t <= U_s(w)`` para todo escenario (SCN-006)."""
    if len(slices) < 1 or len(slices) != len(factors):
        raise ScenarioError("Un factor de Σ_s por escenario y al menos un escenario.")
    aversion = _check_risk_aversion(risk_aversion)
    base = build_fixed_composition_problem(inputs, cost_treatment, quadratic=False)
    builder = ModelBuilder(base.problem)
    t_index = builder.add_variables(1)
    # el objetivo del problema base (retorno máximo de BASE) NO se conserva: solo ``max t``
    epigraph = np.zeros(builder.n_variables)
    epigraph[t_index] = -1.0
    builder.set_objective(None, epigraph)
    total = builder.n_variables
    columns = np.arange(base.n_weights, dtype=np.int64)
    for scenario, factor in zip(slices, factors, strict=True):
        affine, constant = _net_return_terms(scenario, base, total)
        height = affine / aversion
        height[t_index] = -1.0 / aversion
        cone = quadratic_cone(factor, columns, total, height, constant / aversion)
        builder.add_cone(
            f"worst_case:{scenario.scenario_id}",
            cone.matrix,
            cone.offset,
            cone.height,
            cone.constant,
        )
    add_volatility_cap(builder, volatility_cap, base.n_weights)
    problem = builder.finalize("worst_case_scenarios")
    extended = ExtendedProblem(
        problem=problem,
        n_weights=base.n_weights,
        n_base_variables=base.problem.n_variables,
        roles={"t": t_index},
        description="SOCP: max t s.a. t <= μ_sᵀw − λ wᵀΣ_s w − TC_s(w) para todo s",
    )
    return extended, base


def build_base_with_stress_problem(
    inputs: CompositionInputs,
    cost_treatment: CostTreatment,
    risk_aversion: float,
    stresses: Sequence[StressSpec],
    volatility_cap: VolatilityCap | None = None,
) -> tuple[ExtendedProblem, BuiltProblem]:
    """Utilidad del escenario BASE (``inputs``) con los límites de estrés añadidos (SCN-007)."""
    if not stresses:
        raise UnsupportedCombinationError(
            "BaseWithStressConstraints sin ningún límite de estrés equivaldría al escenario BASE."
        )
    aversion = _check_risk_aversion(risk_aversion)
    base = build_fixed_composition_problem(inputs, cost_treatment, quadratic=True)
    builder = ModelBuilder(base.problem)
    builder.set_objective(base.problem.P, base.q_risk_aversion(1.0 / aversion))
    total = builder.n_variables
    columns = np.arange(base.n_weights, dtype=np.int64)
    for spec in stresses:
        name = spec.slice.scenario_id
        if spec.max_volatility is not None and spec.factor is not None:
            if not math.isfinite(spec.max_volatility) or spec.max_volatility <= 0.0:
                raise UnsupportedCombinationError(f"{name}: max_volatility debe ser > 0.")
            cone = volatility_cone(spec.factor, columns, total, spec.max_volatility)
            builder.add_cone(
                f"stress_volatility:{name}", cone.matrix, cone.offset, cone.height, cone.constant
            )
        if spec.min_return is not None:
            if not math.isfinite(spec.min_return):
                raise UnsupportedCombinationError(f"{name}: min_return debe ser finito.")
            affine, constant = _net_return_terms(spec.slice, base, total)
            builder.add_rows(
                sparse.csr_matrix(affine.reshape(1, -1)),
                np.full(1, spec.min_return - constant),
                np.full(1, np.inf),
            )
    add_volatility_cap(builder, volatility_cap, base.n_weights)
    problem = builder.finalize("base_with_stress_constraints")
    extended = ExtendedProblem(
        problem=problem,
        n_weights=base.n_weights,
        n_base_variables=base.problem.n_variables,
        roles={},
        description="Utilidad BASE con límites de volatilidad y retorno bajo escenarios de estrés",
    )
    return extended, base
