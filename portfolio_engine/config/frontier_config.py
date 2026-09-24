"""Configuración de fronteras eficientes (MASTER_SPEC §4, §35-43; CFG-007).

Los valores por defecto (p. ej. 20 puntos) viven únicamente en ``config/default_engine.toml``
(decisión A-29).
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import (
    require_int_at_least,
    require_non_negative,
    require_positive,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import GridScale, ThetaGridMode


@dataclass(frozen=True, slots=True)
class FrontierConfig:
    """Parámetros de las mallas de theta y de retorno objetivo, frontera adaptativa y filtros.

    Attributes:
        frontier_points: número máximo de puntos (incluye los extremos MinVariance/MaxReturn).
        adaptive: activa la frontera adaptativa (MASTER_SPEC §42).
        initial_frontier_points: puntos de la malla inicial; solo con ``adaptive`` (y entonces
            ``2 <= initial < frontier_points``).
        adaptive_gap_tolerance: hueco normalizado por debajo del cual no se inserta; solo con
            ``adaptive``.
        theta_grid_mode: ``EXPLICIT`` (``theta_min``/``theta_max``) o ``AUTO`` (calibrado desde
            los extremos con los multiplicadores, decisión A-16).
        theta_min: theta mínimo (solo ``EXPLICIT``).
        theta_max: theta máximo (solo ``EXPLICIT``).
        theta_scale: espaciado de la malla de theta.
        theta_auto_min_multiplier: theta mínimo = multiplicador × theta de referencia (``AUTO``).
        theta_auto_max_multiplier: theta máximo = multiplicador × theta de referencia (``AUTO``).
        dedup_weight_tolerance: tolerancia (norma infinito) en pesos para deduplicar.
        dedup_return_tolerance: tolerancia en retorno bruto para deduplicar.
        dedup_volatility_tolerance: tolerancia en volatilidad para deduplicar.
        pareto_tolerance: tolerancia de dominancia en (volatilidad, retorno).
        zero_weight_tolerance: peso por debajo del cual un activo no cuenta como mantenido.
        zero_volatility_tolerance: volatilidad por debajo de la cual el Sharpe no se define.
        min_holding_weight: peso mínimo estricto para todo activo de la composición (decisión
            A-08); ``None`` = no exigido.
    """

    frontier_points: int
    adaptive: bool
    initial_frontier_points: int | None
    adaptive_gap_tolerance: float | None
    theta_grid_mode: ThetaGridMode
    theta_min: float | None
    theta_max: float | None
    theta_scale: GridScale
    theta_auto_min_multiplier: float
    theta_auto_max_multiplier: float
    dedup_weight_tolerance: float
    dedup_return_tolerance: float
    dedup_volatility_tolerance: float
    pareto_tolerance: float
    zero_weight_tolerance: float
    zero_volatility_tolerance: float
    min_holding_weight: float | None

    def __post_init__(self) -> None:
        require_int_at_least(self.frontier_points, 2, "frontier.frontier_points")
        if not isinstance(self.adaptive, bool):
            raise ConfigError("frontier.adaptive debe ser booleano.")
        self._check_adaptive()
        self._check_theta()
        for name in (
            "dedup_weight_tolerance",
            "dedup_return_tolerance",
            "dedup_volatility_tolerance",
            "pareto_tolerance",
            "zero_weight_tolerance",
            "zero_volatility_tolerance",
        ):
            require_non_negative(getattr(self, name), f"frontier.{name}")
        if self.min_holding_weight is not None:
            require_non_negative(self.min_holding_weight, "frontier.min_holding_weight")

    def _check_adaptive(self) -> None:
        initial, gap = self.initial_frontier_points, self.adaptive_gap_tolerance
        if not self.adaptive:
            if initial is not None or gap is not None:
                raise ConfigError(
                    "initial_frontier_points y adaptive_gap_tolerance solo se admiten con "
                    "adaptive = true (no se aceptan parámetros ignorados)."
                )
            return
        if initial is None or gap is None:
            raise ConfigError(
                "adaptive = true exige initial_frontier_points y adaptive_gap_tolerance."
            )
        require_int_at_least(initial, 2, "frontier.initial_frontier_points")
        if initial >= self.frontier_points:
            raise ConfigError("initial_frontier_points debe ser menor que frontier_points.")
        require_positive(gap, "frontier.adaptive_gap_tolerance")

    def _check_theta(self) -> None:
        require_positive(self.theta_auto_min_multiplier, "frontier.theta_auto_min_multiplier")
        require_positive(self.theta_auto_max_multiplier, "frontier.theta_auto_max_multiplier")
        if self.theta_auto_min_multiplier >= self.theta_auto_max_multiplier:
            raise ConfigError("theta_auto_min_multiplier debe ser menor que el máximo.")
        if self.theta_grid_mode is ThetaGridMode.EXPLICIT:
            if self.theta_min is None or self.theta_max is None:
                raise ConfigError("theta_grid_mode = EXPLICIT exige theta_min y theta_max.")
            require_positive(self.theta_min, "frontier.theta_min")
            require_positive(self.theta_max, "frontier.theta_max")
            if self.theta_min >= self.theta_max:
                raise ConfigError("theta_min debe ser menor que theta_max.")
        elif self.theta_min is not None or self.theta_max is not None:
            raise ConfigError("theta_min/theta_max solo se admiten con theta_grid_mode = EXPLICIT.")
