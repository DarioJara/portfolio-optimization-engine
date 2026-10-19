"""SCN-001, SCN-010, CFG-010: definiciones declarativas de escenarios, probabilidades y carga TOML.

Ninguna magnitud de shock está en el código: todo procede de la definición; un escenario que no
define ninguna transformación se rechaza (el tipo no implica magnitudes).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_engine.config import (
    AssetShock,
    ConstraintOverrides,
    CorrelationStress,
    CostShock,
    CustomScenarioInputs,
    ScenarioConfig,
    ScenarioDefinition,
    StressLimits,
    load_scenario_definitions,
    validate_scenario_set,
)
from portfolio_engine.exceptions import ConfigError, ScenarioError
from portfolio_engine.models.enums import (
    CorrelationTarget,
    ScenarioType,
    ShockSelector,
)
from portfolio_engine.optimizers.formulations.multi_scenario import validated_probabilities

pytestmark = pytest.mark.unit


def _definition(
    scenario_type: ScenarioType = ScenarioType.BEAR, **fields: object
) -> ScenarioDefinition:
    values: dict[str, object] = {
        "scenario_id": "S",
        "scenario_type": scenario_type,
        "probability": None,
        "description": None,
        "asset_shocks": (AssetShock(ShockSelector.ALL, (), None, -0.05, None),),
        "correlation_stress": None,
        "cost_shocks": (),
        "constraint_overrides": None,
        "stress_limits": None,
        "custom": None,
    }
    values.update(fields)
    return ScenarioDefinition(**values)  # type: ignore[arg-type]


def test_all_ten_scenario_types_are_supported_as_labels() -> None:
    assert {t.value for t in ScenarioType} == {
        "BASE",
        "BULL",
        "BEAR",
        "STRESS",
        "RATE_UP",
        "RATE_DOWN",
        "EQUITY_CRASH",
        "CREDIT_WIDENING",
        "FX_SHOCK",
        "CUSTOM",
    }
    for scenario_type in ScenarioType:
        if scenario_type in (ScenarioType.BASE, ScenarioType.CUSTOM):
            continue
        assert _definition(scenario_type).scenario_type is scenario_type


def test_base_without_modifications_is_the_identity_and_needs_no_magnitudes() -> None:
    base = _definition(ScenarioType.BASE, asset_shocks=())
    assert base.is_identity and not base.has_transformations
    modified = _definition(ScenarioType.BASE)
    assert not modified.is_identity  # «modificaciones expresas» sobre BASE están permitidas


@pytest.mark.parametrize(
    "scenario_type",
    [
        ScenarioType.BULL,
        ScenarioType.BEAR,
        ScenarioType.STRESS,
        ScenarioType.RATE_UP,
        ScenarioType.RATE_DOWN,
        ScenarioType.EQUITY_CRASH,
        ScenarioType.CREDIT_WIDENING,
        ScenarioType.FX_SHOCK,
    ],
)
def test_a_typed_scenario_without_transformations_is_rejected_no_magnitude_is_assumed(
    scenario_type: ScenarioType,
) -> None:
    with pytest.raises(ConfigError, match=r"ninguna se asume por el tipo|no define ninguna"):
        _definition(scenario_type, asset_shocks=())


def test_custom_scenarios_need_inputs_or_transformations() -> None:
    with pytest.raises(ConfigError, match="CUSTOM"):
        _definition(ScenarioType.CUSTOM, asset_shocks=())
    custom = CustomScenarioInputs(("A", "B"), (0.01, 0.02), None)
    assert _definition(ScenarioType.CUSTOM, asset_shocks=(), custom=custom).custom is custom
    assert _definition(ScenarioType.CUSTOM).has_transformations  # solo con transformaciones


def test_probabilities_and_identifiers_are_validated() -> None:
    with pytest.raises(ConfigError, match=r"\[0, 1\]"):
        _definition(probability=1.2)
    with pytest.raises(ConfigError, match="finito"):
        _definition(probability=float("nan"))
    with pytest.raises(ConfigError, match="scenario_id"):
        _definition(scenario_id=" ")
    first, second = _definition(scenario_id="X"), _definition(scenario_id="X")
    with pytest.raises(ConfigError, match="duplicados"):
        validate_scenario_set((first, second))
    bases = (
        _definition(ScenarioType.BASE, scenario_id="B1", asset_shocks=()),
        _definition(ScenarioType.BASE, scenario_id="B2", asset_shocks=()),
    )
    with pytest.raises(ConfigError, match="Más de un escenario BASE"):
        validate_scenario_set(bases)


def test_probabilities_must_be_declared_non_negative_and_sum_to_one_without_normalization() -> None:
    """SCN-010: no se suponen iguales, no se renormalizan, y las inválidas se rechazan."""
    tolerance = 1e-9
    assert validated_probabilities([0.5, 0.3, 0.2], tolerance).tolist() == [0.5, 0.3, 0.2]
    with pytest.raises(ScenarioError, match="no se suponen iguales"):
        validated_probabilities([0.5, None, 0.5], tolerance)
    with pytest.raises(ScenarioError, match="suman"):
        validated_probabilities([0.5, 0.3], tolerance)  # suman 0,8: no se normaliza a 1
    with pytest.raises(ScenarioError, match="no negativas"):
        validated_probabilities([1.2, -0.2], tolerance)
    with pytest.raises(ScenarioError, match="finitas"):
        validated_probabilities([float("nan"), 1.0], tolerance)
    with pytest.raises(ScenarioError):
        validated_probabilities([], tolerance)


def test_component_dataclasses_reject_incoherent_parameters() -> None:
    with pytest.raises(ConfigError, match="ALL no admite"):
        AssetShock(ShockSelector.ALL, ("x",), 1.0, None, None)
    with pytest.raises(ConfigError, match="exige al menos un valor"):
        AssetShock(ShockSelector.SECTOR, (), 1.0, None, None)
    with pytest.raises(ConfigError, match="duplicados"):
        AssetShock(ShockSelector.SECTOR, ("a", "a"), 1.0, None, None)
    with pytest.raises(ConfigError, match="ninguna transformación"):
        AssetShock(ShockSelector.ALL, (), None, None, None)
    with pytest.raises(ConfigError, match="> 0"):
        AssetShock(ShockSelector.ALL, (), None, None, 0.0)
    with pytest.raises(ConfigError, match="intensity"):
        CorrelationStress(1.5, CorrelationTarget.CONSTANT, 0.5, None, None)
    with pytest.raises(ConfigError, match="constant"):
        CorrelationStress(0.5, CorrelationTarget.CONSTANT, None, None, None)
    with pytest.raises(ConfigError, match=r"\(-1, 1\)"):
        CorrelationStress(0.5, CorrelationTarget.CONSTANT, 1.0, None, None)
    with pytest.raises(ConfigError, match="SUPPLIED exige"):
        CorrelationStress(0.5, CorrelationTarget.SUPPLIED, None, None, None)
    with pytest.raises(ConfigError, match="n×n"):
        CorrelationStress(0.5, CorrelationTarget.SUPPLIED, None, ("A", "B"), ((1.0,),))
    with pytest.raises(ConfigError, match="negativo"):
        CostShock(ShockSelector.ALL, (), -1.0)
    with pytest.raises(ConfigError, match="vacío"):
        ConstraintOverrides(None, None, None, ())
    with pytest.raises(ConfigError, match="negativo"):
        ConstraintOverrides(-0.1, None, None, ())
    with pytest.raises(ConfigError, match="sin ningún límite"):
        StressLimits(None, None)
    with pytest.raises(ConfigError, match="> 0"):
        StressLimits(0.0, None)
    with pytest.raises(ConfigError, match="sin mu ni covariance"):
        CustomScenarioInputs(("A",), None, None)
    with pytest.raises(ConfigError, match="ordenado"):
        CustomScenarioInputs(("B", "A"), (0.0, 0.0), None)
    with pytest.raises(ConfigError, match="n×n"):
        CustomScenarioInputs(("A", "B"), None, ((1.0, 0.0),))
    with pytest.raises(ConfigError, match="finita"):
        CustomScenarioInputs(("A",), None, ((float("inf"),),))
    with pytest.raises(ConfigError, match="probability_sum_tolerance"):
        ScenarioConfig(0.0, 1e-9)


def test_overrides_report_their_keys_for_traceability() -> None:
    overrides = ConstraintOverrides(0.2, None, 0.6, ())
    assert overrides.keys == ("max_turnover", "global_max_weight")


_TOML = """
[[scenario]]
scenario_id = "BASE"
scenario_type = "BASE"
probability = 0.6

