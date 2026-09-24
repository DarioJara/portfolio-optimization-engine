"""TST-022 (contractual B2, enmienda E-03): consistencia de horizonte de la frontera neta."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.frontiers import ContinuousFrontierEngine, RiskAversionGrid
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem, weights_of

pytestmark = pytest.mark.unit

SIGMA = cov_from_vol_corr([0.20, 0.30], [[1.0, 0.2], [0.2, 1.0]])
MU = np.array([0.05, 0.10])
COSTS = {"BuyCost": [100.0, 150.0], "SellCost": [300.0, 450.0], "MaxWeight": [1.0, 1.0]}
UP, DOWN = 0.01 + 0.045, 0.03 + 0.015
THETA = 1.5
GRID = np.linspace(0.0, 1.0, 400_001)


def _engine_weight(horizon: float) -> tuple[float, float]:
    config = dataclasses.replace(base_config(), optimization_horizon_years=horizon)
    problem = make_problem(MU, SIGMA, [0.7, 0.3], config, universe_overrides=COSTS)
    session = ContinuousFrontierEngine(config).open_session(
        problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    point = RiskAversionGrid(session).solve_theta(THETA)
    assert point.metrics is not None and point.metrics.transaction_cost_one_off is not None
    assert point.metrics.transaction_cost is not None
    # TransactionCost = TransactionCostOneOff / H (E-03)
    assert point.metrics.transaction_cost == pytest.approx(
        point.metrics.transaction_cost_one_off / horizon, abs=1e-15
    )
    return float(weights_of(point)[0]), point.metrics.transaction_cost_one_off


def _horizon_basis_argmin(horizon: float) -> float:
    """Minimiza en base horizonte ``H·wᵀΣw − θ·H·μᵀw + θ·TC_one_off`` por búsqueda en malla."""
    variance = (
        SIGMA[0, 0] * GRID**2 + 2 * SIGMA[0, 1] * GRID * (1 - GRID) + SIGMA[1, 1] * (1 - GRID) ** 2
    )
    one_off = UP * np.maximum(GRID - 0.7, 0.0) + DOWN * np.maximum(0.7 - GRID, 0.0)
    objective = (
        horizon * variance - THETA * horizon * (MU[0] * GRID + MU[1] * (1 - GRID)) + THETA * one_off
    )
    return float(GRID[np.argmin(objective)])


@pytest.mark.parametrize("horizon", [0.5, 1.0, 2.0, 4.0])
def test_annualized_and_horizon_bases_give_the_same_solution(horizon: float) -> None:
    """Base anualizada (``μᵀw − TC_one_off/H``) y base horizonte producen el mismo óptimo."""
    weight, _ = _engine_weight(horizon)
    assert weight == pytest.approx(_horizon_basis_argmin(horizon), abs=2e-6)


def test_the_horizon_changes_the_solution_and_no_horizon_is_implicit() -> None:
    """``H`` importa: horizontes largos amortizan el coste ⇒ más movimiento; nada asume ``H =
    1``."""
    weights = {h: _engine_weight(h)[0] for h in (0.25, 0.5, 1.0, 2.0, 8.0)}
    moves = [abs(weights[h] - 0.7) for h in sorted(weights)]
    assert moves == sorted(moves) and moves[-1] > moves[0] + 1e-3
    one_off = {h: _engine_weight(h)[1] for h in (1.0, 2.0)}
    assert one_off[2.0] >= one_off[1.0] - 1e-12
