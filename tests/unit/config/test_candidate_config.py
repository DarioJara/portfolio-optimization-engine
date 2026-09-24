"""CFG-009: ``CandidateConfig`` (BeamWidth, swaps, pesos de señales, exploración, presupuestos)."""

from __future__ import annotations

import copy
import dataclasses
import re
import tomllib

import pytest

from portfolio_engine.config import (
    CandidateConfig,
    ExplorationMix,
    ScreeningWeights,
    config_hash,
    load_engine_config,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import (
    EvaluationMode,
    MissingSignalPolicy,
    ScreeningNormalization,
    UnknownFlagPolicy,
)
from tests.conftest import DEFAULT_CONFIG_PATH, REPO_ROOT
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def _raw() -> dict[str, dict[str, object]]:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_default_configuration_declares_the_candidate_section() -> None:
    """Los valores de ejemplo viven solo en ``default_engine.toml`` (A-29) y se cargan tipados."""
    config = load_engine_config(_raw())
    candidates = config.candidates
    assert isinstance(candidates, CandidateConfig)
    assert candidates.beam_width > 1 and candidates.swap_orders == (1, 2)
    assert isinstance(candidates.screening_weights, ScreeningWeights)
    assert isinstance(candidates.exploration, ExplorationMix)
    assert candidates.evaluation_mode is EvaluationMode.PROJECTED_WEIGHTS
    assert candidates.normalization is ScreeningNormalization.RANK
    assert candidates.missing_signal_policy is MissingSignalPolicy.NEUTRAL
    assert candidates.unknown_liquidity_policy is UnknownFlagPolicy.EXCLUDE
    assert candidates.max_new_assets is None and candidates.max_swaps is None
    assert candidates.utility_risk_aversions == tuple(sorted(candidates.utility_risk_aversions))


def test_missing_section_and_missing_key_are_errors() -> None:
    raw = _raw()
    del raw["candidates"]
    with pytest.raises(ConfigError, match="candidates"):
        load_engine_config(raw)
    raw = _raw()
    del raw["candidates"]["beam_width"]  # type: ignore[attr-defined]
    with pytest.raises(ConfigError, match=r"candidates\.beam_width"):
        load_engine_config(raw)


def test_unknown_keys_are_rejected_including_nested_tables() -> None:
    raw = _raw()
    raw["candidates"]["surprise"] = 1  # type: ignore[index]
    with pytest.raises(ConfigError, match="surprise"):
        load_engine_config(raw)
    raw = _raw()
    raw["candidates"]["screening_weights"]["surprise"] = 1.0  # type: ignore[index]
    with pytest.raises(ConfigError, match="surprise"):
        load_engine_config(raw)
    raw = _raw()
    del raw["candidates"]["exploration"]["explore_share"]  # type: ignore[attr-defined,index]
    with pytest.raises(ConfigError, match="explore_share"):
        load_engine_config(raw)


def test_optional_limits_can_be_declared() -> None:
    raw = _raw()
    raw["candidates"]["max_new_assets"] = 2  # type: ignore[index]
    raw["candidates"]["max_swaps"] = 3  # type: ignore[index]
    config = load_engine_config(raw)
    assert config.candidates.max_new_assets == 2 and config.candidates.max_swaps == 3


@pytest.mark.parametrize(
    "field",
    [
        "beam_width",
        "max_levels",
        "shortlist_in",
        "shortlist_out",
        "max_neighbors_per_order",
        "max_evaluations",
        "max_candidates",
        "stagnation_levels",
        "diversity_min_distance",
    ],
)
def test_positive_integer_parameters_reject_zero(field: str) -> None:
    candidates = base_config().candidates
    with pytest.raises(ConfigError, match=field):
        dataclasses.replace(candidates, **{field: 0})


def test_swap_orders_must_be_positive_strictly_increasing_and_non_empty() -> None:
    candidates = base_config().candidates
    for bad in ((), (0, 1), (2, 1), (1, 1)):
        with pytest.raises(ConfigError, match="swap_orders"):
            dataclasses.replace(candidates, swap_orders=bad)
    assert dataclasses.replace(candidates, swap_orders=(1, 2, 3)).swap_orders == (1, 2, 3)


def test_risk_aversion_profiles_must_be_positive_increasing_and_non_empty() -> None:
    candidates = base_config().candidates
    for bad in ((), (0.0, 1.0), (-1.0,), (2.0, 1.0), (1.0, 1.0), (float("inf"),)):
        with pytest.raises(ConfigError, match="utility_risk_aversions"):
            dataclasses.replace(candidates, utility_risk_aversions=bad)


def test_signal_weights_and_exploration_shares_must_be_valid() -> None:
    weights = base_config().candidates.screening_weights
    with pytest.raises(ConfigError, match="al menos un peso"):
        ScreeningWeights(*(0.0,) * len(weights.as_tuple()))
    with pytest.raises(ConfigError, match="liquidity"):
        dataclasses.replace(weights, liquidity=-0.1)
    with pytest.raises(ConfigError, match="al menos un reparto"):
        ExplorationMix(0.0, 0.0, 0.0)
    with pytest.raises(ConfigError, match="explore_share"):
        ExplorationMix(1.0, 0.0, -1.0)


def test_qp_mode_rejects_refinement_iterations_as_an_ignored_parameter() -> None:
    candidates = base_config().candidates
    with pytest.raises(ConfigError, match="refinement_iterations"):
        dataclasses.replace(candidates, evaluation_mode=EvaluationMode.QP_UTILITY)
    ok = dataclasses.replace(
        candidates, evaluation_mode=EvaluationMode.QP_UTILITY, refinement_iterations=0
    )
    assert ok.evaluation_mode is EvaluationMode.QP_UTILITY


def test_candidate_parameters_change_the_config_hash() -> None:
    base = base_config()
    changes = {
        "beam_width": 7,
        "max_levels": 9,
        "swap_orders": (1, 2, 3),
        "shortlist_in": 11,
        "shortlist_out": 12,
        "max_neighbors_per_order": 13,
        "max_evaluations": 14,
        "max_candidates": 15,
        "stagnation_levels": 5,
        "improvement_tolerance": 1e-6,
        "diversity_min_distance": 2,
        "local_search_starts": 4,
        "utility_risk_aversions": (0.5, 2.0),
        "refinement_iterations": 3,
        "normalization": ScreeningNormalization.ZSCORE,
        "missing_signal_policy": MissingSignalPolicy.EXCLUDE,
        "unknown_liquidity_policy": UnknownFlagPolicy.ALLOW,
        "max_new_assets": 1,
        "max_swaps": 1,
        "cold_start": False,
        "max_recorded_rejections": 5,
        "screening_weights": dataclasses.replace(base.candidates.screening_weights, sector_fit=9.0),
        "exploration": ExplorationMix(1.0, 1.0, 1.0),
    }
    assert set(changes) == {f.name for f in dataclasses.fields(CandidateConfig)} - {
        "evaluation_mode"
    }
    for name, value in changes.items():
        other = dataclasses.replace(
            base, candidates=dataclasses.replace(base.candidates, **{name: value})
        )
        assert config_hash(other) != config_hash(base), name


def test_every_candidate_parameter_is_consumed_by_the_engine_code() -> None:
    """Sin parámetros declarados pero ignorados: cada campo se lee fuera de ``config/``."""
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for folder in ("candidates", "frontiers", "validation", "constraints")
        for path in (REPO_ROOT / "portfolio_engine" / folder).rglob("*.py")
    )
    unused = [
        field.name
        for field in dataclasses.fields(CandidateConfig)
        if not re.search(rf"\.{field.name}\b", sources)
    ]
    assert not unused, unused


def test_no_candidate_numbers_are_hardcoded_in_the_toml_free_code() -> None:
    """Los pesos 70/20/10 y demás valores de ejemplo solo existen en el TOML de configuración."""
    exploration = _raw()["candidates"]["exploration"]  # type: ignore[index]
    assert exploration["exploit_share"] == 7.0  # type: ignore[index]
    code = (REPO_ROOT / "portfolio_engine" / "candidates" / "exploration.py").read_text(
        encoding="utf-8"
    )
    assert "0.7" not in code and "70" not in code


def test_configuration_is_immutable() -> None:
    config = load_engine_config(copy.deepcopy(_raw()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.candidates.beam_width = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.candidates.screening_weights.liquidity = 1.0  # type: ignore[misc]
    assert isinstance(config.candidates.swap_orders, tuple)
