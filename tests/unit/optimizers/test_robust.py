"""ROB-002..006: optimización robusta (peor caso de conjuntos de incertidumbre), con oráculos
independientes: el motor de utilidad del Bloque 2 con datos modificados, búsqueda aleatoria
factible y fórmulas cerradas del peor caso (:mod:`portfolio_engine.metrics.robust_metric`).

No es una reducción arbitraria de ``μ``: el peor caso de cada conjunto es exacto y la solución
robusta maximiza la utilidad del peor caso, no la nominal.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest
from scipy.stats import chi2

from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.frontiers import ContinuousFrontierEngine, StrategyOptimizer
from portfolio_engine.metrics.robust_metric import (
    worst_case_box_return,
    worst_case_ellipsoid_return,
    worst_case_variance,
)
from portfolio_engine.models.enums import (
    CostTreatment,
    ExpectedReturnMode,
    FrontierMethod,
    MuUncertaintyKind,
    OptimalityClaim,
    ProblemClass,
    StrategyID,
)
from portfolio_engine.models.risk_model import ExpectedReturns, RiskModel
from portfolio_engine.optimizers.formulations.conic import factor_covariance
from portfolio_engine.optimizers.formulations.robust import MuUncertaintySet, build_robust_problem
from tests.fixtures.block4 import CORR4, MU4, VOL4, four_asset_problem
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem

pytestmark = pytest.mark.unit

CONFIG = base_config()
SIGMA4 = cov_from_vol_corr(VOL4, CORR4)
LAMBDA = 3.0
DELTA = np.array([0.02, 0.03, 0.05, 0.01])


def _utility_optimum(mu: np.ndarray, sigma: np.ndarray, cap: float = 1.0) -> np.ndarray:
    """Óptimo de ``μᵀw − λ wᵀΣw`` con el motor del Bloque 2 (oráculo de referencia)."""
    problem = make_problem(
        mu, sigma, [0.25] * 4, CONFIG, universe_overrides={"MaxWeight": [cap] * 4}
    )
    session = ContinuousFrontierEngine(CONFIG).open_session(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    point = session.solve_risk_aversion(1.0 / LAMBDA, strategy=StrategyID.FRONTIER_POINT)
    assert point.weights is not None
    return np.asarray(point.weights)


def _box_utility(w: np.ndarray, delta: np.ndarray = DELTA, scale: float = 1.0) -> float:
    return worst_case_box_return(w, MU4, delta) - LAMBDA * worst_case_variance(w, [scale * SIGMA4])


def test_box_uncertainty_on_a_long_only_portfolio_is_exactly_the_lower_corner() -> None:
    """P15: con ``w >= 0`` el peor caso es ``(μ̂ − δ)ᵀw``: coincide con la utilidad de ``μ̂ − δ``."""
    result = StrategyOptimizer(CONFIG).robust(
        four_asset_problem(CONFIG),
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    assert result.is_valid_solution and result.weights is not None
    np.testing.assert_allclose(result.weights, _utility_optimum(MU4 - DELTA, SIGMA4), atol=1e-6)
    assert result.strategy_id is StrategyID.ROBUST and result.solver_names == ("OSQP",)  # QP lineal
    assert result.extra("worst_case_utility") == pytest.approx(
        _box_utility(result.weights), abs=1e-12
    )
    nominal = _utility_optimum(MU4, SIGMA4)
    assert _box_utility(result.weights) > _box_utility(nominal) + 1e-6  # más robusto que el nominal
    assert float(MU4 @ nominal - LAMBDA * nominal @ SIGMA4 @ nominal) > result.extra(
        "nominal_utility"
    )  # type: ignore[operator]
    assert not np.allclose(result.weights, nominal, atol=1e-3)


def test_the_robust_solution_beats_every_random_portfolio_on_the_worst_case_utility() -> None:
    problem = four_asset_problem(CONFIG, max_weight=0.6)
    result = StrategyOptimizer(CONFIG).robust(
        problem,
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    assert result.weights is not None
    best = _box_utility(result.weights)
    rng = np.random.default_rng(5)
    candidates = rng.dirichlet(np.ones(4), size=40000)
    candidates = candidates[candidates.max(axis=1) <= 0.6]
    assert candidates.shape[0] > 5000
    assert max(_box_utility(w) for w in candidates[:5000]) <= best + 1e-10


def test_box_uncertainty_with_short_positions_uses_absolute_value_variables() -> None:
    """Con cotas inferiores negativas ``min μᵀw = μ̂ᵀw − δᵀ|w|``: se usan ``a >= |w|``."""
    config = base_config(constraints={"long_only": False})
    problem = make_problem(
        MU4,
        SIGMA4,
        [0.25] * 4,
        config,
        universe_overrides={"MinWeight": [-0.3] * 4, "MaxWeight": [0.8] * 4},
    )
    result = StrategyOptimizer(config).robust(
        problem,
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    assert result.is_valid_solution and result.weights is not None
    context, _ = StrategyOptimizer(config).prepare(problem, CostTreatment.GROSS)
    assert context is not None and float(context.compiled.lower.min()) < 0.0
    extended, _ = build_robust_problem(
        context.inputs,
        CostTreatment.GROSS,
        LAMBDA,
        MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    assert "abs_w" in extended.roles  # a >= |w| solo cuando hay cotas inferiores negativas
    best = _box_utility(result.weights)
    rng = np.random.default_rng(8)
    raw = rng.uniform(-0.3, 0.8, size=(60000, 4))
    raw = raw / raw.sum(axis=1, keepdims=True)
    feasible = raw[(raw.min(axis=1) >= -0.3) & (raw.max(axis=1) <= 0.8)]
    assert feasible.shape[0] > 1000
    assert max(_box_utility(w) for w in feasible) <= best + 1e-9


def test_ellipsoidal_uncertainty_is_a_socp_solved_by_clarabel_and_beats_the_nominal_solution() -> (
    None
):
    """P16: ``min μᵀw = μ̂ᵀw − κ‖Ω^{½}w‖``: SOCP; la solución robusta gana en el peor caso."""
    omega = 0.05 * SIGMA4
    radius = 1.7
    mu_set = MuUncertaintySet(
        MuUncertaintyKind.ELLIPSOIDAL,
        radius=radius,
        omega_factor=factor_covariance(omega, CONFIG.conic),
        omega=omega,
    )
    problem = four_asset_problem(CONFIG, max_weight=0.7)
    optimizer = StrategyOptimizer(CONFIG)
    result = optimizer.robust(problem, CostTreatment.GROSS, LAMBDA, mu_set=mu_set)
    nominal = optimizer.robust(
        problem,
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.NONE),
        covariance_scale_max=1.0,  # sin incertidumbre efectiva: utilidad nominal como referencia
    )
    assert result.is_valid_solution and nominal.is_valid_solution
    assert result.solver_names == ("CLARABEL",)
    assert result.weights is not None and nominal.weights is not None

    def value(w: np.ndarray) -> float:
        return worst_case_ellipsoid_return(w, MU4, omega, radius) - LAMBDA * float(w @ SIGMA4 @ w)

    assert result.extra("worst_case_utility") == pytest.approx(value(result.weights), abs=1e-12)
    assert value(result.weights) > value(nominal.weights) + 1e-6
    rng = np.random.default_rng(2)
    candidates = rng.dirichlet(np.ones(4), size=30000)
    candidates = candidates[candidates.max(axis=1) <= 0.7]
    assert max(value(w) for w in candidates[:4000]) <= value(result.weights) + 1e-9


def test_a_zero_radius_ellipsoid_reduces_to_the_nominal_utility() -> None:
    omega = 0.05 * SIGMA4
    mu_set = MuUncertaintySet(
        MuUncertaintyKind.ELLIPSOIDAL,
        radius=0.0,
        omega_factor=factor_covariance(omega, CONFIG.conic),
        omega=omega,
    )
    result = StrategyOptimizer(CONFIG).robust(
        four_asset_problem(CONFIG), CostTreatment.GROSS, LAMBDA, mu_set=mu_set
    )
    assert result.weights is not None
    np.testing.assert_allclose(result.weights, _utility_optimum(MU4, SIGMA4), atol=1e-6)


def test_covariance_uncertainty_is_the_utility_with_the_worst_scaled_covariance() -> None:
    """P17: ``{aΣ : a ∈ [1, s]}`` ⇒ peor caso ``sΣ``: coincide con la utilidad con ``Σ' = sΣ``."""
    scale = 1.8
    result = StrategyOptimizer(CONFIG).robust(
        four_asset_problem(CONFIG),
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.NONE),
        covariance_scale_max=scale,
    )
    assert result.is_valid_solution and result.weights is not None
    np.testing.assert_allclose(result.weights, _utility_optimum(MU4, scale * SIGMA4), atol=1e-5)
    assert result.solver_names == ("CLARABEL",)  # epígrafe + cono rotado
    assert result.extra("worst_case_utility") == pytest.approx(
        float(MU4 @ result.weights)
        - LAMBDA * scale * float(result.weights @ SIGMA4 @ result.weights),
        abs=1e-9,
    )
    # una covarianza más pesimista reduce el riesgo asumido (menos varianza nominal)
    baseline = _utility_optimum(MU4, SIGMA4)
    assert float(result.weights @ SIGMA4 @ result.weights) < float(baseline @ SIGMA4 @ baseline)


