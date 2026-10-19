"""CVaR de Rockafellar-Uryasev sobre escenarios de retorno (MASTER_SPEC §22; OPT-011, OPT-012).

Para la pérdida ``L_t(w) = −r_tᵀw`` de cada escenario ``t`` (probabilidad ``π_t``) y el
nivel ``β``::

    CVaR_β(w) = min_α  α + 1/(1 − β) · Σ_t π_t · max(L_t(w) − α, 0)

que se linealiza con variables auxiliares ``u_t >= max(L_t − α, 0)``::

    minimize    α + 1/(1 − β) Σ_t π_t u_t
    subject to  u_t + r_tᵀw + α >= 0,   u_t >= 0            (t = 1..T)

Es una formulación **lineal** en ``(w, α, u)``: con objetivo ``MIN_CVAR`` o
``MAX_RETURN_WITH_LIMIT``
es un LP (HiGHS) y con ``UTILITY_WITH_LIMIT`` un QP con restricciones lineales (OSQP): ninguna
necesita un solver cónico. En el óptimo ``α*`` es el ``VaR_β`` y el valor es el ``CVaR_β`` exacto
de la medida discreta; la solución se contrasta siempre con el cálculo directo e independiente de
:mod:`portfolio_engine.metrics.cvar_metric`.

Unidades: los escenarios son retornos **por periodo**; el límite ``MaxCVaR`` está en el horizonte
de ``CVaRConfig`` (``CVaR_horizonte = factor · CVaR_periodo``, escalado declarado), de modo que la
restricción es ``CVaR_periodo <= MaxCVaR / factor``. CVaR no es VaR ni volatilidad ni pérdida
máxima.
"""

from __future__ import annotations

import math

import numpy as np
import scipy.sparse as sparse

from portfolio_engine.config.cvar_config import CVaRConfig
from portfolio_engine.exceptions import DataValidationError, UnsupportedCombinationError
from portfolio_engine.models.cvar import ReturnScenarioSet
from portfolio_engine.models.enums import CostTreatment, CVaRObjective
from portfolio_engine.optimizers.formulations.model_builder import ExtendedProblem, ModelBuilder
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.formulations.volatility import VolatilityCap, add_volatility_cap


def check_tail_observations(scenarios: ReturnScenarioSet, config: CVaRConfig) -> None:
    """Exige observaciones suficientes en la cola: ``(1 − β)·T >= min_tail_observations``."""
    tail = (1.0 - config.confidence_level) * scenarios.n_scenarios
    if tail < config.min_tail_observations:
        raise DataValidationError(
            f"La cola del CVaR tiene {tail:.2f} observaciones efectivas (< "
            f"{config.min_tail_observations}): amplíe los escenarios o rebaje el nivel."
        )


def build_cvar_problem(
    inputs: CompositionInputs,
    scenarios: ReturnScenarioSet,
    config: CVaRConfig,
    cost_treatment: CostTreatment,
    objective: CVaRObjective,
    *,
    max_cvar: float | None = None,
    risk_aversion: float | None = None,
    volatility_cap: VolatilityCap | None = None,
) -> tuple[ExtendedProblem, BuiltProblem]:
    """Problema de CVaR de la composición: LP o QP con restricciones lineales.

    ``max_cvar`` (en unidades del horizonte de ``config``) es obligatorio con los objetivos
    ``*_WITH_LIMIT`` y opcional con ``MIN_CVAR``; ``risk_aversion`` (``λ > 0``) es obligatorio con
    ``UTILITY_WITH_LIMIT``. Nunca se ignora un parámetro sobrante: se rechaza.
    """
    limited = objective is not CVaRObjective.MIN_CVAR
    utility = objective is CVaRObjective.UTILITY_WITH_LIMIT
    if limited and max_cvar is None:
        raise UnsupportedCombinationError(f"{objective.value} exige max_cvar.")
    if utility != (risk_aversion is not None):
        raise UnsupportedCombinationError(
            "risk_aversion es obligatorio con UTILITY_WITH_LIMIT y no se admite en los demás."
        )
    if max_cvar is not None and (not math.isfinite(max_cvar) or max_cvar < 0.0):
        raise UnsupportedCombinationError("max_cvar debe ser finito y no negativo.")
    if risk_aversion is not None and (not math.isfinite(risk_aversion) or risk_aversion <= 0.0):
        raise UnsupportedCombinationError("risk_aversion debe ser finito y > 0.")
    check_tail_observations(scenarios, config)
    returns = scenarios.columns_for(inputs.compiled.asset_ids)
    base = build_fixed_composition_problem(inputs, cost_treatment, quadratic=utility)
    builder = ModelBuilder(base.problem)
    n_scenarios = returns.shape[0]
    alpha = builder.add_variables(1)
    excess = builder.add_variables(n_scenarios, lower=0.0)
    n_weights = base.n_weights
    rows = sparse.lil_matrix((n_scenarios, builder.n_variables))
    rows[:, :n_weights] = returns
    rows[np.arange(n_scenarios), excess + np.arange(n_scenarios)] = 1.0
    rows[:, alpha] = 1.0
    builder.add_rows(sparse.csr_matrix(rows), np.zeros(n_scenarios), np.full(n_scenarios, np.inf))
    tail = 1.0 / (1.0 - config.confidence_level)
    cvar_row = np.zeros(builder.n_variables)
    cvar_row[alpha] = 1.0
    cvar_row[excess : excess + n_scenarios] = tail * scenarios.weights
    if objective is CVaRObjective.MIN_CVAR:
        builder.set_objective(None, cvar_row)
    elif utility and risk_aversion is not None:
        theta = base.q_risk_aversion(1.0 / risk_aversion)
        builder.set_objective(base.problem.P, np.concatenate([theta, np.zeros(1 + n_scenarios)]))
    else:
        builder.set_objective(
            None, np.concatenate([base.unit_objective, np.zeros(1 + n_scenarios)])
        )
    if max_cvar is not None:
        builder.add_rows(
            sparse.csr_matrix(cvar_row.reshape(1, -1)),
            np.full(1, -np.inf),
            np.full(1, max_cvar / config.horizon_factor),
        )
    add_volatility_cap(builder, volatility_cap, n_weights)
    problem = builder.finalize("cvar_" + objective.value.lower())
    extended = ExtendedProblem(
        problem=problem,
        n_weights=n_weights,
        n_base_variables=base.problem.n_variables,
        roles={"alpha": alpha, "excess": excess},
        description=f"Rockafellar-Uryasev {objective.value}",
    )
    return extended, base
