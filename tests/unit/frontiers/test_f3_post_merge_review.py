"""SOL-002, OPT-003, FRN-008 (revisión posterior al merge del PR #3, remediación F-3).

P2-01. La normalización de la fila de retorno calculaba la escala solo sobre el bloque de pesos:
con retornos idénticos el centrado anula ese bloque y la fila NET conserva los coeficientes de
compra/venta (``−c_b/H``, ``−c_s/H``), de modo que devolvía ``None`` y abortaba los reintentos con
una restricción todavía informativa.

P2-02. ``SolveResult.iterations`` excluía las iteraciones del oráculo de HiGHS aunque su tiempo sí
se sumaba a ``solve_time``. Ahora el total incluye todos los intentos (una vez cada uno) y se
desglosa por solver.
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
from portfolio_engine.optimizers import FeasibilityVerdict, lp_feasibility
from tests.fixtures import near_degenerate as nd
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
ENGINE = ContinuousFrontierEngine(CONFIG)
HORIZON = CONFIG.optimization_horizon_years
TARGET_84 = 0.056772036654895656

SIGMA = np.diag([0.02, 0.04])
CURRENT = np.array([0.7, 0.3])


def _identical(spread: float = 0.0) -> nd.Instance:
    """Dos activos de retorno idéntico (o casi), costes de compra/venta asimétricos y no nulos."""
    mu = np.array([0.07, 0.07 + spread])
    return nd.custom_instance(mu, SIGMA, CURRENT)


def _built(inst: nd.Instance, treatment: CostTreatment):  # type: ignore[no-untyped-def]
    session = ENGINE.open_session(inst.problem, treatment, FrontierMethod.TARGET_RETURN_GRID)
    return session, session.variance_problem


def _row(problem, index: int) -> np.ndarray:  # type: ignore[no-untyped-def]
    return np.asarray(problem.A.getrow(index).toarray(), dtype=np.float64).ravel()


# ================================================================================ P2-01


@pytest.mark.parametrize("spread", [0.0, 1e-13, 1e-10])
@pytest.mark.parametrize("weight_scale", [1.0, 10.0, 100.0])
def test_net_identical_or_almost_identical_returns_keep_an_informative_row(
    spread: float, weight_scale: float
) -> None:
    """El defecto original: el bloque de pesos centrado es (casi) nulo pero los coeficientes de
    compra/venta no; la normalización debe existir y escalar sobre todos los coeficientes."""
    _, built = _built(_identical(spread), CostTreatment.NET)
    original = _row(built.problem, built.return_row)
    n = built.n_weights
    assert np.abs(original[n:]).min() > 0.0  # coeficientes auxiliares no nulos y asimétricos
    assert not np.allclose(original[n : 2 * n], original[2 * n :])

    normalized = built.normalize_return_row(weight_scale)
    assert normalized is not None  # con ``centered[:n_weights]`` era ``None`` si spread == 0
    row = _row(normalized.problem, built.return_row)
    # el bloque de pesos centrado es (casi) cero, el auxiliar sigue siendo informativo
    assert np.abs(row[:n]).max() <= weight_scale * max(spread * 1e3, 1e-9)
    assert np.abs(row[n:]).max() > 0.0
    assert np.abs(row).max() == pytest.approx(weight_scale, rel=1e-12)


def test_a_negligible_weight_block_falls_back_to_the_scale_of_the_whole_row() -> None:
    """Con pesos centrados nulos, la escala depende exclusivamente del bloque auxiliar; con pesos
    informativos se conserva la escala de pesos validada en F-3 (test siguiente)."""
    _, built = _built(_identical(), CostTreatment.NET)
    n = built.n_weights
    original = _row(built.problem, built.return_row)
    normalized = built.normalize_return_row(10.0)
    assert normalized is not None
    assert normalized.row_scale == pytest.approx(10.0 / np.abs(original[n:]).max(), rel=1e-12)


@pytest.mark.parametrize("weight_scale", [1.0, 10.0, 100.0])
@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_the_transformed_row_is_algebraically_equivalent_to_the_original(
    treatment: CostTreatment, weight_scale: float
) -> None:
    """Para todo ``x`` con ``1ᵀw = 1``: ``fila'·x − cota' = s·(fila·x − cota)`` con las variables
    auxiliares libres (no solo los pesos), incluido el caso de retornos idénticos."""
    # GROSS con retornos idénticos es la fila nula: se comprueba aparte
    inst = nd.instance(3, 67) if treatment is CostTreatment.GROSS else _identical()
    _, built = _built(inst, treatment)
    normalized = built.normalize_return_row(weight_scale)
    assert normalized is not None
    lower = built.lower_for_target(0.05)
    mapped = normalized.lower_for(lower)
    rng = np.random.default_rng(11)
    row = built.return_row
    for _ in range(50):
        x = rng.normal(size=built.problem.n_variables)
        x[: built.n_weights] += (1.0 - x[: built.n_weights].sum()) / built.n_weights
        original = _row(built.problem, row) @ x - lower[row]
        transformed = _row(normalized.problem, row) @ x - mapped[row]
        assert transformed == pytest.approx(normalized.row_scale * original, rel=1e-9, abs=1e-12)
    keep = np.arange(built.problem.n_constraints) != row
    assert (normalized.problem.A.toarray()[keep] == built.problem.A.toarray()[keep]).all()
    assert (mapped[keep] == lower[keep]).all()
    assert (normalized.problem.upper == built.problem.upper).all()


def test_a_completely_null_row_has_nothing_to_normalize() -> None:
    """GROSS idéntico, o NET idéntico sin costes: fila centrada nula (o solo ruido) → ``None``."""
    mu = np.full(3, 0.07)
    inst = nd.custom_instance(mu, np.diag([0.02, 0.03, 0.04]), np.full(3, 1 / 3))
    assert _built(inst, CostTreatment.GROSS)[1].normalize_return_row(10.0) is None
    free = nd._build(np.full(2, 0.07), SIGMA, CURRENT, np.zeros(2), np.zeros(2))
    assert _built(free, CostTreatment.NET)[1].normalize_return_row(10.0) is None
    roundoff = nd.custom_instance(np.full(3, 0.1 + 0.2), np.eye(3) * 0.02, np.full(3, 1 / 3))
    assert _built(roundoff, CostTreatment.GROSS)[1].normalize_return_row(10.0) is None


@pytest.mark.parametrize("weight_scale", [1.0, 10.0, 100.0])
def test_the_weight_dominated_scale_is_unchanged_for_ordinary_instances(
    weight_scale: float,
) -> None:
    """Sin regresión: con pesos dominantes la escala sigue siendo la del bloque de pesos."""
    for n, seed in nd.CONTRACT_INSTANCES:
        for treatment in (CostTreatment.GROSS, CostTreatment.NET):
            _, built = _built(nd.instance(n, seed), treatment)
            normalized = built.normalize_return_row(weight_scale)
            assert normalized is not None
            weights_only = np.abs(_row(normalized.problem, built.return_row)[: built.n_weights])
            assert weights_only.max() == pytest.approx(weight_scale, rel=1e-12)


def _net_return_at_hold(inst: nd.Instance) -> float:
    """Con retornos idénticos y sin operar, el retorno neto es ``μ`` (referencia independiente)."""
    return float(inst.mu @ inst.current)


@pytest.mark.parametrize(("offset", "feasible"), [(-1e-4, True), (-1e-3, True), (1e-6, False)])
def test_the_transformed_problem_agrees_with_an_independent_lp_on_feasibility(
    offset: float, feasible: bool
) -> None:
    """Oráculo independiente: ``lp_max_return`` (linprog sobre las variables originales) decide la
    factibilidad; el LP de HiGHS sobre la fila transformada debe coincidir con él."""
    inst = _identical()
    _, built = _built(inst, CostTreatment.NET)
    target = _net_return_at_hold(inst) + offset
    assert (nd.lp_max_return(inst, CostTreatment.NET, HORIZON) >= target) is feasible
    normalized = built.normalize_return_row(10.0)
    assert normalized is not None
    lower = built.lower_for_target(target)
    original_verdict, _ = lp_feasibility(built.problem, lower, CONFIG.solver)
    problem = dataclasses.replace(normalized.problem, lower=normalized.lower_for(lower))
    transformed_verdict, _ = lp_feasibility(problem, problem.lower, CONFIG.solver)
    expected = FeasibilityVerdict.FEASIBLE if feasible else FeasibilityVerdict.INFEASIBLE
    assert original_verdict is expected
    assert transformed_verdict is expected


def _forced_first(session, built, lower) -> SolveResult:  # type: ignore[no-untyped-def]
    """Fallo numérico inicial ficticio (``INFEASIBLE`` espurio de OSQP) con 100 iteraciones."""
    return _result(SolverStatus.INFEASIBLE, 100, built, "OSQP", None)


def _result(
    status: SolverStatus,
    iterations: int,
    built,
    solver: str,
    x: np.ndarray | None,  # type: ignore[no-untyped-def]
) -> SolveResult:
    return SolveResult(
        status=status,
        native_status=f"scripted {status.value}",
        status_source=StatusSource.SOLVER,
        solver_name=solver,
        solver_version="test",
        problem_class=ProblemClass.QP,
        x=x,
        y=None,
        objective_value=None,
        iterations=iterations,
        setup_time=0.0,
        update_time=0.0,
        solve_time=0.0,
        primal_residual=None,
        dual_residual=None,
        warm_start_used=False,
        cold_retries=0,
    )


def test_net_recovery_of_identical_returns_reaches_the_independent_optimum() -> None:
    """Ruta completa con fallo inicial forzado: oráculo → reintento con la fila normalizada.

    Antes de la corrección ``normalize_return_row`` devolvía ``None`` y no había ningún reintento.
    """
    inst = _identical()
    session, built = _built(inst, CostTreatment.NET)
    target = _net_return_at_hold(inst) - 1e-4
    lower = built.lower_for_target(target)
    first = _forced_first(session, built, lower)
    backends: list = []  # type: ignore[type-arg]
    recovery = NumericalRecovery(CONFIG.solver)
    q = built.q_zero()
    assert recovery.applies(built, lower, first)
    result = recovery.recover(
        built,
        q,
        lower,
        first,
        backends,
        lambda r: session._passes_validation(r, target),
    )
    assert result.status is SolverStatus.OPTIMAL
    assert result.recovery is not None and result.recovery.outcome is RecoveryOutcome.RECOVERED
    assert result.recovery.feasibility == "FEASIBLE"
    assert [a.strategy for a in result.recovery.attempts][:3] == [
        "ORIGINAL",
        "LP_FEASIBILITY_ORACLE",
        "NORMALIZED_RETURN_ROW",
    ]
    weights = built.weights(result.x)  # type: ignore[arg-type]
    net = nd.two_asset_reference(inst, CostTreatment.NET, HORIZON, target)
    assert net is not None
    assert float(weights @ SIGMA @ weights) == pytest.approx(net, abs=1e-6)
    assert result.recovery.trigger_status is SolverStatus.INFEASIBLE  # el objetivo no se altera


def test_a_truly_infeasible_net_target_is_still_confirmed_infeasible_by_the_oracle() -> None:
    inst = _identical()
    session, built = _built(inst, CostTreatment.NET)
    target = _net_return_at_hold(inst) + 1e-6  # por encima del máximo neto (retener la cartera)
    lower = built.lower_for_target(target)
    first = _forced_first(session, built, lower)
    result = NumericalRecovery(CONFIG.solver).recover(
        built, built.q_zero(), lower, first, [], lambda r: True
    )
    assert result.recovery is not None
    assert result.recovery.outcome is RecoveryOutcome.CONFIRMED_INFEASIBLE
    assert result.status is SolverStatus.INFEASIBLE and result.x is None
    assert [a.strategy for a in result.recovery.attempts] == ["ORIGINAL", "LP_FEASIBILITY_ORACLE"]


@pytest.mark.parametrize("treatment", list(CostTreatment))
def test_identical_returns_give_valid_frontiers_for_every_treatment(
    treatment: CostTreatment,
) -> None:
    result = ENGINE.solve(_identical().problem, treatment, FrontierMethod.TARGET_RETURN_GRID)
    assert result.pre_check_feasible and result.points
    assert all(p.is_valid_solution and p.status is SolverStatus.OPTIMAL for p in result.points)


# ================================================================================ P2-02


class _Scripted:
    """Backend de reintento con resultados prefijados (iteraciones deterministas)."""

    def __init__(self, results: list[SolveResult]) -> None:
        self._results = results

    def setup(self, problem) -> None:  # type: ignore[no-untyped-def]
        pass

    def solve(self) -> SolveResult:
        return self._results.pop(0)


def _harness(  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    *,
    first_status: SolverStatus,
    oracle: tuple[FeasibilityVerdict, SolverStatus, int] | None,
    retries: list[tuple[SolverStatus, int]],
):
    """``recover`` sobre (2, 84) GROSS con veredicto del oráculo y reintentos guionizados."""
    inst = nd.instance(2, 84)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    built = session.variance_problem
    lower = built.lower_for_target(TARGET_84)
    x = np.array([0.5, 0.5])
    first = _result(first_status, 10, built, "OSQP", None)
    calls: list[str] = []
    if oracle is not None:
        verdict, status, iterations = oracle

        def fake_oracle(problem, low, config):  # type: ignore[no-untyped-def]
            calls.append("oracle")
            usable = x if status is SolverStatus.OPTIMAL else None
            return verdict, _result(status, iterations, built, "HiGHS", usable)

        monkeypatch.setattr(numerical_recovery, "lp_feasibility", fake_oracle)
    recovery = NumericalRecovery(CONFIG.solver)
    scripted = [
        _result(status, iterations, built, "OSQP", x if status is SolverStatus.OPTIMAL else None)
        for status, iterations in retries
    ]
    monkeypatch.setattr(recovery._router, "route", lambda problem: _Scripted(scripted))
    result = recovery.recover(built, built.q_zero(), lower, first, [], lambda r: True)
    assert not scripted or calls == ["oracle"] or oracle is None
    return result


def _check_sums(result: SolveResult) -> None:
    """La suma del total es la suma de intentos: cada uno se cuenta una sola vez."""
    trace = result.recovery
    assert trace is not None
    assert result.iterations == sum(a.iterations for a in trace.attempts)
    assert sum(n for _, n in result.iterations_by_solver) == result.iterations
    assert result.iterations_by_solver == trace.iterations_by_solver


def test_case_a_an_optimal_first_solution_has_no_oracle_and_no_recovery() -> None:
    inst = nd.instance(2, 84)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    grid = TargetReturnGrid(session)
    point = grid.solve_target(0.05)  # objetivo holgado que OSQP resuelve sin recuperación
    assert point.solve is not None and point.solve.recovery is None
    assert point.status is SolverStatus.OPTIMAL
    result = point.solve
    assert result.iterations_by_solver == (("OSQP", result.iterations),)
    assert result.iterations > 0
    assert session.total_iterations == sum(n for _, n in session.iterations_by_solver)


def test_case_b_the_oracle_confirming_infeasibility_adds_its_iterations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _harness(
        monkeypatch,
        first_status=SolverStatus.INFEASIBLE,
        oracle=(FeasibilityVerdict.INFEASIBLE, SolverStatus.INFEASIBLE, 4),
        retries=[],
    )
    assert result.recovery is not None
    assert result.recovery.outcome is RecoveryOutcome.CONFIRMED_INFEASIBLE
    assert [a.iterations for a in result.recovery.attempts] == [10, 4]
    assert result.iterations == 14  # antes: 10 (oráculo excluido)
    assert result.iterations_by_solver == (("HiGHS", 4), ("OSQP", 10))
    _check_sums(result)


def test_case_c_the_oracle_proving_feasibility_then_a_retry_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _harness(
        monkeypatch,
        first_status=SolverStatus.INFEASIBLE,
        oracle=(FeasibilityVerdict.FEASIBLE, SolverStatus.OPTIMAL, 4),
        retries=[(SolverStatus.OPTIMAL, 25)],
    )
    assert result.status is SolverStatus.OPTIMAL
    assert result.recovery is not None and result.recovery.outcome is RecoveryOutcome.RECOVERED
    assert [a.iterations for a in result.recovery.attempts] == [10, 4, 25]
    assert result.iterations == 39
    assert result.iterations_by_solver == (("HiGHS", 4), ("OSQP", 35))
    _check_sums(result)


def test_case_d_an_inconclusive_oracle_still_counts_its_iterations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _harness(
        monkeypatch,
        first_status=SolverStatus.NUMERICAL_ERROR,
        oracle=(FeasibilityVerdict.INCONCLUSIVE, SolverStatus.MAX_ITERATIONS, 6),
        retries=[(SolverStatus.OPTIMAL, 25)],
    )
    assert result.recovery is not None
    assert result.recovery.feasibility == "INCONCLUSIVE"
    assert result.recovery.outcome is RecoveryOutcome.RECOVERED
    assert result.iterations == 10 + 6 + 25
    assert result.iterations_by_solver == (("HiGHS", 6), ("OSQP", 35))
    _check_sums(result)


def test_case_e_a_recovery_that_does_not_recover_counts_every_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scales = len(CONFIG.solver.recovery_row_scales)
    result = _harness(
        monkeypatch,
        first_status=SolverStatus.INFEASIBLE,
        oracle=(FeasibilityVerdict.FEASIBLE, SolverStatus.OPTIMAL, 4),
        retries=[(SolverStatus.INFEASIBLE, 5)] * scales,
    )
    assert result.recovery is not None
    assert result.recovery.outcome is RecoveryOutcome.NOT_RECOVERED
    assert result.status is SolverStatus.NUMERICAL_ERROR  # reclasificado, iteraciones intactas
    assert result.iterations == 10 + 4 + 5 * scales
    assert result.iterations_by_solver == (("HiGHS", 4), ("OSQP", 10 + 5 * scales))
    _check_sums(result)


def test_case_f_several_retries_are_summed_once_each(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _harness(
        monkeypatch,
        first_status=SolverStatus.MAX_ITERATIONS,  # no consulta el oráculo
        oracle=None,
        retries=[
            (SolverStatus.MAX_ITERATIONS, 30),
            (SolverStatus.NUMERICAL_ERROR, 40),
            (SolverStatus.OPTIMAL, 8),
        ],
    )
    assert result.recovery is not None and result.recovery.outcome is RecoveryOutcome.RECOVERED
    assert result.recovery.feasibility is None
    assert [a.strategy for a in result.recovery.attempts] == ["ORIGINAL"] + [
        "NORMALIZED_RETURN_ROW"
    ] * 3
    assert result.iterations == 10 + 30 + 40 + 8
    assert result.iterations_by_solver == (("OSQP", 88),)
    _check_sums(result)


def test_a_real_recovered_point_counts_the_oracle_and_the_session_matches() -> None:
    """(2, 84) GROSS con OSQP y HiGHS reales: totales y desglose coherentes, sin doble cómputo."""
    inst = nd.instance(2, 84)
    session = ENGINE.open_session(
        inst.problem, CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID
    )
    point = TargetReturnGrid(session).solve_target(TARGET_84)
    assert point.solve is not None and point.solve.recovery is not None
    trace = point.solve.recovery
    oracle = [a for a in trace.attempts if a.strategy == "LP_FEASIBILITY_ORACLE"]
    assert len(oracle) == 1 and oracle[0].solver_name == "HiGHS"
    assert point.solve.iterations == sum(a.iterations for a in trace.attempts)
    by_solver = dict(point.solve.iterations_by_solver)
    assert by_solver["HiGHS"] == oracle[0].iterations
    assert sum(by_solver.values()) == point.solve.iterations
    assert session.total_iterations == point.solve.iterations
    assert dict(session.diagnostics().iterations_by_solver) == by_solver


def test_frontier_diagnostics_total_is_the_sum_of_the_per_solver_breakdown() -> None:
    result = ENGINE.solve(
        nd.instance(2, 84).problem, CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID
    )
    assert result.diagnostics.total_iterations == sum(
        n for _, n in result.diagnostics.iterations_by_solver
    )
    assert {name for name, _ in result.diagnostics.iterations_by_solver} <= {"OSQP", "HiGHS"}
