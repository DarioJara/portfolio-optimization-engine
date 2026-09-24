"""Escenario ADV/NAV (A-11) con valores explícitos y capacidades calculadas a mano.

``LiquidityCapacity = p · ADV · días / NAV`` con ``p = 0,10``, ``días = 5`` y ``NAV = 1e8``:
``ADV = 2e7`` ⇒ ``0,10 · 2e7 · 5 / 1e8 = 0,10``. ``A000`` es muy rentable y tiene capacidad 0,10; el
resto tiene ``ADV = 1e9`` (capacidad 5, no vinculante). Los valores esperados de los tests son estas
constantes; nunca proceden de ``liquidity_capacity``.
"""

from __future__ import annotations

from typing import Any

from portfolio_engine.config import EngineConfig, FxRate, LiquidityConfig
from portfolio_engine.frontiers import FrontierProblem
from tests.fixtures.non_buyable import MU, SIGMA
from tests.fixtures.problems import base_config, make_problem, spec_with

PARTICIPATION = 0.10
DAYS = 5.0
NAV = 1e8
CAPACITY_A000 = 0.10  # 0,10 · 2e7 · 5 / 1e8
ADV_A000 = 2e7
ADV_OTHERS = 1e9


def liquidity_config(
    participation: float | None = PARTICIPATION,
    days: float | None = DAYS,
    fx: tuple[FxRate, ...] = (),
    *,
    enabled: bool = True,
) -> EngineConfig:
    """Configuración con ``[constraints.liquidity]`` activada con parámetros explícitos de test."""
    liquidity = LiquidityConfig(enabled, participation, days, fx)
    return base_config(constraints={"liquidity": liquidity})


def liquidity_problem(
    current: list[float],
    config: EngineConfig | None = None,
    *,
    adv_a000: float = ADV_A000,
    nav: float | None = NAV,
    nav_currency: str | None = "EUR",
    overrides: dict[str, list[Any]] | None = None,
    mu: Any = MU,
    **kwargs: Any,
) -> tuple[EngineConfig, FrontierProblem]:
    """``(config, problem)`` con la capacidad ADV/NAV de ``A000`` = ``adv_a000·p·días/NAV``."""
    config = config or liquidity_config()
    universe = {
        "MaxWeight": [1.0] * 4,
        "ADV": [adv_a000, ADV_OTHERS, ADV_OTHERS, ADV_OTHERS],
        # contrato de datos completo por defecto: importe diario en EUR con procedencia
        "ADVUnit": ["NOTIONAL_PER_DAY"] * 4,
        "ADVCurrency": ["EUR"] * 4,
        "ADVSource": ["TEST_FEED"] * 4,
        **(overrides or {}),
    }
    spec = kwargs.pop("spec", None) or spec_with(nav=nav, nav_currency=nav_currency)
    problem = make_problem(
        mu, SIGMA, current, config, universe_overrides=universe, spec=spec, **kwargs
    )
    return config, problem
