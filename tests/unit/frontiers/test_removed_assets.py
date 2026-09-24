"""TC-011 (parte optimizada), CON-005, CON-013, CON-022, FEA-004, VAL-004: activos actuales que no
están en la composición (liquidación completa) dentro del optimizador continuo, sin CandidateEngine.

Escenario: cartera actual ``A000, A001, C=A002, D=A003`` (0.3, 0.3, 0.2, 0.2) y composición fija
``A000, A001, E=A004, F=A005``. ``C`` y ``D`` se venden por completo: aportan al coste único
``K_E = 0.2·sell_C + 0.2·sell_D`` y al turnover ``0.5·(0.2 + 0.2) = 0.2``. Todos los valores
esperados se calculan aquí con NumPy/SciPy desde las definiciones (§23-25), no con el motor.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.optimize import linprog, minimize

from portfolio_engine.constraints import ConstraintCompiler, build_constraint_set
from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    RestrictedExistingPositionPolicy,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.validation import (
    ReturnTarget,
    SolutionValidator,
    ValidationContext,
    ValidationTolerances,
)
from tests.fixtures.problems import (
    base_config,
    compiled_for,
    composition_inputs,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    point_of,
    policy_config,
    restricted_universe,
    spec_with,
    weights_of,
)

pytestmark = pytest.mark.unit

GROSS, NET, POST = CostTreatment.GROSS, CostTreatment.NET, CostTreatment.POST_COST_GROSS
Policy = RestrictedExistingPositionPolicy

MU = np.array([0.06, 0.05, 0.04, 0.03, 0.10, 0.08])
SIGMA = cov_from_vol_corr(
    [0.15, 0.12, 0.10, 0.10, 0.25, 0.20],
    np.full((6, 6), 0.3) + 0.7 * np.eye(6),
)
CURRENT = [0.3, 0.3, 0.2, 0.2, 0.0, 0.0]
COMPOSITION = ("A000", "A001", "A004", "A005")
KEPT = np.array([0, 1, 4, 5])
BUY_BPS = [20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
SELL_BPS = [100.0, 120.0, 140.0, 160.0, 180.0, 200.0]
BUY, SELL = np.array(BUY_BPS) / 1e4, np.array(SELL_BPS) / 1e4
#: Coste único de liquidar C y D por completo (constante, independiente de la optimización).
EXIT_COST_ONE_OFF = 0.2 * SELL[2] + 0.2 * SELL[3]
EXIT_TURNOVER = 0.5 * (0.2 + 0.2)
OVERRIDES = {"BuyCost": BUY_BPS, "SellCost": SELL_BPS, "MaxWeight": [0.6] * 6}


def _problem(config, **kwargs):  # type: ignore[no-untyped-def]
    overrides = {**OVERRIDES, **kwargs.pop("universe_overrides", {})}
    return make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides=overrides,
        composition=kwargs.pop("composition", COMPOSITION),
        **kwargs,
    )


def _union(weights: np.ndarray) -> np.ndarray:
    """Pesos de la composición llevados a los 6 activos del universo (0 fuera)."""
    full = np.zeros(6)
    full[KEPT] = weights
    return full


def _cost_one_off(weights: np.ndarray) -> float:
    delta = _union(weights) - np.array(CURRENT)
    return float(BUY @ np.maximum(delta, 0.0) + SELL @ np.maximum(-delta, 0.0))


def _turnover(weights: np.ndarray) -> float:
    return float(0.5 * np.abs(_union(weights) - np.array(CURRENT)).sum())


def _net_return(weights: np.ndarray, horizon: float) -> float:
    return float(MU[KEPT] @ weights - _cost_one_off(weights) / horizon)


def _reference_lp(
    horizon: float, *, max_turnover: float | None = None, net: bool = True
) -> tuple[np.ndarray, float]:
    """``max μᵀw − [TC(w) incl. K_E]`` con ``w − b + s = w0``, ``1ᵀw = 1``, ``0 <= w <= 0.6`` y
    ``0.5·Σ(b + s) <= T − 0.2`` (HiGHS, formulación escrita aquí)."""
    n = 4
    w0, mu = np.array(CURRENT)[KEPT], MU[KEPT]
    cost = np.concatenate([-mu, BUY[KEPT] / horizon, SELL[KEPT] / horizon]) if net else None
    if cost is None:
        cost = np.concatenate([-mu, np.zeros(n), np.zeros(n)])
    ident = np.eye(n)
    a_eq = np.vstack(
        [
            np.hstack([np.ones((1, n)), np.zeros((1, n)), np.zeros((1, n))]),
            np.hstack([ident, -ident, ident]),
        ]
    )
    b_eq = np.concatenate([[1.0], w0])
    a_ub = b_ub = None
    if max_turnover is not None:
        a_ub = np.concatenate([np.zeros(n), np.full(n, 0.5), np.full(n, 0.5)]).reshape(1, -1)
        b_ub = np.array([max_turnover - EXIT_TURNOVER])
    bounds = [(0.0, 0.6)] * n + [(0.0, None)] * (2 * n)
    result = linprog(
        cost, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs"
    )
    assert result.success
    weights = np.asarray(result.x[:n])
    value = float(mu @ weights - (_cost_one_off(weights) / horizon if net else 0.0))
    return weights, value


def test_metrics_include_the_full_liquidation_of_removed_assets() -> None:
    """Coste de venta completo de C y D, turnover con la parte constante y retorno neto, para
    cada punto de cada tratamiento, frente al cálculo independiente sobre la unión."""
    config = base_config()
    problem = _problem(config)
    horizon = config.optimization_horizon_years
    for treatment in (GROSS, NET, POST):
        result = frontier_result(problem, config, treatment)
        assert result.notes in ((), ("POST_COST_GROSS_EVALUATED_FROM_GROSS_WEIGHTS",))
        assert result.asset_set == set(COMPOSITION) and len(result.valid_points) > 2
        for point in result.valid_points:
            weights = weights_of(point)
            assert weights.shape == (4,) and weights.sum() == pytest.approx(1.0, abs=1e-7)
            metrics = point.metrics
            assert metrics is not None and metrics.transaction_cost_one_off is not None
            assert metrics.transaction_cost_one_off == pytest.approx(
                _cost_one_off(weights), abs=1e-9
            )
            assert metrics.transaction_cost_one_off >= EXIT_COST_ONE_OFF - 1e-12
            assert metrics.turnover == pytest.approx(_turnover(weights), abs=1e-9)
            assert metrics.turnover is not None and metrics.turnover >= EXIT_TURNOVER - 1e-12
            assert metrics.expected_return_net == pytest.approx(
                _net_return(weights, horizon), abs=1e-9
            )
            full, held = _union(weights), np.array(CURRENT) > 0.0
            removed = int(((full <= config.frontier.zero_weight_tolerance) & held).sum())
            assert metrics.number_removed_assets == removed >= 2  # C y D siempre cuentan


def test_current_portfolio_metrics_cover_the_removed_assets() -> None:
    """La cartera actual (A, B, C, D) se evalúa completa: sin cambios, turnover y coste nulos."""
    config = base_config()
    result = frontier_result(_problem(config), config, NET)
    current = result.current_metrics
    assert current is not None
    assert current.expected_return_gross == pytest.approx(MU[:4] @ np.array(CURRENT)[:4])
    w0 = np.array(CURRENT)[:4]
    assert current.variance == pytest.approx(w0 @ SIGMA[:4, :4] @ w0)
    assert current.turnover == pytest.approx(0.0, abs=1e-15)
    assert current.transaction_cost_one_off == pytest.approx(0.0, abs=1e-15)
    assert current.number_removed_assets == 0


def test_maximum_return_net_matches_the_independent_lp_with_liquidation() -> None:
    config = base_config()
    horizon = config.optimization_horizon_years
    result = frontier_result(_problem(config), config, NET)
    best = point_of(result, StrategyID.MAX_RETURN)
    reference_weights, reference_value = _reference_lp(horizon)
    assert best.metrics is not None and best.metrics.expected_return_net is not None
    assert best.metrics.expected_return_net == pytest.approx(reference_value, abs=1e-8)
    assert weights_of(best) == pytest.approx(reference_weights, abs=1e-6)
    # la constante K_E/H está dentro del retorno neto publicado (no se omite ni se duplica)
    without_exit = (
        float(MU[KEPT] @ reference_weights)
        - float(
            BUY[KEPT] @ np.maximum(reference_weights - np.array(CURRENT)[KEPT], 0.0)
            + SELL[KEPT] @ np.maximum(np.array(CURRENT)[KEPT] - reference_weights, 0.0)
        )
        / horizon
    )
    assert reference_value == pytest.approx(without_exit - EXIT_COST_ONE_OFF / horizon, abs=1e-12)


def test_net_target_return_accounts_for_the_liquidation_cost() -> None:
    """Objetivo de retorno neto: ``μᵀw − TC(w) − K_E/H >= R``. Si ``K_E`` se omitiera de la fila de
    retorno, el retorno neto real (independiente) quedaría ``K_E/H`` por debajo del objetivo."""
    config = base_config()
    horizon = config.optimization_horizon_years
    problem = _problem(config)
    _, best_net = _reference_lp(horizon)
    target = best_net - 0.01
    session = ContinuousFrontierEngine(config).open_session(
        problem, NET, FrontierMethod.TARGET_RETURN_GRID
    )
    point = session.solve_target(target, strategy=StrategyID.FRONTIER_POINT)
    assert point.is_valid_solution and point.weights is not None
    achieved = _net_return(point.weights, horizon)
    assert achieved >= target - 1e-7
    assert achieved == pytest.approx(target, abs=1e-6)  # el objetivo es activo
    assert EXIT_COST_ONE_OFF / horizon > 1e-3  # el offset es numéricamente relevante
    # óptimo independiente (SLSQP sobre la formulación elevada escrita aquí)
    w0 = np.array(CURRENT)[KEPT]
    sigma = SIGMA[np.ix_(KEPT, KEPT)]
    mu = MU[KEPT]
    constraints = [
        {"type": "eq", "fun": lambda x: x[:4].sum() - 1.0},
        {"type": "eq", "fun": lambda x: x[:4] - x[4:8] + x[8:] - w0},
        {
            "type": "ineq",
            "fun": lambda x: (
                mu @ x[:4]
                - (BUY[KEPT] @ x[4:8] + SELL[KEPT] @ x[8:]) / horizon
                - EXIT_COST_ONE_OFF / horizon
                - target
            ),
        },
    ]
    start = np.concatenate([w0 / w0.sum(), np.zeros(8)])
    solved = minimize(
        lambda x: x[:4] @ sigma @ x[:4],
        start,
        bounds=[(0.0, 0.6)] * 4 + [(0.0, None)] * 8,
        constraints=constraints,
        method="SLSQP",
        options={"ftol": 1e-14, "maxiter": 1000},
    )
    assert solved.success
    assert point.weights == pytest.approx(solved.x[:4], abs=1e-4)
    assert point.weights @ sigma @ point.weights == pytest.approx(solved.fun, abs=1e-9)


def test_max_turnover_counts_the_liquidations_in_the_optimizer_and_the_validator() -> None:
    """``T = 0.45``: el turnover de la composición debe ser ``<= 0.45 − 0.2``. Frente al mismo
    problema *ignorando* los retirados el máximo retorno es estrictamente mayor."""
    config = base_config()
    spec = spec_with(max_turnover=0.45)
    problem = _problem(config, spec=spec)
    for treatment in (GROSS, NET):
        result = frontier_result(problem, config, treatment)
        assert result.pre_check_feasible and len(result.valid_points) > 2
        assert all(_turnover(weights_of(p)) <= 0.45 + 1e-7 for p in result.valid_points)
        assert all(p.validation is not None and p.validation.is_valid for p in result.valid_points)
    gross_best = point_of(frontier_result(problem, config, GROSS), StrategyID.MAX_RETURN)
    ref_weights, ref_value = _reference_lp(
        config.optimization_horizon_years, max_turnover=0.45, net=False
    )
    assert weights_of(gross_best) == pytest.approx(ref_weights, abs=1e-6)
    assert _turnover(weights_of(gross_best)) == pytest.approx(0.45, abs=1e-7)  # cota activa
    naive = linprog(  # el mismo problema con el turnover de C y D olvidado (T = 0.45 sobre A,B,E,F)
        np.concatenate([-MU[KEPT], np.zeros(8)]),
        A_ub=np.concatenate([np.zeros(4), np.full(4, 0.5), np.full(4, 0.5)]).reshape(1, -1),
        b_ub=[0.45],
        A_eq=np.vstack(
            [
                np.hstack([np.ones((1, 4)), np.zeros((1, 8))]),
                np.hstack([np.eye(4), -np.eye(4), np.eye(4)]),
            ]
        ),
        b_eq=np.concatenate([[1.0], np.array(CURRENT)[KEPT]]),
        bounds=[(0.0, 0.6)] * 4 + [(0.0, None)] * 8,
        method="highs",
    )
    assert -naive.fun > ref_value + 1e-3


@pytest.mark.parametrize(
    ("max_turnover", "cause"),
    [
        (0.15, "REMOVED_ASSETS_TURNOVER_ABOVE_MAX"),  # 0.2 (solo C y D) > 0.15
        (0.35, "TURNOVER_FORCED_ABOVE_MAX"),  # mínimo forzado 0.2 (retirados) + 0.2 (reinvertir)
    ],
)
def test_turnover_above_the_limit_is_infeasible_before_the_solver(
    max_turnover: float, cause: str
) -> None:
    config = base_config()
    problem = _problem(config, spec=spec_with(max_turnover=max_turnover))
    for treatment in (GROSS, NET):
        result = frontier_result(problem, config, treatment)
        assert not result.pre_check_feasible
        assert any(item.startswith(cause) for item in result.infeasibility_causes)
        point = result.points[0]
        assert point.status is SolverStatus.INFEASIBLE
        assert point.status_source is StatusSource.PRE_SOLVER_CHECK and point.solve is None
        assert result.diagnostics.solve_count == 0 and result.diagnostics.setup_count == 0


def test_the_minimum_forced_turnover_is_feasible_at_exactly_that_limit() -> None:
    """Mínimo hecho a mano: vender C y D (0.2) y reinvertir 0.4 en la composición (0.2)."""
    config = base_config()
    problem = _problem(config, spec=spec_with(max_turnover=0.4 + 1e-9))
    result = frontier_result(problem, config, GROSS)
    assert result.pre_check_feasible and len(result.valid_points) >= 1
    assert all(_turnover(weights_of(p)) <= 0.4 + 1e-6 for p in result.valid_points)


@pytest.mark.parametrize("policy", [Policy.HOLD_OR_REDUCE, Policy.FORCE_LIQUIDATE])
def test_restricted_exited_positions_are_compatible_with_reduce_and_liquidate(
    policy: RestrictedExistingPositionPolicy,
) -> None:
    """C restringido y actual: dejarlo fuera de la composición cumple ambas políticas."""
    config = policy_config(base_config(), policy)
    problem = _problem(config, universe_overrides=restricted_universe(6, [2]))
    for treatment in (GROSS, NET):
        result = frontier_result(problem, config, treatment)
        assert result.pre_check_feasible and len(result.valid_points) > 2
        assert all(p.validation is not None and p.validation.is_valid for p in result.valid_points)
        assert all(weights_of(p).sum() == pytest.approx(1.0, abs=1e-7) for p in result.valid_points)
    compiled = compiled_for(problem, config)
    exited = {position.asset_id: position for position in compiled.exited}
    assert exited["A002"].is_restricted and exited["A002"].policy is policy


def test_freeze_weight_cannot_leave_the_composition() -> None:
    """FREEZE_WEIGHT y ``CurrentWeight > 0``: el activo no puede desaparecer; la composición se
    rechaza antes del solver. Con C dentro de la composición, en cambio, es viable (congelado)."""
    config = policy_config(base_config(), Policy.FREEZE_WEIGHT)
    overrides = restricted_universe(6, [2])
    incompatible = _problem(config, universe_overrides=overrides)
    for treatment in (GROSS, NET):
        result = frontier_result(incompatible, config, treatment)
        assert not result.pre_check_feasible
        assert any(c.startswith("FREEZE_WEIGHT_EXITED") for c in result.infeasibility_causes)
        assert "A002" in " ".join(result.infeasibility_causes)
        assert result.diagnostics.solve_count == 0
    compatible = _problem(
        config, universe_overrides=overrides, composition=("A000", "A001", "A002", "A004")
    )
    result = frontier_result(compatible, config, GROSS)
    assert result.pre_check_feasible and len(result.valid_points) > 2
    assert all(weights_of(p)[2] == pytest.approx(0.2, abs=1e-7) for p in result.valid_points)


def test_freeze_weight_of_a_non_held_restricted_asset_may_stay_outside() -> None:
    """Un restringido sin posición no es un problema: FREEZE solo protege posiciones actuales."""
    config = policy_config(base_config(), Policy.FREEZE_WEIGHT)
    problem = _problem(config, universe_overrides=restricted_universe(6, [4]))  # E: no actual
    compiled = compiled_for(
        _problem(config, universe_overrides=restricted_universe(6, [4]), composition=COMPOSITION),
        config,
    )
    assert problem.state.weight_of("A004") == 0.0
    assert all(
        position.policy is None or position.asset_id != "A004" for position in compiled.exited
    )


# ------------------------------------------------------------------------ SolutionValidator


def _validator_case(spec=None, policy=None):  # type: ignore[no-untyped-def]
    config = base_config() if policy is None else policy_config(base_config(), policy)
    overrides = restricted_universe(6, [2]) if policy is not None else None
    problem = _problem(config, spec=spec, universe_overrides=overrides or {})
    inputs = composition_inputs(problem, config)
    context = ValidationContext(inputs.mu, inputs.sigma, inputs.cost_model)
    tolerances = ValidationTolerances.from_config(config.solver)
    return config, inputs, context, SolutionValidator(tolerances)


def test_validator_counts_removed_assets_in_the_turnover() -> None:
    """``w = (0.2, 0.2, 0.3, 0.3)``: turnover de la composición 0.4 (<= 0.45) pero total 0.6."""
    _, inputs, context, validator = _validator_case(spec_with(max_turnover=0.45))
    within = np.array([0.3, 0.3, 0.4, 0.0])  # 0.5·(0 + 0 + 0.4 + 0) + 0.2 = 0.4
    beyond = np.array([0.2, 0.2, 0.3, 0.3])  # 0.5·(0.1 + 0.1 + 0.3 + 0.3) + 0.2 = 0.6
    assert _turnover(within) == pytest.approx(0.4) and _turnover(beyond) == pytest.approx(0.6)
    assert validator.validate(within, inputs.compiled, context).is_valid
    report = validator.validate(beyond, inputs.compiled, context)
    assert not report.is_valid
    assert [v.constraint_id for v in report.violations] == ["TURNOVER:max"]
    assert report.violations[0].value == pytest.approx(0.6, abs=1e-12)
    assert 0.5 * np.abs(beyond - np.array(CURRENT)[KEPT]).sum() <= 0.45  # sin retirados "pasaría"


def test_validator_net_target_uses_the_union_cost_including_liquidation() -> None:
    config, inputs, context, validator = _validator_case()
    weights = np.array([0.3, 0.3, 0.2, 0.2])
    net = _net_return(weights, config.optimization_horizon_years)
    assert validator.validate(
        weights, inputs.compiled, context, ReturnTarget(NET, net - 1e-9)
    ).is_valid
    report = validator.validate(weights, inputs.compiled, context, ReturnTarget(NET, net + 1e-3))
    assert [v.constraint_id for v in report.violations] == ["RETURN_TARGET:net"]
    # con el coste de liquidar C y D omitido, un objetivo por encima del neto real pasaría
    gross_minus_partial = (
        float(MU[KEPT] @ weights)
        - (_cost_one_off(weights) - EXIT_COST_ONE_OFF) / config.optimization_horizon_years
    )
    assert gross_minus_partial > net + 1e-3 / 2


def test_validator_rejects_a_frozen_position_that_leaves_the_composition() -> None:
    """Independiente del pre-check: el validador re-deriva FREEZE_WEIGHT desde la política."""
    _, inputs, context, validator = _validator_case(policy=Policy.FREEZE_WEIGHT)
    report = validator.validate(np.array([0.3, 0.3, 0.4, 0.0]), inputs.compiled, context)
    assert not report.is_valid
    assert "RESTRICTED_POLICY:A002:frozen_exited" in {v.constraint_id for v in report.violations}
    _, inputs, context, validator = _validator_case(policy=Policy.HOLD_OR_REDUCE)
    assert validator.validate(np.array([0.3, 0.3, 0.4, 0.0]), inputs.compiled, context).is_valid


def test_compiled_exit_data_is_consistent_with_the_cost_model() -> None:
    """``K_E`` del modelo de costes = valor independiente; el turnover constante coincide."""
    config, inputs, _, _ = _validator_case()
    assert inputs.cost_model is not None
    assert inputs.cost_model.exit_cost_one_off() == pytest.approx(EXIT_COST_ONE_OFF, abs=1e-15)
    assert inputs.compiled.exit_turnover == pytest.approx(EXIT_TURNOVER, abs=1e-15)
    constraint_set = build_constraint_set(
        config.constraints, None, "P1", None, config.candidates.unknown_liquidity_policy
    )
    problem = _problem(config)
    compiled = ConstraintCompiler().compile(
        constraint_set, problem.universe, COMPOSITION, problem.state
    )
    assert dataclasses.astuple(compiled.exited[0])[:2] == ("A002", 0.2)
