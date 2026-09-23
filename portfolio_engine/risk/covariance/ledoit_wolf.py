"""Ledoit-Wolf (2004) con objetivo identidad escalada (MASTER_SPEC §11: LEDOIT_WOLF).

Con ``X`` los retornos centrados (T×N) y ``S = XᵀX / T`` (estimador de máxima verosimilitud):

* ``m  = tr(S) / N``
* ``d² = ‖S − m·I‖²_F / N``
* ``b̄² = (Σ_t ‖x_t‖⁴ − T·‖S‖²_F) / (N·T²)``  (usa ``Σ_t x_t x_tᵀ = T·S``)
* ``b² = min(b̄², d²)``, intensidad ``δ = b² / d²`` (``δ = 0`` si ``b² = 0``)
* ``Σ̂ = δ·m·I + (1 − δ)·S``

Los autovalores de ``Σ̂`` son ``(1 − δ)·λ_i(S) + δ·m`` con los mismos autovectores que ``S``.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from portfolio_engine.models.enums import CovarianceMethod
from portfolio_engine.risk.covariance.base import RawCovariance, check_returns_matrix


class LedoitWolfCovarianceEstimator:
    """Estimador de contracción de Ledoit-Wolf hacia ``m·I``."""

    @property
    def method(self) -> CovarianceMethod:
        """``LEDOIT_WOLF``."""
        return CovarianceMethod.LEDOIT_WOLF

    def estimate(self, returns: npt.NDArray[np.float64]) -> RawCovariance:
        """Covarianza contraída por periodo e intensidad de contracción ``δ ∈ [0, 1]``."""
        data = check_returns_matrix(returns)
        n_obs, n_assets = data.shape
        centered = data - data.mean(axis=0)
        sample = centered.T @ centered / float(n_obs)
        target_scale = float(np.trace(sample)) / n_assets
        identity = np.eye(n_assets)
        dispersion = float(np.sum((sample - target_scale * identity) ** 2)) / n_assets
        fourth_moments = float(np.sum(np.sum(centered**2, axis=1) ** 2))
        sample_norm = float(np.sum(sample**2))
        estimation_error = (fourth_moments - n_obs * sample_norm) / (n_assets * n_obs**2)
        bounded_error = min(estimation_error, dispersion)
        shrinkage = 0.0 if bounded_error <= 0.0 else bounded_error / dispersion
        matrix = shrinkage * target_scale * identity + (1.0 - shrinkage) * sample
        return RawCovariance(matrix=matrix, shrinkage=shrinkage, n_observations=n_obs)
