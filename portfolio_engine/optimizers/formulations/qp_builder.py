"""Constructor de problemas QP/LP de composición fija (MASTER_SPEC §15-19, §35-38).

Requisitos: OPT-003..008, TC-010.

Variables. Bruto sin turnover: ``x = w ∈ R^n``. Con costes (``NET``) o ``MaxTurnover``:
``x = [w; b; s] ∈ R^{3n}`` con ``w − b + s = w0``, ``b, s >= 0`` (linealización de ``|Δw|``).

Objetivo (forma OSQP ``½xᵀPx + qᵀx``)::

    P = blkdiag(2Σ, 0, 0)                        constante para todo theta y todo objetivo
    q(θ) = θ · q1,   q1 = [−μ; c_b/H; c_s/H]     (bloque de costes solo en NET)

de modo que ``min ½xᵀPx + q(θ)ᵀx = min wᵀΣw − θ μᵀw + θ TC(w)`` con
``TC(w) = (c_bᵀb + c_sᵀs)/H`` (MASTER_SPEC §37): **el coste escala también con θ**. En bruto el
bloque de costes de ``q1`` es cero. ``P`` y ``A`` no cambian entre puntos: solo ``q`` (malla de
theta) o ``lower`` de la fila de retorno (malla de retorno objetivo).

Filas de ``A`` (``lower <= A x <= upper``): presupuesto, límites de peso, ``b, s >= 0``, grupos,
lifting, ``½(1ᵀb + 1ᵀs) <= MaxTurnover`` y una última **fila de retorno**
``μᵀw − (c_bᵀb + c_sᵀs)/H`` (neto) o ``μᵀw`` (bruto), libre (``-inf``) salvo que se fije un
objetivo. ``LP`` = mismo problema con ``P = 0`` y ``q = q1`` (retorno máximo, decisión A-14).

Activos actuales fuera de la composición. Se liquidan por completo: aportan al coste único la
constante ``K_E`` (``TransactionCostModel.exit_cost_one_off``) y al turnover ``exit_turnover``.
Ambas son constantes de la optimización: ``K_E`` no altera el argmin (con ``θ·K_E/H`` aditivo) pero
sí la fila de retorno neta (``μᵀw − c'(b,s)/H − K_E/H >= R`` ⇔ fila ``>= R + K_E/H``, atributo
``return_offset``) y el límite de turnover de la composición (``T − exit_turnover``).

Para costes estrictamente positivos, ``b_i·s_i = 0`` en el óptimo y ``c_bᵀb + c_sᵀs`` coincide con
el coste ex post; el conjunto factible en ``w`` con la restricción de turnover es exactamente el
original. Las métricas publicadas se recalculan siempre desde ``w`` (independencia del validador).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.costs.transaction_cost_model import TransactionCostModel
from portfolio_engine.exceptions import FrontierError
from portfolio_engine.models.enums import CostTreatment, OptimizationFamily, ProblemClass
from portfolio_engine.optimizers.problem import CanonicalProblem
from portfolio_engine.utils.numerics import readonly_float_array


@dataclass(frozen=True, eq=False, slots=True)
class CompositionInputs:
    """Datos de una composición fija: ``μ_C``, ``Σ_C``, restricciones compiladas y costes."""

    mu: npt.NDArray[np.float64]
    sigma: npt.NDArray[np.float64]
    compiled: CompiledConstraints
    cost_model: TransactionCostModel | None

    def __post_init__(self) -> None:
        size = self.compiled.size
        if self.mu.shape != (size,) or self.sigma.shape != (size, size):
            raise FrontierError("mu y sigma deben corresponder a la composición compilada.")


@dataclass(frozen=True, eq=False, slots=True)
class NormalizedReturnProblem:
    """Mismo problema con la fila de retorno centrada y escalada (recuperación numérica, F-3).

    La fila de retorno ``r`` es casi paralela a la de presupuesto ``e`` (retornos casi idénticos, o
    costes que casi cancelan la pendiente de ``μ``): OSQP ve entonces una fila cuya información
    útil es minúscula frente a su magnitud y declara inviabilidad espuria o no converge. Como
    ``eᵀx = presupuesto`` es una igualdad, restar ``λe`` (``λ = rᵀe/eᵀe``) y desplazar la cota en
    ``λ·presupuesto`` es **exactamente** el mismo conjunto factible; multiplicar la fila y su cota
    por ``s > 0`` tampoco lo altera. Las variables (``x``, pesos incluidos) y el objetivo no
    cambian, de modo que la solución se usa tal cual.

    Attributes:
        problem: problema con la fila de retorno transformada (``lower``/``upper`` originales
            solo para las demás filas; para un objetivo concreto use :meth:`lower_for`).
        return_row: índice de la fila de retorno.
        row_scale: factor ``s`` aplicado a la fila y a su cota.
        row_shift: ``λ·presupuesto`` restado de la cota inferior antes de escalar.
    """

    problem: CanonicalProblem
    return_row: int
    row_scale: float
    row_shift: float

    def lower_for(self, lower: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """``lower`` del problema original (con su objetivo) transformado a la fila normalizada."""
        mapped = np.array(lower, dtype=np.float64)
        mapped[self.return_row] = (mapped[self.return_row] - self.row_shift) * self.row_scale
        return mapped


@dataclass(frozen=True, eq=False, slots=True)
class BuiltProblem:
    """Problema canónico más la información para actualizarlo (``q``, ``lower`` de retorno).

    Attributes:
        problem: problema en forma canónica (``P``, ``A`` fijos).
        n_weights: número de variables de peso ``n``.
        lifted: ``True`` si hay variables ``b, s``.
        cost_in_objective: ``True`` si es NET (coste dentro de objetivo y de la fila de retorno).
        return_row: índice de la fila de retorno en ``A``.
        unit_objective: vector ``q1`` tal que ``q(θ) = θ·q1``.
        buy_costs: ``c_b`` sobre la composición (``None`` si no hay modelo de costes).
        sell_costs: ``c_s`` sobre la composición.
        horizon_years: horizonte ``H`` de conversión de costes (``None`` sin costes).
        return_offset: ``K_E/H`` en NET (coste constante de liquidar los activos retirados, en
            unidades de retorno); ``0`` en bruto. Retorno neto = valor de la fila de retorno −
            ``return_offset``.
    """

    problem: CanonicalProblem
    n_weights: int
    lifted: bool
    cost_in_objective: bool
    return_row: int
    unit_objective: npt.NDArray[np.float64]
    buy_costs: npt.NDArray[np.float64] | None
    sell_costs: npt.NDArray[np.float64] | None
    horizon_years: float | None
    return_offset: float

    def q_risk_aversion(self, theta: float) -> npt.NDArray[np.float64]:
        """``q(θ) = θ·q1`` (todo el vector, incluido el bloque de costes, escala con θ)."""
        return np.asarray(theta * self.unit_objective, dtype=np.float64)

    def q_zero(self) -> npt.NDArray[np.float64]:
        """``q = 0``: objetivo de varianza pura (MinVariance y problemas de retorno objetivo)."""
        return np.zeros(self.unit_objective.shape[0], dtype=np.float64)

    def lower_free_return(self) -> npt.NDArray[np.float64]:
        """``lower`` con la fila de retorno libre (``-inf``)."""
        return np.array(self.problem.lower, dtype=np.float64)

    def lower_for_target(self, target: float) -> npt.NDArray[np.float64]:
        """``lower`` con la fila de retorno fijada a ``>= target`` (bruto o neto).

        En NET la fila no incluye la liquidación de los activos retirados: ``target + K_E/H``.
        """
        lower = self.lower_free_return()
        lower[self.return_row] = target + self.return_offset
        return lower

    def normalize_return_row(self, weight_scale: float) -> NormalizedReturnProblem | None:
        """Problema equivalente con la fila de retorno centrada y de máximo coeficiente de peso
        ``weight_scale`` (``None`` si los retornos son idénticos: no queda información que escalar).

        Solo cambia la fila de retorno (y su cota, vía :meth:`NormalizedReturnProblem.lower_for`);
        ``P``, ``q``, las demás filas y las variables son las del problema original.
        """
        problem = self.problem
        budget = 0
        if problem.lower[budget] != problem.upper[budget]:
            raise FrontierError("La fila 0 debe ser la restricción de presupuesto (igualdad).")
        matrix = sparse.lil_matrix(problem.A)
        budget_row = np.asarray(problem.A.getrow(budget).toarray(), dtype=np.float64).ravel()
        return_row = np.asarray(
            problem.A.getrow(self.return_row).toarray(), dtype=np.float64
        ).ravel()
        centering = float(return_row @ budget_row) / float(budget_row @ budget_row)
        centered = return_row - centering * budget_row
        largest = float(np.max(np.abs(centered[: self.n_weights])))
        if largest <= 0.0:
            return None
        scale = weight_scale / largest
        matrix[self.return_row, :] = centered * scale
        normalized = dataclasses.replace(problem, A=sparse.csc_matrix(matrix))
        return NormalizedReturnProblem(
            normalized, self.return_row, scale, centering * float(problem.lower[budget])
        )

    def weights(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Variables de peso ``w`` de una solución ``x``."""
        return np.array(x[: self.n_weights], dtype=np.float64)

    def lifted_cost_one_off(self, x: npt.NDArray[np.float64]) -> float:
        """``c_bᵀb + c_sᵀs`` de una solución (coste único según las variables auxiliares)."""
        if not self.lifted or self.buy_costs is None or self.sell_costs is None:
            raise FrontierError("El problema no tiene variables auxiliares de compra/venta.")
        n = self.n_weights
        buys, sells = x[n : n + n], x[n + n : n + n + n]
        return float(self.buy_costs @ buys + self.sell_costs @ sells)


