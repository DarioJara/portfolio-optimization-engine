"""VAL-001..005, VAL-007..009: el validador rechaza soluciones aunque el solver diga OPTIMAL."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.config import GroupLimit
from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    GroupDimension,
    RestrictedExistingPositionPolicy,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers import OSQPBackend, SolverRouter
from portfolio_engine.validation import (
    ReturnTarget,
    SolutionValidator,
    ValidationContext,
    ValidationTolerances,
)
from tests.fixtures.problems import (
    base_config,
    composition_inputs,
    cov_from_vol_corr,
    make_problem,
    policy_config,
    restricted_universe,
    spec_with,
    with_group_limits,
)

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = cov_from_vol_corr(
    [0.10, 0.15, 0.25, 0.20],
    [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
)
CURRENT = [0.4, 0.3, 0.2, 0.1]
GOOD = np.array([0.4, 0.3, 0.2, 0.1])
TOL = ValidationTolerances(budget=1e-7, bound=1e-7, constraint=1e-7, variance=1e-12)
COSTS = {"BuyCost": [100.0] * 4, "SellCost": [100.0] * 4}


def _validate(config, weights, *, spec=None, target=None, overrides=None, current=CURRENT):  # type: ignore[no-untyped-def]
    problem = make_problem(
        MU, SIGMA, current, config, spec=spec, universe_overrides={**COSTS, **(overrides or {})}
    )
    inputs = composition_inputs(problem, config)
    context = ValidationContext(inputs.mu, inputs.sigma, inputs.cost_model)
    return SolutionValidator(TOL).validate(weights, inputs.compiled, context, target)


def _codes(report) -> set[str]:  # type: ignore[no-untyped-def]
    return {violation.constraint_id.split(":")[0] for violation in report.violations}


def test_valid_solution_reports_every_check() -> None:
    """VAL-002/VAL-009: una solución válida tiene informe válido y lista las comprobaciones."""
    report = _validate(base_config(), GOOD)
    assert report.is_valid and report.violations == () and report.max_violation < 1e-12
    assert set(report.checks) >= {
        "FINITE",
        "BUDGET",
        "BOUNDS",
        "LONG_ONLY",
        "GROUPS",
        "TURNOVER",
        "RESTRICTED_POLICY",
        "VARIANCE",
    }


def test_basic_checks() -> None:
    """VAL-002: suma de pesos, límites inferior y superior, no negatividad y finitud."""
    config = base_config()
    assert _codes(_validate(config, np.array([0.4, 0.3, 0.2, 0.2]))) == {"BUDGET"}
    over = _validate(config, np.array([0.6, 0.2, 0.1, 0.1]))  # 0.6 > MaxWeight 0.5
    assert _codes(over) == {"BOUNDS"} and over.max_violation == pytest.approx(0.1)
    assert "LONG_ONLY" in _codes(_validate(config, np.array([0.5, 0.5, 0.2, -0.2])))
    for bad in (np.array([np.nan, 0.5, 0.3, 0.2]), np.array([np.inf, 0.0, 0.0, 0.0]), np.ones(3)):
        report = _validate(config, bad)
        assert not report.is_valid and _codes(report) == {"FINITE"}


def test_violations_within_tolerance_are_accepted_but_reported() -> None:
    report = _validate(base_config(), GOOD + np.array([1e-9, -1e-9, 0.0, 0.0]))
    assert report.is_valid and 0.0 < report.max_violation <= 1e-7


def test_groups() -> None:
    """VAL-005: sectores, países, clases de activo y divisas."""
    limits = [
        GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.5),
        GroupLimit(GroupDimension.CURRENCY, "EUR", 1.1, None),
    ]
    report = _validate(with_group_limits(base_config(), limits), GOOD)  # Tech = 0.6
    assert {v.constraint_id for v in report.violations} == {
        "GROUPS:SECTOR:Tech:max",
        "GROUPS:CURRENCY:EUR:min",
    }
    assert next(
        v for v in report.violations if v.constraint_id.endswith("Tech:max")
    ).violation == pytest.approx(0.1)


def test_turnover() -> None:
    """VAL-004: ``0.5·Σ|w − w0|`` frente a MaxTurnover, calculado desde los pesos."""
    spec = spec_with(max_turnover=0.15)
    inside = _validate(base_config(), np.array([0.5, 0.25, 0.15, 0.1]), spec=spec)  # turnover 0.10
    outside = _validate(base_config(), np.array([0.5, 0.4, 0.0, 0.1]), spec=spec)  # turnover 0.20
    assert inside.is_valid
    assert _codes(outside) == {"TURNOVER"} and outside.violations[0].violation == pytest.approx(
        0.05
    )


@pytest.mark.parametrize(
    ("policy", "weights", "violated"),
    [
        (RestrictedExistingPositionPolicy.HOLD_OR_REDUCE, [0.3, 0.4, 0.2, 0.1], True),
        (RestrictedExistingPositionPolicy.HOLD_OR_REDUCE, [0.5, 0.2, 0.2, 0.1], False),
        (RestrictedExistingPositionPolicy.FREEZE_WEIGHT, [0.4, 0.29, 0.21, 0.1], True),
        (RestrictedExistingPositionPolicy.FREEZE_WEIGHT, [0.4, 0.3, 0.1, 0.2], False),
        (RestrictedExistingPositionPolicy.FORCE_LIQUIDATE, [0.4, 0.1, 0.3, 0.2], True),
        (RestrictedExistingPositionPolicy.FORCE_LIQUIDATE, [0.5, 0.0, 0.3, 0.2], False),
    ],
)
def test_restricted_policy_is_checked_from_the_policy_not_from_bounds(
    policy: RestrictedExistingPositionPolicy, weights: list[float], violated: bool
) -> None:
    """VAL-007: la política se evalúa desde ``w_current`` y la política, no desde los límites
    compilados."""
    config = policy_config(base_config(), policy)
    report = _validate(config, np.array(weights), overrides=restricted_universe(4, [1]))
    assert ("RESTRICTED_POLICY" in _codes(report)) is violated


def test_return_target_gross_and_net() -> None:
    """Retorno objetivo bruto (``μ'w >= R``) y neto (``μ'w − TC(w) >= R``)."""
    config = base_config()
    gross = float(MU @ GOOD)
    assert _validate(config, GOOD, target=ReturnTarget(CostTreatment.GROSS, gross - 1e-9)).is_valid
    assert _codes(
        _validate(config, GOOD, target=ReturnTarget(CostTreatment.GROSS, gross + 0.01))
    ) == {"RETURN_TARGET"}
    moved = np.array([0.3, 0.3, 0.3, 0.1])  # compra 0.1 (100 bps) y vende 0.1 (100 bps)
    cost = 0.1 * 0.01 + 0.1 * 0.01
    net = float(MU @ moved) - cost
    assert _validate(config, moved, target=ReturnTarget(CostTreatment.NET, net - 1e-9)).is_valid
    assert not _validate(config, moved, target=ReturnTarget(CostTreatment.NET, net + 1e-4)).is_valid
    # un objetivo neto que solo se cumpliría ignorando los costes debe rechazarse
    ignoring_costs = float(MU @ moved) - 1e-4
    assert not _validate(
        config, moved, target=ReturnTarget(CostTreatment.NET, ignoring_costs)
    ).is_valid


def test_report_fields() -> None:
    """VAL-009: ``IsValidSolution``, ``MaximumConstraintViolation`` y lista de violaciones."""
    report = _validate(base_config(), np.array([0.6, 0.3, 0.2, 0.1]))
    assert (report.is_valid, len(report.violations)) == (False, 2)
    assert report.max_violation == pytest.approx(0.2)
    assert all(v.violation > 0 for v in report.violations)


def test_negative_variance_is_flagged() -> None:
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides=COSTS)
    inputs = composition_inputs(problem, config)
    broken = ValidationContext(inputs.mu, -inputs.sigma, inputs.cost_model)
    report = SolutionValidator(TOL).validate(GOOD, inputs.compiled, broken)
    assert "VARIANCE" in _codes(report)


class _TamperedBackend(OSQPBackend):
    """OSQP real cuyo vector solución se corrompe tras resolver (el estado sigue siendo OPTIMAL)."""

    def solve(self) -> SolveResult:
        result = super().solve()
        assert result.x is not None
        corrupted = np.array(result.x)
        corrupted[0] += 0.3  # rompe presupuesto y límite superior
        return dataclasses.replace(result, x=corrupted)


def test_solver_optimal_but_invalid_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """VAL-001: un punto que el solver marca OPTIMAL pero viola el contrato se rechaza."""
    config = base_config()
    monkeypatch.setattr(
        SolverRouter, "route", lambda self, problem: _TamperedBackend(config.solver)
    )
    problem = make_problem(MU, SIGMA, CURRENT, config)
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert result.points and all(p.status is SolverStatus.OPTIMAL for p in result.points)
    assert not any(p.is_valid_solution for p in result.points)
    first = result.points[0]
    assert first.validation is not None and not first.validation.is_valid
    assert first.status_source is StatusSource.VALIDATOR
    assert {v.constraint_id.split(":")[0] for v in first.validation.violations} >= {
        "BUDGET",
        "BOUNDS",
    }
    assert not any(
        p.is_gross_efficient for p in result.points
    )  # inválidos fuera de Pareto (FRN-023)
