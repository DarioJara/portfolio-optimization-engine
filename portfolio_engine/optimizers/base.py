"""Interfaz ``OptimizationBackend`` y capacidades (MASTER_SPEC §46; SOL-003).

Un backend es dueño de un *workspace*: ``setup`` factoriza el problema una vez y las llamadas
posteriores actualizan solo ``q``, ``lower`` y ``upper`` (MASTER_SPEC §47), reutilizando ``P``,
``A`` y la factorización. Los backends son agnósticos del significado financiero del problema.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.models.enums import ProblemClass
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers.problem import CanonicalProblem


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Capacidades reales del backend (no asumidas; verificadas por tests)."""

    supports_qp: bool
    supports_socp: bool
    supports_sdp: bool
    supports_integer: bool
    supports_nonconvex: bool
    supports_vector_update: bool
    supports_matrix_update: bool
    supports_warm_start: bool
    supports_factorization_reuse: bool


@dataclass(frozen=True, slots=True)
class SetupInfo:
    """Resultado de crear el workspace."""

    setup_time: float
    n_variables: int
    n_constraints: int


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """Resultado de actualizar vectores del workspace."""

    update_time: float


class OptimizationBackend(ABC):
    """Contrato común de los backends de optimización."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre del solver."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Versión del solver."""

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        """Capacidades declaradas."""

    @property
    @abstractmethod
    def setup_count(self) -> int:
        """Veces que se ha creado el workspace (una por grid si se reutiliza)."""

    @property
    @abstractmethod
    def update_count(self) -> int:
        """Veces que se han actualizado vectores."""

    @property
    @abstractmethod
    def solve_count(self) -> int:
        """Veces que se ha resuelto."""

    @property
    @abstractmethod
    def updated_fields(self) -> tuple[str, ...]:
        """Historial de campos actualizados (``q``, ``lower``, ``upper``); nunca ``P`` ni ``A``."""

    @abstractmethod
    def supports(self, problem_class: ProblemClass) -> bool:
        """``True`` si el backend resuelve problemas de esa clase."""

    @abstractmethod
    def setup(self, problem: CanonicalProblem) -> SetupInfo:
        """Crea el workspace para ``problem``."""

    @abstractmethod
    def update(
        self,
        *,
        q: npt.NDArray[np.float64] | None = None,
        lower: npt.NDArray[np.float64] | None = None,
        upper: npt.NDArray[np.float64] | None = None,
    ) -> UpdateInfo:
        """Actualiza ``q``, ``lower`` y/o ``upper`` sin reconstruir ``P`` ni ``A``."""

    @abstractmethod
    def warm_start(
        self,
        x: npt.NDArray[np.float64] | None = None,
        y: npt.NDArray[np.float64] | None = None,
    ) -> None:
        """Inicializa el siguiente solve con ``x``/``y``."""

    @abstractmethod
    def solve(self) -> SolveResult:
        """Resuelve con los datos actuales del workspace."""

    @abstractmethod
    def cold_retry(self) -> SolveResult:
        """Reintenta desde cero (workspace nuevo, más iteraciones) con los datos actuales."""
