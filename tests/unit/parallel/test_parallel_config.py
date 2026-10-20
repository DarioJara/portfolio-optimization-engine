"""CFG-011, PAR-012: ``ParallelConfig`` (carga estricta, validación y ausencia de ``cpu_count``)."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

import pytest

from portfolio_engine.config import ParallelConfig, ProcessStartMethod, load_parallel_config
from portfolio_engine.exceptions import ConfigError
from tests.conftest import DEFAULT_PARALLEL_CONFIG_PATH

pytestmark = pytest.mark.unit

VALID: dict[str, Any] = {
    "workers": 3,
    "auto_batches_per_worker": 4,
    "max_batch_size": 50,
    "max_in_flight_batches_per_worker": 2,
    "start_method": "SPAWN",
    "blas_threads": 1,
    "shared_data_mode": "BUNDLE_FILE",
    "cache": {"enabled": False, "max_entries": 8, "max_bytes": 1024},
    "recovery": {
        "max_task_attempts": 2,
        "max_rebuilds_without_progress": 3,
        "max_total_rebuilds": 10,
        "supervision_poll_seconds": 0.1,
        "cancel_grace_seconds": 0.0,
        "journal_enabled": False,
        "max_message_chars": 200,
    },
}


def _load(**changes: Any) -> ParallelConfig:
    values: Mapping[str, Any] = {**VALID, **changes}
    return load_parallel_config({"parallel": values})


def test_the_example_file_loads_and_optional_keys_are_not_configured() -> None:
    config = load_parallel_config(DEFAULT_PARALLEL_CONFIG_PATH)
    assert config.batch_size is None  # AUTO
    assert config.max_tasks_per_child is None
    assert config.start_method is ProcessStartMethod.SPAWN
    assert config.blas_threads == 1
    assert config.max_in_flight_batches == config.workers * config.max_in_flight_batches_per_worker


@pytest.mark.parametrize("missing", sorted(VALID))
def test_every_mandatory_key_must_be_present(missing: str) -> None:
    values = {key: value for key, value in VALID.items() if key != missing}
    with pytest.raises(ConfigError, match=missing):
        load_parallel_config({"parallel": values})


def test_workers_has_no_implicit_default() -> None:
    """PAR-012: sin ``workers`` explícito la carga falla; nunca se deduce de la CPU."""
    values = {key: value for key, value in VALID.items() if key != "workers"}
    with pytest.raises(ConfigError, match="workers"):
        load_parallel_config({"parallel": values})


def test_unknown_keys_and_sections_are_rejected() -> None:
    with pytest.raises(ConfigError, match="desconocidas"):
        _load(unexpected=1)
    with pytest.raises(ConfigError, match="desconocidas"):
        load_parallel_config({"parallel": VALID, "other": {}})
    with pytest.raises(ConfigError, match="ausente"):
        load_parallel_config({})


@pytest.mark.parametrize(
    "field",
    [
        "workers",
        "auto_batches_per_worker",
        "max_batch_size",
        "max_in_flight_batches_per_worker",
        "blas_threads",
    ],
)
@pytest.mark.parametrize("bad", [0, -1])
def test_counts_must_be_at_least_one(field: str, bad: int) -> None:
    with pytest.raises(ConfigError, match=field):
        _load(**{field: bad})


def test_optional_counts_are_validated_when_present() -> None:
    assert _load(batch_size=5).batch_size == 5
    assert _load(max_tasks_per_child=7).max_tasks_per_child == 7
    with pytest.raises(ConfigError, match="batch_size"):
        _load(batch_size=0)
    with pytest.raises(ConfigError, match="max_tasks_per_child"):
        _load(max_tasks_per_child=0)


def test_batch_size_cannot_exceed_the_maximum() -> None:
    with pytest.raises(ConfigError, match="max_batch_size"):
        _load(batch_size=51)


def test_booleans_are_not_integers() -> None:
    with pytest.raises(ConfigError, match="workers"):
        _load(workers=True)


def test_fork_is_not_an_accepted_start_method() -> None:
    """``fork`` es inseguro con librerías con hilos: no existe como opción."""
    assert {method.name for method in ProcessStartMethod} == {"SPAWN", "FORKSERVER"}
    with pytest.raises(ConfigError, match="start_method"):
        _load(start_method="FORK")


def test_config_is_immutable() -> None:
    config = _load()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.workers = 9  # type: ignore[misc]


# ------------------------------------------------------------------------------ recuperación (B5.4)


def test_recovery_limits_come_from_the_example_file_and_timeouts_are_optional() -> None:
    recovery = load_parallel_config(DEFAULT_PARALLEL_CONFIG_PATH).recovery
    assert recovery.task_timeout_seconds is None and recovery.batch_timeout_seconds is None
    assert recovery.journal_enabled is False  # el diario es opt-in
    assert recovery.max_task_attempts >= 1


@pytest.mark.parametrize(
    "missing",
    [
        "max_task_attempts",
        "max_rebuilds_without_progress",
        "max_total_rebuilds",
        "supervision_poll_seconds",
        "cancel_grace_seconds",
        "journal_enabled",
        "max_message_chars",
    ],
)
def test_every_mandatory_recovery_key_must_be_present(missing: str) -> None:
    recovery = {key: value for key, value in VALID["recovery"].items() if key != missing}
    with pytest.raises(ConfigError, match=missing):
        _load(recovery=recovery)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("max_task_attempts", 0),
        ("max_rebuilds_without_progress", 0),
        ("max_total_rebuilds", -1),
        ("max_message_chars", 0),
        ("supervision_poll_seconds", 0.0),
        ("task_timeout_seconds", 0.0),
        ("batch_timeout_seconds", -5.0),
        ("cancel_grace_seconds", -0.1),
    ],
)
def test_recovery_values_are_validated(field: str, bad: float) -> None:
    with pytest.raises(ConfigError, match=field):
        _load(recovery={**VALID["recovery"], field: bad})


def test_recovery_rejects_unknown_keys_and_non_boolean_journal_flag() -> None:
    with pytest.raises(ConfigError, match="desconocidas"):
        _load(recovery={**VALID["recovery"], "retries": 3})
    with pytest.raises(ConfigError, match="journal_enabled"):
        _load(recovery={**VALID["recovery"], "journal_enabled": 1})
