"""TST-013 (contractual B2, MASTER_SPEC §76): el coste escala con theta en la formulación Risk
Aversion."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.optimizers import OSQPBackend
from portfolio_engine.optimizers.formulations import build_fixed_composition_problem
from tests.fixtures.problems import base_config, composition_inputs, cov_from_vol_corr, make_problem
from tests.fixtures.reference import two_asset_net_optimum

pytestmark = pytest.mark.unit

SIGMA = cov_from_vol_corr([0.20, 0.30], [[1.0, 0.2], [0.2, 1.0]])
MU = np.array([0.05, 0.10])
COSTS = {"BuyCost": [100.0, 150.0], "SellCost": [300.0, 450.0], "MaxWeight": [1.0, 1.0]}
UP, DOWN = 0.01 + 0.045, 0.03 + 0.015
HORIZON = 2.0
THETA = 5.0


def _built():  # type: ignore[no-untyped-def]
    config = dataclasses.replace(base_config(), optimization_horizon_years=HORIZON)
    problem = make_problem(MU, SIGMA, [0.7, 0.3], config, universe_overrides=COSTS)
    inputs = composition_inputs(problem, config)
    return config, build_fixed_composition_problem(inputs, CostTreatment.NET, quadratic=True)


def _solve(config, built, q):  # type: ignore[no-untyped-def]
    backend = OSQPBackend(config.solver)
    backend.setup(built.problem)
    backend.update(q=q)
    result = backend.solve()
    assert result.x is not None
    return built.weights(result.x)


def test_algebraic_scaling_q_equals_theta_times_q1() -> None:
    """(a) ``q(θ) = θ·q(1)`` exactamente, para todo el vector incluido el bloque de costes."""
    _, built = _built()
    q1 = built.q_risk_aversion(1.0)
    for theta in (0.1, 0.5, 2.0, THETA, 30.0):
        assert built.q_risk_aversion(theta) == pytest.approx(theta * q1, rel=1e-15)
    n = built.n_weights
    assert np.all(q1[n:] > 0.0)  # bloque de costes presente y positivo
    assert built.q_risk_aversion(THETA)[n:] == pytest.approx(THETA * q1[n:], rel=1e-15)


def test_solution_equals_the_independent_utility_maximum() -> None:
    """(b) ``argmin`` con ``q(θ)`` = ``argmax μᵀw − TC(w) − λ wᵀΣw`` con ``λ = 1/θ`` (análisis
    por tramos)."""
    config, built = _built()
    weights = _solve(config, built, built.q_risk_aversion(THETA))
    expected = two_asset_net_optimum(SIGMA, MU, THETA, 0.7, UP, DOWN, HORIZON, 0.0, 1.0)
    assert weights == pytest.approx([expected, 1.0 - expected], abs=1e-6)
    # maximización directa de la utilidad (λ = 1/θ) por búsqueda en malla, sin theta en el coste
    lam = 1.0 / THETA
    grid = np.linspace(0.0, 1.0, 400_001)
    variance = (
        SIGMA[0, 0] * grid**2 + 2 * SIGMA[0, 1] * grid * (1 - grid) + SIGMA[1, 1] * (1 - grid) ** 2
    )
    tc = (UP * np.maximum(grid - 0.7, 0.0) + DOWN * np.maximum(0.7 - grid, 0.0)) / HORIZON
    utility = MU[0] * grid + MU[1] * (1 - grid) - tc - lam * variance
    assert weights[0] == pytest.approx(grid[np.argmax(utility)], abs=2e-6)


def test_unscaled_cost_formulation_gives_different_solutions() -> None:
    """(c) Una formulación con el coste sin escalar por θ es distinta y se detecta."""
    config, built = _built()
    n = built.n_weights
    q_correct = built.q_risk_aversion(THETA)
    q_wrong = q_correct.copy()
    q_wrong[n:] = built.unit_objective[n:]  # coste sin multiplicar por θ (error habitual)
    correct = _solve(config, built, q_correct)
    wrong = _solve(config, built, q_wrong)
    assert np.max(np.abs(correct - wrong)) > 1e-3
    # la formulación incorrecta equivale a costes θ veces menores
    equivalent = two_asset_net_optimum(
        SIGMA, MU, THETA, 0.7, UP / THETA, DOWN / THETA, HORIZON, 0.0, 1.0
    )
    assert wrong == pytest.approx([equivalent, 1.0 - equivalent], abs=1e-6)
    right = two_asset_net_optimum(SIGMA, MU, THETA, 0.7, UP, DOWN, HORIZON, 0.0, 1.0)
    assert correct == pytest.approx([right, 1.0 - right], abs=1e-6)
