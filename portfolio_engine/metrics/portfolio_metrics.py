"""Métricas vectorizadas de carteras (MASTER_SPEC §55; MET-001, MET-002, MET-005, MET-006).

Para ``W ∈ R^{K×n}`` (``K`` carteras, ``n`` activos de la composición)::

    Ret = W μ            Var = rowsum((W Σ) ∘ W)      Vol = sqrt(Var)
    Sharpe = (Ret − rf) / Vol          (no definido si Vol <= tolerancia)
    HHI = rowsum(W ∘ W)
    Turnover = 0.5·rowsum|Δ|           TC_one_off = max(Δ,0)·c_b + max(−Δ,0)·c_s
    TC = TC_one_off / H                Net = Ret − TC

con ``Δ = W_union − w_current`` sobre la unión current ∪ composición. No hay bucles de Python por
punto de frontera. Las métricas que dependen de la cartera actual o de los costes se marcan como no
disponibles (``None`` con motivo), nunca se inventan (MASTER_SPEC §24).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.costs.transaction_cost_model import TransactionCostModel, UnionAlignment
from portfolio_engine.costs.turnover import turnover as union_turnover
from portfolio_engine.exceptions import MetricsError
from portfolio_engine.models.frontier import PointMetrics

REASON_NO_CURRENT_PORTFOLIO = "NO_CURRENT_PORTFOLIO"
REASON_NO_TRANSACTION_COST_DATA = "NO_TRANSACTION_COST_DATA"


@dataclass(frozen=True, slots=True)
class MetricsTolerances:
    """Tolerancias de las métricas (proceden de configuración).

    Attributes:
        variance_tolerance: negatividad numérica tolerada de ``w'Σw``.
        zero_volatility_tolerance: volatilidad por debajo de la cual el Sharpe no se define.
        zero_weight_tolerance: peso por debajo del cual un activo no cuenta como mantenido.
    """

    variance_tolerance: float
    zero_volatility_tolerance: float
    zero_weight_tolerance: float

    @classmethod
    def from_config(cls, solver: SolverConfig, frontier: FrontierConfig) -> MetricsTolerances:
        """Construye las tolerancias desde ``SolverConfig`` y ``FrontierConfig``."""
        return cls(
            variance_tolerance=solver.variance_tolerance,
            zero_volatility_tolerance=frontier.zero_volatility_tolerance,
            zero_weight_tolerance=frontier.zero_weight_tolerance,
        )


@dataclass(frozen=True, eq=False, slots=True)
class MetricsTable:
    """Métricas de ``K`` carteras. Los arrays opcionales son ``None`` si no están disponibles."""

    expected_return_gross: npt.NDArray[np.float64]
    variance: npt.NDArray[np.float64]
    volatility: npt.NDArray[np.float64]
    sharpe_ratio: npt.NDArray[np.float64]
    herfindahl_index: npt.NDArray[np.float64]
    number_assets: npt.NDArray[np.int64]
    turnover: npt.NDArray[np.float64] | None
    transaction_cost_one_off: npt.NDArray[np.float64] | None
    transaction_cost: npt.NDArray[np.float64] | None
    expected_return_net: npt.NDArray[np.float64] | None
    number_new_assets: npt.NDArray[np.int64] | None
    number_removed_assets: npt.NDArray[np.int64] | None
    unavailable_reason: str | None

    def __len__(self) -> int:
        return int(self.expected_return_gross.shape[0])

    def row(self, index: int) -> PointMetrics:
        """Métricas de la cartera ``index`` como :class:`PointMetrics` (``NaN`` → ``None``)."""
        sharpe = float(self.sharpe_ratio[index])
        return PointMetrics(
            expected_return_gross=float(self.expected_return_gross[index]),
            variance=float(self.variance[index]),
            volatility=float(self.volatility[index]),
            sharpe_ratio=None if np.isnan(sharpe) else sharpe,
            herfindahl_index=float(self.herfindahl_index[index]),
            number_assets=int(self.number_assets[index]),
            turnover=_optional(self.turnover, index),
            transaction_cost_one_off=_optional(self.transaction_cost_one_off, index),
            transaction_cost=_optional(self.transaction_cost, index),
            expected_return_net=_optional(self.expected_return_net, index),
            number_new_assets=_optional_int(self.number_new_assets, index),
            number_removed_assets=_optional_int(self.number_removed_assets, index),
            unavailable_reason=self.unavailable_reason,
        )


def _optional(values: npt.NDArray[np.float64] | None, index: int) -> float | None:
    return None if values is None else float(values[index])


def _optional_int(values: npt.NDArray[np.int64] | None, index: int) -> int | None:
    return None if values is None else int(values[index])


def portfolio_variance(
    weights: npt.NDArray[np.float64],
    sigma: npt.NDArray[np.float64],
    tolerance: float,
) -> npt.NDArray[np.float64]:
    """``w'Σw`` por fila. Una negatividad numérica ``>= -tolerance`` se recorta a 0."""
    variance = np.asarray(((weights @ sigma) * weights).sum(axis=-1), dtype=np.float64)
    if np.any(variance < -tolerance):
        raise MetricsError(
            f"Varianza negativa {float(variance.min()):.3e} por debajo de -{tolerance:.3e}: "
            "la covarianza no es PSD o los pesos no son finitos."
        )
    return np.maximum(variance, 0.0)


