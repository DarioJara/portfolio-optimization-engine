"""Malla de aversión al riesgo (MASTER_SPEC §35, §37; FRN-005, FRN-010, FRN-013).

Resuelve secuencialmente ``min wᵀΣw − θ μᵀw`` (``+ θ TC(w)`` en NET) para cada ``θ = 1/λ`` de la
malla. ``P = 2Σ`` y ``A`` son constantes: solo se actualiza ``q(θ) = θ·q1`` en el mismo workspace,
con arranque en caliente desde el punto vecino. El tratamiento de costes (``GROSS`` o ``NET``) lo
fija la sesión; en NET **todo** ``q`` escala con θ, coste incluido.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from portfolio_engine.frontiers.session import FrontierSession
from portfolio_engine.models.enums import StrategyID
from portfolio_engine.models.frontier import FrontierPoint


class RiskAversionGrid:
    """Recorre una malla de theta en orden ascendente sobre un workspace reutilizable."""

    def __init__(self, session: FrontierSession) -> None:
        self._session = session

    def solve_theta(self, theta: float, *, adaptive: bool = False) -> FrontierPoint:
        """Punto de frontera para un ``θ`` concreto."""
        return self._session.solve_risk_aversion(
            theta, strategy=StrategyID.FRONTIER_POINT, adaptive=adaptive
        )

    def solve_grid(self, thetas: Sequence[float] | npt.NDArray[np.float64]) -> list[FrontierPoint]:
        """Un punto por cada ``θ`` de ``thetas``, en el orden dado."""
        return [self.solve_theta(float(theta)) for theta in thetas]
