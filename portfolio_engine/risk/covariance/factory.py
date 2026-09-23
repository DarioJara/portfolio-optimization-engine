"""Selección del estimador de covarianza según ``RiskConfig`` (única fuente de verdad)."""

from __future__ import annotations

from portfolio_engine.config.risk_config import RiskConfig
from portfolio_engine.models.enums import CovarianceMethod
from portfolio_engine.risk.covariance.base import CovarianceEstimator
from portfolio_engine.risk.covariance.empirical import EmpiricalCovarianceEstimator
from portfolio_engine.risk.covariance.ledoit_wolf import LedoitWolfCovarianceEstimator


def make_covariance_estimator(config: RiskConfig) -> CovarianceEstimator:
    """Estimador indicado por ``config.covariance_method``."""
    if config.covariance_method is CovarianceMethod.EMPIRICAL:
        return EmpiricalCovarianceEstimator(config.empirical_ddof)
    return LedoitWolfCovarianceEstimator()