def test_mu_and_covariance_uncertainty_combine() -> None:
    result = StrategyOptimizer(CONFIG).robust(
        four_asset_problem(CONFIG, max_weight=0.6),
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
        covariance_scale_max=1.5,
    )
    assert result.is_valid_solution and result.weights is not None
    best = _box_utility(result.weights, scale=1.5)
    assert result.extra("worst_case_utility") == pytest.approx(best, abs=1e-9)
    rng = np.random.default_rng(4)
    candidates = rng.dirichlet(np.ones(4), size=30000)
    candidates = candidates[candidates.max(axis=1) <= 0.6]
    assert max(_box_utility(w, scale=1.5) for w in candidates[:4000]) <= best + 1e-9


def test_robust_optimization_without_any_uncertainty_set_is_rejected_not_relabelled() -> None:
    """Una utilidad nominal no se presenta como robusta."""
    with pytest.raises(UnsupportedCombinationError, match="sin ningún conjunto"):
        StrategyOptimizer(CONFIG).robust(four_asset_problem(CONFIG), CostTreatment.GROSS, LAMBDA)
    with pytest.raises(UnsupportedCombinationError, match="risk_aversion"):
        StrategyOptimizer(CONFIG).robust(
            four_asset_problem(CONFIG),
            CostTreatment.GROSS,
            -1.0,
            mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
        )


