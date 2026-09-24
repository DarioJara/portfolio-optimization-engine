"""Contribuciones por activo (MASTER_SPEC §64; MET-003).

::

    MRC_i = (Σw)_i / σ_p          contribución marginal a la volatilidad (∂σ/∂w_i)
    Σ_i w_i·MRC_i = σ_p           (identidad de Euler; comprobada en los tests)
    ERC_i = w_i·μ_i               contribución al retorno esperado; Σ_i ERC_i = μ'w
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def marginal_risk_contribution(
    weights: npt.NDArray[np.float64],
    sigma: npt.NDArray[np.float64],
    zero_volatility_tolerance: float,
) -> npt.NDArray[np.float64]:
    """``MRC_i = (Σw)_i / σ_p`` para cada fila de ``weights``; ``NaN`` si ``σ_p`` no se define."""
    matrix = np.atleast_2d(np.asarray(weights, dtype=np.float64))
    covariance_times_weights = matrix @ sigma
    volatility = np.sqrt(np.maximum((covariance_times_weights * matrix).sum(axis=1), 0.0))
    defined = volatility > zero_volatility_tolerance
    safe = np.where(defined, volatility, 1.0)
    contribution = covariance_times_weights / safe[:, np.newaxis]
    return np.asarray(np.where(defined[:, np.newaxis], contribution, np.nan), dtype=np.float64)


def return_contribution(
    weights: npt.NDArray[np.float64], mu: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """``ERC_i = w_i·μ_i`` para cada fila de ``weights``."""
    return np.asarray(np.atleast_2d(weights) * mu, dtype=np.float64)
