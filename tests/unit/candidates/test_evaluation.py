"""CAN-021: estimación de la utilidad de una composición (PROJECTED_WEIGHTS y QP_UTILITY).

El óptimo de referencia se calcula con SciPy SLSQP sobre variables ``w, b, s`` (sin usar el motor).
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import minimize

from portfolio_engine.candidates import (
    EvaluationRejection,
    ProjectedWeightsEvaluator,
    current_portfolio_utility,
    project_box_budget,
    tightened_bounds,
)
from portfolio_engine.frontiers import QPCompositionEvaluator
from portfolio_engine.models.composition import CompositionEstimate
from portfolio_engine.models.enums import EvaluationMode
from portfolio_engine.validation import SolutionValidator, ValidationTolerances
from tests.fixtures.candidates import corr_matrix, exact_net_utility, prepared_for
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem, spec_with

pytestmark = pytest.mark.unit

N = 8
MU = np.array([0.07, 0.06, 0.05, 0.03, 0.04, 0.11, 0.09, 0.02])
VOLS = [0.18, 0.15, 0.12, 0.10, 0.14, 0.28, 0.22, 0.09]
SIGMA = cov_from_vol_corr(VOLS, corr_matrix(N, 0.25))
CURRENT = [0.4, 0.35, 0.25] + [0.0] * (N - 3)
BUY_BPS = [15.0, 20.0, 25.0, 30.0, 35.0, 60.0, 45.0, 10.0]
SELL_BPS = [40.0, 50.0, 55.0, 30.0, 35.0, 80.0, 70.0, 20.0]
BUY, SELL = np.array(BUY_BPS) / 1e4, np.array(SELL_BPS) / 1e4
COMPOSITION = ("A001", "A002", "A005")  # A000 sale (venta completa), A005 entra
MAX_WEIGHT = 0.7


def _config(iterations: int = 25, horizon: float = 1.0):  # type: ignore[no-untyped-def]
    return base_config(
        engine={"optimization_horizon_years": horizon},
        candidates={"refinement_iterations": iterations},
    )


def _problem(config, **kwargs):  # type: ignore[no-untyped-def]
    return make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={
            "MaxWeight": [MAX_WEIGHT] * N,
            "BuyCost": BUY_BPS,
            "SellCost": SELL_BPS,
        },
        **kwargs,
    )


def _exact(lam: float, horizon: float = 1.0):  # type: ignore[no-untyped-def]
    idx = [1, 2, 5]
    current = np.array([0.35, 0.25, 0.0])
    exit_cost = 0.4 * SELL[0]
    return exact_net_utility(
        MU[idx], SIGMA[np.ix_(idx, idx)], current, BUY[idx], SELL[idx], exit_cost, horizon,
        np.zeros(3), np.full(3, MAX_WEIGHT), lam,
    )  # fmt: skip


def _baseline(lam: float) -> float:
    held = [0, 1, 2]
    w0 = np.array(CURRENT[:3])
    return float(MU[held] @ w0 - lam * w0 @ SIGMA[np.ix_(held, held)] @ w0)


def _validator(config):  # type: ignore[no-untyped-def]
    return SolutionValidator(ValidationTolerances.from_config(config.solver))


def test_project_box_budget_matches_an_independent_projection() -> None:
    rng = np.random.default_rng(3)
    for _ in range(25):
        n = int(rng.integers(3, 9))
        lower = rng.uniform(0.0, 0.05, n)
        upper = lower + rng.uniform(0.35, 0.8, n)  # Σ upper > 1: factible
        target = rng.normal(0.2, 0.4, n)
        projected = project_box_budget(target, lower, upper, 1.0)
        reference = minimize(
            lambda w, t=target: float(np.sum((w - t) ** 2)),
            np.full(n, 1.0 / n),
            method="SLSQP",
            bounds=list(zip(lower, upper, strict=True)),
            constraints=[{"type": "eq", "fun": lambda w: float(w.sum() - 1.0)}],
            options={"ftol": 1e-15, "maxiter": 500},
        ).x
        assert projected.sum() == pytest.approx(1.0, abs=1e-12)
        assert np.all(projected >= lower - 1e-12) and np.all(projected <= upper + 1e-12)
        assert np.allclose(projected, reference, atol=1e-6)
        assert np.allclose(project_box_budget(projected, lower, upper, 1.0), projected, atol=1e-12)


def test_tightened_bounds_only_use_the_budget_and_stay_finite() -> None:
    config = _config()
    prepared = prepared_for(_problem(config), config, COMPOSITION)
    assert prepared.compiled is not None
    lower, upper = tightened_bounds(prepared.compiled)  # type: ignore[misc]
    assert np.all(np.isfinite(lower)) and np.all(np.isfinite(upper))
    assert np.allclose(lower, 0.0) and np.allclose(upper, MAX_WEIGHT)


@pytest.mark.parametrize("lam", [1.0, 4.0, 16.0])
def test_qp_evaluator_reproduces_the_independent_optimum_including_costs_and_exits(
    lam: float,
) -> None:
    config = _config(iterations=0)
    problem = _problem(config)
    prepared = prepared_for(problem, config, COMPOSITION)
    estimate = QPCompositionEvaluator(config).evaluate(prepared, lam, _baseline(lam))
    assert isinstance(estimate, CompositionEstimate)
    expected_utility, expected_weights = _exact(lam)
    assert estimate.utility == pytest.approx(expected_utility, abs=1e-7)
    assert np.allclose(estimate.weights, expected_weights, atol=1e-4)
    assert estimate.basis is EvaluationMode.QP_UTILITY and estimate.satisfies_constraints
    assert estimate.utility_gain == pytest.approx(expected_utility - _baseline(lam), abs=1e-7)


def test_qp_evaluator_respects_the_optimization_horizon() -> None:
    config = _config(iterations=0, horizon=2.0)
    problem = _problem(config)
    prepared = prepared_for(problem, config, COMPOSITION)
    estimate = QPCompositionEvaluator(config).evaluate(prepared, 4.0, 0.0)
    assert isinstance(estimate, CompositionEstimate)
    assert estimate.utility == pytest.approx(_exact(4.0, horizon=2.0)[0], abs=1e-7)
    # el coste único no cambia con H; el coste anualizado sí (E-03)
    assert estimate.transaction_cost == pytest.approx(estimate.transaction_cost_one_off / 2.0)  # type: ignore[operator]


@pytest.mark.parametrize("lam", [1.0, 4.0, 16.0])
def test_projected_estimate_is_a_lower_bound_and_refinement_only_improves_it(lam: float) -> None:
    exact, _ = _exact(lam)
    utilities = []
    for iterations in (0, 5, 25):
        config = _config(iterations)
        prepared = prepared_for(_problem(config), config, COMPOSITION)
        estimate = ProjectedWeightsEvaluator(iterations, _validator(config)).evaluate(
            prepared, lam, _baseline(lam)
        )
        assert isinstance(estimate, CompositionEstimate)
        assert estimate.basis is EvaluationMode.PROJECTED_WEIGHTS
        assert estimate.utility <= exact + 1e-9  # cota inferior de la utilidad óptima
        assert estimate.weights.sum() == pytest.approx(1.0, abs=1e-9)
        assert np.all(estimate.weights >= -1e-12) and np.all(estimate.weights <= MAX_WEIGHT + 1e-12)
        utilities.append(estimate.utility)
    assert (
        utilities[0] <= utilities[1] + 1e-12 <= utilities[2] + 2e-12
    )  # el mejor iterado no empeora
    assert exact - utilities[2] < exact - utilities[0] + 1e-12


def test_estimate_metrics_are_recomputed_from_the_weights_on_the_union() -> None:
    config = _config(iterations=10)
    problem = _problem(config)
    prepared = prepared_for(problem, config, COMPOSITION)
    lam = 4.0
    estimate = ProjectedWeightsEvaluator(10, _validator(config)).evaluate(
        prepared, lam, _baseline(lam)
    )
    assert isinstance(estimate, CompositionEstimate)
    w = estimate.weights
    idx = [1, 2, 5]
    new = np.zeros(N)
    new[idx] = w
    old = np.array(CURRENT)
    delta = new - old
    expected_cost = float(np.sum(BUY * np.maximum(delta, 0) + SELL * np.maximum(-delta, 0)))
    expected_turnover = 0.5 * float(np.abs(delta).sum())
    assert estimate.transaction_cost_one_off == pytest.approx(expected_cost)
    assert estimate.transaction_cost == pytest.approx(expected_cost / 1.0)
    assert estimate.turnover == pytest.approx(expected_turnover)
    assert estimate.expected_return_gross == pytest.approx(float(MU[idx] @ w))
    assert estimate.variance == pytest.approx(float(w @ SIGMA[np.ix_(idx, idx)] @ w))
    assert estimate.utility == pytest.approx(
        estimate.expected_return_gross - lam * estimate.variance - expected_cost
    )
    # la venta completa del activo que sale (A000 con 40 %) está en el coste y en el turnover
    assert expected_cost >= 0.4 * SELL[0] and expected_turnover >= 0.5 * 0.4


def test_the_current_composition_evaluated_with_its_own_weights_has_no_cost() -> None:
    config = _config(iterations=0)
    problem = _problem(config)
    prepared = prepared_for(problem, config, ("A000", "A001", "A002"))
    baseline = _baseline(4.0)
    assert baseline == pytest.approx(
        current_portfolio_utility(MU[:3], SIGMA[:3, :3], np.array(CURRENT[:3]), 4.0)
    )
    estimate = ProjectedWeightsEvaluator(0, _validator(config)).evaluate(prepared, 4.0, baseline)
    assert isinstance(estimate, CompositionEstimate)
    # sin refinar, los pesos transferidos son los actuales: coste 0, turnover 0, ganancia 0
    assert np.allclose(estimate.weights, CURRENT[:3])
    assert estimate.transaction_cost == pytest.approx(0.0, abs=1e-15)
    assert estimate.turnover == pytest.approx(0.0, abs=1e-15)
    assert estimate.utility_gain == pytest.approx(0.0, abs=1e-12)


def test_infeasible_compositions_are_rejected_with_explicit_causes_by_both_evaluators() -> None:
    """MaxTurnover menor que el turnover forzado por la venta completa de A000 (0.2)."""
    config = _config()
    problem = _problem(config, spec=spec_with(max_turnover=0.05))
    prepared = prepared_for(problem, config, COMPOSITION)
    assert not prepared.feasible
    for evaluator in (
        ProjectedWeightsEvaluator(5, _validator(config)),
        QPCompositionEvaluator(config),
    ):
        outcome = evaluator.evaluate(prepared, 4.0, 0.0)
        assert isinstance(outcome, EvaluationRejection)
        assert "REMOVED_ASSETS_TURNOVER_ABOVE_MAX" in outcome.reasons
        assert outcome.details


def test_projected_estimate_flags_group_or_turnover_violations_without_rejecting() -> None:
    """La proyección solo respeta cotas y presupuesto; el validador informa del resto."""
    limit = 0.42  # el turnover mínimo forzado es 0.5·(0.4 de venta + 0.4 de compra) = 0.40
    config = _config(iterations=60)
    problem = _problem(config, spec=spec_with(max_turnover=limit))
    prepared = prepared_for(problem, config, COMPOSITION)
    assert prepared.feasible
    estimate = ProjectedWeightsEvaluator(60, _validator(config)).evaluate(prepared, 0.5, 0.0)
    assert isinstance(estimate, CompositionEstimate)
    assert estimate.satisfies_constraints == (not estimate.violations)
    assert not estimate.satisfies_constraints  # el gradiente proyectado ignora el turnover
    assert any(item.startswith("TURNOVER") for item in estimate.violations)
    exact = QPCompositionEvaluator(config).evaluate(prepared, 0.5, 0.0)
    assert isinstance(exact, CompositionEstimate) and exact.satisfies_constraints
    assert exact.turnover <= limit + 1e-7  # type: ignore[operator]


def test_no_current_portfolio_leaves_turnover_and_cost_unavailable() -> None:
    config = _config(iterations=5)
    problem = make_problem(
        MU, SIGMA, None, config, universe_overrides={"MaxWeight": [MAX_WEIGHT] * N}
    )
    prepared = prepared_for(problem, config, COMPOSITION)
    estimate = ProjectedWeightsEvaluator(5, _validator(config)).evaluate(prepared, 4.0, 0.0)
    assert isinstance(estimate, CompositionEstimate)
    assert estimate.turnover is None and estimate.transaction_cost is None
    assert estimate.transaction_cost_one_off is None
    assert estimate.utility == pytest.approx(
        estimate.expected_return_gross - 4.0 * estimate.variance
    )
