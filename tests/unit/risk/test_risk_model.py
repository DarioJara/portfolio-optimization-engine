"""RSK-013 e integración del Bloque 1: datos → retornos → mu, Sigma → RiskModel."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from sklearn.covariance import ledoit_wolf

from portfolio_engine.config import EngineConfig
from portfolio_engine.data.sources import DataFrameSource
from portfolio_engine.data.validation import MarketDataValidator, UniverseValidator
from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.enums import CovarianceMethod
from portfolio_engine.models.risk_model import RiskModel
from portfolio_engine.returns import ReturnsEngine
from portfolio_engine.returns.expected import make_expected_return_provider
from portfolio_engine.risk import CovarianceBuilder, build_risk_model
from tests.fixtures.synthetic import holdings_frame, price_frame, universe_frame

pytestmark = pytest.mark.unit


def _risk_model(config: EngineConfig, seed: int = 11) -> RiskModel:
    source = DataFrameSource(
        prices=price_frame(8, 150, seed=seed),
        universe=universe_frame(8),
        holdings=holdings_frame([("P1", "A000", 1.0)]),
    )
    universe = UniverseValidator(config.constraints).validate(source.load_universe()).universe
    prices = MarketDataValidator(config.data).validate(source.load_prices(), universe).prices
    returns = ReturnsEngine(config.returns).compute(prices)
    ids = returns.asset_ids
    expected = make_expected_return_provider(config.returns, None).estimate(ids, returns)
    covariance = CovarianceBuilder(config.risk, config.returns.trading_days_per_year).build(
        returns, ids
    )
    return build_risk_model(expected, covariance)


def test_end_to_end_foundation_pipeline(config: EngineConfig) -> None:
    model = _risk_model(config)
    assert model.asset_ids == tuple(f"A{i:03d}" for i in range(8))
    assert model.mu.shape == (8,)
    assert model.sigma.shape == (8, 8)
    assert model.covariance.method is CovarianceMethod.LEDOIT_WOLF
    assert model.covariance.final_diagnostics.is_psd
    assert not model.mu.flags.writeable
    assert not model.sigma.flags.writeable


def test_sigma_is_annualized_ledoit_wolf_of_daily_returns(config: EngineConfig) -> None:
    model = _risk_model(config)
    prices = price_frame(8, 150, seed=11).pivot(
        index="Date", columns="AssetID", values="AdjustedClose"
    )
    daily = (prices.to_numpy()[1:] / prices.to_numpy()[:-1]) - 1.0
    reference, _ = ledoit_wolf(daily)
    np.testing.assert_allclose(model.sigma, 252 * reference, rtol=1e-10)
    np.testing.assert_allclose(model.mu, 252 * daily.mean(axis=0), rtol=1e-12)


def test_mu_sigma_version_is_deterministic_and_sensitive(config: EngineConfig) -> None:
    first, second = _risk_model(config), _risk_model(config)
    assert first.mu_sigma_version == second.mu_sigma_version
    assert _risk_model(config, seed=12).mu_sigma_version != first.mu_sigma_version
    empirical = dataclasses.replace(
        config, risk=dataclasses.replace(config.risk, covariance_method=CovarianceMethod.EMPIRICAL)
    )
    assert _risk_model(empirical).mu_sigma_version != first.mu_sigma_version


def test_risk_model_requires_aligned_assets(config: EngineConfig) -> None:
    model = _risk_model(config)
    shifted = dataclasses.replace(
        model.expected_returns,
        asset_ids=tuple(f"B{i:03d}" for i in range(8)),
    )
    with pytest.raises(DataValidationError, match="mismos activos"):
        build_risk_model(shifted, model.covariance)
