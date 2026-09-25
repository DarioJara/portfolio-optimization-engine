"""SOL-002, VAL-001, FRN-008 (remediación F-3): recuperación numérica de los puntos de retorno
objetivo que OSQP no resuelve.

Las siete instancias contractuales de F-3 (y las halladas por el barrido determinista) tienen
fronteras ``TARGET_RETURN_GRID`` casi degeneradas: OSQP declaraba ``INFEASIBLE`` (certificado
espurio), ``NUMERICAL_ERROR``, ``MAX_ITERATIONS`` u ``OPTIMAL_INACCURATE`` en puntos factibles.
Estos tests fijan que, tras la remediación, todos los puntos son válidos y **óptimos frente a
referencias independientes** (solución analítica, SLSQP por regiones y LP de HiGHS), que los
estados se distinguen y se registran, que un objetivo verdaderamente infactible sigue siendo
``INFEASIBLE`` y que ningún punto ``OPTIMAL_INACCURATE`` u ``OPTIMAL`` rechazado por el validador
se acepta.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.frontiers import (
    ContinuousFrontierEngine,
    TargetReturnGrid,
    numerical_recovery,
)
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    RecoveryOutcome,
    SolverStatus,
    StatusSource,
    StrategyID,
)
from portfolio_engine.models.frontier import CompositionFrontierResult, FrontierPoint
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers.feasibility_oracle import FeasibilityVerdict
from tests.fixtures import near_degenerate as nd
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
ENGINE = ContinuousFrontierEngine(CONFIG)
HORIZON = CONFIG.optimization_horizon_years
TREATMENTS = list(CostTreatment)
#: Tolerancia de la varianza frente a la referencia exacta (varianzas ~0,05; tolerancia de
#: restricción del validador 1e-7 en retorno).
VARIANCE_TOLERANCE = 1e-6


def _solve(inst: nd.Instance, treatment: CostTreatment, engine=ENGINE):  # type: ignore[no-untyped-def]
    return engine.solve(inst.problem, treatment, FrontierMethod.TARGET_RETURN_GRID)


def _assert_all_valid(result: CompositionFrontierResult) -> None:
    assert result.pre_check_feasible and result.points
    for point in result.points:
        assert point.is_valid_solution, (point.point_id, point.status, point.validation)
        assert point.status is SolverStatus.OPTIMAL
        assert point.validation is not None and point.validation.is_valid
        assert point.weights is not None and point.metrics is not None
        assert point.weights.sum() == pytest.approx(1.0, abs=1e-7)
        assert point.weights.min() >= -1e-7


# ----------------------------------------------------------------- casos contractuales de F-3


@pytest.mark.parametrize(("n", "seed"), nd.CONTRACT_INSTANCES)
@pytest.mark.parametrize("treatment", TREATMENTS)
def test_every_contract_instance_has_only_valid_optimal_points(
    n: int, seed: int, treatment: CostTreatment
) -> None:
    """Las siete instancias de F-3 × GROSS/NET/POST_COST_GROSS: ningún punto inválido."""
    _assert_all_valid(_solve(nd.instance(n, seed), treatment))


@pytest.mark.parametrize(("n", "seed", "treatment"), nd.SWEEP_INSTANCES)
def test_the_instances_found_by_the_sweep_have_only_valid_optimal_points(
    n: int, seed: int, treatment: CostTreatment
) -> None:
    """Instancias adicionales del barrido (mismo generador, mismo defecto en la línea base)."""
    _assert_all_valid(_solve(nd.instance(n, seed), treatment))


#: Con referencia independiente: dos activos (GROSS y NET, analítica) y NET con tres (SLSQP).
REFERENCE_CASES = [
    (n, seed, treatment)
    for n, seed in nd.CONTRACT_INSTANCES
    for treatment in (CostTreatment.GROSS, CostTreatment.NET)
    if n == 2 or treatment is CostTreatment.NET
]


@pytest.mark.parametrize(("n", "seed", "treatment"), REFERENCE_CASES)
def test_recovered_frontiers_are_optimal_against_independent_references(
    n: int, seed: int, treatment: CostTreatment
) -> None:
    """La varianza de cada punto interior coincide con la mínima exacta con retorno >= objetivo.

    Dos activos: solución analítica por regiones; tres activos (NET): SLSQP por regiones de
    compra/venta. El extremo MaxReturn (holgura de desempate A-14) no es un punto de malla.
    """
    inst = nd.instance(n, seed)
    result = _solve(inst, treatment)
    checked = 0
    for point in result.points:
        if point.strategy_id is not StrategyID.FRONTIER_POINT:
            continue
        assert point.target_return is not None and point.metrics is not None
        if n == 2:
            reference = nd.two_asset_reference(inst, treatment, HORIZON, point.target_return)
        else:
            reference = nd.orthant_reference(inst, HORIZON, point.target_return)
        assert reference is not None
        assert point.metrics.variance == pytest.approx(reference, abs=VARIANCE_TOLERANCE)
        checked += 1
    assert checked >= 10


@pytest.mark.parametrize(("n", "seed"), nd.CONTRACT_INSTANCES)
@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_no_grid_target_is_truly_infeasible(n: int, seed: int, treatment: CostTreatment) -> None:
    """Oráculo LP: todos los objetivos de la malla están por debajo del retorno máximo."""
    inst = nd.instance(n, seed)
    best = nd.lp_max_return(inst, treatment, HORIZON)
    for point in _solve(inst, treatment).points:
        if point.target_return is not None:
            assert point.target_return <= best + 1e-9


def test_post_cost_gross_is_evaluated_from_the_recovered_gross_weights() -> None:
    """POST_COST_GROSS no resuelve nada nuevo: hereda los pesos ya recuperados de GROSS."""
    inst = nd.instance(2, 84)
    gross = _solve(inst, CostTreatment.GROSS)
    post = _solve(inst, CostTreatment.POST_COST_GROSS)
    assert all(p.is_valid_solution for p in post.points)
    for one, other in zip(gross.points, post.points, strict=True):
        assert one.weights is not None and other.weights is not None
        assert one.weights.tobytes() == other.weights.tobytes()
        assert other.cost_treatment is CostTreatment.POST_COST_GROSS


# ------------------------------------------------------------- estados, trazas y diagnósticos


def _recovering_point() -> tuple[FrontierPoint, float]:
    """Punto de (2, 84) GROSS que la línea base declaraba ``INFEASIBLE`` (certificado espurio)."""
    inst = nd.instance(2, 84)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    target = 0.056772036654895656
    return TargetReturnGrid(session).solve_target(target), target


def test_a_recovered_point_records_why_and_how_it_was_recovered() -> None:
    point, target = _recovering_point()
    assert point.is_valid_solution and point.status is SolverStatus.OPTIMAL
    assert point.target_return == target  # el objetivo solicitado no se modifica
    assert point.status_source is StatusSource.CROSS_CHECK
    solve = point.solve
    assert solve is not None and solve.recovery is not None
    trace = solve.recovery
    assert trace.trigger_status is SolverStatus.INFEASIBLE
    assert trace.trigger_native_status == "primal infeasible"
    assert trace.feasibility == "FEASIBLE"  # el LP independiente lo halla factible
    assert trace.outcome is RecoveryOutcome.RECOVERED
    strategies = [attempt.strategy for attempt in trace.attempts]
    assert strategies[0] == "ORIGINAL" and strategies[1] == "LP_FEASIBILITY_ORACLE"
    assert strategies[-1] == "NORMALIZED_RETURN_ROW"
    original, oracle, final = trace.attempts[0], trace.attempts[1], trace.attempts[-1]
    assert original.solver_name == "OSQP" and original.status is SolverStatus.INFEASIBLE
    assert oracle.solver_name == "HiGHS" and oracle.status is SolverStatus.OPTIMAL
    assert final.solver_name == "OSQP" and final.status is SolverStatus.OPTIMAL
    assert final.row_scale is not None and not final.rejected_by_validator
    # iteraciones de todos los intentos de solver cuadrático (sin el oráculo)
    assert solve.iterations == sum(a.iterations for a in trace.attempts if a.solver_name == "OSQP")
    assert solve.y is None  # multiplicadores de la fila normalizada: no se exponen


def test_recovery_is_reproducible_bit_for_bit() -> None:
    first, _ = _recovering_point()
    second, _ = _recovering_point()
    assert first.weights is not None and second.weights is not None
    assert first.weights.tobytes() == second.weights.tobytes()
    assert first.solve is not None and second.solve is not None
    assert first.solve.recovery is not None and second.solve.recovery is not None
    assert [a.iterations for a in first.solve.recovery.attempts] == [
        a.iterations for a in second.solve.recovery.attempts
    ]


@pytest.mark.parametrize(
    ("n", "seed", "treatment", "status"),
    [
        (2, 84, CostTreatment.GROSS, SolverStatus.INFEASIBLE),
        (2, 89, CostTreatment.NET, SolverStatus.INFEASIBLE),
        (3, 67, CostTreatment.NET, SolverStatus.NUMERICAL_ERROR),
        (2, 159, CostTreatment.NET, SolverStatus.MAX_ITERATIONS),
        (2, 19, CostTreatment.NET, SolverStatus.OPTIMAL_INACCURATE),
    ],
)
def test_without_recovery_the_baseline_statuses_are_reproduced(
    n: int, seed: int, treatment: CostTreatment, status: SolverStatus
) -> None:
    """Con ``numerical_recovery = false`` los estados de F-3 son los originales, sin traza y sin
    aceptar nunca un punto no óptimo: la mejora se debe exclusivamente a la recuperación."""
    engine = ContinuousFrontierEngine(base_config(solver={"numerical_recovery": False}))
    result = _solve(nd.instance(n, seed), treatment, engine)
    invalid = [p for p in result.points if not p.is_valid_solution]
    assert invalid and {p.status for p in invalid} == {status}
    assert all(p.solve is not None and p.solve.recovery is None for p in result.points)


def test_a_truly_infeasible_target_stays_infeasible_and_is_confirmed_by_the_lp() -> None:
    inst = nd.instance(2, 84)
    best = nd.lp_max_return(inst, CostTreatment.GROSS, HORIZON)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    point = TargetReturnGrid(session).solve_target(best + 1e-3)
    assert point.status is SolverStatus.INFEASIBLE and not point.is_valid_solution
    assert point.status_source is StatusSource.SOLVER  # el estado del solver queda confirmado
    assert point.weights is None
    assert point.solve is not None and point.solve.recovery is not None
    trace = point.solve.recovery
    assert trace.outcome is RecoveryOutcome.CONFIRMED_INFEASIBLE
    assert trace.feasibility == "INFEASIBLE"
    assert [a.strategy for a in trace.attempts] == ["ORIGINAL", "LP_FEASIBILITY_ORACLE"]  # sin más


def test_the_targets_just_below_the_maximum_are_solved_not_declared_infeasible() -> None:
    inst = nd.instance(2, 84)
    best = nd.lp_max_return(inst, CostTreatment.GROSS, HORIZON)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    for margin in (1e-6, 1e-7):
        point = TargetReturnGrid(session).solve_target(best - margin)
        assert point.is_valid_solution, (margin, point.status)


def test_a_retry_that_the_solver_calls_optimal_but_the_validator_rejects_is_not_accepted() -> None:
    """Escala de fila inservible: OSQP dice ``OPTIMAL`` sobre la fila reescalada pero el punto
    viola el objetivo original. Se registra el rechazo, no se acepta y el ``INFEASIBLE`` inicial
    (que el LP halla factible) se reclasifica a ``NUMERICAL_ERROR``."""
    config = base_config(solver={"recovery_row_scales": (1e-9,)})
    engine = ContinuousFrontierEngine(config)
    inst = nd.instance(2, 84)
    session = engine.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    point = TargetReturnGrid(session).solve_target(0.056772036654895656)
    assert not point.is_valid_solution and point.weights is None
    assert point.status is SolverStatus.NUMERICAL_ERROR
    assert point.solve is not None and point.solve.recovery is not None
    trace = point.solve.recovery
    assert trace.outcome is RecoveryOutcome.NOT_RECOVERED
    assert trace.trigger_status is SolverStatus.INFEASIBLE and trace.feasibility == "FEASIBLE"
    retried = trace.attempts[-1]
    assert retried.status is SolverStatus.OPTIMAL and retried.rejected_by_validator


def test_an_inaccurate_retry_is_never_promoted_to_optimal() -> None:
    """Con muy pocas iteraciones ningún reintento converge: el punto conserva un estado no
    óptimo, es inválido y no hay más intentos que escalas (sin bucles)."""
    config = base_config(solver={"max_iterations": 25, "retry_iteration_multiplier": 1})
    engine = ContinuousFrontierEngine(config)
    inst = nd.instance(2, 89)
    session = engine.open_session(
        inst.problem, CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID
    )
    point = TargetReturnGrid(session).solve_target(0.11514)
    assert point.status is not SolverStatus.OPTIMAL and not point.is_valid_solution
    assert point.solve is not None and point.solve.recovery is not None
    trace = point.solve.recovery
    assert trace.outcome is RecoveryOutcome.NOT_RECOVERED
    scales = CONFIG.solver.recovery_row_scales
    normalized = [a for a in trace.attempts if a.strategy == "NORMALIZED_RETURN_ROW"]
    assert len(normalized) == len(scales)
    assert all(a.status is not SolverStatus.OPTIMAL for a in normalized)


TARGET_84 = 0.056772036654895656


class _InaccurateBackend:
    """Envuelve un backend real y degrada su ``OPTIMAL`` a ``OPTIMAL_INACCURATE``.

    La solución (``x``) sigue siendo la del reintento real, que supera el validador: lo único que
    puede provocar el rechazo es el estado, de modo que el test aísla la regla «un reintento
    ``OPTIMAL_INACCURATE`` no se promueve».
    """

    def __init__(self, inner) -> None:  # type: ignore[no-untyped-def]
        self._inner = inner

    def setup(self, problem) -> None:  # type: ignore[no-untyped-def]
        self._inner.setup(problem)

    def solve(self) -> SolveResult:
        real = self._inner.solve()
        assert real.status is SolverStatus.OPTIMAL and real.x is not None
        return dataclasses.replace(real, status=SolverStatus.OPTIMAL_INACCURATE)


def test_a_retry_returning_optimal_inaccurate_is_recorded_but_never_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AF3-01: el reintento devuelve realmente ``OPTIMAL_INACCURATE`` con pesos válidos.

    No se promueve a ``OPTIMAL``, no se acepta el punto, se conserva el estado real (el
    ``INFEASIBLE`` inicial que el LP halla factible pasa a ``NUMERICAL_ERROR``), cada escala queda
    registrada con su estado auténtico y no se inventan pesos ni métricas.
    """
    inst = nd.instance(2, 84)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    router = session._recovery._router  # type: ignore[attr-defined]
    real_route = router.route
    monkeypatch.setattr(router, "route", lambda problem: _InaccurateBackend(real_route(problem)))
    point = TargetReturnGrid(session).solve_target(TARGET_84)

    assert point.status is not SolverStatus.OPTIMAL
    assert point.status is SolverStatus.NUMERICAL_ERROR
    assert not point.is_valid_solution
    assert point.weights is None and point.metrics is None
    assert point.solve is not None and point.solve.recovery is not None
    assert point.solve.x is None
    trace = point.solve.recovery
    assert trace.outcome is RecoveryOutcome.NOT_RECOVERED
    assert trace.trigger_status is SolverStatus.INFEASIBLE
    normalized = [a for a in trace.attempts if a.strategy == "NORMALIZED_RETURN_ROW"]
    assert len(normalized) == len(CONFIG.solver.recovery_row_scales)  # una por escala, sin bucles
    assert all(a.status is SolverStatus.OPTIMAL_INACCURATE for a in normalized)
    # el validador no llegó a decidir: el estado, no la solución, motiva el descarte
    assert not any(a.rejected_by_validator for a in normalized)


