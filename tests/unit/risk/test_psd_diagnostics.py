"""RSK-006 … RSK-009: finitud, simetría, autovalores, condición y PSD (obligatorios B1)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from portfolio_engine.exceptions import CovarianceEstimationError
from portfolio_engine.risk import diagnose_psd, relative_asymmetry, symmetrize
from portfolio_engine.risk.psd_diagnostics import check_finite

pytestmark = pytest.mark.unit

TOLERANCE = 1e-10


def test_non_finite_matrix_rejected() -> None:
    for bad in (np.array([[1.0, np.nan], [np.nan, 1.0]]), np.array([[np.inf]])):
        with pytest.raises(CovarianceEstimationError, match="NaN o infinitos"):
            check_finite(bad)
    with pytest.raises(CovarianceEstimationError, match="cuadrada"):
        check_finite(np.ones((2, 3)))


def test_symmetrization_is_exact_average() -> None:
    matrix = np.array([[2.0, 1.0 + 1e-9], [1.0 - 1e-9, 3.0]])
    symmetric = symmetrize(matrix)
    np.testing.assert_array_equal(symmetric, symmetric.T)
    np.testing.assert_allclose(symmetric, [[2.0, 1.0], [1.0, 3.0]], rtol=0, atol=1e-15)
    assert relative_asymmetry(matrix) == pytest.approx(2e-9 / 3.0, rel=1e-6)
    assert relative_asymmetry(np.zeros((2, 2))) == 0.0


def test_eigenvalues_min_and_condition_number() -> None:
    q, _ = np.linalg.qr(np.random.default_rng(0).normal(size=(3, 3)))
    matrix = (q * np.array([0.5, 2.0, 10.0])) @ q.T
    diagnostics = diagnose_psd(matrix, TOLERANCE)
    np.testing.assert_allclose(diagnostics.eigenvalues, [0.5, 2.0, 10.0], rtol=1e-12)
    assert diagnostics.min_eigenvalue == pytest.approx(0.5, rel=1e-12)
    assert diagnostics.max_eigenvalue == pytest.approx(10.0, rel=1e-12)
    assert diagnostics.condition_number == pytest.approx(20.0, rel=1e-10)
    assert diagnostics.is_psd


def test_indefinite_matrix_is_not_psd() -> None:
    matrix = np.array([[1.0, 2.0], [2.0, 1.0]])  # autovalores −1 y 3
    diagnostics = diagnose_psd(matrix, TOLERANCE)
    assert diagnostics.min_eigenvalue == pytest.approx(-1.0)
    assert not diagnostics.is_psd
    assert math.isinf(diagnostics.condition_number)


def test_singular_covariance_is_psd_with_infinite_condition() -> None:
    """Obligatorio B1: matriz singular (T < N) es PSD pero no invertible."""
    returns = np.random.default_rng(1).normal(size=(5, 8))
    centered = returns - returns.mean(axis=0)
    singular = centered.T @ centered / 4.0
    diagnostics = diagnose_psd(singular, TOLERANCE)
    assert diagnostics.is_psd
    assert abs(diagnostics.min_eigenvalue) <= TOLERANCE * diagnostics.max_eigenvalue
    assert diagnostics.condition_number > 1e12 or math.isinf(diagnostics.condition_number)


def test_near_singular_covariance_is_psd_but_ill_conditioned() -> None:
    """Obligatorio B1: dos activos casi colineales."""
    epsilon = 1e-7
    matrix = np.array([[1.0, 1.0 - epsilon], [1.0 - epsilon, 1.0]])
    diagnostics = diagnose_psd(matrix, TOLERANCE)
    assert diagnostics.is_psd
    assert diagnostics.min_eigenvalue == pytest.approx(epsilon, rel=1e-6)
    assert diagnostics.condition_number == pytest.approx((2 - epsilon) / epsilon, rel=1e-6)


def test_psd_tolerance_is_relative_to_spectral_scale() -> None:
    tiny_negative = np.diag([-1e-12, 1.0])
    assert diagnose_psd(tiny_negative, TOLERANCE).is_psd
    assert not diagnose_psd(tiny_negative, 0.0).is_psd
    scaled = tiny_negative * 1e6
    assert diagnose_psd(scaled, TOLERANCE).is_psd  # invariante a la escala
    assert not diagnose_psd(np.diag([-1e-9, 1.0]), TOLERANCE).is_psd
