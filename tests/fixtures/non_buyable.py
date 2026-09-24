"""Escenario de la posición actual no comprable (E-10; H-1 de AUDIT_BLOCK_3).

``A000`` pesa 0,10 en la cartera, tiene un retorno esperado muy superior al del resto (sin tope el
optimizador lo subiría muy por encima de 0,10) y no admite compras por una de cuatro causas.
Los valores esperados de los tests salen de estas constantes, no de las funciones bajo prueba.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from portfolio_engine.config import EngineConfig
from portfolio_engine.frontiers import FrontierProblem
from portfolio_engine.models.enums import EligibilityReason
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem, spec_with

HELD_WEIGHT = 0.10  # peso actual de A000
CURRENT = [HELD_WEIGHT, 0.90, 0.0, 0.0]
MU = np.array([0.30, 0.04, 0.06, 0.09])
MU_UNATTRACTIVE = np.array([-0.05, 0.04, 0.06, 0.09])  # A000 conviene reducirlo hasta salir
SIGMA = cov_from_vol_corr([0.10, 0.05, 0.15, 0.25], np.full((4, 4), 0.1) + 0.9 * np.eye(4))
OPEN_BOUNDS: dict[str, list[Any]] = {"MaxWeight": [1.0] * 4}

#: Cada caso: (overrides del universo, ``InvestmentUniverse``, causa esperada del bloqueo).
BLOCKERS: dict[str, tuple[dict[str, list[Any]], tuple[str, ...] | None, EligibilityReason]] = {
    "not_eligible": (
        {"EligibleFlag": [False, True, True, True]},
        None,
        EligibilityReason.NOT_ELIGIBLE,
    ),
    "not_liquid": (
        {"LiquidityFlag": [False, True, True, True]},
        None,
        EligibilityReason.NOT_LIQUID,
    ),
    "unknown_liquidity_excluded": (
        {"LiquidityFlag": [None, True, True, True]},
        None,
        EligibilityReason.UNKNOWN_LIQUIDITY_FLAG,
    ),
    "outside_investment_universe": (
        {},
        ("A001", "A002", "A003"),
        EligibilityReason.OUTSIDE_INVESTMENT_UNIVERSE,
    ),
}


def non_buyable_problem(
    case: str,
    config: EngineConfig | None = None,
    *,
    mu: Any = MU,
    extra_overrides: dict[str, list[Any]] | None = None,
    **kwargs: Any,
) -> tuple[EngineConfig, FrontierProblem]:
    """``(config, problem)`` con ``A000`` (10 %) no comprable por la causa ``case``."""
    overrides, universe, _ = BLOCKERS[case]
    config = config or base_config()
    spec = spec_with(investment_universe=universe) if universe is not None else None
    problem = make_problem(
        mu,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={**OPEN_BOUNDS, **overrides, **(extra_overrides or {})},
        spec=spec,
        **kwargs,
    )
    return config, problem
