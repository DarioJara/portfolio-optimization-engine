"""Reparación de covarianzas no PSD o mal condicionadas (MASTER_SPEC §11).

* ``EIGENVALUE_FLOOR``: ``λ_i ← max(λ_i, floor · λ_max)`` conservando autovectores. Garantiza
  ``λ_min ≥ floor · λ_max`` y, por tanto, número de condición ``≤ 1 / floor``.
* ``NEAREST_PSD``: proyección de Frobenius sobre el cono PSD (Higham, 1988):
  ``X = V · max(Λ, 0) · Vᵀ``. Es la matriz PSD más cercana a la original en norma de
  Frobenius, con distancia ``sqrt(Σ λ_i⁻²)``; puede ser singular.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from portfolio_engine.risk.psd_diagnostics import symmetrize
from portfolio_engine.utils.numerics import symmetric_eigh


def _reconstruct(
    eigenvalues: npt.NDArray[np.float64], eigenvectors: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    return symmetrize((eigenvectors * eigenvalues) @ eigenvectors.T)


def eigenvalue_floor_repair(
    matrix: npt.NDArray[np.float64], floor_relative: float
) -> npt.NDArray[np.float64]:
    """Eleva los autovalores por debajo de ``floor_relative · λ_max`` hasta ese suelo."""
    eigenvalues, eigenvectors = symmetric_eigh(matrix)
    floor = floor_relative * max(float(eigenvalues[-1]), 0.0)
    return _reconstruct(np.maximum(eigenvalues, floor), eigenvectors)


def nearest_psd_repair(matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Proyección de Frobenius de una matriz simétrica sobre el cono PSD."""
    eigenvalues, eigenvectors = symmetric_eigh(matrix)
    return _reconstruct(np.maximum(eigenvalues, 0.0), eigenvectors)
