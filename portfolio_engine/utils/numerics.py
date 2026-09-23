"""Utilidades numéricas genéricas (sin parámetros financieros)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def readonly_float_array(values: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Copia ``values`` a un array float64 contiguo y no escribible."""
    array = np.array(values, dtype=np.float64, copy=True, order="C")
    array.setflags(write=False)
    return array


def readonly_int_array(values: npt.ArrayLike) -> npt.NDArray[np.int64]:
    """Copia ``values`` a un array int64 contiguo y no escribible."""
    array = np.array(values, dtype=np.int64, copy=True, order="C")
    array.setflags(write=False)
    return array


def symmetric_eigh(
    matrix: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Descomposición espectral de una matriz simétrica (autovalores ascendentes)."""
    eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    return eigenvalues.astype(np.float64), eigenvectors.astype(np.float64)
