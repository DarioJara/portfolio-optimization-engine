"""CON-004, OPT-010: representaciones cónicas de ``√(wᵀΣw)`` y factorización PSD de ``Σ``.

Comprueba: construcción de matrices, dimensiones, orden de variables, signos, unidades y
reconstrucción de la solución; matrices singulares o casi singulares; ``Σ`` no PSD rechazada.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import scipy.sparse as sparse

from portfolio_engine.exceptions import (
    CovarianceEstimationError,
    NotPositiveSemidefiniteError,
    SolverError,
)
from portfolio_engine.models.enums import OptimizationFamily, ProblemClass, SolverStatus
from portfolio_engine.optimizers import CanonicalProblem, ClarabelBackend, ConicProblem
from portfolio_engine.optimizers.formulations.conic import (
    factor_covariance,
    quadratic_cone,
    volatility_cone,
)
from portfolio_engine.optimizers.formulations.model_builder import ModelBuilder
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
CONIC = CONFIG.conic


def _random_psd(n: int, rank: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, rank))
    return np.asarray(factor @ factor.T, dtype=np.float64)


def _empty_builder(size: int) -> ModelBuilder:
    base = CanonicalProblem(
        name="empty",
        problem_class=ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((size, size)),
        q=np.zeros(size),
        A=sparse.csc_matrix((0, size)),
        lower=np.zeros(0),
        upper=np.zeros(0),
    )
    return ModelBuilder(base)


def test_the_factor_reconstructs_a_positive_definite_covariance() -> None:
    sigma = _random_psd(5, 5, 1) + 0.1 * np.eye(5)
    factor = factor_covariance(sigma, CONIC)
    assert factor.rank == 5 and factor.dropped == 0
    np.testing.assert_allclose(factor.loading @ factor.loading.T, sigma, atol=1e-10)
    assert factor.reconstruction_error < CONIC.factorization_tolerance
    assert not factor.loading.flags.writeable
    np.testing.assert_allclose(factor.transpose, factor.loading.T)


def test_a_singular_covariance_is_factorized_by_its_numerical_rank() -> None:
    """Un activo duplicado (o con varianza nula) da una Σ singular: Cholesky fallaría; la
    factorización espectral conserva el rango numérico."""
    sigma = _random_psd(6, 3, 2)
    factor = factor_covariance(sigma, CONIC)
    assert factor.rank == 3 and factor.dropped == 3
    np.testing.assert_allclose(factor.loading @ factor.loading.T, sigma, atol=1e-9)
    with pytest.raises(np.linalg.LinAlgError):
        np.linalg.cholesky(sigma)
    zero_variance = np.diag([0.04, 0.0, 0.09])
    reduced = factor_covariance(zero_variance, CONIC)
    assert reduced.rank == 2
    np.testing.assert_allclose(reduced.loading @ reduced.loading.T, zero_variance, atol=1e-12)


def test_a_nearly_singular_covariance_drops_only_negligible_eigenvalues() -> None:
    base = _random_psd(4, 4, 3) + 0.05 * np.eye(4)
    eigenvalues, vectors = np.linalg.eigh(base)
    tiny = eigenvalues.copy()
    tiny[0] = eigenvalues[-1] * CONIC.psd_eigenvalue_relative_tolerance * 0.01
    sigma = (vectors * tiny) @ vectors.T
    factor = factor_covariance((sigma + sigma.T) / 2.0, CONIC)
    assert factor.rank == 3 and factor.dropped == 1
    assert factor.reconstruction_error < CONIC.factorization_tolerance


def test_the_zero_matrix_has_rank_zero() -> None:
    factor = factor_covariance(np.zeros((3, 3)), CONIC)
    assert factor.rank == 0 and factor.loading.shape == (3, 0)
    assert factor.reconstruction_error == 0.0


def test_a_non_psd_asymmetric_or_non_finite_covariance_is_rejected_not_repaired() -> None:
    indefinite = np.array([[1.0, 2.0], [2.0, 1.0]])
    with pytest.raises(NotPositiveSemidefiniteError, match="PSD"):
        factor_covariance(indefinite, CONIC)
    with pytest.raises(CovarianceEstimationError, match="simétrica"):
        factor_covariance(np.array([[1.0, 0.5], [0.0, 1.0]]), CONIC)
    with pytest.raises(CovarianceEstimationError, match="finita"):
        factor_covariance(np.array([[1.0, np.nan], [np.nan, 1.0]]), CONIC)
    with pytest.raises(CovarianceEstimationError):
        factor_covariance(np.ones((2, 3)), CONIC)


def test_the_volatility_cone_bounds_sqrt_of_the_quadratic_form() -> None:
    """``max cᵀw`` sobre ``‖Lᵀw‖ <= σ`` tiene por óptimo ``σ·√(cᵀΣ⁻¹c)`` (forma cerrada)."""
    sigma = np.array([[0.09, 0.02, 0.0], [0.02, 0.04, 0.01], [0.0, 0.01, 0.16]])
    c = np.array([0.10, 0.07, 0.12])
    limit = 0.15
    factor = factor_covariance(sigma, CONIC)
    builder = _empty_builder(3)
    builder.set_objective(None, -c)
    cone = volatility_cone(factor, np.arange(3), builder.n_variables, limit)
    builder.add_cone("vol", cone.matrix, cone.offset, cone.height, cone.constant)
    problem = builder.finalize("vol")
    assert isinstance(problem, ConicProblem) and problem.problem_class is ProblemClass.SOCP
    backend = ClarabelBackend(CONFIG.solver, CONIC)
    backend.setup(problem)
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    expected = limit * np.sqrt(c @ np.linalg.solve(sigma, c))
    assert float(c @ result.x) == pytest.approx(expected, rel=1e-6)
    assert float(np.sqrt(result.x @ sigma @ result.x)) == pytest.approx(limit, rel=1e-6)
    np.testing.assert_allclose(
        result.x,
        limit * np.linalg.solve(sigma, c) / np.sqrt(c @ np.linalg.solve(sigma, c)),
        rtol=1e-5,
    )


def test_the_cone_of_a_rank_zero_covariance_is_a_valid_trivial_constraint() -> None:
    factor = factor_covariance(np.zeros((2, 2)), CONIC)
    builder = _empty_builder(2)
    builder.set_objective(None, np.array([-1.0, -1.0]))
    builder.add_rows(sparse.csr_matrix(np.eye(2)), np.zeros(2), np.ones(2))
    cone = volatility_cone(factor, np.arange(2), builder.n_variables, 0.5)
    builder.add_cone("vol", cone.matrix, cone.offset, cone.height, cone.constant)
    backend = ClarabelBackend(CONFIG.solver, CONIC)
    backend.setup(builder.finalize("trivial"))
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    np.testing.assert_allclose(result.x, [1.0, 1.0], atol=1e-6)


def test_the_rotated_quadratic_cone_encodes_w_sigma_w_below_an_affine_bound() -> None:
    """``wᵀΣw <= t`` ⇔ ``‖(2Lᵀw, t − 1)‖ <= t + 1``: con ``w`` fijo, ``min t`` da ``wᵀΣw``."""
    sigma = np.array([[0.09, 0.02], [0.02, 0.04]])
    factor = factor_covariance(sigma, CONIC)
    builder = _empty_builder(2)
    fixed = np.array([0.6, 0.4])
    builder.add_rows(sparse.csr_matrix(np.eye(2)), fixed, fixed)
    t_index = builder.add_variables(1, cost=1.0)
    height = np.zeros(builder.n_variables)
    height[t_index] = 1.0
    cone = quadratic_cone(factor, np.arange(2), builder.n_variables, height, 0.0)
    builder.add_cone("quad", cone.matrix, cone.offset, cone.height, cone.constant)
    backend = ClarabelBackend(CONFIG.solver, CONIC)
    backend.setup(builder.finalize("quad"))
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    assert float(result.x[t_index]) == pytest.approx(float(fixed @ sigma @ fixed), rel=1e-7)


def test_the_builder_keeps_variable_order_and_pads_columns() -> None:
    """Las variables originales conservan índices; las auxiliares se añaden al final."""
    builder = _empty_builder(2)
    first = builder.add_variables(1, lower=0.0, cost=2.0)
    second = builder.add_variables(2, upper=1.0)
    assert (first, second, builder.n_variables) == (2, 3, 5)
    builder.add_rows(sparse.csr_matrix(np.array([[1.0, 1.0]])), np.ones(1), np.ones(1))
    problem = builder.finalize("layout")
    assert problem.n_variables == 5
    assert problem.q.tolist() == [0.0, 0.0, 2.0, 0.0, 0.0]
    # cota de la variable 2, cotas de las variables 3 y 4 y, al final, la fila del usuario
    assert problem.A.shape == (4, 5)
    assert problem.problem_class is ProblemClass.LP
    dense = problem.A.toarray()
    np.testing.assert_allclose(dense[0], [0, 0, 1, 0, 0])
    np.testing.assert_allclose(dense[1], [0, 0, 0, 1, 0])
    np.testing.assert_allclose(dense[2], [0, 0, 0, 0, 1])
    np.testing.assert_allclose(dense[3], [1, 1, 0, 0, 0])
    assert problem.lower.tolist() == [0.0, -np.inf, -np.inf, 1.0]
    assert problem.upper.tolist() == [np.inf, 1.0, 1.0, 1.0]


def test_the_builder_rejects_inconsistent_data() -> None:
    builder = _empty_builder(2)
    with pytest.raises(SolverError):
        builder.set_objective(None, np.zeros(3))
    with pytest.raises(SolverError):
        builder.add_rows(sparse.csr_matrix(np.ones((1, 3))), np.zeros(1), np.zeros(1))
    with pytest.raises(SolverError):
        builder.add_variables(0)
    with pytest.raises(SolverError):
        builder.set_objective(sparse.csr_matrix(np.array([[0.0, 0.0], [1.0, 0.0]])), np.zeros(2))
    with pytest.raises(SolverError, match="fuera de rango"):
        builder.mark_binary([5])


def test_the_class_of_the_assembled_problem_follows_its_structure() -> None:
    builder = _empty_builder(2)
    builder.set_objective(sparse.triu(sparse.csc_matrix(np.eye(2))), np.zeros(2))
    qp = builder.finalize("qp")
    assert qp.problem_class is ProblemClass.QP and type(qp) is CanonicalProblem
    builder.mark_binary([0])
    mip = builder.finalize("mip")
    assert mip.problem_class is ProblemClass.MIQP
    assert mip.family is OptimizationFamily.EXACT_MIP
    assert dataclasses.is_dataclass(mip)
