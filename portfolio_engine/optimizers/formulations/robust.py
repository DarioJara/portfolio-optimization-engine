"""Optimización robusta: conjuntos de incertidumbre de ``μ`` y ``Σ`` (MASTER_SPEC §52).

Requisitos: ROB-002..005.

Se maximiza la **utilidad del peor caso** dentro de conjuntos de incertidumbre declarados
(``U(w) = min_{μ∈𝓜} μᵀw − λ max_{Σ∈𝓢} wᵀΣw − TC(w)``); no es una simple reducción arbitraria de
``μ``, ni un escenario determinista, ni un estimador de shrinkage (esos son cosas distintas).
Cada conjunto tiene un peor caso **cerrado** que permite una reformulación exacta:

* caja ``μ ∈ [μ̂ − δ, μ̂ + δ]`` (P15): ``min μᵀw = μ̂ᵀw − δᵀ|w|``. Con ``w >= 0`` para todo activo
  es lineal (``(μ̂ − δ)ᵀw``); en general se usan ``a >= |w|`` (``a >= w``, ``a >= −w``) y coste
  ``δᵀa`` (exacto porque ``δ >= 0`` y se maximiza);
* elipsoide ``(μ − μ̂)ᵀΩ⁻¹(μ − μ̂) <= κ²`` (P16): ``min μᵀw = μ̂ᵀw − κ‖Ω^{½}w‖₂``; se añade
  ``ν >= κ‖L_Ωᵀw‖`` (cono) con coste ``ν``;
* covarianzas en un conjunto finito ``{Σ_k}`` (P17; el conjunto escalado ``{aΣ : a ∈ [1, s]}`` se
  reduce a ``{sΣ}`` porque ``wᵀ(aΣ)w`` es creciente en ``a``): ``λ τ`` con ``τ >= wᵀΣ_kw`` ∀k
  (conos rotados). La incertidumbre general de ``Σ`` requeriría SDP: no implementada (A-23).

El objetivo se escribe como el del Bloque 2 (``θ = 1/λ``): ``minimize τ' + θ(−μ̂ᵀw + ρ + TC)`` con
``τ' = wᵀΣw`` (objetivo cuadrático ``P = 2Σ``) o la variable epígrafe ``τ`` con los conos. Sin
ningún conjunto de incertidumbre la formulación coincide con la utilidad del Bloque 2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.models.enums import CostTreatment, MuUncertaintyKind
from portfolio_engine.optimizers.formulations.conic import (
    PSDFactor,
    quadratic_cone,
    volatility_cone,
)
from portfolio_engine.optimizers.formulations.model_builder import ExtendedProblem, ModelBuilder
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    CompositionInputs,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.formulations.volatility import VolatilityCap, add_volatility_cap


@dataclass(frozen=True, eq=False, slots=True)
class MuUncertaintySet:
    """Conjunto de incertidumbre de ``μ`` sobre los activos de la composición.

    ``BOX`` usa ``half_width`` (``δ >= 0``); ``ELLIPSOIDAL`` usa ``radius`` (``κ >= 0``) y el
    factor ``omega_factor`` de la covarianza del error ``Ω``. ``NONE`` no lleva datos.
    """

    kind: MuUncertaintyKind
    half_width: npt.NDArray[np.float64] | None = None
    radius: float | None = None
    omega_factor: PSDFactor | None = None
    omega: npt.NDArray[np.float64] | None = None

    def __post_init__(self) -> None:
        if self.kind is MuUncertaintyKind.BOX:
            if self.half_width is None or np.any(self.half_width < 0.0):
                raise UnsupportedCombinationError("BOX exige half_width >= 0 por activo.")
            if not np.all(np.isfinite(self.half_width)):
                raise UnsupportedCombinationError("half_width debe ser finito.")
        elif self.kind is MuUncertaintyKind.ELLIPSOIDAL:
            if self.omega_factor is None or self.radius is None or self.omega is None:
                raise UnsupportedCombinationError(
                    "ELLIPSOIDAL exige radius, omega y su factor omega_factor."
                )
            if not math.isfinite(self.radius) or self.radius < 0.0:
                raise UnsupportedCombinationError("radius debe ser finito y >= 0.")
        elif self.half_width is not None or self.radius is not None:
            raise UnsupportedCombinationError("NONE no admite parámetros de incertidumbre.")


def build_robust_problem(
    inputs: CompositionInputs,
    cost_treatment: CostTreatment,
    risk_aversion: float,
    mu_set: MuUncertaintySet,
    covariance_factors: tuple[PSDFactor, ...] = (),
    volatility_cap: VolatilityCap | None = None,
) -> tuple[ExtendedProblem, BuiltProblem]:
    """Utilidad del peor caso sobre los conjuntos indicados (P15, P16, P17; ROB-005).

    Con ``mu_set.kind = NONE`` y sin ``covariance_factors`` se rechaza: sería la utilidad del
    Bloque 2 presentada como robusta.
    """
    n = inputs.compiled.size
    _check_inputs(mu_set, risk_aversion, covariance_factors, n)
    theta = 1.0 / risk_aversion
    base = build_fixed_composition_problem(inputs, cost_treatment, quadratic=True)
    builder = ModelBuilder(base.problem)
    unit = np.array(base.unit_objective, dtype=np.float64)
    extra_costs: dict[int, float] = {}
    roles: dict[str, int] = {}
    columns = np.arange(n, dtype=np.int64)
    if mu_set.kind is MuUncertaintyKind.BOX and mu_set.half_width is not None:
        if mu_set.half_width.shape != (n,):
            raise UnsupportedCombinationError("half_width debe tener un valor por activo.")
        long_only = bool(np.all(inputs.compiled.lower >= 0.0))
        start = _add_box(builder, mu_set.half_width, long_only, unit, theta, extra_costs)
        if start is not None:
            roles["abs_w"] = start
    tau_index: int | None = None
    if covariance_factors:
        tau_index = builder.add_variables(1)
        roles["tau"] = tau_index
        extra_costs[tau_index] = 1.0
    if mu_set.kind is MuUncertaintyKind.ELLIPSOIDAL and mu_set.omega_factor is not None:
        nu_index = _add_ellipsoid(builder, mu_set.omega_factor, float(mu_set.radius or 0.0), n)
        roles["nu"] = nu_index
        extra_costs[nu_index] = theta
    linear = np.zeros(builder.n_variables)
    linear[: unit.shape[0]] = theta * unit
    for index, cost in extra_costs.items():
        linear[index] = cost
    builder.set_objective(None if tau_index is not None else base.problem.P, linear)
    for index, factor in enumerate(covariance_factors):
        if tau_index is None:
            raise UnsupportedCombinationError("Falta la variable epígrafe de la covarianza.")
        height = np.zeros(builder.n_variables)
        height[tau_index] = 1.0
        cone = quadratic_cone(factor, columns, builder.n_variables, height, 0.0)
        builder.add_cone(
            f"covariance_set:{index}", cone.matrix, cone.offset, cone.height, cone.constant
        )
    add_volatility_cap(builder, volatility_cap, base.n_weights)
    problem = builder.finalize("robust_worst_case_utility")
    extended = ExtendedProblem(
        problem=problem,
        n_weights=base.n_weights,
        n_base_variables=base.problem.n_variables,
        roles=roles,
        description="Utilidad del peor caso con conjuntos de incertidumbre de μ y/o Σ",
    )
    return extended, base


def _check_inputs(
    mu_set: MuUncertaintySet,
    risk_aversion: float,
    covariance_factors: tuple[PSDFactor, ...],
    n: int,
) -> None:
    if mu_set.kind is MuUncertaintyKind.NONE and not covariance_factors:
        raise UnsupportedCombinationError(
            "Optimización robusta sin ningún conjunto de incertidumbre: use la utilidad del "
            "Bloque 2; no se etiqueta como robusta."
        )
    if not math.isfinite(risk_aversion) or risk_aversion <= 0.0:
        raise UnsupportedCombinationError("risk_aversion debe ser finito y > 0.")
    if any(factor.loading.shape[0] != n for factor in covariance_factors):
        raise UnsupportedCombinationError("Un factor de Σ no corresponde a la composición.")


def _add_ellipsoid(builder: ModelBuilder, factor: PSDFactor, radius: float, n: int) -> int:
    """Añade ``ν >= κ‖L_Ωᵀw‖`` (cono de segundo orden) y devuelve el índice de ``ν``."""
    nu_index = builder.add_variables(1)
    cone = volatility_cone(factor, np.arange(n, dtype=np.int64), builder.n_variables, 0.0)
    height = np.zeros(builder.n_variables)
    height[nu_index] = 1.0
    builder.add_cone("mu_ellipsoid", radius * cone.matrix, cone.offset, height, 0.0)
    return nu_index


def _add_box(
    builder: ModelBuilder,
    half_width: npt.NDArray[np.float64],
    long_only: bool,
    unit: npt.NDArray[np.float64],
    theta: float,
    extra_costs: dict[int, float],
) -> int | None:
    """Peor caso de la caja ``min μᵀw = μ̂ᵀw − δᵀ|w|``.

    Con ``w >= 0`` (todas las cotas inferiores no negativas) es lineal: se suma ``δ`` al vector de
    coste unitario (``(μ̂ − δ)ᵀw``) y no hay variables nuevas (devuelve ``None``). En general se
    añaden ``a >= |w|`` (``a − w >= 0``, ``a + w >= 0``) con coste ``θ·δ`` y se devuelve el
    índice de la primera.
    """
    n = half_width.shape[0]
    if long_only:
        unit[:n] += half_width
        return None
    start = builder.add_variables(n, lower=0.0)
    columns = np.arange(n, dtype=np.int64)
    total = builder.n_variables
    identity = sparse.csr_matrix((np.ones(n), (columns, columns)), shape=(n, total))
    abs_part = sparse.csr_matrix((np.ones(n), (columns, start + columns)), shape=(n, total))
    builder.add_rows(abs_part - identity, np.zeros(n), np.full(n, np.inf))
    builder.add_rows(abs_part + identity, np.zeros(n), np.full(n, np.inf))
    extra_costs.update({start + i: theta * float(half_width[i]) for i in range(n)})
    return start
