"""RSK-001 … RSK-003: estimadores Empirical y Ledoit-Wolf frente a referencias independientes."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.covariance import ledoit_wolf as sklearn_ledoit_wolf

from portfolio_engine.config import EngineConfig
from portfolio_engine.exceptions import InsufficientDataError
from portfolio_engine.models.enums import CovarianceMethod
from portfolio_engine.risk.covariance import (
    EmpiricalCovarianceEstimator,
    LedoitWolfCovarianceEstimator,
    make_covariance_estimator,
)
from tests.fixtures.synthetic import replace_section

pytestmark = pytest.mark.unit


def _returns(n_obs: int, n_assets: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    loadings = rng.normal(size=(n_assets, 2))
    factors = rng.normal(scale=0.01, size=(n_obs, 2))
    return factors @ loadings.T + rng.normal(scale=0.005, size=(n_obs, n_assets))


@pytest.mark.parametrize("ddof", [0, 1])
def test_empirical_matches_numpy_cov(ddof: int) -> None:
    data = _returns(120, 7, seed=1)
    raw = EmpiricalCovarianceEstimator(ddof).estimate(data)
    np.testing.assert_allclose(raw.matrix, np.cov(data, rowvar=False, ddof=ddof), rtol=1e-12)
    assert raw.shrinkage is None
    assert raw.n_observations == 120


def test_empirical_manual_two_by_two() -> None:
    data = np.array([[1.0, 2.0], [3.0, 2.0], [5.0, 8.0]])
    # medias (3, 4); desviaciones [(-2,-2),(0,-2),(2,4)]
    expected = np.array([[8.0, 12.0], [12.0, 24.0]]) / 2.0
    np.testing.assert_allclose(EmpiricalCovarianceEstimator(1).estimate(data).matrix, expected)


@pytest.mark.parametrize(("n_obs", "n_assets"), [(250, 10), (40, 60), (15, 3)])
def test_ledoit_wolf_matches_reference_implementation(n_obs: int, n_assets: int) -> None:
    data = _returns(n_obs, n_assets, seed=n_obs)
    raw = LedoitWolfCovarianceEstimator().estimate(data)
    reference, reference_shrinkage = sklearn_ledoit_wolf(data)
    np.testing.assert_allclose(raw.matrix, reference, rtol=1e-10, atol=1e-18)
    assert raw.shrinkage == pytest.approx(reference_shrinkage, rel=1e-10)
    assert 0.0 <= raw.shrinkage <= 1.0


def test_ledoit_wolf_spectrum_is_convex_combination() -> None:
    data = _returns(30, 50, seed=5)  # T < N: muestral singular
    raw = LedoitWolfCovarianceEstimator().estimate(data)
    centered = data - data.mean(axis=0)
    sample = centered.T @ centered / data.shape[0]
    scale = np.trace(sample) / sample.shape[0]
    delta = raw.shrinkage
    assert delta is not None
    expected = (1 - delta) * np.linalg.eigvalsh(sample) + delta * scale
    np.testing.assert_allclose(np.linalg.eigvalsh(raw.matrix), expected, rtol=1e-9, atol=1e-15)
    assert np.linalg.eigvalsh(sample)[0] < 1e-15  # la muestral es singular
    assert np.linalg.eigvalsh(raw.matrix)[0] >= delta * scale * (1 - 1e-9)  # LW es PD


def test_ledoit_wolf_on_scaled_identity_sample_does_not_shrink() -> None:
    data = np.array([[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0], [0.0, -1.0]])  # S = 0.5·I
    raw = LedoitWolfCovarianceEstimator().estimate(data)
    assert raw.shrinkage == 0.0
    np.testing.assert_allclose(raw.matrix, 0.5 * np.eye(2))


@pytest.mark.parametrize(
    "data",
    [np.zeros((1, 3)), np.zeros((5, 0)), np.array([[0.1, np.nan], [0.2, 0.1]])],
)
def test_estimators_reject_insufficient_or_invalid_data(data: np.ndarray) -> None:
    for estimator in (EmpiricalCovarianceEstimator(1), LedoitWolfCovarianceEstimator()):
        with pytest.raises(InsufficientDataError):
            estimator.estimate(data)


def test_factory_follows_configuration(config: EngineConfig) -> None:
    assert make_covariance_estimator(config.risk).method is CovarianceMethod.LEDOIT_WOLF
    empirical = replace_section(config, "risk", covariance_method=CovarianceMethod.EMPIRICAL).risk
    assert make_covariance_estimator(empirical).method is CovarianceMethod.EMPIRICAL


def test_deferred_methods_are_not_selectable() -> None:
    """E-07: OAS y EWMA siguen diferidos; no existen como opción seleccionable."""
    assert {method.name for method in CovarianceMethod} == {"EMPIRICAL", "LEDOIT_WOLF"}
