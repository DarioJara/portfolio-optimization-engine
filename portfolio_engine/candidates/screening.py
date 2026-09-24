"""``CandidateScreening``: score multiseñal vectorizado de activos entrantes y salientes.

Requisitos: CAN-009, CAN-010, CAN-011, CAN-012 (MASTER_SPEC §27).

Para una cartera de referencia (composición ``C`` con pesos ``w``) cada activo ``a`` recibe nueve
señales, todas con la misma convención: **mayor es mejor** tras aplicar su dirección. Se evalúa el
efecto de que ``a`` esté presente con peso ``m`` frente al **resto** de la cartera ``r``
(``r = w`` para un activo entrante; ``r = w`` sin ``a`` renormalizado para un activo de ``C``;
``m = 1/T`` para un entrante, ``T`` = tamaño objetivo, y ``m = w_a`` para uno mantenido)::

    dVar  = m²·Σ_aa + 2·m·(1−m)·cov(a, r) + ((1−m)² − 1)·var(r)      varianza incremental
    dU    = m·(μ_a − μ_r) − λ·dVar                                    utilidad incremental

===============================  ===============================  ==========================
señal                            definición                       dirección (mejor = mayor)
===============================  ===============================  ==========================
``expected_alpha``               ``μ_a``                          ``+μ_a``
``marginal_risk_contribution``   ``dVar``                         ``−dVar``
``diversification_contribution`` ``ρ(a, r)``                      ``−ρ``
``covariance_with_portfolio``    ``cov(a, r)``                    ``−cov``
``expected_utility_gain``        ``dU``                           ``+dU``
``risk_adjusted_return``         ``(μ_a − r_f)/σ_a``              ``+``
``liquidity``                    ``log ADV_a``                    ``+``
``transaction_cost``             entrante: ``BuyCost_a``;         entrante ``−Buy``;
                                 mantenido: ``SellCost_a``        mantenido ``+Sell``
``sector_fit``                   exposición sectorial de ``r``    ``1 − exposición``
===============================  ===============================  ==========================

Las señales de un conjunto (entrantes, mantenidos) se normalizan **dentro** de él (percentil por
rango con empates promediados, o z-score) y se combinan con los pesos de configuración. El
resultado es un ``CandidateScreeningScore`` heurístico para preseleccionar composiciones
prometedoras; **no** es el ``OptimizedPortfolioObjective`` ni una solución del problema continuo.

Un dato ausente sigue ``MissingSignalPolicy`` (``EXCLUDE``, ``NEUTRAL`` o ``ERROR``) y queda
registrado en ``SignalTable.missing``; una señal con peso 0 no interviene. Todo es vectorizado por
señal sobre el universo elegible: no hay bucles de Python por activo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates.universe_data import UniverseSnapshot
from portfolio_engine.config.candidate_config import SIGNAL_NAMES, CandidateConfig
from portfolio_engine.exceptions import CandidateError
from portfolio_engine.models.enums import MissingSignalPolicy, ScreeningNormalization

ROW_ALPHA = SIGNAL_NAMES.index("expected_alpha")
ROW_MARGINAL_RISK = SIGNAL_NAMES.index("marginal_risk_contribution")
ROW_DIVERSIFICATION = SIGNAL_NAMES.index("diversification_contribution")
ROW_COVARIANCE = SIGNAL_NAMES.index("covariance_with_portfolio")
ROW_UTILITY = SIGNAL_NAMES.index("expected_utility_gain")
ROW_LIQUIDITY = SIGNAL_NAMES.index("liquidity")
ROW_COST = SIGNAL_NAMES.index("transaction_cost")


def average_rank_percentile(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Percentil por rango en ``[0, 1]`` con empates promediados (``0.5`` si hay un solo valor)."""
    count = values.shape[0]
    if count == 0:
        return np.empty(0, dtype=np.float64)
    if count == 1:
        return np.full(1, 0.5, dtype=np.float64)
    order = np.argsort(values, kind="stable")
    ordered = values[order]
    starts = np.concatenate(([True], ordered[1:] != ordered[:-1]))
    group = np.cumsum(starts) - 1
    first = np.flatnonzero(starts)
    sizes = np.diff(np.concatenate((first, [count])))
    average = first[group] + (sizes[group] - 1) * 0.5
    ranks = np.empty(count, dtype=np.float64)
    ranks[order] = average
    return np.asarray(ranks / (count - 1), dtype=np.float64)


