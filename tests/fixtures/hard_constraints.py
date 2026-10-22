"""Escenarios y constructores para las pruebas de restricciones obligatorias de carteras finales.

Todos los datos son sintéticos y deterministas. ``eleven_asset_problem`` es el caso de aceptación
del mandato: una cartera original de 11 posiciones iguales (``1/11``) en un universo de 16 activos
con volatilidades por activo conocidas y correlación nula, de modo que la volatilidad y la
concentración de cualquier propuesta se derivan analíticamente en el propio test.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from portfolio_engine.config import (
    EngineConfig,
    HardConstraintsConfig,
    MandateLevel,
    MandateSettings,
)
from portfolio_engine.frontiers import FrontierProblem
from portfolio_engine.frontiers.hard_constraint_gate import HardConstraintGate
from portfolio_engine.hard_constraints.resolver import resolve_hard_constraints
from portfolio_engine.hard_constraints.validator import ProposalContext
from portfolio_engine.models.hard_constraints import EffectiveHardConstraints
from portfolio_engine.models.portfolio import PortfolioSpec
from tests.fixtures.problems import base_config, make_problem

N_ASSETS = 16
HELD = 11
POSITION_FLOOR = 0.02
#: Parámetros de la estrategia de banda de los tests (declarados, nunca implícitos).
BAND_PARAMS: Mapping[str, Any] = {
    "band_max_starts": 6,
    "band_max_iterations": 25,
    "band_convergence_tolerance": 1e-9,
}


def mandate_settings(**fields: Any) -> MandateSettings:
    """``MandateSettings`` con ``min_active_weight`` de ejemplo si no se indica otro."""
    fields.setdefault("min_active_weight", POSITION_FLOOR)
    return MandateSettings(**fields)


def with_mandate(
    config: EngineConfig | None = None,
    *,
    profiles: Sequence[MandateLevel] = (),
    portfolios: Sequence[MandateLevel] = (),
    **fields: Any,
) -> EngineConfig:
    """Copia de ``config`` con restricciones obligatorias globales ``fields`` (más niveles)."""
    hard = HardConstraintsConfig(mandate_settings(**fields), tuple(profiles), tuple(portfolios))
    return dataclasses.replace(config or base_config(), hard_constraints=hard)


def eleven_asset_problem(
    config: EngineConfig | None = None,
    *,
    vol: float = 0.20,
    spec: PortfolioSpec | None = None,
    universe_overrides: Mapping[str, list[Any]] | None = None,
) -> FrontierProblem:
    """11 posiciones al ``1/11`` en 16 activos con ``σ_i = vol``, ``ρ = 0`` y ``μ`` creciente."""
    config = config or base_config()
    mu = 0.04 + 0.004 * np.arange(N_ASSETS)
    sigma = np.diag(np.full(N_ASSETS, vol**2))
    current = [1.0 / HELD] * HELD + [0.0] * (N_ASSETS - HELD)
    overrides: dict[str, list[Any]] = {"MaxWeight": [1.0] * N_ASSETS}
    overrides.update(dict(universe_overrides or {}))
    return make_problem(mu, sigma, current, config, universe_overrides=overrides, spec=spec)


def effective_of(config: EngineConfig, problem: FrontierProblem) -> EffectiveHardConstraints:
    """Restricciones efectivas de la cartera del problema (única fuente de verdad)."""
    weights = dict(zip(problem.state.asset_ids, problem.state.weights.tolist(), strict=True))
    return resolve_hard_constraints(config, problem.portfolio_id, problem.spec, weights)


def proposal_context(config: EngineConfig, problem: FrontierProblem) -> ProposalContext:
    """Contexto de validación final del problema, con las restricciones efectivas de ``config``."""
    return HardConstraintGate(config).context(problem, effective_of(config, problem))


def equal_weights(asset_ids: Sequence[str]) -> dict[str, float]:
    """Pesos iguales sobre ``asset_ids``."""
    return {asset_id: 1.0 / len(asset_ids) for asset_id in asset_ids}
