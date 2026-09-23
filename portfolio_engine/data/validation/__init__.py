"""Validación de datos de entrada (MASTER_SPEC §10). Nunca corrige datos en silencio."""

from portfolio_engine.data.validation.alpha_validator import build_external_alpha
from portfolio_engine.data.validation.market_data_validator import (
    MarketDataResult,
    MarketDataValidator,
)
from portfolio_engine.data.validation.portfolio_validator import (
    PortfolioSetResult,
    PortfolioValidator,
    effective_restricted_policy,
)
from portfolio_engine.data.validation.report import (
    Correction,
    DataIssue,
    DataQualityReport,
    IssueCode,
)
from portfolio_engine.data.validation.transaction_cost_inputs import (
    CostResolution,
    resolve_asset_costs,
)
from portfolio_engine.data.validation.universe_validator import UniverseResult, UniverseValidator

__all__ = (
    "Correction",
    "CostResolution",
    "DataIssue",
    "DataQualityReport",
    "IssueCode",
    "MarketDataResult",
    "MarketDataValidator",
    "PortfolioSetResult",
    "PortfolioValidator",
    "UniverseResult",
    "UniverseValidator",
    "build_external_alpha",
    "effective_restricted_policy",
    "resolve_asset_costs",
)
