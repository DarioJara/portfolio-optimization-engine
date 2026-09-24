"""FRN-007, FRN-014..016, FRN-018, FRN-020, FRN-021, FRN-023: dedup, Pareto, número de puntos y
calibración."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.frontiers import (
    apply_efficiency,
    calibrate_theta_from_points,
    deduplicate,
    grid_values,
    is_equivalent,
    midpoint,
    pareto_mask,
)
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    FrontierScope,
    GridScale,
    SolverStatus,
    StatusSource,
    StrategyID,
    ThetaGridMode,
)
from portfolio_engine.models.frontier import FrontierPoint, PointMetrics
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    weights_of,
)

pytestmark = pytest.mark.unit

FRONTIER = base_config().frontier


def _metrics(vol: float, gross: float, net: float | None) -> PointMetrics:
    return PointMetrics(
        gross, vol * vol, vol, None, 0.0, 2, None, None, None, net, None, None, None
    )


def _point(
    index: int,
    vol: float,
    gross: float,
    net: float | None = None,
    *,
    weights=(0.5, 0.5),
    valid=True,
) -> FrontierPoint:  # type: ignore[no-untyped-def]
    return FrontierPoint(
        point_id=f"P{index}",
        sequence=index,
        strategy_id=StrategyID.FRONTIER_POINT,
        scope=FrontierScope.CONTINUOUS_FRONTIER,
        cost_treatment=CostTreatment.GROSS,
        method=FrontierMethod.RISK_AVERSION_GRID,
        composition_id="C",
        theta=None,
        target_return=None,
        weights=np.array(weights),
        metrics=_metrics(vol, gross, net),
        objective_value=None,
        solve=None,
        validation=None,
        is_valid_solution=valid,
        status=SolverStatus.OPTIMAL,
        status_source=StatusSource.SOLVER,
    )


def test_dedup_requires_equivalence_in_weights_return_and_volatility() -> None:
    """FRN-020: duplicado solo si los tres criterios están dentro de tolerancia; se marca, no se
    borra."""
    base = _point(0, 0.10, 0.06, weights=(0.5, 0.5))
    same = _point(1, 0.10, 0.06, weights=(0.5 + 1e-9, 0.5 - 1e-9))
    other_weights = _point(2, 0.10, 0.06, weights=(0.6, 0.4))
    other_return = _point(3, 0.10, 0.07, weights=(0.5, 0.5))
    other_vol = _point(4, 0.11, 0.06, weights=(0.5, 0.5))
    result = deduplicate([base, same, other_weights, other_return, other_vol], FRONTIER)
    assert len(result) == 5  # nada se elimina del almacenamiento
    assert [p.is_duplicate for p in result] == [False, True, False, False, False]
    assert result[1].duplicate_of == "P0" and result[0].duplicate_of is None
    assert is_equivalent(base, same, FRONTIER) and not is_equivalent(base, other_weights, FRONTIER)
    tight = dataclasses.replace(
        FRONTIER,
        dedup_weight_tolerance=0.0,
        dedup_return_tolerance=0.0,
        dedup_volatility_tolerance=0.0,
    )
    assert not deduplicate([base, same], tight)[1].is_duplicate


def test_dedup_ignores_invalid_points() -> None:
    invalid = _point(1, 0.10, 0.06, valid=False)
    assert not any(p.is_duplicate for p in deduplicate([_point(0, 0.10, 0.06), invalid], FRONTIER))


def test_pareto_mask_dominance_and_tolerance() -> None:
    """FRN-014/015: dominado = otro válido con ≤ volatilidad y ≥ retorno, mejor en al menos uno."""
    vol = np.array([0.10, 0.12, 0.12, 0.15, 0.09])
    ret = np.array([0.05, 0.06, 0.055, 0.08, 0.05])
    valid = np.array([True, True, True, True, False])
    assert pareto_mask(vol, ret, valid, 0.0).tolist() == [True, True, False, True, False]
    # una tolerancia grande hace que puntos casi iguales no se dominen entre sí
    near = pareto_mask(
        np.array([0.10, 0.10 + 1e-12]), np.array([0.05, 0.05 + 1e-12]), np.array([True, True]), 1e-9
    )
    assert near.tolist() == [True, True]


def test_efficiency_flags_gross_and_net_and_dominated_are_kept() -> None:
    """FRN-016: se marcan ``IsGrossEfficient``/``IsNetEfficient`` y los dominados siguen
    almacenados."""
    points = [
        _point(0, 0.10, 0.05, 0.049),
        _point(1, 0.12, 0.07, 0.040),  # eficiente en bruto, dominado en neto por el punto 0
        _point(2, 0.13, 0.065, 0.062),
        _point(3, 0.14, 0.09, 0.085),
    ]
    flagged = apply_efficiency(points, 0.0)
    assert len(flagged) == 4
    assert [p.is_gross_efficient for p in flagged] == [True, True, False, True]
    assert [p.is_net_efficient for p in flagged] == [True, False, True, True]


def test_invalid_points_are_stored_but_excluded_from_pareto() -> None:
    """FRN-023: un punto inválido conserva su fila y nunca es eficiente."""
    flagged = apply_efficiency([_point(0, 0.10, 0.05), _point(1, 0.09, 0.09, valid=False)], 0.0)
    assert [p.is_gross_efficient for p in flagged] == [True, False]
    assert flagged[1].is_valid_solution is False


def test_duplicates_inherit_the_efficiency_of_their_original() -> None:
    marked = deduplicate(
        [_point(0, 0.10, 0.05), _point(1, 0.10, 0.05), _point(2, 0.12, 0.04)], FRONTIER
    )
    flagged = apply_efficiency(marked, 0.0)
    assert [p.is_gross_efficient for p in flagged] == [True, True, False]


@pytest.mark.parametrize("points", [10, 20, 30, 50])
@pytest.mark.parametrize("method", list(FrontierMethod))
def test_frontier_points_is_configurable(points: int, method: FrontierMethod) -> None:
    """FRN-018: 10/20/30/50 puntos (defecto 20 declarado solo en la configuración)."""
    config = base_config()
    config = dataclasses.replace(
        config, frontier=dataclasses.replace(config.frontier, frontier_points=points)
    )
    assert base_config().frontier.frontier_points == 20
    problem = make_problem(
        [0.05, 0.08, 0.12, 0.10],
        cov_from_vol_corr([0.10, 0.15, 0.25, 0.20], np.eye(4) * 0.7 + 0.3),
        [0.4, 0.3, 0.2, 0.1],
        config,
        universe_overrides={"MaxWeight": [0.5] * 4},
    )
    result = frontier_result(problem, config, method=method)
    assert len(result.points) == points and all(p.is_valid_solution for p in result.points)
    assert len({p.point_id for p in result.points}) == points


def test_frontier_type_encoding() -> None:
    """FRN-021: ``FrontierType = "{FrontierScope}:{CostTreatment}"``."""
    config = base_config()
    problem = make_problem(
        [0.05, 0.08],
        np.diag([0.04, 0.09]),
        [0.5, 0.5],
        config,
        universe_overrides={"MaxWeight": [1.0, 1.0]},
    )
    for treatment in CostTreatment:
        result = frontier_result(problem, config, treatment)
        assert result.frontier_type == f"CONTINUOUS_FRONTIER:{treatment.value}"
        assert weights_of(result.points[0]).sum() == pytest.approx(1.0)


def test_theta_calibration_auto_and_explicit() -> None:
    """FRN-007/A-16: ``θ_ref = (σ²_MR − σ²_MV)/(R_MR − R_MV)`` con multiplicadores; EXPLICIT usa
    la configuración."""
    grid = calibrate_theta_from_points(FRONTIER, (0.01, 0.05), (0.04, 0.09), 1e-9)
    assert grid is not None and grid.reference == pytest.approx((0.04 - 0.01) / (0.09 - 0.05))
    assert grid.theta_min == pytest.approx(FRONTIER.theta_auto_min_multiplier * 0.75)
    assert grid.theta_max == pytest.approx(FRONTIER.theta_auto_max_multiplier * 0.75)
    assert (
        calibrate_theta_from_points(FRONTIER, (0.01, 0.05), (0.04, 0.05), 1e-9) is None
    )  # degenerada
    explicit = dataclasses.replace(
        FRONTIER, theta_grid_mode=ThetaGridMode.EXPLICIT, theta_min=0.1, theta_max=2.0
    )
    fixed = calibrate_theta_from_points(explicit, (0.01, 0.05), (0.04, 0.09), 1e-9)
    assert fixed is not None and (fixed.theta_min, fixed.theta_max, fixed.reference) == (
        0.1,
        2.0,
        None,
    )


def test_grid_values_and_midpoints() -> None:
    assert grid_values(1.0, 100.0, 3, GridScale.LOG).tolist() == pytest.approx([1.0, 10.0, 100.0])
    assert grid_values(1.0, 3.0, 3, GridScale.LINEAR).tolist() == [1.0, 2.0, 3.0]
    assert (
        midpoint(1.0, 100.0, GridScale.LOG) == pytest.approx(10.0)
        and midpoint(1.0, 3.0, GridScale.LINEAR) == 2.0
    )