def compute_metrics(
    weights: npt.ArrayLike,
    *,
    mu: npt.NDArray[np.float64],
    sigma: npt.NDArray[np.float64],
    risk_free_rate: float,
    tolerances: MetricsTolerances,
    alignment: UnionAlignment | None,
    cost_model: TransactionCostModel | None,
) -> MetricsTable:
    """Métricas vectorizadas de ``weights`` (``K×n`` o ``n``) sobre la composición ``(mu, sigma)``.

    ``alignment`` permite turnover y conteos de activos nuevos/eliminados; ``cost_model`` permite
    costes y retorno neto. Sin alguno de ellos, esas métricas son ``None`` con su motivo.
    """
    matrix = np.atleast_2d(np.asarray(weights, dtype=np.float64))
    if matrix.shape[1] != mu.shape[0]:
        raise MetricsError("Dimensión de pesos incompatible con mu.")
    if not np.all(np.isfinite(matrix)):
        raise MetricsError("Los pesos deben ser finitos.")
    gross = matrix @ mu
    variance = portfolio_variance(matrix, sigma, tolerances.variance_tolerance)
    volatility = np.sqrt(variance)
    defined = volatility > tolerances.zero_volatility_tolerance
    safe = np.where(defined, volatility, 1.0)
    sharpe = np.where(defined, (gross - risk_free_rate) / safe, np.nan)
    held = matrix > tolerances.zero_weight_tolerance
    has_current = alignment is not None and alignment.has_current_portfolio
    turnover_values: npt.NDArray[np.float64] | None = None
    new_assets: npt.NDArray[np.int64] | None = None
    removed_assets: npt.NDArray[np.int64] | None = None
    if alignment is not None and has_current:
        expanded = alignment.expand(matrix)
        turnover_values = union_turnover(expanded, alignment.current_weights)
        new_assets, removed_assets = _composition_changes(
            expanded, alignment.current_weights, tolerances.zero_weight_tolerance
        )
    one_off: npt.NDArray[np.float64] | None = None
    cost: npt.NDArray[np.float64] | None = None
    net: npt.NDArray[np.float64] | None = None
    reason: str | None = None
    if not has_current:
        reason = REASON_NO_CURRENT_PORTFOLIO
    elif cost_model is None:
        reason = REASON_NO_TRANSACTION_COST_DATA
    else:
        one_off = cost_model.cost_one_off(matrix)
        cost = cost_model.cost(matrix)
        net = gross - cost
    return MetricsTable(
        expected_return_gross=gross,
        variance=variance,
        volatility=volatility,
        sharpe_ratio=np.asarray(sharpe, dtype=np.float64),
        herfindahl_index=np.asarray((matrix * matrix).sum(axis=1), dtype=np.float64),
        number_assets=held.sum(axis=1).astype(np.int64),
        turnover=turnover_values,
        transaction_cost_one_off=one_off,
        transaction_cost=cost,
        expected_return_net=net,
        number_new_assets=new_assets,
        number_removed_assets=removed_assets,
        unavailable_reason=reason,
    )


def _composition_changes(
    expanded: npt.NDArray[np.float64],
    current: npt.NDArray[np.float64],
    tolerance: float,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """Conteo de activos nuevos (antes sin peso) y eliminados (antes con peso, ahora sin él)."""
    was_held = current > 0.0
    now_held = expanded > tolerance
    new = (now_held & ~was_held).sum(axis=1).astype(np.int64)
    removed = (~now_held & was_held).sum(axis=1).astype(np.int64)
    return new, removed