def test_uncertainty_sets_are_derived_from_the_declared_configuration() -> None:
    """``[robust]``: caja ``δ_i = z·√(Σ_ii/años)`` y elipsoide ``κ² = χ²_n(confianza)``."""
    box = base_config(robust={"mu_uncertainty": MuUncertaintyKind.BOX, "box_z": 1.5})
    problem = four_asset_problem(box)
    years = problem.risk_model.covariance.n_observations / box.returns.trading_days_per_year
    optimizer = StrategyOptimizer(box)
    context, _ = optimizer.prepare(problem, CostTreatment.GROSS)
    assert context is not None
    derived = optimizer._mu_set(problem, context.inputs)
    assert derived.half_width is not None
    np.testing.assert_allclose(
        derived.half_width, 1.5 * np.sqrt(np.diag(SIGMA4) / years), rtol=1e-10
    )
    ellipsoid = base_config(
        robust={"mu_uncertainty": MuUncertaintyKind.ELLIPSOIDAL, "ellipsoid_confidence": 0.9}
    )
    derived = StrategyOptimizer(ellipsoid)._mu_set(problem, context.inputs)
    assert derived.radius == pytest.approx(math.sqrt(float(chi2.ppf(0.9, 4))))
    assert derived.omega is not None
    np.testing.assert_allclose(derived.omega, SIGMA4 / years, rtol=1e-10)
    result = StrategyOptimizer(box).robust(problem, CostTreatment.GROSS, LAMBDA)
    assert result.is_valid_solution and result.notes[0] == "BOX"