def _inconclusive_oracle(monkeypatch: pytest.MonkeyPatch) -> list[FeasibilityVerdict]:
    """Sustituye el veredicto del oráculo por ``INCONCLUSIVE`` (HiGHS sin conclusión)."""
    real = numerical_recovery.lp_feasibility
    calls: list[FeasibilityVerdict] = []

    def inconclusive(problem, lower, config):  # type: ignore[no-untyped-def]
        _, result = real(problem, lower, config)
        inconclusive_result = dataclasses.replace(
            result, status=SolverStatus.MAX_ITERATIONS, native_status="iteration limit", x=None
        )
        calls.append(FeasibilityVerdict.INCONCLUSIVE)
        return FeasibilityVerdict.INCONCLUSIVE, inconclusive_result

    monkeypatch.setattr(numerical_recovery, "lp_feasibility", inconclusive)
    return calls


def test_an_inconclusive_oracle_keeps_the_original_infeasible_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AF3-02: el LP no concluye y los reintentos no recuperan el punto.

    ``INCONCLUSIVE`` no es ``FEASIBLE`` (no se reclasifica a ``NUMERICAL_ERROR``) ni ``INFEASIBLE``
    (la escalera de reintentos sí se ejecuta, acotada). Se conserva el ``INFEASIBLE`` original del
    solver y el veredicto del oráculo queda trazado.
    """
    calls = _inconclusive_oracle(monkeypatch)
    config = base_config(solver={"recovery_row_scales": (1e-9,)})  # reintentos inservibles
    engine = ContinuousFrontierEngine(config)
    inst = nd.instance(2, 84)
    session = engine.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    point = TargetReturnGrid(session).solve_target(TARGET_84)

    assert len(calls) == 1  # el oráculo se consulta una sola vez
    assert point.status is SolverStatus.INFEASIBLE  # ni NUMERICAL_ERROR ni OPTIMAL
    assert point.status_source is StatusSource.SOLVER
    assert not point.is_valid_solution and point.weights is None and point.metrics is None
    assert point.solve is not None and point.solve.recovery is not None
    trace = point.solve.recovery
    assert trace.outcome is RecoveryOutcome.NOT_RECOVERED  # no CONFIRMED_INFEASIBLE
    assert trace.trigger_status is SolverStatus.INFEASIBLE
    assert trace.trigger_native_status == "primal infeasible"
    assert trace.feasibility == "INCONCLUSIVE"
    assert [a.strategy for a in trace.attempts] == [
        "ORIGINAL",
        "LP_FEASIBILITY_ORACLE",
        "NORMALIZED_RETURN_ROW",  # una por escala configurada: sin ciclos
    ]
    assert trace.attempts[1].status is SolverStatus.MAX_ITERATIONS


def test_an_inconclusive_oracle_does_not_block_a_genuine_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AF3-02: ``INCONCLUSIVE`` tampoco se interpreta como ``INFEASIBLE`` confirmada."""
    _inconclusive_oracle(monkeypatch)
    inst = nd.instance(2, 84)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    point = TargetReturnGrid(session).solve_target(TARGET_84)
    assert point.is_valid_solution and point.status is SolverStatus.OPTIMAL
    assert point.solve is not None and point.solve.recovery is not None
    assert point.solve.recovery.feasibility == "INCONCLUSIVE"
    assert point.solve.recovery.outcome is RecoveryOutcome.RECOVERED


