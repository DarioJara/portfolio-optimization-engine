"""Contrato de estimadores de covarianza (MASTER_SPEC §11)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import InsufficientDataError
from portfolio_engine.models.enums import CovarianceMethod

#: Una covarianza muestral necesita al menos dos observaciones.
MIN_OBSERVATIONS = 2


@dataclass(frozen=True, eq=False, slots=True)
class RawCovariance:
    """Covarianza por periodo (sin anualizar, sin validar) devuelta por un estimador."""

    matrix: npt.NDArray[np.float64]
    shrinkage: float | None
    n_observations: int


class CovarianceEstimator(Protocol):
    """Estimador de covarianza por periodo a partir de una matriz de retornos T×N."""

    @property
    def method(self) -> CovarianceMethod:
        """Método implementado."""
        ...

    def estimate(self, returns: npt.NDArray[np.float64]) -> RawCovariance:
        """Covarianza N×N por periodo de ``returns`` (T×N, sin NaN)."""
        ...


def check_returns_matrix(returns: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Valida forma y finitud de la matriz de retornos y la devuelve como float64 2-D."""
    data = np.asarray(returns, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] == 0:
        raise InsufficientDataError("Se esperaba una matriz de retornos T×N con N ≥ 1.")
    if data.shape[0] < MIN_OBSERVATIONS:
        raise InsufficientDataError(
            f"Se necesitan al menos {MIN_OBSERVATIONS} observaciones (hay {data.shape[0]})."
        )
    if not np.all(np.isfinite(data)):
        raise InsufficientDataError("La matriz de retornos contiene NaN o infinitos.")
    return data
