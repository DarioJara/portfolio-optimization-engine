"""Métricas vectorizadas de carteras (MASTER_SPEC §55, §64)."""

from portfolio_engine.metrics.contributions import marginal_risk_contribution, return_contribution
from portfolio_engine.metrics.portfolio_metrics import (
    REASON_NO_CURRENT_PORTFOLIO,
    REASON_NO_TRANSACTION_COST_DATA,
    MetricsTable,
    MetricsTolerances,
    compute_metrics,
    portfolio_variance,
)

__all__ = (
    "REASON_NO_CURRENT_PORTFOLIO",
    "REASON_NO_TRANSACTION_COST_DATA",
    "MetricsTable",
    "MetricsTolerances",
    "compute_metrics",
    "marginal_risk_contribution",
    "portfolio_variance",
    "return_contribution",
)
