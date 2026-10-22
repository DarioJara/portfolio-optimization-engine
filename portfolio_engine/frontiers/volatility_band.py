"""Máximo retorno de una composición bajo la banda de volatilidad ``[σ_min, σ_max]`` (HC-007).

Problema (composición ``C`` fija, ``P`` = restricciones lineales compiladas B1–B4 y, si existe,
``Σ w² <= H``)::

    max  r(w)        s.a.  w ∈ P,   σ_min <= √(wᵀΣw) <= σ_max

``σ <= σ_max`` y ``Σ w² <= H`` son conos de segundo orden (convexos); **``σ >= σ_min`` no es
convexa** (complemento de una elipse convexa: «reverse convex»). Estrategia, con garantías
distintas en cada caso:

1. **Relajación convexa** (se descarta ``σ_min``): ``w_A = argmax r(w)`` s.a. ``P``, cono de
   volatilidad máxima y cota de concentración. Su valor ``r_A`` es una **cota superior** del
   problema con banda (el conjunto factible de la banda está contenido en el de la relajación).
   Si ``σ(w_A) >= σ_min`` la solución de la relajación es factible para la banda, luego es el
   **óptimo global certificado** (``OPTIMAL_CERTIFIED``). Si la relajación es inviable, la banda
   también (``INFEASIBLE_PROVEN``, solo con el veredicto firme del solver).
2. **Mínimo activo** (``σ(w_A) < σ_min``): el problema es no convexo y se resuelve de forma
   *local con garantía de admisibilidad* mediante el procedimiento convexo-cóncavo (DC):

   * *Fase 1 (arranque admisible):* ascenso de varianza por linealización. Dado ``v``, se resuelve
     ``w⁺ = argmax (Σv)ᵀw`` s.a. ``P``, conos. Por convexidad ``wᵀΣw >= vᵀΣv + 2(Σv)ᵀ(w − v)``,
     de modo que ``σ(w⁺) >= σ(v)`` (ascenso monótono). Se repite desde cada arranque hasta cruzar
     ``σ_min`` o estancarse. El primer arranque es ``w_A``; los demás concentran el peso en cada
     activo, por orden decreciente de ``Σ_ii`` y luego de ``AssetID`` (determinista).
   * *Fase 2 (mejora de retorno):* dado un punto admisible ``v``, el corte tangente
     ``2(Σv)ᵀw >= σ_min² + vᵀΣv`` es una **aproximación interior** de ``wᵀΣw >= σ_min²`` (porque
     ``wᵀΣw − 2vᵀΣw + vᵀΣv = ‖Lᵀ(w − v)‖² >= 0``) que contiene a ``v``. Resolver el subproblema
     convexo con ese corte da ``w⁺`` admisible con ``r(w⁺) >= r(v)``: iterar produce una sucesión
     monótona de puntos admisibles que converge a un punto KKT (óptimo **local**).
3. **Veredictos honestos.** Si algún arranque produce un punto admisible se devuelve el mejor
   (``FEASIBLE_LOCAL``) junto con la cota ``r_A`` y la brecha ``r_A − r``; si la brecha cabe en la
   tolerancia el resultado se promueve a ``OPTIMAL_CERTIFIED`` (alcanza la cota). Si ningún
   arranque cruza ``σ_min`` el resultado es ``NO_FEASIBLE_SOLUTION_FOUND``: la búsqueda no halló
   un punto admisible, lo que **no** demuestra inviabilidad (maximizar una función convexa sobre un
   politopo es NP-difícil). Nunca se relaja ``σ_min``, ``σ_max`` ni ninguna otra restricción.

El resultado es una *propuesta*: quien lo llama la valida con
:class:`~portfolio_engine.hard_constraints.validator.FinalProposalValidator`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt
import scipy.sparse as sparse

from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.frontiers.continuous_frontier import FrontierProblem
from portfolio_engine.frontiers.session import FrontierContext
from portfolio_engine.frontiers.strategy_optimizer import StrategyOptimizer
from portfolio_engine.models.enums import CostTreatment, SolverStatus
from portfolio_engine.models.hard_constraints import EffectiveHardConstraints
from portfolio_engine.optimizers.formulations.conic import PSDFactor, factor_covariance
from portfolio_engine.optimizers.formulations.model_builder import ModelBuilder
from portfolio_engine.optimizers.formulations.qp_builder import (
    BuiltProblem,
    build_fixed_composition_problem,
)
from portfolio_engine.optimizers.formulations.volatility import add_volatility_limit
from portfolio_engine.optimizers.problem import CanonicalProblem


class BandOutcome(StrEnum):
    """Veredicto de la estrategia de banda (véase el docstring del módulo)."""

    OPTIMAL_CERTIFIED = "OPTIMAL_CERTIFIED"
    FEASIBLE_LOCAL = "FEASIBLE_LOCAL"
    NO_FEASIBLE_SOLUTION_FOUND = "NO_FEASIBLE_SOLUTION_FOUND"
    INFEASIBLE_PROVEN = "INFEASIBLE_PROVEN"
    SOLVER_FAILURE = "SOLVER_FAILURE"


@dataclass(frozen=True, eq=False, slots=True)
class BandResult:
    """Resultado de la estrategia de banda para una composición.

    ``upper_bound`` es el retorno de la relajación convexa (cota superior del óptimo global con
    banda) y ``gap = upper_bound − objective_value``; ambos ``None`` si no hay solución.
    """

    composition_id: str
    asset_ids: tuple[str, ...]
    outcome: BandOutcome
    weights: npt.NDArray[np.float64] | None
    objective_value: float | None
    upper_bound: float | None
    gap: float | None
    relaxation_volatility: float | None
    starts_tried: int
    iterations: int
    notes: tuple[str, ...]


def _row(coefficients: npt.NDArray[np.float64]) -> sparse.csr_matrix:
    return sparse.csr_matrix(coefficients.reshape(1, -1))


class VolatilityBandSolver:
    """Resuelve el máximo retorno de una composición con la banda de volatilidad obligatoria."""

    def __init__(self, config: EngineConfig, optimizer: StrategyOptimizer | None = None) -> None:
        self._config = config
        self._optimizer = optimizer or StrategyOptimizer(config)

    def solve(
        self,
        problem: FrontierProblem,
        treatment: CostTreatment,
        effective: EffectiveHardConstraints,
    ) -> BandResult:
        """Mejor propuesta de ``problem.composition_asset_ids`` bajo ``effective`` (ver módulo)."""
        context, report = self._optimizer.prepare(problem, treatment)
        asset_ids = tuple(problem.composition_asset_ids or ())
        if context is None:
            causes = tuple(f"{c.code}: {c.detail}" for c in report.causes)
            return self._failed(
                "", asset_ids, BandOutcome.INFEASIBLE_PROVEN, ("PRE_SOLVER_CHECK", *causes)
            )
        run = _Run(self._optimizer, self._config, context, treatment, effective)
        return run.execute()

    @staticmethod
    def _failed(
        composition_id: str,
        asset_ids: tuple[str, ...],
        outcome: BandOutcome,
        notes: tuple[str, ...],
    ) -> BandResult:
        return BandResult(
            composition_id, asset_ids, outcome, None, None, None, None, None, 0, 0, notes
        )


class _Run:
    """Estado de una resolución de banda para una composición."""

    def __init__(
        self,
        optimizer: StrategyOptimizer,
        config: EngineConfig,
        context: FrontierContext,
        treatment: CostTreatment,
        effective: EffectiveHardConstraints,
    ) -> None:
        self._optimizer = optimizer
        self._context = context
        self._treatment = treatment
        self._effective = effective
        self._inputs = context.inputs
        self._sigma = context.inputs.sigma
        self._factor: PSDFactor = factor_covariance(self._sigma, config.conic)
        self._n = context.compiled.size
        self._tolerance = float(effective.band_convergence_tolerance or 0.0)
        self._max_iterations = int(effective.band_max_iterations or 1)
        self._max_starts = int(effective.band_max_starts or 1)
        self._vol_tolerance = effective.volatility_tolerance
        self.iterations = 0

    # ------------------------------------------------------------------ problema convexo

    def _build(
        self,
        linear: npt.NDArray[np.float64] | None,
        cut: tuple[npt.NDArray[np.float64], float] | None,
    ) -> tuple[CanonicalProblem, BuiltProblem]:
        """Problema convexo: objetivo (retorno o ``linear·w``), conos y, opcional, corte tangente.

        ``linear`` ``None`` maximiza el retorno del tratamiento; si no, maximiza ``linearᵀw``.
        """
        base = build_fixed_composition_problem(self._inputs, self._treatment, quadratic=False)
        builder = ModelBuilder(base.problem)
        if linear is None:
            builder.set_objective(None, np.array(base.unit_objective, dtype=np.float64))
        else:
            objective = np.zeros(builder.n_variables)
            objective[: self._n] = -linear
            builder.set_objective(None, objective)
        effective = self._effective
        if effective.max_volatility is not None:
            add_volatility_limit(
                builder, self._factor, self._n, effective.max_volatility, "band_max_volatility"
            )
        cap = effective.hhi_cap
        if cap is not None:
            builder.add_cone(
                "band_hhi_cap",
                sparse.identity(self._n, format="csr"),
                np.zeros(self._n),
                np.zeros(self._n),
                math.sqrt(cap),
            )
        if cut is not None:
            gradient, rhs = cut
            builder.add_rows(_row(gradient), np.array([rhs]), np.array([np.inf]))
        return builder.finalize("volatility_band"), base

    def _solve(
        self,
        linear: npt.NDArray[np.float64] | None,
        cut: tuple[npt.NDArray[np.float64], float] | None,
    ) -> tuple[npt.NDArray[np.float64] | None, SolverStatus]:
        problem, _ = self._build(linear, cut)
        result = self._optimizer.solve_problem(problem)
        self.iterations += 1
        if result.x is None or not self._optimizer.accepts(result.status):
            return None, result.status
        return np.array(result.x[: self._n], dtype=np.float64), result.status

    # ------------------------------------------------------------------------- medidas

    def _vol(self, weights: npt.NDArray[np.float64]) -> float:
        return math.sqrt(max(float(weights @ self._sigma @ weights), 0.0))

    def _objective(self, weights: npt.NDArray[np.float64]) -> float:
        return self._optimizer.treatment_return(self._context, weights, self._treatment)

    def _admissible(self, weights: npt.NDArray[np.float64]) -> bool:
        floor = self._effective.min_volatility
        return floor is None or self._vol(weights) >= floor - self._vol_tolerance

    # ------------------------------------------------------------------------ algoritmo

    def execute(self) -> BandResult:
        """Relajación convexa y, si el mínimo de volatilidad está activo, estrategia DC."""
        relaxed, status = self._solve(None, None)
        composition_id = self._context.composition_id
        asset_ids = self._context.compiled.asset_ids
        if relaxed is None:
            outcome = (
                BandOutcome.INFEASIBLE_PROVEN
                if status is SolverStatus.INFEASIBLE
                else BandOutcome.SOLVER_FAILURE
            )
            note = f"RELAXATION_STATUS={status.value}"
            return VolatilityBandSolver._failed(composition_id, asset_ids, outcome, (note,))
        upper = self._objective(relaxed)
        relaxed_vol = self._vol(relaxed)
        if self._admissible(relaxed):
            return self._result(relaxed, upper, relaxed_vol, 1, ("RELAXATION_FEASIBLE_FOR_BAND",))
        return self._floor_active(relaxed, upper, relaxed_vol)

    def _floor_active(
        self, relaxed: npt.NDArray[np.float64], upper: float, relaxed_vol: float
    ) -> BandResult:
        best: npt.NDArray[np.float64] | None = None
        best_value = -math.inf
        tried = 0
        for start in self._starts(relaxed):
            tried += 1
            feasible = self._reach_floor(start)
            if feasible is None:
                continue
            improved = self._improve(feasible)
            value = self._objective(improved)
            if value > best_value:
                best, best_value = improved, value
        if best is None:
            notes = ("FLOOR_NOT_REACHED_FROM_ANY_START", f"RELAXATION_VOLATILITY={relaxed_vol!r}")
            return BandResult(
                self._context.composition_id,
                self._context.compiled.asset_ids,
                BandOutcome.NO_FEASIBLE_SOLUTION_FOUND,
                None,
                None,
                upper,
                None,
                relaxed_vol,
                tried,
                self.iterations,
                notes,
            )
        return self._result(best, upper, relaxed_vol, tried, ("DC_LOCAL_OPTIMUM",))

    def _starts(self, relaxed: npt.NDArray[np.float64]) -> list[npt.NDArray[np.float64]]:
        """Arranques deterministas: la relajación y un punto concentrado por activo."""
        starts = [relaxed]
        order = sorted(
            range(self._n),
            key=lambda i: (-float(self._sigma[i, i]), self._context.compiled.asset_ids[i]),
        )
        for index in order:
            if len(starts) >= self._max_starts:
                break
            direction = np.zeros(self._n)
            direction[index] = 1.0
            point, _ = self._solve(direction, None)
            if point is not None:
                starts.append(point)
        return starts

    def _reach_floor(self, start: npt.NDArray[np.float64]) -> npt.NDArray[np.float64] | None:
        """Ascenso de varianza (linealización) hasta cruzar ``σ_min``; ``None`` si se estanca."""
        current = start
        for _ in range(self._max_iterations):
            if self._admissible(current):
                return current
            point, _ = self._solve(np.asarray(self._sigma @ current), None)
            if point is None:
                return None
            if self._vol(point) <= self._vol(current):
                return point if self._admissible(point) else None
            current = point
        return current if self._admissible(current) else None

    def _improve(self, start: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Mejora de retorno con cortes tangentes (aproximación interior, monótona y admisible)."""
        floor = self._effective.min_volatility
        assert floor is not None
        current, value = start, self._objective(start)
        for _ in range(self._max_iterations):
            gradient = np.asarray(2.0 * (self._sigma @ current))
            rhs = floor**2 + float(current @ self._sigma @ current)
            point, _ = self._solve(None, (gradient, rhs))
            if point is None or not self._admissible(point):
                break
            gained = self._objective(point)
            if gained <= value + self._tolerance:
                if gained > value:
                    current = point
                break
            current, value = point, gained
        return current

    def _result(
        self,
        weights: npt.NDArray[np.float64],
        upper: float,
        relaxed_vol: float,
        tried: int,
        notes: tuple[str, ...],
    ) -> BandResult:
        value = self._objective(weights)
        gap = max(upper - value, 0.0)
        certified = gap <= self._tolerance
        outcome = BandOutcome.OPTIMAL_CERTIFIED if certified else BandOutcome.FEASIBLE_LOCAL
        return BandResult(
            self._context.composition_id,
            self._context.compiled.asset_ids,
            outcome,
            weights,
            value,
            upper,
            gap,
            relaxed_vol,
            tried,
            self.iterations,
            notes,
        )
