"""SOL-001, SOL-002: estados normalizados y mapeo de todos los estados nativos de OSQP."""

from __future__ import annotations

import pytest

from portfolio_engine.models.enums import SolverStatus
from portfolio_engine.optimizers import AMBIGUOUS_STATUSES, map_osqp_status
from portfolio_engine.optimizers.status import OSQP_STATUS_MAP

pytestmark = pytest.mark.unit


def test_enum_complete() -> None:
    """SOL-001: exactamente los nueve estados del MASTER_SPEC §45."""
    assert [status.name for status in SolverStatus] == [
        "OPTIMAL",
        "OPTIMAL_INACCURATE",
        "INFEASIBLE",
        "UNBOUNDED",
        "MAX_ITERATIONS",
        "TIME_LIMIT",
        "NUMERICAL_ERROR",
        "INSUFFICIENT_PROGRESS",
        "UNKNOWN",
    ]


@pytest.mark.parametrize(
    ("native", "expected"),
    [
        ("solved", SolverStatus.OPTIMAL),
        ("solved inaccurate", SolverStatus.OPTIMAL_INACCURATE),
        ("primal infeasible", SolverStatus.INFEASIBLE),
        ("primal infeasible inaccurate", SolverStatus.NUMERICAL_ERROR),
        ("dual infeasible", SolverStatus.UNBOUNDED),
        ("dual infeasible inaccurate", SolverStatus.NUMERICAL_ERROR),
        ("maximum iterations reached", SolverStatus.MAX_ITERATIONS),
        ("run time limit reached", SolverStatus.TIME_LIMIT),
        ("problem non convex", SolverStatus.NUMERICAL_ERROR),
        ("interrupted", SolverStatus.UNKNOWN),
        ("unsolved", SolverStatus.UNKNOWN),
    ],
)
def test_mapping_all_native_statuses(native: str, expected: SolverStatus) -> None:
    """SOL-002: los 11 estados nativos de OSQP 1.x tienen un mapeo explícito."""
    assert map_osqp_status(native) is expected
    assert native in OSQP_STATUS_MAP


def test_inaccurate_statuses_are_never_promoted_to_firm_verdicts() -> None:
    """A-33: ``*_inaccurate`` nunca es OPTIMAL ni INFEASIBLE; un fallo numérico no es
    inviabilidad."""
    assert map_osqp_status("solved inaccurate") is not SolverStatus.OPTIMAL
    assert map_osqp_status("primal infeasible inaccurate") is not SolverStatus.INFEASIBLE
    assert map_osqp_status("dual infeasible inaccurate") is not SolverStatus.UNBOUNDED
    assert map_osqp_status("primal infeasible inaccurate") is SolverStatus.NUMERICAL_ERROR


def test_unknown_native_status_is_unknown_and_matching_ignores_case() -> None:
    assert map_osqp_status("some future status") is SolverStatus.UNKNOWN
    assert map_osqp_status("  Solved ") is SolverStatus.OPTIMAL


def test_certificates_are_not_ambiguous() -> None:
    """Un certificado firme de inviabilidad o no acotación no se reintenta."""
    assert SolverStatus.INFEASIBLE not in AMBIGUOUS_STATUSES
    assert SolverStatus.UNBOUNDED not in AMBIGUOUS_STATUSES
    assert SolverStatus.OPTIMAL not in AMBIGUOUS_STATUSES
    assert SolverStatus.NUMERICAL_ERROR in AMBIGUOUS_STATUSES
    assert SolverStatus.OPTIMAL_INACCURATE in AMBIGUOUS_STATUSES