def neutral_value(normalization: ScreeningNormalization) -> float:
    """Valor normalizado neutro (mediana teórica) usado con ``MissingSignalPolicy.NEUTRAL``."""
    return 0.5 if normalization is ScreeningNormalization.RANK else 0.0


def _normalize_rows(
    raw: npt.NDArray[np.float64],
    usable: npt.NDArray[np.bool_],
    normalization: ScreeningNormalization,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    """Normaliza cada señal sobre sus valores finitos y utilizables; ``NaN`` donde falta."""
    finite = np.isfinite(raw)
    normalized = np.full(raw.shape, np.nan, dtype=np.float64)
    for row in range(raw.shape[0]):
        use = finite[row] & usable
        values = raw[row][use]
        if values.size == 0:
            continue
        if normalization is ScreeningNormalization.RANK:
            normalized[row][use] = average_rank_percentile(values)
        else:
            spread = float(values.std())
            normalized[row][use] = (
                (values - values.mean()) / spread if spread > 0 else np.zeros_like(values)
            )
    return normalized, ~finite


@dataclass(frozen=True, eq=False, slots=True)
class SignalTable:
    """Señales de un conjunto de activos (entrantes o mantenidos).

    Attributes:
        positions: posiciones globales de los activos.
        raw: señales con su dirección aplicada (mayor es mejor), ``k×m`` en el orden de
            ``SIGNAL_NAMES``.
        normalized: señales normalizadas dentro del conjunto (``NaN`` si faltan).
        missing: ``True`` donde el dato de la señal está ausente.
        score: ``CandidateScreeningScore`` combinado (``NaN`` si el activo se excluyó).
        excluded: activos excluidos por ``MissingSignalPolicy.EXCLUDE``.
        diversification: score de diversificación (correlación y covarianza con la cartera).
        imputed: señales activas que faltaban y se sustituyeron por el valor neutro (registro).
    """

    positions: npt.NDArray[np.int64]
    raw: npt.NDArray[np.float64]
    normalized: npt.NDArray[np.float64]
    missing: npt.NDArray[np.bool_]
    score: npt.NDArray[np.float64]
    excluded: npt.NDArray[np.bool_]
    diversification: npt.NDArray[np.float64]
    imputed: npt.NDArray[np.bool_]

    def missing_names(self, item: int) -> tuple[str, ...]:
        """Nombres de las señales activas ausentes (imputadas o causa de exclusión) del activo."""
        return tuple(
            name
            for name, is_missing in zip(SIGNAL_NAMES, self.missing[:, item].tolist(), strict=True)
            if is_missing
        )


@dataclass(frozen=True, eq=False, slots=True)
class ScreeningResult:
    """Score de los activos entrantes y de mantenimiento de los activos de la composición."""

    entrants: SignalTable
    held: SignalTable
    position_weight: float
    risk_aversion: float


class CandidateScreening:
    """Calcula las nueve señales del screening de forma vectorizada."""

    def __init__(self, config: CandidateConfig, risk_free_rate: float) -> None:
        self._config = config
        self._risk_free_rate = risk_free_rate
        weights = np.asarray(config.screening_weights.as_tuple(), dtype=np.float64)
        self._active = weights > 0
        self._weights = weights / weights.sum()

    def screen(
        self,
        snapshot: UniverseSnapshot,
        node_positions: npt.NDArray[np.int64],
        node_weights: npt.NDArray[np.float64],
        entrant_positions: npt.NDArray[np.int64],
        risk_aversion: float,
        position_weight: float,
        entrant_weight_caps: npt.NDArray[np.float64] | None = None,
    ) -> ScreeningResult:
        """Screening de ``entrant_positions`` y de los activos de la composición de referencia.

        ``node_positions``/``node_weights`` describen la composición de referencia (posiciones
        globales ascendentes y pesos que suman 1); ``position_weight`` es el peso ``m`` que se
        supone a un activo entrante (``1/T``); ``entrant_weight_caps`` (opcional, un valor por
        entrante) lo limita para los activos que E-10 no deja crecer por encima de su peso actual.
        """
        nodes, weights = node_positions, node_weights
        sigma_nn = snapshot.sigma[np.ix_(nodes, nodes)]
        sigma_w = sigma_nn @ weights
        variance = float(weights @ sigma_w)
        mean = float(snapshot.mu[nodes] @ weights)
        expo = self._sector_exposure(snapshot, nodes, weights)
        entrants = self._entrant_table(
            snapshot,
            nodes,
            weights,
            entrant_positions,
            variance,
            mean,
            expo,
            risk_aversion,
            position_weight,
            entrant_weight_caps,
        )
        held = self._held_table(
            snapshot, nodes, weights, sigma_nn, sigma_w, variance, mean, expo, risk_aversion
        )
        return ScreeningResult(entrants, held, position_weight, risk_aversion)

    # -------------------------------------------------------------------------- construcción

    def _sector_exposure(
        self,
        snapshot: UniverseSnapshot,
        nodes: npt.NDArray[np.int64],
        weights: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        codes = snapshot.sector_codes[nodes]
        valid = codes >= 0
        return np.bincount(codes[valid], weights=weights[valid], minlength=snapshot.sector_count)

    def _entrant_sector_fit(
        self, codes: npt.NDArray[np.int64], expo: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        if expo.size == 0:
            return np.full(codes.shape, np.nan, dtype=np.float64)
        return np.where(codes >= 0, 1.0 - expo[np.maximum(codes, 0)], np.nan)

    def _held_sector_fit(
        self,
        codes: npt.NDArray[np.int64],
        expo: npt.NDArray[np.float64],
        weights: npt.NDArray[np.float64],
        remaining: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        if expo.size == 0:
            return np.full(codes.shape, np.nan, dtype=np.float64)
        return np.where(
            codes >= 0, 1.0 - (expo[np.maximum(codes, 0)] - weights) / remaining, np.nan
        )

    def _entrant_table(
        self,
        snapshot: UniverseSnapshot,
        nodes: npt.NDArray[np.int64],
        weights: npt.NDArray[np.float64],
        entrants: npt.NDArray[np.int64],
        variance: float,
        mean: float,
        expo: npt.NDArray[np.float64],
        risk_aversion: float,
        position_weight: float,
        weight_caps: npt.NDArray[np.float64] | None,
    ) -> SignalTable:
        covariance = snapshot.sigma[np.ix_(entrants, nodes)] @ weights
        entry_weight = np.full(entrants.shape, position_weight)
        if weight_caps is not None:
            entry_weight = np.minimum(entry_weight, weight_caps)
        fit = self._entrant_sector_fit(snapshot.sector_codes[entrants], expo)
        raw = self._raw_signals(
            mu_a=snapshot.mu[entrants],
            own_variance=snapshot.sigma[entrants, entrants],
            weight_a=entry_weight,
            cov_rest=covariance,
            var_rest=np.full(entrants.shape, variance),
            mu_rest=np.full(entrants.shape, mean),
            adv=snapshot.adv[entrants],
            cost_signal=-snapshot.buy_cost[entrants],
            sector_fit=fit,
            risk_aversion=risk_aversion,
        )
        return self._table(entrants, raw)

    def _held_table(
        self,
        snapshot: UniverseSnapshot,
        nodes: npt.NDArray[np.int64],
        weights: npt.NDArray[np.float64],
        sigma_nn: npt.NDArray[np.float64],
        sigma_w: npt.NDArray[np.float64],
        variance: float,
        mean: float,
        expo: npt.NDArray[np.float64],
        risk_aversion: float,
    ) -> SignalTable:
        diag = np.diag(sigma_nn)
        remaining = 1.0 - weights
        with np.errstate(divide="ignore", invalid="ignore"):
            cov_rest = (sigma_w - weights * diag) / remaining
            var_rest = (variance - 2.0 * weights * sigma_w + weights * weights * diag) / (
                remaining * remaining
            )
            mu_rest = (mean - weights * snapshot.mu[nodes]) / remaining
            fit = self._held_sector_fit(snapshot.sector_codes[nodes], expo, weights, remaining)
        raw = self._raw_signals(
            mu_a=snapshot.mu[nodes],
            own_variance=diag,
            weight_a=weights,
            cov_rest=cov_rest,
            var_rest=var_rest,
            mu_rest=mu_rest,
            adv=snapshot.adv[nodes],
            cost_signal=snapshot.sell_cost[nodes],
            sector_fit=fit,
            risk_aversion=risk_aversion,
        )
        return self._table(nodes, raw)

    def _raw_signals(
        self,
        *,
        mu_a: npt.NDArray[np.float64],
        own_variance: npt.NDArray[np.float64],
        weight_a: npt.NDArray[np.float64],
        cov_rest: npt.NDArray[np.float64],
        var_rest: npt.NDArray[np.float64],
        mu_rest: npt.NDArray[np.float64],
        adv: npt.NDArray[np.float64],
        cost_signal: npt.NDArray[np.float64],
        sector_fit: npt.NDArray[np.float64],
        risk_aversion: float,
    ) -> npt.NDArray[np.float64]:
        """Matriz ``k×m`` de señales con su dirección (mayor es mejor); ``NaN`` si no definidas."""
        m = weight_a
        with np.errstate(divide="ignore", invalid="ignore"):
            d_var = m * m * own_variance + 2.0 * m * (1.0 - m) * cov_rest
            d_var = d_var + ((1.0 - m) * (1.0 - m) - 1.0) * var_rest
            d_utility = m * (mu_a - mu_rest) - risk_aversion * d_var
            sigma_a = np.sqrt(own_variance)
            correlation = cov_rest / (sigma_a * np.sqrt(var_rest))
            risk_adjusted = (mu_a - self._risk_free_rate) / sigma_a
            liquidity = np.log(adv)
        rows = {
            "expected_alpha": mu_a,
            "marginal_risk_contribution": -d_var,
            "diversification_contribution": -correlation,
            "covariance_with_portfolio": -cov_rest,
            "expected_utility_gain": d_utility,
            "risk_adjusted_return": risk_adjusted,
            "liquidity": liquidity,
            "transaction_cost": cost_signal,
            "sector_fit": sector_fit,
        }
        stacked = np.vstack([rows[name] for name in SIGNAL_NAMES]).astype(np.float64)
        return np.asarray(np.where(np.isfinite(stacked), stacked, np.nan), dtype=np.float64)

    def _table(self, positions: npt.NDArray[np.int64], raw: npt.NDArray[np.float64]) -> SignalTable:
        config = self._config
        missing_raw = ~np.isfinite(raw)
        blocking = (missing_raw & self._active[:, np.newaxis]).any(axis=0)
        policy = config.missing_signal_policy
        if blocking.any() and policy is MissingSignalPolicy.ERROR:
            names = [int(position) for position in positions[blocking]]
            raise CandidateError(
                f"Señales de screening ausentes para las posiciones globales {names} "
                "(política ERROR)."
            )
        excluded = blocking & (policy is MissingSignalPolicy.EXCLUDE)
        normalized, missing = _normalize_rows(raw, ~excluded, config.normalization)
        filled = np.where(
            missing & self._active[:, np.newaxis], neutral_value(config.normalization), normalized
        )
        contribution = np.where(self._active[:, np.newaxis], filled, 0.0)
        score = np.asarray((self._weights[:, np.newaxis] * contribution).sum(axis=0))
        score = np.where(excluded, np.nan, score)
        pair = normalized[[ROW_DIVERSIFICATION, ROW_COVARIANCE]]
        available = (~np.isnan(pair)).sum(axis=0)
        diversification = np.where(
            available > 0, np.nansum(pair, axis=0) / np.maximum(available, 1), np.nan
        )
        return SignalTable(
            positions=positions,
            raw=raw,
            normalized=normalized,
            missing=missing,
            score=score,
            excluded=excluded,
            diversification=np.asarray(diversification, dtype=np.float64),
            imputed=missing & self._active[:, np.newaxis] & ~excluded[np.newaxis, :],
        )
