"""OPT-005, SOL-008, TST-017 (QP→OSQP): routing por clase de problema y familia."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import scipy.sparse as sparse

from portfolio_engine.exceptions import RoutingError
from portfolio_engine.models.enums import OptimizationFamily, ProblemClass
from portfolio_engine.optimizers import (
    CanonicalProblem,
    HiGHSLPBackend,
    OSQPBackend,
    SolverRouter,
)
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def _problem(problem_class: ProblemClass, family: OptimizationFamily) -> CanonicalProblem:
    return CanonicalProblem(
        name="t",
        problem_class=problem_class,
        family=family,
        P=sparse.csc_matrix(np.eye(1)),
        q=np.zeros(1),
        A=sparse.csc_matrix(np.eye(1)),
        lower=np.zeros(1),
        upper=np.ones(1),
    )


ROUTER = SolverRouter(base_config().solver)


def test_routing_qp_to_osqp() -> None:
    backend = ROUTER.route(_problem(ProblemClass.QP, OptimizationFamily.FAST_PRODUCTION))
    assert isinstance(backend, OSQPBackend)


def test_routing_lp_to_highs() -> None:
    """R2-01: el LP de MaximumReturn (P = 0) va a HiGHS; OSQP sigue siendo el backend de los QP."""
    backend = ROUTER.route(_problem(ProblemClass.LP, OptimizationFamily.FAST_PRODUCTION))
    assert isinstance(backend, HiGHSLPBackend) and not isinstance(backend, OSQPBackend)


def test_each_route_call_returns_a_new_workspace_owner() -> None:
    problem = _problem(ProblemClass.QP, OptimizationFamily.FAST_PRODUCTION)
    assert ROUTER.route(problem) is not ROUTER.route(problem)


@pytest.mark.parametrize(
    "problem_class", [ProblemClass.MIQP, ProblemClass.MIQCP, ProblemClass.MISOCP]
)
def test_miqp_not_routed_to_osqp(problem_class: ProblemClass) -> None:
    """MIP-002: ninguna clase mixta entera llega a OSQP; se rechaza explícitamente."""
    with pytest.raises(RoutingError, match="mixto entero"):
        ROUTER.route(_problem(problem_class, OptimizationFamily.EXACT_MIP))


@pytest.mark.parametrize("problem_class", [ProblemClass.SOCP, ProblemClass.SDP])
def test_conic_problems_are_rejected_until_block_4(problem_class: ProblemClass) -> None:
    with pytest.raises(RoutingError, match="Clarabel"):
        ROUTER.route(_problem(problem_class, OptimizationFamily.FAST_PRODUCTION))


def test_other_classes_and_families_are_never_degraded_to_osqp() -> None:
    with pytest.raises(RoutingError, match="NonConvex"):
        ROUTER.route(_problem(ProblemClass.NLP_NONCONVEX, OptimizationFamily.NONCONVEX_RESEARCH))
    with pytest.raises(RoutingError):
        ROUTER.route(_problem(ProblemClass.HEURISTIC, OptimizationFamily.FAST_PRODUCTION))
    qp_in_exact_family = dataclasses.replace(
        _problem(ProblemClass.QP, OptimizationFamily.FAST_PRODUCTION),
        family=OptimizationFamily.EXACT_MIP,
    )
    with pytest.raises(RoutingError):
        ROUTER.route(qp_in_exact_family)
