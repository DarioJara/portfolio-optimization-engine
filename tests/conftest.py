"""Fixtures comunes de tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_engine.config import EngineConfig, load_engine_config
from portfolio_engine.data.validation import UniverseValidator
from portfolio_engine.models.asset import Universe
from tests.fixtures.synthetic import universe_frame

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default_engine.toml"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def config() -> EngineConfig:
    """Configuración de ejemplo del repositorio (incluye HOLD_OR_REDUCE, E-09)."""
    return load_engine_config(DEFAULT_CONFIG_PATH)


@pytest.fixture()
def universe(config: EngineConfig) -> Universe:
    """Universo sintético válido de 6 activos."""
    return UniverseValidator(config.constraints).validate(universe_frame(6)).universe
