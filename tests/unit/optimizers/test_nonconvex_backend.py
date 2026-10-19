"""NCV-001, NCV-002, NCV-004, SOL-007: arquitectura de NONCONVEX_RESEARCH (E-25).

No existe ningún algoritmo no convexo concreto: el registro está vacío por defecto y el backend
solo demuestra que sus garantías de optimalidad no pueden confundirse con un óptimo global.
"""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sparse

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import (
    OptimalityClaim,
    OptimizationFamily,
    ProblemClass,
    SolverStatus,
)
from portfolio_engine.optimizers import NonConvexBackend, NonConvexOutcome, NonConvexProblem

pytestmark = pytest.mark.unit


def _problem(convex: bool = False) -> NonConvexProblem:
    return NonConvexProblem(
        name="nc",
        problem_class=ProblemClass.NLP_NONCONVEX,
        family=OptimizationFamily.NONCONVEX_RESEARCH,
        P=sparse.csc_matrix((2, 2)),
        q=np.zeros(2),
        A=sparse.csc_matrix(np.eye(2)),
        lower=np.zeros(2),
        upper=np.ones(2),
        objective=lambda x: float(np.cos(3.0 * x[0]) + x[1]),
        has_convex_reformulation=convex,
        convex_reformulation="SOCP" if convex else None,
    )


class _Algorithm:
    """Algoritmo de mentira (solo para ejercitar el contrato del backend)."""

    def __init__(self, converged: bool, feasible: bool = True) -> None:
        self.name = "fake"
        self._converged = converged
        self._feasible = feasible

    def minimize(self, problem: NonConvexProblem, start: object) -> NonConvexOutcome:
        return NonConvexOutcome(
            np.array([0.5, 0.0]),
            problem.objective(np.array([0.5, 0.0])) if problem.objective else 0.0,
            self._converged,
            self._feasible,
            7,
        )


def test_the_registry_is_empty_by_default_and_the_backend_refuses_to_pretend() -> None:
    """test_registry_empty_by_default / test_no_algorithm_registered_raises."""
    backend = NonConvexBackend()
    assert backend.algorithms == ()
    with pytest.raises(SolverError, match="E-25"):
        backend.setup(_problem())
    with pytest.raises(SolverError, match="setup"):
        backend.solve()


def test_a_convex_reformulable_problem_is_never_solved_as_nonconvex() -> None:
    backend = NonConvexBackend((_Algorithm(True),))
    with pytest.raises(SolverError, match="reformulación convexa"):
        backend.setup(_problem(convex=True))


def test_a_local_result_never_claims_global_optimality() -> None:
    """NCV-004: local ⇒ ``LOCAL``; solo factible ⇒ ``FEASIBLE_ONLY``; nunca global."""
    backend = NonConvexBackend((_Algorithm(True),))
    backend.setup(_problem())
    local = backend.solve()
    assert local.status is SolverStatus.OPTIMAL
    assert local.optimality_claim is OptimalityClaim.LOCAL
    assert local.optimality_claim not in (OptimalityClaim.CONVEX_GLOBAL, OptimalityClaim.MIP_PROVEN)
    weak = NonConvexBackend((_Algorithm(False),))
    weak.setup(_problem())
    result = weak.solve()
    assert result.status is SolverStatus.INSUFFICIENT_PROGRESS and result.x is None
    assert result.optimality_claim is OptimalityClaim.FEASIBLE_ONLY
    infeasible = NonConvexBackend((_Algorithm(True, feasible=False),))
    infeasible.setup(_problem())
    dead = infeasible.solve()
    assert dead.optimality_claim is OptimalityClaim.NOT_ASSESSED and dead.x is None


def test_the_problem_declares_its_class_family_and_objective() -> None:
    with pytest.raises(SolverError, match="NLP_NONCONVEX"):
        NonConvexProblem(
            name="x",
            problem_class=ProblemClass.QP,
            family=OptimizationFamily.NONCONVEX_RESEARCH,
            P=sparse.csc_matrix((1, 1)),
            q=np.zeros(1),
            A=sparse.csc_matrix((0, 1)),
            lower=np.zeros(0),
            upper=np.zeros(0),
            objective=lambda x: 0.0,
        )
    with pytest.raises(SolverError, match="objetivo"):
        NonConvexProblem(
            name="x",
            problem_class=ProblemClass.NLP_NONCONVEX,
            family=OptimizationFamily.NONCONVEX_RESEARCH,
            P=sparse.csc_matrix((1, 1)),
            q=np.zeros(1),
            A=sparse.csc_matrix((0, 1)),
            lower=np.zeros(0),
            upper=np.zeros(0),
        )


def test_the_backend_does_not_support_updates_or_dual_starts() -> None:
    backend = NonConvexBackend((_Algorithm(True),))
    with pytest.raises(SolverError):
        backend.update(q=np.zeros(2))
    with pytest.raises(SolverError):
        backend.warm_start(y=np.zeros(2))
    assert backend.capabilities.supports_nonconvex and not backend.capabilities.supports_qp
    assert backend.supports(ProblemClass.NLP_NONCONVEX) and not backend.supports(ProblemClass.QP)
