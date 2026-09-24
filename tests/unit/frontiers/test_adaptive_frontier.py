"""FRN-019: la frontera adaptativa tiene comportamiento real (no es un parámetro ignorado)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from portfolio_engine.config import FrontierConfig
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import CostTreatment, FrontierMethod, StrategyID
from tests.fixtures.problems import base_config, cov_from_vol_corr, frontier_result, make_problem

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = cov_from_vol_corr(
    [0.10, 0.15, 0.25, 0.20],
    [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
)
CURRENT = [0.4, 0.3, 0.2, 0.1]


def _config(*, adaptive: bool, points: int, initial: int | None = None, gap: float = 1e-6):  # type: ignore[no-untyped-def]
    config = base_config()
    frontier = dataclasses.replace(
        config.frontier,
        frontier_points=points,
        adaptive=adaptive,
        initial_frontier_points=initial if adaptive else None,
        adaptive_gap_tolerance=gap if adaptive else None,
    )
    return dataclasses.replace(config, frontier=frontier)


def _problem(config):  # type: ignore[no-untyped-def]
    return make_problem(MU, SIGMA, CURRENT, config, universe_overrides={"MaxWeight": [0.5] * 4})


def _curve(result):  # type: ignore[no-untyped-def]
    return np.array(
        [
            [p.metrics.volatility, p.metrics.expected_return_gross]
            for p in result.points
            if p.metrics
        ]
    )


def _scores(curve: np.ndarray) -> np.ndarray:
    """Puntuación independiente (hueco × curvatura) de cada intervalo de una curva ordenada."""
    unit = curve / (curve.max(axis=0) - curve.min(axis=0))
    steps = np.diff(unit, axis=0)
    gaps = np.hypot(steps[:, 0], steps[:, 1])
    turning = np.zeros(len(curve))
    for i in range(1, len(curve) - 1):
        a, b = steps[i - 1], steps[i]
        turning[i] = (
            math.acos(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1)) / math.pi
        )
    return gaps * (1.0 + np.maximum(turning[:-1], turning[1:]))


@pytest.mark.parametrize("method", list(FrontierMethod))
def test_adaptive_inserts_points_in_the_largest_gap_and_respects_the_maximum(
    method: FrontierMethod,
) -> None:
    initial = frontier_result(
        _problem(_config(adaptive=False, points=6)),
        _config(adaptive=False, points=6),
        method=method,
    )
    adaptive_config = _config(adaptive=True, points=9, initial=6)
    adaptive = frontier_result(_problem(adaptive_config), adaptive_config, method=method)
    assert len(adaptive.points) == 9 <= adaptive_config.frontier.frontier_points
    inserted = [p for p in adaptive.points if p.is_adaptive_insertion]
    assert len(inserted) == 3 and len(adaptive.points) - len(inserted) == 6
    assert all(p.strategy_id is StrategyID.FRONTIER_POINT for p in inserted)
    # la primera inserción cae en el intervalo de mayor puntuación de la malla inicial
    curve = _curve(initial)
    interval = int(np.argmax(_scores(curve)))
    first = min(inserted, key=lambda p: p.sequence)
    assert first.metrics is not None
    low, high = sorted((curve[interval, 0], curve[interval + 1, 0]))
    assert low - 1e-9 <= first.metrics.volatility <= high + 1e-9


@pytest.mark.parametrize("method", list(FrontierMethod))
def test_adaptive_grid_differs_from_the_uniform_grid(method: FrontierMethod) -> None:
    """No es la malla uniforme completa: los parámetros finales difieren de los de
    ``frontier_points`` uniformes."""
    uniform_config = _config(adaptive=False, points=8)
    uniform = frontier_result(_problem(uniform_config), uniform_config, method=method)
    adaptive_config = _config(adaptive=True, points=8, initial=5)
    adaptive = frontier_result(_problem(adaptive_config), adaptive_config, method=method)
    key = "theta" if method is FrontierMethod.RISK_AVERSION_GRID else "target_return"
    uniform_params = sorted(getattr(p, key) for p in uniform.points if getattr(p, key) is not None)
    adaptive_params = sorted(
        getattr(p, key) for p in adaptive.points if getattr(p, key) is not None
    )
    assert len(adaptive_params) > 0 and not np.allclose(uniform_params, adaptive_params, rtol=1e-6)
    assert any(p.is_adaptive_insertion for p in adaptive.points)
    assert not any(p.is_adaptive_insertion for p in uniform.points)


def test_adaptive_stops_when_every_gap_is_below_the_tolerance() -> None:
    config = _config(
        adaptive=True, points=20, initial=5, gap=10.0
    )  # tolerancia enorme: sin inserciones
    result = frontier_result(_problem(config), config)
    assert len(result.points) == 5 and not any(p.is_adaptive_insertion for p in result.points)


def test_adaptive_never_exceeds_the_maximum_even_with_degenerate_frontiers() -> None:
    """Con costes NET y tolerancia mínima la frontera termina y no supera ``FrontierPoints``."""
    config = _config(adaptive=True, points=12, initial=4, gap=1e-12)
    problem = _problem(config)
    for treatment in (CostTreatment.GROSS, CostTreatment.NET):
        for method in FrontierMethod:
            result = frontier_result(problem, config, treatment, method)
            assert 4 <= len(result.points) <= 12


def test_adaptive_configuration_is_coherent() -> None:
    """Sin parámetros ignorados: ``initial``/``gap`` solo con ``adaptive``; ``initial < points``."""
    base = base_config().frontier
    with pytest.raises(ConfigError, match="no se aceptan parámetros ignorados"):
        dataclasses.replace(base, adaptive=False, initial_frontier_points=5)
    with pytest.raises(ConfigError, match="exige"):
        dataclasses.replace(base, adaptive=True)
    with pytest.raises(ConfigError, match="menor"):
        dataclasses.replace(
            base, adaptive=True, initial_frontier_points=20, adaptive_gap_tolerance=1e-3
        )
    ok = dataclasses.replace(
        base, adaptive=True, initial_frontier_points=8, adaptive_gap_tolerance=1e-3
    )
    assert isinstance(ok, FrontierConfig) and ok.initial_frontier_points == 8


# ------------------------------------------------------------- retorno de puntuación (M-1)


def _costly_problem(config):  # type: ignore[no-untyped-def]
    """Costes altos (200 bps): retorno bruto y neto de cada punto difieren de forma apreciable."""
    return make_problem(
        MU,
        SIGMA,
        CURRENT,
        config,
        universe_overrides={
            "MaxWeight": [0.5] * 4,
            "BuyCost": [200.0] * 4,
            "SellCost": [200.0] * 4,
        },
    )


def _record_first_curve(monkeypatch: pytest.MonkeyPatch) -> list[np.ndarray]:
    """Espía ``_interval_scores``: guarda las curvas (volatilidad, retorno) que puntúa."""
    from portfolio_engine.frontiers import adaptive

    curves: list[np.ndarray] = []
    original = adaptive._interval_scores

    def spy(curve: np.ndarray) -> np.ndarray:
        curves.append(np.array(curve))
        return original(curve)

    monkeypatch.setattr(adaptive, "_interval_scores", spy)
    return curves


def _sorted_by_volatility(curve: np.ndarray) -> np.ndarray:
    return curve[np.argsort(curve[:, 0], kind="stable")]


@pytest.mark.parametrize("method", list(FrontierMethod))
def test_net_adaptive_frontier_is_scored_with_the_net_return(
    monkeypatch: pytest.MonkeyPatch, method: FrontierMethod
) -> None:
    """M-1: la curva puntuada en NET es (volatilidad, retorno NETO). Fallaría si se usara el
    retorno bruto (con costes de 200 bps ambos difieren por encima de 1e-3)."""
    initial_config = _config(adaptive=False, points=6)
    initial = frontier_result(
        _costly_problem(initial_config), initial_config, CostTreatment.NET, method
    )
    net_curve = np.array(
        [[p.metrics.volatility, p.metrics.expected_return_net] for p in initial.points if p.metrics]
    )
    gross_curve = _curve(initial)
    assert np.abs(net_curve[:, 1] - gross_curve[:, 1]).max() > 1e-3
    curves = _record_first_curve(monkeypatch)
    config = _config(adaptive=True, points=9, initial=6)
    frontier_result(_costly_problem(config), config, CostTreatment.NET, method)
    assert curves, "la frontera adaptativa debe puntuar al menos una vez"
    first = _sorted_by_volatility(curves[0])
    assert first == pytest.approx(_sorted_by_volatility(net_curve), abs=1e-9)
    assert not np.allclose(first[:, 1], _sorted_by_volatility(gross_curve)[:, 1], atol=1e-4)


def test_gross_adaptive_frontier_is_scored_with_the_gross_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_config = _config(adaptive=False, points=6)
    initial = frontier_result(_costly_problem(initial_config), initial_config)
    curves = _record_first_curve(monkeypatch)
    config = _config(adaptive=True, points=9, initial=6)
    frontier_result(_costly_problem(config), config)
    assert _sorted_by_volatility(curves[0]) == pytest.approx(
        _sorted_by_volatility(_curve(initial)), abs=1e-9
    )


def test_post_cost_gross_adaptive_frontier_is_scored_with_the_net_return_of_gross_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST_COST_GROSS publica (volatilidad, retorno tras costes) de los pesos GROSS: la
    adaptativa puntúa con ese retorno neto, no con el bruto."""
    initial_config = _config(adaptive=False, points=6)
    initial = frontier_result(_costly_problem(initial_config), initial_config)
    expected = np.array(
        [[p.metrics.volatility, p.metrics.expected_return_net] for p in initial.points if p.metrics]
    )
    curves = _record_first_curve(monkeypatch)
    config = _config(adaptive=True, points=9, initial=6)
    result = frontier_result(_costly_problem(config), config, CostTreatment.POST_COST_GROSS)
    assert result.cost_treatment is CostTreatment.POST_COST_GROSS
    assert _sorted_by_volatility(curves[0]) == pytest.approx(
        _sorted_by_volatility(expected), abs=1e-9
    )


def test_scoring_return_selects_the_metric_of_the_treatment() -> None:
    from portfolio_engine.exceptions import FrontierError
    from portfolio_engine.frontiers.adaptive import scoring_return

    config = _config(adaptive=False, points=6)
    result = frontier_result(_costly_problem(config), config, CostTreatment.NET)
    metrics = next(p.metrics for p in result.valid_points if p.metrics)
    assert metrics.expected_return_net is not None
    assert scoring_return(CostTreatment.GROSS)(metrics) == metrics.expected_return_gross
    for treatment in (CostTreatment.NET, CostTreatment.POST_COST_GROSS):
        assert scoring_return(treatment)(metrics) == metrics.expected_return_net
    unavailable = dataclasses.replace(
        metrics, expected_return_net=None, unavailable_reason="NO_CURRENT_PORTFOLIO"
    )
    with pytest.raises(FrontierError, match="retorno neto"):
        scoring_return(CostTreatment.NET)(unavailable)
