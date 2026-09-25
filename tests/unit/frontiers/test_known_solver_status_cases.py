"""SOL-002, VAL-001 (hallazgo B2, separado): casos deterministas del fallo intermitente de
``tests/property/test_invariants.py::test_every_frontier_point_satisfies_the_financial_invariants``.

**No resuelve el hallazgo**: el hallazgo se remedió después en ``fix/b2-numerical-f3`` (recuperación
numérica; ver ``REMEDIATION_F3_NUMERICAL.md`` y ``test_numerical_recovery.py``, que exige fronteras
completamente válidas). Estos tests se conservan sin cambios y siguen pasando (un punto que
``numerical_recovery`` no recupere seguiría clasificado como aquí). Fija, con las siete
instancias reproducibles ``(n, semilla)`` del generador del test de propiedades, lo que sí es cierto
y distingue cuatro situaciones sin relajar ninguna restricción económica:

* **problema numérico del solver:** el punto no es ``OPTIMAL`` (``INFEASIBLE``, ``NUMERICAL_ERROR``,
  ``MAX_ITERATIONS`` u ``OPTIMAL_INACCURATE``);
* **solución verdaderamente infactible:** un retorno objetivo por encima del máximo alcanzable
  (oráculo LP independiente con HiGHS); ninguno de estos casos lo es;
* **solución factible que no converge:** el oráculo demuestra ``objetivo < máximo alcanzable``;
* **estado reportado correctamente:** ningún punto no óptimo se cuenta como válido, y los
  ``OPTIMAL_INACCURATE`` conservan su validación independiente.

Los tests no exigen que el fallo ocurra (si el solver mejora, siguen pasando).
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import linprog

from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod, SolverStatus
from tests.fixtures.problems import base_config, make_problem

pytestmark = pytest.mark.unit

#: Instancias ``(n, semilla)`` reproducidas por exploración determinista (4.800 casos, 10 fallos).
KNOWN = [(2, 19), (3, 67), (2, 84), (2, 89), (2, 159), (2, 184), (2, 193)]
NON_OPTIMAL = {
    SolverStatus.INFEASIBLE,
    SolverStatus.NUMERICAL_ERROR,
    SolverStatus.MAX_ITERATIONS,
    SolverStatus.OPTIMAL_INACCURATE,
}
CONFIG = base_config()
ENGINE = ContinuousFrontierEngine(CONFIG)
HORIZON = CONFIG.optimization_horizon_years


def _instance(n: int, seed: int):  # type: ignore[no-untyped-def]
    """Mismo generador que ``tests/property/test_invariants.py::frontier_problems``."""
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, n)) * 0.1
    sigma = factor @ factor.T + np.diag(rng.uniform(0.01, 0.05, n))
    mu = rng.uniform(0.02, 0.15, n)
    raw = rng.uniform(0.05, 1.0, n)
    current = raw / raw.sum()
    buy = rng.uniform(1.0, 200.0, n)
    sell = rng.uniform(1.0, 200.0, n)
    problem = make_problem(
        mu,
        sigma,
        current.tolist(),
        CONFIG,
        universe_overrides={
            "MaxWeight": [1.0] * n,
            "BuyCost": buy.tolist(),
            "SellCost": sell.tolist(),
        },
    )
    return problem, mu, current, buy, sell


def _max_achievable(treatment, mu, current, buy, sell) -> float:  # type: ignore[no-untyped-def]
    """Retorno máximo alcanzable con un LP independiente (bruto: ``max μ``; neto: con costes)."""
    if treatment is not CostTreatment.NET:
        return float(mu.max())
    n = mu.shape[0]
    cost = np.concatenate([-mu, buy / 1e4 / HORIZON, sell / 1e4 / HORIZON])  # bps → fracción
    a_eq = np.zeros((n + 1, 3 * n))
    b_eq = np.zeros(n + 1)
    for i in range(n):
        a_eq[i, i], a_eq[i, n + i], a_eq[i, 2 * n + i], b_eq[i] = 1.0, -1.0, 1.0, current[i]
    a_eq[n, :n], b_eq[n] = 1.0, 1.0
    bounds = [(0.0, 1.0)] * n + [(0.0, None)] * (2 * n)
    result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert result.status == 0
    return float(-result.fun)


@pytest.mark.parametrize(("n", "seed"), KNOWN)
def test_every_non_valid_point_is_a_correctly_reported_solver_status_of_a_feasible_target(
    n: int, seed: int
) -> None:
    problem, mu, current, buy, sell = _instance(n, seed)
    for treatment in CostTreatment:
        result = ENGINE.solve(problem, treatment, FrontierMethod.TARGET_RETURN_GRID)
        assert result.pre_check_feasible and result.points
        best = _max_achievable(treatment, mu, current, buy, sell)
        for point in result.points:
            if point.is_valid_solution:
                assert point.status is SolverStatus.OPTIMAL
                assert point.validation is not None and point.validation.is_valid
                continue
            # estado reportado correctamente: nunca válido y siempre un estado no óptimo explícito
            assert point.status in NON_OPTIMAL, (n, seed, treatment, point.status)
            # ni una sola es verdaderamente infactible: el objetivo está por debajo del máximo
            assert point.target_return is not None
            assert point.target_return < best, (n, seed, treatment, point.target_return, best)
            if point.status is SolverStatus.OPTIMAL_INACCURATE:
                assert point.validation is not None and point.validation.is_valid


def test_the_grid_never_asks_for_more_than_the_achievable_maximum() -> None:
    """La malla no pide imposibles (la infactibilidad verdadera: ``test_target_return_grid``)."""
    problem, mu, current, buy, sell = _instance(2, 84)
    best = _max_achievable(CostTreatment.GROSS, mu, current, buy, sell)
    assert best == pytest.approx(mu.max())
    # el mayor objetivo de la malla nunca supera el máximo alcanzable (no se piden imposibles)
    result = ENGINE.solve(problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID)
    assert max(p.target_return for p in result.points if p.target_return is not None) < best


def test_the_economic_constraints_are_untouched_by_these_cases() -> None:
    """Sin relajar nada: las tolerancias de solver y validación son las de ejemplo."""
    assert CONFIG.solver.eps_abs == 1e-9 and CONFIG.solver.eps_rel == 1e-9
    assert CONFIG.solver.accept_inaccurate_solutions is False
    assert CONFIG.solver.constraint_tolerance == 1e-7
