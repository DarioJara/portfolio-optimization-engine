"""Forma canónica de un QP con restricciones lineales (MASTER_SPEC §46-47; OPT-013).

::

    minimize    ½ xᵀ P x + qᵀ x
    subject to  lower <= A x <= upper

es la forma nativa de OSQP. ``P`` se almacena triangular superior (convención de OSQP); la forma
cuadrática es ``½ xᵀ (P + Pᵀ − diag(P)) x``. Cada problema declara su ``ProblemClass`` y su
``OptimizationFamily``, que son la base del routing (``SolverRouter``).
"""

from __future__ import annotations

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
