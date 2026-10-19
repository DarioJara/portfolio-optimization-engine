"""SOL-006, MIP-002, MIP-007: ``MixedIntegerBackend`` con SCIP como referencia (E-24).

El MIQP se contrasta con una enumeración exhaustiva de composiciones resueltas con el QP validado
del Bloque 2 (oráculo independiente del solver mixto).
"""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pytest
import scipy.sparse as sparse

import portfolio_engine.optimizers.router as router_module
from portfolio_engine.exceptions import RoutingError, SolverError
from portfolio_engine.models.enums import (
    OptimalityClaim,
    OptimizationFamily,
    ProblemClass,
    SolverStatus,
)
from portfolio_engine.optimizers import (
    SCIP_AVAILABLE,
    CanonicalProblem,
    MixedIntegerProblem,
    SCIPBackend,
    SecondOrderCone,
    SolverRouter,
    mixed_integer_availability,
)
from tests.fixtures.problems import base_config
from tests.fixtures.reference import slsqp_qp

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(not SCIP_AVAILABLE, reason="PySCIPOpt (opcional, E-24) no instalado"),
]

CONFIG = base_config()


def _cardinality_problem(
    sigma: np.ndarray, mu: np.ndarray, theta: float, k: int, low: float, high: float
) -> MixedIntegerProblem:
    """``min wᵀΣw − θ μᵀw`` con ``low·z <= w <= high·z``, ``Σz = k`` y ``Σw = 1``."""
    n = mu.shape[0]
    p_matrix = np.zeros((2 * n, 2 * n))
    p_matrix[:n, :n] = 2.0 * sigma
    rows, lower, upper = [], [], []
    budget = np.zeros(2 * n)
    budget[:n] = 1.0
    rows.append(budget)
    lower.append(1.0)
    upper.append(1.0)
    count = np.zeros(2 * n)
    count[n:] = 1.0
    rows.append(count)
    lower.append(float(k))
    upper.append(float(k))
    for i in range(n):
        up = np.zeros(2 * n)
        up[i], up[n + i] = 1.0, -high
        rows.append(up)
        lower.append(-np.inf)
        upper.append(0.0)
        lo = np.zeros(2 * n)
        lo[i], lo[n + i] = 1.0, -low
        rows.append(lo)
        lower.append(0.0)
        upper.append(np.inf)
        unit = np.zeros(2 * n)
        unit[n + i] = 1.0
        rows.append(unit)
        lower.append(0.0)
        upper.append(1.0)
    return MixedIntegerProblem(
        name="cardinality",
        problem_class=ProblemClass.MIQP,
        family=OptimizationFamily.EXACT_MIP,
        P=sparse.triu(sparse.csc_matrix(p_matrix), format="csc"),
        q=np.concatenate([-theta * mu, np.zeros(n)]),
        A=sparse.csc_matrix(np.array(rows)),
        lower=np.array(lower),
        upper=np.array(upper),
        binary_indices=tuple(range(n, 2 * n)),
    )


def _instance(seed: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, n))
    sigma = factor @ factor.T / n * 0.05 + 0.01 * np.eye(n)
    return sigma, rng.uniform(0.02, 0.14, n)


def _enumerate_best(
    sigma: np.ndarray, mu: np.ndarray, theta: float, k: int, low: float, high: float
) -> tuple[float, tuple[int, ...]]:
    best = (np.inf, ())
    for subset in itertools.combinations(range(mu.shape[0]), k):
        idx = list(subset)
        sub = sigma[np.ix_(idx, idx)]
        try:
            weights = slsqp_qp(
                sub, -theta * mu[idx], np.full(k, low), np.full(k, high), start=np.full(k, 1.0 / k)
            )
        except AssertionError:
            continue
        value = float(weights @ sub @ weights - theta * mu[idx] @ weights)
        if value < best[0]:
            best = (value, subset)
    return best


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_miqp_matches_exhaustive_enumeration(seed: int) -> None:
    """MIP-001 (test_formulation): el óptimo del MIQP es el de la mejor composición enumerada."""
    n, k, theta, low, high = 8, 3, 3.0, 0.1, 0.6
    sigma, mu = _instance(seed, n)
    problem = _cardinality_problem(sigma, mu, theta, k, low, high)
    backend = SCIPBackend(CONFIG.exact_mip, seed=CONFIG.random_seed)
    backend.setup(problem)
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL
    assert result.optimality_claim is OptimalityClaim.MIP_PROVEN
    assert result.solver_name == "SCIP" and result.x is not None
    z = result.x[n:]
    assert np.all(np.abs(z - np.round(z)) < 1e-6) and round(z.sum()) == k
    best_value, best_subset = _enumerate_best(sigma, mu, theta, k, low, high)
    assert result.objective_value == pytest.approx(best_value, abs=1e-5)
    assert tuple(np.flatnonzero(np.round(z) > 0.5).tolist()) == best_subset
    mip = result.mip
    assert mip is not None and mip.has_valid_dual_bound
    assert mip.dual_bound is not None and mip.dual_bound <= best_value + 1e-6