def test_sampling_error_sets_are_refused_for_an_external_alpha() -> None:
    """El error de muestreo no describe la incertidumbre de un alpha externo (ROB, honestidad)."""
    box = base_config(robust={"mu_uncertainty": MuUncertaintyKind.BOX, "box_z": 1.0})
    internal = four_asset_problem(box)
    base = internal.risk_model
    external_returns = ExpectedReturns(
        base.asset_ids, base.mu, ExpectedReturnMode.EXTERNAL_ALPHA, "EXTERNAL_ALPHA"
    )
    problem = dataclasses.replace(internal, risk_model=RiskModel(external_returns, base.covariance))
    assert problem.risk_model.expected_returns.is_external_alpha
    with pytest.raises(UnsupportedCombinationError, match="alpha externo"):
        StrategyOptimizer(box).robust(problem, CostTreatment.GROSS, LAMBDA)
    # con un conjunto explícito sí es posible
    explicit = StrategyOptimizer(CONFIG).robust(
        problem,
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    assert explicit.is_valid_solution


def test_formulation_classes_follow_their_mathematical_structure() -> None:
    problem = four_asset_problem(CONFIG)
    context, _ = StrategyOptimizer(CONFIG).prepare(problem, CostTreatment.GROSS)
    assert context is not None
    factor = factor_covariance(context.inputs.sigma, CONFIG.conic)
    box, _ = build_robust_problem(
        context.inputs,
        CostTreatment.GROSS,
        LAMBDA,
        MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    assert box.problem.problem_class is ProblemClass.QP
    scaled, _ = build_robust_problem(
        context.inputs,
        CostTreatment.GROSS,
        LAMBDA,
        MuUncertaintySet(MuUncertaintyKind.NONE),
        (factor,),
    )
    assert scaled.problem.problem_class is ProblemClass.SOCP and scaled.role("tau") == 4
    with pytest.raises(UnsupportedCombinationError, match="half_width"):
        MuUncertaintySet(MuUncertaintyKind.BOX)
    with pytest.raises(UnsupportedCombinationError, match="radius"):
        MuUncertaintySet(MuUncertaintyKind.ELLIPSOIDAL, radius=1.0)
    with pytest.raises(UnsupportedCombinationError, match="NONE"):
        MuUncertaintySet(MuUncertaintyKind.NONE, radius=1.0)


def test_net_costs_are_part_of_the_robust_objective() -> None:
    problem = four_asset_problem(
        CONFIG,
        current=[0.7, 0.1, 0.1, 0.1],
        universe_overrides={"BuyCost": [300.0] * 4, "SellCost": [400.0] * 4},
    )
    optimizer = StrategyOptimizer(CONFIG)
    net = optimizer.robust(
        problem,
        CostTreatment.NET,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    gross = optimizer.robust(
        problem,
        CostTreatment.GROSS,
        LAMBDA,
        mu_set=MuUncertaintySet(MuUncertaintyKind.BOX, half_width=DELTA),
    )
    assert net.weights is not None and gross.weights is not None
    assert (
        np.abs(net.weights - np.array([0.7, 0.1, 0.1, 0.1])).sum()
        < np.abs(gross.weights - np.array([0.7, 0.1, 0.1, 0.1])).sum()
    )
    assert net.optimality_claim is OptimalityClaim.CONVEX_GLOBAL
