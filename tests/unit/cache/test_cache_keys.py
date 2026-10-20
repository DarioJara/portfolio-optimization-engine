"""CCH-002, CCH-004: la clave canónica es completa y cada componente la cambia por sí solo."""

from __future__ import annotations

import dataclasses

import pytest

from portfolio_engine.cache import OFFICIAL_COMPONENTS, UNSPECIFIED, CacheKey, CacheKeyError

pytestmark = pytest.mark.unit


def make(**changes: str) -> CacheKey:
    values = {field.name: f"{field.name}-0" for field in dataclasses.fields(CacheKey)}
    values.update(changes)
    return CacheKey(**values)


def test_the_key_contains_every_official_component() -> None:
    names = {field.name for field in dataclasses.fields(CacheKey)}
    assert set(OFFICIAL_COMPONENTS) <= names
    assert len(OFFICIAL_COMPONENTS) == 10  # CCH-002: los diez componentes oficiales
    assert {"portfolio_id", "operation_hash", "snapshot_key"} <= names  # extensiones documentadas
    assert "current_portfolio_state_hash" in OFFICIAL_COMPONENTS  # E-06: siempre


@pytest.mark.parametrize("field", [f.name for f in dataclasses.fields(CacheKey)])
def test_changing_any_single_component_changes_the_digest(field: str) -> None:
    assert make().digest != make(**{field: "otro-valor"}).digest


def test_composition_hash_alone_is_not_enough_to_share_an_entry() -> None:
    """CCH-004: misma composición, distinto estado actual ⇒ claves distintas."""
    first = make(current_portfolio_state_hash="estado-A")
    second = make(current_portfolio_state_hash="estado-B")
    assert first.composition_hash == second.composition_hash
    assert first.digest != second.digest


def test_the_digest_is_deterministic_and_order_independent_of_construction() -> None:
    assert make().digest == make().digest
    assert len(make().digest) == 64
    assert dict(make().components)["config_hash"] == "config_hash-0"


@pytest.mark.parametrize("bad", ["", None, 3])
def test_every_component_is_mandatory_and_non_empty(bad: object) -> None:
    with pytest.raises(CacheKeyError):
        make(market_data_timestamp=bad)  # type: ignore[arg-type]


def test_a_missing_timestamp_is_recorded_explicitly_not_omitted() -> None:
    assert make(market_data_timestamp=UNSPECIFIED).digest != make().digest
