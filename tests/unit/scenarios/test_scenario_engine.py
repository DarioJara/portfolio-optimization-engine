"""SCN-002, SCN-003, SCN-009, TC-013: el ``ScenarioEngine`` transforma datos reales y verificables.

Cada escenario produce explícitamente ``μ_s``, ``Σ_s``, ``cost_s`` y ``constraints_s``. Las
transformaciones se comprueban con cálculo manual (``D Σ D``, mezcla de correlaciones, escalas y
desplazamientos), sin usar el mismo código bajo prueba.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.config import (
    AssetShock,
    ConstraintOverrides,
    CorrelationStress,
    CostShock,
    CustomScenarioInputs,
    GroupLimit,
    ScenarioDefinition,
    StressLimits,
)
from portfolio_engine.exceptions import (
    CovarianceEstimationError,
    NotPositiveSemidefiniteError,
    ScenarioError,
)
from portfolio_engine.models.enums import (
    CorrelationTarget,
    GroupDimension,
    PSDRepairMethod,
    ScenarioType,
    ShockSelector,
)
from portfolio_engine.scenarios import ScenarioEngine, scenario_hash
from tests.fixtures.block4 import CORR4, MU4, VOL4, four_asset_problem, scenario_definitions
from tests.fixtures.problems import base_config, cov_from_vol_corr, spec_with

pytestmark = pytest.mark.unit

CONFIG = base_config()
SIGMA4 = cov_from_vol_corr(VOL4, CORR4)
TECH = (0, 2)  # A000 y A002 son Tech en el universo sintético; A001 y A003 Energy


def _build(definitions: tuple[ScenarioDefinition, ...], config=CONFIG, problem=None, spec=None):  # type: ignore[no-untyped-def]
    problem = problem or four_asset_problem(config)
    engine = ScenarioEngine(config)
    return problem, engine.build(
        problem.risk_model,
        problem.universe,
        problem.costs,
        config.constraints,
        spec if spec is not None else problem.spec,
        definitions,
    )


def _definition(scenario_type=ScenarioType.STRESS, **fields):  # type: ignore[no-untyped-def]
    values = {
        "scenario_id": "S",
        "scenario_type": scenario_type,
        "probability": None,
        "description": None,
        "asset_shocks": (),
        "correlation_stress": None,
        "cost_shocks": (),
        "constraint_overrides": None,
        "stress_limits": None,
        "custom": None,
    }
    values.update(fields)
    return ScenarioDefinition(**values)


def test_base_without_modifications_preserves_the_original_data_object() -> None:
    """BASE sin modificaciones expresas: el mismo modelo de riesgo, costes y restricciones."""
    definition = _definition(ScenarioType.BASE, scenario_id="BASE")
    problem, scenarios = _build((definition,))
    base = scenarios.get("BASE")
    assert base.is_identity and base.transformations == ()
    assert base.risk_model is problem.risk_model  # ni copia ni recálculo
    assert base.costs is problem.costs
    assert base.constraints.constraints is CONFIG.constraints
    assert base.constraints.overrides_applied == ()
    assert base.risk_model.mu_sigma_version == scenarios.base_mu_sigma_version
    assert scenarios.base is base and scenarios.ids == ("BASE",)


def test_each_scenario_produces_mu_sigma_cost_and_constraints_explicitly() -> None:
    problem, scenarios = _build(scenario_definitions())
    assert scenarios.ids == ("BASE", "BEAR", "CRASH")
    for scenario in scenarios.scenarios:
        assert scenario.risk_model.mu.shape == (4,) and scenario.risk_model.sigma.shape == (4, 4)
        assert scenario.costs is not None and scenario.constraints.constraints is not None
        assert np.all(np.isfinite(scenario.risk_model.mu))
        np.testing.assert_array_equal(scenario.risk_model.sigma, scenario.risk_model.sigma.T)
        assert np.linalg.eigvalsh(scenario.risk_model.sigma)[0] > -1e-12
        assert scenario.scenario_hash == scenario_hash(scenario.definition)
    assert problem.risk_model.mu_sigma_version != scenarios.get("BEAR").risk_model.mu_sigma_version


def test_mu_shocks_scale_then_shift_only_the_selected_assets() -> None:
    shock = AssetShock(ShockSelector.SECTOR, ("Tech",), 0.5, -0.02, None)
    problem, scenarios = _build((_definition(asset_shocks=(shock,)),))
    expected = MU4.copy()
    expected[list(TECH)] = expected[list(TECH)] * 0.5 - 0.02
    np.testing.assert_allclose(scenarios.get("S").risk_model.mu, expected, rtol=0, atol=1e-15)
    np.testing.assert_array_equal(scenarios.get("S").risk_model.sigma, problem.risk_model.sigma)


def test_shocks_compose_in_order_and_asset_selectors_work() -> None:
    first = AssetShock(ShockSelector.ALL, (), 2.0, None, None)
    second = AssetShock(ShockSelector.ASSET, ("A001",), None, 0.01, None)
    _, scenarios = _build((_definition(asset_shocks=(first, second)),))
    expected = MU4 * 2.0
    expected[1] += 0.01
    np.testing.assert_allclose(scenarios.get("S").risk_model.mu, expected, atol=1e-15)
    # el orden importa: escala tras desplazar no es lo mismo
    swapped = _build((_definition(asset_shocks=(second, first)),))[1].get("S").risk_model.mu
    assert not np.allclose(swapped, expected)


def test_volatility_scaling_is_d_sigma_d_and_preserves_correlations() -> None:
    scale = np.array([1.5, 1.0, 2.0, 1.0])
    shocks = (
        AssetShock(ShockSelector.SECTOR, ("Tech",), None, None, 1.5),
        AssetShock(ShockSelector.ASSET, ("A002",), None, None, 2.0 / 1.5),
    )
    _, scenarios = _build((_definition(asset_shocks=shocks),))
    sigma_s = scenarios.get("S").risk_model.sigma
    np.testing.assert_allclose(sigma_s, np.diag(scale) @ SIGMA4 @ np.diag(scale), rtol=1e-14)
    std = np.sqrt(np.diag(sigma_s))
    np.testing.assert_allclose(sigma_s / np.outer(std, std), CORR4, atol=1e-14)  # correlaciones
    np.testing.assert_allclose(std, VOL4 * scale, rtol=1e-14)
    np.testing.assert_array_equal(scenarios.get("S").risk_model.mu, MU4)


def test_correlation_stress_mixes_towards_the_target_keeping_variances() -> None:
    rho, target = 0.4, 0.8
    stress = CorrelationStress(rho, CorrelationTarget.CONSTANT, target, None, None)
    _, scenarios = _build((_definition(correlation_stress=stress),))
    sigma_s = scenarios.get("S").risk_model.sigma
    np.testing.assert_allclose(np.diag(sigma_s), np.diag(SIGMA4), rtol=1e-14)  # varianzas intactas
    constant = np.full((4, 4), target)
    np.fill_diagonal(constant, 1.0)
    expected_corr = (1 - rho) * CORR4 + rho * constant
    std = np.sqrt(np.diag(SIGMA4))
    np.testing.assert_allclose(sigma_s, expected_corr * np.outer(std, std), rtol=1e-13)
    assert np.linalg.eigvalsh(sigma_s)[0] > 0
    # ρ = 0 no cambia nada y ρ = 1 impone exactamente la correlación objetivo
    none = _build((_definition(correlation_stress=dataclasses.replace(stress, intensity=0.0)),))[1]
    np.testing.assert_allclose(none.get("S").risk_model.sigma, SIGMA4, rtol=1e-13)
    full = _build((_definition(correlation_stress=dataclasses.replace(stress, intensity=1.0)),))[1]
    np.testing.assert_allclose(
        full.get("S").risk_model.sigma, constant * np.outer(std, std), rtol=1e-13
    )


def test_a_supplied_target_correlation_is_validated_and_used() -> None:
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    target = np.full((4, 4), 0.5)
    np.fill_diagonal(target, 1.0)
    stress = CorrelationStress(
        1.0, CorrelationTarget.SUPPLIED, None, ids, tuple(tuple(row) for row in target.tolist())
    )
    _, scenarios = _build((_definition(correlation_stress=stress),))
    std = np.sqrt(np.diag(SIGMA4))
    np.testing.assert_allclose(
        scenarios.get("S").risk_model.sigma, target * np.outer(std, std), rtol=1e-13
    )
    asymmetric = target.copy()
    asymmetric[0, 1] = 0.9
    bad = dataclasses.replace(stress, target_matrix=tuple(tuple(r) for r in asymmetric.tolist()))
    with pytest.raises(ScenarioError, match="simétrica"):
        _build((_definition(correlation_stress=bad),))
    indefinite = np.array([[1, 2, 0, 0], [2, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1.0]])
    not_psd = dataclasses.replace(
        stress, target_matrix=tuple(tuple(r) for r in indefinite.tolist())
    )
    with pytest.raises(ScenarioError, match="PSD"):
        _build((_definition(correlation_stress=not_psd),))
    bad_diagonal = dataclasses.replace(
        stress, target_matrix=tuple(tuple(r) for r in (target * 2.0).tolist())
    )
    with pytest.raises(ScenarioError, match="diagonal"):
        _build((_definition(correlation_stress=bad_diagonal),))
    other_ids = dataclasses.replace(stress, target_asset_ids=("A000", "A001", "A002", "AZZZ"))
    with pytest.raises(ScenarioError, match="cubrir exactamente"):
        _build((_definition(correlation_stress=other_ids),))


def test_a_zero_variance_asset_keeps_zero_covariance_under_correlation_stress() -> None:
    from tests.fixtures.problems import make_problem

    sigma = np.diag([0.04, 0.09, 0.0])
    sigma[0, 1] = sigma[1, 0] = 0.01
    problem = make_problem(np.array([0.05, 0.08, 0.02]), sigma, [1 / 3] * 3, CONFIG)
    stress = CorrelationStress(0.5, CorrelationTarget.CONSTANT, 0.9, None, None)
    _, scenarios = _build((_definition(correlation_stress=stress),), problem=problem)
    sigma_s = scenarios.get("S").risk_model.sigma
    np.testing.assert_array_equal(sigma_s[2], np.zeros(3))
    np.testing.assert_array_equal(sigma_s[:, 2], np.zeros(3))
    assert sigma_s[0, 1] > sigma[0, 1]  # la correlación entre los activos con riesgo sube


def test_sigma_s_is_validated_psd_and_a_repair_is_recorded_only_if_authorised() -> None:
    """SCN-003: una ``Σ_s`` no PSD se repara solo si la configuración lo autoriza, con registro."""
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    indefinite = np.array(
        [
            [0.04, 0.05, 0.0, 0.0],
            [0.05, 0.04, 0.0, 0.0],
            [0.0, 0.0, 0.09, 0.0],
            [0.0, 0.0, 0.0, 0.01],
        ]
    )
    custom = CustomScenarioInputs(ids, None, tuple(tuple(r) for r in indefinite.tolist()))
    definition = _definition(ScenarioType.CUSTOM, custom=custom)
    _, scenarios = _build((definition,))
    scenario = scenarios.get("S")
    assert scenario.covariance_repair is not None
    assert scenario.covariance_repair.method is CONFIG.risk.repair_method
    assert scenario.covariance_repair.original_min_eigenvalue < 0.0
    assert np.linalg.eigvalsh(scenario.risk_model.sigma)[0] > -1e-12
    strict = base_config(
        risk={"repair_method": PSDRepairMethod.NONE, "eigenvalue_floor_relative": None}
    )
    with pytest.raises(NotPositiveSemidefiniteError):
        _build((definition,), config=strict)
    asymmetric = CustomScenarioInputs(
        ids, None, ((0.04, 0.0, 0, 0), (0.05, 0.04, 0, 0), (0, 0, 0.09, 0), (0, 0, 0, 0.01))
    )
    with pytest.raises(CovarianceEstimationError, match="Asimetría"):
        _build((_definition(ScenarioType.CUSTOM, custom=asymmetric),))


def test_custom_inputs_replace_mu_and_sigma_and_must_cover_the_same_universe() -> None:
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    mu = (0.01, 0.02, 0.03, 0.04)
    sigma = np.diag([0.02, 0.03, 0.04, 0.05])
    custom = CustomScenarioInputs(ids, mu, tuple(tuple(r) for r in sigma.tolist()))
    _, scenarios = _build((_definition(ScenarioType.CUSTOM, custom=custom),))
    np.testing.assert_allclose(scenarios.get("S").risk_model.mu, mu)
    np.testing.assert_allclose(scenarios.get("S").risk_model.sigma, sigma)
    assert "custom_mu" in scenarios.get("S").transformations
    with pytest.raises(ScenarioError, match="mismos AssetID"):
        _build(
            (_definition(ScenarioType.CUSTOM, custom=CustomScenarioInputs(ids[:3], mu[:3], None)),)
        )
    # las transformaciones se aplican tras las entradas CUSTOM
    shocked = _definition(
        ScenarioType.CUSTOM,
        custom=CustomScenarioInputs(ids, mu, None),
        asset_shocks=(AssetShock(ShockSelector.ALL, (), None, 0.1, None),),
    )
    problem, built = _build((shocked,))
    result = built.get("S").risk_model
    np.testing.assert_allclose(result.mu, np.array(mu) + 0.1, atol=1e-15)
    np.testing.assert_array_equal(result.sigma, problem.risk_model.sigma)


def test_cost_multipliers_scale_buy_and_sell_costs_by_group_without_touching_the_original() -> None:
    problem = four_asset_problem(CONFIG)
    original = problem.costs
    assert original is not None
    before = (original.buy_costs.copy(), original.sell_costs.copy())
    shocks = (
        CostShock(ShockSelector.ALL, (), 2.0),
        CostShock(ShockSelector.SECTOR, ("Energy",), 1.5),
    )
    _, scenarios = _build((_definition(cost_shocks=shocks),), problem=problem)
    costs = scenarios.get("S").costs
    assert costs is not None and costs is not original
    factor = np.array([2.0, 3.0, 2.0, 3.0])
    np.testing.assert_allclose(costs.buy_costs, before[0] * factor)
    np.testing.assert_allclose(costs.sell_costs, before[1] * factor)
    np.testing.assert_array_equal(original.buy_costs, before[0])  # el original no se toca
    assert costs.sources == original.sources and costs.asset_ids == original.asset_ids
    problem_without_costs = dataclasses.replace(problem, costs=None)
    with pytest.raises(ScenarioError, match="no costes de partida"):
        _build((_definition(cost_shocks=shocks),), problem=problem_without_costs)


def test_constraint_overrides_build_constraints_s_and_leave_the_base_untouched() -> None:
    overrides = ConstraintOverrides(
        0.1, 0.02, 0.6, (GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.5),)
    )
    base_limits = (GroupLimit(GroupDimension.SECTOR, "Energy", None, 0.7),)
    config = dataclasses.replace(
        CONFIG, constraints=dataclasses.replace(CONFIG.constraints, group_limits=base_limits)
    )
    spec = spec_with(max_turnover=0.3)
    _, scenarios = _build((_definition(constraint_overrides=overrides),), config=config, spec=spec)
    scenario = scenarios.get("S")
    constraints = scenario.constraints.constraints
    assert constraints.global_max_turnover == 0.1
    assert constraints.global_min_weight == 0.02 and constraints.global_max_weight == 0.6
    assert {(g.group, g.max_weight) for g in constraints.group_limits} == {
        ("Energy", 0.7),
        ("Tech", 0.5),
    }
    assert scenario.constraints.spec is not None and scenario.constraints.spec.max_turnover == 0.1
    assert scenario.constraints.overrides_applied == (
        "max_turnover",
        "global_min_weight",
        "global_max_weight",
        "group_limits",
    )
    assert config.constraints.global_max_turnover is None and spec.max_turnover == 0.3
    # un límite del mismo (dimensión, grupo) sustituye al existente
    replaced = ConstraintOverrides(
        None, None, None, (GroupLimit(GroupDimension.SECTOR, "Energy", None, 0.4),)
    )
    merged = _build((_definition(constraint_overrides=replaced),), config=config)[1].get("S")
    assert [g.max_weight for g in merged.constraints.constraints.group_limits] == [0.4]
    with pytest.raises(ScenarioError, match="inválidos"):
        _build((_definition(constraint_overrides=ConstraintOverrides(None, 0.9, 0.1, ())),))


def test_a_selector_that_matches_nothing_is_an_error_not_a_silent_no_op() -> None:
    no_sector = AssetShock(ShockSelector.SECTOR, ("Biotech",), None, 0.1, None)
    with pytest.raises(ScenarioError, match="no coincide con ningún activo"):
        _build((_definition(asset_shocks=(no_sector,)),))
    unknown_asset = AssetShock(ShockSelector.ASSET, ("A999",), None, 0.1, None)
    with pytest.raises(ScenarioError, match="AssetID desconocidos"):
        _build((_definition(asset_shocks=(unknown_asset,)),))
    with pytest.raises(ScenarioError, match="no coincide"):
        _build((_definition(cost_shocks=(CostShock(ShockSelector.CURRENCY, ("JPY",), 2.0),)),))
    twin = AssetShock(ShockSelector.ALL, (), None, 0.01, None)
    with pytest.raises(ScenarioError, match="duplicados"):
        _build(
            (
                _definition(scenario_id="Z", asset_shocks=(twin,)),
                _definition(scenario_id="Z", asset_shocks=(twin,)),
            )
        )


def test_scenarios_never_modify_the_base_data_in_place() -> None:
    problem = four_asset_problem(CONFIG)
    mu_before = problem.risk_model.mu.copy()
    sigma_before = problem.risk_model.sigma.copy()
    version = problem.risk_model.mu_sigma_version
    _build(scenario_definitions(), problem=problem)
    np.testing.assert_array_equal(problem.risk_model.mu, mu_before)
    np.testing.assert_array_equal(problem.risk_model.sigma, sigma_before)
    assert problem.risk_model.mu_sigma_version == version
    _, scenarios = _build(scenario_definitions(), problem=problem)
    for scenario in scenarios.scenarios:
        assert not scenario.risk_model.mu.flags.writeable
        assert not scenario.risk_model.sigma.flags.writeable
        if not scenario.is_identity:
            assert scenario.risk_model.mu is not problem.risk_model.mu


def test_scenarios_are_reproducible_and_their_hash_tracks_the_parameters() -> None:
    first = _build(scenario_definitions())[1]
    second = _build(scenario_definitions())[1]
    for a, b in zip(first.scenarios, second.scenarios, strict=True):
        np.testing.assert_array_equal(a.risk_model.mu, b.risk_model.mu)
        np.testing.assert_array_equal(a.risk_model.sigma, b.risk_model.sigma)
        assert a.scenario_hash == b.scenario_hash
        assert a.risk_model.mu_sigma_version == b.risk_model.mu_sigma_version
    hashes = {s.scenario_hash for s in first.scenarios}
    assert len(hashes) == 3
    bear = first.get("BEAR").definition
    changed = dataclasses.replace(
        bear, asset_shocks=(AssetShock(ShockSelector.ALL, (), None, -0.06, 1.3),)
    )
    assert scenario_hash(changed) != scenario_hash(bear)
    other_probability = dataclasses.replace(bear, probability=0.31)
    assert scenario_hash(other_probability) != scenario_hash(bear)


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
def test_every_scenario_type_transforms_the_data_through_its_declared_parameters(
    scenario_type: ScenarioType,
) -> None:
    """Rates/equity/credit/FX se modelan por selectores de grupo (sector, clase, divisa)."""
    selector, value = {
        ScenarioType.RATE_UP: (ShockSelector.ASSET_CLASS, "Equity"),
        ScenarioType.RATE_DOWN: (ShockSelector.ASSET_CLASS, "Equity"),
        ScenarioType.CREDIT_WIDENING: (ShockSelector.SECTOR, "Energy"),
        ScenarioType.FX_SHOCK: (ShockSelector.CURRENCY, "EUR"),
        ScenarioType.EQUITY_CRASH: (ShockSelector.SECTOR, "Tech"),
    }.get(scenario_type, (ShockSelector.ALL, ""))
    shock = AssetShock(selector, () if selector is ShockSelector.ALL else (value,), 0.8, -0.03, 1.2)
    _, scenarios = _build((_definition(scenario_type, asset_shocks=(shock,)),))
    scenario = scenarios.get("S")
    assert scenario.scenario_type is scenario_type and not scenario.is_identity
    assert not np.allclose(scenario.risk_model.mu, MU4) and not np.allclose(
        scenario.risk_model.sigma, SIGMA4
    )


def test_stress_limits_and_probability_travel_with_the_scenario_data() -> None:
    limits = StressLimits(0.2, -0.05)
    definition = _definition(
        asset_shocks=(AssetShock(ShockSelector.ALL, (), None, -0.01, None),),
        stress_limits=limits,
        probability=0.25,
    )
    scenario = _build((definition,))[1].get("S")
    assert scenario.stress_limits is limits and scenario.probability == 0.25
