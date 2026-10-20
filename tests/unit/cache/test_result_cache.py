"""CCH-001, CCH-003, CCH-005: ``ResultCache`` (resultados reales, acierto sin cálculo, límites)."""

from __future__ import annotations

import dataclasses
import pickle

import numpy as np
import pytest

from portfolio_engine.cache import (
    CacheError,
    CacheEvent,
    CacheKey,
    CacheMetrics,
    ResultCache,
)

pytestmark = pytest.mark.unit


def key(tag: str = "a") -> CacheKey:
    return CacheKey(**{field.name: f"{field.name}-{tag}" for field in dataclasses.fields(CacheKey)})


@dataclasses.dataclass(frozen=True)
class Payload:
    name: str
    weights: np.ndarray  # type: ignore[type-arg]


def payload(size: int = 4, value: float = 1.0) -> Payload:
    return Payload("resultado", np.full(size, value))


def test_it_stores_real_results_and_a_hit_never_calls_the_computation() -> None:
    cache = ResultCache(max_entries=4, max_bytes=10**6)
    calls: list[int] = []

    def compute() -> Payload:
        calls.append(1)
        return payload()

    first, event_1 = cache.get_or_compute(key(), compute)
    second, event_2 = cache.get_or_compute(key(), compute)
    assert (event_1, event_2) == (CacheEvent.MISS, CacheEvent.HIT)
    assert len(calls) == 1  # CCH-003: el acierto elimina el cálculo
    assert second.name == first.name and np.array_equal(second.weights, first.weights)
    metrics = cache.metrics
    assert (metrics.hits, metrics.misses, metrics.stores, metrics.entries) == (1, 1, 1, 1)
    assert metrics.hit_ratio == pytest.approx(0.5)


def test_each_read_returns_a_new_object_so_nothing_mutable_is_shared() -> None:
    cache = ResultCache(max_entries=4, max_bytes=10**6)
    original = payload()
    cache.put(key(), original)
    first, second = cache.get(key()), cache.get(key())
    assert first is not second and first is not original
    first.weights[0] = 99.0  # type: ignore[union-attr]
    assert cache.get(key()).weights[0] == 1.0  # type: ignore[union-attr]
    assert second.weights[0] == 1.0  # type: ignore[union-attr]


def test_entries_are_bounded_with_lru_eviction() -> None:
    cache = ResultCache(max_entries=2, max_bytes=10**6)
    for tag in ("a", "b"):
        cache.put(key(tag), payload())
    assert cache.get(key("a")) is not None  # «a» pasa a ser la más reciente
    cache.put(key("c"), payload())  # expulsa «b» (la menos reciente)
    assert cache.get(key("b")) is None
    assert key("a") in cache and key("c") in cache
    metrics = cache.metrics
    assert metrics.entries == 2 and metrics.evictions == 1


def test_bytes_are_bounded_and_oversized_results_are_rejected() -> None:
    small = len(pickle.dumps(payload(4)))
    cache = ResultCache(max_entries=100, max_bytes=2 * small + 8)
    for tag in "abc":
        cache.put(key(tag), payload(4))
    assert cache.metrics.entries == 2 and cache.metrics.evictions == 1
    assert cache.metrics.bytes <= 2 * small + 8
    assert cache.put(key("big"), payload(10_000)) is False  # mayor que max_bytes
    assert cache.metrics.rejected == 1 and key("big") not in cache
    assert cache.metrics.entries == 2  # el rechazo no expulsa nada


def test_a_computation_that_fails_stores_nothing_and_propagates() -> None:
    cache = ResultCache(max_entries=2, max_bytes=10**6)

    def boom() -> Payload:
        raise ValueError("fallo del motor")

    with pytest.raises(ValueError, match="fallo del motor"):
        cache.get_or_compute(key(), boom)
    assert cache.metrics.entries == 0 and cache.metrics.stores == 0
    assert cache.metrics.misses == 1


def test_results_that_are_not_final_are_returned_but_not_stored() -> None:
    cache = ResultCache(max_entries=2, max_bytes=10**6)
    value, event = cache.get_or_compute(key(), payload, cacheable=lambda _: False)
    assert event is CacheEvent.MISS and value.name == "resultado"
    assert cache.metrics.skipped == 1 and cache.metrics.stores == 0 and key() not in cache


def test_unpicklable_results_are_not_stored() -> None:
    cache = ResultCache(max_entries=2, max_bytes=10**6)
    value, _ = cache.get_or_compute(key(), lambda: lambda: None)
    assert callable(value)
    assert cache.metrics.rejected == 1 and cache.metrics.entries == 0


def test_replacing_an_entry_keeps_the_byte_accounting_exact() -> None:
    cache = ResultCache(max_entries=4, max_bytes=10**6)
    cache.put(key(), payload(4))
    before = cache.metrics.bytes
    cache.put(key(), payload(400))
    assert cache.metrics.entries == 1 and cache.metrics.bytes > before
    cache.clear()
    assert cache.metrics.entries == 0 and cache.metrics.bytes == 0
    assert cache.metrics.stores == 2  # los contadores acumulados se conservan


def test_metrics_aggregate_and_report_deltas() -> None:
    a = CacheMetrics(hits=1, misses=2, stores=2, entries=2, bytes=10)
    b = CacheMetrics(hits=3, misses=1, stores=1, evictions=1, entries=1, bytes=5)
    total = a + b
    assert (total.hits, total.misses, total.evictions, total.entries, total.bytes) == (
        4,
        3,
        1,
        3,
        15,
    )
    assert total.since(a).hits == 3 and total.since(a).entries == total.entries
    assert CacheMetrics().hit_ratio is None


@pytest.mark.parametrize("entries, size", [(0, 1), (1, 0), (-1, 5)])
def test_invalid_limits_are_rejected(entries: int, size: int) -> None:
    with pytest.raises(CacheError):
        ResultCache(max_entries=entries, max_bytes=size)
