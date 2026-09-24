"""OPT-003, OPT-004, OPT-013, TC-010, TST-013 (parte algebraica): constructor de problemas QP/LP."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.exceptions import FrontierError
from portfolio_engine.models.enums import CostTreatment, OptimizationFamily, ProblemClass
from portfolio_engine.optimizers import OSQPBackend
from portfolio_engine.optimizers.formulations import build_fixed_composition_problem
from tests.fixtures.problems import (
    base_config,
    composition_inputs,
    cov_from_vol_corr,
    make_problem,
    spec_with,
)

pytestmark = pytest.mark.unit

MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = cov_from_vol_corr(
    [0.10, 0.15, 0.25, 0.20],
    [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
)
CURRENT = [0.4, 0.3, 0.2, 0.1]
COSTS = {"BuyCost": [20.0, 30.0, 40.0, 50.0], "SellCost": [60.0, 70.0, 80.0, 90.0]}  # bps


def _inputs(config=None, *, spec=None, horizon: float = 1.0):  # type: ignore[no-untyped-def]
    config = config or base_config()
    config = dataclasses.replace(config, optimization_horizon_years=horizon)
    problem = make_problem(MU, SIGMA, CURRENT, config, universe_overrides=COSTS, spec=spec)
    return config, composition_inputs(problem, config)


def test_variables_only_selected_assets() -> None:
    """OPT-003: las variables son solo los activos de la composición (4), bruto sin lifting."""
    _, inputs = _inputs()
    built = build_fixed_composition_problem(inputs, CostTreatment.GROSS, quadratic=True)
    assert built.n_weights == 4 and not built.lifted
    assert built.problem.n_variables == 4
    # filas: presupuesto (1) + límites (4) + retorno (1)
    assert built.problem.n_constraints == 6 and built.return_row == 5
    assert built.problem.problem_class is ProblemClass.QP
    assert built.problem.family is OptimizationFamily.FAST_PRODUCTION


def test_p_is_twice_sigma_and_constant() -> None:
    """P = 2Σ (triangular superior) y no depende de theta ni del tratamiento de costes."""
    _, inputs = _inputs()
    gross = build_fixed_composition_problem(inputs, CostTreatment.GROSS, quadratic=True)
    net = build_fixed_composition_problem(inputs, CostTreatment.NET, quadratic=True)
    expected = np.triu(2.0 * SIGMA)
    assert gross.problem.P.toarray() == pytest.approx(expected, abs=1e-15)
    top_left = net.problem.P.toarray()[:4, :4]
    assert top_left == pytest.approx(expected, abs=1e-15)
    assert not net.problem.P.toarray()[4:, :].any() and not net.problem.P.toarray()[:, 4:].any()
    for theta in (0.1, 1.0, 10.0):  # q cambia, P no
        gross.q_risk_aversion(theta)
        assert gross.problem.P.toarray() == pytest.approx(expected, abs=1e-15)


def test_q_scales_with_theta_including_the_cost_block() -> None:
    """TST-013 (a): ``q(θ) = θ·q1`` con ``q1 = [−μ; c_b/H; c_s/H]`` (H = horizonte)."""
    horizon = 2.5
    _, inputs = _inputs(horizon=horizon)
    net = build_fixed_composition_problem(inputs, CostTreatment.NET, quadratic=True)
    buy = np.array(COSTS["BuyCost"]) / 10_000.0
    sell = np.array(COSTS["SellCost"]) / 10_000.0
    q1 = np.concatenate([-MU, buy / horizon, sell / horizon])
    assert net.unit_objective == pytest.approx(q1, abs=1e-15)
    for theta in (0.3, 1.0, 4.0):
        assert net.q_risk_aversion(theta) == pytest.approx(theta * q1, abs=1e-15)
    gross = build_fixed_composition_problem(inputs, CostTreatment.GROSS, quadratic=True)
    assert gross.unit_objective == pytest.approx(-MU, abs=1e-15)


def test_net_layout_lifting_and_return_row() -> None:
    """TC-010: variables ``[w; b; s]``, ``w − b + s = w0``, fila de retorno neto."""
    horizon = 2.0
    _, inputs = _inputs(horizon=horizon)
    net = build_fixed_composition_problem(inputs, CostTreatment.NET, quadratic=True)
    a = net.problem.A.toarray()
    assert net.lifted and net.problem.n_variables == 12
    # presupuesto 1 + límites 4 + b>=0 4 + s>=0 4 + lifting 4 + retorno 1
    assert a.shape == (18, 12)
    lifting = a[13:17]
    assert lifting[:, :4] == pytest.approx(np.eye(4)) and lifting[:, 4:8] == pytest.approx(
        -np.eye(4)
    )
    assert lifting[:, 8:] == pytest.approx(np.eye(4))
    assert net.problem.lower[13:17] == pytest.approx(CURRENT)
    assert net.problem.upper[13:17] == pytest.approx(CURRENT)
    buy = np.array(COSTS["BuyCost"]) / 10_000.0
    sell = np.array(COSTS["SellCost"]) / 10_000.0
    assert a[17] == pytest.approx(np.concatenate([MU, -buy / horizon, -sell / horizon]))
    assert net.problem.lower[17] == -np.inf and net.problem.upper[17] == np.inf
    target = net.lower_for_target(0.07)
    assert target[17] == 0.07 and (target[:17] == net.problem.lower[:17]).all()


def test_max_turnover_uses_lifting_even_in_gross_problems() -> None:
    """CON-005: ``½(1ᵀb + 1ᵀs) <= MaxTurnover``; el bloque de costes de ``q1`` es cero en bruto."""
    _, inputs = _inputs(spec=spec_with(max_turnover=0.25))
    gross = build_fixed_composition_problem(inputs, CostTreatment.GROSS, quadratic=True)
    a = gross.problem.A.toarray()
    assert gross.lifted and not gross.cost_in_objective
    turnover_row = a[17]
    assert turnover_row[:4].tolist() == [0.0] * 4 and set(turnover_row[4:].tolist()) == {0.5}
    assert gross.problem.upper[17] == 0.25 and gross.problem.lower[17] == -np.inf
    assert gross.unit_objective[4:].tolist() == [0.0] * 8


def test_cost_lifting_complementarity_and_ex_post_cost() -> None:
    """TC-010: con costes > 0, ``b·s = 0`` y ``c_bᵀb + c_sᵀs`` = coste ex post del modelo."""
    config, inputs = _inputs(horizon=1.5)
    net = build_fixed_composition_problem(inputs, CostTreatment.NET, quadratic=True)
    backend = OSQPBackend(config.solver)
    backend.setup(net.problem)
    backend.update(q=net.q_risk_aversion(2.0))
    result = backend.solve()
    assert result.x is not None
    x = result.x
    weights, buys, sells = x[:4], x[4:8], x[8:]
    assert np.all(np.abs(buys * sells) < 1e-9)
    assert net.lifted_cost_one_off(x) == pytest.approx(
        float(inputs.cost_model.cost_one_off(weights)), abs=1e-8
    )
    assert weights - buys + sells == pytest.approx(CURRENT, abs=1e-8)


def test_lp_variant_for_maximum_return() -> None:
    """``quadratic = False``: ``P = 0``, ``q = q1``, clase LP."""
    _, inputs = _inputs()
    lp = build_fixed_composition_problem(inputs, CostTreatment.GROSS, quadratic=False)
    assert lp.problem.problem_class is ProblemClass.LP
    assert lp.problem.P.nnz == 0 and lp.problem.q == pytest.approx(-MU)


def test_builder_rejects_unsupported_treatments() -> None:
    _, inputs = _inputs()
    with pytest.raises(FrontierError, match="POST_COST_GROSS"):
        build_fixed_composition_problem(inputs, CostTreatment.POST_COST_GROSS, quadratic=True)
    config = base_config()
    no_costs = composition_inputs(
        make_problem(MU, SIGMA, CURRENT, config, with_costs=False), config
    )
    with pytest.raises(FrontierError, match="NET exige"):
        build_fixed_composition_problem(no_costs, CostTreatment.NET, quadratic=True)
    with pytest.raises(FrontierError):
        build_fixed_composition_problem(
            no_costs, CostTreatment.GROSS, quadratic=True
        ).lifted_cost_one_off(np.zeros(4))
