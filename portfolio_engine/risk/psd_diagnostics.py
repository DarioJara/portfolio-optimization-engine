"""Diagnóstico de matrices de covarianza (MASTER_SPEC §11).

Verifica finitud, mide y corrige la asimetría (``Σ = (Σ + Σᵀ)/2``), calcula autovalores,
autovalor mínimo, número de condición y el criterio PSD con tolerancia relativa.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import CovarianceEstimationError
from portfolio_engine.models.risk_model import PSDDiagnostics
from portfolio_engine.utils.numerics import symmetric_eigh


def check_finite(matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Exige una matriz cuadrada y finita; la devuelve como float64."""
    data = np.asarray(matrix, dtype=np.float64)
    if data.ndim != 2 or data.shape[0] != data.shape[1]:
        raise CovarianceEstimationError("La covarianza debe ser una matriz cuadrada.")
    if not np.all(np.isfinite(data)):
        raise CovarianceEstimationError("La covarianza contiene NaN o infinitos.")
    return data


def relative_asymmetry(matrix: npt.NDArray[np.float64]) -> float:
    """``max|Σ − Σᵀ| / max|Σ|`` (0 para la matriz nula)."""
    scale = float(np.max(np.abs(matrix))) if matrix.size else 0.0
    if scale == 0.0:
        return 0.0
    return float(np.max(np.abs(matrix - matrix.T))) / scale


def symmetrize(matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """``(Σ + Σᵀ) / 2`` (resultado exactamente simétrico)."""
    return (matrix + matrix.T) / 2.0


def diagnose_psd(matrix: npt.NDArray[np.float64], psd_tolerance: float) -> PSDDiagnostics:
    """Diagnóstico espectral de una matriz simétrica.

    PSD ⇔ ``λ_min ≥ −psd_tolerance · max|λ|``. Número de condición ``λ_max / λ_min`` si
    ``λ_min > 0``; infinito en otro caso (matriz singular o indefinida).
    """
    eigenvalues, _ = symmetric_eigh(matrix)
    min_eigenvalue = float(eigenvalues[0])
    max_eigenvalue = float(eigenvalues[-1])
    spectral_scale = float(np.max(np.abs(eigenvalues)))
    threshold = psd_tolerance * spectral_scale
    condition = max_eigenvalue / min_eigenvalue if min_eigenvalue > 0.0 else math.inf
    return PSDDiagnostics(
        eigenvalues=eigenvalues,
        min_eigenvalue=min_eigenvalue,
        max_eigenvalue=max_eigenvalue,
        condition_number=condition,
        is_psd=min_eigenvalue >= -threshold,
        psd_threshold=threshold,
    )
