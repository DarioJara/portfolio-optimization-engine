"""SOL-002, VAL-001 (I-1 de AUDIT_BLOCK_3): origen del fallo intermitente del test de propiedades.

``tests/property/test_invariants.py::test_every_frontier_point_satisfies_the_financial_invariants``
falló una vez en una extracción limpia del baseline ``block2-validated``. La causa es reproducible
sin Hypothesis: ``n = 2``, ``seed = 19`` (generador del propio test), ``NET`` con
``TARGET_RETURN_GRID``. Con ``eps_abs = eps_rel = 1e-9`` (valor de ejemplo del proyecto) OSQP agota
las iteraciones con residuales primal 2e-9 y dual 1e-11 y declara ``solved inaccurate``; el punto
se etiqueta ``OPTIMAL_INACCURATE`` (``accept_inaccurate_solutions = false``) y por eso el test de
propiedades, que exige ``is_valid_solution``, lo rechaza **cuando Hypothesis genera ese caso**
(≈ 0,1 % de los casos; ver ``REMEDIATION_BLOCK_3.md``). No es un error financiero: el
``SolutionValidator`` independiente valida el punto. Estos tests fijan el comportamiento correcto
—el estado se distingue, nunca se acepta en silencio— sin tocar tolerancias.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.frontiers import ContinuousFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod, SolverStatus
from tests.fixtures.problems import base_config, make_problem

pytestmark = pytest.mark.unit

N, SEED = 2, 19


def _problem(config):  # type: ignore[no-untyped-def]
    """Mismo generador que ``tests/property/test_invariants.py::frontier_problems``."""
    rng = np.random.default_rng(SEED)
    factor = rng.normal(size=(N, N)) * 0.1
    sigma = factor @ factor.T + np.diag(rng.uniform(0.01, 0.05, N))
    mu = rng.uniform(0.02, 0.15, N)
    raw = rng.uniform(0.05, 1.0, N)
    current = (raw / raw.sum()).tolist()
    buy = rng.uniform(1.0, 200.0, N).tolist()
    sell = rng.uniform(1.0, 200.0, N).tolist()
    return make_problem(
        mu,
        sigma,
        current,
        config,
        universe_overrides={"MaxWeight": [1.0] * N, "BuyCost": buy, "SellCost": sell},
    )


def _solve(config):  # type: ignore[no-untyped-def]
    return ContinuousFrontierEngine(config).solve(
        _problem(config), CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID
    )


def test_an_inaccurate_status_is_never_accepted_silently() -> None:
    """Regla general: todo punto es ``OPTIMAL`` válido, o ``OPTIMAL_INACCURATE`` marcado inválido
    (con su validación independiente disponible); nunca un inexacto contado como válido."""
    result = _solve(base_config())
    assert result.pre_check_feasible and result.points
    for point in result.points:
        if point.status is SolverStatus.OPTIMAL_INACCURATE:
            assert not point.is_valid_solution
            assert point.validation is not None
        else:
            assert point.is_valid_solution


def test_the_configured_tolerance_is_at_the_solver_precision_floor_for_this_case() -> None:
    """Con la tolerancia de ejemplo (1e-9) hay a lo sumo un punto inexacto y, si existe, el
    validador independiente lo encuentra dentro de la tolerancia de validación; con 1e-8 todos los
    puntos convergen (la causa es la tolerancia pedida, no el problema)."""
    strict = base_config()
    inaccurate = [p for p in _solve(strict).points if p.status is SolverStatus.OPTIMAL_INACCURATE]
    assert len(inaccurate) <= 1
    for point in inaccurate:
        assert point.validation is not None and point.validation.is_valid
        assert point.validation.max_violation <= strict.solver.bound_tolerance
    relaxed = base_config(solver={"eps_abs": 1e-8, "eps_rel": 1e-8})
    result = _solve(relaxed)
    assert result.points and all(p.is_valid_solution for p in result.points)
