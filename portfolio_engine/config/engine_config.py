"""Configuración raíz del motor (MASTER_SPEC §4).

Contiene las subconfiguraciones de los Bloques 1 a 4 y el parámetro centralizado
``optimization_horizon_years`` (``OptimizationHorizonYears``, enmienda E-03). Las
subconfiguraciones de bloques posteriores (paralelismo, persistencia) se añadirán en su bloque.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_int_at_least, require_positive
from portfolio_engine.config.benchmark_config import BenchmarkConfig
from portfolio_engine.config.candidate_config import CandidateConfig
from portfolio_engine.config.conic_config import ConicSolverConfig, SharpeConfig
from portfolio_engine.config.constraint_config import ConstraintConfig
from portfolio_engine.config.cvar_config import CVaRConfig
from portfolio_engine.config.data_config import DataConfig
from portfolio_engine.config.exact_mip_config import ExactMIPConfig
from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.config.hard_constraints_config import HardConstraintsConfig
from portfolio_engine.config.return_config import ReturnConfig
from portfolio_engine.config.risk_config import RiskConfig
from portfolio_engine.config.robust_config import RobustConfig
from portfolio_engine.config.scenario_config import ScenarioConfig
from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.config.transaction_cost_config import TransactionCostConfig
from portfolio_engine.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Configuración raíz inmutable.

    Attributes:
        optimization_horizon_years: horizonte ``H`` (años) sobre el que se comparan expected
            returns, costes y métricas netas (E-03). Única fuente de verdad.
        random_seed: semilla raíz de toda aleatoriedad del motor.
        hard_constraints: restricciones obligatorias de las carteras finales (global, perfiles y
            carteras). ``None`` = módulo no configurado: el motor se comporta exactamente como
            antes y el ``ConfigHash`` no cambia (``config_to_dict`` omite el campo si es ``None``).
    """

    data: DataConfig
    returns: ReturnConfig
    risk: RiskConfig
    constraints: ConstraintConfig
    transaction_costs: TransactionCostConfig
    frontier: FrontierConfig
    solver: SolverConfig
    benchmark: BenchmarkConfig
    candidates: CandidateConfig
    conic: ConicSolverConfig
    sharpe: SharpeConfig
    cvar: CVaRConfig
    exact_mip: ExactMIPConfig
    robust: RobustConfig
    scenarios: ScenarioConfig
    optimization_horizon_years: float
    random_seed: int
    hard_constraints: HardConstraintsConfig | None = None

    def __post_init__(self) -> None:
        expected_types = {
            "data": DataConfig,
            "returns": ReturnConfig,
            "risk": RiskConfig,
            "constraints": ConstraintConfig,
            "transaction_costs": TransactionCostConfig,
            "frontier": FrontierConfig,
            "solver": SolverConfig,
            "benchmark": BenchmarkConfig,
            "candidates": CandidateConfig,
            "conic": ConicSolverConfig,
            "sharpe": SharpeConfig,
            "cvar": CVaRConfig,
            "exact_mip": ExactMIPConfig,
            "robust": RobustConfig,
            "scenarios": ScenarioConfig,
        }
        for name, expected in expected_types.items():
            if not isinstance(getattr(self, name), expected):
                raise ConfigError(f"{name} debe ser {expected.__name__}.")
        if self.hard_constraints is not None and not isinstance(
            self.hard_constraints, HardConstraintsConfig
        ):
            raise ConfigError("hard_constraints debe ser HardConstraintsConfig o None.")
        require_positive(self.optimization_horizon_years, "optimization_horizon_years")
        require_int_at_least(self.random_seed, 0, "random_seed")
