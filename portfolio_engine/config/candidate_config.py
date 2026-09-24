"""Configuración del ``CandidateEngine`` (MASTER_SPEC §4, §26-31; CFG-009).

Toda decisión de búsqueda (anchura del haz, órdenes de sustitución, pesos del screening, reparto
exploración/explotación, presupuestos y perfiles de aversión al riesgo) procede de esta sección;
sus valores de ejemplo viven únicamente en ``config/default_engine.toml`` (decisión A-29).
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import (
    require_finite,
    require_int_at_least,
    require_non_negative,
    require_positive,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import (
    EvaluationMode,
    MissingSignalPolicy,
    ScreeningNormalization,
    UnknownFlagPolicy,
)

#: Nombres de las señales de screening, en el orden de ``ScreeningWeights.as_tuple``.
SIGNAL_NAMES = (
    "expected_alpha",
    "marginal_risk_contribution",
    "diversification_contribution",
    "covariance_with_portfolio",
    "expected_utility_gain",
    "risk_adjusted_return",
    "liquidity",
    "transaction_cost",
    "sector_fit",
)


@dataclass(frozen=True, slots=True)
class ScreeningWeights:
    """Pesos relativos de las nueve señales del screening (MASTER_SPEC §27).

    Son no negativos y no todos nulos; se normalizan al usarlos. Una señal con peso 0 no
    interviene en el score (ni le afecta su ausencia de datos).
    """

    expected_alpha: float
    marginal_risk_contribution: float
    diversification_contribution: float
    covariance_with_portfolio: float
    expected_utility_gain: float
    risk_adjusted_return: float
    liquidity: float
    transaction_cost: float
    sector_fit: float

    def __post_init__(self) -> None:
        values = self.as_tuple()
        for name, value in zip(SIGNAL_NAMES, values, strict=True):
            require_non_negative(value, f"candidates.screening_weights.{name}")
        if not sum(values) > 0:
            raise ConfigError("candidates.screening_weights: al menos un peso debe ser > 0.")

    def as_tuple(self) -> tuple[float, ...]:
        """Pesos en el orden de :data:`SIGNAL_NAMES`."""
        return (
            self.expected_alpha,
            self.marginal_risk_contribution,
            self.diversification_contribution,
            self.covariance_with_portfolio,
            self.expected_utility_gain,
            self.risk_adjusted_return,
            self.liquidity,
            self.transaction_cost,
            self.sector_fit,
        )


@dataclass(frozen=True, slots=True)
class ExplorationMix:
    """Reparto relativo de la lista corta de activos entrantes (MASTER_SPEC §28).

    ``exploit_share``: alta convicción (mejor score de screening); ``diversify_share``: menor
    correlación/covarianza con la cartera; ``explore_share``: muestra aleatoria determinista del
    resto. Son pesos relativos no negativos (se normalizan), no todos nulos.
    """

    exploit_share: float
    diversify_share: float
    explore_share: float

    def __post_init__(self) -> None:
        values = (self.exploit_share, self.diversify_share, self.explore_share)
        for name, value in zip(("exploit", "diversify", "explore"), values, strict=True):
            require_non_negative(value, f"candidates.exploration.{name}_share")
        if not sum(values) > 0:
            raise ConfigError("candidates.exploration: al menos un reparto debe ser > 0.")


@dataclass(frozen=True, slots=True)
class CandidateConfig:
    """Parámetros del ``CandidateEngine``: screening, sustituciones, haz y evaluación.

    Attributes:
        beam_width: composiciones que sobreviven por nivel de la búsqueda en haz (``B``).
        max_levels: niveles máximos de la búsqueda en haz y de la búsqueda local.
        swap_orders: órdenes de sustitución generados (``1`` = 1-swap, ``2`` = 2-swap, ``3`` =
            3-swap opcional). Estrictamente crecientes.
        shortlist_in: activos entrantes de la lista corta por nodo (top-K, decisión A-18).
        shortlist_out: activos salientes de la lista corta por nodo.
        max_neighbors_per_order: vecinos máximos por orden y nodo; el vecindario es exhaustivo
            solo si cabe en este límite (decisión A-18), si no se conservan los de mayor prior.
        max_evaluations: composiciones evaluadas como máximo **por perfil de aversión al riesgo y
            por fase** (búsqueda en haz y pulido con búsqueda local, cada una con su propio
            presupuesto). Tope total de una generación:
            ``len(utility_risk_aversions) × 2 × max_evaluations`` (más la raíz de cada perfil).
        max_candidates: composiciones devueltas como máximo (incluye la de referencia).
        stagnation_levels: niveles consecutivos sin mejora tras los que se detiene la búsqueda.
        improvement_tolerance: mejora mínima de utilidad que cuenta como progreso.
        diversity_min_distance: distancia mínima entre supervivientes del haz (nº de activos que
            difieren por un lado); ``1`` solo elimina duplicados.
        local_search_starts: finalistas pulidos con búsqueda local tras el haz (``0`` = ninguno).
        utility_risk_aversions: perfiles de aversión ``λ`` de la utilidad ``μᵀw − λ wᵀΣw − TC``
            con los que se busca (uno por región de la frontera); estrictamente crecientes.
        evaluation_mode: estimación de la utilidad de una composición (CAN-021).
        refinement_iterations: pasos de gradiente proyectado del modo ``PROJECTED_WEIGHTS``.
        screening_weights: pesos de las señales (MASTER_SPEC §27).
        normalization: normalización de las señales.
        missing_signal_policy: tratamiento de señales ausentes.
        unknown_liquidity_policy: tratamiento de un ``LiquidityFlag`` desconocido.
        exploration: reparto exploración/explotación de la lista corta.
        max_new_assets: ``MaximumNewAssets`` respecto a la cartera actual (``None`` = sin límite).
        max_swaps: ``MaximumSwaps`` respecto a la cartera actual (``None`` = sin límite).
        cold_start: permite generar composiciones sin cartera actual (decisión A-19).
        max_recorded_rejections: composiciones rechazadas que se conservan en los diagnósticos.
    """

    beam_width: int
    max_levels: int
    swap_orders: tuple[int, ...]
    shortlist_in: int
    shortlist_out: int
    max_neighbors_per_order: int
    max_evaluations: int
    max_candidates: int
    stagnation_levels: int
    improvement_tolerance: float
    diversity_min_distance: int
    local_search_starts: int
    utility_risk_aversions: tuple[float, ...]
    evaluation_mode: EvaluationMode
    refinement_iterations: int
    screening_weights: ScreeningWeights
    normalization: ScreeningNormalization
    missing_signal_policy: MissingSignalPolicy
    unknown_liquidity_policy: UnknownFlagPolicy
    exploration: ExplorationMix
    max_new_assets: int | None
    max_swaps: int | None
    cold_start: bool
    max_recorded_rejections: int

    def __post_init__(self) -> None:
        for name in (
            "beam_width",
            "max_levels",
            "shortlist_in",
            "shortlist_out",
            "max_neighbors_per_order",
            "max_evaluations",
            "max_candidates",
            "stagnation_levels",
            "diversity_min_distance",
        ):
            require_int_at_least(getattr(self, name), 1, f"candidates.{name}")
        for name in ("local_search_starts", "refinement_iterations", "max_recorded_rejections"):
            require_int_at_least(getattr(self, name), 0, f"candidates.{name}")
        require_non_negative(self.improvement_tolerance, "candidates.improvement_tolerance")
        self._check_orders()
        self._check_risk_aversions()
        for name in ("max_new_assets", "max_swaps"):
            value = getattr(self, name)
            if value is not None:
                require_int_at_least(value, 0, f"candidates.{name}")
        if not isinstance(self.cold_start, bool):
            raise ConfigError("candidates.cold_start debe ser booleano.")
        if self.evaluation_mode is EvaluationMode.QP_UTILITY and self.refinement_iterations != 0:
            raise ConfigError(
                "refinement_iterations solo se admite con evaluation_mode = PROJECTED_WEIGHTS "
                "(no se aceptan parámetros ignorados)."
            )

    def _check_orders(self) -> None:
        if not self.swap_orders:
            raise ConfigError("candidates.swap_orders no puede estar vacío.")
        for order in self.swap_orders:
            require_int_at_least(order, 1, "candidates.swap_orders[]")
        if list(self.swap_orders) != sorted(set(self.swap_orders)):
            raise ConfigError("candidates.swap_orders debe ser estrictamente creciente.")

    def _check_risk_aversions(self) -> None:
        if not self.utility_risk_aversions:
            raise ConfigError("candidates.utility_risk_aversions no puede estar vacío.")
        for value in self.utility_risk_aversions:
            require_finite(value, "candidates.utility_risk_aversions[]")
            require_positive(value, "candidates.utility_risk_aversions[]")
        if list(self.utility_risk_aversions) != sorted(set(self.utility_risk_aversions)):
            raise ConfigError("candidates.utility_risk_aversions debe ser estrictamente creciente.")
