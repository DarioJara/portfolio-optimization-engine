"""MET-004: VaR, CVaR (Expected Shortfall), pérdida máxima y volatilidad son cantidades distintas.

Valores calculados a mano sobre distribuciones discretas pequeñas (con el átomo frontera
fraccionado); el cálculo directo es el que valida al LP de Rockafellar-Uryasev.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.exceptions import MetricsError
from portfolio_engine.metrics import (
    conditional_value_at_risk,
    loss_volatility,
    maximum_loss,
    portfolio_losses,
    value_at_risk,
)

pytestmark = pytest.mark.unit

LOSSES = np.array([1.0, 2.0, 3.0, 4.0])
UNIFORM = np.full(4, 0.25)


def test_cvar_is_the_mean_of_the_tail_with_the_boundary_atom_split() -> None:
    assert conditional_value_at_risk(LOSSES, UNIFORM, 0.75) == pytest.approx(4.0)
    # cola de masa 0,4: 0,25·4 + 0,15·3 = 1,45 → /0,4 = 3,625 (el átomo de 3 se fracciona)
    assert conditional_value_at_risk(LOSSES, UNIFORM, 0.6) == pytest.approx(3.625)
    assert conditional_value_at_risk(LOSSES, UNIFORM, 0.5) == pytest.approx(3.5)
    assert conditional_value_at_risk(LOSSES, UNIFORM, 0.25) == pytest.approx(3.0)


def test_var_is_a_quantile_and_differs_from_cvar_max_loss_and_volatility() -> None:
    var = value_at_risk(LOSSES, UNIFORM, 0.6)
    cvar = conditional_value_at_risk(LOSSES, UNIFORM, 0.6)
    worst = maximum_loss(LOSSES)
    vol = loss_volatility(LOSSES, UNIFORM)
    assert var == 3.0 and cvar == pytest.approx(3.625) and worst == 4.0
    assert vol == pytest.approx(float(np.sqrt(1.25)))
    assert len({var, round(cvar, 9), worst, round(vol, 9)}) == 4
    assert var <= cvar <= worst  # jerarquía de las medidas de cola


def test_unequal_weights_move_the_tail() -> None:
    probabilities = np.array([0.5, 0.3, 0.15, 0.05])
    # cola de masa 0,1 (β = 0,9): 0,05·4 + 0,05·3 = 0,35 → /0,1 = 3,5
    assert conditional_value_at_risk(LOSSES, probabilities, 0.9) == pytest.approx(3.5)
    assert value_at_risk(LOSSES, probabilities, 0.9) == 3.0
    assert value_at_risk(LOSSES, probabilities, 0.5) == 1.0


def test_losses_are_minus_the_portfolio_return_per_scenario() -> None:
    returns = np.array([[0.02, -0.01], [-0.03, 0.01]])
    losses = portfolio_losses(returns, np.array([0.5, 0.5]))
    np.testing.assert_allclose(losses, [-0.005, 0.01])
    with pytest.raises(MetricsError):
        portfolio_losses(returns, np.array([1.0]))


def test_cvar_is_translation_and_scale_covariant() -> None:
    base = conditional_value_at_risk(LOSSES, UNIFORM, 0.6)
    assert conditional_value_at_risk(LOSSES + 10.0, UNIFORM, 0.6) == pytest.approx(base + 10.0)
    assert conditional_value_at_risk(3.0 * LOSSES, UNIFORM, 0.6) == pytest.approx(3.0 * base)


def test_cvar_is_monotone_in_the_confidence_level_and_bounded_by_the_maximum() -> None:
    values = [conditional_value_at_risk(LOSSES, UNIFORM, level) for level in (0.1, 0.4, 0.7, 0.99)]
    assert values == sorted(values) and values[-1] <= maximum_loss(LOSSES) + 1e-12


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(MetricsError, match="nivel"):
        conditional_value_at_risk(LOSSES, UNIFORM, 1.0)
    with pytest.raises(MetricsError, match="nivel"):
        value_at_risk(LOSSES, UNIFORM, 0.0)
    with pytest.raises(MetricsError, match="negativas"):
        conditional_value_at_risk(LOSSES, np.array([0.5, 0.6, -0.1, 0.0]), 0.5)
    with pytest.raises(MetricsError, match="finitas"):
        conditional_value_at_risk(np.array([1.0, np.nan, 3.0, 4.0]), UNIFORM, 0.5)
    with pytest.raises(MetricsError):
        conditional_value_at_risk(LOSSES, np.full(3, 1 / 3), 0.5)
    with pytest.raises(MetricsError):
        maximum_loss(np.array([]))