def test_the_risk_aversion_grid_and_the_extremes_are_outside_the_recovery() -> None:
    """La recuperación solo actúa con retorno objetivo (F-3 es de ``TARGET_RETURN_GRID``)."""
    inst = nd.instance(2, 84)
    result = ENGINE.solve(inst.problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)
    assert all(p.solve is not None and p.solve.recovery is None for p in result.points)


def test_valid_frontiers_are_bit_identical_with_and_without_recovery() -> None:
    """La recuperación nunca toca un punto ``OPTIMAL``: las fronteras sin defecto no cambian."""
    off = ContinuousFrontierEngine(base_config(solver={"numerical_recovery": False}))
    for n, seed in [(3, 5), (3, 6), (4, 7), (5, 8), (4, 9), (5, 10)]:
        inst = nd.instance(n, seed)
        for treatment in (CostTreatment.GROSS, CostTreatment.NET):
            with_recovery = _solve(inst, treatment)
            without = _solve(inst, treatment, off)
            assert len(with_recovery.points) == len(without.points)
            for one, other in zip(with_recovery.points, without.points, strict=True):
                assert one.status is other.status is SolverStatus.OPTIMAL
                assert one.weights is not None and other.weights is not None
                assert one.weights.tobytes() == other.weights.tobytes()
                assert one.solve is not None and other.solve is not None
                assert one.solve.iterations == other.solve.iterations
                assert one.solve.recovery is None


