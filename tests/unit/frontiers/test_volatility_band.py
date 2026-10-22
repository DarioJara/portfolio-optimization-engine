"""HC-007: máximo retorno bajo la banda de volatilidad (``max_volatility`` convexa,
``min_volatility`` no convexa). Casos de dos activos con solución analítica y barrido
independiente en el símplex.

Con ``w = (1 − x, x)``, ``ρ = 0`` y ``σ₁ = 0,1``, ``σ₂ = 0,3``: ``σ²(x) = 0,01(1 − x)² + 0,09x²`` y
``σ(x) = s`` ⇔ ``0,1x² − 0,02x + 0,01 − s² = 0``; para ``s = 0,2`` la raíz derecha es
``x = (0,02 + √(0,0004 + 0,012)) / 0,2 ≈ 0,656776``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from portfolio_engine.frontiers.volatility_band import (
    BandOutcome,
    BandResult,
    VolatilityBandSolver,
)
from portfolio_engine.hard_constraints.resolver import derive_engine_config
from portfolio_engine.models.enums import CostTreatment
from tests.fixtures.hard_constraints import BAND_PARAMS, effective_of, with_mandate
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem

pytestmark = pytest.mark.unit

FLOOR = 0.02
X_AT_0_2 = (0.02 + math.sqrt(0.0004 + 0.012)) / 0.2


def _problem(mu, vols, corr=None, config=None, with_costs=False):  # type: ignore[no-untyped-def]
    n = len(mu)
    corr = np.eye(n) if corr is None else corr
    return make_problem(
        mu,
        cov_from_vol_corr(vols, corr),
        [1.0 / n] * n,
        config or base_config(),
        universe_overrides={"MaxWeight": [1.0] * n},
        with_costs=with_costs,
    )


def _solve(
    mu, vols, corr=None, treatment=CostTreatment.GROSS, **fields
) -> tuple[BandResult, object]:  # type: ignore[no-untyped-def]
    problem = _problem(mu, vols, corr, with_costs=treatment is CostTreatment.NET)
    config = with_mandate(**fields)
    effective = effective_of(config, problem)
    derived = derive_engine_config(config, effective)
    sub = type(problem)(
        problem.portfolio_id, problem.scenario_id, problem.risk_model, problem.universe,
        problem.state, problem.spec, problem.costs, tuple(problem.universe.asset_ids),
    )  # fmt: skip
    return VolatilityBandSolver(derived).solve(sub, treatment, effective), problem


def _vol(weights, problem):  # type: ignore[no-untyped-def]
    sigma = problem.risk_model.sigma
    return math.sqrt(float(weights @ sigma @ weights))


def test_with_only_a_maximum_the_convex_optimum_is_certified_and_matches_the_closed_form() -> None:
    result, problem = _solve([0.05, 0.10], [0.1, 0.3], max_volatility=0.2)
    assert result.outcome is BandOutcome.OPTIMAL_CERTIFIED
    assert result.weights is not None
    assert result.weights[1] == pytest.approx(X_AT_0_2, abs=1e-5)
    assert _vol(result.weights, problem) == pytest.approx(0.2, abs=1e-6)
    assert result.gap == pytest.approx(0.0, abs=1e-12)
    assert result.upper_bound == pytest.approx(result.objective_value)
    assert result.objective_value == pytest.approx(0.05 + 0.05 * X_AT_0_2, abs=1e-6)


def test_when_the_relaxation_already_satisfies_the_floor_it_is_the_global_optimum() -> None:
    """σ(w_A) ∈ [σ_min, σ_max]: el óptimo de la relajación es factible para la banda."""
    result, _ = _solve(
        [0.05, 0.10], [0.1, 0.3], min_volatility=0.15, max_volatility=0.2, **BAND_PARAMS
    )
    assert result.outcome is BandOutcome.OPTIMAL_CERTIFIED
    assert result.weights is not None and result.weights[1] == pytest.approx(X_AT_0_2, abs=1e-5)
    assert "RELAXATION_FEASIBLE_FOR_BAND" in result.notes


def test_an_active_floor_is_nonconvex_and_solved_to_a_certified_admissible_local_optimum() -> None:
    """El activo de mayor riesgo rinde menos: el máximo retorno ignora el mínimo (σ ≈ 0,098)."""
    result, problem = _solve(
        [0.10, 0.05], [0.1, 0.3], min_volatility=0.2, max_volatility=0.25, **BAND_PARAMS
    )
    assert result.relaxation_volatility is not None and result.relaxation_volatility < 0.2
    assert (
        result.outcome is BandOutcome.FEASIBLE_LOCAL
    )  # cota superior no alcanzada: sin certificado
    assert result.weights is not None
    assert _vol(result.weights, problem) >= 0.2 - 1e-7  # nunca se relaja el mínimo
    assert _vol(result.weights, problem) <= 0.25 + 1e-7
    assert result.weights[1] == pytest.approx(X_AT_0_2, abs=1e-4)  # óptimo analítico (rama derecha)
    assert result.objective_value is not None and result.upper_bound is not None
    assert result.gap == pytest.approx(result.upper_bound - result.objective_value)
    assert result.gap > 0.0
    # barrido independiente de x: el óptimo global con banda es el de la solución
    grid = np.linspace(FLOOR, 1.0 - FLOOR, 20001)
    sigma = np.sqrt(0.01 * (1 - grid) ** 2 + 0.09 * grid**2)
    feasible = (sigma >= 0.2 - 1e-12) & (sigma <= 0.25 + 1e-12)
    best = float(np.max((0.10 * (1 - grid) + 0.05 * grid)[feasible]))
    assert result.objective_value == pytest.approx(best, abs=1e-4)
    assert best <= result.upper_bound + 1e-12  # la relajación es, en efecto, una cota superior


def test_the_band_solution_is_admissible_and_bounded_by_the_relaxation_on_random_problems() -> None:
    checked = 0
    for seed in range(6):
        local = np.random.default_rng(seed + 100)
        vols = local.uniform(0.08, 0.30, 3)
        factor = local.normal(size=(3, 3))
        corr = np.corrcoef(factor @ factor.T + 3 * np.eye(3))
        mu = local.uniform(0.02, 0.12, 3)
        problem = _problem(list(mu), list(vols), corr)
        floor = 0.7 * float(np.max(vols))
        result, _ = _solve(list(mu), list(vols), corr, min_volatility=floor, **BAND_PARAMS)
        if result.weights is None:
            assert result.outcome is BandOutcome.NO_FEASIBLE_SOLUTION_FOUND
            continue
        checked += 1
        assert result.outcome in {BandOutcome.OPTIMAL_CERTIFIED, BandOutcome.FEASIBLE_LOCAL}
        assert _vol(result.weights, problem) >= floor - 1e-6
        assert result.weights.sum() == pytest.approx(1.0, abs=1e-7)
        assert result.weights.min() >= FLOOR - 1e-7
        # barrido independiente en el símplex (paso 0,01): ni una cota ni el valor se violan
        sigma = problem.risk_model.sigma
        step = np.arange(0.02, 0.97, 0.01)
        best = -math.inf
        for a in step:
            for b in step:
                c = 1.0 - a - b
                if c < FLOOR - 1e-12:
                    continue
                w = np.array([a, b, c])
                if math.sqrt(float(w @ sigma @ w)) >= floor:
                    best = max(best, float(mu @ w))
        assert result.upper_bound is not None and result.objective_value is not None
        assert best <= result.upper_bound + 1e-9
        assert result.objective_value <= result.upper_bound + 1e-9
        assert result.objective_value >= best - 2e-3  # empírico: 3 activos y arranques múltiples
    assert checked >= 3


def test_a_cap_below_the_minimum_variance_is_proven_infeasible_by_the_relaxation() -> None:
    result, _ = _solve([0.05, 0.10], [0.1, 0.3], max_volatility=0.05)
    assert result.outcome is BandOutcome.INFEASIBLE_PROVEN
    assert result.weights is None and result.objective_value is None


def test_a_floor_above_every_attainable_volatility_is_not_found_but_not_claimed_infeasible() -> (
    None
):
    result, _ = _solve([0.10, 0.05], [0.1, 0.3], min_volatility=0.5, **BAND_PARAMS)
    assert result.outcome is BandOutcome.NO_FEASIBLE_SOLUTION_FOUND
    assert result.weights is None
    assert result.upper_bound is not None  # la cota de la relajación sí se conserva
    assert "FLOOR_NOT_REACHED_FROM_ANY_START" in result.notes


def test_the_concentration_cap_is_a_second_order_cone_in_the_band_problem() -> None:
    """Σw² <= 0,5 con dos activos solo admite w = (0,5; 0,5)."""
    result, _ = _solve([0.05, 0.10], [0.1, 0.3], max_concentration_hhi=0.5)
    assert result.weights is not None
    assert result.weights == pytest.approx([0.5, 0.5], abs=1e-5)


def test_net_treatment_discounts_transaction_costs_in_the_objective() -> None:
    gross, _ = _solve([0.05, 0.10], [0.1, 0.3], max_volatility=0.2)
    net, problem = _solve([0.05, 0.10], [0.1, 0.3], treatment=CostTreatment.NET, max_volatility=0.2)
    assert gross.objective_value is not None and net.objective_value is not None
    assert net.objective_value < gross.objective_value  # el coste de la transición reduce el neto
    assert net.weights is not None and _vol(net.weights, problem) <= 0.2 + 1e-7


def test_the_search_is_deterministic() -> None:
    kwargs = {"min_volatility": 0.2, "max_volatility": 0.25, **BAND_PARAMS}
    first, _ = _solve([0.10, 0.05], [0.1, 0.3], **kwargs)
    second, _ = _solve([0.10, 0.05], [0.1, 0.3], **kwargs)
    assert first.weights is not None and second.weights is not None
    assert np.array_equal(first.weights, second.weights)
    assert (first.iterations, first.starts_tried) == (second.iterations, second.starts_tried)
