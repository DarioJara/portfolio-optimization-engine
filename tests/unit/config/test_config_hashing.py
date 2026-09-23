"""CFG-017: ConfigSnapshot canónico y ConfigHash determinista."""

from __future__ import annotations

import copy
import json
import tomllib

import pytest

from portfolio_engine.config import config_hash, config_snapshot, load_engine_config
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.synthetic import replace_section

pytestmark = pytest.mark.unit


def _raw() -> dict[str, dict[str, object]]:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_hash_independent_of_key_order() -> None:
    raw = _raw()
    reordered = {section: dict(reversed(list(values.items()))) for section, values in raw.items()}
    reordered = dict(reversed(list(reordered.items())))
    assert config_hash(load_engine_config(raw)) == config_hash(load_engine_config(reordered))


def test_hash_is_stable_value() -> None:
    first = config_hash(load_engine_config(_raw()))
    second = config_hash(load_engine_config(copy.deepcopy(_raw())))
    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    ("section", "changes"),
    [
        ("returns", {"trading_days_per_year": 260}),
        ("risk", {"psd_tolerance": 1e-9}),
        ("data", {"max_stale_run": 6}),
        ("transaction_costs", {"max_unit_cost": 0.051}),
        ("constraints", {"restricted_existing_position_policy": None}),
    ],
)
def test_any_parameter_change_changes_hash(section: str, changes: dict[str, object]) -> None:
    base = load_engine_config(_raw())
    assert config_hash(replace_section(base, section, **changes)) != config_hash(base)


def test_snapshot_is_complete_canonical_json() -> None:
    config = load_engine_config(_raw())
    snapshot = json.loads(config_snapshot(config))
    assert set(snapshot) == {
        "data",
        "returns",
        "risk",
        "constraints",
        "transaction_costs",
        "optimization_horizon_years",
        "random_seed",
    }
    assert snapshot["risk"]["covariance_method"] == "LEDOIT_WOLF"
    assert config_snapshot(config) == json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
