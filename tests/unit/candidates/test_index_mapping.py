"""TST-015, DAT-013: mapeo global ↔ elegible ↔ local con activos elegibles no consecutivos."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.candidates import CandidateContext, EligibilityFilter, UniverseSnapshot
from portfolio_engine.exceptions import AssetResolutionError, DataValidationError
from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.models.universe_index import (
    AssetIndex,
    CompositionIndexMap,
    EligibleUniverseIndex,
)
from tests.fixtures.candidates import context_of, corr_matrix
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem, weights_of

pytestmark = pytest.mark.unit

N = 10
ELIGIBLE = [1, 3, 4, 8]  # no consecutivos dentro del universo global de 10 activos


def _problem():  # type: ignore[no-untyped-def]
    config = base_config()
    rng = np.random.default_rng(11)
    mu = np.round(rng.uniform(0.02, 0.15, N), 4)
    sigma = cov_from_vol_corr(np.round(rng.uniform(0.1, 0.3, N), 3), corr_matrix(N, 0.25))
    eligible_flags = [i in ELIGIBLE or i == 0 for i in range(N)]
    problem = make_problem(
        mu,
        sigma,
        [0.5, 0.5] + [0.0] * (N - 2),
        config,
        universe_overrides={"EligibleFlag": eligible_flags, "MaxWeight": [1.0] * N},
    )
    return config, problem, mu, sigma


def test_eligible_index_is_a_non_consecutive_subset_of_the_global_index() -> None:
    index = AssetIndex([f"A{i:03d}" for i in range(N)])
    eligible = EligibleUniverseIndex(index, [8, 1, 4, 3, 3])
    assert eligible.global_indices.tolist() == ELIGIBLE  # ordenado y sin duplicados
    assert eligible.asset_ids == ("A001", "A003", "A004", "A008")
    assert eligible.eligible_of([8, 1]).tolist() == [3, 0]
    assert eligible.global_of([0, 2]).tolist() == [1, 4]
    assert len(eligible) == 4
    # Los índices eligible y global no coinciden: el elegible 3 es el global 8.
    assert eligible.global_of([3]).item() == 8 != 3
    with pytest.raises(AssetResolutionError, match="no elegibles"):
        eligible.eligible_of([0, 1])
    assert eligible.contains_global(4) and not eligible.contains_global(5)
    assert not eligible.contains_global(-1) and not eligible.contains_global(99)
    with pytest.raises(DataValidationError, match="fuera del universo"):
        EligibleUniverseIndex(index, [10])


def test_composition_map_links_the_three_levels() -> None:
    index = AssetIndex([f"A{i:03d}" for i in range(N)])
    eligible = EligibleUniverseIndex(index, ELIGIBLE)
    mapping = CompositionIndexMap.build(eligible, ["A008", "A001", "A004"])
    assert mapping.asset_ids == ("A001", "A004", "A008")
    assert mapping.global_indices.tolist() == [1, 4, 8]
    assert mapping.eligible_indices.tolist() == [0, 2, 3]
    assert mapping.size == 3
    # local != global: el activo global 8 es el local 2.
    assert mapping.local_of_global(8) == 2 and mapping.local_of_global(1) == 0
    with pytest.raises(AssetResolutionError, match="fuera de la composición"):
        mapping.local_of_global(3)


def test_held_non_eligible_asset_has_a_sentinel_eligible_index() -> None:
    index = AssetIndex([f"A{i:03d}" for i in range(N)])
    eligible = EligibleUniverseIndex(index, ELIGIBLE)
    mapping = CompositionIndexMap.build(eligible, ["A000", "A003"])
    assert mapping.global_indices.tolist() == [0, 3]
    assert mapping.eligible_indices.tolist() == [-1, 1]


def test_local_submatrix_and_vector_come_from_the_global_arrays_by_asset_identity() -> None:
    _, _, mu, sigma = _problem()
    index = AssetIndex([f"A{i:03d}" for i in range(N)])
    mapping = CompositionIndexMap.build(
        EligibleUniverseIndex(index, ELIGIBLE), ["A008", "A001", "A004"]
    )
    local_sigma = mapping.extract_submatrix(sigma)
    local_mu = mapping.extract_vector(mu)
    order = [1, 4, 8]
    expected_sigma = np.array([[sigma[i, j] for j in order] for i in order])
    assert local_sigma.shape == (3, 3) and np.array_equal(local_sigma, expected_sigma)
    assert np.array_equal(local_mu, mu[order])
    # ``np.ix_`` produce una copia: escribir en ella no toca la matriz global.
    assert not np.shares_memory(local_sigma, sigma)
    local_sigma[0, 0] = -1.0
    assert sigma[1, 1] != -1.0


def test_a_global_index_is_never_used_as_a_local_index() -> None:
    """Interpretar la posición global 8 como local dentro de una composición de 3 activos falla."""
    _, _, _, sigma = _problem()
    index = AssetIndex([f"A{i:03d}" for i in range(N)])
    mapping = CompositionIndexMap.build(
        EligibleUniverseIndex(index, ELIGIBLE), ["A001", "A004", "A008"]
    )
    local_sigma = mapping.extract_submatrix(sigma)
    with pytest.raises(IndexError):
        _ = local_sigma[8, 8]


def test_invalid_maps_are_rejected() -> None:
    with pytest.raises(DataValidationError, match="ordenados"):
        CompositionIndexMap(("A001", "A000"), np.array([1, 0]), np.array([0, 0]))
    with pytest.raises(DataValidationError, match="crecientes"):
        CompositionIndexMap(("A000", "A001"), np.array([1, 1]), np.array([0, 0]))
    with pytest.raises(DataValidationError, match="Dimensiones"):
        CompositionIndexMap(("A000", "A001"), np.array([0]), np.array([0, 1]))


def test_snapshot_and_filter_use_asset_identity_not_the_universe_order() -> None:
    """La cartera y el modelo de riesgo pueden tener índices distintos: se mapea por AssetID."""
    config, problem, _, _ = _problem()
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    assert snapshot.sigma is problem.risk_model.sigma  # referencia, no copia
    assert snapshot.mu is problem.risk_model.mu
    result = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    assert result.enterable.global_indices.tolist() == [0, 1, 3, 4, 8]  # A000/A001 en cartera
    assert result.enterable.asset_ids == ("A000", "A001", "A003", "A004", "A008")
    assert result.held_positions.tolist() == [0, 1]


def test_the_frontier_engine_uses_the_same_local_order_as_the_map() -> None:
    """Σ_C del mapa coincide con la que usa el motor continuo para la misma composición."""
    config, problem, mu, sigma = _problem()
    ids = ("A001", "A004", "A008")
    from dataclasses import replace

    solved = ContinuousFrontierEngine(config).solve(
        replace(problem, composition_asset_ids=ids),
        CostTreatment.GROSS,
        FrontierMethod.RISK_AVERSION_GRID,
    )
    assert solved.asset_ids == ids
    mapping = CompositionIndexMap.build(
        EligibleUniverseIndex(AssetIndex(problem.risk_model.asset_ids), ELIGIBLE), ids
    )
    local_sigma, local_mu = mapping.extract_submatrix(sigma), mapping.extract_vector(mu)
    for point in solved.valid_points:
        weights = weights_of(point)
        assert point.metrics is not None
        assert point.metrics.volatility == pytest.approx(
            float(np.sqrt(weights @ local_sigma @ weights))
        )
        assert point.metrics.expected_return_gross == pytest.approx(float(local_mu @ weights))


def test_context_helper_exposes_the_same_problem_data() -> None:
    _, problem, _, _ = _problem()
    context = context_of(problem)
    assert isinstance(context, CandidateContext) and context.state is problem.state