# --------------------------------------------------------- degeneración: retornos y covarianza


def _near_identical(n: int, spread: float, seed: int) -> nd.Instance:
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, n)) * 0.1
    sigma = factor @ factor.T + np.diag(rng.uniform(0.01, 0.05, n))
    mu = 0.07 + rng.uniform(0.0, 1.0, n) * spread
    current = rng.dirichlet(np.ones(n))
    return nd.custom_instance(mu, sigma, current, seed)


@pytest.mark.parametrize(("n", "spread"), [(2, 1e-6), (2, 1e-8), (3, 1e-7), (4, 1e-8)])
@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_almost_identical_returns_give_fully_valid_frontiers(
    n: int, spread: float, treatment: CostTreatment
) -> None:
    _assert_all_valid(_solve(_near_identical(n, spread, 5), treatment))


@pytest.mark.parametrize(("n", "jitter"), [(3, 0.0), (3, 1e-10), (4, 1e-8)])
@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_singular_and_almost_singular_covariance_give_valid_frontiers(
    n: int, jitter: float, treatment: CostTreatment
) -> None:
    rng = np.random.default_rng(11)
    loading = rng.normal(size=(n, 1)) * 0.2
    sigma = loading @ loading.T + np.eye(n) * jitter
    mu = rng.uniform(0.03, 0.12, n)
    inst = nd.custom_instance(mu, sigma, rng.dirichlet(np.ones(n)), 11)
    _assert_all_valid(_solve(inst, treatment))


def test_identical_returns_are_a_degenerate_single_portfolio_frontier() -> None:
    """Retornos exactamente iguales (GROSS): frontera degenerada documentada, sin fallo."""
    mu = np.full(3, 0.07)
    inst = nd.custom_instance(mu, np.diag([0.02, 0.03, 0.04]), np.array([0.3, 0.3, 0.4]))
    result = _solve(inst, CostTreatment.GROSS)
    assert "DEGENERATE_FRONTIER_SINGLE_EFFICIENT_PORTFOLIO" in result.notes
    assert all(p.is_valid_solution for p in result.points)
