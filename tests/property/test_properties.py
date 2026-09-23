"""Tests basados en propiedades (Hypothesis) de los invariantes del Bloque 1 (TST-003)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from portfolio_engine.config import load_engine_config
from portfolio_engine.data.validation.transaction_cost_inputs import to_decimal
from portfolio_engine.models.costs import BPS_PER_UNIT
from portfolio_engine.models.enums import CostInputUnit, ReturnKind
from portfolio_engine.models.market_data import PriceHistory
from portfolio_engine.models.portfolio import current_portfolio_state_hash
from portfolio_engine.returns import ReturnsEngine, annualize_covariance, annualize_mean
from portfolio_engine.risk import diagnose_psd, eigenvalue_floor_repair, nearest_psd_repair
from portfolio_engine.risk.covariance import (
    EmpiricalCovarianceEstimator,
    LedoitWolfCovarianceEstimator,
)
from tests.conftest import DEFAULT_CONFIG_PATH

pytestmark = pytest.mark.property

PROFILE = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
RETURNS_CONFIG = load_engine_config(DEFAULT_CONFIG_PATH).returns

finite_returns = st.floats(min_value=-0.2, max_value=0.2, allow_nan=False, allow_infinity=False)
positive_prices = st.floats(min_value=0.01, max_value=1e4, allow_nan=False, allow_infinity=False)


def _matrix(n_obs: int, n_assets: int) -> st.SearchStrategy[np.ndarray]:
    return arrays(np.float64, (n_obs, n_assets), elements=finite_returns)


#: Magnitud mínima no nula de las entradas generadas. Con entradas cercanas al underflow
#: (~1e-160) ``np.linalg.eigvalsh`` (oráculo del test) pierde precisión (error relativo ~2e-4)
#: mientras que ``np.linalg.eigh`` (usado por el motor) no: es un límite de LAPACK, no del
#: motor, y esas magnitudes no aparecen en covarianzas reales (ver CHANGELOG, Bloque 1).
MIN_ENTRY_MAGNITUDE = 1e-6


def _symmetric(n: int) -> st.SearchStrategy[np.ndarray]:
    element = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False).map(
        lambda x: 0.0 if abs(x) < MIN_ENTRY_MAGNITUDE else x
    )
    return arrays(np.float64, (n, n), elements=element).map(lambda a: (a + a.T) / 2.0)


@PROFILE
@given(st.lists(positive_prices, min_size=2, max_size=40))
def test_compounded_arithmetic_returns_reproduce_price_ratio(prices: list[float]) -> None:
    dates = pd.bdate_range("2024-01-01", periods=len(prices))
    history = PriceHistory(pd.DataFrame({"Date": dates, "AssetID": "A", "AdjustedClose": prices}))
    returns = ReturnsEngine(RETURNS_CONFIG).compute(history)
    assert returns.kind is ReturnKind.ARITHMETIC
    assert np.all(returns.values > -1.0)
    growth = float(np.prod(1.0 + returns.values[:, 0]))
    assert growth == pytest.approx(prices[-1] / prices[0], rel=1e-9)


@PROFILE
@given(
    arrays(np.float64, 5, elements=finite_returns),
    st.integers(min_value=1, max_value=400),
    st.integers(min_value=1, max_value=400),
)
def test_annualization_is_linear_in_trading_days(mean: np.ndarray, first: int, second: int) -> None:
    combined = annualize_mean(mean, first + second)
    np.testing.assert_allclose(
        combined, annualize_mean(mean, first) + annualize_mean(mean, second), atol=1e-12
    )


@PROFILE
@given(st.integers(min_value=3, max_value=25), st.integers(min_value=1, max_value=8), st.data())
def test_estimated_covariances_are_symmetric_psd(
    n_obs: int, n_assets: int, data: st.DataObject
) -> None:
    returns = data.draw(_matrix(n_obs, n_assets))
    for estimator in (EmpiricalCovarianceEstimator(1), LedoitWolfCovarianceEstimator()):
        raw = estimator.estimate(returns)
        np.testing.assert_allclose(raw.matrix, raw.matrix.T, atol=1e-15)
        annual = annualize_covariance(raw.matrix, 252)
        assert diagnose_psd(annual, 1e-9).is_psd
        if raw.shrinkage is not None:
            assert 0.0 <= raw.shrinkage <= 1.0


@PROFILE
@given(st.integers(min_value=2, max_value=6).flatmap(_symmetric))
def test_nearest_psd_is_psd_idempotent_and_closest(matrix: np.ndarray) -> None:
    repaired = nearest_psd_repair(matrix)
    scale = max(1.0, float(np.max(np.abs(np.linalg.eigvalsh(matrix)))))
    assert np.linalg.eigvalsh(repaired)[0] >= -1e-12 * scale
    np.testing.assert_allclose(nearest_psd_repair(repaired), repaired, atol=1e-10 * scale)
    distance = np.linalg.norm(repaired - matrix, "fro")
    rng = np.random.default_rng(0)
    for _ in range(5):  # cualquier otra matriz PSD está al menos igual de lejos
        factor = rng.normal(size=matrix.shape)
        candidate = factor @ factor.T
        assert distance <= np.linalg.norm(candidate - matrix, "fro") + 1e-9 * scale


@PROFILE
@given(
    st.integers(min_value=2, max_value=6).flatmap(_symmetric),
    st.floats(min_value=1e-8, max_value=1e-2),
)
def test_eigenvalue_floor_guarantees_relative_floor(matrix: np.ndarray, floor: float) -> None:
    eigenvalues = np.linalg.eigvalsh(matrix)
    repaired_eigenvalues = np.linalg.eigvalsh(eigenvalue_floor_repair(matrix, floor))
    target = floor * max(eigenvalues[-1], 0.0)
    scale = max(1.0, float(np.max(np.abs(eigenvalues))))
    assert repaired_eigenvalues[0] >= target - 1e-10 * scale
    # Los autovalores por encima del suelo no cambian.
    np.testing.assert_allclose(
        repaired_eigenvalues, np.maximum(eigenvalues, target), atol=1e-9 * scale
    )


weights_strategy = st.dictionaries(
    st.text(alphabet="ABCDEFGH", min_size=1, max_size=3),
    st.floats(min_value=1e-6, max_value=1.0, allow_nan=False),
    min_size=1,
    max_size=8,
)


@PROFILE
@given(weights_strategy, st.randoms())
def test_state_hash_is_order_invariant(weights: dict[str, float], random: object) -> None:
    items = list(weights.items())
    random.shuffle(items)  # type: ignore[attr-defined]
    assert current_portfolio_state_hash(dict(items)) == current_portfolio_state_hash(weights)


@PROFILE
@given(weights_strategy, st.data())
def test_state_hash_detects_any_single_weight_change(
    weights: dict[str, float], data: st.DataObject
) -> None:
    asset = data.draw(st.sampled_from(sorted(weights)))
    changed = dict(weights)
    changed[asset] = float(np.nextafter(weights[asset], 2.0))
    assert current_portfolio_state_hash(changed) != current_portfolio_state_hash(weights)


@PROFILE
@given(st.floats(min_value=0.0, max_value=1e4, allow_nan=False))
def test_bps_conversion_is_exact_division(value: float) -> None:
    assert to_decimal(value, CostInputUnit.BPS) == value / BPS_PER_UNIT
    assert to_decimal(value, CostInputUnit.DECIMAL) == value
