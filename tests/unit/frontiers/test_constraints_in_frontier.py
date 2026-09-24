"""CON-005, CON-013, CON-022, SOL-013, SOL-014, TC-007, FRN-023: restricciones, políticas y
fallos en la frontera."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.config import GroupLimit
from portfolio_engine.exceptions import ConstraintCompilationError, FrontierError
from portfolio_engine.models.enums import (
    CostTreatment,
    CrossCheckPolicy,
    FrontierMethod,
    GroupDimension,
    RestrictedExistingPositionPolicy,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    point_of,
    policy_config,
    restricted_universe,
    spec_with,
    weights_of,
    with_group_limits,
)

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = cov_from_vol_corr(
    [0.10, 0.15, 0.25, 0.20],
    [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
)
CURRENT = [0.4, 0.3, 0.2, 0.1]
POLICY = RestrictedExistingPositionPolicy
COSTS = {"BuyCost": [100.0] * 4, "SellCost": [150.0] * 4}


# --------------------------------------------------------------------------- MaxTurnover
def test_two_asset_max_turnover_matches_the_clipped_minimum_variance() -> None:
    """CON-005: con 2 activos ``|t − a| <= T``: el óptimo es el mínimo de varianza recortado al
    intervalo."""
    config = base_config()
    sigma = cov_from_vol_corr([0.20, 0.30], [[1.0, 0.2], [0.2, 1.0]])
    problem_free = make_problem(
        [0.05, 0.10], sigma, [0.9, 0.1], config, universe_overrides={"MaxWeight": [1.0, 1.0]}
    )
    unconstrained = weights_of(
        point_of(frontier_result(problem_free, config), StrategyID.MIN_VARIANCE)
    )[0]
    assert unconstrained == pytest.approx(
        0.7358490566, abs=1e-6
    )  # fórmula cerrada; lejos de la actual (0,9)
    problem = make_problem(
        [0.05, 0.10],
        sigma,
        [0.9, 0.1],
        config,
        universe_overrides={"MaxWeight": [1.0, 1.0]},
        spec=spec_with(max_turnover=0.05),
    )
    result = frontier_result(problem, config)
    minimum = point_of(result, StrategyID.MIN_VARIANCE)
    assert weights_of(minimum)[0] == pytest.approx(
        0.9 - 0.05, abs=1e-6
    )  # recortado al borde del intervalo
    maximum = point_of(result, StrategyID.MAX_RETURN)
    assert weights_of(maximum)[0] == pytest.approx(
        0.9 - 0.05, abs=1e-6
    )  # mayor retorno = más peso en el activo 2


@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_all_points_respect_max_turnover(treatment: CostTreatment) -> None:
    config = base_config()
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={"MaxWeight": [0.5] * 4, **COSTS},
        spec=spec_with(max_turnover=0.12),
    )
    for method in FrontierMethod:
        result = frontier_result(problem, config, treatment, method)
        assert all(p.is_valid_solution for p in result.points)
        for point in result.valid_points:
            assert point.metrics is not None and point.metrics.turnover is not None
            assert point.metrics.turnover <= 0.12 + 1e-7
            assert point.validation is not None and "TURNOVER" in point.validation.checks
        assert (
            max(p.metrics.turnover for p in result.valid_points if p.metrics and p.metrics.turnover)
            > 0.10
        )  # es activa


def test_zero_max_turnover_collapses_the_frontier_to_the_current_portfolio() -> None:
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, spec=spec_with(max_turnover=0.0))
    result = frontier_result(problem, config)
    for point in result.valid_points:
        assert weights_of(point) == pytest.approx(CURRENT, abs=1e-6)
        assert point.metrics is not None and point.metrics.turnover == pytest.approx(0.0, abs=1e-6)
    assert sum(p.is_duplicate for p in result.points) == len(result.points) - 1


def test_max_turnover_makes_the_gross_frontier_smaller() -> None:
    config = base_config()
    free = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4})
    limited = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={"MaxWeight": [0.5] * 4},
        spec=spec_with(max_turnover=0.1),
    )
    best_free = point_of(frontier_result(free, config), StrategyID.MAX_RETURN).metrics
    best_limited = point_of(frontier_result(limited, config), StrategyID.MAX_RETURN).metrics
    assert best_free and best_limited
    assert best_limited.expected_return_gross < best_free.expected_return_gross - 1e-3


# ------------------------------------------------------------ grupos y restringidos
def test_group_limits_hold_on_every_point() -> None:
    """CON-006..009 en la frontera: ``Tech <= 40 %`` y ``Energy >= 35 %`` para todos los puntos."""
    config = with_group_limits(
        base_config(),
        [
            GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.4),
            GroupLimit(GroupDimension.SECTOR, "Energy", 0.35, None),
        ],
    )
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4})
    result = frontier_result(problem, config)
    assert all(p.is_valid_solution for p in result.points)
    for point in result.valid_points:
        w = weights_of(point)
        assert (
            w[0] + w[2] <= 0.4 + 1e-7 and w[1] + w[3] >= 0.35 - 1e-7
        )  # A000/A002 Tech; A001/A003 Energy


@pytest.mark.parametrize(
    ("policy", "check"),
    [
        (POLICY.HOLD_OR_REDUCE, lambda w: w[1] <= 0.3 + 1e-7),
        (POLICY.FREEZE_WEIGHT, lambda w: abs(w[1] - 0.3) <= 1e-7),
        (POLICY.FORCE_LIQUIDATE, lambda w: abs(w[1]) <= 1e-7),
    ],
)
def test_restricted_policy_semantics_in_the_continuous_frontier(policy, check) -> None:  # type: ignore[no-untyped-def]
    """CON-022: una prueba por política sobre toda la frontera (bruta y neta)."""
    config = policy_config(base_config(), policy)
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides=restricted_universe(4, [1], MaxWeight=[0.5] * 4, **COSTS),
    )
    for treatment in (CostTreatment.GROSS, CostTreatment.NET):
        result = frontier_result(problem, config, treatment)
        assert result.pre_check_feasible and all(p.is_valid_solution for p in result.points)
        assert all(check(weights_of(p)) for p in result.points)
        assert result.asset_set == set(
            problem.state.asset_ids
        )  # sigue siendo variable de la composición
    if policy is POLICY.FORCE_LIQUIDATE:
        net = frontier_result(problem, config, CostTreatment.NET).points[0]
        assert net.metrics is not None and net.metrics.number_removed_assets == 1
        assert (
            net.metrics.transaction_cost_one_off is not None
            and net.metrics.transaction_cost_one_off >= 0.3 * 0.015
        )
    if policy is POLICY.HOLD_OR_REDUCE:  # nunca aumenta aunque su retorno sea atractivo
        assert min(weights_of(p)[1] for p in frontier_result(problem, config).points) < 0.3 - 1e-3


def test_policy_conflicts_are_infeasible_without_calling_the_solver() -> None:
    """E-09: FORCE_LIQUIDATE con MaxTurnover insuficiente y FREEZE con MaxWeight menor ⇒
    INFEASIBLE previo."""
    config = policy_config(base_config(), POLICY.FORCE_LIQUIDATE)
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides=restricted_universe(4, [1], MaxWeight=[0.5] * 4),
        spec=spec_with(max_turnover=0.1),
    )
    result = frontier_result(problem, config)
    assert not result.pre_check_feasible and any(
        "TURNOVER_FORCED_ABOVE_MAX" in c for c in result.infeasibility_causes
    )
    assert (
        result.points[0].status_source is StatusSource.PRE_SOLVER_CHECK
        and result.diagnostics.solve_count == 0
    )
    frozen = policy_config(base_config(), POLICY.FREEZE_WEIGHT)
    caps = make_problem(
        MU,
        SIGMA,
        CURRENT,
        frozen,
        universe_overrides=restricted_universe(4, [1], MaxWeight=[0.5, 0.25, 0.5, 0.5]),
    )
    assert not frontier_result(caps, frozen).pre_check_feasible


# ------------------------------------------------------------------------------ sin cartera actual
def test_no_current_portfolio_gross_frontier_and_explicit_errors() -> None:
    """TC-007: se puede optimizar una composición explícita en bruto, pero no NET/POST_COST ni
    MaxTurnover."""
    config = base_config()
    ids = ("A000", "A001", "A002", "A003")
    problem = make_problem(
        MU, SIGMA, None, config, universe_overrides={"MaxWeight": [0.5] * 4}, composition=ids
    )
    result = frontier_result(problem, config)
    assert (
        result.asset_ids == ids
        and not result.has_current_portfolio
        and result.current_metrics is None
    )
    for point in result.valid_points:
        assert point.metrics is not None and point.metrics.turnover is None  # NO 0,5 ni 1
        assert point.metrics.transaction_cost is None and point.metrics.expected_return_net is None
        assert point.is_net_efficient is None and point.is_gross_efficient is not None
    with pytest.raises(FrontierError, match="NET exige"):
        frontier_result(problem, config, CostTreatment.NET)
    with pytest.raises(FrontierError, match="POST_COST_GROSS exige"):
        frontier_result(problem, config, CostTreatment.POST_COST_GROSS)
    with pytest.raises(ConstraintCompilationError, match="sin cartera actual"):
        frontier_result(dataclasses.replace(problem, spec=spec_with(max_turnover=0.2)), config)
    with pytest.raises(FrontierError, match="composición debe indicarse"):
        frontier_result(dataclasses.replace(problem, composition_asset_ids=None), config)


# ------------------------------------------------------------------------------- fallos del solver
def test_iteration_limit_points_are_stored_invalid_with_their_own_status() -> None:
    """SOL-002/FRN-023: un límite de iteraciones no es inviabilidad; el punto se almacena
    inválido."""
    config = base_config(
        solver={"max_iterations": 1, "ambiguous_status_policy": CrossCheckPolicy.NONE}
    )
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4})
    result = frontier_result(problem, config)
    assert result.points and not any(p.is_valid_solution for p in result.points)
    assert {p.status for p in result.points} == {SolverStatus.MAX_ITERATIONS}
    assert all(p.weights is None and p.metrics is None for p in result.points)
    assert not any(p.is_gross_efficient for p in result.points)
    assert (
        result.notes and "NOT_SOLVED" in result.notes[0]
    )  # MinVariance no resuelta: se omite la malla


def test_cold_retry_rescues_points_and_is_recorded() -> None:
    config = base_config(solver={"max_iterations": 1, "retry_iteration_multiplier": 10_000})
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4})
    result = frontier_result(problem, config)
    assert all(p.is_valid_solution for p in result.points)
    assert result.diagnostics.cold_retry_count >= 1
    assert any(p.status_source is StatusSource.CROSS_CHECK for p in result.points)


def test_inaccurate_solutions_are_rejected_unless_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OPTIMAL_INACCURATE`` no se acepta como firme salvo ``accept_inaccurate_solutions``."""
    from portfolio_engine.optimizers import osqp_backend as backend_module

    real = backend_module.map_osqp_status
    monkeypatch.setattr(
        backend_module,
        "map_osqp_status",
        lambda native: (
            SolverStatus.OPTIMAL_INACCURATE
            if real(native) is SolverStatus.OPTIMAL
            else real(native)
        ),
    )
    problem_config = base_config(solver={"ambiguous_status_policy": CrossCheckPolicy.NONE})
    problem = make_problem(
        MU, SIGMA, CURRENT, problem_config, universe_overrides={"MaxWeight": [0.5] * 4}
    )
    rejected = frontier_result(problem, problem_config)
    assert rejected.points and {p.status for p in rejected.points} == {
        SolverStatus.OPTIMAL_INACCURATE
    }
    assert not any(p.is_valid_solution for p in rejected.points)
    accepting = base_config(
        solver={
            "ambiguous_status_policy": CrossCheckPolicy.NONE,
            "accept_inaccurate_solutions": True,
        }
    )
    accepted = frontier_result(problem, accepting)
    assert all(
        p.is_valid_solution and p.status is SolverStatus.OPTIMAL_INACCURATE for p in accepted.points
    )
