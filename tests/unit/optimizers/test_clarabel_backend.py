"""SOL-005, SOL-011, SOL-002 (Clarabel): backend cónico real, capacidades verificadas y estados.

Las capacidades declaradas por ``ClarabelBackend.capabilities`` se comprueban aquí con
comportamiento real (A-37: detección por test, no por suposición).
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import scipy.sparse as sparse

from portfolio_engine.exceptions import RoutingError, SolverError
from portfolio_engine.models.enums import (
    OptimalityClaim,
    OptimizationFamily,
    ProblemClass,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.optimizers import (
    CanonicalProblem,
    ClarabelBackend,
    ConicProblem,
    OSQPBackend,
    SecondOrderCone,
    SolverRouter,
    cross_check_with_second_solver,
    map_clarabel_status,
)
from portfolio_engine.optimizers.clarabel_backend import to_conic_form
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()


def _backend(**conic_changes: object) -> ClarabelBackend:
    conic = dataclasses.replace(CONFIG.conic, **conic_changes)
    return ClarabelBackend(CONFIG.solver, conic)


def _ball_problem(cost: np.ndarray, radius: float = 1.0) -> ConicProblem:
    """``min cᵀx`` sujeto a ``‖x‖₂ <= radius`` (sin filas lineales)."""
    size = cost.shape[0]
    cone = SecondOrderCone("ball", np.eye(size), np.zeros(size), np.zeros(size), radius)
    return ConicProblem(
        name="ball",
        problem_class=ProblemClass.SOCP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((size, size)),
        q=cost,
        A=sparse.csc_matrix((0, size)),
        lower=np.zeros(0),
        upper=np.zeros(0),
        cones=(cone,),
    )


def _linear_problem(
    q: np.ndarray, matrix: np.ndarray, lower: np.ndarray, upper: np.ndarray, quadratic: float = 0.0
) -> CanonicalProblem:
    size = q.shape[0]
    return CanonicalProblem(
        name="linear",
        problem_class=ProblemClass.QP if quadratic else ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix(quadratic * np.eye(size)),
        q=q,
        A=sparse.csc_matrix(matrix),
        lower=lower,
        upper=upper,
    )


def test_a_second_order_cone_problem_matches_its_closed_form() -> None:
    """``min cᵀx`` en la bola unidad tiene solución ``x = −c/‖c‖`` y valor ``−‖c‖``."""
    cost = np.array([3.0, -4.0, 12.0])
    backend = _backend()
    backend.setup(_ball_problem(cost))
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL
    assert result.x is not None
    np.testing.assert_allclose(result.x, -cost / np.linalg.norm(cost), atol=1e-7)
    assert result.objective_value == pytest.approx(-np.linalg.norm(cost), abs=1e-7)
    assert result.solver_name == "CLARABEL" and result.problem_class is ProblemClass.SOCP
    assert result.optimality_claim is OptimalityClaim.CONVEX_GLOBAL
    assert result.primal_residual is not None and result.iterations > 0


def test_linear_rows_and_cones_are_translated_without_approximation() -> None:
    """Igualdad → cono cero; cotas superior/inferior → ortante; cono → segundo orden."""
    problem = _ball_problem(np.array([1.0, 1.0]))
    matrix = np.array([[1.0, 1.0], [1.0, 0.0], [0.0, 1.0]])
    problem = dataclasses.replace(
        problem,
        A=sparse.csc_matrix(matrix),
        lower=np.array([0.5, -np.inf, -0.2]),
        upper=np.array([0.5, 0.7, np.inf]),
    )
    form = to_conic_form(problem, problem.q, problem.lower, problem.upper)
    assert form.equality.tolist() == [True, False, False]
    assert form.above.tolist() == [False, True, False]
    assert form.below.tolist() == [False, False, True]
    assert form.n_linear_rows == 3
    dense = form.A.toarray()
    np.testing.assert_allclose(dense[0], [1.0, 1.0])  # A_eq x = 0.5
    np.testing.assert_allclose(dense[1], [1.0, 0.0])  # A x + s = 0.7
    np.testing.assert_allclose(dense[2], [0.0, -1.0])  # −A x + s = 0.2
    np.testing.assert_allclose(form.b[:3], [0.5, 0.7, 0.2])
    # cono: −[aᵀ; F] x + s = [c; g]  con a = 0, F = I, c = radio = 1, g = 0
    np.testing.assert_allclose(dense[3:], [[0.0, 0.0], [-1.0, 0.0], [0.0, -1.0]])
    np.testing.assert_allclose(form.b[3:], [1.0, 0.0, 0.0])
    assert form.A.shape[0] == 3 + 3  # 3 filas lineales + cono de dimensión 1 + 2


def test_a_quadratic_objective_with_a_cone_is_supported() -> None:
    """``min ½‖x − a‖²`` con ``‖x‖ <= 1`` proyecta ``a`` sobre la bola."""
    target = np.array([3.0, 4.0])
    problem = dataclasses.replace(
        _ball_problem(-target), P=sparse.triu(sparse.csc_matrix(np.eye(2)), format="csc")
    )
    backend = _backend()
    backend.setup(problem)
    result = backend.solve()
    assert result.x is not None
    np.testing.assert_allclose(result.x, target / np.linalg.norm(target), atol=1e-7)


def test_infeasible_and_unbounded_problems_are_not_confused_with_numerical_errors() -> None:
    infeasible = dataclasses.replace(
        _ball_problem(np.array([1.0, 1.0])),
        A=sparse.csc_matrix(np.array([[1.0, 0.0]])),
        lower=np.array([2.0]),
        upper=np.array([np.inf]),
    )
    backend = _backend()
    backend.setup(infeasible)
    result = backend.solve()
    assert result.status is SolverStatus.INFEASIBLE and result.x is None
    unbounded = _linear_problem(
        np.array([-1.0]), np.array([[1.0]]), np.array([0.0]), np.array([np.inf])
    )
    backend = _backend()
    backend.setup(unbounded)
    result = backend.solve()
    assert result.status is SolverStatus.UNBOUNDED and result.x is None


def test_the_status_mapping_never_promotes_inaccurate_or_suspected_certificates() -> None:
    """Un resultado ``Almost*`` nunca es firme: ``AlmostSolved`` sigue siendo inaccurate y los
    certificados de inviabilidad aproximados son un error numérico, no inviabilidad."""
    assert map_clarabel_status("Solved") is SolverStatus.OPTIMAL
    assert map_clarabel_status("AlmostSolved") is SolverStatus.OPTIMAL_INACCURATE
    assert map_clarabel_status("PrimalInfeasible") is SolverStatus.INFEASIBLE
    assert map_clarabel_status("DualInfeasible") is SolverStatus.UNBOUNDED
    assert map_clarabel_status("AlmostPrimalInfeasible") is SolverStatus.NUMERICAL_ERROR
    assert map_clarabel_status("AlmostDualInfeasible") is SolverStatus.NUMERICAL_ERROR
    assert map_clarabel_status("MaxIterations") is SolverStatus.MAX_ITERATIONS
    assert map_clarabel_status("MaxTime") is SolverStatus.TIME_LIMIT
    assert map_clarabel_status("NumericalError") is SolverStatus.NUMERICAL_ERROR
    assert map_clarabel_status("InsufficientProgress") is SolverStatus.INSUFFICIENT_PROGRESS
    assert map_clarabel_status("CallbackTerminated") is SolverStatus.UNKNOWN
    assert map_clarabel_status("SomethingNew") is SolverStatus.UNKNOWN


def test_an_iteration_limit_is_reported_as_such_and_the_cold_retry_uses_more_iterations() -> None:
    hard = _ball_problem(np.array([1.0, 2.0, 3.0, 4.0]))
    backend = _backend(max_iterations=2)
    backend.setup(hard)
    first = backend.solve()
    assert first.status is SolverStatus.MAX_ITERATIONS and first.x is None
    retried = backend.cold_retry()
    assert retried.status_source is StatusSource.CROSS_CHECK and retried.cold_retries == 1
    assert retried.iterations > first.iterations
    # el reintento no mejora artificialmente un estado: un AlmostSolved sigue siendo inaccurate
    expected = (
        SolverStatus.OPTIMAL_INACCURATE
        if retried.native_status == "AlmostSolved"
        else SolverStatus.OPTIMAL
    )
    assert retried.status is expected


def test_update_reuses_the_workspace_when_the_row_structure_is_unchanged() -> None:
    """``update`` de ``q`` y de las cotas modifica el workspace vivo (SOL-011, capacidad real)."""
    problem = dataclasses.replace(
        _ball_problem(np.array([-1.0, -1.0])),
        A=sparse.csc_matrix(np.array([[1.0, 0.0]])),
        lower=np.array([-np.inf]),
        upper=np.array([10.0]),
    )
    backend = _backend()
    backend.setup(problem)
    first = backend.solve()
    backend.update(q=np.array([-1.0, -3.0]))
    second = backend.solve()
    backend.update(upper=np.array([0.2]))
    third = backend.solve()
    assert backend.setup_count == 1 and backend.update_count == 2
    assert backend.updated_fields == ("q", "upper")
    assert first.x is not None and second.x is not None and third.x is not None
    np.testing.assert_allclose(third.x[0], 0.2, atol=1e-7)
    assert not np.allclose(first.x, second.x)


def test_a_change_of_row_structure_rebuilds_the_problem_and_is_counted_as_a_setup() -> None:
    problem = dataclasses.replace(
        _ball_problem(np.array([-1.0, -1.0])),
        A=sparse.csc_matrix(np.array([[1.0, 0.0]])),
        lower=np.array([-np.inf]),
        upper=np.array([0.3]),
    )
    backend = _backend()
    backend.setup(problem)
    backend.solve()
    backend.update(upper=np.array([np.inf]))  # la fila deja de tener cota finita
    result = backend.solve()
    assert backend.setup_count == 2
    assert result.x is not None
    np.testing.assert_allclose(result.x, [1 / np.sqrt(2)] * 2, atol=1e-7)


def test_declared_capabilities_are_real() -> None:
    """SOL-011: cada capacidad declarada se comprueba con comportamiento, no se supone."""
    backend = _backend()
    capabilities = backend.capabilities
    assert capabilities.supports_socp and capabilities.supports_qp
    assert capabilities.supports_vector_update and not capabilities.supports_matrix_update
    assert not capabilities.supports_warm_start and not capabilities.supports_factorization_reuse
    assert not capabilities.supports_integer and not capabilities.supports_nonconvex
    assert not capabilities.supports_sdp
    assert backend.supports(ProblemClass.SOCP) and backend.supports(ProblemClass.QP)
    assert not backend.supports(ProblemClass.SDP) and not backend.supports(ProblemClass.MIQP)
    backend.setup(_ball_problem(np.array([1.0, 1.0])))
    with pytest.raises(SolverError, match="arranque en caliente"):
        backend.warm_start(x=np.zeros(2))


def test_the_backend_rejects_what_it_cannot_solve() -> None:
    backend = _backend()
    with pytest.raises(SolverError, match="setup"):
        backend.solve()
    mixed = CanonicalProblem(
        name="x",
        problem_class=ProblemClass.MIQP,
        family=OptimizationFamily.EXACT_MIP,
        P=sparse.csc_matrix((1, 1)),
        q=np.zeros(1),
        A=sparse.csc_matrix((0, 1)),
        lower=np.zeros(0),
        upper=np.zeros(0),
    )
    with pytest.raises(SolverError, match="MIQP"):
        backend.setup(mixed)


def test_osqp_refuses_a_conic_problem_instead_of_ignoring_its_cones() -> None:
    """Un SOCP jamás se disfraza de QP: OSQP lo rechaza por clase y por tipo."""
    with pytest.raises(SolverError, match="OSQP"):
        OSQPBackend(CONFIG.solver).setup(_ball_problem(np.array([1.0, 1.0])))
    disguised = dataclasses.replace(_ball_problem(np.array([1.0, 1.0])))
    object.__setattr__(disguised, "problem_class", ProblemClass.QP)
    with pytest.raises(SolverError, match="OSQP"):
        OSQPBackend(CONFIG.solver).setup(disguised)
    router = SolverRouter.from_engine_config(CONFIG)
    assert isinstance(router.route(_ball_problem(np.array([1.0, 1.0]))), ClarabelBackend)
    with pytest.raises(RoutingError, match="cónico"):
        router.route(disguised)


def test_clarabel_cross_checks_an_osqp_solution() -> None:
    """SOL-014: un segundo solver de otra familia confirma (o no) la solución de OSQP."""
    q = np.array([-1.0, -2.0, -0.5])
    matrix = np.vstack([np.ones((1, 3)), np.eye(3)])
    lower = np.array([1.0, 0.0, 0.0, 0.0])
    upper = np.array([1.0, 0.6, 0.6, 0.6])
    problem = _linear_problem(q, matrix, lower, upper, quadratic=2.0)
    problem = dataclasses.replace(problem, P=sparse.triu(problem.P, format="csc"))
    router = SolverRouter.from_engine_config(CONFIG)
    osqp_backend = router.route(problem)
    assert isinstance(osqp_backend, OSQPBackend)
    osqp_backend.setup(problem)
    first = osqp_backend.solve()
    report = cross_check_with_second_solver(problem, first, router, 1e-6)
    assert report.second.solver_name == "CLARABEL"
    assert report.agree is True
    assert report.max_abs_solution_difference is not None
    assert report.max_abs_solution_difference < 1e-4


def test_a_conic_problem_needs_a_cone_and_the_socp_class() -> None:
    with pytest.raises(SolverError, match="SOCP"):
        ConicProblem(
            name="x",
            problem_class=ProblemClass.QP,
            family=OptimizationFamily.FAST_PRODUCTION,
            P=sparse.csc_matrix((1, 1)),
            q=np.zeros(1),
            A=sparse.csc_matrix((0, 1)),
            lower=np.zeros(0),
            upper=np.zeros(0),
            cones=(SecondOrderCone("c", np.eye(1), np.zeros(1), np.zeros(1), 1.0),),
        )
    with pytest.raises(SolverError, match="cono"):
        ConicProblem(
            name="x",
            problem_class=ProblemClass.SOCP,
            family=OptimizationFamily.FAST_PRODUCTION,
            P=sparse.csc_matrix((1, 1)),
            q=np.zeros(1),
            A=sparse.csc_matrix((0, 1)),
            lower=np.zeros(0),
            upper=np.zeros(0),
        )
