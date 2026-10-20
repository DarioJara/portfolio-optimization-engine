"""PAR-007: control de hilos numéricos por worker."""

from __future__ import annotations

import os

import pytest

from portfolio_engine.parallel.threading_control import (
    THREAD_ENV_VARS,
    blas_thread_report,
    limit_blas_threads,
    thread_environment,
    worker_thread_environment,
)

pytestmark = pytest.mark.unit


def test_thread_environment_sets_every_known_variable() -> None:
    environment = thread_environment(2)
    assert set(environment) == set(THREAD_ENV_VARS)
    assert set(environment.values()) == {"2"}
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        assert name in environment


@pytest.mark.parametrize("threads", [0, -3])
def test_invalid_thread_counts_are_rejected(threads: int) -> None:
    with pytest.raises(ValueError, match="threads"):
        thread_environment(threads)
    with pytest.raises(ValueError, match="threads"):
        limit_blas_threads(threads)


def test_the_environment_is_restored_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "7")
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)
    before = dict(os.environ)
    with worker_thread_environment(1):
        assert os.environ["OMP_NUM_THREADS"] == "1"
        assert os.environ["MKL_NUM_THREADS"] == "1"
    assert dict(os.environ) == before


def test_the_environment_is_restored_when_the_block_fails() -> None:
    before = dict(os.environ)
    with pytest.raises(RuntimeError), worker_thread_environment(1):
        raise RuntimeError("fallo dentro del pool")
    assert dict(os.environ) == before


def test_limit_blas_threads_is_observable_and_reversible() -> None:
    reference = blas_thread_report()
    limiter = limit_blas_threads(1)
    try:
        report = blas_thread_report()
        assert len(report) == len(reference)
        assert all(state.num_threads == 1 for state in report)
    finally:
        limiter.restore_original_limits()
    assert blas_thread_report() == reference
