"""CON-001..003, 005..009, 013, 018, 020, 022: compilación de restricciones para una composición
fija."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.config import GroupLimit
from portfolio_engine.constraints import ConstraintCompiler, build_constraint_set
from portfolio_engine.exceptions import ConstraintCompilationError
from portfolio_engine.models.enums import GroupDimension, RestrictedExistingPositionPolicy
from portfolio_engine.models.portfolio import WeightBounds
from tests.fixtures.problems import (
    base_config,
    build_universe,
    make_problem,
    policy_config,
    restricted_universe,
    spec_with,
    with_group_limits,
)

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = np.diag([0.01, 0.02, 0.03, 0.04])
CURRENT = [0.4, 0.3, 0.2, 0.1]
POLICY = RestrictedExistingPositionPolicy


def _compile(config, problem, **kwargs):  # type: ignore[no-untyped-def]
    constraint_set = build_constraint_set(
        config.constraints, problem.spec, "P1", None, config.candidates.unknown_liquidity_policy
    )
    composition = problem.composition_asset_ids or problem.state.asset_ids
    return ConstraintCompiler().compile(
        constraint_set, problem.universe, composition, problem.state
    )


def test_budget_long_only_and_bounds_from_universe() -> None:
    """CON-001/002/003: presupuesto 1, límites del universo y no negatividad."""
    config = base_config()
    compiled = _compile(config, make_problem(MU, SIGMA, CURRENT, config))
    assert compiled.budget == 1.0 and compiled.long_only
    assert compiled.lower.tolist() == [0.0] * 4
    assert compiled.upper.tolist() == [0.5] * 4
    assert compiled.current_weights.tolist() == CURRENT
    assert compiled.max_turnover is None and compiled.group_matrix.shape == (0, 4)
    assert compiled.asset_ids == ("A000", "A001", "A002", "A003")


def test_bound_precedence_override_over_global_over_universe() -> None:
    """CON-020: override de cartera > configuración global > campo del universo (por extremo)."""
    config = base_config()
    config = dataclasses.replace(
        config,
        constraints=dataclasses.replace(
            config.constraints, global_min_weight=0.05, global_max_weight=0.4
        ),
    )
    spec = spec_with(weight_bound_overrides={"A001": WeightBounds(0.1, 0.3)})
    compiled = _compile(config, make_problem(MU, SIGMA, CURRENT, config, spec=spec))
    assert compiled.lower.tolist() == [0.05, 0.1, 0.05, 0.05]
    assert compiled.upper.tolist() == [0.4, 0.3, 0.4, 0.4]


def test_group_constraints_for_every_dimension() -> None:
    """CON-006..009: una fila indicadora por límite de grupo, con sus cotas."""
    limits = [
        GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.6),
        GroupLimit(GroupDimension.SECTOR, "Energy", 0.2, None),
        GroupLimit(GroupDimension.COUNTRY, "ES", 0.5, 1.0),
        GroupLimit(GroupDimension.ASSET_CLASS, "Equity", None, 1.0),
        GroupLimit(GroupDimension.CURRENCY, "EUR", 0.1, 0.9),
    ]
    config = with_group_limits(base_config(), limits)
    compiled = _compile(config, make_problem(MU, SIGMA, CURRENT, config))
    rows = dict(zip(compiled.group_labels, compiled.group_matrix.tolist(), strict=True))
    assert rows["SECTOR:Tech"] == [1.0, 0.0, 1.0, 0.0]
    assert rows["SECTOR:Energy"] == [0.0, 1.0, 0.0, 1.0]
    assert rows["COUNTRY:ES"] == [1.0] * 4
    lows = dict(zip(compiled.group_labels, compiled.group_min.tolist(), strict=True))
    highs = dict(zip(compiled.group_labels, compiled.group_max.tolist(), strict=True))
    assert lows["SECTOR:Tech"] == -np.inf and highs["SECTOR:Tech"] == 0.6
    assert lows["SECTOR:Energy"] == 0.2 and highs["SECTOR:Energy"] == np.inf
    assert (lows["CURRENCY:EUR"], highs["CURRENCY:EUR"]) == (0.1, 0.9)


def test_group_limit_needs_the_grouping_attribute() -> None:
    """DAT-028 en compilación: un activo sin el atributo de grupo impide compilar el límite."""
    config = base_config()
    problem = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides={"Sector": ["Tech", None, "Tech", "Energy"]}
    )
    limited = with_group_limits(config, [GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.5)])
    with pytest.raises(ConstraintCompilationError, match="A001"):
        _compile(limited, problem)


def test_max_turnover_precedence_and_requirement() -> None:
    """CON-005/CON-020: MaxTurnover de la cartera prevalece; sin cartera actual no se puede
    compilar."""
    config = base_config()
    config = dataclasses.replace(
        config, constraints=dataclasses.replace(config.constraints, global_max_turnover=0.4)
    )
    assert _compile(config, make_problem(MU, SIGMA, CURRENT, config)).max_turnover == 0.4
    spec = spec_with(max_turnover=0.25)
    assert (
        _compile(config, make_problem(MU, SIGMA, CURRENT, config, spec=spec)).max_turnover == 0.25
    )
    assert build_constraint_set(
        config.constraints, spec, "P1", None, config.candidates.unknown_liquidity_policy
    ).max_turnover_source.value == ("PORTFOLIO_OVERRIDE")
    empty = make_problem(MU, SIGMA, None, config, composition=("A000", "A001", "A002", "A003"))
    with pytest.raises(ConstraintCompilationError, match="sin cartera actual"):
        _compile(config, empty)


@pytest.mark.parametrize(
    ("policy", "lower", "upper"),
    [
        (POLICY.HOLD_OR_REDUCE, 0.0, 0.3),
        (POLICY.FREEZE_WEIGHT, 0.3, 0.3),
        (POLICY.FORCE_LIQUIDATE, 0.0, 0.0),
    ],
)
def test_restricted_existing_position_policies(
    policy: RestrictedExistingPositionPolicy, lower: float, upper: float
) -> None:
    """CON-022/E-09: traducción de cada política a límites efectivos del activo restringido."""
    config = policy_config(base_config(), policy)
    problem = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides=restricted_universe(4, [1])
    )
    compiled = _compile(config, problem)
    assert (compiled.lower[1], compiled.upper[1]) == (lower, upper)
    assert compiled.lower[[0, 2, 3]].tolist() == [0.0] * 3  # el resto no cambia
    assert [rule.asset_id for rule in compiled.restricted_rules] == ["A001"]
    assert compiled.restricted_rules[0].policy is policy


def test_hold_or_reduce_respects_a_lower_max_weight_and_overrides_min_weight() -> None:
    """HOLD_OR_REDUCE: ``0 <= w <= min(w_current, MaxWeight)`` y prevalece sobre MinWeight."""
    config = policy_config(base_config(), POLICY.HOLD_OR_REDUCE)
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides=restricted_universe(
            4, [1], MaxWeight=[0.5, 0.2, 0.5, 0.5], MinWeight=[0.0, 0.15, 0.0, 0.0]
        ),
    )
    compiled = _compile(config, problem)
    assert (compiled.lower[1], compiled.upper[1]) == (0.0, 0.2)


def test_new_restricted_asset_is_never_incorporated() -> None:
    """CON-013: un restringido de la composición que no está en la cartera queda fijo a 0."""
    config = policy_config(base_config(), POLICY.HOLD_OR_REDUCE)
    problem = make_problem(
        MU,
        SIGMA,
        [0.5, 0.5, 0.0, 0.0],
        config,
        universe_overrides=restricted_universe(4, [2]),
        composition=("A000", "A001", "A002"),
    )
    compiled = _compile(config, problem)
    assert (compiled.lower[2], compiled.upper[2]) == (0.0, 0.0)
    assert compiled.restricted_rules[0].policy is None and not compiled.restricted_rules[0].is_held


def test_min_holding_weight_is_a_lower_bound_except_for_policy_assets() -> None:
    """A-08: ``min_holding_weight`` exige tenencia positiva; la política de restringidos
    prevalece."""
    config = policy_config(base_config(), POLICY.HOLD_OR_REDUCE)
    problem = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides=restricted_universe(4, [1])
    )
    constraint_set = build_constraint_set(
        config.constraints, None, "P1", 0.02, config.candidates.unknown_liquidity_policy
    )
    compiled = ConstraintCompiler().compile(
        constraint_set, problem.universe, problem.state.asset_ids, problem.state
    )
    assert compiled.lower.tolist() == [0.02, 0.0, 0.02, 0.02]


def test_composition_must_be_sorted_unique_and_non_empty() -> None:
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config)
    constraint_set = build_constraint_set(
        config.constraints, None, "P1", None, config.candidates.unknown_liquidity_policy
    )
    compiler = ConstraintCompiler()
    universe = problem.universe
    with pytest.raises(ConstraintCompilationError, match="ordenada"):
        compiler.compile(constraint_set, universe, ("A001", "A000", "A002", "A003"), problem.state)
    with pytest.raises(ConstraintCompilationError, match="repetidos"):
        compiler.compile(
            constraint_set, universe, ("A000", "A000", "A001", "A002", "A003"), problem.state
        )
    with pytest.raises(ConstraintCompilationError, match="vacía"):
        compiler.compile(constraint_set, universe, (), problem.state)


def test_constraint_hash_is_deterministic_and_sensitive() -> None:
    """CON-018: ``ConstraintHash`` estable y distinto ante cualquier cambio de restricción."""
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config)
    base = _compile(config, problem).constraint_hash
    assert base == _compile(config, make_problem(MU, SIGMA, CURRENT, config)).constraint_hash
    variants = {
        "max_weight": make_problem(
            MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.6] * 4}
        ),
        "current": make_problem(MU, SIGMA, [0.4, 0.3, 0.25, 0.05], config),
    }
    hashes = {name: _compile(config, variant).constraint_hash for name, variant in variants.items()}
    limited = with_group_limits(config, [GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.5)])
    hashes["group"] = _compile(limited, problem).constraint_hash
    turnover = dataclasses.replace(
        config, constraints=dataclasses.replace(config.constraints, global_max_turnover=0.3)
    )
    hashes["turnover"] = _compile(turnover, problem).constraint_hash
    assert len({base, *hashes.values()}) == len(hashes) + 1


def test_unknown_restricted_status_of_a_new_asset_is_an_error() -> None:
    config = base_config()
    universe = build_universe(4, config, {"RestrictedAssetFlag": [False, False, None, False]})
    problem = make_problem(
        MU, SIGMA, [0.5, 0.5, 0.0, 0.0], config, composition=("A000", "A001", "A002")
    )
    constraint_set = build_constraint_set(
        config.constraints, None, "P1", None, config.candidates.unknown_liquidity_policy
    )
    with pytest.raises(ConstraintCompilationError, match="RestrictedAssetFlag"):
        ConstraintCompiler().compile(
            constraint_set, universe, ("A000", "A001", "A002"), problem.state
        )


def test_current_assets_outside_the_composition_are_recorded_as_exited() -> None:
    """Un activo actual que no está en la composición se liquida por completo (MASTER_SPEC §23)."""
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, composition=("A000", "A001"))
    compiled = _compile(config, problem)
    assert compiled.asset_ids == ("A000", "A001")
    assert compiled.current_weights.tolist() == [0.4, 0.3]
    assert [(p.asset_id, p.current_weight) for p in compiled.exited] == [
        ("A002", 0.2),
        ("A003", 0.1),
    ]
    assert compiled.exit_turnover == pytest.approx(0.5 * (0.2 + 0.1), abs=1e-15)
    full = _compile(config, make_problem(MU, SIGMA, CURRENT, config))
    assert full.exited == () and full.exit_turnover == 0.0
    assert compiled.constraint_hash != full.constraint_hash


def test_exited_restricted_positions_carry_their_policy() -> None:
    """E-09: la política efectiva se registra en cada restringido retirado (los no restringidos
    no tienen política)."""
    for policy in POLICY:
        config = policy_config(base_config(), policy)
        problem = make_problem(
            MU,
            SIGMA,
            CURRENT,
            config,
            universe_overrides=restricted_universe(4, [2]),
            composition=("A000", "A001"),
        )
        exited = {p.asset_id: p for p in _compile(config, problem).exited}
        assert exited["A002"].is_restricted and exited["A002"].policy is policy
        assert not exited["A003"].is_restricted and exited["A003"].policy is None


def test_exited_restricted_position_without_policy_is_rejected() -> None:
    base = base_config()
    config = dataclasses.replace(
        base,
        constraints=dataclasses.replace(base.constraints, restricted_existing_position_policy=None),
    )
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides=restricted_universe(4, [2]),
        composition=("A000", "A001"),
    )
    with pytest.raises(ConstraintCompilationError, match="RestrictedExistingPositionPolicy"):
        _compile(config, problem)
