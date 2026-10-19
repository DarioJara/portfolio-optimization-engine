"""Interfaz de los backends mixtos enteros y registro de disponibilidad (MASTER_SPEC §46, §49).

Requisitos: MIP-002, MIP-007 (enmienda E-24).

``MixedIntegerBackend`` es el contrato de los solvers de ``EXACT_MIP`` (MIQP / MIQCP / MISOCP). La
implementación de referencia es SCIP/PySCIPOpt (:mod:`portfolio_engine.optimizers.scip_backend`);
otros solvers (Gurobi, CPLEX, MOSEK) podrían enchufarse con un adaptador, pero **ninguno es una
dependencia obligatoria**: el paquete se importa y funciona sin ellos y la disponibilidad se
consulta con :func:`mixed_integer_availability`, que jamás lanza por un solver ausente.

Un solver mixto entero no comparte nada con OSQP: el problema exacto no se envía jamás a un QP.
"""

from __future__ import annotations

import importlib.util
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import ProblemClass
from portfolio_engine.optimizers.base import OptimizationBackend, UpdateInfo

MIXED_INTEGER_CLASSES = frozenset({ProblemClass.MIQP, ProblemClass.MIQCP, ProblemClass.MISOCP})

#: Módulos de los solvers mixtos enteros comerciales opcionales (solo se detectan, no se importan).
OPTIONAL_COMMERCIAL_MODULES = (
    ("GUROBI", "gurobipy"),
    ("CPLEX", "cplex"),
    ("MOSEK", "mosek"),
)


@dataclass(frozen=True, slots=True)
class BackendAvailability:
    """Disponibilidad de un solver mixto entero en el entorno actual.

    ``implemented`` indica si el motor tiene un adaptador para él; un solver comercial instalado
    sin adaptador figura como no utilizable (``usable = False``) con su motivo.
    """

    name: str
    installed: bool
    implemented: bool
    reason: str

    @property
    def usable(self) -> bool:
        """``True`` si está instalado y el motor tiene un adaptador."""
        return self.installed and self.implemented


class MixedIntegerBackend(OptimizationBackend, ABC):
    """Contrato de un backend ``EXACT_MIP``: variables binarias y (opcionalmente) conos.

    No admite actualización de vectores ni arranque en caliente obligatorio: cada resolución exacta
    es independiente y se usa solo en modo validación, nunca en el bucle interno de producción.
    """

    def update(
        self,
        *,
        q: npt.NDArray[np.float64] | None = None,
        lower: npt.NDArray[np.float64] | None = None,
        upper: npt.NDArray[np.float64] | None = None,
    ) -> UpdateInfo:
        """Un problema exacto se reconstruye: no admite actualizar datos de un modelo vivo."""
        raise SolverError("Un backend EXACT_MIP no admite update: reconstruya el problema.")

    @abstractmethod
    def hint(self, x: npt.NDArray[np.float64]) -> None:
        """Sugiere una solución inicial (p. ej. la de una heurística); el solver la valida."""


def mixed_integer_availability() -> tuple[BackendAvailability, ...]:
    """Disponibilidad de SCIP (referencia) y de los solvers comerciales opcionales.

    No importa ningún solver comercial y nunca lanza: un solver ausente es simplemente
    ``installed = False``.
    """
    entries = [
        BackendAvailability(
            name="SCIP",
            installed=importlib.util.find_spec("pyscipopt") is not None,
            implemented=True,
            reason="backend de referencia (E-24)",
        )
    ]
    for name, module in OPTIONAL_COMMERCIAL_MODULES:
        installed = importlib.util.find_spec(module) is not None
        entries.append(
            BackendAvailability(
                name=name,
                installed=installed,
                implemented=False,
                reason=(
                    "instalado pero sin adaptador en el motor"
                    if installed
                    else "no instalado (opcional, nunca obligatorio)"
                ),
            )
        )
    return tuple(entries)
