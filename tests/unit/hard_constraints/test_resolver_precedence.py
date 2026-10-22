"""HC-005, HC-010: una única fuente de verdad con precedencia global < perfil < cartera.

Comprueba que un nivel posterior solo puede endurecer un límite, que relajarlo exige una
autorización explícita y trazable, que los campos del motor que ya existían se integran, la
política de cardinalidad (FIXED por defecto) y que los parámetros efectivos y su hash son
deterministas y sensibles a cualquier cambio.
"""

from __future__ import annotations

import dataclasses

import pytest

from portfolio_engine.config import (
    HardConstraintsConfig,
    MandateLevel,
    MandateSettings,
    RelaxationAuthorization,
    config_hash,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.hard_constraints.resolver import (
    derive_engine_config,
    resolve_hard_constraints,
)
from portfolio_engine.models.enums import CardinalityPolicy
from portfolio_engine.models.portfolio import WeightBounds
from tests.fixtures.hard_constraints import (
    BAND_PARAMS,
    HELD,
    POSITION_FLOOR,
    effective_of,
    eleven_asset_problem,
    mandate_settings,
    with_mandate,
)
from tests.fixtures.problems import base_config, spec_with

pytestmark = pytest.mark.unit


def _auth(field: str) -> RelaxationAuthorization:
    return RelaxationAuthorization(field, "Comité de Riesgos", "Mandato aprobado", "ACTA-1")


def _level(name: str, *, profile: str | None = None, auth: tuple[str, ...] = (), **fields):  # type: ignore[no-untyped-def]
    return MandateLevel(
        name, MandateSettings(**fields), tuple(_auth(f) for f in auth), profile=profile
    )


@pytest.fixture(scope="module")
def problem():  # type: ignore[no-untyped-def]
    return eleven_asset_problem(base_config())


def test_the_default_policy_is_fixed_and_covers_exactly_the_original_size(problem):  # type: ignore[no-untyped-def]
    effective = effective_of(with_mandate(), problem)
    assert effective.cardinality_policy is CardinalityPolicy.FIXED
    assert effective.provenance_of("cardinality_policy") == "DEFAULT_FIXED"
    assert (effective.original_size, effective.size_min, effective.size_max) == (HELD, HELD, HELD)
    assert effective.allowed_sizes == (HELD,)


def test_increase_and_decrease_policies_build_bounded_size_intervals(problem):  # type: ignore[no-untyped-def]
    up = effective_of(
        with_mandate(cardinality_policy=CardinalityPolicy.INCREASE, max_size_increase=2), problem
    )
    assert up.allowed_sizes == (HELD, HELD + 1, HELD + 2)
    down = effective_of(
        with_mandate(cardinality_policy=CardinalityPolicy.DECREASE, max_size_decrease=3), problem
    )
    assert down.allowed_sizes == tuple(range(HELD - 3, HELD + 1))
    capped = effective_of(
        with_mandate(
            cardinality_policy=CardinalityPolicy.INCREASE, max_size_increase=5, max_size=HELD + 1
        ),
        problem,
    )
    assert capped.allowed_sizes == (HELD, HELD + 1)
    floor = effective_of(
        with_mandate(
            cardinality_policy=CardinalityPolicy.DECREASE, max_size_decrease=5, min_size=HELD - 1
        ),
        problem,
    )
    assert floor.allowed_sizes == (HELD - 1, HELD)


def test_unbounded_increase_or_decrease_is_a_configuration_error(problem):  # type: ignore[no-untyped-def]
    with pytest.raises(ConfigError, match="INCREASE exige"):
        effective_of(with_mandate(cardinality_policy=CardinalityPolicy.INCREASE), problem)
    with pytest.raises(ConfigError, match="DECREASE exige"):
        effective_of(with_mandate(cardinality_policy=CardinalityPolicy.DECREASE), problem)


def test_an_explicit_target_must_be_compatible_with_the_policy(problem):  # type: ignore[no-untyped-def]
    inside = effective_of(
        with_mandate(
            cardinality_policy=CardinalityPolicy.INCREASE, max_size_increase=3, target_size=HELD + 2
        ),
        problem,
    )
    assert inside.allowed_sizes == (HELD + 2,)
    outside = effective_of(with_mandate(target_size=HELD + 2), problem)  # FIXED
    assert outside.allowed_sizes == ()  # el intervalo de la política no lo admite


def test_a_stricter_profile_and_portfolio_tighten_the_global_limits(problem):  # type: ignore[no-untyped-def]
    config = with_mandate(
        max_volatility=0.18,
        max_replacements=3,
        profiles=(_level("CONSERVATIVE", max_volatility=0.12),),
        portfolios=(_level("P1", profile="CONSERVATIVE", max_replacements=2),),
    )
    effective = effective_of(config, problem)
    assert effective.max_volatility == 0.12 and effective.max_replacements == 2
    assert effective.risk_profile == "CONSERVATIVE"
    assert effective.provenance_of("max_volatility") == "PROFILE:CONSERVATIVE"
    assert effective.provenance_of("max_replacements") == "PORTFOLIO:P1"
    assert effective.relaxations == ()


@pytest.mark.parametrize(
    ("field", "global_value", "override"),
    [
        ("max_volatility", 0.18, 0.25),
        ("min_volatility", 0.08, 0.05),
        ("max_replacements", 3, 5),
        ("max_active_weight", 0.20, 0.30),
        ("min_active_weight", 0.03, 0.02),
        ("max_concentration_hhi", 0.20, 0.40),
        ("max_total_changed_assets", 4, 8),
    ],
)
def test_relaxing_a_mandatory_limit_without_authorization_is_rejected(
    problem, field: str, global_value: float, override: float
) -> None:  # type: ignore[no-untyped-def]
    extra = dict(BAND_PARAMS) if field == "min_volatility" else {}
    base = {field: global_value, **extra}
    base["min_active_weight"] = base.get("min_active_weight", POSITION_FLOOR)
    config = with_mandate(**base, portfolios=(_level("P1", **{field: override}),))
    with pytest.raises(ConfigError, match="MANDATE_RELAXATION_NOT_AUTHORIZED"):
        effective_of(config, problem)


def test_an_explicit_traceable_authorization_allows_the_relaxation_and_is_recorded(problem):  # type: ignore[no-untyped-def]
    config = with_mandate(
        max_volatility=0.18,
        portfolios=(_level("P1", max_volatility=0.25, auth=("max_volatility",)),),
    )
    effective = effective_of(config, problem)
    assert effective.max_volatility == 0.25
    (applied,) = effective.relaxations
    assert (applied.field, applied.authorized_by, applied.reference) == (
        "max_volatility",
        "Comité de Riesgos",
        "ACTA-1",
    )
    plain = effective_of(with_mandate(max_volatility=0.18), problem)
    assert plain.effective_hash != effective.effective_hash  # la autorización queda en el hash


def test_an_authorization_of_another_field_does_not_cover_the_relaxation(problem):  # type: ignore[no-untyped-def]
    config = with_mandate(
        max_volatility=0.18,
        portfolios=(_level("P1", max_volatility=0.25, auth=("max_replacements",)),),
    )
    with pytest.raises(ConfigError, match="MANDATE_RELAXATION_NOT_AUTHORIZED"):
        effective_of(config, problem)


def test_authorizations_require_responsible_reason_and_reference() -> None:
    for blank in ("", "  "):
        with pytest.raises(ConfigError):
            RelaxationAuthorization("max_volatility", blank, "motivo", "ref")
        with pytest.raises(ConfigError):
            RelaxationAuthorization("max_volatility", "alguien", blank, "ref")
        with pytest.raises(ConfigError):
            RelaxationAuthorization("max_volatility", "alguien", "motivo", blank)
    with pytest.raises(ConfigError, match="desconocido"):
        RelaxationAuthorization("campo_inexistente", "a", "b", "c")


def test_the_cardinality_policy_cannot_be_relaxed_by_an_override_without_authorization(problem):  # type: ignore[no-untyped-def]
    config = with_mandate(
        portfolios=(
            _level("P1", cardinality_policy=CardinalityPolicy.DECREASE, max_size_decrease=2),
        )
    )
    with pytest.raises(ConfigError, match="MANDATE_RELAXATION_NOT_AUTHORIZED"):
        effective_of(config, problem)
    authorized = with_mandate(
        portfolios=(
            _level(
                "P1",
                cardinality_policy=CardinalityPolicy.DECREASE,
                max_size_decrease=2,
                auth=("cardinality_policy", "max_size_decrease"),
            ),
        )
    )
    # max_size_decrease no existía en el nivel global: definirlo por primera vez es endurecer
    assert effective_of(authorized, problem).allowed_sizes == (HELD - 2, HELD - 1, HELD)


def test_tolerances_and_definitions_are_global_only() -> None:
    for field in ("weight_tolerance", "volatility_tolerance", "hhi_tolerance"):
        with pytest.raises(ConfigError, match="solo pueden definirse en el nivel global"):
            _level("P1", **{field: 1e-9})


def test_portfolio_spec_fields_are_part_of_the_third_level(problem):  # type: ignore[no-untyped-def]
    spec = spec_with(volatility_limit=0.10, target_portfolio_size=None)
    config = with_mandate(max_volatility=0.18)
    effective = effective_of(config, dataclasses.replace(problem, spec=spec))
    assert effective.max_volatility == 0.10
    assert effective.provenance_of("max_volatility") == "PORTFOLIO_SPEC:volatility_limit"
    loose = spec_with(volatility_limit=0.30)
    with pytest.raises(ConfigError, match="MANDATE_RELAXATION_NOT_AUTHORIZED"):
        effective_of(config, dataclasses.replace(problem, spec=loose))
    authorized = with_mandate(
        max_volatility=0.18, portfolios=(_level("P1", auth=("max_volatility",)),)
    )
    assert effective_of(authorized, dataclasses.replace(problem, spec=loose)).max_volatility == 0.30


def test_a_weight_override_that_widens_the_mandatory_cap_needs_authorization(problem):  # type: ignore[no-untyped-def]
    spec = spec_with(weight_bound_overrides={"A000": WeightBounds(None, 0.35)})
    with_override = dataclasses.replace(problem, spec=spec)
    config = with_mandate(max_active_weight=0.20)
    with pytest.raises(ConfigError, match="MANDATE_RELAXATION_NOT_AUTHORIZED"):
        effective_of(config, with_override)
    authorized = with_mandate(
        max_active_weight=0.20, portfolios=(_level("P1", auth=("max_active_weight",)),)
    )
    effective = effective_of(authorized, with_override)
    (exception,) = effective.asset_exceptions
    assert (exception.asset_id, exception.max_weight) == ("A000", 0.35)
    tighter = dataclasses.replace(
        problem, spec=spec_with(weight_bound_overrides={"A000": WeightBounds(None, 0.15)})
    )
    assert effective_of(config, tighter).asset_exceptions == ()  # endurecer no es una excepción


def test_existing_engine_fields_are_integrated_as_the_global_level(problem):  # type: ignore[no-untyped-def]
    base = base_config(
        candidates={"max_new_assets": 3, "max_swaps": 2},
        constraints={"global_max_weight": 0.25},
        frontier={"min_holding_weight": 0.03},
    )
    config = dataclasses.replace(
        base,
        hard_constraints=HardConstraintsConfig(
            MandateSettings(max_added_assets=5, max_active_weight=0.30, min_active_weight=0.01)
        ),
    )
    effective = effective_of(config, problem)
    assert effective.max_added_assets == 3  # el más estricto entre [candidates] y el mandato
    assert effective.max_swaps == 2
    assert effective.max_active_weight == 0.25
    assert effective.min_active_weight == 0.03
    assert "ENGINE_CONFIG" in effective.provenance_of("max_added_assets")


def test_a_positive_per_position_floor_is_mandatory(problem):  # type: ignore[no-untyped-def]
    config = dataclasses.replace(
        base_config(), hard_constraints=HardConstraintsConfig(MandateSettings(max_volatility=0.2))
    )
    with pytest.raises(ConfigError, match="peso mínimo estrictamente positivo"):
        effective_of(config, problem)
    clash = with_mandate(position_weight_threshold=5e-7, min_active_weight=5e-7)
    with pytest.raises(ConfigError, match="position_weight_threshold"):
        effective_of(clash, problem)


def test_min_volatility_requires_an_explicit_search_strategy(problem):  # type: ignore[no-untyped-def]
    with pytest.raises(ConfigError, match="no convexo"):
        effective_of(with_mandate(min_volatility=0.05), problem)
    assert effective_of(
        with_mandate(min_volatility=0.05, **BAND_PARAMS), problem
    ).has_volatility_band


def test_a_minimum_return_requires_an_explicit_treatment(problem):  # type: ignore[no-untyped-def]
    with pytest.raises(ConfigError, match="expected_return_treatment"):
        effective_of(with_mandate(preserve_original_expected_return=True), problem)


def test_effective_tolerances_default_to_the_solver_tolerances_and_respect_the_ceiling(problem):  # type: ignore[no-untyped-def]
    effective = effective_of(with_mandate(), problem)
    solver = base_config().solver
    assert effective.weight_tolerance == solver.bound_tolerance
    assert effective.budget_tolerance == solver.budget_tolerance
    assert effective.volatility_tolerance == solver.constraint_tolerance
    assert effective.position_weight_threshold == base_config().frontier.zero_weight_tolerance
    with pytest.raises(ConfigError):
        mandate_settings(volatility_tolerance=1e-3)
    loose_solver = base_config(solver={"constraint_tolerance": 1e-3})
    config = dataclasses.replace(
        loose_solver, hard_constraints=HardConstraintsConfig(mandate_settings())
    )
    with pytest.raises(ConfigError, match="Tolerancia"):
        effective_of(config, problem)


def test_effective_parameters_and_hash_are_deterministic_and_sensitive(problem):  # type: ignore[no-untyped-def]
    config = with_mandate(max_volatility=0.18, max_replacements=3)
    first, second = effective_of(config, problem), effective_of(config, problem)
    assert first.effective_hash == second.effective_hash
    assert first.to_payload() == second.to_payload()
    assert first.engine_config_hash == config_hash(config)
    changed = effective_of(with_mandate(max_volatility=0.18, max_replacements=2), problem)
    assert changed.effective_hash != first.effective_hash
    assert changed.engine_config_hash != first.engine_config_hash  # ConfigHash incluye el mandato
    other = dataclasses.replace(config, random_seed=config.random_seed + 1)
    assert effective_of(other, problem).effective_hash != first.effective_hash


def test_the_derived_engine_config_aligns_b1_b4_fields_and_is_idempotent(problem):  # type: ignore[no-untyped-def]
    config = with_mandate(
        max_active_weight=0.25, max_added_assets=4, max_replacements=2, min_active_weight=0.04
    )
    effective = effective_of(config, problem)
    derived = derive_engine_config(config, effective)
    assert derived.frontier.min_holding_weight == 0.04
    assert derived.constraints.global_max_weight == 0.25
    assert derived.candidates.max_new_assets == 4
    again = resolve_hard_constraints(
        derived,
        problem.portfolio_id,
        problem.spec,
        dict(zip(problem.state.asset_ids, problem.state.weights.tolist(), strict=True)),
    )
    assert again.to_payload()["max_added_assets"] == effective.to_payload()["max_added_assets"]
    assert derive_engine_config(derived, again).frontier == derived.frontier
    # el motor sin mandato no cambia: ConfigHash idéntico al de siempre
    assert config_hash(base_config()) == config_hash(dataclasses.replace(base_config()))


def test_unknown_profiles_and_duplicated_levels_are_configuration_errors() -> None:
    with pytest.raises(ConfigError, match="perfil desconocido"):
        HardConstraintsConfig(mandate_settings(), (), (_level("P1", profile="X"),))
    with pytest.raises(ConfigError, match="duplicados"):
        HardConstraintsConfig(mandate_settings(), (_level("A"), _level("A")))
    with pytest.raises(ConfigError, match="duplicadas"):
        MandateLevel(
            "P1",
            MandateSettings(),
            (_auth("max_volatility"), _auth("max_volatility")),
        )
