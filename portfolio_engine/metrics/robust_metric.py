"""Utilidad del peor caso evaluada **directamente** desde los pesos (MASTER_SPEC §52; ROB-005).

Cálculo independiente de la formulación cónica: aplica las fórmulas cerradas del peor caso de cada
conjunto de incertidumbre, sin factorizar ``Σ`` ni resolver nada, para validar la solución de la
optimización robusta:

* caja ``|μ_i − μ̂_i| <= δ_i``:        ``min μᵀw = μ̂ᵀw − Σ δ_i |w_i|``;
* elipsoide ``(μ−μ̂)ᵀΩ⁻¹(μ−μ̂) <= κ²``: ``min μᵀw = μ̂ᵀw − κ √(wᵀΩw)``;
* covarianzas ``{Σ_k}`` finitas:        ``max_k wᵀΣ_k w``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import MetricsError


def worst_case_box_return(
    weights: npt.NDArray[np.float64],
    mu_hat: npt.NDArray[np.float64],
    half_width: npt.NDArray[np.float64],
) -> float:
    """``μ̂ᵀw − δᵀ|w|``: retorno esperado del peor caso del conjunto en caja."""
    if not (weights.shape == mu_hat.shape == half_width.shape):
        raise MetricsError("weights, mu_hat y half_width deben tener la misma forma.")
    return float(mu_hat @ weights - half_width @ np.abs(weights))


def worst_case_ellipsoid_return(
    weights: npt.NDArray[np.float64],
    mu_hat: npt.NDArray[np.float64],
    omega: npt.NDArray[np.float64],
    radius: float,
) -> float:
    """``μ̂ᵀw − κ√(wᵀΩw)``: retorno esperado del peor caso del conjunto elipsoidal."""
    if omega.shape != (weights.shape[0], weights.shape[0]) or radius < 0.0:
        raise MetricsError("omega debe ser n × n y radius no negativo.")
    variance = float(weights @ omega @ weights)
    return float(mu_hat @ weights - radius * math.sqrt(max(variance, 0.0)))


def worst_case_variance(
    weights: npt.NDArray[np.float64], covariances: Sequence[npt.NDArray[np.float64]]
) -> float:
    """``max_k wᵀΣ_k w`` sobre un conjunto finito de covarianzas."""
    if not covariances:
        raise MetricsError("Se necesita al menos una covarianza.")
    return max(float(weights @ sigma @ weights) for sigma in covariances)
