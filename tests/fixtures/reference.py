"""Soluciones de referencia independientes del optimizador (fórmulas cerradas y SciPy).

Ningún test usa el propio motor para calcular su resultado esperado: estas funciones resuelven los
mismos problemas con álgebra lineal (NumPy), SLSQP/HiGHS (SciPy) o enumeración analítica.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from scipy.optimize import linprog, minimize

FloatArray = npt.NDArray[np.float64]


def min_variance_budget_only(sigma: FloatArray) -> FloatArray:
    """``argmin wᵀΣw`` s.a. ``1ᵀw = 1``: ``w = Σ⁻¹1 / (1ᵀΣ⁻¹1)`` (sin límites activos)."""
    ones = np.ones(sigma.shape[0])
    solved = np.linalg.solve(sigma, ones)
    return np.asarray(solved / solved.sum(), dtype=np.float64)


def risk_aversion_budget_only(sigma: FloatArray, mu: FloatArray, theta: float) -> FloatArray:
    """``argmin wᵀΣw − θμᵀw`` s.a. ``1ᵀw = 1`` resolviendo el sistema KKT (sin límites activos)."""
    n = sigma.shape[0]
    kkt = np.zeros((n + 1, n + 1))
    kkt[:n, :n] = 2.0 * sigma
    kkt[:n, n] = -1.0
    kkt[n, :n] = 1.0
    rhs = np.concatenate([theta * mu, [1.0]])
    return np.asarray(np.linalg.solve(kkt, rhs)[:n], dtype=np.float64)


def max_return_box_budget(mu: FloatArray, lower: FloatArray, upper: FloatArray) -> FloatArray:
    """``argmax μᵀw`` s.a. ``1ᵀw = 1``, ``lower <= w <= upper``: llenado voraz por retorno."""
    weights = lower.astype(np.float64).copy()
    remaining = 1.0 - weights.sum()
    for index in np.argsort(-mu, kind="stable"):
        step = min(upper[index] - weights[index], remaining)
        weights[index] += step
        remaining -= step
    return weights


def slsqp_qp(
    sigma: FloatArray,
    linear: FloatArray,
    lower: FloatArray,
    upper: FloatArray,
    *,
    start: FloatArray,
    extra_ineq: Sequence[tuple[FloatArray, float, float]] = (),
) -> FloatArray:
    """``min wᵀΣw + linearᵀw`` s.a. ``1ᵀw = 1``, cotas y filas ``lo <= a·w <= hi`` (SLSQP)."""
    constraints: list[dict[str, object]] = [
        {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0), "jac": lambda w: np.ones_like(w)}
    ]
    for row, low, high in extra_ineq:
        if np.isfinite(low):
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, r=row, lo=low: float(r @ w - lo),
                    "jac": lambda w, r=row: r,
                }
            )
        if np.isfinite(high):
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, r=row, hi=high: float(hi - r @ w),
                    "jac": lambda w, r=row: -r,
                }
            )
    result = minimize(
        lambda w: float(w @ sigma @ w + linear @ w),
        start,
        jac=lambda w: 2.0 * sigma @ w + linear,
        bounds=list(zip(lower.tolist(), upper.tolist(), strict=True)),
        constraints=constraints,
        method="SLSQP",
        options={"ftol": 1e-15, "maxiter": 1000},
    )
    assert result.success, result.message
    return np.asarray(result.x, dtype=np.float64)


def two_asset_net_optimum(
    sigma: FloatArray,
    mu: FloatArray,
    theta: float,
    current_first: float,
    up_cost: float,
    down_cost: float,
    horizon: float,
    lower: float,
    upper: float,
) -> float:
    """Peso óptimo del activo 1 en el problema neto de 2 activos, por análisis de tramos.

    Con ``w = (t, 1−t)`` y ``a = w0_1``: ``TC_one_off = up·(t−a)⁺ + down·(a−t)⁺`` donde
    ``up = c_b1 + c_s2`` y ``down = c_s1 + c_b2``. La función
    ``f(t) = wᵀΣw − θμᵀw + θ·TC_one_off/H`` es convexa y por tramos cuadrática: se evalúan el
    mínimo interior de cada tramo (derivada nula), el nudo ``t = a`` y las cotas.
    """
    s11, s22, s12 = sigma[0, 0], sigma[1, 1], sigma[0, 1]
    # wᵀΣw = s22 + 2(s12 − s22)t + (s11 + s22 − 2 s12)t²;  μᵀw = mu2 + (mu1 − mu2)t
    quad = s11 + s22 - 2.0 * s12
    lin_base = 2.0 * (s12 - s22) - theta * (mu[0] - mu[1])

    def objective(t: float) -> float:
        tc = up_cost * max(t - current_first, 0.0) + down_cost * max(current_first - t, 0.0)
        variance = s22 + 2.0 * (s12 - s22) * t + quad * t * t
        return float(variance - theta * (mu[1] + (mu[0] - mu[1]) * t) + theta * tc / horizon)

    candidates = [lower, upper, min(max(current_first, lower), upper)]
    for slope in (theta * up_cost / horizon, -theta * down_cost / horizon):
        stationary = -(lin_base + slope) / (2.0 * quad)
        candidates.append(min(max(stationary, lower), upper))
    return float(min(candidates, key=objective))


def min_turnover_lp(
    current: FloatArray, lower: FloatArray, upper: FloatArray, budget: float = 1.0
) -> float:
    """Menor ``0.5·Σ|w − w0|`` con ``1ᵀw = budget`` y cotas, resuelto como LP (HiGHS)."""
    n = current.shape[0]
    cost = np.concatenate([np.zeros(n), np.full(n, 0.5), np.full(n, 0.5)])
    identity = np.eye(n)
    a_eq = np.vstack(
        [
            np.hstack([np.ones((1, n)), np.zeros((1, n)), np.zeros((1, n))]),
            np.hstack([identity, -identity, identity]),
        ]
    )
    b_eq = np.concatenate([[budget], current])
    bounds = [*zip(lower.tolist(), upper.tolist(), strict=True)] + [(0.0, None)] * (n + n)
    result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert result.success, result.message
    return float(result.fun)


def max_net_return_lp(
    mu: FloatArray,
    current: FloatArray,
    buy: FloatArray,
    sell: FloatArray,
    lower: FloatArray,
    upper: FloatArray,
    horizon: float = 1.0,
) -> float:
    """Máximo de ``μᵀw − (c_bᵀb + c_sᵀs)/H`` con ``w − b + s = w0`` y ``1ᵀw = 1`` (HiGHS)."""
    n = mu.shape[0]
    cost = np.concatenate([-mu, buy / horizon, sell / horizon])
    identity = np.eye(n)
    a_eq = np.vstack(
        [
            np.hstack([np.ones((1, n)), np.zeros((1, n)), np.zeros((1, n))]),
            np.hstack([identity, -identity, identity]),
        ]
    )
    b_eq = np.concatenate([[1.0], current])
    bounds = [*zip(lower.tolist(), upper.tolist(), strict=True)] + [(0.0, None)] * (n + n)
    result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    assert result.success, result.message
    return float(-result.fun)
