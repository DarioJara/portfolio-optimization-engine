"""``EXACT_MIP``: MIQP / MISOCP de cardinalidad con posiciones semicontinuas (§49).

Requisitos: MIP-001, MIP-006.

Sobre un universo ``U`` (composición que contiene **todos** los activos actuales y el conjunto de
candidatos del que se elige) se formula, con ``z_i ∈ {0, 1}`` (``z_i = 1`` ⇔ el activo
``i`` pertenece
a la composición)::

    minimize    wᵀΣw − θ(μᵀw − TC(w))                     (objetivo del Bloque 2, θ = 1/λ)
    subject to  l_i z_i <= w_i <= u_i z_i                 (MinWeight·z <= w <= MaxWeight·z)
                Σ_i z_i = TargetPortfolioSize                        (si se exige)
                Σ_{i ∉ actual} z_i <= MaximumNewAssets               (si se exige)
                Σ_{i ∉ actual} z_i <= MaximumSwaps,  Σ_{i ∈ actual}(1 − z_i) <= MaximumSwaps
                z_i = 1 (FREEZE_WEIGHT), z_i = 0 (cota superior efectiva nula)
                budget, grupos, lifting w − b + s = w0, turnover, costes NET

donde ``l_i`` y ``u_i`` son las cotas efectivas **compiladas** (incluyen ``MinWeight`` /
``min_holding_weight``, ``MaxWeight`` y los topes de E-09, E-10 y ADV/NAV): las restricciones
económicas de la composición fija se conservan íntegras. Un activo con ``z_i = 0`` tiene
``w_i = 0`` y,
si estaba en cartera, se vende por completo (``s_i = w0_i``) con su coste de venta: la
liquidación de
los activos que salen entra en el objetivo y en el turnover de forma exacta, sin heurísticas. Con
``volatility_limit`` se añade el cono ``‖Lᵀw‖ <= σ_max`` (MISOCP).

Es un problema convexo relajable con variables binarias: SCIP lo resuelve con branch-and-bound y
entrega una cota dual válida (``optimality gap``). No es apto para el bucle interno de producción.
Cuando ``l_i = 0`` un miembro puede tener peso 0: la cardinalidad es la de la composición (variables
de decisión, decisión A-08); ``min_holding_weight`` la convierte en tenencia estrictamente positiva.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import scipy.sparse as sparse

from portfolio_engine.constraints.compiler import CompiledConstraints
from portfolio_engine.constraints.integer import CompositionLimits, membership_rules
from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.optimizers.formulations.conic import PSDFactor
from portfolio_engine.optimizers.formulations.model_builder import ExtendedProblem, ModelBuilder
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.formulations.volatility import add_volatility_limit


def build_cardinality_miqp(
    inputs: CompositionInputs,
    cost_treatment: CostTreatment,
    risk_aversion: float,
    limits: CompositionLimits,
    *,
    volatility_factor: PSDFactor | None = None,
    volatility_limit: float | None = None,
) -> tuple[ExtendedProblem, BuiltProblem]:
    """MIQP (o MISOCP con ``volatility_limit``) de cardinalidad sobre el universo ``inputs``.

    ``limits.target_size``, ``max_new_assets`` y ``max_swaps`` son opcionales; ``limits.mandatory``
    son ``AssetID`` que deben permanecer. Rechaza un universo que no contiene toda la
    cartera actual.
    """
    compiled = inputs.compiled
    n = compiled.size
    if compiled.exited:
        raise UnsupportedCombinationError(
            "El universo del MIP debe contener todos los activos de la cartera actual: hay "
            f"{len(compiled.exited)} activos actuales fuera de él."
        )
    if not math.isfinite(risk_aversion) or risk_aversion <= 0.0:
        raise UnsupportedCombinationError("risk_aversion debe ser finito y > 0.")
    if (volatility_factor is None) != (volatility_limit is None):
        raise UnsupportedCombinationError("volatility_factor y volatility_limit van juntos.")
    _check_limits(limits, n)
    lower, upper = np.array(compiled.lower), np.array(compiled.upper)
    hull = dataclasses.replace(compiled, lower=np.minimum(lower, 0.0), upper=np.maximum(upper, 0.0))
    relaxed = CompositionInputs(inputs.mu, inputs.sigma, hull, inputs.cost_model)
    base = build_fixed_composition_problem(relaxed, cost_treatment, quadratic=True)
    builder = ModelBuilder(base.problem)
    builder.set_objective(base.problem.P, base.q_risk_aversion(1.0 / risk_aversion))
    z_start = builder.add_variables(n)
    builder.mark_binary(range(z_start, z_start + n))
    total = builder.n_variables
    weights = np.arange(n)
    z_cols = z_start + weights
    link_lower = _link(weights, z_cols, lower, total, n)
    link_upper = _link(weights, z_cols, upper, total, n)
    builder.add_rows(link_lower, np.zeros(n), np.full(n, np.inf))
    builder.add_rows(link_upper, np.full(n, -np.inf), np.zeros(n))
    _add_membership_rows(builder, compiled, limits, z_cols, total)
    if volatility_factor is not None and volatility_limit is not None:
        add_volatility_limit(builder, volatility_factor, n, volatility_limit, "volatility_limit")
    problem = builder.finalize("exact_mip_cardinality")
    extended = ExtendedProblem(
        problem=problem,
        n_weights=n,
        n_base_variables=base.problem.n_variables,
        roles={"z": z_start},
        description="MIQP de cardinalidad: MinWeight·z <= w <= MaxWeight·z, Σz = K",
    )
    return extended, base


def _check_limits(limits: CompositionLimits, n: int) -> None:
    if limits.target_size is not None and not 0 < limits.target_size <= n:
        raise UnsupportedCombinationError(
            f"TargetPortfolioSize {limits.target_size} fuera de (0, {n}]."
        )
    for value, name in ((limits.max_new_assets, "max_new_assets"), (limits.max_swaps, "max_swaps")):
        if value is not None and value < 0:
            raise UnsupportedCombinationError(f"{name} no puede ser negativo.")


def _link(
    weights: np.ndarray, z_cols: np.ndarray, bound: np.ndarray, total: int, n: int
) -> sparse.csr_matrix:
    """Filas ``w_i − bound_i·z_i`` (cota semicontinua)."""
    rows = np.concatenate([np.arange(n), np.arange(n)])
    cols = np.concatenate([weights, z_cols])
    values = np.concatenate([np.ones(n), -bound])
    return sparse.csr_matrix((values, (rows, cols)), shape=(n, total))


def _add_membership_rows(
    builder: ModelBuilder,
    compiled: CompiledConstraints,
    limits: CompositionLimits,
    z_cols: np.ndarray,
    total: int,
) -> None:
    n = compiled.size
    held = compiled.current_weights > 0.0

    def row(mask: np.ndarray, sign: float = 1.0) -> sparse.csr_matrix:
        columns = z_cols[mask]
        return sparse.csr_matrix(
            (np.full(columns.shape[0], sign), (np.zeros(columns.shape[0]), columns)),
            shape=(1, total),
        )

    everyone = np.ones(n, dtype=bool)
    if limits.target_size is not None:
        target = float(limits.target_size)
        builder.add_rows(row(everyone), np.full(1, target), np.full(1, target))
    if limits.max_new_assets is not None:
        builder.add_rows(row(~held), np.full(1, -np.inf), np.full(1, float(limits.max_new_assets)))
    if limits.max_swaps is not None:
        swaps = float(limits.max_swaps)
        builder.add_rows(row(~held), np.full(1, -np.inf), np.full(1, swaps))
        # retirados = |actual| − Σ_{actual} z  <=  swaps  ⇔  Σ_{actual} z >= |actual| − swaps
        builder.add_rows(row(held), np.full(1, float(held.sum()) - swaps), np.full(1, np.inf))
    rules = membership_rules(compiled)
    mandatory = {compiled.asset_ids.index(a) for a in limits.mandatory if a in compiled.asset_ids}
    for position in sorted(set(rules.mandatory) | mandatory):
        one = np.zeros(n, dtype=bool)
        one[position] = True
        builder.add_rows(row(one), np.ones(1), np.ones(1))
    for position in rules.forbidden:
        one = np.zeros(n, dtype=bool)
        one[position] = True
        builder.add_rows(row(one), np.zeros(1), np.zeros(1))
