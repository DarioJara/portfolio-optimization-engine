"""RET-011: anualización lineal configurable (obligatorio B1)."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.exceptions import ConfigError
from portfolio_engine.returns import annualize_covariance, annualize_mean

pytestmark = pytest.mark.unit


def test_mean_annualization_uses_configured_trading_days() -> None:
    daily = np.array([0.001, -0.0005])
    np.testing.assert_allclose(annualize_mean(daily, 252), [0.252, -0.126], rtol=1e-15)
    np.testing.assert_allclose(annualize_mean(daily, 260), [0.26, -0.13], rtol=1e-15)


def test_covariance_annualization_scales_every_entry() -> None:
    daily = np.array([[1e-4, 2e-5], [2e-5, 4e-4]])
    annual = annualize_covariance(daily, 252)
    np.testing.assert_allclose(annual, 252 * daily, rtol=1e-15)
    # La volatilidad escala con la raíz del número de periodos.
    np.testing.assert_allclose(
        np.sqrt(np.diag(annual)), np.sqrt(252) * np.array([0.01, 0.02]), rtol=1e-12
    )


@pytest.mark.parametrize("trading_days", [0, -252, True, 252.0])
def test_invalid_trading_days(trading_days: object) -> None:
    with pytest.raises(ConfigError):
        annualize_mean(np.zeros(1), trading_days)  # type: ignore[arg-type]
