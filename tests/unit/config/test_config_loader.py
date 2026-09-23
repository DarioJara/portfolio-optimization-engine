"""CFG-001 … CFG-006, CFG-016: carga estricta y validación de la configuración."""

from __future__ import annotations

import copy
import tomllib
from typing import Any

import pytest

from portfolio_engine.config import EngineConfig, load_engine_config
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import (
    CostSource,
    CovarianceMethod,
    PSDRepairMethod,
    RestrictedExistingPositionPolicy,
    ReturnKind,
)
from tests.conftest import DEFAULT_CONFIG_PATH

pytestmark = pytest.mark.unit


@pytest.fixture()
def raw() -> dict[str, Any]:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _load(raw: dict[str, Any]) -> EngineConfig:
    return load_engine_config(copy.deepcopy(raw))


def test_default_config_loads_with_typed_values(config: EngineConfig) -> None:
    assert config.returns.return_kind is ReturnKind.ARITHMETIC
    assert config.returns.trading_days_per_year == 252
    assert config.risk.covariance_method is CovarianceMethod.LEDOIT_WOLF
    assert config.risk.repair_method is PSDRepairMethod.EIGENVALUE_FLOOR
    assert config.transaction_costs.source_precedence == (
        CostSource.BUY_SELL,
        CostSource.ESTIMATED,
        CostSource.BID_ASK_SPREAD,
    )
    assert (
        config.constraints.restricted_existing_position_policy
        is RestrictedExistingPositionPolicy.HOLD_OR_REDUCE
    )
    # Campos opcionales omitidos en el TOML valen None, no un default oculto.
    assert config.data.cash_asset_id is None
    assert config.risk.condition_number_limit is None


@pytest.mark.parametrize(
    ("section", "key"),
    [("data", "unexpected"), ("risk", "psd_tol"), ("engine", "horizon")],
)
def test_unknown_keys_are_rejected(raw: dict[str, Any], section: str, key: str) -> None:
    raw[section][key] = 1
    with pytest.raises(ConfigError, match="desconocidas"):
        _load(raw)


def test_unknown_section_is_rejected(raw: dict[str, Any]) -> None:
    raw["frontier"] = {"points": 20}
    with pytest.raises(ConfigError, match="desconocidas"):
        _load(raw)


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("returns", "trading_days_per_year"),
        ("risk", "psd_tolerance"),
        ("data", "min_return_observations"),
        ("transaction_costs", "max_unit_cost"),
        ("constraints", "long_only"),
    ],
)
def test_required_keys_have_no_implicit_default(
    raw: dict[str, Any], section: str, key: str
) -> None:
    del raw[section][key]
    with pytest.raises(ConfigError, match="obligatoria ausente"):
        _load(raw)


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("returns", "trading_days_per_year", True, "entero"),
        ("returns", "trading_days_per_year", 252.0, "entero"),
        ("constraints", "long_only", 1, "booleano"),
        ("risk", "covariance_method", "OAS", "uno de"),
        ("risk", "covariance_method", "EWMA", "uno de"),
        ("transaction_costs", "source_precedence", "BUY_SELL", "lista"),
        ("risk", "psd_tolerance", "0.1", "numérico"),
    ],
)
def test_types_and_enum_names_are_checked(
    raw: dict[str, Any], section: str, key: str, value: object, message: str
) -> None:
    raw[section][key] = value
    with pytest.raises(ConfigError, match=message):
        _load(raw)


@pytest.mark.parametrize(
    ("section", "changes", "message"),
    [
        ("returns", {"return_kind": "LOG"}, "justification"),
        ("returns", {"log_return_justification": "x"}, "solo se admite"),
        ("returns", {"trading_days_per_year": 0}, "≥ 1"),
        ("data", {"min_return_observations": 1}, "≥ 2"),
        ("data", {"residual_weight_policy": "ASSIGN_TO_CASH"}, "cash_asset_id"),
        ("data", {"cash_asset_id": "CASH"}, "solo se admite"),
        ("data", {"outlier_threshold": 0.0}, "> 0"),
        ("risk", {"empirical_ddof": 2}, "0 o 1"),
        ("risk", {"repair_method": "NONE"}, "solo se admite con EIGENVALUE_FLOOR"),
        ("risk", {"eigenvalue_floor_relative": -1.0}, "> 0"),
        (
            "risk",
            {"repair_method": "NEAREST_PSD", "condition_number_limit": 1e6},
            "eigenvalue_floor_relative solo",
        ),
        ("transaction_costs", {"source_precedence": ["BUY_SELL", "BUY_SELL"]}, "repetidas"),
        ("transaction_costs", {"source_precedence": []}, "no vacía"),
        ("transaction_costs", {"spread_commission": 0.2}, "no puede superar"),
        ("constraints", {"global_min_weight": 0.3, "global_max_weight": 0.2}, "no puede superar"),
        ("constraints", {"global_min_weight": -0.1}, "negativo"),
    ],
)
def test_incoherent_values_are_rejected(
    raw: dict[str, Any], section: str, changes: dict[str, object], message: str
) -> None:
    raw[section].update(changes)
    with pytest.raises(ConfigError, match=message):
        _load(raw)


def test_condition_limit_requires_floor_repair(raw: dict[str, Any]) -> None:
    raw["risk"].update({"repair_method": "NEAREST_PSD", "condition_number_limit": 1e6})
    del raw["risk"]["eigenvalue_floor_relative"]
    with pytest.raises(ConfigError, match="condition_number_limit exige"):
        _load(raw)


def test_log_returns_accepted_with_justification(raw: dict[str, Any]) -> None:
    raw["returns"].update(
        {"return_kind": "LOG", "log_return_justification": "Agregación temporal de escenarios"}
    )
    config = _load(raw)
    assert config.returns.return_kind is ReturnKind.LOG


def test_unreadable_file_is_config_error(tmp_path: Any) -> None:
    broken = tmp_path / "broken.toml"
    broken.write_text("[engine\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="No se puede leer"):
        load_engine_config(broken)
