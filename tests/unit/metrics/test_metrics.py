"""MET-001, MET-002, MET-005, MET-006, TC-007, TC-008, OUT-006: métricas vectorizadas y no
disponibles."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

import portfolio_engine.metrics.portfolio_metrics as metrics_module
from portfolio_engine.costs import TransactionCostModel, align_union
from portfolio_engine.exceptions import MetricsError
from portfolio_engine.metrics import (
    REASON_NO_CURRENT_PORTFOLIO,
    REASON_NO_TRANSACTION_COST_DATA,
    MetricsTolerances,
    compute_metrics,
    marginal_risk_contribution,
    return_contribution,
)
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import CostSource
from portfolio_engine.models.portfolio import CurrentPortfolioState
from portfolio_engine.models.universe_index import AssetIndex
from tests.fixtures.problems import cov_from_vol_corr

pytestmark = pytest.mark.unit

IDS = ("A", "B", "C")
TOL = MetricsTolerances(
    variance_tolerance=1e-12, zero_volatility_tolerance=1e-12, zero_weight_tolerance=1e-8
)
MU = np.array([0.05, 0.08, 0.11])
SIGMA = cov_from_vol_corr([0.10, 0.20, 0.30], [[1, 0.2, 0.1], [0.2, 1, 0.4], [0.1, 0.4, 1]])
RISK_FREE = 0.02


def _alignment(current: dict[str, float], composition: tuple[str, ...] = IDS):  # type: ignore[no-untyped-def]
    state = CurrentPortfolioState.from_weights("P", current, AssetIndex(IDS), None)
    return align_union(state, composition)


def _cost_model(alignment, horizon: float = 1.0) -> TransactionCostModel:  # type: ignore[no-untyped-def]
    costs = AssetCostVector(
        IDS,
        np.array([0.001, 0.002, 0.003]),
        np.array([0.004, 0.005, 0.006]),
        (CostSource.BUY_SELL,) * 3,
    )
    return TransactionCostModel(alignment, costs, horizon)


def test_vectorized_vs_scalar_reference() -> None:
    """MET-001: la evaluación vectorizada coincide con un cálculo escalar independiente."""
    alignment = _alignment({"A": 0.5, "B": 0.3, "C": 0.2})
    model = _cost_model(alignment, horizon=2.0)
    rng = np.random.default_rng(7)
    raw = rng.random((25, 3))
    weights = raw / raw.sum(axis=1, keepdims=True)
    table = compute_metrics(
        weights,
        mu=MU,
        sigma=SIGMA,
        risk_free_rate=RISK_FREE,
        tolerances=TOL,
        alignment=alignment,
        cost_model=model,
    )
    current = np.array([0.5, 0.3, 0.2])
    buy, sell = np.array([0.001, 0.002, 0.003]), np.array([0.004, 0.005, 0.006])
    for row, w in enumerate(weights):
        gross = sum(w[i] * MU[i] for i in range(3))
        variance = sum(w[i] * SIGMA[i, j] * w[j] for i in range(3) for j in range(3))
        one_off = sum(
            buy[i] * max(w[i] - current[i], 0.0) + sell[i] * max(current[i] - w[i], 0.0)
            for i in range(3)
        )
        assert table.expected_return_gross[row] == pytest.approx(gross, abs=1e-14)
        assert table.variance[row] == pytest.approx(variance, abs=1e-14)
        assert table.volatility[row] == pytest.approx(variance**0.5, abs=1e-14)
        assert table.sharpe_ratio[row] == pytest.approx((gross - RISK_FREE) / variance**0.5)
        assert table.herfindahl_index[row] == pytest.approx(float(w @ w))
        assert table.turnover is not None
        assert table.turnover[row] == pytest.approx(0.5 * float(np.abs(w - current).sum()))
        assert table.transaction_cost_one_off is not None
        assert table.transaction_cost_one_off[row] == pytest.approx(one_off, abs=1e-15)
        assert table.transaction_cost is not None
        assert table.transaction_cost[row] == pytest.approx(one_off / 2.0, abs=1e-15)
        assert table.expected_return_net is not None
        assert table.expected_return_net[row] == pytest.approx(gross - one_off / 2.0, abs=1e-14)


def test_no_python_loop_over_points() -> None:
    """MET-002: ``compute_metrics`` no contiene bucles ``for`` sobre los puntos."""
    source = inspect.getsource(metrics_module.compute_metrics)
    assert "for " not in source.split('"""')[2]


