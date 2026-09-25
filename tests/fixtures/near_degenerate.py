"""Instancias F-3 (fronteras ``TARGET_RETURN_GRID`` casi degeneradas) y referencias independientes.

El generador es el de ``tests/property/test_invariants.py::frontier_problems``. Las referencias no
usan el motor: ``two_asset_reference`` es una solución analítica exacta de ``min wᵀΣw`` con retorno
(bruto o neto) mínimo para dos activos (intervalos por región de compra/venta y argmin cuadrático
recortado), ``orthant_reference`` resuelve con SLSQP cada región lineal de compra/venta y
``lp_max_return`` es el LP de HiGHS del retorno máximo alcanzable.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.optimize import linprog, minimize

from portfolio_engine.frontiers import FrontierProblem
from portfolio_engine.models.enums import CostTreatment
from tests.fixtures.problems import base_config, make_problem

FloatArray = npt.NDArray[np.float64]

#: Las siete instancias ``(n, semilla)`` contractuales de F-3 (AUDIT_BLOCK_3_FINAL_CLOSURE §14).
CONTRACT_INSTANCES = [(2, 84), (2, 184), (2, 193), (2, 89), (3, 67), (2, 159), (2, 19)]
#: Instancias adicionales halladas por el barrido determinista de la remediación
#: (``n = 2``, semillas 0-1399): mismo generador, mismo defecto en la línea base.
SWEEP_INSTANCES = [
    (2, 329, CostTreatment.GROSS),
    (2, 627, CostTreatment.GROSS),
    (2, 655, CostTreatment.GROSS),
    (2, 685, CostTreatment.NET),
    (2, 845, CostTreatment.GROSS),
    (2, 878, CostTreatment.NET),
    (2, 1115, CostTreatment.NET),
    (2, 1192, CostTreatment.NET),
    (2, 1229, CostTreatment.NET),
    (2, 1342, CostTreatment.GROSS),
]


@dataclass(frozen=True)
class Instance:
    """Problema de frontera y sus datos crudos (``mu``, ``Σ``, pesos actuales, costes en bps)."""

    problem: FrontierProblem
    mu: FloatArray
    sigma: FloatArray
    current: FloatArray
    buy_bps: FloatArray
    sell_bps: FloatArray


def instance(n: int, seed: int) -> Instance:
    """Mismo generador que ``frontier_problems`` del test de propiedades."""
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, n)) * 0.1
    sigma = factor @ factor.T + np.diag(rng.uniform(0.01, 0.05, n))
    mu = rng.uniform(0.02, 0.15, n)
    raw = rng.uniform(0.05, 1.0, n)
    current = raw / raw.sum()
    buy = rng.uniform(1.0, 200.0, n)
    sell = rng.uniform(1.0, 200.0, n)
    return _build(mu, sigma, current, buy, sell)


def custom_instance(
    mu: FloatArray, sigma: FloatArray, current: FloatArray, seed: int = 0
) -> Instance:
    """Problema con ``mu``/``Σ`` dados y costes aleatorios en ``[1, 200]`` bps (semilla fija)."""
    rng = np.random.default_rng(seed)
    n = mu.shape[0]
    return _build(mu, sigma, current, rng.uniform(1.0, 200.0, n), rng.uniform(1.0, 200.0, n))


def _build(
    mu: FloatArray, sigma: FloatArray, current: FloatArray, buy: FloatArray, sell: FloatArray
) -> Instance:
    n = mu.shape[0]
    problem = make_problem(
        mu,
        sigma,
        current.tolist(),
        base_config(),
        universe_overrides={
            "MaxWeight": [1.0] * n,
            "BuyCost": buy.tolist(),
            "SellCost": sell.tolist(),
        },
    )
    return Instance(problem, mu, sigma, current, buy, sell)


def lp_max_return(inst: Instance, treatment: CostTreatment, horizon: float) -> float:
    """Retorno máximo alcanzable (LP independiente de HiGHS): bruto ``max μ``; neto con costes."""
    if treatment is not CostTreatment.NET:
        return float(inst.mu.max())
    n = inst.mu.shape[0]
    cost = np.concatenate([-inst.mu, inst.buy_bps / 1e4 / horizon, inst.sell_bps / 1e4 / horizon])
    a_eq = np.zeros((n + 1, 3 * n))
    b_eq = np.zeros(n + 1)
    for i in range(n):
        a_eq[i, i], a_eq[i, n + i], a_eq[i, 2 * n + i], b_eq[i] = 1.0, -1.0, 1.0, inst.current[i]
    a_eq[n, :n], b_eq[n] = 1.0, 1.0
    bounds = [(0.0, 1.0)] * n + [(0.0, None)] * (2 * n)
    result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert result.status == 0
    return float(-result.fun)


def _piece(
    signs: tuple[int, ...],
    mu: FloatArray,
    current: FloatArray,
    buy_cost: FloatArray,
    sell_cost: FloatArray,
) -> tuple[FloatArray, float]:
    """Retorno neto lineal ``coef·w + const`` en la región de compra/venta ``signs``.

    ``+1``: ``w >= w0`` (compra, ``−cb(w − w0)``); ``−1``: ``w <= w0`` (venta, ``−cs(w0 − w)``).
    """
    sign = np.array(signs)
    coef = mu + np.where(sign > 0, -buy_cost, sell_cost)
    const = float(np.sum(np.where(sign > 0, buy_cost * current, -sell_cost * current)))
    return coef, const


def two_asset_reference(
    inst: Instance, treatment: CostTreatment, horizon: float, target: float
) -> float | None:
    """Mínima varianza exacta para dos activos con ``retorno >= target`` (``None`` si infactible).

    ``w = (x, 1 − x)``. Bruto: una sola región sin costes. Neto: las cuatro regiones de
    compra/venta; en cada una el retorno es lineal en ``x`` y la varianza cuadrática convexa, de
    modo que el mínimo de la región es el argmin no restringido recortado al intervalo factible.
    """
    assert inst.mu.shape[0] == 2
    net = treatment is CostTreatment.NET
    buy_cost = inst.buy_bps / 1e4 / horizon if net else np.zeros(2)
    sell_cost = inst.sell_bps / 1e4 / horizon if net else np.zeros(2)
    s11, s12, s22 = inst.sigma[0, 0], inst.sigma[0, 1], inst.sigma[1, 1]
    argmin = (s22 - s12) / (s11 - 2.0 * s12 + s22)
    start = float(inst.current[0])
    best: float | None = None
    for signs in itertools.product((1, -1), repeat=2) if net else [(1, 1)]:
        low, high = 0.0, 1.0
        if net:
            coef, const = _piece(signs, inst.mu, inst.current, buy_cost, sell_cost)
            # activo 1: signo·(x − x0) >= 0; activo 2: signo·(x0 − x) >= 0 (w2 = 1 − x)
            for direction in (signs[0], -signs[1]):
                if direction > 0:
                    low = max(low, start)
                else:
                    high = min(high, start)
        else:
            coef, const = inst.mu, 0.0
        slope = float(coef[0] - coef[1])
        rhs = float(target - coef[1] - const)
        if slope > 0.0:
            low = max(low, rhs / slope)
        elif slope < 0.0:
            high = min(high, rhs / slope)
        elif rhs > 0.0:
            continue
        if low > high:
            continue
        x = min(max(argmin, low), high)
        variance = float(s11 * x * x + 2.0 * s12 * x * (1.0 - x) + s22 * (1.0 - x) ** 2)
        best = variance if best is None else min(best, variance)
    return best


def orthant_reference(inst: Instance, horizon: float, target: float) -> float | None:
    """Mínima varianza neta por enumeración de las regiones de compra/venta + SLSQP (cualquier n).

    En cada región el retorno neto es lineal, de modo que cada subproblema es un QP suave y bien
    planteado; el mínimo global es el mejor de las regiones. ``None`` si ninguna es factible.
    """
    n = inst.mu.shape[0]
    buy_cost = inst.buy_bps / 1e4 / horizon
    sell_cost = inst.sell_bps / 1e4 / horizon
    best: float | None = None
    for signs in itertools.product((1, -1), repeat=n):
        coef, const = _piece(signs, inst.mu, inst.current, buy_cost, sell_cost)
        sign = np.array(signs, dtype=np.float64)
        constraints = [
            {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0), "jac": lambda w: np.ones(n)},
            {
                "type": "ineq",
                "fun": lambda w, c=coef, k=const: float(c @ w + k - target),
                "jac": lambda w, c=coef: c,
            },
            {
                "type": "ineq",
                "fun": lambda w, s=sign: s * (w - inst.current),
                "jac": lambda w, s=sign: np.diag(s),
            },
        ]
        result = minimize(
            lambda w: float(w @ inst.sigma @ w),
            inst.current,
            jac=lambda w: 2.0 * inst.sigma @ w,
            bounds=[(0.0, 1.0)] * n,
            constraints=constraints,
            method="SLSQP",
            options={"ftol": 1e-15, "maxiter": 1000},
        )
        weights = result.x
        feasible = (
            result.success
            and abs(weights.sum() - 1.0) < 1e-9
            and coef @ weights + const >= target - 1e-9
            and np.all(sign * (weights - inst.current) >= -1e-9)
            and np.all(weights >= -1e-9)
        )
        if feasible:
            value = float(weights @ inst.sigma @ weights)
            best = value if best is None else min(best, value)
    return best
