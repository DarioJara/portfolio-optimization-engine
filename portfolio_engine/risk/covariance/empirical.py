"""Covarianza empírica (MASTER_SPEC §11: EMPIRICAL)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import InsufficientDataError
from portfolio_engine.models.enums import CovarianceMethod
from portfolio_engine.risk.covariance.base import RawCovariance, check_returns_matrix


class EmpiricalCovarianceEstimator:
    """``S = Xcᵀ Xc / (T − ddof)`` con ``Xc`` los retornos centrados por su media muestral."""

    def __init__(self, ddof: int) -> None:
        self._ddof = ddof

    @property
    def method(self) -> CovarianceMethod:
        """``EMPIRICAL``."""
        return CovarianceMethod.EMPIRICAL

    def estimate(self, returns: npt.NDArray[np.float64]) -> RawCovariance:
        """Covarianza muestral por periodo."""
        data = check_returns_matrix(returns)
        n_obs = data.shape[0]
        if n_obs <= self._ddof:
            raise InsufficientDataError("Observaciones insuficientes para el ddof configurado.")
        centered = data - data.mean(axis=0)
        matrix = centered.T @ centered / float(n_obs - self._ddof)
        return RawCovariance(matrix=matrix, shrinkage=None, n_observations=n_obs)
