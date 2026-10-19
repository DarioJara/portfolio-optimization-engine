"""Shrinkage de expected returns (MASTER_SPEC §52; ROB-001): un **estimador**, no robustez.

Encoge la estimación ``μ̂`` hacia un destino ``μ₀``: ``μ = (1 − δ)·μ̂ + δ·μ₀``. Reduce el error de
estimación de una media muestral ruidosa, pero **no** es optimización robusta (no hay conjunto de
incertidumbre ni peor caso) y su resultado se etiqueta ``SHRUNK_HISTORICAL_MEAN`` para no
confundirlo con la media histórica. No se aplica a un alpha externo (su error no es de muestreo).

Métodos:

* ``FIXED_INTENSITY``: ``δ`` declarado en ``[robust]``; destino ``GRAND_MEAN`` (media de ``μ̂``),
  ``RISK_FREE`` (``rf``) o ``SUPPLIED`` (vector suministrado).
* ``JORION`` (Bayes-Stein, Jorion 1986): destino la media de mínima varianza
  ``μ₀ = 1ᵀΣ⁻¹μ̂ / 1ᵀΣ⁻¹1`` (``GRAND_MEAN`` en la configuración) e intensidad estimada
  ``δ = (N + 2) / ((N + 2) + Y·(μ̂ − μ₀1)ᵀΣ⁻¹(μ̂ − μ₀1))`` con ``Y`` años de datos
  (``T/TradingDays``): con ``μ`` y ``Σ`` anualizados el estadístico de Jorion es ``Y·q``. Exige
  ``Σ`` definida positiva.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.robust_config import RobustConfig
from portfolio_engine.exceptions import ConfigError, DataValidationError
from portfolio_engine.models.enums import (
    ExpectedReturnMode,
    InternalEstimationMethod,
    ShrinkageMethod,
    ShrinkageTarget,
)
from portfolio_engine.models.risk_model import ExpectedReturns


@dataclass(frozen=True, eq=False, slots=True)
class ShrinkageResult:
    """Expected returns encogidos, la intensidad aplicada y el destino usado."""

    expected_returns: ExpectedReturns
    intensity: float
    target: npt.NDArray[np.float64]
    method: ShrinkageMethod


def shrink_expected_returns(
    expected: ExpectedReturns,
    sigma: npt.NDArray[np.float64],
    n_observations: int,
    trading_days_per_year: int,
    risk_free_rate: float,
    config: RobustConfig,
    supplied_target: npt.NDArray[np.float64] | None = None,
) -> ShrinkageResult:
    """Aplica el shrinkage configurado a ``expected`` (solo estimaciones internas)."""
    method = config.shrinkage_method
    target_kind = config.shrinkage_target
    if method is None or target_kind is None:
        raise ConfigError("robust.shrinkage_method no configurado: no hay shrinkage que aplicar.")
    if expected.mode is not ExpectedReturnMode.INTERNAL_ESTIMATION:
        raise DataValidationError(
            "El shrinkage solo se aplica a una estimación interna, no a un alpha externo."
        )
    mu_hat = np.array(expected.values, dtype=np.float64)
    size = mu_hat.shape[0]
    if method is ShrinkageMethod.JORION:
        if target_kind is not ShrinkageTarget.GRAND_MEAN:
            raise ConfigError(
                "JORION usa la media de mínima varianza: shrinkage_target = GRAND_MEAN."
            )
        target, intensity = _jorion(mu_hat, sigma, n_observations, trading_days_per_year)
    else:
        target = _target(target_kind, mu_hat, risk_free_rate, supplied_target)
        intensity = float(config.shrinkage_intensity or 0.0)
    values = (1.0 - intensity) * mu_hat + intensity * target
    shrunk = ExpectedReturns(
        expected.asset_ids,
        values,
        ExpectedReturnMode.INTERNAL_ESTIMATION,
        InternalEstimationMethod.SHRUNK_HISTORICAL_MEAN.value,
    )
    del size
    return ShrinkageResult(shrunk, intensity, target, method)


def _target(
    kind: ShrinkageTarget,
    mu_hat: npt.NDArray[np.float64],
    risk_free_rate: float,
    supplied: npt.NDArray[np.float64] | None,
) -> npt.NDArray[np.float64]:
    if kind is ShrinkageTarget.GRAND_MEAN:
        return np.full(mu_hat.shape, float(mu_hat.mean()), dtype=np.float64)
    if kind is ShrinkageTarget.RISK_FREE:
        return np.full(mu_hat.shape, risk_free_rate, dtype=np.float64)
    if supplied is None or supplied.shape != mu_hat.shape or not np.all(np.isfinite(supplied)):
        raise DataValidationError(
            "SUPPLIED exige un vector de destino finito, un valor por activo."
        )
    return np.array(supplied, dtype=np.float64)


def _jorion(
    mu_hat: npt.NDArray[np.float64],
    sigma: npt.NDArray[np.float64],
    n_observations: int,
    trading_days_per_year: int,
) -> tuple[npt.NDArray[np.float64], float]:
    size = mu_hat.shape[0]
    if n_observations < 1:
        raise DataValidationError("JORION exige el número de observaciones de la estimación.")
    try:
        chol = np.linalg.cholesky((sigma + sigma.T) / 2.0)
    except np.linalg.LinAlgError as error:
        raise DataValidationError(
            "JORION exige Σ definida positiva (no admite singular)."
        ) from error
    ones = np.ones(size)
    inverse_ones = np.linalg.solve(chol.T, np.linalg.solve(chol, ones))
    inverse_mu = np.linalg.solve(chol.T, np.linalg.solve(chol, mu_hat))
    grand = float(ones @ inverse_mu) / float(ones @ inverse_ones)
    deviation = mu_hat - grand
    quadratic = float(deviation @ np.linalg.solve(chol.T, np.linalg.solve(chol, deviation)))
    years = n_observations / trading_days_per_year
    weight = (size + 2.0) / ((size + 2.0) + years * quadratic)
    return np.full(size, grand, dtype=np.float64), float(weight)
