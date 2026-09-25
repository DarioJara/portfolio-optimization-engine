"""SOL-002, OPT-003 (remediación F-3): normalización reversible de la fila de retorno y oráculo LP.

La normalización (centrado con la fila de presupuesto + escalado) es una transformación *exacta* del
conjunto factible: mismas variables, mismo objetivo, mismas demás filas. El oráculo de factibilidad
resuelve las mismas filas con HiGHS y objetivo nulo, sin usar ningún resultado de OSQP.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod, SolverStatus
from portfolio_engine.optimizers import FeasibilityVerdict, lp_feasibility
from tests.fixtures import near_degenerate as nd
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()
ENGINE = ContinuousFrontierEngine(CONFIG)
HORIZON = CONFIG.optimization_horizon_years


def _built(inst: nd.Instance, treatment: CostTreatment):  # type: ignore[no-untyped-def]
    session = ENGINE.open_session(inst.problem, treatment, FrontierMethod.TARGET_RETURN_GRID)
    return session.variance_problem


@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
@pytest.mark.parametrize("weight_scale", [1.0, 10.0, 100.0])
def test_the_normalized_row_is_an_exact_rescaling_of_the_original_constraint(
    treatment: CostTreatment, weight_scale: float
) -> None:
    """Para todo ``x`` con ``1ᵀw = 1``: ``fila'·x − cota' = s·(fila·x − cota)`` (mismo signo y
    mismo conjunto factible); las demás filas, ``P``, ``q`` y las cotas superiores no cambian."""
    built = _built(nd.instance(3, 67), treatment)
    problem = built.problem
    target = 0.11
    normalized = built.normalize_return_row(weight_scale)
    assert normalized is not None
    lower = built.lower_for_target(target)
    mapped = normalized.lower_for(lower)
    rng = np.random.default_rng(3)
    row = built.return_row
    for _ in range(50):
        x = rng.normal(size=problem.n_variables)
        x[: built.n_weights] += (1.0 - x[: built.n_weights].sum()) / built.n_weights  # 1ᵀw = 1
        original = float(problem.A.getrow(row).toarray().ravel() @ x) - lower[row]
        transformed = float(normalized.problem.A.getrow(row).toarray().ravel() @ x) - mapped[row]
        assert transformed == pytest.approx(normalized.row_scale * original, rel=1e-9, abs=1e-12)
    keep = np.arange(problem.n_constraints) != row
    assert (normalized.problem.A.toarray()[keep] == problem.A.toarray()[keep]).all()
    assert (mapped[keep] == lower[keep]).all()
    assert (normalized.problem.upper == problem.upper).all()
    assert (normalized.problem.q == problem.q).all()
    assert (problem.P != normalized.problem.P).nnz == 0
    assert normalized.problem.n_variables == problem.n_variables


@pytest.mark.parametrize("weight_scale", [1.0, 10.0, 100.0])
def test_the_largest_weight_coefficient_of_the_normalized_row_is_the_requested_scale(
    weight_scale: float,
) -> None:
    built = _built(nd.instance(2, 84), CostTreatment.GROSS)
    normalized = built.normalize_return_row(weight_scale)
    assert normalized is not None
    row = normalized.problem.A.getrow(built.return_row).toarray().ravel()[: built.n_weights]
    assert np.abs(row).max() == pytest.approx(weight_scale, rel=1e-12)
    assert row.sum() == pytest.approx(0.0, abs=1e-9 * weight_scale)  # centrada: ⟂ presupuesto


def test_identical_returns_leave_nothing_to_normalize() -> None:
    inst = nd.custom_instance(np.full(3, 0.07), np.diag([0.02, 0.03, 0.04]), np.full(3, 1 / 3))
    assert _built(inst, CostTreatment.GROSS).normalize_return_row(10.0) is None


# ----------------------------------------------------------------------------- oráculo LP


@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_the_lp_oracle_separates_feasible_from_infeasible_targets(
    treatment: CostTreatment,
) -> None:
    inst = nd.instance(3, 67)
    built = _built(inst, treatment)
    best = nd.lp_max_return(inst, treatment, HORIZON)
    below, _ = lp_feasibility(built.problem, built.lower_for_target(best - 1e-6), CONFIG.solver)
    above, result = lp_feasibility(
        built.problem, built.lower_for_target(best + 1e-3), CONFIG.solver
    )
    assert below is FeasibilityVerdict.FEASIBLE
    assert above is FeasibilityVerdict.INFEASIBLE and result.status is SolverStatus.INFEASIBLE


@pytest.mark.parametrize("override", [{"lp_max_iterations": 1}, {"time_limit_seconds": 1e-9}])
def test_the_lp_oracle_is_inconclusive_when_highs_reaches_a_limit(
    override: dict[str, float],
) -> None:
    """Un límite de iteraciones o de tiempo no se toma por factibilidad ni por infactibilidad."""
    config = base_config(solver=override)
    inst = nd.instance(3, 67)
    built = _built(inst, CostTreatment.NET)
    verdict, result = lp_feasibility(built.problem, built.lower_for_target(0.13), config.solver)
    assert verdict is FeasibilityVerdict.INCONCLUSIVE
    assert result.status in {SolverStatus.MAX_ITERATIONS, SolverStatus.TIME_LIMIT}


def test_the_oracle_does_not_modify_the_quadratic_problem() -> None:
    built = _built(nd.instance(2, 84), CostTreatment.GROSS)
    before = (built.problem.P.copy(), built.problem.q.copy(), built.problem.lower.copy())
    lp_feasibility(built.problem, built.lower_for_target(0.05677), CONFIG.solver)
    assert (before[0] != built.problem.P).nnz == 0
    assert (built.problem.q == before[1]).all() and (built.problem.lower == before[2]).all()
