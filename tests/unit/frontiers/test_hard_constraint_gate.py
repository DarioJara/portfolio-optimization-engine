"""HC-009: la puerta de restricciones obligatorias no promueve puntos que el solver no valida.

Se parte de una frontera global real y se **manipulan sus puntos** (estado del solver, validez,
ausencia de pesos) para comprobar que ninguna combinación convierte una propuesta no válida en una
solución aceptada, aunque sus pesos cumplan por casualidad todas las restricciones obligatorias.
"""

from __future__ import annotations

import dataclasses

import pytest

from portfolio_engine.frontiers import GlobalCandidateFrontierEngine
from portfolio_engine.frontiers.hard_constraint_gate import (
    CODE_NO_SOLUTION,
    CODE_SOLVER_REJECTED,
    HardConstraintGate,
)
from portfolio_engine.models.enums import (
    AuditStatus,
    CostTreatment,
    FrontierMethod,
    SolverStatus,
)
from tests.fixtures.candidates import random_problem
from tests.fixtures.hard_constraints import HELD, effective_of, with_mandate

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def solved():  # type: ignore[no-untyped-def]
    config = with_mandate(max_replacements=2)
    problem = random_problem(14, list(range(HELD)), 4, config, max_weight=0.6)
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    return config, problem, result


def _audit(solved, points):  # type: ignore[no-untyped-def]
    config, problem, result = solved
    effective = effective_of(config, problem)
    return HardConstraintGate(config).audit(
        problem, effective, points, (), len(result.candidates), lambda accepted: accepted[:1]
    )


def _good(result):  # type: ignore[no-untyped-def]
    return next(p for p in result.accepted_points if p.point.status is SolverStatus.OPTIMAL)


def test_a_real_accepted_point_is_accepted_again_by_a_fresh_audit(solved) -> None:  # type: ignore[no-untyped-def]
    _, _, result = solved
    good = _good(result)
    audit = _audit(solved, [good])
    assert audit.status is AuditStatus.FEASIBLE
    assert audit.accepted_point_ids == (good.global_point_id,)


def test_a_point_the_solver_did_not_validate_is_never_accepted_even_if_its_weights_comply(
    solved,
) -> None:  # type: ignore[no-untyped-def]
    _, _, result = solved
    good = _good(result)
    unvalidated = dataclasses.replace(
        good, point=dataclasses.replace(good.point, is_valid_solution=False)
    )
    audit = _audit(solved, [unvalidated])
    assert audit.accepted_point_ids == ()
    assert audit.status is AuditStatus.NO_FEASIBLE_SOLUTION
    (verdict,) = audit.verdicts
    assert CODE_SOLVER_REJECTED in verdict.report.rejection_codes
    # los pesos sí cumplían el mandato: la única causa es la validez del solver
    assert verdict.report.rejection_codes == (CODE_SOLVER_REJECTED,)


@pytest.mark.parametrize(
    "status",
    [
        SolverStatus.INFEASIBLE,
        SolverStatus.NUMERICAL_ERROR,
        SolverStatus.MAX_ITERATIONS,
        SolverStatus.TIME_LIMIT,
        SolverStatus.UNKNOWN,
    ],
)
def test_an_inadmissible_solver_state_rejects_the_point(solved, status: SolverStatus) -> None:  # type: ignore[no-untyped-def]
    _, _, result = solved
    good = _good(result)
    broken = dataclasses.replace(good, point=dataclasses.replace(good.point, status=status))
    audit = _audit(solved, [broken])
    assert audit.accepted_point_ids == ()
    assert "HC_REJECTED:SOLVER_STATUS" in audit.verdicts[0].report.rejection_codes


def test_inaccurate_solutions_are_accepted_only_when_the_solver_configuration_allows_it(
    solved,
) -> None:  # type: ignore[no-untyped-def]
    config, problem, result = solved
    good = _good(result)
    inaccurate = dataclasses.replace(
        good,
        point=dataclasses.replace(good.point, status=SolverStatus.OPTIMAL_INACCURATE),
    )
    strict = _audit(solved, [inaccurate])
    assert strict.accepted_point_ids == ()
    lenient_solver = dataclasses.replace(config.solver, accept_inaccurate_solutions=True)
    lenient_config = dataclasses.replace(config, solver=lenient_solver)
    effective = effective_of(lenient_config, problem)
    lenient = HardConstraintGate(lenient_config).audit(
        problem, effective, [inaccurate], (), 1, lambda accepted: accepted
    )
    assert lenient.accepted_point_ids == (inaccurate.global_point_id,)


def test_a_point_without_weights_is_rejected_as_no_solution(solved) -> None:  # type: ignore[no-untyped-def]
    _, _, result = solved
    good = _good(result)
    empty = dataclasses.replace(good, point=dataclasses.replace(good.point, weights=None))
    audit = _audit(solved, [empty])
    assert audit.verdicts[0].report.rejection_codes == (CODE_NO_SOLUTION,)
    assert audit.accepted_point_ids == () and audit.accepted_envelope_ids == ()


def test_no_accepted_point_means_no_feasible_solution_unless_the_preflight_proved_it(
    solved,
) -> None:  # type: ignore[no-untyped-def]
    config, problem, _ = solved
    audit = _audit(solved, [])
    assert audit.status is AuditStatus.NO_FEASIBLE_SOLUTION  # se buscó (hay candidatos)
    effective = effective_of(config, problem)
    proven = HardConstraintGate(config).audit(
        problem,
        effective,
        [],
        ("HARD_CONSTRAINTS_INFEASIBLE: HC_ALL_SIZES_INFEASIBLE: demo",),
        0,
        lambda accepted: accepted,
    )
    assert proven.status is AuditStatus.INFEASIBLE
    assert proven.preflight_causes
    # sin candidatos pero sin causa determinista no hay prueba de inviabilidad
    unproven = HardConstraintGate(config).audit(
        problem, effective, [], (), 0, lambda accepted: accepted
    )
    assert unproven.status is AuditStatus.NO_FEASIBLE_SOLUTION
