"""SOL-002, OPT-005 (cierre de RF-01 de AUDIT_F3_POST_MERGE): NET con retornos casi idénticos.

Cuando el bloque de pesos centrado es pequeño pero supera ``√eps`` del máximo de la fila, la
normalización conserva la escala sobre los pesos (regla F-3 validada) y los coeficientes de
compra/venta quedan muy inflados: la recuperación es correcta pero puede consumir una proporción
elevada del presupuesto de iteraciones de reintento. Este test fija el comportamiento correcto
(recuperación válida, traza completa, sin exceder el presupuesto configurado) **sin** fijar tiempos
en segundos ni un número de iteraciones concreto, y sin cambiar la regla de normalización.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.frontiers.numerical_recovery import NumericalRecovery
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    ProblemClass,
    RecoveryOutcome,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.solution import SolveResult
from tests.fixtures import near_degenerate as nd
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
ENGINE = ContinuousFrontierEngine(CONFIG)
HORIZON = CONFIG.optimization_horizon_years
SIGMA = np.diag([0.02, 0.04])
CURRENT = np.array([0.7, 0.3])
#: Diferencias de retorno entre los dos activos (banda intermedia de RF-01).
SPREADS = [1e-9, 2e-9, 5e-9]
#: Holgura del objetivo respecto de mantener la cartera actual (retorno neto de no operar).
TARGET_MARGIN = 1e-4


def _first_failure() -> SolveResult:
    """``INFEASIBLE`` inicial inducido de OSQP (no se ha observado espontáneamente)."""
    return SolveResult(
        status=SolverStatus.INFEASIBLE,
        native_status="induced primal infeasible",
        status_source=StatusSource.SOLVER,
        solver_name="OSQP",
        solver_version="test",
        problem_class=ProblemClass.QP,
        x=None,
        y=None,
        objective_value=None,
        iterations=100,
        setup_time=0.0,
        update_time=0.0,
        solve_time=0.0,
        primal_residual=None,
        dual_residual=None,
        warm_start_used=False,
        cold_retries=0,
    )


@pytest.mark.parametrize("spread", SPREADS)
def test_near_identical_net_returns_are_recovered_within_the_configured_budget(
    spread: float,
) -> None:
    mu = np.array([0.07, 0.07 + spread])
    inst = nd.custom_instance(mu, SIGMA, CURRENT)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID
    )
    built = session.variance_problem
    target = float(mu @ CURRENT) - TARGET_MARGIN
    lower = built.lower_for_target(target)
    solver = CONFIG.solver
    budget = solver.max_iterations * solver.retry_iteration_multiplier

    result = NumericalRecovery(solver).recover(
        built,
        built.q_zero(),
        lower,
        _first_failure(),
        [],
        lambda r: session._passes_validation(r, target),
    )

    # recuperación correcta y solución OPTIMAL válida frente al objetivo ORIGINAL
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    assert result.status_source is StatusSource.CROSS_CHECK
    trace = result.recovery
    assert trace is not None and trace.outcome is RecoveryOutcome.RECOVERED
    weights = built.weights(result.x)
    report = session._validate(weights, target)
    assert report.is_valid
    assert session.net_return(weights) >= target - 1e-6
    # referencia analítica independiente de mínima varianza
    reference = nd.two_asset_reference(inst, CostTreatment.NET, HORIZON, target)
    assert reference is not None
    assert float(weights @ SIGMA @ weights) == pytest.approx(reference, abs=1e-6)

    # trazabilidad: original → oráculo → reintentos; solo el último es aceptado
    strategies = [a.strategy for a in trace.attempts]
    assert strategies[:2] == ["ORIGINAL", "LP_FEASIBILITY_ORACLE"]
    retries = trace.attempts[2:]
    assert retries and all(a.strategy == "NORMALIZED_RETURN_ROW" for a in retries)
    assert trace.feasibility == "FEASIBLE"
    assert retries[-1].status is SolverStatus.OPTIMAL and not retries[-1].rejected_by_validator
    assert all(a.row_scale is not None and a.row_scale > 0.0 for a in retries)

    # presupuesto: cada reintento respeta max_iterations × multiplicador y hay a lo sumo
    # una resolución por escala configurada; el total es la suma de los intentos
    assert len(retries) <= len(solver.recovery_row_scales)
    assert all(a.iterations <= budget for a in retries)
    assert result.iterations == sum(a.iterations for a in trace.attempts)
    assert result.iterations <= trace.attempts[0].iterations + trace.attempts[1].iterations + (
        len(retries) * budget
    )


@pytest.mark.parametrize("spread", SPREADS)
def test_near_identical_net_frontiers_have_no_invalid_points(spread: float) -> None:
    """Flujo completo de la frontera: todos los puntos OPTIMAL y válidos."""
    mu = np.array([0.07, 0.07 + spread])
    inst = nd.custom_instance(mu, SIGMA, CURRENT)
    result = ENGINE.solve(inst.problem, CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID)
    assert result.pre_check_feasible and result.points
    assert all(p.is_valid_solution and p.status is SolverStatus.OPTIMAL for p in result.points)
