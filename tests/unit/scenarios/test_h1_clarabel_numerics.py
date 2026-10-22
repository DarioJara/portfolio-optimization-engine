"""H-1 (AUDIT_BLOCK_5_3, INVESTIGATION_H1_B4): Clarabel ante diferencias de redondeo de 1 ulp.

Una instancia cónica degenerada (rotación máxima, peso máximo y límite de grupo activos a la vez)
queda en el borde de la tolerancia configurada (``1e-9``): el residuo primal se estanca por encima
de ``tol_feas`` en la iteración siguiente a la que cumple la brecha y Clarabel termina
``AlmostSolved`` (``OPTIMAL_INACCURATE``, rechazado por ``accept_inaccurate_solutions = false``)
aunque los pesos sean válidos. El resultado depende del redondeo de la CPU (orden de sumas, FMA).

Estos tests no dependen de la CPU: perturban de forma determinista los datos ``b`` y ``q`` que
se entregan a Clarabel en ``eps`` relativo (≈ lo que cambian entre CPU) y exigen que **todas**
las soluciones sean válidas y ``OPTIMAL``. Antes de la remediación (reintento en frío idéntico)
``eps = 1e-16`` daba ≈ 50 % de soluciones inválidas; el reintento con otra numérica
(``conic.retry_equilibrate``) y las mismas tolerancias las rescata.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import clarabel
import numpy as np
import pytest

from portfolio_engine.config import ConstraintOverrides, GroupLimit
from portfolio_engine.models.enums import (
    CostTreatment,
    GroupDimension,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.optimizers import clarabel_backend
from portfolio_engine.scenarios import MultiScenarioOptimizer
from tests.fixtures.block4 import four_asset_problem, scenario_definitions, with_overrides
from tests.unit.optimizers.test_clarabel_backend import _backend, _ball_problem
from tests.unit.scenarios.test_multi_scenario import CONFIG, LAMBDA, _scenarios

pytestmark = pytest.mark.unit

REPETITIONS = 12


def _h1_inputs() -> tuple[Any, Any]:
    """Problema y escenarios exactamente como en el primer test de H-1."""
    problem = four_asset_problem(CONFIG, current=[0.25] * 4)
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(0.05, None, 0.4, ()))
    definitions[2] = with_overrides(
        definitions[2],
        ConstraintOverrides(
            None, None, None, (GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.45),)
        ),
    )
    return problem, _scenarios(problem, tuple(definitions))


def _perturb_conic_data(monkeypatch: pytest.MonkeyPatch, eps: float, seed: int) -> None:
    """Perturba ``b`` y ``q`` de Clarabel en ``eps`` relativo (determinista, igual en toda CPU)."""
    original = clarabel_backend.to_conic_form
    rng = np.random.default_rng(seed)

    def perturbed(problem: Any, q: Any, lower: Any, upper: Any) -> Any:
        form = original(problem, q, lower, upper)
        return dataclasses.replace(
            form,
            b=form.b * (1 + eps * rng.standard_normal(form.b.shape)),
            q=form.q * (1 + eps * rng.standard_normal(form.q.shape)),
        )

    monkeypatch.setattr(clarabel_backend, "to_conic_form", perturbed)


@pytest.mark.parametrize("eps", [0.0, 1e-16, 1e-14, 1e-12])
def test_one_ulp_perturbations_never_invalidate_the_degenerate_worst_case(
    monkeypatch: pytest.MonkeyPatch, eps: float
) -> None:
    """Todas las soluciones son ``OPTIMAL`` y válidas, sin relajar ninguna tolerancia."""
    assert CONFIG.conic.tol_feas == CONFIG.conic.tol_gap_abs == 1e-9  # tolerancia sin relajar
    assert CONFIG.solver.accept_inaccurate_solutions is False
    problem, scenarios = _h1_inputs()
    if eps:
        _perturb_conic_data(monkeypatch, eps, seed=0)
    optimizer = MultiScenarioOptimizer(CONFIG)
    for _ in range(REPETITIONS):
        solution = optimizer.solve_worst_case(
            problem, scenarios, CostTreatment.GROSS, LAMBDA
        ).single_solution
        assert solution is not None and solution.weights is not None
        assert solution.validation is not None and not solution.validation.violations
        assert solution.status is SolverStatus.OPTIMAL, (
            solution.status,
            solution.status_source,
        )
        assert solution.is_valid_solution
        assert solution.extra("solver_t") == pytest.approx(
            solution.extra("worst_case_utility"), abs=1e-6
        )


def _spy_on_clarabel(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    captured: list[Any] = []
    real_solver = clarabel_backend.clarabel.DefaultSolver

    def spy(*args: Any) -> Any:
        captured.append(args[-1])
        return real_solver(*args)

    monkeypatch.setattr(clarabel_backend.clarabel, "DefaultSolver", spy)
    return captured


class _Stalled:
    """Resultado de Clarabel con el estado nativo cambiado (simula un estancamiento numérico)."""

    def __init__(self, raw: Any, status: str) -> None:
        self.status, self.x, self.obj_val = status, raw.x, raw.obj_val
        self.iterations, self.solve_time = raw.iterations, raw.solve_time
        self.r_prim, self.r_dual = raw.r_prim, raw.r_dual


def _stall_first_solve(backend: Any, status: str) -> None:
    solver = backend._solver
    real_solve = solver.solve

    class Wrapper:
        def solve(self) -> Any:
            return _Stalled(real_solve(), status)

    backend._solver = Wrapper()


def test_the_retry_changes_the_numerics_after_a_stall_but_not_the_tolerances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tras ``AlmostSolved`` el reintento usa ``retry_equilibrate`` con las mismas tolerancias."""
    conic = CONFIG.conic
    assert conic.retry_equilibrate != conic.equilibrate  # un reintento idéntico no sirve (H-1)
    captured = _spy_on_clarabel(monkeypatch)
    backend = _backend()
    backend.setup(_ball_problem(np.array([1.0, 2.0, 3.0, 4.0])))
    _stall_first_solve(backend, "AlmostSolved")
    first = backend.solve()
    retried = backend.cold_retry()
    assert first.status is SolverStatus.OPTIMAL_INACCURATE
    assert retried.status_source is StatusSource.CROSS_CHECK and retried.cold_retries == 1
    assert retried.status is SolverStatus.OPTIMAL  # el reintento es un Solved genuino
    primary, retry = captured[0], captured[-1]
    assert primary.equilibrate_enable is conic.equilibrate
    assert retry.equilibrate_enable is conic.retry_equilibrate
    for name in ("tol_gap_abs", "tol_gap_rel", "tol_feas", "tol_infeas_abs", "tol_infeas_rel"):
        assert getattr(retry, name) == getattr(primary, name) == getattr(conic, name)
    assert retry.max_iter == conic.max_iterations * CONFIG.solver.retry_iteration_multiplier
    assert isinstance(retry, clarabel.DefaultSettings)


def test_the_retry_after_an_iteration_limit_keeps_the_primary_numerics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El límite de iteraciones no es un estancamiento: solo se aumentan las iteraciones."""
    conic = CONFIG.conic
    captured = _spy_on_clarabel(monkeypatch)
    backend = _backend(max_iterations=2)
    backend.setup(_ball_problem(np.array([1.0, 2.0, 3.0, 4.0])))
    first = backend.solve()
    retried = backend.cold_retry()
    assert first.status is SolverStatus.MAX_ITERATIONS
    assert retried.status_source is StatusSource.CROSS_CHECK and retried.iterations > 0
    assert captured[-1].equilibrate_enable is conic.equilibrate
    assert captured[-1].max_iter == 2 * CONFIG.solver.retry_iteration_multiplier


def test_a_retry_that_ends_almost_solved_is_still_reported_inaccurate() -> None:
    """La remediación no promueve estados: ``AlmostSolved`` sigue siendo ``OPTIMAL_INACCURATE``."""
    from portfolio_engine.optimizers.status import map_clarabel_status

    assert map_clarabel_status("AlmostSolved") is SolverStatus.OPTIMAL_INACCURATE
    assert map_clarabel_status("Solved") is SolverStatus.OPTIMAL
