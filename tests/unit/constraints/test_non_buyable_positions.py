"""E-10, CON-013, CON-022, CAN-013, FEA-007: posición actual no comprable (H-1 de AUDIT_BLOCK_3).

Un activo mantenido que no admite nuevas compras (``EligibleFlag`` falso, ``LiquidityFlag`` falso o
desconocido con política conservadora, o fuera del ``InvestmentUniverse``) cumple
``0 <= w <= min(w_current, MaxWeight)``: puede mantenerse o reducirse, nunca incrementarse. Los
valores esperados son constantes del enunciado (``w_current = 0.10``), no salen de las funciones
bajo prueba.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.candidates import EligibilityFilter, UniverseSnapshot
from portfolio_engine.config import GroupLimit
from portfolio_engine.constraints import (
    ConstraintCompiler,
    PreFeasibilityChecker,
    build_constraint_set,
)
from portfolio_engine.exceptions import ConstraintCompilationError
from portfolio_engine.models.enums import (
    GroupDimension,
    RestrictedExistingPositionPolicy,
    UnknownFlagPolicy,
)
from portfolio_engine.validation import SolutionValidator, ValidationContext, ValidationTolerances
from tests.fixtures.candidates import ROLES_HELD, roles_problem, with_candidates
from tests.fixtures.non_buyable import (
    BLOCKERS,
    CURRENT,
    HELD_WEIGHT,
    MU,
    OPEN_BOUNDS,
    SIGMA,
    non_buyable_problem,
)
from tests.fixtures.problems import (
    base_config,
    make_problem,
    policy_config,
    restricted_universe,
    with_group_limits,
)

pytestmark = pytest.mark.unit

Policy = RestrictedExistingPositionPolicy


def _problem(case: str, config=None, **kwargs):  # type: ignore[no-untyped-def]
    return non_buyable_problem(case, config, **kwargs)


def _compile(config, problem):  # type: ignore[no-untyped-def]
    constraint_set = build_constraint_set(
        config.constraints,
        problem.spec,
        "P1",
        config.frontier.min_holding_weight,
        config.candidates.unknown_liquidity_policy,
    )
    composition = problem.composition_asset_ids or problem.state.asset_ids
    return ConstraintCompiler().compile(
        constraint_set, problem.universe, composition, problem.state
    )


def _validator(config):  # type: ignore[no-untyped-def]
    return SolutionValidator(ValidationTolerances.from_config(config.solver))


def _context(compiled):  # type: ignore[no-untyped-def]
    n = compiled.size
    return ValidationContext(np.full(n, 0.05), np.eye(n) * 0.01, None)


def _violated_checks(report) -> set[str]:  # type: ignore[no-untyped-def]
    return {violation.constraint_id.split(":")[0] for violation in report.violations}


# ------------------------------------------------------------------------------- compilador


@pytest.mark.parametrize("case", list(BLOCKERS))
def test_a_held_non_buyable_asset_is_capped_at_its_current_weight(case: str) -> None:
    config, problem = _problem(case)
    compiled = _compile(config, problem)
    assert compiled.lower[0] == 0.0  # puede reducirse hasta salir: no es una liquidación
    assert compiled.upper[0] == pytest.approx(HELD_WEIGHT)
    assert compiled.upper[1] == pytest.approx(1.0)  # el resto sigue con su MaxWeight
    (rule,) = compiled.non_buyable_rules
    assert rule.asset_id == "A000" and rule.is_held and rule.current_weight == HELD_WEIGHT
    assert rule.reasons == (BLOCKERS[case][2],)


def test_the_cap_never_exceeds_a_lower_max_weight() -> None:
    config = base_config()
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={
            "EligibleFlag": [False, True, True, True],
            "MaxWeight": [0.05, 1.0, 1.0, 1.0],
        },
    )
    compiled = _compile(config, problem)
    assert compiled.upper[0] == pytest.approx(0.05)  # min(0.10, 0.05)


def test_min_weight_does_not_force_a_non_buyable_position_to_grow() -> None:
    config = base_config()
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={
            "EligibleFlag": [False, True, True, True],
            "MinWeight": [0.20, 0.0, 0.0, 0.0],
            "MaxWeight": [1.0] * 4,
        },
    )
    compiled = _compile(config, problem)
    assert compiled.lower[0] == 0.0 and compiled.upper[0] == pytest.approx(HELD_WEIGHT)


@pytest.mark.parametrize("case", ["not_eligible", "not_liquid", "unknown_liquidity_excluded"])
def test_a_non_buyable_asset_that_is_not_held_cannot_enter(case: str) -> None:
    config, problem = _problem(case)
    problem = dataclasses.replace(
        problem,
        state=make_problem(MU, SIGMA, [0.0, 0.5, 0.5, 0.0], config).state,
        composition_asset_ids=("A000", "A001", "A002"),
    )
    compiled = _compile(config, problem)
    assert (compiled.lower[0], compiled.upper[0]) == (0.0, 0.0)
    (rule,) = compiled.non_buyable_rules
    assert not rule.is_held and rule.current_weight == 0.0


def test_unknown_liquidity_follows_the_explicit_policy() -> None:
    overrides = {**OPEN_BOUNDS, "LiquidityFlag": [None, True, True, True]}
    for policy, capped in (
        (UnknownFlagPolicy.EXCLUDE, True),
        (UnknownFlagPolicy.ALLOW, False),
    ):
        config = with_candidates(base_config(), unknown_liquidity_policy=policy)
        problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides=overrides)
        compiled = _compile(config, problem)
        assert bool(compiled.upper[0] == pytest.approx(HELD_WEIGHT)) is capped
        assert bool(compiled.non_buyable_rules) is capped
    config = with_candidates(base_config(), unknown_liquidity_policy=UnknownFlagPolicy.ERROR)
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides=overrides)
    with pytest.raises(ConstraintCompilationError, match="LiquidityFlag desconocido"):
        _compile(config, problem)


def test_the_unknown_liquidity_policy_changes_the_constraint_hash() -> None:
    hashes = set()
    for policy in (UnknownFlagPolicy.EXCLUDE, UnknownFlagPolicy.ALLOW):
        config = with_candidates(base_config(), unknown_liquidity_policy=policy)
        problem = make_problem(
            MU,
            SIGMA,
            CURRENT,
            config,
            universe_overrides={**OPEN_BOUNDS, "LiquidityFlag": [None] * 4},
        )
        hashes.add(_compile(config, problem).constraint_hash)
    assert len(hashes) == 2


# ------------------------------------------------------------------------------- validador


@pytest.mark.parametrize("case", list(BLOCKERS))
def test_the_validator_rejects_an_increase_and_accepts_holding_or_reducing(case: str) -> None:
    config, problem = _problem(case)
    compiled = _compile(config, problem)
    validator, context = _validator(config), _context(compiled)
    for weight_a000, valid in (
        (0.20, False),
        (0.11, False),
        (0.10, True),
        (0.05, True),
        (0.0, True),
    ):
        weights = np.array([weight_a000, 1.0 - weight_a000])
        report = validator.validate(weights, compiled, context)
        assert report.is_valid is valid, (case, weight_a000, report.violations)
        if not valid:
            assert "NON_BUYABLE_POLICY" in _violated_checks(report)
            assert "NON_BUYABLE_POLICY:A000:no_increase" in {
                violation.constraint_id for violation in report.violations
            }


def test_the_validator_does_not_rely_on_the_compiled_upper_bound() -> None:
    """Independencia: con la cota compilada abierta el validador rechaza igualmente."""
    config, problem = _problem("not_eligible")
    compiled = _compile(config, problem)
    tampered = dataclasses.replace(compiled, upper=np.array([1.0, 1.0]))
    report = _validator(config).validate(np.array([0.20, 0.80]), tampered, _context(tampered))
    assert "BOUNDS" not in _violated_checks(report)
    assert "NON_BUYABLE_POLICY" in _violated_checks(report)


def test_the_validator_rejects_a_purchase_of_an_asset_that_may_not_enter() -> None:
    config, problem = _problem("not_eligible")
    problem = dataclasses.replace(
        problem,
        state=make_problem(MU, SIGMA, [0.0, 0.5, 0.5, 0.0], config).state,
        composition_asset_ids=("A000", "A001", "A002"),
    )
    compiled = _compile(config, problem)
    report = _validator(config).validate(np.array([0.05, 0.5, 0.45]), compiled, _context(compiled))
    assert not report.is_valid
    assert "NON_BUYABLE_POLICY:A000:no_entry" in {v.constraint_id for v in report.violations}


# ------------------------------------------------------------------- precedencia de E-09


@pytest.mark.parametrize(
    ("policy", "bounds"),
    [
        (Policy.HOLD_OR_REDUCE, (0.0, 0.10)),
        (Policy.FREEZE_WEIGHT, (0.10, 0.10)),
        (Policy.FORCE_LIQUIDATE, (0.0, 0.0)),
    ],
)
def test_the_restricted_policy_keeps_precedence_over_the_non_buyable_rule(
    policy: RestrictedExistingPositionPolicy, bounds: tuple[float, float]
) -> None:
    config = policy_config(base_config(), policy)
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={
            **restricted_universe(4, [0]),
            "EligibleFlag": [False, True, True, True],
            "MaxWeight": [1.0] * 4,
        },
    )
    compiled = _compile(config, problem)
    assert (compiled.lower[0], compiled.upper[0]) == pytest.approx(bounds)
    assert compiled.non_buyable_rules == ()  # lo gobierna E-09, no E-10
    assert compiled.restricted_rules[0].policy is policy


# ------------------------------------------------------------ conflictos de restricciones


def test_caps_that_make_the_budget_impossible_are_infeasible_before_the_solver() -> None:
    config, problem = _problem("not_liquid")
    problem = dataclasses.replace(problem, composition_asset_ids=("A000",))
    report = PreFeasibilityChecker(config.solver.constraint_tolerance).check(
        _compile(config, problem)
    )
    codes = {cause.code for cause in report.causes}
    assert not report.feasible
    assert {"SUM_UPPER_BELOW_BUDGET", "NON_BUYABLE_CAPS_BELOW_BUDGET"} <= codes
    detail = next(c.detail for c in report.causes if c.code == "NON_BUYABLE_CAPS_BELOW_BUDGET")
    assert "A000" in detail and "NOT_LIQUID" in detail


def test_a_group_minimum_above_the_capped_members_is_infeasible() -> None:
    """Sector ``Tech`` = {A000, A002}; A000 vale a lo sumo 0,10 y A002 no está en la composición."""
    config = with_group_limits(
        base_config(), [GroupLimit(GroupDimension.SECTOR, "Tech", 0.50, None)]
    )
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={**OPEN_BOUNDS, "EligibleFlag": [False, True, True, True]},
    )
    report = PreFeasibilityChecker(config.solver.constraint_tolerance).check(
        _compile(config, problem)
    )
    assert not report.feasible
    assert "GROUP_UPPER_BELOW_MIN" in {cause.code for cause in report.causes}


def test_a_feasible_cap_produces_no_pre_solver_cause() -> None:
    config, problem = _problem("not_eligible")
    report = PreFeasibilityChecker(config.solver.constraint_tolerance).check(
        _compile(config, problem)
    )
    assert report.feasible and report.causes == ()


# ----------------------------------------------------- acuerdo con el EligibilityFilter


def test_the_compiler_and_the_eligibility_filter_agree_on_which_assets_are_non_buyable() -> None:
    """12 activos con todos los roles: reglas del compilador == no comprables no restringidos."""
    config = base_config()
    problem = roles_problem(config)
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    result = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    composition = tuple(
        a for a in problem.universe.asset_ids if a != "A009"
    )  # A009: flag restringido desconocido
    problem = dataclasses.replace(problem, composition_asset_ids=composition)
    compiled = _compile(config, problem)
    expected = {
        asset_id
        for position, asset_id in enumerate(snapshot.index.asset_ids)
        if asset_id in composition
        and not result.purchasable[position]
        and not (snapshot.restricted_known[position] and snapshot.restricted[position])
    }
    assert {rule.asset_id for rule in compiled.non_buyable_rules} == expected
    assert {"A001", "A003", "A005", "A006", "A008"} == expected  # oráculo escrito a mano
    held = {f"A{p:03d}" for p in ROLES_HELD}
    for rule in compiled.non_buyable_rules:
        position = compiled.asset_ids.index(rule.asset_id)
        assert compiled.upper[position] == (0.25 if rule.asset_id in held else 0.0)
