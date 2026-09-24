"""FEA-001, FEA-003, FEA-004, FEA-007, SOL-013: factibilidad previa determinista (sin solver)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.config import GroupLimit
from portfolio_engine.constraints import (
    ConstraintCompiler,
    PreFeasibilityChecker,
    build_constraint_set,
    minimum_forced_turnover,
)
from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    GroupDimension,
    RestrictedExistingPositionPolicy,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.portfolio import WeightBounds
from portfolio_engine.optimizers.router import SolverRouter
from tests.fixtures.problems import (
    base_config,
    make_problem,
    policy_config,
    restricted_universe,
    spec_with,
    with_group_limits,
)
from tests.fixtures.reference import min_turnover_lp

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = np.diag([0.01, 0.02, 0.03, 0.04])
CURRENT = [0.4, 0.3, 0.2, 0.1]
TOLERANCE = 1e-9


def _causes(config, problem) -> set[str]:  # type: ignore[no-untyped-def]
    constraint_set = build_constraint_set(
        config.constraints, problem.spec, "P1", None, config.candidates.unknown_liquidity_policy
    )
    compiled = ConstraintCompiler().compile(
        constraint_set, problem.universe, problem.state.asset_ids, problem.state
    )
    return {cause.code for cause in PreFeasibilityChecker(TOLERANCE).check(compiled).causes}


def test_feasible_problem_has_no_causes() -> None:
    config = base_config()
    assert _causes(config, make_problem(MU, SIGMA, CURRENT, config)) == set()


def test_bounds_rules() -> None:
    """FEA-001: ``Σ MaxWeight >= 1`` y ``Σ MinWeight <= 1`` sobre la composición."""
    config = base_config()
    low_caps = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.2] * 4})
    assert "SUM_UPPER_BELOW_BUDGET" in _causes(config, low_caps)
    high_floors = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides={"MinWeight": [0.3] * 4}
    )
    assert "SUM_LOWER_EXCEEDS_BUDGET" in _causes(config, high_floors)
    exactly_one = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.25] * 4}
    )
    assert _causes(config, exactly_one) == set()


def test_group_rules() -> None:
    """FEA-003: incompatibilidades entre grupos y límites de activo."""
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config)
    cases = {
        "GROUP_UPPER_BELOW_MIN": [GroupLimit(GroupDimension.SECTOR, "Tech", 1.2, None)],
        "GROUP_MINIMUMS_EXCEED_BUDGET": [
            GroupLimit(GroupDimension.SECTOR, "Tech", 0.7, None),
            GroupLimit(GroupDimension.SECTOR, "Energy", 0.7, None),
        ],
    }
    for code, limits in cases.items():
        assert code in _causes(with_group_limits(config, limits), problem)
    floors = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MinWeight": [0.15] * 4})
    tight = with_group_limits(config, [GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.2)])
    assert "GROUP_LOWER_EXCEEDS_MAX" in _causes(tight, floors)


def test_freeze_weight_conflict_is_reported() -> None:
    """E-09: FREEZE_WEIGHT con ``w_current`` por encima de MaxWeight no se relaja: INFEASIBLE."""
    config = policy_config(base_config(), RestrictedExistingPositionPolicy.FREEZE_WEIGHT)
    spec = spec_with(weight_bound_overrides={"A001": WeightBounds(None, 0.2)})
    problem = make_problem(
        MU, SIGMA, CURRENT, config, spec=spec, universe_overrides=restricted_universe(4, [1])
    )
    assert "FREEZE_WEIGHT_CONFLICT" in _causes(config, problem)


def test_turnover_rules() -> None:
    """FEA-004: turnover mínimo forzado por los límites frente a MaxTurnover."""
    config = policy_config(base_config(), RestrictedExistingPositionPolicy.FORCE_LIQUIDATE)
    problem = make_problem(
        MU, SIGMA, CURRENT, config, universe_overrides=restricted_universe(4, [1])
    )
    loose = dataclasses.replace(
        config, constraints=dataclasses.replace(config.constraints, global_max_turnover=0.5)
    )
    tight = dataclasses.replace(
        config, constraints=dataclasses.replace(config.constraints, global_max_turnover=0.2)
    )
    assert "TURNOVER_FORCED_ABOVE_MAX" not in _causes(loose, problem)
    assert "TURNOVER_FORCED_ABOVE_MAX" in _causes(tight, problem)


def test_forced_turnover_matches_a_linear_program() -> None:
    """La fórmula del turnover mínimo coincide con el óptimo de un LP resuelto con HiGHS."""
    config = base_config()
    checked = 0
    for seed in range(40):
        rng = np.random.default_rng(seed)
        raw = rng.random(5)
        current = (raw / raw.sum()).tolist()
        lower = rng.uniform(0.0, 0.25, 5)
        upper = lower + rng.uniform(0.2, 0.6, 5)
        if lower.sum() > 1.0 or upper.sum() < 1.0:
            continue
        problem = make_problem(
            np.linspace(0.05, 0.1, 5),
            np.diag(np.linspace(0.01, 0.05, 5)),
            current,
            config,
            universe_overrides={"MinWeight": lower.tolist(), "MaxWeight": upper.tolist()},
        )
        constraint_set = build_constraint_set(
            config.constraints, None, "P1", None, config.candidates.unknown_liquidity_policy
        )
        compiled = ConstraintCompiler().compile(
            constraint_set, problem.universe, problem.state.asset_ids, problem.state
        )
        expected = min_turnover_lp(np.array(current), lower, upper)
        assert minimum_forced_turnover(compiled) == pytest.approx(expected, abs=1e-9)
        checked += 1
    assert checked >= 15


def test_solver_is_not_called_when_pre_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEA-007/SOL-013: inviabilidad previa ⇒ ``INFEASIBLE`` con ``PRE_SOLVER_CHECK`` y 0
    llamadas."""
    calls: list[str] = []

    def spy(self: SolverRouter, problem: object) -> object:
        calls.append("route")
        raise AssertionError("El solver no debe invocarse.")

    monkeypatch.setattr(SolverRouter, "route", spy)
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.2] * 4})
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert calls == []
    assert not result.pre_check_feasible
    assert any("SUM_UPPER_BELOW_BUDGET" in cause for cause in result.infeasibility_causes)
    (point,) = result.points
    assert point.status is SolverStatus.INFEASIBLE
    assert point.status_source is StatusSource.PRE_SOLVER_CHECK
    assert not point.is_valid_solution and point.weights is None and point.solve is None
    assert result.diagnostics.solve_count == 0 and result.diagnostics.solver_name == "NONE"


