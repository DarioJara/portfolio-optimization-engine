"""Configuración global de los escenarios (MASTER_SPEC §53-54; CFG-010).

Los parámetros de cada escenario (shocks, probabilidad) no son configuración global: se declaran
como datos en :mod:`portfolio_engine.config.scenario_definitions` (decisión A-22). Aquí solo viven
las tolerancias con las que se validan.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_positive


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    """Tolerancias de validación de un conjunto de escenarios.

    Attributes:
        probability_sum_tolerance: desviación máxima de ``Σ p_s`` respecto de 1 en los modos que
            usan probabilidades; por encima se rechaza (las probabilidades no se renormalizan en
            silencio).
        correlation_tolerance: tolerancia de simetría y de diagonal unitaria de una matriz de
            correlación objetivo suministrada.
    """

    probability_sum_tolerance: float
    correlation_tolerance: float

    def __post_init__(self) -> None:
        require_positive(self.probability_sum_tolerance, "scenarios.probability_sum_tolerance")
        require_positive(self.correlation_tolerance, "scenarios.correlation_tolerance")
