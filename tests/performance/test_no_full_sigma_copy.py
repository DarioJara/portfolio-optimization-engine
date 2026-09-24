"""PAR-006, CAN-012: el CandidateEngine no copia ``Sigma`` global (700×700) por cartera.

Con un universo de 700 activos y una cartera de 20, la generación de composiciones solo extrae los
bloques ``|E|×n`` (screening) y ``n×n`` (composición); jamás ``Sigma[eligible, eligible]``. Se mide
con ``tracemalloc`` el pico de memoria de la generación: una sola copia completa de ``Sigma``
(700² · 8 B ≈ 3,9 MB) ya lo superaría. La medida es descriptiva (no un umbral de producción).
"""

from __future__ import annotations

import tracemalloc

import numpy as np
import pytest

from portfolio_engine.candidates import UniverseSnapshot
from tests.fixtures.candidates import prepared_for, search
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem

pytestmark = pytest.mark.performance

N = 700
HELD = 20
FULL_SIGMA_BYTES = N * N * 8


@pytest.fixture(scope="module")
def big_problem():  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(1)
    config = base_config(
        candidates={
            "max_evaluations": 40,
            "utility_risk_aversions": [4.0],
            "refinement_iterations": 5,
            "max_levels": 2,
            "shortlist_in": 10,
        }
    )
    factors = rng.normal(size=(N, 8))
    covariance = factors @ factors.T + np.diag(rng.uniform(0.5, 2.0, N))
    correlation = covariance / np.sqrt(np.outer(np.diag(covariance), np.diag(covariance)))
    sigma = cov_from_vol_corr(rng.uniform(0.1, 0.4, N), correlation)
    current = [0.0] * N
    for i in range(HELD):
        current[i * 7] = 1.0 / HELD
    problem = make_problem(
        rng.uniform(0.02, 0.15, N),
        sigma,
        current,
        config,
        universe_overrides={"MaxWeight": [0.2] * N},
    )
    return config, problem


def test_the_snapshot_and_the_engine_share_the_global_covariance_without_copying(
    big_problem,
) -> None:  # type: ignore[no-untyped-def]
    _config, problem = big_problem
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    assert snapshot.sigma is problem.risk_model.sigma and snapshot.mu is problem.risk_model.mu
    assert np.shares_memory(snapshot.sigma, problem.risk_model.sigma)
    assert not snapshot.sigma.flags.writeable  # solo lectura


def test_local_covariance_is_extracted_only_for_the_defined_composition(big_problem) -> None:  # type: ignore[no-untyped-def]
    config, problem = big_problem
    held = problem.state.asset_ids
    prepared = prepared_for(problem, config, held)
    assert prepared.sigma.shape == (HELD, HELD)  # Σ_20×20, no Σ_700×700
    assert prepared.sigma.nbytes == HELD * HELD * 8 < FULL_SIGMA_BYTES / 1000
    assert not np.shares_memory(prepared.sigma, problem.risk_model.sigma)  # copia pequeña explícita


def test_generation_never_allocates_a_full_sigma_copy(big_problem) -> None:  # type: ignore[no-untyped-def]
    config, problem = big_problem
    tracemalloc.start()
    try:
        result = search(config, problem)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(result.compositions) > 1
    assert result.diagnostics.total_evaluated > 0
    # una sola copia de Sigma[eligible, eligible] ya costaría ≥ FULL_SIGMA_BYTES
    assert peak < 0.6 * FULL_SIGMA_BYTES, (
        f"pico {peak / 1e6:.2f} MB vs Σ completa {FULL_SIGMA_BYTES / 1e6:.2f} MB"
    )
