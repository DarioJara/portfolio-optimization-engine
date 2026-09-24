"""Carteras explícitas: MinimumVariance y MaximumReturn (MASTER_SPEC §17-18, §35).

Requisitos: OPT-006, OPT-007, FRN-006.

Se resuelven **explícitamente** (no como ``θ = 0`` / ``θ → ∞`` de la malla) y los extremos de
toda frontera proceden de aquí:

* ``MinimumVariance``: ``min wᵀΣw`` sujeto a las restricciones.
* ``MaximumReturn`` (lexicográfico, A-14): etapa 1 LP ``max μᵀw`` (neto: ``μᵀw − TC(w)``);
  etapa 2 ``min wᵀΣw`` s.a. retorno ``>= R* − ε`` (desempate de mínima varianza).
"""

from __future__ import annotations

from portfolio_engine.frontiers.session import FrontierSession
from portfolio_engine.models.frontier import FrontierPoint


def solve_minimum_variance(session: FrontierSession) -> FrontierPoint:
    """Cartera de mínima varianza de la composición de ``session``."""
    return session.solve_minimum_variance()


def solve_maximum_return(session: FrontierSession) -> tuple[FrontierPoint, tuple[str, ...]]:
    """Cartera de máximo retorno con desempate de mínima varianza, y notas de la resolución."""
    return session.solve_maximum_return()
