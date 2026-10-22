"""HC-001..HC-005: configuración declarativa, carga estricta y compatibilidad del ``ConfigHash``."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from portfolio_engine.config import (
    CardinalityPolicy,
    MandateSettings,
    config_hash,
    config_snapshot,
    config_to_dict,
    load_engine_config,
    load_hard_constraints,
)
from portfolio_engine.config.hard_constraints_config import TOLERANCE_CEILING
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import CostTreatment, VolatilityBandEnforcement
from tests.conftest import DEFAULT_CONFIG_PATH, REPO_ROOT
from tests.fixtures.hard_constraints import with_mandate
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

EXAMPLE = REPO_ROOT / "config" / "example_hard_constraints.toml"


def test_the_example_file_loads_with_all_three_levels() -> None:
    hard = load_hard_constraints(EXAMPLE)
    glob = hard.global_settings
    assert glob.cardinality_policy is CardinalityPolicy.FIXED
    assert glob.volatility_band_enforcement is VolatilityBandEnforcement.HARD
    assert (glob.min_volatility, glob.max_volatility) == (0.08, 0.18)
    assert glob.expected_return_treatment is CostTreatment.GROSS
    assert [level.name for level in hard.profiles] == ["CONSERVATIVE"]
    p1, p2 = hard.portfolio("P1"), hard.portfolio("P2")
    assert p1 is not None and p1.profile == "CONSERVATIVE"
    assert p2 is not None and [a.field for a in p2.relaxations] == ["max_volatility"]


def test_the_engine_toml_accepts_an_inline_hard_constraints_table(tmp_path: Path) -> None:
    text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    text += '\n[hard_constraints]\ncardinality_policy = "FIXED"\nmin_active_weight = 0.02\n'
    path = tmp_path / "engine.toml"
    path.write_text(text, encoding="utf-8")
    config = load_engine_config(path)
    assert config.hard_constraints is not None
    assert config.hard_constraints.global_settings.min_active_weight == 0.02


def test_without_the_section_the_engine_and_its_config_hash_are_unchanged() -> None:
    config = load_engine_config(DEFAULT_CONFIG_PATH)
    assert config.hard_constraints is None
    assert "hard_constraints" not in config_to_dict(config)
    assert "hard_constraints" not in config_snapshot(config)
    # con el mandato el hash cambia y cualquier parámetro lo mueve
    mandated = with_mandate(config, max_volatility=0.2)
    assert "hard_constraints" in config_to_dict(mandated)
    assert config_hash(mandated) != config_hash(config)
    assert config_hash(with_mandate(config, max_volatility=0.21)) != config_hash(mandated)


def test_unknown_keys_and_wrong_types_are_configuration_errors() -> None:
    for raw in (
        {"bogus": 1},
        {"max_volatility": "alto"},
        {"max_replacements": 1.5},
        {"cardinality_policy": "SHRINK"},
        {"volatility_band_enforcement": "SOFT"},
        {"expected_return_treatment": "POST_COST_GROSS"},
        {"profiles": []},
        {"portfolios": {"P1": {"relaxation_authorizations": [{"field": "max_volatility"}]}}},
    ):
        with pytest.raises(ConfigError):
            load_hard_constraints(raw)


def test_values_are_validated_when_the_settings_are_built() -> None:
    bad = [
        {"max_volatility": 0.0},
        {"max_volatility": float("inf")},
        {"min_volatility": -0.1},
        {"min_active_weight": 0.0},
        {"max_active_weight": 1.5},
        {"max_concentration_hhi": 0.0},
        {"min_effective_number_of_positions": 0.0},
        {"max_replacements": -1},
        {"target_size": 0},
        {"position_weight_threshold": 1.0},
        {"volatility_tolerance": TOLERANCE_CEILING * 10},
        {"band_max_starts": 0},
    ]
    for fields in bad:
        with pytest.raises(ConfigError):
            MandateSettings(**fields)
    MandateSettings(volatility_tolerance=TOLERANCE_CEILING)  # el techo es admisible


def test_there_is_no_soft_volatility_mode() -> None:
    assert [mode.value for mode in VolatilityBandEnforcement] == ["HARD"]
    assert config_hash(base_config()) == config_hash(base_config())
    reloaded = dataclasses.replace(base_config())
    assert reloaded.hard_constraints is None
