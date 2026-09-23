"""Configuración raíz del motor (MASTER_SPEC §4).

Contiene las subconfiguraciones del Bloque 1 y el parámetro centralizado
``optimization_horizon_years`` (``OptimizationHorizonYears``, enmienda E-03). Las
subconfiguraciones de bloques posteriores (frontera, solver, candidatos, escenarios,
paralelismo, persistencia, benchmark) se añadirán en su bloque.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_int_at_least, require_positive
from portfolio_engine.config.constraint_config import ConstraintConfig
from portfolio_engine.config.data_config import DataConfig
from portfolio_engine.config.return_config import ReturnConfig
from portfolio_engine.config.risk_config import RiskConfig
from portfolio_engine.config.transaction_cost_config import TransactionCostConfig
from portfolio_engine.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Configuración raíz inmutable.

    Attributes:
        optimization_horizon_years: horizonte ``H`` (años) sobre el que se comparan expected
            returns, costes y métricas netas (E-03). Única fuente de verdad.
        random_seed: semilla raíz de toda aleatoriedad del motor.
    """

    data: DataConfig
    returns: ReturnConfig
    risk: RiskConfig
    constraints: ConstraintConfig
    transaction_costs: TransactionCostConfig
    optimization_horizon_years: float
    random_seed: int

    def __post_init__(self) -> None:
        expected_types = {
            "data": DataConfig,
            "returns": ReturnConfig,
            "risk": RiskConfig,
            "constraints": ConstraintConfig,
            "transaction_costs": TransactionCostConfig,
        }
        for name, expected in expected_types.items():
            if not isinstance(getattr(self, name), expected):
                raise ConfigError(f"{name} debe ser {expected.__name__}.")
        require_positive(self.optimization_horizon_years, "optimization_horizon_years")
        require_int_at_least(self.random_seed, 0, "random_seed")
