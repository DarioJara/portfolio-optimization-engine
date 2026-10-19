"""Arquitectura de ``NONCONVEX_RESEARCH`` (MASTER_SPEC §50-51; NCV-001, NCV-002, NCV-004; E-25).

Solo arquitectura: familia, clase de problema (``NLP_NONCONVEX``), routing, interfaz de algoritmos y
guarda de convexidad. **No se implementa ningún algoritmo no convexo concreto** (IPOPT, SLSQP,
Differential Evolution, multi-start…) mientras no exista un caso financiero validado que lo exija
(enmienda E-25): el registro de algoritmos está vacío por defecto y un ``NonConvexBackend`` sin
algoritmos rechaza el problema en lugar de fingir una resolución.

Reglas que este módulo hace cumplir:

* un problema que declara una **reformulación convexa** válida no se resuelve como no convexo
  (NCV-002, MASTER_SPEC §50);
* el resultado de un algoritmo no convexo jamás afirma optimalidad global: ``LOCAL`` si converge y
  ``FEASIBLE_ONLY`` si solo es factible (NCV-004, MASTER_SPEC §51).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import (
    OptimalityClaim,
    ProblemClass,
    SolverStatus,
    StatusSource,
)
from portfolio_engine.models.solution import SolveResult
from portfolio_engine.optimizers.base import (
    BackendCapabilities,
    OptimizationBackend,
    SetupInfo,
    UpdateInfo,
)
from portfolio_engine.optimizers.problem import CanonicalProblem, NonConvexProblem


@dataclass(frozen=True, eq=False, slots=True)
class NonConvexOutcome:
    """Resultado bruto de un algoritmo no convexo: punto, objetivo y qué garantiza.

    ``converged`` significa convergencia local (condiciones de primer orden); ``feasible``, que el
    punto cumple las restricciones. Nada de esto es optimalidad global.
    """

    x: npt.NDArray[np.float64]
    objective: float
    converged: bool
    feasible: bool
    iterations: int


class NonConvexAlgorithm(Protocol):
    """Contrato de un algoritmo de optimización no convexa registrable."""

    @property
    def name(self) -> str:
        """Nombre del algoritmo."""

    def minimize(
        self, problem: NonConvexProblem, start: npt.NDArray[np.float64] | None
    ) -> NonConvexOutcome:
        """Minimiza ``problem`` desde ``start`` (o desde donde decida el algoritmo)."""


class NonConvexBackend(OptimizationBackend):
    """Backend de ``NONCONVEX_RESEARCH``: usa los algoritmos registrados (ninguno por defecto)."""

    def __init__(self, algorithms: Sequence[NonConvexAlgorithm] = ()) -> None:
        self._algorithms = tuple(algorithms)
        self._problem: NonConvexProblem | None = None
        self._start: npt.NDArray[np.float64] | None = None
        self._setup_count = 0
        self._solve_count = 0

    @property
    def algorithms(self) -> tuple[NonConvexAlgorithm, ...]:
        """Algoritmos registrados (vacío por defecto, E-25)."""
        return self._algorithms

    @property
    def name(self) -> str:
        """Nombre del backend."""
        return "NONCONVEX"

    @property
    def version(self) -> str:
        """Versión: la del primer algoritmo registrado, o ``NONE``."""
        return "NONE" if not self._algorithms else self._algorithms[0].name

    @property
    def capabilities(self) -> BackendCapabilities:
        """Solo problemas no convexos; sin actualización ni arranque compartido."""
        return BackendCapabilities(
            supports_qp=False,
            supports_socp=False,
            supports_sdp=False,
            supports_integer=False,
            supports_nonconvex=True,
            supports_vector_update=False,
            supports_matrix_update=False,
            supports_warm_start=True,
            supports_factorization_reuse=False,
        )

    @property
    def setup_count(self) -> int:
        """Problemas registrados."""
        return self._setup_count

    @property
    def update_count(self) -> int:
        """Siempre 0."""
        return 0

    @property
    def solve_count(self) -> int:
        """Resoluciones realizadas."""
        return self._solve_count

    @property
    def updated_fields(self) -> tuple[str, ...]:
        """Siempre vacío."""
        return ()

    def supports(self, problem_class: ProblemClass) -> bool:
        """Solo ``NLP_NONCONVEX``."""
        return problem_class is ProblemClass.NLP_NONCONVEX

    def setup(self, problem: CanonicalProblem) -> SetupInfo:
        """Registra ``problem``; rechaza los convexos reformulables y la falta de algoritmos."""
        if not isinstance(problem, NonConvexProblem):
            raise SolverError("NonConvexBackend solo resuelve NonConvexProblem.")
        if problem.has_convex_reformulation:
            raise SolverError(
                "El problema admite una reformulación convexa "
                f"({problem.convex_reformulation}): no se resuelve como no convexo (§50)."
            )
        if not self._algorithms:
            raise SolverError(
                "No hay algoritmos no convexos registrados: E-25 los difiere hasta que exista un "
                "caso financiero validado."
            )
        self._problem = problem
        self._setup_count += 1
        return SetupInfo(0.0, problem.n_variables, problem.n_constraints)

    def update(
        self,
        *,
        q: npt.NDArray[np.float64] | None = None,
        lower: npt.NDArray[np.float64] | None = None,
        upper: npt.NDArray[np.float64] | None = None,
    ) -> UpdateInfo:
        """No admite actualización."""
        raise SolverError("NonConvexBackend no admite update.")

    def warm_start(
        self,
        x: npt.NDArray[np.float64] | None = None,
        y: npt.NDArray[np.float64] | None = None,
    ) -> None:
        """Punto inicial del siguiente ``solve`` (``y`` no existe en un problema no convexo)."""
        if y is not None:
            raise SolverError("Un problema no convexo no admite multiplicadores duales iniciales.")
        self._start = None if x is None else np.array(x, dtype=np.float64)

    def solve(self) -> SolveResult:
        """Ejecuta el primer algoritmo registrado; el resultado nunca es una afirmación global."""
        problem = self._require_problem()
        algorithm = self._algorithms[0]
        started = time.perf_counter()
        outcome = algorithm.minimize(problem, self._start)
        elapsed = time.perf_counter() - started
        self._solve_count += 1
        usable = outcome.feasible and bool(np.all(np.isfinite(outcome.x)))
        status = SolverStatus.OPTIMAL if usable and outcome.converged else SolverStatus.UNKNOWN
        if usable and not outcome.converged:
            status = SolverStatus.INSUFFICIENT_PROGRESS
        claim = OptimalityClaim.NOT_ASSESSED
        if usable:
            claim = OptimalityClaim.LOCAL if outcome.converged else OptimalityClaim.FEASIBLE_ONLY
        exposed = outcome.x if status is SolverStatus.OPTIMAL else None
        return SolveResult(
            status=status,
            native_status=f"{algorithm.name}:converged={outcome.converged}",
            status_source=StatusSource.SOLVER,
            solver_name=self.name,
            solver_version=algorithm.name,
            problem_class=problem.problem_class,
            x=exposed,
            y=None,
            objective_value=outcome.objective if exposed is not None else None,
            iterations=outcome.iterations,
            setup_time=0.0,
            update_time=0.0,
            solve_time=elapsed,
            primal_residual=None,
            dual_residual=None,
            warm_start_used=self._start is not None,
            cold_retries=0,
            optimality_claim=claim,
        )

    def cold_retry(self) -> SolveResult:
        """Reintenta sin punto inicial."""
        self._start = None
        return self.solve()

    def _require_problem(self) -> NonConvexProblem:
        if self._problem is None:
            raise SolverError("El problema no está registrado: llame a setup() primero.")
        return self._problem
