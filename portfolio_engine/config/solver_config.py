"""Configuración de solvers y tolerancias de validación (MASTER_SPEC §4, §44-47; CFG-008, VAL-008).

Todos los parámetros numéricos del backend OSQP y las tolerancias con las que el
``SolutionValidator`` acepta o rechaza una solución proceden de aquí.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import (
    require_int_at_least,
    require_non_negative,
    require_positive,
)
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import CrossCheckPolicy


@dataclass(frozen=True, slots=True)
class SolverConfig:
    """Parámetros del backend OSQP, política de estados ambiguos y tolerancias de validación.

    Attributes:
        eps_abs: tolerancia absoluta de convergencia de OSQP.
        eps_rel: tolerancia relativa de convergencia de OSQP.
        max_iterations: iteraciones máximas por resolución.
        time_limit_seconds: límite de tiempo por resolución (``None`` = sin límite).
        polish: activa el pulido de la solución de OSQP.
        adaptive_rho_interval: intervalo fijo (iteraciones) de actualización adaptativa de ``rho``.
            Debe ser positivo: con 0 OSQP decide por tiempo de reloj y los resultados dejan de ser
            reproducibles (MASTER_SPEC §70).
        warm_start: si es ``False`` cada resolución parte de cero aunque se reutilice el workspace.
        workspace_reuse: si es ``False`` cada punto de frontera crea un workspace nuevo
            (referencia "cold setup" del benchmark).
        ambiguous_status_policy: qué hacer ante estados ambiguos (``MAX_ITERATIONS``,
            ``OPTIMAL_INACCURATE``, ``NUMERICAL_ERROR``, ``UNKNOWN``).
        retry_iteration_multiplier: factor sobre ``max_iterations`` en el reintento en frío.
        accept_inaccurate_solutions: si es ``False``, una solución ``OPTIMAL_INACCURATE`` se
            almacena pero se marca como no válida.
        budget_tolerance: tolerancia de ``sum(w) = 1`` en el validador.
        bound_tolerance: tolerancia de límites de peso y de la política de restringidos.
        constraint_tolerance: tolerancia de restricciones de grupo, turnover y retorno objetivo,
            y de las reglas de factibilidad previa.
        variance_tolerance: negatividad numérica tolerada de ``w'Σw`` (por debajo se rechaza).
        lp_feasibility_tolerance: tolerancia primal y dual de HiGHS en el LP de MaximumReturn.
        lp_max_iterations: iteraciones máximas de HiGHS por resolución del LP.
        max_return_tie_abs_tolerance: parte absoluta (unidades de retorno anualizado) de la
            holgura de la etapa 2 de MaximumReturn.
        max_return_tie_rel_tolerance: parte relativa (fracción de ``|R*|``) de esa holgura.
        numerical_recovery: activa la recuperación numérica de puntos de retorno objetivo que el
            solver no resuelve (F-3): comprobación de factibilidad con un LP independiente y
            reintentos deterministas sobre una fila de retorno normalizada.
        recovery_row_scales: escalas de la escalera de reintentos: cada valor es el máximo
            ``|coeficiente|`` de los pesos de la fila de retorno tras centrarla; se prueban en orden
            hasta obtener ``OPTIMAL`` validado (una resolución por escala con ``max_iterations ×
            retry_iteration_multiplier`` iteraciones, sin más reintentos).

    La etapa 2 de MaximumReturn (decisión A-14) resuelve ``min wᵀΣw`` sujeto a
    ``retorno >= R* − tol`` con ``tol = max(abs, rel·|R*|)`` (:meth:`max_return_tie_tolerance`):
    es la única fuente de esa holgura y es una tolerancia numérica, no una relajación financiera.
    """

    eps_abs: float
    eps_rel: float
    max_iterations: int
    time_limit_seconds: float | None
    polish: bool
    adaptive_rho_interval: int
    warm_start: bool
    workspace_reuse: bool
    ambiguous_status_policy: CrossCheckPolicy
    retry_iteration_multiplier: int
    accept_inaccurate_solutions: bool
    budget_tolerance: float
    bound_tolerance: float
    constraint_tolerance: float
    variance_tolerance: float
    lp_feasibility_tolerance: float
    lp_max_iterations: int
    max_return_tie_abs_tolerance: float
    max_return_tie_rel_tolerance: float
    numerical_recovery: bool
    recovery_row_scales: tuple[float, ...]

    def __post_init__(self) -> None:
        require_positive(self.eps_abs, "solver.eps_abs")
        require_positive(self.eps_rel, "solver.eps_rel")
        require_int_at_least(self.max_iterations, 1, "solver.max_iterations")
        if self.time_limit_seconds is not None:
            require_positive(self.time_limit_seconds, "solver.time_limit_seconds")
        require_int_at_least(self.adaptive_rho_interval, 1, "solver.adaptive_rho_interval")
        require_positive(self.lp_feasibility_tolerance, "solver.lp_feasibility_tolerance")
        require_int_at_least(self.lp_max_iterations, 1, "solver.lp_max_iterations")
        require_int_at_least(
            self.retry_iteration_multiplier, 1, "solver.retry_iteration_multiplier"
        )
        for name in (
            "polish",
            "warm_start",
            "workspace_reuse",
            "accept_inaccurate_solutions",
            "numerical_recovery",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(f"solver.{name} debe ser booleano.")
        if not isinstance(self.ambiguous_status_policy, CrossCheckPolicy):
            raise ConfigError("solver.ambiguous_status_policy debe ser un CrossCheckPolicy.")
        for name in (
            "budget_tolerance",
            "bound_tolerance",
            "constraint_tolerance",
            "variance_tolerance",
            "max_return_tie_abs_tolerance",
            "max_return_tie_rel_tolerance",
        ):
            require_non_negative(getattr(self, name), f"solver.{name}")
        if self.numerical_recovery and not self.recovery_row_scales:
            raise ConfigError("solver.recovery_row_scales no puede estar vacía con recuperación.")
        for scale in self.recovery_row_scales:
            require_positive(scale, "solver.recovery_row_scales[]")
        if self.max_return_tie_abs_tolerance == 0.0 and self.max_return_tie_rel_tolerance == 0.0:
            raise ConfigError(
                "La holgura de la etapa 2 de MaximumReturn no puede ser nula: el conjunto "
                "factible degeneraría en un punto (indicar solver.max_return_tie_*_tolerance)."
            )

    def max_return_tie_tolerance(self, best_return: float) -> float:
        """Holgura ``max(abs, rel·|R*|)`` de la etapa 2 de MaximumReturn (unidades de retorno)."""
        return max(
            self.max_return_tie_abs_tolerance, self.max_return_tie_rel_tolerance * abs(best_return)
        )
