"""Expected returns, covarianza, diagnósticos PSD y modelo de riesgo (MASTER_SPEC §8, §11).

Todas las magnitudes están anualizadas (ARCHITECTURE §5.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import CovarianceEstimationError, DataValidationError
from portfolio_engine.models.enums import (
    CovarianceMethod,
    ExpectedReturnMode,
    InternalEstimationMethod,
    PSDRepairMethod,
)
from portfolio_engine.utils.hashing import canonical_json, hash_float_array, sha256_hex
from portfolio_engine.utils.numerics import readonly_float_array

EXTERNAL_ALPHA_METHOD = "EXTERNAL_ALPHA"


def _check_asset_ids(asset_ids: tuple[str, ...], owner: str) -> None:
    if list(asset_ids) != sorted(set(asset_ids)):
        raise DataValidationError(f"{owner} exige AssetID únicos y ordenados.")


@dataclass(frozen=True, eq=False, slots=True)
class ExternalAlpha:
    """Alpha externo validado y convertido a base anualizada (MASTER_SPEC §8, E-03)."""

    asset_ids: tuple[str, ...]
    annualized_values: npt.NDArray[np.float64]
    source: str

    def __post_init__(self) -> None:
        _check_asset_ids(self.asset_ids, "ExternalAlpha")
        values = readonly_float_array(self.annualized_values)
        if values.shape != (len(self.asset_ids),) or not np.all(np.isfinite(values)):
            raise DataValidationError("ExternalAlpha exige un valor finito por activo.")
        object.__setattr__(self, "annualized_values", values)


@dataclass(frozen=True, eq=False, slots=True)
class ExpectedReturns:
    """Vector de expected returns anualizados, etiquetado con su modo y método.

    La etiqueta impide confundir una estimación histórica con alpha (MASTER_SPEC §8):
    ``EXTERNAL_ALPHA`` solo puede combinarse con el método ``EXTERNAL_ALPHA`` y
    ``INTERNAL_ESTIMATION`` solo con un :class:`InternalEstimationMethod`.
    """

    asset_ids: tuple[str, ...]
    values: npt.NDArray[np.float64]
    mode: ExpectedReturnMode
    method: str

    def __post_init__(self) -> None:
        _check_asset_ids(self.asset_ids, "ExpectedReturns")
        values = readonly_float_array(self.values)
        if values.shape != (len(self.asset_ids),) or not np.all(np.isfinite(values)):
            raise DataValidationError("ExpectedReturns exige un valor finito por activo.")
        internal_methods = {method.value for method in InternalEstimationMethod}
        if self.mode is ExpectedReturnMode.EXTERNAL_ALPHA and self.method != EXTERNAL_ALPHA_METHOD:
            raise DataValidationError("EXTERNAL_ALPHA exige el método EXTERNAL_ALPHA.")
        if self.mode is ExpectedReturnMode.INTERNAL_ESTIMATION and self.method not in (
            internal_methods
        ):
            raise DataValidationError(
                f"Método interno desconocido {self.method!r}; una estimación interna no es alpha."
            )
        object.__setattr__(self, "values", values)

    @property
    def is_external_alpha(self) -> bool:
        """``True`` solo si los valores proceden de alpha externo."""
        return self.mode is ExpectedReturnMode.EXTERNAL_ALPHA


@dataclass(frozen=True, eq=False, slots=True)
class PSDDiagnostics:
    """Diagnóstico espectral de una matriz simétrica (MASTER_SPEC §11)."""

    eigenvalues: npt.NDArray[np.float64]
    min_eigenvalue: float
    max_eigenvalue: float
    condition_number: float
    is_psd: bool
    psd_threshold: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "eigenvalues", readonly_float_array(self.eigenvalues))


@dataclass(frozen=True, slots=True)
class PSDRepairReport:
    """Registro de una reparación de covarianza (MASTER_SPEC §11).

    ``correction_magnitude`` es la norma de Frobenius de la diferencia entre la matriz
    reparada y la matriz simetrizada original.
    """

    method: PSDRepairMethod
    reason: str
    original_min_eigenvalue: float
    corrected_min_eigenvalue: float
    original_condition_number: float
    corrected_condition_number: float
    correction_magnitude: float


@dataclass(frozen=True, eq=False, slots=True)
class CovarianceEstimate:
    """Covarianza anualizada validada, con diagnósticos y reparación (si la hubo)."""

    asset_ids: tuple[str, ...]
    matrix: npt.NDArray[np.float64]
    method: CovarianceMethod
    shrinkage: float | None
    n_observations: int
    original_asymmetry: float
    original_diagnostics: PSDDiagnostics
    final_diagnostics: PSDDiagnostics
    repair: PSDRepairReport | None

    def __post_init__(self) -> None:
        _check_asset_ids(self.asset_ids, "CovarianceEstimate")
        matrix = readonly_float_array(self.matrix)
        size = len(self.asset_ids)
        if matrix.shape != (size, size) or not np.all(np.isfinite(matrix)):
            raise CovarianceEstimationError("Covarianza con dimensiones inválidas o no finita.")
        if not np.array_equal(matrix, matrix.T):
            raise CovarianceEstimationError("La covarianza final debe ser exactamente simétrica.")
        if not self.final_diagnostics.is_psd:
            raise CovarianceEstimationError("La covarianza final debe ser PSD.")
        object.__setattr__(self, "matrix", matrix)

    @property
    def condition_number(self) -> float:
        """Número de condición de la matriz final."""
        return self.final_diagnostics.condition_number


@dataclass(frozen=True, eq=False, slots=True)
class RiskModel:
    """``mu`` y ``Sigma`` globales, read-only y alineados, con ``MuSigmaVersion`` (§31)."""

    expected_returns: ExpectedReturns
    covariance: CovarianceEstimate
    mu_sigma_version: str = field(init=False)

    def __post_init__(self) -> None:
        if self.expected_returns.asset_ids != self.covariance.asset_ids:
            raise DataValidationError("mu y Sigma deben referirse a los mismos activos y orden.")
        payload = {
            "asset_ids": list(self.asset_ids),
            "mu": hash_float_array(self.mu),
            "sigma": hash_float_array(self.sigma),
            "expected_return_mode": self.expected_returns.mode,
            "expected_return_method": self.expected_returns.method,
            "covariance_method": self.covariance.method,
        }
        object.__setattr__(self, "mu_sigma_version", sha256_hex(canonical_json(payload)))

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """AssetID en el orden de ``mu`` y ``sigma``."""
        return self.expected_returns.asset_ids

    @property
    def mu(self) -> npt.NDArray[np.float64]:
        """Expected returns anualizados (no escribible)."""
        return self.expected_returns.values

    @property
    def sigma(self) -> npt.NDArray[np.float64]:
        """Covarianza anualizada (no escribible)."""
        return self.covariance.matrix
