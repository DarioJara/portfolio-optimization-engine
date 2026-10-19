"""Constructor incremental de problemas extendidos sobre el problema de composición fija.

Las formulaciones del Bloque 4 (volatilidad, peor caso, CVaR, robustez, MIQP) parten del problema
del Bloque 2 (:class:`BuiltProblem`: presupuesto, límites, grupos, turnover, política de
restringidos, lifting de compra/venta) y le añaden **variables auxiliares**, **filas lineales**,
**términos de objetivo** y **conos de segundo orden**. Este módulo evita duplicar la compilación de
restricciones: las filas del Bloque 2 se copian tal cual (mismo orden, mismas cotas) y las
variables originales conservan sus índices, de modo que ``weights(x) = x[:n]``.

Las columnas solo crecen: cada bloque se declara sobre las variables existentes en ese momento y
se rellena con ceros hasta el tamaño final.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.exceptions import SolverError
from portfolio_engine.models.enums import OptimizationFamily, ProblemClass
from portfolio_engine.optimizers.problem import (
    CanonicalProblem,
    ConicProblem,
    MixedIntegerProblem,
    SecondOrderCone,
)


@dataclass(frozen=True, eq=False, slots=True)
class _PendingCone:
    name: str
    matrix: sparse.coo_matrix
    offset: npt.NDArray[np.float64]
    height: npt.NDArray[np.float64]
    constant: float


class ModelBuilder:
    """Acumula variables, filas, objetivo cuadrático y conos; :meth:`finalize` los ensambla."""

    def __init__(self, base: CanonicalProblem) -> None:
        self._n = base.n_variables
        matrix = sparse.coo_matrix(base.A)
        self._rows: list[
            tuple[npt.NDArray[np.int64], npt.NDArray[np.int64], npt.NDArray[np.float64]]
        ]
        self._rows = [(matrix.row, matrix.col, matrix.data)]
        self._n_rows = base.n_constraints
        self._lower = [np.array(base.lower, dtype=np.float64)]
        self._upper = [np.array(base.upper, dtype=np.float64)]
        p_matrix = sparse.coo_matrix(base.P)
        self._p_terms = [(p_matrix.row, p_matrix.col, p_matrix.data)]
        self._q = [np.array(base.q, dtype=np.float64)]
        self._cones: list[_PendingCone] = []
        self._binary: list[int] = []

    @property
    def n_variables(self) -> int:
        """Variables declaradas hasta ahora."""
        return self._n

    @property
    def n_rows(self) -> int:
        """Filas lineales declaradas hasta ahora."""
        return self._n_rows

    def set_objective(
        self, quadratic: sparse.spmatrix | None, linear: npt.NDArray[np.float64]
    ) -> None:
        """Sustituye el objetivo por ``½xᵀPx + qᵀx`` (``P`` triangular superior o ``None``)."""
        if linear.shape != (self._n,):
            raise SolverError("El vector lineal del objetivo debe cubrir todas las variables.")
        if quadratic is None:
            self._p_terms = []
        else:
            matrix = sparse.coo_matrix(quadratic)
            if matrix.shape[0] > self._n or matrix.shape[1] > self._n:
                raise SolverError("El objetivo cuadrático excede las variables declaradas.")
            if sparse.tril(matrix, k=-1).nnz:
                raise SolverError("P debe ser triangular superior.")
            self._p_terms = [(matrix.row, matrix.col, matrix.data)]
        self._q = [np.array(linear, dtype=np.float64)]

    def add_quadratic(self, quadratic: sparse.spmatrix) -> None:
        """Suma un término ``½xᵀPx`` (``P`` triangular superior) al objetivo."""
        matrix = sparse.coo_matrix(quadratic)
        if matrix.shape[0] > self._n or matrix.shape[1] > self._n:
            raise SolverError("El término cuadrático excede las variables declaradas.")
        if sparse.tril(matrix, k=-1).nnz:
            raise SolverError("P debe ser triangular superior.")
        self._p_terms.append((matrix.row, matrix.col, matrix.data))

    def add_linear_objective(self, linear: npt.NDArray[np.float64]) -> None:
        """Suma ``qᵀx`` al objetivo (``linear`` sobre las variables actuales)."""
        if linear.shape != (self._n,):
            raise SolverError("El término lineal debe cubrir todas las variables.")
        self._q.append(np.array(linear, dtype=np.float64))

    def add_variables(
        self,
        count: int,
        *,
        lower: float = -np.inf,
        upper: float = np.inf,
        cost: float = 0.0,
    ) -> int:
        """Añade ``count`` variables con cotas (filas de identidad) y coste lineal; devuelve el
        índice de la primera."""
        if count < 1:
            raise SolverError("count debe ser positivo.")
        start = self._n
        self._n += count
        self._q.append(np.concatenate([np.zeros(start), np.full(count, cost)]))
        indices = np.arange(start, start + count, dtype=np.int64)
        if np.isfinite(lower) or np.isfinite(upper):
            self.add_rows(
                sparse.csr_matrix(
                    (np.ones(count), (np.arange(count), indices)), shape=(count, self._n)
                ),
                np.full(count, lower),
                np.full(count, upper),
            )
        return start

    def mark_binary(self, indices: range | list[int]) -> None:
        """Declara variables binarias (cotas ``[0, 1]`` añadidas como filas)."""
        members = [int(index) for index in indices]
        if any(not 0 <= index < self._n for index in members):
            raise SolverError("Variable binaria fuera de rango.")
        self._binary.extend(members)
        count = len(members)
        self.add_rows(
            sparse.csr_matrix(
                (np.ones(count), (np.arange(count), np.array(members))), shape=(count, self._n)
            ),
            np.zeros(count),
            np.ones(count),
        )

    def add_rows(
        self,
        matrix: sparse.spmatrix,
        lower: npt.NDArray[np.float64],
        upper: npt.NDArray[np.float64],
    ) -> int:
        """Añade filas ``lower <= matrix·x <= upper`` sobre las variables actuales; devuelve la
        primera fila añadida."""
        block = sparse.coo_matrix(matrix)
        if block.shape[1] > self._n or not (block.shape[0] == lower.shape[0] == upper.shape[0]):
            raise SolverError("Filas con dimensiones incoherentes.")
        first = self._n_rows
        self._rows.append((block.row + first, block.col, block.data))
        self._n_rows += block.shape[0]
        self._lower.append(np.array(lower, dtype=np.float64))
        self._upper.append(np.array(upper, dtype=np.float64))
        return first

    def add_cone(
        self,
        name: str,
        matrix: sparse.spmatrix,
        offset: npt.NDArray[np.float64],
        height: npt.NDArray[np.float64],
        constant: float,
    ) -> None:
        """Añade ``‖matrix·x + offset‖ <= height·x + constant`` (sobre las variables actuales)."""
        block = sparse.coo_matrix(matrix)
        if block.shape[1] > self._n or height.shape[0] > self._n:
            raise SolverError(f"Cono {name}: excede las variables declaradas.")
        self._cones.append(_PendingCone(name, block, offset, height, float(constant)))

    def finalize(
        self,
        name: str,
        family: OptimizationFamily = OptimizationFamily.FAST_PRODUCTION,
    ) -> CanonicalProblem:
        """Ensambla el problema: MIQP/MISOCP si hay binarias, SOCP si hay conos, QP o LP si no."""
        n, m = self._n, self._n_rows
        rows = np.concatenate([part[0] for part in self._rows])
        cols = np.concatenate([part[1] for part in self._rows])
        data = np.concatenate([part[2] for part in self._rows])
        matrix = sparse.csc_matrix((data, (rows, cols)), shape=(m, n))
        lower = np.concatenate(self._lower)
        upper = np.concatenate(self._upper)
        linear = np.zeros(n)
        for part in self._q:
            linear[: part.shape[0]] += part
        p_rows = [t[0] for t in self._p_terms]
        p_cols = [t[1] for t in self._p_terms]
        p_data = [t[2] for t in self._p_terms]
        if p_data:
            quadratic = sparse.csc_matrix(
                (np.concatenate(p_data), (np.concatenate(p_rows), np.concatenate(p_cols))),
                shape=(n, n),
            )
        else:
            quadratic = sparse.csc_matrix((n, n))
        cones = tuple(self._pad_cone(cone) for cone in self._cones)
        has_quadratic = quadratic.nnz > 0
        common = {
            "name": name,
            "P": quadratic,
            "q": linear,
            "A": matrix,
            "lower": lower,
            "upper": upper,
        }
        if self._binary:
            klass = ProblemClass.MISOCP if cones else ProblemClass.MIQP
            return MixedIntegerProblem(
                problem_class=klass,
                family=OptimizationFamily.EXACT_MIP,
                binary_indices=tuple(self._binary),
                cones=cones,
                **common,
            )
        if cones:
            return ConicProblem(
                problem_class=ProblemClass.SOCP, family=family, cones=cones, **common
            )
        return CanonicalProblem(
            problem_class=ProblemClass.QP if has_quadratic else ProblemClass.LP,
            family=family,
            **common,
        )

    def _pad_cone(self, cone: _PendingCone) -> SecondOrderCone:
        n = self._n
        block = cone.matrix
        padded = sparse.coo_matrix((block.data, (block.row, block.col)), shape=(block.shape[0], n))
        height = np.zeros(n)
        height[: cone.height.shape[0]] = cone.height
        return SecondOrderCone(cone.name, padded, cone.offset, height, cone.constant)


@dataclass(frozen=True, eq=False, slots=True)
class ExtendedProblem:
    """Problema del Bloque 4 sobre una composición fija, con el mapa de sus variables.

    Attributes:
        problem: problema canónico final (QP, LP, SOCP o MIQP/MISOCP).
        n_weights: variables de peso ``n`` (siempre las primeras ``n`` de ``x``).
        n_base_variables: variables del problema del Bloque 2 (pesos y, con lifting, ``b``
            y ``s``).
        roles: primer índice de cada bloque de variables auxiliares por nombre.
        description: descripción legible de la formulación.
    """

    problem: CanonicalProblem
    n_weights: int
    n_base_variables: int
    roles: dict[str, int]
    description: str

    def weights(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Variables de peso ``w`` de una solución ``x``."""
        return np.array(x[: self.n_weights], dtype=np.float64)

    def role(self, name: str) -> int:
        """Primer índice del bloque de variables ``name``."""
        try:
            return self.roles[name]
        except KeyError as error:
            raise SolverError(f"La formulación no tiene variables {name!r}.") from error
