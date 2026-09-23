"""RSK-010 … RSK-012: reparación PSD y su registro (obligatorio B1)."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.config import EngineConfig
from portfolio_engine.exceptions import CovarianceEstimationError, NotPositiveSemidefiniteError
from portfolio_engine.models.enums import CovarianceMethod, PSDRepairMethod
from portfolio_engine.risk import CovarianceBuilder, eigenvalue_floor_repair, nearest_psd_repair
from tests.fixtures.synthetic import replace_section

pytestmark = pytest.mark.unit

INDEFINITE = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])
IDS = ("A", "B", "C")


def _builder(config: EngineConfig, **risk_changes: object) -> CovarianceBuilder:
    risk = replace_section(config, "risk", **risk_changes).risk
    return CovarianceBuilder(risk, config.returns.trading_days_per_year)


def test_nearest_psd_is_frobenius_projection() -> None:
    eigenvalues, vectors = np.linalg.eigh(INDEFINITE)
    assert eigenvalues[0] < 0
    repaired = nearest_psd_repair(INDEFINITE)
    np.testing.assert_allclose(
        repaired, (vectors * np.maximum(eigenvalues, 0)) @ vectors.T, atol=1e-14
    )
    assert np.linalg.eigvalsh(repaired)[0] >= -1e-14
    distance = np.linalg.norm(repaired - INDEFINITE, "fro")
    assert distance == pytest.approx(np.sqrt(np.sum(np.minimum(eigenvalues, 0) ** 2)))
    floored = eigenvalue_floor_repair(INDEFINITE, 1e-3)
    assert distance < np.linalg.norm(floored - INDEFINITE, "fro")


def test_nearest_psd_leaves_psd_matrix_unchanged() -> None:
    psd = np.array([[2.0, 0.5], [0.5, 1.0]])
    np.testing.assert_allclose(nearest_psd_repair(psd), psd, atol=1e-14)


def test_eigenvalue_floor_bounds_condition_number() -> None:
    floor = 1e-4
    repaired = eigenvalue_floor_repair(INDEFINITE, floor)
    eigenvalues = np.linalg.eigvalsh(repaired)
    assert eigenvalues[0] >= floor * eigenvalues[-1] * (1 - 1e-9)
    assert eigenvalues[-1] / eigenvalues[0] <= (1 / floor) * (1 + 1e-9)
    np.testing.assert_array_equal(repaired, repaired.T)


def test_builder_repairs_non_psd_and_records_everything(config: EngineConfig) -> None:
    estimate = _builder(config).validate(INDEFINITE, IDS, CovarianceMethod.EMPIRICAL, None, 10)
    report = estimate.repair
    assert report is not None
    assert report.method is PSDRepairMethod.EIGENVALUE_FLOOR
    assert report.reason == "NOT_PSD"
    assert report.original_min_eigenvalue == pytest.approx(np.linalg.eigvalsh(INDEFINITE)[0])
    assert report.corrected_min_eigenvalue > 0
    assert report.correction_magnitude == pytest.approx(
        np.linalg.norm(estimate.matrix - INDEFINITE, "fro")
    )
    assert report.correction_magnitude > 0
    assert estimate.final_diagnostics.is_psd
    assert not estimate.original_diagnostics.is_psd
    assert estimate.condition_number == report.corrected_condition_number


def test_builder_nearest_psd_method(config: EngineConfig) -> None:
    estimate = _builder(
        config, repair_method=PSDRepairMethod.NEAREST_PSD, eigenvalue_floor_relative=None
    ).validate(INDEFINITE, IDS, CovarianceMethod.EMPIRICAL, None, 10)
    assert estimate.repair is not None
    assert estimate.repair.method is PSDRepairMethod.NEAREST_PSD
    np.testing.assert_allclose(estimate.matrix, nearest_psd_repair(INDEFINITE), atol=1e-15)


def test_no_repair_configured_raises(config: EngineConfig) -> None:
    builder = _builder(config, repair_method=PSDRepairMethod.NONE, eigenvalue_floor_relative=None)
    with pytest.raises(NotPositiveSemidefiniteError, match="repair_method=NONE"):
        builder.validate(INDEFINITE, IDS, CovarianceMethod.EMPIRICAL, None, 10)


def test_psd_matrix_is_not_modified(config: EngineConfig) -> None:
    psd = np.array([[0.04, 0.01], [0.01, 0.09]])
    estimate = _builder(config).validate(psd, ("A", "B"), CovarianceMethod.EMPIRICAL, None, 10)
    assert estimate.repair is None
    np.testing.assert_array_equal(estimate.matrix, psd)


def test_ill_conditioned_repair_only_when_limit_configured(config: EngineConfig) -> None:
    near_singular = np.array([[1.0, 1.0 - 1e-9], [1.0 - 1e-9, 1.0]])
    untouched = _builder(config).validate(
        near_singular, ("A", "B"), CovarianceMethod.EMPIRICAL, None, 10
    )
    assert untouched.repair is None
    assert untouched.condition_number > 1e8
    limited = _builder(config, eigenvalue_floor_relative=1e-4, condition_number_limit=1e6).validate(
        near_singular, ("A", "B"), CovarianceMethod.EMPIRICAL, None, 10
    )
    assert limited.repair is not None
    assert limited.repair.reason == "ILL_CONDITIONED"
    assert limited.condition_number <= 1e4 * (1 + 1e-9)


def test_excessive_asymmetry_is_rejected_not_silently_fixed(config: EngineConfig) -> None:
    asymmetric = np.array([[1.0, 0.5], [0.1, 1.0]])
    with pytest.raises(CovarianceEstimationError, match="Asimetría"):
        _builder(config).validate(asymmetric, ("A", "B"), CovarianceMethod.EMPIRICAL, None, 10)


def test_small_asymmetry_is_symmetrized_and_recorded(config: EngineConfig) -> None:
    matrix = np.array([[1.0, 0.5 + 1e-12], [0.5, 1.0]])
    estimate = _builder(config).validate(matrix, ("A", "B"), CovarianceMethod.EMPIRICAL, None, 10)
    assert estimate.original_asymmetry == pytest.approx(1e-12, rel=1e-3)
    np.testing.assert_array_equal(estimate.matrix, estimate.matrix.T)
