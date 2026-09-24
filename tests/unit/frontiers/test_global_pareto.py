"""FRN-017, FRN-016, FRN-020 (entre composiciones): envolvente de Pareto global sobre puntos
construidos a mano (dominancia, magnitudes separadas, duplicados, inválidos)."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.frontiers import global_pareto
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    FrontierScope,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.models.frontier import (
    FrontierPoint,
    GlobalFrontierPoint,
    PointMetrics,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

FRONTIER = base_config().frontier


def _point(
    composition: str,
    assets: tuple[str, ...],
    index: int,
    vol: float,
    gross: float,
    net: float | None,
    weights: tuple[float, ...],
    *,
    valid: bool = True,
) -> GlobalFrontierPoint:
    metrics = PointMetrics(
        expected_return_gross=gross,
        variance=vol * vol,
        volatility=vol,
        sharpe_ratio=None,
        herfindahl_index=0.5,
        number_assets=len(assets),
        turnover=None if net is None else 0.1,
        transaction_cost_one_off=None if net is None else gross - net,
        transaction_cost=None if net is None else gross - net,
        expected_return_net=net,
        number_new_assets=None,
        number_removed_assets=None,
        unavailable_reason=None,
    )
    point = FrontierPoint(
        point_id=f"P{index:03d}",
        sequence=index,
        strategy_id=StrategyID.FRONTIER_POINT,
        scope=FrontierScope.GLOBAL_CANDIDATE_FRONTIER,
        cost_treatment=CostTreatment.NET,
        method=FrontierMethod.RISK_AVERSION_GRID,
        composition_id=composition,
        theta=None,
        target_return=None,
        weights=np.array(weights),
        metrics=metrics,
        objective_value=None,
        solve=None,
        validation=None,
        is_valid_solution=valid,
        status=SolverStatus.OPTIMAL,
        status_source=StatusSource.SOLVER,
    )
    return GlobalFrontierPoint(f"{composition}:{point.point_id}", index, composition, assets, point)


def _flags(points, attribute):  # type: ignore[no-untyped-def]
    return [getattr(p, attribute) for p in points]


def test_a_point_dominated_by_another_composition_is_flagged_but_kept() -> None:
    points = [
        _point("X", ("A", "B"), 0, 0.10, 0.05, 0.05, (0.5, 0.5)),
        _point("Y", ("A", "C"), 1, 0.15, 0.04, 0.04, (0.6, 0.4)),  # dominado por el punto 0
        _point("X", ("A", "B"), 2, 0.30, 0.20, 0.20, (0.1, 0.9)),
    ]
    result = global_pareto(points, FRONTIER)
    assert len(result) == 3  # no se elimina ninguno (FRN-016)
    assert _flags(result, "is_global_gross_efficient") == [True, False, True]
    assert _flags(result, "is_global_net_efficient") == [True, False, True]


def test_two_compositions_can_both_contribute_non_dominated_points() -> None:
    x = [
        _point("X", ("A", "B"), 0, 0.10, 0.05, 0.05, (0.5, 0.5)),
        _point("X", ("A", "B"), 1, 0.30, 0.20, 0.20, (0.1, 0.9)),
    ]
    y = [
        _point("Y", ("C", "D"), 2, 0.20, 0.12, 0.12, (0.5, 0.5)),  # entre los dos de X
        _point("Y", ("C", "D"), 3, 0.40, 0.18, 0.18, (0.2, 0.8)),  # dominado por el punto 1
    ]
    result = global_pareto(x + y, FRONTIER)
    assert _flags(result, "is_global_gross_efficient") == [True, True, True, False]
    assert {p.composition_id for p in result if p.is_global_gross_efficient} == {"X", "Y"}


def test_gross_and_net_efficiency_use_a_single_magnitude_each() -> None:
    """Mismo riesgo: por retorno bruto gana P0; por retorno neto gana P1 (costes menores)."""
    points = [
        _point("X", ("A",), 0, 0.20, 0.10, 0.090, (1.0,)),
        _point("Y", ("B",), 1, 0.20, 0.09, 0.095, (1.0,)),
    ]
    result = global_pareto(points, FRONTIER)
    assert _flags(result, "is_global_gross_efficient") == [True, False]
    assert _flags(result, "is_global_net_efficient") == [False, True]


def test_points_without_net_return_leave_the_net_flag_unavailable() -> None:
    points = [
        _point("X", ("A", "B"), 0, 0.10, 0.05, None, (0.5, 0.5)),
        _point("X", ("A", "B"), 1, 0.30, 0.20, None, (0.1, 0.9)),
    ]
    result = global_pareto(points, FRONTIER)
    assert _flags(result, "is_global_net_efficient") == [None, None]
    assert _flags(result, "is_global_gross_efficient") == [True, True]


def test_invalid_points_are_stored_but_never_dominate() -> None:
    points = [
        _point("X", ("A",), 0, 0.05, 0.50, 0.50, (1.0,), valid=False),  # dominaría a todos
        _point("Y", ("B",), 1, 0.20, 0.10, 0.10, (1.0,)),
    ]
    result = global_pareto(points, FRONTIER)
    assert len(result) == 2 and not result[0].is_valid_solution
    assert _flags(result, "is_global_gross_efficient") == [False, True]


def test_equivalent_points_of_different_compositions_are_duplicates_with_traceability() -> None:
    """Misma cartera vista desde dos composiciones (una con un peso 0 adicional)."""
    points = [
        _point("X", ("A", "B"), 0, 0.10, 0.05, 0.05, (0.5, 0.5)),
        _point("Y", ("A", "B", "C"), 1, 0.10, 0.05, 0.05, (0.5, 0.5, 0.0)),
        _point("Z", ("A", "B"), 2, 0.30, 0.20, 0.20, (0.1, 0.9)),
    ]
    result = global_pareto(points, FRONTIER)
    assert [p.is_duplicate for p in result] == [False, True, False]
    assert result[1].duplicate_of == result[0].global_point_id  # trazabilidad al representante
    assert _flags(result, "is_global_gross_efficient") == [True, True, True]  # hereda la eficiencia


def test_points_that_differ_in_weights_beyond_the_tolerance_are_not_duplicates() -> None:
    tolerance = FRONTIER.dedup_weight_tolerance
    points = [
        _point("X", ("A", "B"), 0, 0.10, 0.05, 0.05, (0.5, 0.5)),
        _point(
            "Y", ("A", "B"), 1, 0.10, 0.05, 0.05, (0.5 + 100 * tolerance, 0.5 - 100 * tolerance)
        ),
    ]
    assert [p.is_duplicate for p in global_pareto(points, FRONTIER)] == [False, False]


def test_empty_input_and_all_invalid_input() -> None:
    assert global_pareto([], FRONTIER) == ()
    only_invalid = [_point("X", ("A",), 0, 0.1, 0.1, 0.1, (1.0,), valid=False)]
    result = global_pareto(only_invalid, FRONTIER)
    assert _flags(result, "is_global_gross_efficient") == [False]


def test_the_representative_of_a_duplicate_group_is_the_first_in_canonical_order() -> None:
    a = _point("X", ("A", "B"), 0, 0.10, 0.05, 0.05, (0.5, 0.5))
    b = _point("Y", ("A", "B"), 1, 0.10, 0.05, 0.05, (0.5, 0.5))
    assert [p.is_duplicate for p in global_pareto([a, b], FRONTIER)] == [False, True]
    assert [p.is_duplicate for p in global_pareto([b, a], FRONTIER)] == [
        False,
        True,
    ]  # el primero manda
    assert global_pareto([b, a], FRONTIER)[1].duplicate_of == b.global_point_id


def test_envelope_matches_an_independent_brute_force_dominance_check() -> None:
    """Propiedad sobre 200 puntos aleatorios: eficiente ⇔ ningún otro punto válido lo domina."""
    rng = np.random.default_rng(9)
    compositions = ["X", "Y", "Z", "W"]
    points = [
        _point(
            compositions[i % 4],
            ("A", "B"),
            i,
            float(rng.uniform(0.05, 0.4)),
            float(rng.uniform(0.0, 0.3)),
            float(rng.uniform(0.0, 0.3)),
            (i / 200, 1 - i / 200),
            valid=bool(rng.uniform() > 0.1),
        )
        for i in range(200)
    ]
    result = global_pareto(points, FRONTIER)
    tolerance = FRONTIER.pareto_tolerance
    for magnitude, attribute in (
        ("expected_return_gross", "is_global_gross_efficient"),
        ("expected_return_net", "is_global_net_efficient"),
    ):
        for candidate in result:
            if not candidate.is_valid_solution:
                assert getattr(candidate, attribute) is False
                continue
            c_vol = candidate.point.metrics.volatility  # type: ignore[union-attr]
            c_ret = getattr(candidate.point.metrics, magnitude)
            dominated = any(
                other.is_valid_solution
                and not other.is_duplicate
                and other.point.metrics.volatility <= c_vol + tolerance  # type: ignore[union-attr]
                and getattr(other.point.metrics, magnitude) >= c_ret - tolerance
                and (
                    other.point.metrics.volatility < c_vol - tolerance  # type: ignore[union-attr]
                    or getattr(other.point.metrics, magnitude) > c_ret + tolerance
                )
                for other in result
            )
            assert getattr(candidate, attribute) is (not dominated)
