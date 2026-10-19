"""Representaciones cónicas de ``√(wᵀΣw)`` y de cuadráticas convexas (MASTER_SPEC §20-21).

Requisitos: CON-004, OPT-010.

* **Factorización PSD** (:func:`factor_covariance`): ``Σ = L Lᵀ`` por descomposición espectral
  (``L = V·√Λ`` con los autovalores por encima de un umbral relativo). A diferencia de Cholesky
  funciona con matrices **singulares o casi singulares** (activos de varianza nula, colineales,
  ``CASH``): los autovalores despreciables se descartan y el error de reconstrucción se verifica
  contra una tolerancia de configuración; un autovalor claramente negativo (``Σ`` no PSD) es un
  error, nunca se «arregla» en silencio.
* **Restricción de volatilidad** ``√(wᵀΣw) <= σ``  ⇔  ``‖Lᵀw‖₂ <= σ``: un cono de segundo orden.
* **Cuadrática convexa** ``wᵀΣw <= h(x)`` con ``h`` afín  ⇔  ``‖(2 Lᵀw, h − 1)‖₂ <= h + 1``
  (cono rotado escrito como cono de segundo orden; ``‖z‖² <= h`` ⇔ ``4‖z‖² + (h−1)² <= (h+1)²``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.config.conic_config import ConicSolverConfig
from portfolio_engine.exceptions import CovarianceEstimationError, NotPositiveSemidefiniteError
from portfolio_engine.utils.numerics import readonly_float_array, symmetric_eigh


@dataclass(frozen=True, eq=False, slots=True)
class PSDFactor:
    """Factor ``L`` (``n × r``) de ``Σ ≈ L Lᵀ`` y diagnóstico de la factorización.

    Attributes:
        loading: matriz ``L`` no escribible.
        rank: rango numérico ``r`` (autovalores conservados).
        dropped: autovalores descartados por debajo del umbral relativo.
        min_eigenvalue: menor autovalor de ``Σ`` (puede ser ligeramente negativo por redondeo).
        reconstruction_error: ``max|LLᵀ − Σ| / max|Σ|`` (0 para ``Σ`` nula).
    """

    loading: npt.NDArray[np.float64]
    rank: int
    dropped: int
    min_eigenvalue: float
    reconstruction_error: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "loading", readonly_float_array(self.loading))

    @property
    def transpose(self) -> npt.NDArray[np.float64]:
        """``Lᵀ`` (``r × n``): ``‖Lᵀw‖² = wᵀΣw``."""
        return np.asarray(self.loading.T, dtype=np.float64)


def factor_covariance(sigma: npt.NDArray[np.float64], config: ConicSolverConfig) -> PSDFactor:
    """Factoriza ``Σ = L Lᵀ`` por autovalores; rechaza una ``Σ`` asimétrica, no finita o no PSD."""
    matrix = np.asarray(sigma, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or not np.all(np.isfinite(matrix)):
        raise CovarianceEstimationError("Σ debe ser una matriz cuadrada y finita.")
    scale = float(np.max(np.abs(matrix))) if matrix.size else 0.0
    if scale > 0.0 and float(np.max(np.abs(matrix - matrix.T))) > config.factorization_tolerance * (
        scale
    ):
        raise CovarianceEstimationError("Σ no es simétrica: no se factoriza.")
    eigenvalues, eigenvectors = symmetric_eigh((matrix + matrix.T) / 2.0)
    largest = float(eigenvalues[-1])
    spectral = float(np.max(np.abs(eigenvalues))) if eigenvalues.size else 0.0
    if float(eigenvalues[0]) < -config.psd_negative_tolerance * spectral:
        raise NotPositiveSemidefiniteError(
            f"Σ no es PSD (λ_min = {float(eigenvalues[0]):.3e}): no admite representación cónica."
        )
    threshold = config.psd_eigenvalue_relative_tolerance * max(largest, 0.0)
    keep = eigenvalues > threshold
    loading = eigenvectors[:, keep] * np.sqrt(eigenvalues[keep])
    error = 0.0
    if scale > 0.0:
        error = float(np.max(np.abs(loading @ loading.T - matrix))) / scale
        if error > config.factorization_tolerance:
            raise CovarianceEstimationError(
                f"Error de factorización {error:.3e} > {config.factorization_tolerance:.3e}."
            )
    return PSDFactor(
        loading=loading,
        rank=int(keep.sum()),
        dropped=int((~keep).sum()),
        min_eigenvalue=float(eigenvalues[0]),
        reconstruction_error=error,
    )


@dataclass(frozen=True, eq=False, slots=True)
class ConeData:
    """Argumentos de ``ModelBuilder.add_cone``: ``‖matrix·x + offset‖ <= height·x + constant``."""

    matrix: sparse.csr_matrix
    offset: npt.NDArray[np.float64]
    height: npt.NDArray[np.float64]
    constant: float


def volatility_cone(
    factor: PSDFactor,
    weight_columns: npt.NDArray[np.int64],
    n_variables: int,
    limit: float,
    *,
    limit_column: int | None = None,
) -> ConeData:
    """Cono ``‖Lᵀw‖₂ <= limit`` (``limit·x[limit_column]`` si se homogeniza con ``κ``).

    ``weight_columns`` son los índices de las variables de peso dentro de ``x``.
    """
    matrix = _embed(factor.transpose, weight_columns, n_variables)
    height = np.zeros(n_variables)
    constant = limit
    if limit_column is not None:
        height[limit_column] = limit
        constant = 0.0
    return ConeData(matrix, np.zeros(matrix.shape[0]), height, constant)


def quadratic_cone(
    factor: PSDFactor,
    weight_columns: npt.NDArray[np.int64],
    n_variables: int,
    height: npt.NDArray[np.float64],
    constant: float,
) -> ConeData:
    """Cono de ``wᵀΣw <= h(x)`` con ``h(x) = height·x + constant`` afín.

    ``‖[2 Lᵀw ; h − 1]‖₂ <= h + 1``: la última fila del vector es ``h(x) − 1`` (fila ``height``,
    offset ``constant − 1``) y el lado derecho ``h(x) + 1`` (``height``, ``constant + 1``).
    """
    if height.shape != (n_variables,):
        raise CovarianceEstimationError("height debe cubrir todas las variables.")
    stacked = sparse.vstack(
        [2.0 * _embed(factor.transpose, weight_columns, n_variables), sparse.csr_matrix(height)],
        format="csr",
    )
    offset = np.zeros(stacked.shape[0])
    offset[-1] = constant - 1.0
    return ConeData(stacked, offset, np.array(height, dtype=np.float64), constant + 1.0)


def _embed(
    dense: npt.NDArray[np.float64], columns: npt.NDArray[np.int64], n_variables: int
) -> sparse.csr_matrix:
    """``dense`` (``r × k``) colocada en las columnas ``columns`` de una matriz ``r × n``."""
    rows = np.repeat(np.arange(dense.shape[0]), dense.shape[1])
    cols = np.tile(columns, dense.shape[0])
    return sparse.csr_matrix((dense.ravel(), (rows, cols)), shape=(dense.shape[0], n_variables))
