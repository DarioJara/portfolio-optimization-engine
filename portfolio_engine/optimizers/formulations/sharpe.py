"""Maximum Sharpe por transformación de Charnes-Cooper como SOCP (MASTER_SPEC §20; OPT-009, A-13).

``Sharpe(w) = N(w) / √(wᵀΣw)`` con ``N(w) = (μ − rf)ᵀw`` (bruto) o
``N(w) = (μ − rf)ᵀw − TC(w)`` (neto; ``TC`` convexa y lineal a trozos) **no es un QP**: es un
cociente cuasicóncavo cuando ``N > 0`` sobre un poliedro. La transformación de Charnes-Cooper
(``y = κw``, ``κ > 0``) lo convierte en un problema convexo exacto::

    minimize    r
    subject to  ‖Lᵀy‖₂ <= r                          (Σ = L Lᵀ, r = √(yᵀΣy))
                N(y, κ) >= 1                          (normalización del numerador)
                restricciones de w homogeneizadas por κ
    w = y / κ         y      Sharpe(w) = N(w)/√(wᵀΣw) = 1/r*

Homogeneización de las restricciones del Bloque 2 (todas son poliedrales y de grado 1 en
``(w, κ)``, sin ninguna aproximación):

* presupuesto ``1ᵀw = B``                → ``1ᵀy − Bκ = 0``;
* límites ``l_i <= w_i <= u_i``           → ``l_i κ <= y_i <= u_i κ`` (semicontinuas como en el
  Bloque 2: son las cotas efectivas de E-09, E-10 y ADV/NAV);
* grupos ``g_min <= Gw <= g_max``         → ``g_min κ <= Gy <= g_max κ``;
* ``w − b + s = w0``                       → ``y − b' + s' − w0 κ = 0``, ``b', s' >= 0``;
* ``½(1ᵀb + 1ᵀs) <= T_c``               → ``½(1ᵀb' + 1ᵀs') <= T_c κ``, con ``T_c`` = ``MaxTurnover −
  turnover constante de las liquidaciones``;
* costes NET: ``TC(w) = (c_bᵀb + c_sᵀs + K_E)/H`` → ``(c_bᵀb' + c_sᵀs')/H + (K_E/H)κ``;
* ``VolatilityLimit`` opcional ``√(wᵀΣw) <= σ_max`` → ``‖Lᵀy‖ <= σ_max κ``.

Es un problema convexo: un ``OPTIMAL`` de Clarabel es un óptimo global dentro de su tolerancia (no
un óptimo local). La recuperación ``w = y/κ`` se verifica siempre en el ``SolutionValidator``.
Precondición (A-13): existe ``w`` factible con ``N(w) > 0``; si no, el problema es
``NOT_APPLICABLE`` (no se inventa un Sharpe máximo). Con ``Σ`` singular y ``N > 0`` en el núcleo de
``Σ`` la volatilidad puede ser 0 (Sharpe no acotado): se detecta y se informa aparte.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.models.enums import CostTreatment, OptimizationFamily, ProblemClass
from portfolio_engine.optimizers.formulations.conic import PSDFactor, volatility_cone
from portfolio_engine.optimizers.formulations.model_builder import ModelBuilder
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.formulations.volatility import require_volatility_limit
from portfolio_engine.optimizers.problem import CanonicalProblem, ConicProblem


@dataclass(frozen=True, eq=False, slots=True)
class SharpeProblem:
    """SOCP de Charnes-Cooper de una composición y el mapa de sus variables.

    ``x = [y (n); b' (n); s' (n); κ; r]`` (``b'``, ``s'`` solo con lifting). ``y_index`` empieza
    en 0. ``r`` es la volatilidad normalizada: ``Sharpe* = 1/r*``.
    """

    problem: ConicProblem
    n_weights: int
    kappa_index: int
    r_index: int
    net: bool

    def weights(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64] | None:
        """``w = y / κ`` (``None`` si ``κ`` es numéricamente nulo: la solución no es un cartera)."""
        kappa = float(x[self.kappa_index])
        if not np.isfinite(kappa) or kappa <= 0.0:
            return None
        return np.array(x[: self.n_weights] / kappa, dtype=np.float64)

    def implied_sharpe(self, x: npt.NDArray[np.float64]) -> float | None:
        """``1 / r`` implícito en el óptimo (``None`` si ``r`` no es positivo)."""
        r_value = float(x[self.r_index])
        return None if r_value <= 0.0 else 1.0 / r_value


def build_maximum_sharpe_problem(
    inputs: CompositionInputs,
    cost_treatment: CostTreatment,
    factor: PSDFactor,
    risk_free_rate: float,
    *,
    volatility_limit: float | None = None,
) -> SharpeProblem:
    """Construye el SOCP de Charnes-Cooper de la composición (``GROSS`` o ``NET``)."""
    compiled = inputs.compiled
    n = compiled.size
    if factor.loading.shape[0] != n:
        raise UnsupportedCombinationError("El factor de Σ no corresponde a la composición.")
    if not (np.all(np.isfinite(compiled.lower)) and np.all(np.isfinite(compiled.upper))):
        raise UnsupportedCombinationError(
            "Max Sharpe exige cotas de peso finitas por activo: la transformación de "
            "Charnes-Cooper no está definida con posiciones sin límite."
        )
    # el problema del Bloque 2 aporta costes, horizonte y liquidaciones de las salidas
    base = build_fixed_composition_problem(inputs, cost_treatment, quadratic=False)
    lifted = base.lifted
    builder = ModelBuilder(_empty_problem(n + (n + n if lifted else 0)))
    if lifted:
        builder.add_rows(
            _selector(np.arange(n, n + n + n), builder.n_variables),
            np.zeros(n + n),
            np.full(n + n, np.inf),
        )
    kappa = builder.add_variables(1, lower=0.0)
    total = builder.n_variables
    for matrix, low, high in _homogeneous_blocks(compiled, n, kappa, total, lifted):
        builder.add_rows(matrix, low, high)
    builder.add_rows(
        sparse.csr_matrix(_excess_return_row(inputs, base, risk_free_rate, n, kappa, total)),
        np.ones(1),
        np.full(1, np.inf),
    )
    r_index = builder.add_variables(1, cost=1.0)
    columns = np.arange(n, dtype=np.int64)
    risk_cone = volatility_cone(factor, columns, builder.n_variables, 0.0)
    radius = np.zeros(builder.n_variables)
    radius[r_index] = 1.0
    builder.add_cone("sharpe_risk", risk_cone.matrix, risk_cone.offset, radius, 0.0)
    if volatility_limit is not None:
        limit = volatility_cone(
            factor,
            columns,
            builder.n_variables,
            require_volatility_limit(volatility_limit),
            limit_column=kappa,
        )
        builder.add_cone("volatility_limit", limit.matrix, limit.offset, limit.height, 0.0)
    problem = builder.finalize("maximum_sharpe_charnes_cooper")
    if not isinstance(problem, ConicProblem):
        raise UnsupportedCombinationError("Max Sharpe debe producir un SOCP.")
    return SharpeProblem(problem, n, kappa, r_index, base.cost_in_objective)


def _selector(columns: npt.NDArray[np.int64], n_variables: int) -> sparse.csr_matrix:
    """Filas ``x_j`` para cada ``j`` de ``columns`` (identidad parcial)."""
    count = columns.shape[0]
    return sparse.csr_matrix(
        (np.ones(count), (np.arange(count), columns)), shape=(count, n_variables)
    )


def _empty_problem(size: int) -> CanonicalProblem:
    return CanonicalProblem(
        name="empty",
        problem_class=ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=sparse.csc_matrix((size, size)),
        q=np.zeros(size),
        A=sparse.csc_matrix((0, size)),
        lower=np.zeros(0),
        upper=np.zeros(0),
    )


def _homogeneous_blocks(
    compiled: CompiledConstraints, n: int, kappa: int, total: int, lifted: bool
) -> list[tuple[sparse.csr_matrix, npt.NDArray[np.float64], npt.NDArray[np.float64]]]:
    """Filas homogeneizadas por ``κ`` de las restricciones compiladas (ver el docstring)."""
    blocks: list[tuple[sparse.csr_matrix, npt.NDArray[np.float64], npt.NDArray[np.float64]]] = []
    y_columns = np.arange(n)
    budget = np.zeros((1, total))
    budget[0, :n] = 1.0
    budget[0, kappa] = -compiled.budget
    blocks.append((sparse.csr_matrix(budget), np.zeros(1), np.zeros(1)))
    for bound, sense in ((compiled.upper, "upper"), (compiled.lower, "lower")):
        rows = np.flatnonzero(np.isfinite(bound))
        count = rows.shape[0]
        matrix = sparse.lil_matrix((count, total))
        matrix[np.arange(count), y_columns[rows]] = 1.0
        matrix[:, kappa] = -bound[rows].reshape(-1, 1)
        low = np.full(count, -np.inf) if sense == "upper" else np.zeros(count)
        high = np.zeros(count) if sense == "upper" else np.full(count, np.inf)
        blocks.append((sparse.csr_matrix(matrix), low, high))
    for bound, sense in ((compiled.group_max, "upper"), (compiled.group_min, "lower")):
        rows = np.flatnonzero(np.isfinite(bound))
        if rows.shape[0] == 0:
            continue
        matrix = sparse.lil_matrix((rows.shape[0], total))
        matrix[:, :n] = compiled.group_matrix[rows]
        matrix[:, kappa] = -bound[rows].reshape(-1, 1)
        low = np.full(rows.shape[0], -np.inf) if sense == "upper" else np.zeros(rows.shape[0])
        high = np.zeros(rows.shape[0]) if sense == "upper" else np.full(rows.shape[0], np.inf)
        blocks.append((sparse.csr_matrix(matrix), low, high))
    if lifted:
        lifting = np.zeros((n, total))
        lifting[np.arange(n), np.arange(n)] = 1.0
        lifting[np.arange(n), n + np.arange(n)] = -1.0
        lifting[np.arange(n), n + n + np.arange(n)] = 1.0
        lifting[:, kappa] = -compiled.current_weights
        blocks.append((sparse.csr_matrix(lifting), np.zeros(n), np.zeros(n)))
        if compiled.max_turnover is not None:
            turnover = np.zeros((1, total))
            turnover[0, n : n + n + n] = 0.5
            turnover[0, kappa] = -(compiled.max_turnover - compiled.exit_turnover)
            blocks.append((sparse.csr_matrix(turnover), np.full(1, -np.inf), np.zeros(1)))
    return blocks


def _excess_return_row(
    inputs: CompositionInputs,
    base: BuiltProblem,
    risk_free_rate: float,
    n: int,
    kappa: int,
    total: int,
) -> npt.NDArray[np.float64]:
    """Fila ``N(y, κ)``: ``(μ − rf)ᵀy`` menos, en NET, ``(c_bᵀb' + c_sᵀs')/H + (K_E/H)κ``."""
    row = np.zeros((1, total))
    row[0, :n] = inputs.mu - risk_free_rate
    if base.cost_in_objective:
        if base.buy_costs is None or base.sell_costs is None or base.horizon_years is None:
            raise UnsupportedCombinationError("NET exige costes de compra/venta y horizonte.")
        scale = 1.0 / base.horizon_years
        row[0, n : n + n] = -base.buy_costs * scale
        row[0, n + n : n + n + n] = -base.sell_costs * scale
        row[0, kappa] = -base.return_offset
    return row
