"""Configuración de retornos y expected returns (MASTER_SPEC §8, §9)."""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_finite, require_int_at_least
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import ExpectedReturnMode, InternalEstimationMethod, ReturnKind


@dataclass(frozen=True, slots=True)
class ReturnConfig:
    """Parámetros de retornos.

    Attributes:
        return_kind: ``ARITHMETIC`` (por defecto en la configuración) o ``LOG``.
        log_return_justification: justificación obligatoria si ``return_kind`` es ``LOG``.
        trading_days_per_year: ``TradingDays`` de la anualización lineal (§9).
        risk_free_rate: tasa libre de riesgo anualizada (decimal).
        expected_return_mode: ``INTERNAL_ESTIMATION`` o ``EXTERNAL_ALPHA`` (§8).
        internal_estimation_method: método interno cuando el modo es ``INTERNAL_ESTIMATION``.
    """

    return_kind: ReturnKind
    log_return_justification: str | None
    trading_days_per_year: int
    risk_free_rate: float
    expected_return_mode: ExpectedReturnMode
    internal_estimation_method: InternalEstimationMethod

    def __post_init__(self) -> None:
        require_int_at_least(self.trading_days_per_year, 1, "trading_days_per_year")
        require_finite(self.risk_free_rate, "risk_free_rate")
        justification = (self.log_return_justification or "").strip()
        if self.return_kind is ReturnKind.LOG and not justification:
            raise ConfigError("return_kind LOG exige log_return_justification no vacía (§9).")
        if self.return_kind is ReturnKind.ARITHMETIC and self.log_return_justification is not None:
            raise ConfigError("log_return_justification solo se admite con return_kind LOG.")