def build_fixed_composition_problem(
    inputs: CompositionInputs, cost_treatment: CostTreatment, *, quadratic: bool
) -> BuiltProblem:
    """Construye el problema de composición fija (OPT-003).

    ``cost_treatment`` es ``GROSS`` o ``NET`` (``POST_COST_GROSS`` se evalúa ex post, no se
    optimiza). ``quadratic = False`` construye el LP de retorno máximo (``P = 0``).
    """
    if cost_treatment is CostTreatment.POST_COST_GROSS:
        raise FrontierError("POST_COST_GROSS no se optimiza: se evalúa ex post desde GROSS.")
    compiled = inputs.compiled
    net = cost_treatment is CostTreatment.NET
    if net and inputs.cost_model is None:
        raise FrontierError("NET exige cartera actual y costes de transacción.")
    n = compiled.size
    lifted = net or compiled.needs_turnover_lifting
    n_variables = n + (n + n if lifted else 0)
    model = inputs.cost_model
    buy, sell, horizon = _composition_costs(model, compiled)
    scale = 0.0 if horizon is None else 1.0 / horizon
    cost_buy = np.zeros(n) if not net or buy is None else buy * scale
    cost_sell = np.zeros(n) if not net or sell is None else sell * scale
    unit = np.concatenate([-inputs.mu, cost_buy, cost_sell]) if lifted else -inputs.mu
    matrix, lower, upper = _constraint_rows(inputs, lifted, cost_buy, cost_sell)
    exit_offset = 0.0 if not net or model is None else model.exit_cost_one_off() * scale
    if quadratic:
        curvature = np.zeros((n_variables, n_variables))
        curvature[:n, :n] = 2.0 * inputs.sigma
        p_matrix = sparse.triu(sparse.csc_matrix(curvature), format="csc")
    else:
        p_matrix = sparse.csc_matrix((n_variables, n_variables))
    problem = CanonicalProblem(
        name="fixed_composition_qp" if quadratic else "fixed_composition_max_return_lp",
        problem_class=ProblemClass.QP if quadratic else ProblemClass.LP,
        family=OptimizationFamily.FAST_PRODUCTION,
        P=p_matrix,
        q=np.zeros(n_variables) if quadratic else unit,
        A=sparse.csc_matrix(matrix),
        lower=lower,
        upper=upper,
    )
    return BuiltProblem(
        problem=problem,
        n_weights=n,
        lifted=lifted,
        cost_in_objective=net,
        return_row=matrix.shape[0] - 1,
        unit_objective=readonly_float_array(unit),
        buy_costs=None if buy is None else readonly_float_array(buy),
        sell_costs=None if sell is None else readonly_float_array(sell),
        horizon_years=horizon,
        return_offset=exit_offset,
    )


