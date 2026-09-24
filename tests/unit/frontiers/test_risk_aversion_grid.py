"""FRN-005, FRN-006, FRN-007 (contractual B2): malla de aversión al riesgo, P constante y warm
start."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.frontiers import ContinuousFrontierEngine, RiskAversionGrid
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    GridScale,
    StrategyID,
    ThetaGridMode,
)
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    point_of,
    weights_of,
)
from tests.fixtures.reference import risk_aversion_budget_only, slsqp_qp

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = cov_from_vol_corr(
    [0.10, 0.15, 0.25, 0.20],
    [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
)
CURRENT = [0.4, 0.3, 0.2, 0.1]


def _problem(config, caps=0.5):  # type: ignore[no-untyped-def]
    return make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [caps] * 4})


def test_matches_the_kkt_closed_form_when_bounds_are_inactive() -> None:
    """Sin límites activos: ``w = KKT(θ)`` (sistema lineal resuelto con NumPy)."""
    config = base_config()
    problem = _problem(config, caps=1.0)
    session = ContinuousFrontierEngine(config).open_session(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    checked = 0
    for theta in (0.05, 0.1, 0.2, 0.4):
        expected = risk_aversion_budget_only(SIGMA, MU, theta)
        if np.any(expected < 0.0):
            continue  # el límite inferior sería activo: no aplica la fórmula cerrada
        point = RiskAversionGrid(session).solve_theta(theta)
        assert weights_of(point) == pytest.approx(expected, abs=1e-7)
        assert point.metrics is not None and point.objective_value == pytest.approx(
            point.metrics.variance - theta * point.metrics.expected_return_gross, abs=1e-12
        )
        checked += 1
    assert checked >= 2


def test_matches_slsqp_when_bounds_are_active() -> None:
    """Con cotas activas (0,4) coincide con SLSQP independiente para cada theta de la malla."""
    config = base_config()
    session = ContinuousFrontierEngine(config).open_session(
        _problem(config, caps=0.4), CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    grid = RiskAversionGrid(session)
    for theta in (0.02, 0.1, 0.3, 0.8, 2.0, 6.0):
        expected = slsqp_qp(
            SIGMA, -theta * MU, np.zeros(4), np.full(4, 0.4), start=np.full(4, 0.25)
        )
        assert weights_of(grid.solve_theta(theta)) == pytest.approx(expected, abs=1e-6)


def test_p_and_a_are_constant_only_q_is_updated() -> None:
    """FRN-005: un solo ``setup`` y, dentro de la malla, solo se actualiza ``q``."""
    config = base_config()
    session = ContinuousFrontierEngine(config).open_session(
        _problem(config), CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    grid = RiskAversionGrid(session)
    grid.solve_theta(
        0.1
    )  # primera actualización (deja el workspace en modo "sin retorno objetivo")
    backend = session.shared_backend
    assert backend is not None
    before = len(backend.updated_fields)
    p_before = session.variance_problem.problem.P.toarray().copy()
    grid.solve_grid(np.geomspace(0.1, 5.0, 12))
    assert backend.setup_count == 1
    assert (
        set(backend.updated_fields[before:]) == {"q"} and len(backend.updated_fields[before:]) >= 11
    )
    assert np.array_equal(session.variance_problem.problem.P.toarray(), p_before)


def test_results_equal_cold_solves() -> None:
    """Reutilizar workspace + warm start da los mismos puntos que resolver cada uno en frío."""
    problem_config = base_config()
    cold_config = base_config(solver={"workspace_reuse": False, "warm_start": False})
    problem = _problem(problem_config)
    reuse = frontier_result(problem, problem_config)
    cold = frontier_result(problem, cold_config)
    assert (
        reuse.diagnostics.setup_count == 3  # QP compartido + LP + etapa 2 de MaxReturn
        and cold.diagnostics.setup_count == cold.diagnostics.solve_count
    )
    assert reuse.diagnostics.warm_start_count > 0 and cold.diagnostics.warm_start_count == 0
    assert len(reuse.points) == len(cold.points)
    for warm, fresh in zip(reuse.points, cold.points, strict=True):
        assert weights_of(warm) == pytest.approx(weights_of(fresh), abs=1e-6)


def test_frontier_is_monotone_in_theta() -> None:
    """Volatilidad y retorno crecen con θ; los extremos son MinVariance (primero) y MaxReturn."""
    config = base_config()
    result = frontier_result(_problem(config), config)
    unique = [p for p in result.points if not p.is_duplicate]
    vols = [p.metrics.volatility for p in unique if p.metrics]
    rets = [p.metrics.expected_return_gross for p in unique if p.metrics]
    assert vols == sorted(vols) and rets == sorted(rets)
    assert result.points[0].strategy_id is StrategyID.MIN_VARIANCE
    assert result.points[-1].strategy_id is StrategyID.MAX_RETURN
    thetas = [
        p.theta
        for p in result.points
        if p.theta is not None and p.strategy_id is StrategyID.FRONTIER_POINT
    ]
    assert thetas == sorted(thetas) and len(thetas) == config.frontier.frontier_points - 2


def test_explicit_endpoints() -> None:
    """FRN-006: MinVariance y MaxReturn se resuelven explícitamente y acotan la frontera."""
    config = base_config()
    result = frontier_result(_problem(config), config)
    minimum, maximum = (
        point_of(result, StrategyID.MIN_VARIANCE),
        point_of(result, StrategyID.MAX_RETURN),
    )
    assert minimum.theta is None and maximum.theta is None
    assert minimum.metrics is not None and maximum.metrics is not None
    for point in result.valid_points:
        assert point.metrics is not None
        assert (
            minimum.metrics.variance - 1e-7
            <= point.metrics.variance
            <= maximum.metrics.variance + 1e-7
        )
        assert (
            minimum.metrics.expected_return_gross - 1e-7
            <= point.metrics.expected_return_gross
            <= maximum.metrics.expected_return_gross + 1e-7
        )


def test_theta_grid_modes_are_honoured() -> None:
    """A-16: el rango de theta procede de la configuración (AUTO o EXPLICIT, LOG o LINEAR)."""
    auto = base_config()
    explicit = dataclasses.replace(
        auto,
        frontier=dataclasses.replace(
            auto.frontier,
            theta_grid_mode=ThetaGridMode.EXPLICIT,
            theta_min=0.2,
            theta_max=3.0,
            theta_scale=GridScale.LINEAR,
        ),
    )
    result = frontier_result(_problem(explicit), explicit)
    thetas = [p.theta for p in result.points if p.strategy_id is StrategyID.FRONTIER_POINT]
    assert thetas[0] == pytest.approx(0.2) and thetas[-1] == pytest.approx(3.0)
    assert np.diff(thetas) == pytest.approx(
        np.full(len(thetas) - 1, (3.0 - 0.2) / (len(thetas) - 1))
    )
    auto_result = frontier_result(_problem(auto), auto)
    auto_thetas = [
        p.theta for p in auto_result.points if p.strategy_id is StrategyID.FRONTIER_POINT
    ]
    ratios = np.array(auto_thetas[1:]) / np.array(auto_thetas[:-1])
    assert ratios == pytest.approx(np.full(len(ratios), ratios[0]))  # espaciado logarítmico
    assert auto_thetas[-1] / auto_thetas[0] == pytest.approx(
        auto.frontier.theta_auto_max_multiplier / auto.frontier.theta_auto_min_multiplier
    )
