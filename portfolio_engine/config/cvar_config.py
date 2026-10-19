"""Configuración del CVaR (MASTER_SPEC §22; decisión A-35; CFG-001, CFG-015).

El CVaR se define sobre escenarios de retorno **por periodo** (históricos o simulados) con un nivel
de confianza ``β``; el límite ``MaxCVaR`` se expresa en el horizonte declarado por
``horizon_scaling``. Nada se asume: cada parámetro es explícito.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from portfolio_engine.config._validation import (
    require_finite,
    require_int_at_least,
    require_non_negative,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import HorizonScaling, ScenarioWeighting


@dataclass(frozen=True, slots=True)
class CVaRConfig:
    """Parámetros de CVaR/Expected Shortfall de Rockafellar-Uryasev.

    Attributes:
        confidence_level: nivel ``β`` en ``(0, 1)``; CVaR = pérdida media de la cola ``1 − β``.
        weighting: ``EQUAL`` (medida empírica uniforme, declarada) o ``EXPLICIT`` (pesos de
            escenario suministrados con los datos).
        horizon_periods: número de periodos de los datos que componen el horizonte del límite.
        horizon_scaling: ``NONE`` (horizonte = periodo; exige ``horizon_periods = 1``), ``LINEAR``
            (``×h``) o ``SQRT_TIME`` (``×√h``, supuesto de incrementos independientes).
        min_tail_observations: observaciones mínimas en la cola ``(1 − β)·T``; con menos la cola
            está mal estimada y se rechaza.
        max_cvar: ``MaxCVaR`` por defecto en unidades de pérdida del horizonte (``None`` = sin
            límite configurado).
    """

    confidence_level: float
    weighting: ScenarioWeighting
    horizon_periods: int
    horizon_scaling: HorizonScaling
    min_tail_observations: int
    max_cvar: float | None

    def __post_init__(self) -> None:
        require_finite(self.confidence_level, "cvar.confidence_level")
        if not 0.0 < self.confidence_level < 1.0:
            raise ConfigError("cvar.confidence_level debe estar en (0, 1).")
        require_int_at_least(self.horizon_periods, 1, "cvar.horizon_periods")
        require_int_at_least(self.min_tail_observations, 1, "cvar.min_tail_observations")
        if self.horizon_scaling is HorizonScaling.NONE and self.horizon_periods != 1:
            raise ConfigError("horizon_scaling = NONE exige cvar.horizon_periods = 1.")
        if self.max_cvar is not None:
            require_non_negative(self.max_cvar, "cvar.max_cvar")

    @property
    def horizon_factor(self) -> float:
        """Factor que lleva una pérdida por periodo al horizonte del límite."""
        if self.horizon_scaling is HorizonScaling.LINEAR:
            return float(self.horizon_periods)
        if self.horizon_scaling is HorizonScaling.SQRT_TIME:
            return math.sqrt(self.horizon_periods)
        return 1.0