[[scenario]]
scenario_id = "BEAR"
scenario_type = "BEAR"
probability = 0.4
description = "mu -5 %, vol x1.3"
[[scenario.asset_shocks]]
selector = "ALL"
mu_shift = -0.05
vol_scale = 1.3

[[scenario]]
scenario_id = "CRASH"
scenario_type = "EQUITY_CRASH"
[[scenario.asset_shocks]]
selector = "SECTOR"
values = ["Tech"]
mu_scale = 0.5
[scenario.correlation_stress]
intensity = 0.4
target = "CONSTANT"
constant = 0.8
[[scenario.cost_shocks]]
selector = "ALL"
multiplier = 2.0
[scenario.stress_limits]
max_volatility = 0.2
[scenario.constraint_overrides]
max_turnover = 0.1
"""


def test_definitions_are_loaded_from_toml_with_strict_validation(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.toml"
    path.write_text(_TOML, encoding="utf-8")
    definitions = load_scenario_definitions(path)
    assert [d.scenario_id for d in definitions] == ["BASE", "BEAR", "CRASH"]
    assert definitions[0].is_identity and definitions[0].probability == 0.6
    bear = definitions[1]
    assert bear.asset_shocks[0].mu_shift == -0.05 and bear.asset_shocks[0].vol_scale == 1.3
    crash = definitions[2]
    assert crash.correlation_stress is not None and crash.correlation_stress.constant == 0.8
    assert crash.cost_shocks[0].multiplier == 2.0 and crash.stress_limits is not None
    assert crash.constraint_overrides is not None and crash.constraint_overrides.max_turnover == 0.1
    assert crash.probability is None  # no configurada: nunca se supone


def test_the_loader_rejects_unknown_keys_missing_keys_and_bad_values() -> None:
    with pytest.raises(ConfigError, match="Claves desconocidas"):
        load_scenario_definitions(
            {"scenario": [{"scenario_id": "X", "scenario_type": "BASE", "typo": 1}]}
        )
    with pytest.raises(ConfigError, match="obligatoria ausente"):
        load_scenario_definitions({"scenario": [{"scenario_type": "BASE"}]})
    with pytest.raises(ConfigError, match="uno de"):
        load_scenario_definitions({"scenario": [{"scenario_id": "X", "scenario_type": "MOON"}]})
    with pytest.raises(ConfigError, match="al menos un"):
        load_scenario_definitions({"scenario": []})
    with pytest.raises(ConfigError, match="Claves desconocidas en el fichero"):
        load_scenario_definitions({"scenarios": []})
    with pytest.raises(ConfigError, match="numérico"):
        load_scenario_definitions(
            {"scenario": [{"scenario_id": "X", "scenario_type": "BASE", "probability": "half"}]}
        )
    with pytest.raises(ConfigError, match="duplicados"):
        load_scenario_definitions(
            {
                "scenario": [
                    {"scenario_id": "X", "scenario_type": "BASE"},
                    {"scenario_id": "X", "scenario_type": "BASE"},
                ]
            }
        )
    with pytest.raises(ConfigError, match="No se puede leer"):
        load_scenario_definitions(Path("no-existe-este-fichero.toml"))