def test_forced_turnover_accounts_for_a_current_portfolio_that_does_not_sum_to_one() -> None:
    """Con ``Σw0 = 1 − r`` el turnover mínimo es ``max(F+, F− + r) − r/2``."""
    config = base_config()
    checked = 0
    for seed in range(30):
        rng = np.random.default_rng(100 + seed)
        raw = rng.random(4)
        current = raw / raw.sum() * (1.0 - 5e-4)  # residuo r = 5e-4
        lower = rng.uniform(0.0, 0.2, 4)
        upper = lower + rng.uniform(0.2, 0.6, 4)
        if lower.sum() > 1.0 or upper.sum() < 1.0:
            continue
        problem = make_problem(
            np.linspace(0.05, 0.1, 4),
            np.diag(np.linspace(0.01, 0.04, 4)),
            current.tolist(),
            config,
            universe_overrides={"MinWeight": lower.tolist(), "MaxWeight": upper.tolist()},
        )
        constraint_set = build_constraint_set(
            config.constraints, None, "P1", None, config.candidates.unknown_liquidity_policy
        )
        compiled = ConstraintCompiler().compile(
            constraint_set, problem.universe, problem.state.asset_ids, problem.state
        )
        expected = min_turnover_lp(current, lower, upper)
        assert minimum_forced_turnover(compiled) == pytest.approx(expected, abs=1e-9)
        checked += 1
    assert checked >= 10