def test_a_misocp_with_a_volatility_cone_matches_enumeration() -> None:
    """MIP-006: MISOCP con ``‖Lᵀw‖ <= σ_max`` frente a la enumeración con Clarabel."""
    n, k, theta = 6, 3, 2.0
    sigma, mu = _instance(4, n)
    problem = _cardinality_problem(sigma, mu, theta, k, 0.05, 0.8)
    loading = np.linalg.cholesky(sigma)
    limit = float(np.sqrt(np.full(n, 1.0 / n) @ sigma @ np.full(n, 1.0 / n))) * 1.6
    height = np.zeros(2 * n)
    cone = SecondOrderCone(
        "vol", np.hstack([loading.T, np.zeros((n, n))]), np.zeros(n), height, limit
    )
    mixed = dataclasses.replace(problem)
    object.__setattr__(mixed, "problem_class", ProblemClass.MISOCP)
    object.__setattr__(mixed, "cones", (cone,))
    backend = SCIPBackend(CONFIG.exact_mip, seed=1)
    backend.setup(mixed)
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    weights = result.x[:n]
    assert float(np.sqrt(weights @ sigma @ weights)) <= limit + 1e-6
    # cualquier composición con volatilidad <= límite no mejora el óptimo del MISOCP
    best = np.inf
    for subset in itertools.combinations(range(n), k):
        idx = list(subset)
        sub = sigma[np.ix_(idx, idx)]
        try:
            w = slsqp_qp(
                sub,
                -theta * mu[idx],
                np.full(k, 0.05),
                np.full(k, 0.8),
                start=np.full(k, 1.0 / k),
                extra_ineq=[(np.ones(k), 0.0, np.inf)],
            )
        except AssertionError:
            continue
        if np.sqrt(w @ sub @ w) <= limit + 1e-9:
            best = min(best, float(w @ sub @ w - theta * mu[idx] @ w))
    assert result.objective_value == pytest.approx(best, abs=1e-4)


def test_a_limit_never_yields_a_proven_optimum_without_a_solution_and_reports_no_false_gap() -> (
    None
):
    """Un límite de tiempo/nodos jamás es ``OPTIMAL`` con una afirmación de optimalidad probada."""
    sigma, mu = _instance(5, 30)
    problem = _cardinality_problem(sigma, mu, 3.0, 10, 0.02, 0.3)
    limited = dataclasses.replace(CONFIG.exact_mip, time_limit_seconds=0.001, node_limit=1)
    backend = SCIPBackend(limited, seed=1)
    backend.setup(problem)
    result = backend.solve()
    if result.status is SolverStatus.OPTIMAL:
        assert result.optimality_claim is OptimalityClaim.MIP_PROVEN
    else:
        assert result.x is None
        assert result.optimality_claim is not OptimalityClaim.MIP_PROVEN
        mip = result.mip
        assert mip is not None
        if not mip.has_valid_dual_bound:
            assert result.optimality_claim in (
                OptimalityClaim.FEASIBLE_ONLY,
                OptimalityClaim.NOT_ASSESSED,
            )
    assert result.status is not SolverStatus.OPTIMAL_INACCURATE


