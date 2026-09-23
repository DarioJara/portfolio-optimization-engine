"""Expected returns: interfaz y proveedores (MASTER_SPEC §8)."""

from portfolio_engine.returns.expected.base import ExpectedReturnProvider
from portfolio_engine.returns.expected.external_alpha import ExternalAlphaProvider
from portfolio_engine.returns.expected.factory import make_expected_return_provider
from portfolio_engine.returns.expected.historical_mean import HistoricalMeanProvider

__all__ = (
    "ExpectedReturnProvider",
    "ExternalAlphaProvider",
    "HistoricalMeanProvider",
    "make_expected_return_provider",
)
