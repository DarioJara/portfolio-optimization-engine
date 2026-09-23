"""CFG-014: configuración inmutable en profundidad (test obligatorio del Bloque 1)."""

from __future__ import annotations

import dataclasses

import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.models.enums import CostSource

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("optimization_horizon_years",), 2.0),
        (("random_seed",), 1),
        (("data",), None),
        (("returns", "trading_days_per_year"), 365),
        (("risk", "psd_tolerance"), 0.1),
        (("constraints", "restricted_existing_position_policy"), None),
        (("transaction_costs", "max_unit_cost"), 1.0),
        (("data", "weight_sum_tolerance"), 1.0),
    ],
)
def test_attribute_assignment_is_forbidden(
    config: EngineConfig, path: tuple[str, ...], value: object
) -> None:
    target: object = config
    for name in path[:-1]:
        target = getattr(target, name)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(target, path[-1], value)


def test_collections_inside_config_are_immutable(config: EngineConfig) -> None:
    precedence = config.transaction_costs.source_precedence
    assert isinstance(precedence, tuple)
    with pytest.raises(TypeError):
        precedence[0] = CostSource.ESTIMATED  # type: ignore[index]


def test_no_mutable_containers_anywhere_in_config(config: EngineConfig) -> None:
    def walk(value: object) -> None:
        assert not isinstance(value, (list, dict, set, bytearray)), type(value)
        if dataclasses.is_dataclass(value):
            assert type(value).__dataclass_params__.frozen  # type: ignore[attr-defined]
            for field in dataclasses.fields(value):
                walk(getattr(value, field.name))
        elif isinstance(value, tuple):
            for item in value:
                walk(item)

    walk(config)


def test_replace_creates_new_validated_object(config: EngineConfig) -> None:
    changed = dataclasses.replace(config, optimization_horizon_years=3.0)
    assert config.optimization_horizon_years == 1.0
    assert changed.optimization_horizon_years == 3.0
