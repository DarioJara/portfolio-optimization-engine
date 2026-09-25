"""Oráculo de factibilidad independiente del solver cuadrático (F-3; MASTER_SPEC §44-45).

OSQP puede declarar ``INFEASIBLE`` un problema factible cuando su región factible es una franja
casi degenerada (retornos casi idénticos o costes que anulan la pendiente de ``μ``). Antes de
aceptar ese certificado se resuelve, con HiGHS (algoritmo distinto: símplex/punto interior), el LP
de factibilidad con **las mismas filas** ``lower <= A x <= upper`` y objetivo nulo. El oráculo no
reutiliza ningún resultado de OSQP.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.models.enums import OptimizationFamily, ProblemClass, SolverStatus
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers.highs_backend import HiGHSLPBackend
from portfolio_engine.optimizers.problem import CanonicalProblem
from portfolio_engine.optimizers.router import solve_with_policy


class FeasibilityVerdict(StrEnum):
    """Veredicto del LP de factibilidad."""

    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    INCONCLUSIVE = "INCONCLUSIVE"


def lp_feasibility(
    problem: CanonicalProblem,
    lower: npt.NDArray[np.float64],
    config: SolverConfig,
) -> tuple[FeasibilityVerdict, SolveResult]:
    """Factibilidad de ``lower <= A x <= problem.upper`` con un LP de HiGHS de objetivo nulo.

    ``INCONCLUSIVE`` si HiGHS no llega a un veredicto (límite de iteraciones, error numérico).
    """
    size = problem.n_variables
    lp = dataclasses.replace(
        problem,
        name=f"{problem.name}_feasibility",
        problem_class=ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((size, size)),
        q=np.zeros(size),
        lower=lower,
    )
    backend = HiGHSLPBackend(config)
    backend.setup(lp)
    result = solve_with_policy(backend, config.ambiguous_status_policy)
    if result.status is SolverStatus.OPTIMAL:
        return FeasibilityVerdict.FEASIBLE, result
    if result.status is SolverStatus.INFEASIBLE:
        return FeasibilityVerdict.INFEASIBLE, result
    return FeasibilityVerdict.INCONCLUSIVE, result
