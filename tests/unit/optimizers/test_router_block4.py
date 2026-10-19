"""SOL-005, SOL-008, TST-017, MIP-002, MIP-005, NCV-001, NCV-002: routing completo del Bloque 4.

Reglas: QP → OSQP; LP → HiGHS; SOCP → Clarabel; MIQP/MIQCP/MISOCP → solver mixto y jamás OSQP;
NLP no convexo → ``NonConvexBackend`` (sin algoritmos por defecto); EXACT_MIP fuera del
bucle interno.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import scipy.sparse as sparse

from portfolio_engine.exceptions import RoutingError
from portfolio_engine.models.enums import OptimizationFamily, ProblemClass
from portfolio_engine.optimizers import (
    CanonicalProblem,
    ClarabelBackend,
    ConicProblem,
    HiGHSLPBackend,
    MixedIntegerProblem,
    NonConvexBackend,
    NonConvexProblem,
    OSQPBackend,
    SCIPBackend,
    SecondOrderCone,
    SolverRouter,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
ROUTER = SolverRouter.from_engine_config(CONFIG)


def _plain(problem_class: ProblemClass) -> CanonicalProblem:
    return CanonicalProblem(
        name="t",
        problem_class=problem_class,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix(np.eye(2))
        if problem_class is ProblemClass.QP
        else sparse.csc_matrix((2, 2)),
        q=np.zeros(2),
        A=sparse.csc_matrix(np.eye(2)),
        lower=np.zeros(2),
        upper=np.ones(2),
    )


def _socp() -> ConicProblem:
    cone = SecondOrderCone("c", np.eye(2), np.zeros(2), np.zeros(2), 1.0)
    return ConicProblem(
        name="socp",
        problem_class=ProblemClass.SOCP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((2, 2)),
        q=np.ones(2),
        A=sparse.csc_matrix((0, 2)),
        lower=np.zeros(0),
        upper=np.zeros(0),
        cones=(cone,),
    )


def _miqp(with_cone: bool = False) -> MixedIntegerProblem:
    cones = (SecondOrderCone("c", np.eye(2), np.zeros(2), np.zeros(2), 1.0),) if with_cone else ()
    return MixedIntegerProblem(
        name="miqp",
        problem_class=ProblemClass.MISOCP if with_cone else ProblemClass.MIQP,
        family=OptimizationFamily.EXACT_MIP,
        P=sparse.csc_matrix(np.eye(2)),
        q=np.zeros(2),
        A=sparse.csc_matrix(np.eye(2)),
        lower=np.zeros(2),
        upper=np.ones(2),
        binary_indices=(1,),
        cones=cones,
    )


def test_the_four_backend_families_are_routed_by_mathematical_structure() -> None:
    """TST-017: QP→OSQP, LP→HiGHS, SOCP→Clarabel, MIQP→SCIP (nunca OSQP)."""
    assert isinstance(ROUTER.route(_plain(ProblemClass.QP)), OSQPBackend)
    assert isinstance(ROUTER.route(_plain(ProblemClass.LP)), HiGHSLPBackend)
    assert isinstance(ROUTER.route(_socp()), ClarabelBackend)
    assert isinstance(ROUTER.route(_miqp()), SCIPBackend)
    assert isinstance(ROUTER.route(_miqp(with_cone=True)), SCIPBackend)


def test_a_conic_problem_is_never_sent_to_osqp_even_if_it_is_relabelled() -> None:
    relabelled = _socp()
    object.__setattr__(relabelled, "problem_class", ProblemClass.QP)
    with pytest.raises(RoutingError):
        ROUTER.route(relabelled)
    bare = _plain(ProblemClass.QP)
    object.__setattr__(bare, "problem_class", ProblemClass.SOCP)
    with pytest.raises(RoutingError, match="ConicProblem"):
        ROUTER.route(bare)


def test_a_mixed_integer_class_is_never_sent_to_osqp() -> None:
    """MIP-002: la clase entera sin variables binarias no puede enrutarse a ningún QP."""
    for problem_class in (ProblemClass.MIQP, ProblemClass.MIQCP, ProblemClass.MISOCP):
        declared = dataclasses.replace(
            _plain(ProblemClass.QP),
            problem_class=problem_class,
            family=OptimizationFamily.EXACT_MIP,
        )
        with pytest.raises(RoutingError, match="MixedIntegerProblem"):
            ROUTER.route(declared)
    # un QP que declara la familia EXACT_MIP tampoco llega a OSQP
    qp_in_exact_family = dataclasses.replace(
        _plain(ProblemClass.QP), family=OptimizationFamily.EXACT_MIP
    )
    with pytest.raises(RoutingError):
        ROUTER.route(qp_in_exact_family)


def test_exact_mip_and_nonconvex_are_rejected_in_the_production_inner_loop() -> None:
    """MIP-005 (test_exact_mip_not_in_fast_path): con ``inner_loop=True`` el router los rechaza."""
    with pytest.raises(RoutingError, match="bucle interno"):
        ROUTER.route(_miqp(), inner_loop=True)
    with pytest.raises(RoutingError, match="bucle interno"):
        ROUTER.route(_miqp(with_cone=True), inner_loop=True)
    assert isinstance(ROUTER.route(_socp(), inner_loop=True), ClarabelBackend)
    assert isinstance(ROUTER.route(_plain(ProblemClass.QP), inner_loop=True), OSQPBackend)


def test_the_production_inner_loop_engines_are_built_with_the_inner_loop_guard() -> None:
    """Los motores de frontera y la recuperación F-3 crean su router con ``inner_loop=True``."""
    from portfolio_engine.frontiers import ContinuousFrontierEngine, QPCompositionEvaluator
    from portfolio_engine.frontiers.numerical_recovery import NumericalRecovery

    routers = [
        ContinuousFrontierEngine(CONFIG)._router,
        QPCompositionEvaluator(CONFIG)._router,
        NumericalRecovery(CONFIG.solver)._router,
    ]
    for router in routers:
        with pytest.raises(RoutingError, match="bucle interno"):
            router.route(_miqp())


def test_a_router_without_backend_configuration_rejects_with_an_explicit_reason() -> None:
    bare = SolverRouter(CONFIG.solver)
    with pytest.raises(RoutingError, match="ConicSolverConfig"):
        bare.route(_socp())
    with pytest.raises(RoutingError, match="ExactMIPConfig"):
        bare.route(_miqp())
    assert isinstance(bare.route(_plain(ProblemClass.QP)), OSQPBackend)  # contrato del Bloque 2


def test_sdp_is_rejected_because_no_psd_cone_is_implemented() -> None:
    sdp = dataclasses.replace(_plain(ProblemClass.QP), problem_class=ProblemClass.SDP)
    with pytest.raises(RoutingError, match="SDP"):
        ROUTER.route(sdp)


def _nonconvex(convex_alternative: bool) -> NonConvexProblem:
    return NonConvexProblem(
        name="nc",
        problem_class=ProblemClass.NLP_NONCONVEX,
        family=OptimizationFamily.NONCONVEX_RESEARCH,
        P=sparse.csc_matrix((2, 2)),
        q=np.zeros(2),
        A=sparse.csc_matrix(np.eye(2)),
        lower=np.zeros(2),
        upper=np.ones(2),
        objective=lambda x: float(np.sin(x[0])),
        has_convex_reformulation=convex_alternative,
        convex_reformulation="SOCP" if convex_alternative else None,
    )


def test_nonconvex_research_is_only_an_architecture_without_registered_algorithms() -> None:
    """NCV-001, E-25: sin algoritmos registrados el problema no convexo se rechaza."""
    with pytest.raises(RoutingError, match="E-25"):
        ROUTER.route(_nonconvex(False))
    plain = dataclasses.replace(
        _plain(ProblemClass.QP),
        problem_class=ProblemClass.NLP_NONCONVEX,
        family=OptimizationFamily.NONCONVEX_RESEARCH,
    )
    with pytest.raises(RoutingError, match="NonConvexProblem"):
        ROUTER.route(plain)


def test_a_problem_with_a_convex_reformulation_is_rejected_by_the_nonconvex_backend() -> None:
    """NCV-002: si puede mantenerse convexo, no se resuelve como no convexo."""
    from portfolio_engine.optimizers.nonconvex_backend import NonConvexOutcome

    class _Local:
        name = "fake-local-solver"

        def minimize(self, problem: NonConvexProblem, start: object) -> NonConvexOutcome:
            return NonConvexOutcome(np.zeros(2), 0.0, True, True, 1)

    router = SolverRouter.from_engine_config(CONFIG, nonconvex_algorithms=(_Local(),))
    with pytest.raises(RoutingError, match="reformulación convexa"):
        router.route(_nonconvex(True))
    backend = router.route(_nonconvex(False))
    assert isinstance(backend, NonConvexBackend)
    assert backend.algorithms and backend.algorithms[0].name == "fake-local-solver"
    with pytest.raises(RoutingError, match="bucle interno"):
        router.route(_nonconvex(False), inner_loop=True)
