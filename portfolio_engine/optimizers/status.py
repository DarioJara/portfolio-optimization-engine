"""Mapeo de estados nativos de OSQP a ``SolverStatus`` (MASTER_SPEC §45; SOL-002, decisión A-33).

Reglas:

* Un estado ``*_inaccurate`` de solución es ``OPTIMAL_INACCURATE``: nunca se promueve a ``OPTIMAL``.
* Un certificado de inviabilidad ``*_inaccurate`` **no** es ``INFEASIBLE``: se registra como
  ``NUMERICAL_ERROR`` (el solver sospecha inviabilidad pero no la certifica). Un fallo numérico
  jamás se presenta como inviabilidad matemática.
* HiGHS (``scipy.optimize.linprog``) devuelve un código entero (:data:`HIGHS_STATUS_BY_CODE`):
  óptimo, límite (iteraciones o tiempo), inviable, no acotado y dificultades numéricas; ninguno
  se colapsa en otro y un código desconocido es ``UNKNOWN``.
* Un estado nativo desconocido es ``UNKNOWN``; el texto nativo se conserva siempre.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from portfolio_engine.models.enums import SolverStatus

#: Textos de estado de OSQP 1.x → estado normalizado.
OSQP_STATUS_MAP: Mapping[str, SolverStatus] = MappingProxyType(
    {
        "solved": SolverStatus.OPTIMAL,
        "solved inaccurate": SolverStatus.OPTIMAL_INACCURATE,
        "primal infeasible": SolverStatus.INFEASIBLE,
        "primal infeasible inaccurate": SolverStatus.NUMERICAL_ERROR,
        "dual infeasible": SolverStatus.UNBOUNDED,
        "dual infeasible inaccurate": SolverStatus.NUMERICAL_ERROR,
        "maximum iterations reached": SolverStatus.MAX_ITERATIONS,
        "run time limit reached": SolverStatus.TIME_LIMIT,
        "problem non convex": SolverStatus.NUMERICAL_ERROR,
        "interrupted": SolverStatus.UNKNOWN,
        "unsolved": SolverStatus.UNKNOWN,
    }
)

#: Estado normalizado de cada código de ``scipy.optimize.linprog`` (``res.status`` = índice).
#: El código de límite (1) cubre iteraciones y tiempo; se distingue por el mensaje.
HIGHS_STATUS_BY_CODE = (
    SolverStatus.OPTIMAL,
    SolverStatus.MAX_ITERATIONS,
    SolverStatus.INFEASIBLE,
    SolverStatus.UNBOUNDED,
    SolverStatus.NUMERICAL_ERROR,
)

#: Estados que la política de verificación cruzada considera ambiguos (candidatos a reintento).
AMBIGUOUS_STATUSES = frozenset(
    {
        SolverStatus.OPTIMAL_INACCURATE,
        SolverStatus.MAX_ITERATIONS,
        SolverStatus.NUMERICAL_ERROR,
        SolverStatus.INSUFFICIENT_PROGRESS,
        SolverStatus.UNKNOWN,
    }
)


def map_osqp_status(native_status: str) -> SolverStatus:
    """Estado normalizado de un texto de estado nativo de OSQP (``UNKNOWN`` si no se reconoce)."""
    return OSQP_STATUS_MAP.get(native_status.strip().lower(), SolverStatus.UNKNOWN)


def map_highs_status(code: int, message: str) -> SolverStatus:
    """Estado normalizado de un resultado de ``linprog`` (``UNKNOWN`` si el código no se conoce).

    El código de límite (iteraciones/tiempo) es ``TIME_LIMIT`` si el mensaje menciona el tiempo.
    """
    if not 0 <= code < len(HIGHS_STATUS_BY_CODE):
        return SolverStatus.UNKNOWN
    status = HIGHS_STATUS_BY_CODE[code]
    if status is SolverStatus.MAX_ITERATIONS and "time" in message.lower():
        return SolverStatus.TIME_LIMIT
    return status
