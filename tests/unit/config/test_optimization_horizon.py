"""CFG-018: OptimizationHorizonYears centralizado (enmienda E-03)."""

from __future__ import annotations

import dataclasses
import math
import tomllib

import pytest

from portfolio_engine.config import EngineConfig, config_hash, load_engine_config
from portfolio_engine.exceptions import ConfigError
from tests.conftest import DEFAULT_CONFIG_PATH

pytestmark = pytest.mark.unit


def _raw() -> dict[str, dict[str, object]]:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_default_horizon_comes_from_configuration_file(config: EngineConfig) -> None:
    assert config.optimization_horizon_years == 1.0


def test_horizon_is_mandatory_no_code_default() -> None:
    raw = _raw()
    del raw["engine"]["optimization_horizon_years"]
    with pytest.raises(ConfigError, match="optimization_horizon_years"):
        load_engine_config(raw)


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan])
def test_non_positive_or_non_finite_horizon_rejected(config: EngineConfig, value: float) -> None:
    with pytest.raises(ConfigError, match="optimization_horizon_years"):
        dataclasses.replace(config, optimization_horizon_years=value)


def test_integer_horizon_in_toml_is_accepted_as_float() -> None:
    raw = _raw()
    raw["engine"]["optimization_horizon_years"] = 2
    config = load_engine_config(raw)
    assert config.optimization_horizon_years == 2.0
    assert isinstance(config.optimization_horizon_years, float)


def test_horizon_changes_config_hash(config: EngineConfig) -> None:
    other = dataclasses.replace(config, optimization_horizon_years=0.5)
    assert config_hash(other) != config_hash(config)


def test_single_source_of_truth_for_horizon(config: EngineConfig) -> None:
    """Ninguna subconfiguración declara otro parámetro de horizonte."""
    for section in ("data", "returns", "risk", "constraints", "transaction_costs"):
        names = [field.name for field in dataclasses.fields(getattr(config, section))]
        assert not [name for name in names if "horizon" in name or "amortiz" in name], section
