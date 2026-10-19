"""Control de volatilidad ``√(wᵀΣw) <= VolatilityLimit`` (MASTER_SPEC §21; CON-004, OPT-010).

El límite se formula como un cono de segundo orden ``‖Lᵀw‖₂ <= σ_max`` con ``Σ = L Lᵀ`` (P8 de
``ARCHITECTURE.md`` §9.2): **no** se sustituye por la QP ``wᵀΣw <= σ²_max`` ni se enruta a OSQP.
Las restricciones de la composición (presupuesto, límites, grupos, turnover, política de
restringidos, costes NET con liquidación de los activos retirados) son las del Bloque 2, copiadas
tal cual: la formulación solo añade el cono y cambia el objetivo.

Objetivos admitidos:

* ``risk_aversion = None``: maximizar el retorno (bruto, o neto de costes en ``NET``) sujeto al
  límite: ``min qᵀx`` con ``q = [−μ; c_b/H; c_s/H]`` (un SOCP con objetivo lineal);
* ``risk_aversion = λ``: la utilidad ``μᵀw − TC(w) − λ wᵀΣw`` con el límite como cota adicional
  (objetivo cuadrático ``P = 2Σ`` y cono: un SOCP con objetivo cuadrático, como el ``BaseWith
  StressConstraints`` con un solo escenario).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.optimizers.formulations.conic import PSDFactor, volatility_cone
from portfolio_engine.optimizers.formulations.model_builder import ExtendedProblem, ModelBuilder
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)


def require_volatility_limit(limit: float) -> float:
    """Valida ``σ_max`` (finito y positivo) y lo devuelve."""
    if not math.isfinite(limit) or limit <= 0.0:
        raise UnsupportedCombinationError(
            f"VolatilityLimit debe ser finito y > 0 (recibido {limit})."
        )
    return float(limit)


@dataclass(frozen=True, slots=True)
class VolatilityCap:
    """Mandato ``√(wᵀΣw) <= limit`` de la cartera (``PortfolioSpec.volatility_limit``).

    Se añade como cono ``‖Lᵀw‖ <= limit`` a cualquier formulación de la composición (CVaR,
    robusta, peor caso, BaseWithStress): ninguna estrategia puede ignorarlo.
    """

    factor: PSDFactor
    limit: float


def add_volatility_cap(builder: ModelBuilder, cap: VolatilityCap | None, n_weights: int) -> None:
    """Añade el mandato de volatilidad de ``cap`` (nada si es ``None``)."""
    if cap is not None:
        add_volatility_limit(builder, cap.factor, n_weights, cap.limit, "volatility_limit")


def add_volatility_limit(
    builder: ModelBuilder, factor: PSDFactor, n_weights: int, limit: float, name: str
) -> None:
    """Añade ``‖Lᵀw‖₂ <= limit`` sobre las primeras ``n_weights`` variables de ``builder``."""
    cone = volatility_cone(
        factor,
        np.arange(n_weights, dtype=np.int64),
        builder.n_variables,
        require_volatility_limit(limit),
    )
    builder.add_cone(name, cone.matrix, cone.offset, cone.height, cone.constant)


def build_volatility_problem(
    inputs: CompositionInputs,
    cost_treatment: CostTreatment,
    factor: PSDFactor,
    volatility_limit: float,
    *,
    risk_aversion: float | None = None,
) -> tuple[ExtendedProblem, BuiltProblem]:
    """SOCP de control de volatilidad de la composición; devuelve también el problema base.

    ``risk_aversion`` (``λ > 0``) elige la utilidad cuadrática como objetivo; ``None`` maximiza el
    retorno. El :class:`BuiltProblem` devuelto (Bloque 2) conserva la información de costes y de
    variables de compra/venta para evaluar la solución.
    """
    if factor.loading.shape[0] != inputs.compiled.size:
        raise UnsupportedCombinationError("El factor de Σ no corresponde a la composición.")
    base = build_fixed_composition_problem(
        inputs, cost_treatment, quadratic=risk_aversion is not None
    )
    builder = ModelBuilder(base.problem)
    if risk_aversion is None:
        builder.set_objective(None, np.array(base.unit_objective, dtype=np.float64))
    else:
        if not math.isfinite(risk_aversion) or risk_aversion <= 0.0:
            raise UnsupportedCombinationError("risk_aversion debe ser finito y > 0.")
        builder.set_objective(base.problem.P, base.q_risk_aversion(1.0 / risk_aversion))
    add_volatility_limit(builder, factor, base.n_weights, volatility_limit, "volatility_limit")
    problem = builder.finalize("volatility_control")
    extended = ExtendedProblem(
        problem=problem,
        n_weights=base.n_weights,
        n_base_variables=base.problem.n_variables,
        roles={},
        description="SOCP: objetivo del Bloque 2 con ‖Lᵀw‖ <= VolatilityLimit",
    )
    return extended, base
