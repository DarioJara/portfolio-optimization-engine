"""FRN-008, FRN-009, OPT-008 (contractual B2): malla de retorno objetivo."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.frontiers import (
    ContinuousFrontierEngine,
    TargetReturnGrid,
    interior_targets,
    target_range,
)
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
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
    weights_of,
)
from tests.fixtures.reference import slsqp_qp

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = cov_from_vol_corr(
    [0.10, 0.15, 0.25, 0.20],
    [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
)
CURRENT = [0.4, 0.3, 0.2, 0.1]
ROW = MU.reshape(1, 4)


def _session(config=None, treatment=CostTreatment.GROSS):  # type: ignore[no-untyped-def]
    config = config or base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4})
    engine = ContinuousFrontierEngine(config)
    return engine.open_session(problem, treatment, FrontierMethod.TARGET_RETURN_GRID), config


def test_target_matches_slsqp_reference_and_constraint_is_active() -> None:
    """Para ``R > R_MV`` la restricción ``μᵀw >= R`` está activa y la varianza coincide con
    SLSQP."""
    session, _ = _session()
    grid = TargetReturnGrid(session)
    minimum = session.solve_minimum_variance()
    assert minimum.metrics is not None
    for target in (0.075, 0.085, 0.095, 0.105):
        point = grid.solve_target(target)
        expected = slsqp_qp(
            SIGMA,
            np.zeros(4),
            np.zeros(4),
            np.full(4, 0.5),
            start=np.full(4, 0.25),
            extra_ineq=[(MU, target, np.inf)],
        )
        assert point.metrics is not None and point.is_valid_solution
        assert point.metrics.expected_return_gross == pytest.approx(target, abs=1e-7)  # activa
        assert point.metrics.variance == pytest.approx(float(expected @ SIGMA @ expected), rel=1e-6)
        assert weights_of(point) == pytest.approx(expected, abs=1e-5)
        assert point.target_return == target and point.metrics.variance > minimum.metrics.variance


def test_target_below_minimum_variance_return_is_inactive() -> None:
    """Con ``R <= R_MV`` el óptimo es la mínima varianza (la restricción no ata)."""
    session, _ = _session()
    minimum = session.solve_minimum_variance()
    point = TargetReturnGrid(session).solve_target(0.01)
    assert weights_of(point) == pytest.approx(weights_of(minimum), abs=1e-6)


def test_infeasible_target_is_reported_by_the_solver() -> None:
    """Objetivo factible vs infactible: ``R > R_max`` ⇒ INFEASIBLE del solver (no numérico)."""
    session, _ = _session()
    maximum, _ = session.solve_maximum_return()
    assert maximum.metrics is not None
    feasible = TargetReturnGrid(session).solve_target(maximum.metrics.expected_return_gross - 1e-4)
    infeasible = TargetReturnGrid(session).solve_target(
        maximum.metrics.expected_return_gross + 0.01
    )
    assert feasible.is_valid_solution
    assert (
        infeasible.status is SolverStatus.INFEASIBLE
        and infeasible.status_source is StatusSource.SOLVER
    )
    assert (
        infeasible.weights is None
        and not infeasible.is_valid_solution
        and infeasible.metrics is None
    )


def test_p_a_and_q_are_constant_only_lower_is_updated() -> None:
    """FRN-008: un solo ``setup`` y, dentro de la malla, solo se actualiza ``lower`` (fila de
    retorno)."""
    session, _ = _session()
    grid = TargetReturnGrid(session)
    grid.solve_target(0.07)
    backend = session.shared_backend
    assert backend is not None
    before = len(backend.updated_fields)
    grid.solve_grid(np.linspace(0.072, 0.105, 12))
    assert backend.setup_count == 1
    assert (
        set(backend.updated_fields[before:]) == {"lower"}
        and len(backend.updated_fields[before:]) == 12
    )


def test_range_and_interior_targets() -> None:
    """FRN-009: rango ``[R_MV, R_max]`` y objetivos interiores equiespaciados; degenerado ⇒
    ``None``."""
    assert target_range(0.06, 0.11) == (0.06, 0.11)
    assert target_range(0.06, 0.06) is None and target_range(0.07, 0.06) is None
    inner = interior_targets(0.0, 1.0, 4)
    assert inner.tolist() == pytest.approx([0.2, 0.4, 0.6, 0.8])
    assert interior_targets(0.0, 1.0, 0).size == 0


def test_frontier_targets_span_the_range_and_are_monotone() -> None:
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4})
    result = frontier_result(problem, config, method=FrontierMethod.TARGET_RETURN_GRID)
    minimum, maximum = (
        point_of(result, StrategyID.MIN_VARIANCE),
        point_of(result, StrategyID.MAX_RETURN),
    )
    assert minimum.metrics is not None and maximum.metrics is not None
    targets = [p.target_return for p in result.points if p.strategy_id is StrategyID.FRONTIER_POINT]
    assert len(targets) == config.frontier.frontier_points - 2
    assert targets == sorted(targets)
    assert (
        minimum.metrics.expected_return_gross < targets[0]
        and targets[-1] < maximum.metrics.expected_return_gross
    )
    steps = np.diff(
        [minimum.metrics.expected_return_gross, *targets, maximum.metrics.expected_return_gross]
    )
    assert steps == pytest.approx(np.full(steps.size, steps[0]), abs=1e-7)  # rejilla uniforme
    vols = [p.metrics.volatility for p in result.points if p.metrics]
    assert vols == sorted(vols)
    assert result.diagnostics.setup_count == 3  # QP compartido + LP + etapa 2 de MaxReturn


def test_net_target_is_the_net_return_constraint() -> None:
    """FRN-011: el objetivo neto exige ``μᵀw − TC(w) >= R`` (no un objetivo bruto ajustado)."""
    config = base_config()
    problem = make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={
            "MaxWeight": [0.5] * 4,
            "BuyCost": [150.0] * 4,
            "SellCost": [150.0] * 4,
        },
    )
    session = ContinuousFrontierEngine(config).open_session(
        problem, CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID
    )
    target = 0.085
    point = TargetReturnGrid(session).solve_target(target)
    assert point.metrics is not None and point.metrics.expected_return_net is not None
    assert point.metrics.expected_return_net == pytest.approx(target, abs=1e-7)  # activa en neto
    assert point.metrics.expected_return_gross > target  # el bruto compensa el coste
    assert point.metrics.transaction_cost is not None and point.metrics.transaction_cost > 0.0
    gross_point = TargetReturnGrid(
        ContinuousFrontierEngine(config).open_session(
            problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
        )
    ).solve_target(target)
    assert gross_point.metrics is not None
    assert (
        point.metrics.variance >= gross_point.metrics.variance - 1e-10
    )  # exigir lo mismo en neto cuesta más riesgo
