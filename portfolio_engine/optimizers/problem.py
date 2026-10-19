"""Forma canónica de un QP con restricciones lineales (MASTER_SPEC §46-47; OPT-013).

::

    minimize    ½ xᵀ P x + qᵀ x
    subject to  lower <= A x <= upper

es la forma nativa de OSQP. ``P`` se almacena triangular superior (convención de OSQP); la forma
cuadrática es ``½ xᵀ (P + Pᵀ − diag(P)) x``. Cada problema declara su ``ProblemClass`` y su
``OptimizationFamily``, que son la base del routing (``SolverRouter``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import OptimizationFamily, ProblemClass
from portfolio_engine.utils.numerics import readonly_float_array


@dataclass(frozen=True, eq=False, slots=True)
class CanonicalProblem:
    """QP/LP en forma canónica ``min ½xᵀPx + qᵀx  s.a.  lower <= Ax <= upper``.

    ``lower``/``upper`` admiten ``±inf``; ``P``, ``q`` y ``A`` deben ser finitos.
    """

    name: str
    problem_class: ProblemClass
    family: OptimizationFamily
    P: Any
    q: npt.NDArray[np.float64]
    A: Any
    lower: npt.NDArray[np.float64]
    upper: npt.NDArray[np.float64]

    def __post_init__(self) -> None:
        p_matrix = sparse.csc_matrix(self.P, dtype=np.float64)
        a_matrix = sparse.csc_matrix(self.A, dtype=np.float64)
        q_vector = readonly_float_array(self.q)
        lower = readonly_float_array(self.lower)
        upper = readonly_float_array(self.upper)
        n_variables, n_rows = q_vector.shape[0], lower.shape[0]
        if p_matrix.shape != (n_variables, n_variables):
            raise SolverError("P debe ser cuadrada y de la dimensión de q.")
        if a_matrix.shape != (n_rows, n_variables) or upper.shape != lower.shape:
            raise SolverError("A, lower y upper tienen dimensiones incoherentes.")
        if sparse.tril(p_matrix, k=-1).nnz:
            raise SolverError("P debe almacenarse triangular superior.")
        finite = (
            np.all(np.isfinite(p_matrix.data))
            and np.all(np.isfinite(a_matrix.data))
            and np.all(np.isfinite(q_vector))
        )
        if not finite:
            raise SolverError("P, A y q deben ser finitos.")
        if np.any(np.isnan(lower)) or np.any(np.isnan(upper)) or np.any(lower > upper):
            raise SolverError("lower/upper no pueden ser NaN ni cumplir lower > upper.")
        object.__setattr__(self, "P", p_matrix)
        object.__setattr__(self, "A", a_matrix)
        object.__setattr__(self, "q", q_vector)
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)

    @property
    def n_variables(self) -> int:
        """Número de variables."""
        return int(self.q.shape[0])

    @property
    def n_constraints(self) -> int:
        """Número de filas de restricción."""
        return int(self.lower.shape[0])


@dataclass(frozen=True, eq=False, slots=True)
class SecondOrderCone:
    """Restricción de cono de segundo orden ``‖F x + g‖₂ <= aᵀx + c`` sobre las variables ``x``.

    Es la forma general (afín en ambos lados) de la que se derivan las restricciones de
    volatilidad ``‖Lᵀw‖ <= σ`` y las cuadráticas convexas ``‖z‖² <= y`` (cono rotado, vía
    ``‖(2z, y − 1)‖ <= y + 1``). ``a`` y ``c`` dan la «altura» del cono; ``F`` y ``g`` el vector.
    """

    name: str
    F: Any
    g: npt.NDArray[np.float64]
    a: npt.NDArray[np.float64]
    c: float

    def __post_init__(self) -> None:
        matrix = sparse.csc_matrix(self.F, dtype=np.float64)
        offset = readonly_float_array(self.g)
        height = readonly_float_array(self.a)
        if matrix.shape[0] != offset.shape[0] or matrix.shape[1] != height.shape[0]:
            raise SolverError(f"Cono {self.name}: F, g y a tienen dimensiones incoherentes.")
        if not (
            np.all(np.isfinite(matrix.data))
            and np.all(np.isfinite(offset))
            and np.all(np.isfinite(height))
            and np.isfinite(self.c)
        ):
            raise SolverError(f"Cono {self.name}: los datos deben ser finitos.")
        object.__setattr__(self, "F", matrix)
        object.__setattr__(self, "g", offset)
        object.__setattr__(self, "a", height)
        object.__setattr__(self, "c", float(self.c))

    @property
    def dimension(self) -> int:
        """Dimensión del cono ``1 + filas de F`` (altura más vector)."""
        return 1 + int(self.g.shape[0])

    def value(self, x: npt.NDArray[np.float64]) -> float:
        """Holgura ``aᵀx + c − ‖Fx + g‖₂`` en ``x`` (``>= 0`` si se cumple; para validación)."""
        return float(self.a @ x + self.c - np.linalg.norm(self.F @ x + self.g))


@dataclass(frozen=True, eq=False, slots=True)
class ConicProblem(CanonicalProblem):
    """SOCP: ``min ½xᵀPx + qᵀx`` s.a. ``lower <= Ax <= upper`` y conos de segundo orden.

    Es un :class:`CanonicalProblem` (mismas filas lineales y objetivo cuadrático convexo) con los
    conos adicionales; **nunca** puede resolverlo OSQP, que ignoraría los conos: su
    ``problem_class`` es ``SOCP`` y los backends lineales lo rechazan por clase y por tipo.
    """

    cones: tuple[SecondOrderCone, ...] = ()

    def __post_init__(self) -> None:
        CanonicalProblem.__post_init__(self)
        if self.problem_class is not ProblemClass.SOCP:
            raise SolverError("Un ConicProblem debe declarar la clase SOCP.")
        if not self.cones:
            raise SolverError("Un ConicProblem exige al menos un cono (si no, es un QP/LP).")
        for cone in self.cones:
            if cone.a.shape[0] != self.n_variables:
                raise SolverError(f"Cono {cone.name}: dimensión distinta de la del problema.")
        object.__setattr__(self, "cones", tuple(self.cones))


@dataclass(frozen=True, eq=False, slots=True)
class MixedIntegerProblem(CanonicalProblem):
    """MIQP / MIQCP / MISOCP: problema con variables binarias (``EXACT_MIP``, MASTER_SPEC §49).

    ``binary_indices`` son las variables ``z ∈ {0, 1}``; sus cotas ``0 <= z <= 1`` viajan en las
    filas de ``A``. Sin conos la clase es ``MIQP`` (objetivo cuadrático convexo); con conos,
    ``MIQCP`` o ``MISOCP``. La familia es siempre ``EXACT_MIP``: no es un problema del bucle
    interno de producción.
    """

    binary_indices: tuple[int, ...] = ()
    cones: tuple[SecondOrderCone, ...] = ()

    def __post_init__(self) -> None:
        CanonicalProblem.__post_init__(self)
        if self.family is not OptimizationFamily.EXACT_MIP:
            raise SolverError("Un MixedIntegerProblem pertenece a la familia EXACT_MIP.")
        if self.problem_class not in (
            ProblemClass.MIQP,
            ProblemClass.MIQCP,
            ProblemClass.MISOCP,
        ):
            raise SolverError("Un MixedIntegerProblem debe ser MIQP, MIQCP o MISOCP.")
        if (self.problem_class is ProblemClass.MIQP) != (not self.cones):
            raise SolverError("MIQP no lleva conos; MIQCP y MISOCP exigen al menos uno.")
        indices = tuple(int(i) for i in self.binary_indices)
        if not indices or len(set(indices)) != len(indices):
            raise SolverError("binary_indices: no vacío y sin duplicados.")
        if min(indices) < 0 or max(indices) >= self.n_variables:
            raise SolverError("binary_indices fuera de rango.")
        for cone in self.cones:
            if cone.a.shape[0] != self.n_variables:
                raise SolverError(f"Cono {cone.name}: dimensión distinta de la del problema.")
        object.__setattr__(self, "binary_indices", indices)
        object.__setattr__(self, "cones", tuple(self.cones))


@dataclass(frozen=True, eq=False, slots=True)
class NonConvexProblem(CanonicalProblem):
    """Problema no convexo (``NONCONVEX_RESEARCH``, MASTER_SPEC §50; solo arquitectura, E-25).

    ``P``, ``q``, ``A`` y las cotas describen la región y el modelo local; ``objective`` es la
    función real a minimizar. ``has_convex_reformulation`` declara si existe una reformulación
    convexa válida: en ese caso el problema **no** debe resolverse como no convexo (NCV-002).
    """

    objective: Callable[[npt.NDArray[np.float64]], float] | None = None
    has_convex_reformulation: bool = False
    convex_reformulation: str | None = None

    def __post_init__(self) -> None:
        CanonicalProblem.__post_init__(self)
        if self.problem_class is not ProblemClass.NLP_NONCONVEX:
            raise SolverError("Un NonConvexProblem debe declarar la clase NLP_NONCONVEX.")
        if self.family is not OptimizationFamily.NONCONVEX_RESEARCH:
            raise SolverError("Un NonConvexProblem pertenece a la familia NONCONVEX_RESEARCH.")
        if self.objective is None:
            raise SolverError("Un NonConvexProblem exige la función objetivo.")
        if self.has_convex_reformulation and not self.convex_reformulation:
            raise SolverError("Declare cuál es la reformulación convexa disponible.")
