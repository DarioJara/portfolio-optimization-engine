"""VaR, CVaR (Expected Shortfall), pérdida máxima y volatilidad de una cartera (MASTER_SPEC §22).

Cálculo **directo e independiente** sobre la medida discreta de escenarios (ordenando pérdidas y
acumulando pesos): no usa la formulación de Rockafellar-Uryasev ni ningún solver, de modo que sirve
para validar la solución de un LP/QP de CVaR. Cuatro cantidades distintas que no deben confundirse:

* ``VaR_β``: el menor nivel de pérdida ``ℓ`` tal que ``P(L <= ℓ) >= β`` (un cuantil);
* ``CVaR_β`` (= Expected Shortfall de Acerbi-Tasche): pérdida media de la cola de masa ``1 − β``,
  con el átomo frontera fraccionado para que la masa de la cola sea exactamente ``1 − β``;
* pérdida máxima (peor escenario);
* volatilidad (desviación típica de la pérdida; no es una medida de cola).

La pérdida de un escenario es ``L_t = −r_tᵀw`` (retorno por periodo con signo cambiado).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import MetricsError


def portfolio_losses(
    returns: npt.NDArray[np.float64], weights: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Pérdidas por escenario ``L_t = −r_tᵀw`` (``returns``: ``T × n``; ``weights``: ``n``)."""
    if returns.ndim != 2 or weights.shape != (returns.shape[1],):
        raise MetricsError("returns debe ser T × n y weights de longitud n.")
    return np.asarray(-(returns @ weights), dtype=np.float64)


def _validated_measure(
    losses: npt.NDArray[np.float64], probabilities: npt.NDArray[np.float64], level: float
) -> None:
    if losses.ndim != 1 or probabilities.shape != losses.shape or losses.size == 0:
        raise MetricsError("losses y probabilities deben ser vectores de la misma longitud.")
    if not (np.all(np.isfinite(losses)) and np.all(np.isfinite(probabilities))):
        raise MetricsError("Pérdidas y probabilidades deben ser finitas.")
    if np.any(probabilities < 0.0):
        raise MetricsError("Las probabilidades no pueden ser negativas.")
    if not 0.0 < level < 1.0:
        raise MetricsError("El nivel de confianza debe estar en (0, 1).")


def value_at_risk(
    losses: npt.NDArray[np.float64], probabilities: npt.NDArray[np.float64], level: float
) -> float:
    """``VaR_β``: cuantil ``β`` de la distribución discreta de pérdidas."""
    _validated_measure(losses, probabilities, level)
    order = np.argsort(losses, kind="stable")
    cumulative = np.cumsum(probabilities[order])
    total = float(cumulative[-1])
    index = int(np.searchsorted(cumulative, level * total, side="left"))
    return float(losses[order][min(index, losses.size - 1)])


def conditional_value_at_risk(
    losses: npt.NDArray[np.float64], probabilities: npt.NDArray[np.float64], level: float
) -> float:
    """``CVaR_β``: media de las pérdidas de la cola de masa ``(1 − β)·Σπ`` (átomo fraccionado)."""
    _validated_measure(losses, probabilities, level)
    total = float(probabilities.sum())
    tail_mass = (1.0 - level) * total
    order = np.argsort(-losses, kind="stable")
    remaining = tail_mass
    accumulated = 0.0
    for index in order.tolist():
        take = min(float(probabilities[index]), remaining)
        accumulated += take * float(losses[index])
        remaining -= take
        if remaining <= 0.0:
            break
    return accumulated / tail_mass


def maximum_loss(losses: npt.NDArray[np.float64]) -> float:
    """Pérdida del peor escenario (no es CVaR ni VaR)."""
    if losses.size == 0 or not np.all(np.isfinite(losses)):
        raise MetricsError("losses debe ser no vacío y finito.")
    return float(np.max(losses))


def loss_volatility(
    losses: npt.NDArray[np.float64], probabilities: npt.NDArray[np.float64]
) -> float:
    """Desviación típica ponderada de la pérdida (medida de dispersión, no de cola)."""
    if losses.shape != probabilities.shape or losses.size == 0:
        raise MetricsError("losses y probabilities deben ser vectores de la misma longitud.")
    weights = probabilities / probabilities.sum()
    mean = float(weights @ losses)
    return float(np.sqrt(weights @ (losses - mean) ** 2))
