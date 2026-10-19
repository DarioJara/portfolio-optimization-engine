"""CFG-001, CFG-008, CFG-010, CFG-015: secciones del Bloque 4 (conic, sharpe, cvar, exact_mip,
robust, scenarios): todo parámetro numérico procede de aquí, sin valores por defecto implícitos."""

from __future__ import annotations

import copy
import dataclasses
import tomllib

import pytest

from portfolio_engine.config import (
    ConicSolverConfig,
    CVaRConfig,
    ExactMIPConfig,
    SharpeConfig,
    config_hash,
    load_engine_config,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import HorizonScaling, ScenarioWeighting
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def _raw() -> dict[str, object]:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_the_default_configuration_declares_every_block_4_section() -> None:
    config = load_engine_config(DEFAULT_CONFIG_PATH)
    assert isinstance(config.conic, ConicSolverConfig) and config.conic.max_iterations >= 1
    assert isinstance(config.sharpe, SharpeConfig) and config.sharpe.min_excess_return > 0
    assert isinstance(config.cvar, CVaRConfig) and 0.0 < config.cvar.confidence_level < 1.0
    assert isinstance(config.exact_mip, ExactMIPConfig) and config.exact_mip.time_limit_seconds > 0
    assert config.scenarios.probability_sum_tolerance > 0
    assert config.robust.mu_uncertainty.value == "NONE" and config.robust.shrinkage_method is None


@pytest.mark.parametrize("section", ["conic", "sharpe", "cvar", "exact_mip", "robust", "scenarios"])
def test_a_missing_or_unknown_section_or_key_is_an_error(section: str) -> None:
    raw = _raw()
    without = copy.deepcopy(raw)
    del without[section]  # type: ignore[arg-type]
    with pytest.raises(ConfigError, match="ausentes"):
        load_engine_config(without)
    extra = copy.deepcopy(raw)
    extra[section]["typo_key"] = 1  # type: ignore[index]
    with pytest.raises(ConfigError, match="Claves desconocidas"):
        load_engine_config(extra)


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("conic", "tol_gap_abs"),
        ("conic", "tol_gap_rel"),
        ("conic", "tol_feas"),
        ("conic", "tol_infeas_abs"),
        ("conic", "tol_infeas_rel"),
        ("conic", "max_iterations"),
        ("conic", "equilibrate"),
        ("conic", "psd_eigenvalue_relative_tolerance"),
        ("conic", "psd_negative_tolerance"),
        ("conic", "factorization_tolerance"),
        ("sharpe", "min_excess_return"),
        ("sharpe", "agreement_tolerance"),
        ("cvar", "confidence_level"),
        ("cvar", "weighting"),
        ("cvar", "min_tail_observations"),
        ("exact_mip", "time_limit_seconds"),
        ("exact_mip", "relative_gap_tolerance"),
        ("exact_mip", "absolute_gap_tolerance"),
        ("exact_mip", "integrality_tolerance"),
        ("exact_mip", "max_universe_size"),
        ("exact_mip", "threads"),
        ("scenarios", "probability_sum_tolerance"),
        ("scenarios", "correlation_tolerance"),
    ],
)
def test_every_block_4_parameter_is_required_and_changes_the_config_hash(
    section: str, key: str
) -> None:
    raw = _raw()
    missing = copy.deepcopy(raw)
    del missing[section][key]  # type: ignore[attr-defined]
    with pytest.raises(ConfigError, match="obligatoria ausente"):
        load_engine_config(missing)
    base = load_engine_config(raw)
    value = getattr(getattr(base, section), key)
    if isinstance(value, bool):
        changed = {key: not value}
    elif key == "weighting":
        changed = {key: ScenarioWeighting.EXPLICIT}
    elif isinstance(value, int):
        changed = {key: value + 1}
    else:
        changed = {key: value * 0.5}
    other = dataclasses.replace(
        base, **{section: dataclasses.replace(getattr(base, section), **changed)}
    )
    assert config_hash(other) != config_hash(base)


@pytest.mark.parametrize(
    ("factory", "kwargs", "message"),
    [
        (ConicSolverConfig, {"tol_gap_abs": 0.0}, "tol_gap_abs"),
        (ConicSolverConfig, {"max_iterations": 0}, "max_iterations"),
        (ConicSolverConfig, {"equilibrate": 1}, "booleano"),
        (ConicSolverConfig, {"time_limit_seconds": -1.0}, "time_limit"),
        (ConicSolverConfig, {"psd_negative_tolerance": -1e-3}, "psd_negative"),
        (SharpeConfig, {"min_excess_return": 0.0}, "min_excess_return"),
        (SharpeConfig, {"agreement_tolerance": -1.0}, "agreement_tolerance"),
        (CVaRConfig, {"confidence_level": 1.0}, "confidence_level"),
        (CVaRConfig, {"confidence_level": 0.0}, "confidence_level"),
        (CVaRConfig, {"horizon_periods": 0}, "horizon_periods"),
        (CVaRConfig, {"horizon_periods": 5}, "NONE exige"),
        (CVaRConfig, {"min_tail_observations": 0}, "min_tail"),
        (CVaRConfig, {"max_cvar": -0.1}, "max_cvar"),
        (ExactMIPConfig, {"time_limit_seconds": 0.0}, "time_limit"),
        (ExactMIPConfig, {"relative_gap_tolerance": -1.0}, "relative_gap"),
        (ExactMIPConfig, {"max_universe_size": 0}, "max_universe_size"),
        (ExactMIPConfig, {"threads": 0}, "threads"),
        (ExactMIPConfig, {"node_limit": 0}, "node_limit"),
    ],
)
def test_invalid_block_4_parameters_are_rejected(
    factory: type, kwargs: dict[str, object], message: str
) -> None:
    config = load_engine_config(_raw())
    section = {
        ConicSolverConfig: config.conic,
        SharpeConfig: config.sharpe,
        CVaRConfig: config.cvar,
        ExactMIPConfig: config.exact_mip,
    }[factory]
    with pytest.raises(ConfigError, match=message):
        dataclasses.replace(section, **kwargs)


def test_the_cvar_horizon_factor_follows_the_declared_scaling() -> None:
    config = base_config().cvar
    assert config.horizon_factor == 1.0
    linear = dataclasses.replace(config, horizon_scaling=HorizonScaling.LINEAR, horizon_periods=21)
    assert linear.horizon_factor == 21.0
    root = dataclasses.replace(config, horizon_scaling=HorizonScaling.SQRT_TIME, horizon_periods=16)
    assert root.horizon_factor == 4.0
    assert dataclasses.replace(config, max_cvar=0.05).max_cvar == 0.05


def test_the_new_parameters_are_types_checked_like_the_rest_of_the_configuration() -> None:
    raw = _raw()
    wrong = copy.deepcopy(raw)
    wrong["conic"]["equilibrate"] = "yes"  # type: ignore[index]
    with pytest.raises(ConfigError, match="booleano"):
        load_engine_config(wrong)
    wrong = copy.deepcopy(raw)
    wrong["cvar"]["weighting"] = "UNIFORM"  # type: ignore[index]
    with pytest.raises(ConfigError, match="uno de"):
        load_engine_config(wrong)
    wrong = copy.deepcopy(raw)
    wrong["exact_mip"]["max_universe_size"] = 10.5  # type: ignore[index]
    with pytest.raises(ConfigError, match="entero"):
        load_engine_config(wrong)
