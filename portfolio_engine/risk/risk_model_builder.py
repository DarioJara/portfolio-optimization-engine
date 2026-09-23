"""Construcción de la covarianza validada y del modelo de riesgo global (MASTER_SPEC §11).

Flujo: estimación por periodo → anualización (``TradingDays``) → verificación de finitud →
control de asimetría y simetrización → diagnóstico espectral → reparación (solo si la
configuración la autoriza) → diagnóstico final. Toda reparación queda registrada.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.risk_config import RiskConfig
from portfolio_engine.exceptions import CovarianceEstimationError, NotPositiveSemidefiniteError
from portfolio_engine.models.enums import CovarianceMethod, PSDRepairMethod
from portfolio_engine.models.market_data import ReturnsMatrix
from portfolio_engine.models.risk_model import (
    CovarianceEstimate,
    ExpectedReturns,
    PSDDiagnostics,
    PSDRepairReport,
    RiskModel,
)
from portfolio_engine.returns.annualization import annualize_covariance
from portfolio_engine.risk.covariance.factory import make_covariance_estimator
from portfolio_engine.risk.psd_diagnostics import (
    check_finite,
    diagnose_psd,
    relative_asymmetry,
    symmetrize,
)
from portfolio_engine.risk.psd_repair import eigenvalue_floor_repair, nearest_psd_repair
from portfolio_engine.utils.logging import get_logger, log_event

_LOGGER = get_logger("risk")
REASON_NOT_PSD = "NOT_PSD"
REASON_ILL_CONDITIONED = "ILL_CONDITIONED"


class CovarianceBuilder:
    """Estima, anualiza, diagnostica y (si procede) repara la covarianza."""

    def __init__(self, config: RiskConfig, trading_days_per_year: int) -> None:
        self._config = config
        self._trading_days = trading_days_per_year

    def build(self, returns: ReturnsMatrix, asset_ids: Sequence[str]) -> CovarianceEstimate:
        """Covarianza anualizada validada de ``asset_ids`` (ordenados y únicos)."""
        estimator = make_covariance_estimator(self._config)
        raw = estimator.estimate(returns.columns_for(asset_ids))
        annual = annualize_covariance(raw.matrix, self._trading_days)
        return self.validate(
            annual, tuple(asset_ids), estimator.method, raw.shrinkage, raw.n_observations
        )

    def validate(
        self,
        matrix: npt.NDArray[np.float64],
        asset_ids: tuple[str, ...],
        method: CovarianceMethod,
        shrinkage: float | None,
        n_observations: int,
    ) -> CovarianceEstimate:
        """Valida y, si la configuración lo autoriza, repara una covarianza anualizada."""
        data = check_finite(matrix)
        asymmetry = relative_asymmetry(data)
        if asymmetry > self._config.symmetry_tolerance:
            raise CovarianceEstimationError(
                f"Asimetría relativa {asymmetry:.3e} > tolerancia "
                f"{self._config.symmetry_tolerance:.3e}: no se simetriza en silencio."
            )
        symmetric = symmetrize(data)
        original = diagnose_psd(symmetric, self._config.psd_tolerance)
        decision = self._repair_decision(original)
        final_matrix, final, repair = symmetric, original, None
        if decision is not None:
            repair_method, reason = decision
            final_matrix = self._apply(repair_method, symmetric)
            final = diagnose_psd(final_matrix, self._config.psd_tolerance)
            repair = PSDRepairReport(
                method=repair_method,
                reason=reason,
                original_min_eigenvalue=original.min_eigenvalue,
                corrected_min_eigenvalue=final.min_eigenvalue,
                original_condition_number=original.condition_number,
                corrected_condition_number=final.condition_number,
                correction_magnitude=float(np.linalg.norm(final_matrix - symmetric, "fro")),
            )
            log_event(_LOGGER, logging.WARNING, "covariance_repaired", **_log_fields(repair))
        if not final.is_psd:
            raise NotPositiveSemidefiniteError(
                f"La covarianza reparada sigue sin ser PSD (λ_min={final.min_eigenvalue:.3e}); "
                "revise psd_tolerance."
            )
        return CovarianceEstimate(
            asset_ids=asset_ids,
            matrix=final_matrix,
            method=method,
            shrinkage=shrinkage,
            n_observations=n_observations,
            original_asymmetry=asymmetry,
            original_diagnostics=original,
            final_diagnostics=final,
            repair=repair,
        )

    def _repair_decision(self, diagnostics: PSDDiagnostics) -> tuple[PSDRepairMethod, str] | None:
        """Método y motivo de reparación, o ``None`` si la matriz se acepta tal cual."""
        config = self._config
        if not diagnostics.is_psd:
            if config.repair_method is PSDRepairMethod.NONE:
                raise NotPositiveSemidefiniteError(
                    f"Covarianza no PSD (λ_min={diagnostics.min_eigenvalue:.3e}) y "
                    "repair_method=NONE."
                )
            return config.repair_method, REASON_NOT_PSD
        limit = config.condition_number_limit
        if limit is not None and diagnostics.condition_number > limit:
            return PSDRepairMethod.EIGENVALUE_FLOOR, REASON_ILL_CONDITIONED
        return None

    def _apply(
        self, method: PSDRepairMethod, matrix: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        if method is PSDRepairMethod.NEAREST_PSD:
            return nearest_psd_repair(matrix)
        floor = self._config.eigenvalue_floor_relative
        if floor is None:
            raise CovarianceEstimationError("EIGENVALUE_FLOOR exige eigenvalue_floor_relative.")
        return eigenvalue_floor_repair(matrix, floor)


def _log_fields(report: PSDRepairReport) -> dict[str, object]:
    return {
        "method": report.method.value,
        "reason": report.reason,
        "original_min_eigenvalue": report.original_min_eigenvalue,
        "corrected_min_eigenvalue": report.corrected_min_eigenvalue,
        "original_condition_number": report.original_condition_number,
        "corrected_condition_number": report.corrected_condition_number,
        "correction_magnitude": report.correction_magnitude,
    }


def build_risk_model(expected: ExpectedReturns, covariance: CovarianceEstimate) -> RiskModel:
    """``RiskModel`` global read-only con ``MuSigmaVersion`` determinista."""
    return RiskModel(expected, covariance)
