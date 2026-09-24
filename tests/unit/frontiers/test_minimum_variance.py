"""OPT-006 (contractual B2): Minimum Variance frente a soluciones analíticas y de referencia."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.models.enums import SolverStatus, StatusSource, StrategyID
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    point_of,
    weights_of,
)
from tests.fixtures.reference import min_variance_budget_only, slsqp_qp

pytestmark = pytest.mark.unit

FREE = {"MaxWeight": [1.0] * 6}


def _min_variance(mu, sigma, current, *, overrides=None, config=None):  # type: ignore[no-untyped-def]
    config = config or base_config()
    problem = make_problem(mu, sigma, current, config, universe_overrides=overrides)
    return frontier_result(problem, config), config


def test_diagonal_covariance_matches_inverse_variance_weights() -> None:
    """Σ diagonal, sin límites activos: ``w_i ∝ 1/σ_i²``."""
    variances = np.array([0.04, 0.09, 0.16])
    result, _ = _min_variance(
        [0.05, 0.08, 0.12], np.diag(variances), [0.3, 0.3, 0.4], overrides={"MaxWeight": [1.0] * 3}
    )
    point = point_of(result, StrategyID.MIN_VARIANCE)
    expected = (1.0 / variances) / (1.0 / variances).sum()
    assert point.is_valid_solution and point.status is SolverStatus.OPTIMAL
    assert weights_of(point) == pytest.approx(expected, abs=1e-7)
    assert point.metrics is not None and point.metrics.variance == pytest.approx(
        1.0 / (1.0 / variances).sum(), rel=1e-7
    )


def test_two_assets_with_correlation_match_the_closed_form() -> None:
    """``w1 = (σ2² − σ12) / (σ1² + σ2² − 2σ12)`` (fórmula clásica de dos activos)."""
    sigma = cov_from_vol_corr([0.20, 0.30], [[1.0, 0.25], [0.25, 1.0]])
    result, _ = _min_variance([0.05, 0.09], sigma, [0.5, 0.5], overrides={"MaxWeight": [1.0] * 2})
    w1 = (sigma[1, 1] - sigma[0, 1]) / (sigma[0, 0] + sigma[1, 1] - 2.0 * sigma[0, 1])
    assert weights_of(point_of(result, StrategyID.MIN_VARIANCE)) == pytest.approx(
        [w1, 1.0 - w1], abs=1e-7
    )


def test_general_covariance_matches_linear_algebra_reference() -> None:
    """Σ diagonalmente dominante de 6 activos: solución de ``Σ⁻¹1/(1ᵀΣ⁻¹1)`` con NumPy."""
    rng = np.random.default_rng(11)
    factor = rng.normal(size=(6, 6)) * 0.02
    sigma = factor @ factor.T + np.diag(np.linspace(0.02, 0.06, 6))
    expected = min_variance_budget_only(sigma)
    assert np.all(expected > 0)  # sin límites activos
    result, _ = _min_variance(np.linspace(0.04, 0.10, 6), sigma, [1 / 6] * 6, overrides=FREE)
    assert weights_of(point_of(result, StrategyID.MIN_VARIANCE)) == pytest.approx(
        expected, abs=1e-7
    )


def test_active_upper_bound_matches_slsqp_reference() -> None:
    """Con un límite superior activo (0,3) la solución coincide con SLSQP independiente."""
    sigma = cov_from_vol_corr(
        [0.10, 0.18, 0.22, 0.30, 0.26],
        [
            [1, 0.2, 0.1, 0.0, 0.1],
            [0.2, 1, 0.3, 0.2, 0.1],
            [0.1, 0.3, 1, 0.4, 0.2],
            [0.0, 0.2, 0.4, 1, 0.3],
            [0.1, 0.1, 0.2, 0.3, 1],
        ],
    )
    caps = [0.3] * 5
    result, _ = _min_variance(
        np.linspace(0.04, 0.12, 5), sigma, [0.2] * 5, overrides={"MaxWeight": caps}
    )
    point = point_of(result, StrategyID.MIN_VARIANCE)
    reference = slsqp_qp(sigma, np.zeros(5), np.zeros(5), np.array(caps), start=np.full(5, 0.2))
    assert weights_of(point)[0] == pytest.approx(0.3, abs=1e-7)  # el activo menos volátil topa
    assert weights_of(point) == pytest.approx(reference, abs=1e-6)


def test_minimum_variance_is_the_lowest_variance_of_the_frontier() -> None:
    sigma = cov_from_vol_corr([0.10, 0.15, 0.25], [[1, 0.3, 0.2], [0.3, 1, 0.4], [0.2, 0.4, 1]])
    result, _ = _min_variance(
        [0.05, 0.08, 0.12], sigma, [0.4, 0.3, 0.3], overrides={"MaxWeight": [1.0] * 3}
    )
    minimum = point_of(result, StrategyID.MIN_VARIANCE)
    assert minimum.metrics is not None
    for point in result.valid_points:
        assert point.metrics is not None
        assert point.metrics.variance >= minimum.metrics.variance - 1e-9
    assert result.points[0].strategy_id is StrategyID.MIN_VARIANCE


def test_singular_covariance_gives_a_valid_minimum_variance_portfolio() -> None:
    """Σ singular (activo duplicado, ya validada como PSD en el Bloque 1): varianza mínima
    correcta."""
    base = cov_from_vol_corr([0.10, 0.20], [[1.0, 0.0], [0.0, 1.0]])
    sigma = np.zeros((3, 3))
    sigma[:2, :2] = base
    sigma[2, :2], sigma[:2, 2], sigma[2, 2] = (
        base[1, :],
        base[:, 1],
        base[1, 1],
    )  # activo 3 = activo 2
    assert np.linalg.matrix_rank(sigma) == 2
    result, _ = _min_variance(
        [0.05, 0.07, 0.07], sigma, [0.3, 0.3, 0.4], overrides={"MaxWeight": [1.0] * 3}
    )
    point = point_of(result, StrategyID.MIN_VARIANCE)
    assert point.is_valid_solution
    # los activos 2 y 3 son idénticos: solo importa w2 + w3; varianza mínima analítica (2 activos)
    w1 = (base[1, 1]) / (base[0, 0] + base[1, 1])
    assert point.metrics is not None
    assert point.metrics.variance == pytest.approx(
        w1**2 * base[0, 0] + (1 - w1) ** 2 * base[1, 1], rel=1e-6
    )
    assert weights_of(point)[0] == pytest.approx(w1, abs=1e-6)


def test_near_singular_covariance_is_solved_and_validated() -> None:
    """Σ casi singular (correlación 0,9999): sigue habiendo solución válida y de varianza mínima."""
    sigma = cov_from_vol_corr(
        [0.20, 0.20, 0.10], [[1, 0.9999, 0.1], [0.9999, 1, 0.1], [0.1, 0.1, 1]]
    )
    assert np.linalg.cond(sigma) > 1e4
    result, _ = _min_variance(
        [0.05, 0.05, 0.03], sigma, [0.3, 0.3, 0.4], overrides={"MaxWeight": [1.0] * 3}
    )
    point = point_of(result, StrategyID.MIN_VARIANCE)
    reference = slsqp_qp(sigma, np.zeros(3), np.zeros(3), np.ones(3), start=np.full(3, 1 / 3))
    assert point.is_valid_solution and point.status_source is StatusSource.SOLVER
    assert point.metrics is not None
    assert point.metrics.variance == pytest.approx(float(reference @ sigma @ reference), rel=1e-6)