def _composition_costs(
    model: TransactionCostModel | None, compiled: CompiledConstraints
) -> tuple[npt.NDArray[np.float64] | None, npt.NDArray[np.float64] | None, float | None]:
    if model is None:
        return None, None, None
    positions = model.alignment.composition_positions
    expected = tuple(model.alignment.asset_ids[i] for i in positions.tolist())
    if expected != compiled.asset_ids:
        raise FrontierError("El modelo de costes no corresponde a la composición compilada.")
    return model.buy_costs[positions], model.sell_costs[positions], model.horizon_years


def _constraint_rows(
    inputs: CompositionInputs,
    lifted: bool,
    cost_buy: npt.NDArray[np.float64],
    cost_sell: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    compiled = inputs.compiled
    n = compiled.size
    blocks: list[
        tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]
    ] = []

    def add(
        weights: npt.NDArray[np.float64],
        low: npt.NDArray[np.float64] | float,
        high: npt.NDArray[np.float64] | float,
        buys: npt.NDArray[np.float64] | float = 0.0,
        sells: npt.NDArray[np.float64] | float = 0.0,
    ) -> None:
        rows = weights.shape[0]
        parts = [weights]
        if lifted:
            parts.append(np.broadcast_to(np.asarray(buys, dtype=np.float64), (rows, n)))
            parts.append(np.broadcast_to(np.asarray(sells, dtype=np.float64), (rows, n)))
        blocks.append(
            (
                np.hstack(parts),
                np.broadcast_to(np.asarray(low, dtype=np.float64), (rows,)),
                np.broadcast_to(np.asarray(high, dtype=np.float64), (rows,)),
            )
        )

    ident = np.eye(n)
    add(np.ones((1, n)), compiled.budget, compiled.budget)
    add(ident, compiled.lower, compiled.upper)
    if lifted:
        add(np.zeros((n, n)), 0.0, np.inf, buys=ident)
        add(np.zeros((n, n)), 0.0, np.inf, sells=ident)
    if compiled.group_matrix.shape[0] > 0:
        add(compiled.group_matrix, compiled.group_min, compiled.group_max)
    if lifted:
        add(ident, compiled.current_weights, compiled.current_weights, buys=-ident, sells=ident)
    if compiled.max_turnover is not None:
        half = np.full((1, n), 0.5)
        add(
            np.zeros((1, n)),
            -np.inf,
            compiled.max_turnover - compiled.exit_turnover,
            buys=half,
            sells=half,
        )
    add(inputs.mu.reshape(1, n), -np.inf, np.inf, buys=-cost_buy, sells=-cost_sell)
    matrix = np.vstack([block[0] for block in blocks])
    lower = np.concatenate([block[1] for block in blocks])
    upper = np.concatenate([block[2] for block in blocks])
    return matrix, lower, upper