def test_the_backend_accepts_a_hint_and_never_supports_updates() -> None:
    n, k = 6, 3
    sigma, mu = _instance(6, n)
    problem = _cardinality_problem(sigma, mu, 3.0, k, 0.1, 0.6)
    backend = SCIPBackend(CONFIG.exact_mip, seed=1)
    backend.setup(problem)
    hint = np.zeros(2 * n)
    hint[[0, 1, 2]] = 1.0 / 3.0
    hint[[n, n + 1, n + 2]] = 1.0
    backend.hint(hint)
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL
    with pytest.raises(SolverError, match="update"):
        backend.update(q=np.zeros(2 * n))
    with pytest.raises(SolverError):
        backend.warm_start(y=np.zeros(1))
    with pytest.raises(SolverError):
        backend.hint(np.zeros(3))
    assert backend.update_count == 0 and backend.updated_fields == ()
    retried = backend.cold_retry()
    assert retried.cold_retries == 1 and retried.status is SolverStatus.OPTIMAL


def test_the_backend_only_accepts_mixed_integer_problems() -> None:
    backend = SCIPBackend(CONFIG.exact_mip, seed=1)
    plain = CanonicalProblem(
        name="x",
        problem_class=ProblemClass.MIQP,
        family=OptimizationFamily.EXACT_MIP,
        P=sparse.csc_matrix((1, 1)),
        q=np.zeros(1),
        A=sparse.csc_matrix((0, 1)),
        lower=np.zeros(0),
        upper=np.zeros(0),
    )
    with pytest.raises(SolverError, match="MixedIntegerProblem"):
        backend.setup(plain)
    with pytest.raises(SolverError, match="setup"):
        backend.solve()
    assert backend.capabilities.supports_integer and not backend.capabilities.supports_vector_update


def test_mixed_integer_problems_are_validated_at_construction() -> None:
    base = dict(
        name="x",
        P=sparse.csc_matrix((2, 2)),
        q=np.zeros(2),
        A=sparse.csc_matrix((0, 2)),
        lower=np.zeros(0),
        upper=np.zeros(0),
    )
    with pytest.raises(SolverError, match="EXACT_MIP"):
        MixedIntegerProblem(
            problem_class=ProblemClass.MIQP,
            family=OptimizationFamily.FAST_PRODUCTION,
            binary_indices=(0,),
            **base,
        )
    with pytest.raises(SolverError, match="no vacío"):
        MixedIntegerProblem(
            problem_class=ProblemClass.MIQP, family=OptimizationFamily.EXACT_MIP, **base
        )
    with pytest.raises(SolverError, match="fuera de rango"):
        MixedIntegerProblem(
            problem_class=ProblemClass.MIQP,
            family=OptimizationFamily.EXACT_MIP,
            binary_indices=(5,),
            **base,
        )
    with pytest.raises(SolverError, match="MIQP no lleva conos"):
        MixedIntegerProblem(
            problem_class=ProblemClass.MIQP,
            family=OptimizationFamily.EXACT_MIP,
            binary_indices=(0,),
            cones=(SecondOrderCone("c", np.eye(2), np.zeros(2), np.zeros(2), 1.0),),
            **base,
        )


def test_scip_is_the_reference_and_commercial_backends_are_optional_never_required() -> None:
    """MIP-007 (test_scip_reference / test_commercial_optional): el paquete funciona sin
    solvers comerciales; uno ausente se reporta como no disponible, sin error."""
    entries = {entry.name: entry for entry in mixed_integer_availability()}
    assert entries["SCIP"].usable and entries["SCIP"].installed and entries["SCIP"].implemented
    for name in ("GUROBI", "CPLEX", "MOSEK"):
        assert not entries[name].usable  # ningún adaptador comercial es obligatorio
        assert entries[name].reason


def test_a_missing_scip_is_diagnosed_and_never_replaced_by_another_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin PySCIPOpt el router rechaza con el motivo; no sustituye el MIQP por otro algoritmo."""
    monkeypatch.setattr(router_module, "SCIP_AVAILABLE", False)
    problem = _cardinality_problem(*_instance(7, 5), 2.0, 2, 0.1, 0.9)
    with pytest.raises(RoutingError, match="PySCIPOpt"):
        SolverRouter.from_engine_config(CONFIG).route(problem)
