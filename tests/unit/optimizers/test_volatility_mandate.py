"""F-01 (AUDIT_BLOCK_4): ``PortfolioSpec.volatility_limit`` nunca se ignora.

Cada estrategia que no optimiza el límite (CVaR con límite, robusta, peor caso, BaseWithStress)
debe **cumplirlo** (cono ``‖Lᵀw‖ <= σ_max`` con ``Σ`` no diagonal) o **rechazar** el problema de
forma explícita; el ``AdvancedSolutionValidator`` recalcula la volatilidad desde los pesos. Oráculos
independientes: SLSQP sobre la definición matemática y búsqueda aleatoria factible.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from scipy.optimize import minimize

from portfolio_engine.config import ConstraintOverrides
from portfolio_engine.exceptions import ScenarioError
from portfolio_engine.frontiers import FrontierProblem, StrategyOptimizer
from portfolio_engine.metrics import conditional_value_at_risk, portfolio_losses
from portfolio_engine.models.cvar import ReturnScenarioSet, build_return_scenario_set
from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    CVaRSource,
    MuUncertaintyKind,
    ScenarioWeighting,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.optimizers.formulations import robust as robust_module
from portfolio_engine.optimizers.formulations.robust import MuUncertaintySet
from portfolio_engine.scenarios import MultiScenarioOptimizer, ScenarioEngine, ScenarioSet
from tests.fixtures.block4 import (
    CORR4,
    MU4,
    VOL4,
    four_asset_problem,
    scenario_definitions,
    with_overrides,
)
from tests.fixtures.problems import base_config, cov_from_vol_corr, spec_with

pytestmark = pytest.mark.unit

CONFIG = base_config()
SIGMA4 = cov_from_vol_corr(VOL4, CORR4)  # no diagonal: correlaciones 0,1…0,4
LAMBDA = 3.0
TREATMENT = CostTreatment.GROSS
TOLERANCE = 1e-7


def _vol(weights: np.ndarray | None, sigma: np.ndarray = SIGMA4) -> float:
    assert weights is not None
    return float(np.sqrt(weights @ sigma @ weights))


def _min_vol() -> float:
    result = minimize(
        lambda w: float(w @ SIGMA4 @ w),
        np.full(4, 0.25),
        bounds=[(0.0, 1.0)] * 4,
        constraints=[{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}],
        method="SLSQP",
        options={"ftol": 1e-15},
    )
    return float(np.sqrt(result.fun))


def _cvar_scenarios() -> ReturnScenarioSet:
    returns = np.random.default_rng(0).multivariate_normal(MU4 / 252, SIGMA4 / 252, size=400)
    ids = four_asset_problem(CONFIG).risk_model.asset_ids
    return build_return_scenario_set(
        ids, returns, CVaRSource.HISTORICAL, ScenarioWeighting.EQUAL, None, 1e-9
    )


def _box() -> MuUncertaintySet:
    return MuUncertaintySet(MuUncertaintyKind.BOX, half_width=np.full(4, 0.01))


def _scenario_set(problem: FrontierProblem, definitions=None) -> ScenarioSet:  # type: ignore[no-untyped-def]
    return ScenarioEngine(CONFIG).build(
        problem.risk_model,
        problem.universe,
        problem.costs,
        CONFIG.constraints,
        problem.spec,
        definitions or scenario_definitions(),
    )


def _single(result: Any) -> StrategyResult:
    solution = result.single_solution
    assert solution is not None
    return solution  # type: ignore[no-any-return]


Runner = Callable[[FrontierProblem], StrategyResult]


def _cvar(problem: FrontierProblem) -> StrategyResult:
    return StrategyOptimizer(CONFIG).cvar(
        problem, TREATMENT, _cvar_scenarios(), CVaRObjective.MAX_RETURN_WITH_LIMIT, max_cvar=0.5
    )


def _robust(problem: FrontierProblem) -> StrategyResult:
    return StrategyOptimizer(CONFIG).robust(problem, TREATMENT, LAMBDA, mu_set=_box())


def _worst_case(problem: FrontierProblem) -> StrategyResult:
    return _single(
        MultiScenarioOptimizer(CONFIG).solve_worst_case(
            problem, _scenario_set(problem), TREATMENT, LAMBDA
        )
    )


def _base_with_stress(problem: FrontierProblem) -> StrategyResult:
    return _single(
        MultiScenarioOptimizer(CONFIG).solve_base_with_stress(
            problem, _scenario_set(problem), TREATMENT, LAMBDA
        )
    )


RUNNERS = [
    pytest.param(_cvar, id="CVAR_LIMITED"),
    pytest.param(_robust, id="ROBUST"),
    pytest.param(_worst_case, id="WORST_CASE"),
    pytest.param(_base_with_stress, id="BASE_WITH_STRESS"),
]


@pytest.mark.parametrize("run", RUNNERS)
def test_a_binding_mandate_is_enforced_and_independently_validated(run: Runner) -> None:
    """Con el límite vinculante la volatilidad recalculada lo cumple (y lo alcanza)."""
    free = run(four_asset_problem(CONFIG))
    assert free.is_valid_solution and _vol(free.weights) > _min_vol() + 0.002
    limit = 0.5 * (_min_vol() + _vol(free.weights))
    result = run(four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit)))
    assert result.is_valid_solution and result.status is SolverStatus.OPTIMAL
    assert _vol(result.weights) <= limit + TOLERANCE
    assert _vol(result.weights) == pytest.approx(limit, abs=1e-6)  # el límite está activo
    assert result.validation is not None and "VOLATILITY_LIMIT" in result.validation.checks
    assert result.solver_names == ("CLARABEL",)  # un cono: nunca OSQP/HiGHS


@pytest.mark.parametrize("run", RUNNERS)
def test_a_slack_mandate_leaves_the_solution_unchanged(run: Runner) -> None:
    free = run(four_asset_problem(CONFIG))
    assert free.weights is not None
    slack = run(
        four_asset_problem(CONFIG, spec=spec_with(volatility_limit=2.0 * _vol(free.weights)))
    )
    assert slack.is_valid_solution and slack.weights is not None
    np.testing.assert_allclose(slack.weights, free.weights, atol=1e-5)


@pytest.mark.parametrize("run", RUNNERS)
def test_a_mandate_below_the_minimum_volatility_is_rejected_before_the_solver(run: Runner) -> None:
    limit = 0.5 * _min_vol()
    result = run(four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit)))
    assert not result.is_valid_solution and result.weights is None
    assert result.status is SolverStatus.INFEASIBLE
    assert result.status_source is StatusSource.PRE_SOLVER_CHECK
    assert any("VOLATILITY_LIMIT" in note for note in result.notes)


@pytest.mark.parametrize("run", RUNNERS)
def test_a_mandate_between_the_minimum_and_a_binding_cap_is_feasible_at_the_minimum(
    run: Runner,
) -> None:
    """Límite apenas por encima de σ_min: la solución se acerca a la cartera de mínima varianza."""
    limit = _min_vol() * 1.001
    result = run(four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit)))
    assert result.is_valid_solution and _vol(result.weights) <= limit + TOLERANCE


def _slsqp_worst_case(limit: float) -> np.ndarray:
    problem = four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit))
    scenarios = _scenario_set(problem)
    data = [(np.array(s.risk_model.mu), np.array(s.risk_model.sigma)) for s in scenarios.scenarios]
    constraints: list[dict[str, Any]] = [
        {"type": "eq", "fun": lambda x: float(np.sum(x[:4]) - 1.0)},
        {"type": "ineq", "fun": lambda x: limit**2 - float(x[:4] @ SIGMA4 @ x[:4])},
    ]
    for mu, sigma in data:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda x, mu=mu, sigma=sigma: float(
                    mu @ x[:4] - LAMBDA * x[:4] @ sigma @ x[:4] - x[4]
                ),
            }
        )
    start = np.concatenate([np.full(4, 0.25), [-0.05]])
    result = minimize(
        lambda x: -x[4],
        start,
        bounds=[(0.0, 1.0)] * 4 + [(None, None)],
        constraints=constraints,
        method="SLSQP",
        options={"ftol": 1e-15, "maxiter": 5000},
    )
    assert result.success, result.message
    return np.asarray(result.x[:4])


def test_the_worst_case_with_a_mandate_matches_the_slsqp_epigraph_oracle() -> None:
    free = _worst_case(four_asset_problem(CONFIG))
    limit = 0.5 * (_min_vol() + _vol(free.weights))
    result = _worst_case(four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit)))
    assert result.weights is not None
    np.testing.assert_allclose(result.weights, _slsqp_worst_case(limit), atol=1e-4)


def test_the_robust_solution_with_a_mandate_matches_slsqp() -> None:
    """Caja uniforme con cartera long-only: ``U = μᵀw − δ·1ᵀw − λwᵀΣw`` con ``σ(w) <= σ_max``."""
    free = _robust(four_asset_problem(CONFIG))
    limit = 0.5 * (_min_vol() + _vol(free.weights))
    oracle = minimize(
        lambda w: -float((MU4 - 0.01) @ w - LAMBDA * w @ SIGMA4 @ w),
        np.full(4, 0.25),
        bounds=[(0.0, 1.0)] * 4,
        constraints=[
            {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},
            {"type": "ineq", "fun": lambda w: limit**2 - float(w @ SIGMA4 @ w)},
        ],
        method="SLSQP",
        options={"ftol": 1e-15, "maxiter": 2000},
    )
    result = _robust(four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit)))
    assert result.weights is not None
    np.testing.assert_allclose(result.weights, oracle.x, atol=1e-4)


def test_the_cvar_with_a_mandate_is_not_beaten_by_any_random_feasible_portfolio() -> None:
    scenarios = _cvar_scenarios()
    free = _cvar(four_asset_problem(CONFIG))
    limit = 0.5 * (_min_vol() + _vol(free.weights))
    result = _cvar(four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit)))
    assert result.weights is not None and result.is_valid_solution

    def cvar_of(w: np.ndarray) -> float:
        return conditional_value_at_risk(
            portfolio_losses(scenarios.returns, w), scenarios.weights, CONFIG.cvar.confidence_level
        )

    assert cvar_of(result.weights) <= 0.5 + TOLERANCE
    draws = np.random.default_rng(1).dirichlet(np.ones(4), size=20000)
    feasible = [w for w in draws if _vol(w) <= limit and cvar_of(w) <= 0.5]
    assert feasible  # el oráculo no es vacío
    assert float(MU4 @ result.weights) >= max(float(MU4 @ w) for w in feasible) - 1e-6


@pytest.mark.parametrize(
    ("module_path", "name", "run"),
    [
        ("portfolio_engine.frontiers.strategy_optimizer", "build_cvar_problem", _cvar),
        ("portfolio_engine.frontiers.strategy_optimizer", "build_robust_problem", _robust),
        ("portfolio_engine.scenarios.multi_scenario", "build_worst_case_problem", _worst_case),
        (
            "portfolio_engine.scenarios.multi_scenario",
            "build_base_with_stress_problem",
            _base_with_stress,
        ),
    ],
)
def test_a_formulation_that_drops_the_mandate_is_caught_by_the_validator(
    monkeypatch: pytest.MonkeyPatch, module_path: str, name: str, run: Runner
) -> None:
    """Mutación: si la formulación olvida el cono, el validador independiente lo rechaza."""
    free = run(four_asset_problem(CONFIG))
    limit = 0.5 * (_min_vol() + _vol(free.weights))
    module = __import__(module_path, fromlist=[name])
    original = getattr(module, name)

    def without_cap(*args: Any, **kwargs: Any) -> Any:
        kwargs["volatility_cap"] = None
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, without_cap)
    result = run(four_asset_problem(CONFIG, spec=spec_with(volatility_limit=limit)))
    assert _vol(result.weights) > limit + 1e-4  # la formulación mutilada sí lo violaría…
    assert not result.is_valid_solution  # …y nunca se presenta como válida
    assert result.validation is not None and not result.validation.is_valid


def test_robust_with_a_mandate_and_covariance_uncertainty_keeps_both() -> None:
    """Σ escalada (cono) y mandato (cono) a la vez: ambos se cumplen (SOCP con dos conos)."""
    problem = four_asset_problem(CONFIG, spec=spec_with(volatility_limit=0.12))
    result = StrategyOptimizer(CONFIG).robust(
        problem, TREATMENT, LAMBDA, mu_set=_box(), covariance_scale_max=1.5
    )
    assert result.is_valid_solution and _vol(result.weights) <= 0.12 + TOLERANCE
    worst = result.extra("worst_case_utility")
    nominal = result.extra("nominal_utility")
    assert worst < nominal


def test_the_robust_formulation_module_exposes_the_cap_argument() -> None:
    import inspect

    assert "volatility_cap" in inspect.signature(robust_module.build_robust_problem).parameters


def test_incompatible_scenario_constraints_with_a_mandate_are_rejected_not_ignored() -> None:
    """Escenarios con restricciones incompatibles + mandato: error explícito o inviabilidad."""
    problem = four_asset_problem(CONFIG, spec=spec_with(volatility_limit=0.2))
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(None, 0.6, None, ()))
    definitions[2] = with_overrides(definitions[2], ConstraintOverrides(None, None, 0.3, ()))
    scenarios = _scenario_set(problem, tuple(definitions))
    for solver in (
        MultiScenarioOptimizer(CONFIG).solve_worst_case,
        MultiScenarioOptimizer(CONFIG).solve_base_with_stress,
    ):
        with pytest.raises(ScenarioError, match="incompatibles"):
            solver(problem, scenarios, TREATMENT, LAMBDA)
    infeasible = list(scenario_definitions())
    infeasible[1] = with_overrides(infeasible[1], ConstraintOverrides(None, None, 0.2, ()))
    for solver in (
        MultiScenarioOptimizer(CONFIG).solve_worst_case,
        MultiScenarioOptimizer(CONFIG).solve_base_with_stress,
    ):
        solution = _single(
            solver(problem, _scenario_set(problem, tuple(infeasible)), TREATMENT, LAMBDA)
        )
        assert solution.status is SolverStatus.INFEASIBLE and not solution.is_valid_solution
        assert solution.weights is None


def test_net_treatment_also_honours_the_mandate() -> None:
    problem = four_asset_problem(CONFIG, spec=spec_with(volatility_limit=0.10))
    result = StrategyOptimizer(CONFIG).robust(problem, CostTreatment.NET, LAMBDA, mu_set=_box())
    assert result.is_valid_solution and _vol(result.weights) <= 0.10 + TOLERANCE
