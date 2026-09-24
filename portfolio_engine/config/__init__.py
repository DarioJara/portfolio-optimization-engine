"""Configuración centralizada e inmutable (MASTER_SPEC §4)."""

from portfolio_engine.config.benchmark_config import BenchmarkConfig
from portfolio_engine.config.candidate_config import (
    CandidateConfig,
    ExplorationMix,
    ScreeningWeights,
)
from portfolio_engine.config.constraint_config import (
    ConstraintConfig,
    FxRate,
    GroupLimit,
    LiquidityConfig,
)
from portfolio_engine.config.data_config import DataConfig
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.config.hashing import config_hash, config_snapshot, config_to_dict
from portfolio_engine.config.loader import load_engine_config
from portfolio_engine.config.return_config import ReturnConfig
from portfolio_engine.config.risk_config import RiskConfig
from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.config.transaction_cost_config import TransactionCostConfig

__all__ = (
    "BenchmarkConfig",
    "CandidateConfig",
    "ConstraintConfig",
    "DataConfig",
    "EngineConfig",
    "ExplorationMix",
    "FrontierConfig",
    "FxRate",
    "GroupLimit",
    "LiquidityConfig",
    "ReturnConfig",
    "RiskConfig",
    "ScreeningWeights",
    "SolverConfig",
    "TransactionCostConfig",
    "config_hash",
    "config_snapshot",
    "config_to_dict",
    "load_engine_config",
)
