"""FRN-012 (contractual B2): POST_COST_GROSS no es NET; NET domina o iguala a POST_COST en (vol,
net)."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.exceptions import FrontierError
from portfolio_engine.frontiers import (
    ContinuousFrontierEngine,
    TargetReturnGrid,
    post_cost_evaluation,
)
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    frontier_result,
    make_problem,
    weights_of,
)

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12])
SIGMA = cov_from_vol_corr([0.10, 0.15, 0.25], [[1, 0.3, 0.2], [0.3, 1, 0.4], [0.2, 0.4, 1]])
CURRENT = [0.6, 0.3, 0.1]
COSTS = {"MaxWeight": [1.0] * 3, "BuyCost": [300.0] * 3, "SellCost": [300.0] * 3}


def _results(method: FrontierMethod):  # type: ignore[no-untyped-def]
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides=COSTS)
    return {t: frontier_result(problem, config, t, method) for t in CostTreatment}


@pytest.mark.parametrize("method", list(FrontierMethod))
def test_net_dominates_or_equals_post_cost_in_vol_net(method: FrontierMethod) -> None:
    """Ningún punto POST_COST supera a la frontera NET en (volatilidad, retorno neto).

    Para cada punto post-coste se resuelve el problema NET de retorno objetivo con su mismo retorno
    neto: la varianza mínima alcanzable con costes dentro de la optimización no la supera.
    """
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides=COSTS)
    post = frontier_result(problem, config, CostTreatment.POST_COST_GROSS, method)
    session = ContinuousFrontierEngine(config).open_session(
        problem, CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID
    )
    checked = 0
    for point in post.valid_points:
        assert point.metrics is not None and point.metrics.expected_return_net is not None
        net_point = TargetReturnGrid(session).solve_target(point.metrics.expected_return_net)
        assert net_point.is_valid_solution and net_point.metrics is not None
        assert net_point.metrics.variance <= point.metrics.variance + 1e-8
        checked += 1
    assert checked == len(post.points)


@pytest.mark.parametrize("method", list(FrontierMethod))
def test_net_frontier_differs_from_post_cost_gross_in_a_designed_case(
    method: FrontierMethod,
) -> None:
    """Con costes altos, NET (costes dentro de la optimización) ≠ POST_COST_GROSS (bruta evaluada
    ex post)."""
    results = _results(method)
    net, post = results[CostTreatment.NET], results[CostTreatment.POST_COST_GROSS]
    assert (
        net.cost_treatment is CostTreatment.NET
        and post.cost_treatment is CostTreatment.POST_COST_GROSS
    )
    assert net.frontier_type != post.frontier_type and post.frontier_type.endswith(
        "POST_COST_GROSS"
    )
    # pesos distintos en el mismo punto de la malla
    gaps = [
        float(np.max(np.abs(weights_of(a) - weights_of(b))))
        for a, b in zip(net.points, post.points, strict=True)
    ]
    assert max(gaps) > 1e-2
    # y existe un punto POST_COST dominado estrictamente por la frontera NET
    strictly_dominated = 0
    for p in post.valid_points:
        assert p.metrics is not None and p.metrics.expected_return_net is not None
        best_net = max(
            (
                n.metrics.expected_return_net
                for n in net.valid_points
                if n.metrics
                and n.metrics.expected_return_net is not None
                and n.metrics.volatility <= p.metrics.volatility + 1e-9
            ),
            default=-np.inf,
        )
        strictly_dominated += best_net > p.metrics.expected_return_net + 1e-4
    assert strictly_dominated >= 1


def test_post_cost_reuses_gross_weights_and_is_never_labelled_net() -> None:
    results = _results(FrontierMethod.RISK_AVERSION_GRID)
    gross, post = results[CostTreatment.GROSS], results[CostTreatment.POST_COST_GROSS]
    for g, p in zip(gross.points, post.points, strict=True):
        assert weights_of(g) == pytest.approx(weights_of(p), abs=0.0)
        assert p.cost_treatment is CostTreatment.POST_COST_GROSS
        assert p.metrics is not None and g.metrics is not None
        assert p.metrics.expected_return_net == g.metrics.expected_return_net
    assert (
        post.diagnostics.solve_count == gross.diagnostics.solve_count
    )  # no se resolvió nada nuevo
    assert all(p.point_id.startswith("POST_COST_GROSS:") for p in post.points)


def test_post_cost_requires_a_gross_frontier_and_cost_data() -> None:
    config = base_config()
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides=COSTS, with_costs=False)
    engine = ContinuousFrontierEngine(config)
    with pytest.raises(FrontierError, match="POST_COST_GROSS exige"):
        engine.solve(problem, CostTreatment.POST_COST_GROSS, FrontierMethod.RISK_AVERSION_GRID)
    net = _results(FrontierMethod.RISK_AVERSION_GRID)[CostTreatment.NET]
    with pytest.raises(FrontierError, match="GROSS"):
        post_cost_evaluation(net, 1e-10)
