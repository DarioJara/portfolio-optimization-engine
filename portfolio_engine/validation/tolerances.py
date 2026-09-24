"""Tolerancias del validador de soluciones, desde configuración (MASTER_SPEC §44; VAL-008)."""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.models.enums import CostTreatment


@dataclass(frozen=True, slots=True)
class ValidationTolerances:
    """Tolerancias con las que se acepta una solución.

    Attributes:
        budget: tolerancia de ``sum(w) = presupuesto``.
        bound: tolerancia de límites de peso y de la política de activos restringidos.
        constraint: tolerancia de grupos, turnover y retorno objetivo.
        variance: negatividad numérica tolerada de ``w'Σw``.
    """

    budget: float
    bound: float
    constraint: float
    variance: float

    @classmethod
    def from_config(cls, solver: SolverConfig) -> ValidationTolerances:
        """Tolerancias de ``SolverConfig`` (única fuente de verdad)."""
        return cls(
            budget=solver.budget_tolerance,
            bound=solver.bound_tolerance,
            constraint=solver.constraint_tolerance,
            variance=solver.variance_tolerance,
        )


@dataclass(frozen=True, slots=True)
class ReturnTarget:
    """Retorno objetivo que la solución debe alcanzar: ``μ'w >= value`` (bruto) o neto.

    ``treatment = NET`` exige ``μ'w − TC(w) >= value`` (MASTER_SPEC §38).
    """

    treatment: CostTreatment
    value: float