def test_net_never_exceeds_gross_with_positive_costs() -> None:
    """TST-009 (unitario): con costes positivos, ``Net <= Gross`` para cualquier cartera."""
    alignment = _alignment({"A": 0.2, "B": 0.3, "C": 0.5})
    model = _cost_model(alignment)
    rng = np.random.default_rng(3)
    raw = rng.random((200, 3))
    weights = raw / raw.sum(axis=1, keepdims=True)
    table = compute_metrics(
        weights,
        mu=MU,
        sigma=SIGMA,
        risk_free_rate=RISK_FREE,
        tolerances=TOL,
        alignment=alignment,
        cost_model=model,
    )
    assert table.expected_return_net is not None and table.transaction_cost is not None
    assert np.all(table.transaction_cost >= 0.0)
    assert np.all(table.expected_return_net <= table.expected_return_gross + 1e-15)


def test_no_current_portfolio_marks_metrics_unavailable() -> None:
    """TC-007/OUT-006: sin cartera actual turnover, coste y neto son ``None`` (no 0,5 ni 0)."""
    alignment = _alignment({})
    table = compute_metrics(
        np.array([[0.4, 0.3, 0.3]]),
        mu=MU,
        sigma=SIGMA,
        risk_free_rate=RISK_FREE,
        tolerances=TOL,
        alignment=alignment,
        cost_model=None,
    )
    row = table.row(0)
    assert row.turnover is None and row.transaction_cost is None
    assert row.transaction_cost_one_off is None and row.expected_return_net is None
    assert row.number_new_assets is None and row.number_removed_assets is None
    assert row.unavailable_reason == REASON_NO_CURRENT_PORTFOLIO
    assert row.expected_return_gross == pytest.approx(float(np.array([0.4, 0.3, 0.3]) @ MU))


def test_current_portfolio_without_cost_data_keeps_turnover() -> None:
    """Sin datos de coste pero con cartera actual: turnover disponible, coste y neto no."""
    alignment = _alignment({"A": 0.5, "B": 0.5})
    table = compute_metrics(
        np.array([[0.2, 0.3, 0.5]]),
        mu=MU,
        sigma=SIGMA,
        risk_free_rate=RISK_FREE,
        tolerances=TOL,
        alignment=alignment,
        cost_model=None,
    )
    row = table.row(0)
    assert row.turnover == pytest.approx(0.5)
    assert row.transaction_cost is None and row.expected_return_net is None
    assert row.unavailable_reason == REASON_NO_TRANSACTION_COST_DATA


def test_counts_of_assets() -> None:
    """MET-005: activos mantenidos, nuevos y eliminados según la tolerancia de peso cero."""
    alignment = _alignment({"A": 0.6, "B": 0.4})
    table = compute_metrics(
        np.array([[0.0, 0.7, 0.3]]),
        mu=MU,
        sigma=SIGMA,
        risk_free_rate=RISK_FREE,
        tolerances=TOL,
        alignment=alignment,
        cost_model=None,
    )
    row = table.row(0)
    assert (row.number_assets, row.number_new_assets, row.number_removed_assets) == (2, 1, 1)


def test_sharpe_is_undefined_at_zero_volatility() -> None:
    """MET-006: volatilidad ~ 0 ⇒ Sharpe ``None`` (no infinito)."""
    table = compute_metrics(
        np.array([[1.0, 0.0, 0.0]]),
        mu=np.array([0.05, 0.08, 0.11]),
        sigma=np.zeros((3, 3)),
        risk_free_rate=RISK_FREE,
        tolerances=TOL,
        alignment=None,
        cost_model=None,
    )
    assert table.row(0).sharpe_ratio is None and table.row(0).volatility == 0.0


def test_negative_variance_and_non_finite_weights_are_rejected() -> None:
    not_psd = np.array([[1.0, 2.0, 0.0], [2.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    with pytest.raises(MetricsError, match="negativa"):
        compute_metrics(
            np.array([[1.0, -1.0, 0.0]]),
            mu=MU,
            sigma=not_psd,
            risk_free_rate=0.0,
            tolerances=TOL,
            alignment=None,
            cost_model=None,
        )
    with pytest.raises(MetricsError, match="finitos"):
        compute_metrics(
            np.array([[np.nan, 0.5, 0.5]]),
            mu=MU,
            sigma=SIGMA,
            risk_free_rate=0.0,
            tolerances=TOL,
            alignment=None,
            cost_model=None,
        )


def test_contributions_satisfy_euler_identities() -> None:
    """MET-003: ``Σ w_i·MRC_i = σ_p`` y ``Σ contribuciones al retorno = μᵀw``."""
    weights = np.array([[0.2, 0.3, 0.5], [0.6, 0.1, 0.3]])
    mrc = marginal_risk_contribution(weights, SIGMA, 1e-12)
    volatility = np.sqrt(np.einsum("ki,ij,kj->k", weights, SIGMA, weights))
    assert (weights * mrc).sum(axis=1) == pytest.approx(volatility)
    assert return_contribution(weights, MU).sum(axis=1) == pytest.approx(weights @ MU)
    assert np.all(np.isnan(marginal_risk_contribution(np.zeros((1, 3)), SIGMA, 1e-12)))
