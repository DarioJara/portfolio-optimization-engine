"""Datos de un escenario construido: ``μ_s``, ``Σ_s``, ``cost_s`` y ``constraints_s`` (SCN-002).

Un :class:`ScenarioData` es el resultado **explícito** de aplicar una
:class:`~portfolio_engine.config.ScenarioDefinition` al modelo base: el modelo de riesgo del
escenario (``μ_s`` y ``Σ_s`` validada PSD, con su ``MuSigmaVersion``), los costes del escenario, las
restricciones del escenario y la trazabilidad de qué se transformó. Es inmutable y reproducible: el
mismo modelo base y la misma definición producen los mismos datos y el mismo ``ScenarioHash``.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config.constraint_config import ConstraintConfig
from portfolio_engine.config.scenario_definitions import ScenarioDefinition, StressLimits
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import ScenarioType
from portfolio_engine.models.portfolio import PortfolioSpec
from portfolio_engine.models.risk_model import PSDRepairReport, RiskModel


@dataclass(frozen=True, eq=False, slots=True)
class ScenarioConstraints:
    """``constraints_s``: la configuración de restricciones y la especificación de cartera del
    escenario (con los overrides aplicados) y los nombres de los overrides efectivos."""

    constraints: ConstraintConfig
    spec: PortfolioSpec | None
    overrides_applied: tuple[str, ...]


@dataclass(frozen=True, eq=False, slots=True)
class ScenarioData:
    """Datos completos de un escenario para una cartera.

    Attributes:
        scenario_id: ``ScenarioID``.
        scenario_type: etiqueta de tipo del escenario.
        probability: probabilidad declarada (``None`` si no se declaró).
        risk_model: ``μ_s`` y ``Σ_s`` (PSD validada) con su ``MuSigmaVersion``; para un escenario
            ``BASE`` sin modificaciones es **el mismo objeto** que el modelo base.
        costs: ``cost_s`` (``None`` si no hay costes de partida).
        constraints: ``constraints_s``.
        stress_limits: límites de estrés declarados (``BaseWithStress``).
        scenario_hash: hash determinista de la definición (clave de caché ``ScenarioHash``).
        is_identity: ``True`` si no modifica ningún dato base.
        transformations: descripción legible de las transformaciones aplicadas (auditoría).
        covariance_repair: reparación PSD de ``Σ_s`` si fue necesaria (``None`` si no).
        definition: la definición de origen.
    """

    scenario_id: str
    scenario_type: ScenarioType
    probability: float | None
    risk_model: RiskModel
    costs: AssetCostVector | None
    constraints: ScenarioConstraints
    stress_limits: StressLimits | None
    scenario_hash: str
    is_identity: bool
    transformations: tuple[str, ...]
    covariance_repair: PSDRepairReport | None
    definition: ScenarioDefinition


@dataclass(frozen=True, eq=False, slots=True)
class ScenarioSet:
    """Conjunto ordenado de escenarios construidos sobre un mismo modelo base."""

    scenarios: tuple[ScenarioData, ...]
    base_mu_sigma_version: str

    def get(self, scenario_id: str) -> ScenarioData:
        """Escenario ``scenario_id`` (``KeyError`` si no existe)."""
        for scenario in self.scenarios:
            if scenario.scenario_id == scenario_id:
                return scenario
        raise KeyError(scenario_id)

    @property
    def ids(self) -> tuple[str, ...]:
        """``ScenarioID`` en orden."""
        return tuple(scenario.scenario_id for scenario in self.scenarios)

    @property
    def base(self) -> ScenarioData | None:
        """El escenario de tipo ``BASE`` (``None`` si no hay)."""
        for scenario in self.scenarios:
            if scenario.scenario_type is ScenarioType.BASE:
                return scenario
        return None
