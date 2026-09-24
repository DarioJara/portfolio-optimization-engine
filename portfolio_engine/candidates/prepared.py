"""Datos de una composición concreta listos para evaluarla (MASTER_SPEC §15, §59).

``CompositionFactory`` convierte un conjunto de posiciones globales en un
:class:`PreparedComposition`: mapa de índices global ↔ elegible ↔ local, restricciones compiladas
con el ``ConstraintCompiler`` del Bloque 2 (que ya traduce la política de restringidos y las
liquidaciones de los activos retirados), factibilidad previa determinista, ``mu_C``, ``Σ_C`` y el
modelo de costes sobre la unión ``current ∪ C``.

``Σ_C`` (``n×n``) se extrae **solo** cuando la composición existe; la covarianza global ``N×N`` no
se copia nunca. La memoización interna es local a una búsqueda (evita recompilar la misma
composición para varios perfiles de aversión al riesgo) y guarda datos derivados, no resultados de
optimización: no es la caché de resultados del Bloque 5.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates.composition_hash import composition_hash_of
from portfolio_engine.candidates.universe_data import UniverseSnapshot
from portfolio_engine.constraints.compiler import CompiledConstraints, ConstraintCompiler
from portfolio_engine.constraints.constraint_set import ConstraintSet
from portfolio_engine.constraints.feasibility import PreFeasibilityChecker
from portfolio_engine.costs.transaction_cost_model import (
    TransactionCostModel,
    UnionAlignment,
    align_union,
)
from portfolio_engine.exceptions import ConstraintCompilationError, TransactionCostInputError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.portfolio import CurrentPortfolioState
from portfolio_engine.models.universe_index import CompositionIndexMap, EligibleUniverseIndex

CODE_COMPILATION_ERROR = "CONSTRAINT_COMPILATION_ERROR"
CODE_MISSING_COSTS = "MISSING_TRANSACTION_COST"


@dataclass(frozen=True, eq=False, slots=True)
class PreparedComposition:
    """Una composición con sus restricciones compiladas y submatrices locales.

    ``feasible = False`` implica que el solver no debe invocarse: ``infeasibility_codes`` y
    ``infeasibility_details`` recogen las causas deterministas. En ese caso ``compiled``
    puede ser ``None`` (p. ej. error de compilación); ``mu`` y ``sigma`` siempre existen.
    """

    composition_hash: str
    index_map: CompositionIndexMap
    compiled: CompiledConstraints | None
    feasible: bool
    infeasibility_codes: tuple[str, ...]
    infeasibility_details: tuple[str, ...]
    mu: npt.NDArray[np.float64]
    sigma: npt.NDArray[np.float64]
    alignment: UnionAlignment
    cost_model: TransactionCostModel | None

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """AssetID ordenados de la composición."""
        return self.index_map.asset_ids


class CompositionFactory:
    """Prepara composiciones de una cartera con sus restricciones y su modelo de riesgo."""

    def __init__(
        self,
        *,
        snapshot: UniverseSnapshot,
        eligible: EligibleUniverseIndex,
        universe: Universe,
        state: CurrentPortfolioState,
        costs: AssetCostVector | None,
        constraint_set: ConstraintSet,
        checker: PreFeasibilityChecker,
        horizon_years: float,
    ) -> None:
        self._snapshot = snapshot
        self._eligible = eligible
        self._universe = universe
        self._state = state
        self._costs = costs
        self._constraint_set = constraint_set
        self._checker = checker
        self._horizon = horizon_years
        self._compiler = ConstraintCompiler()
        self._memo: dict[tuple[int, ...], PreparedComposition] = {}
        self._hashes: dict[tuple[int, ...], str] = {}

    def digest(self, positions: Iterable[int]) -> str:
        """``CompositionHash`` de las posiciones globales (memoizado en la búsqueda)."""
        key = tuple(sorted({int(position) for position in positions}))
        found = self._hashes.get(key)
        if found is None:
            index = self._snapshot.index
            found = composition_hash_of(index.asset_id_at(p) for p in key)
            self._hashes[key] = found
        return found

    def prepare(self, positions: Iterable[int]) -> PreparedComposition:
        """Composición formada por las posiciones globales ``positions`` (cualquier orden)."""
        key = tuple(sorted({int(position) for position in positions}))
        cached = self._memo.get(key)
        if cached is None:
            cached = self._build(key)
            self._memo[key] = cached
        return cached

    def _build(self, key: tuple[int, ...]) -> PreparedComposition:
        snapshot = self._snapshot
        asset_ids = tuple(snapshot.index.asset_id_at(position) for position in key)
        index_map = CompositionIndexMap.build(self._eligible, asset_ids)
        mu = index_map.extract_vector(snapshot.mu)
        sigma = index_map.extract_submatrix(snapshot.sigma)
        alignment = align_union(self._state, asset_ids)
        digest = self.digest(key)
        try:
            compiled = self._compiler.compile(
                self._constraint_set, self._universe, asset_ids, self._state
            )
        except ConstraintCompilationError as error:
            return PreparedComposition(
                composition_hash=digest,
                index_map=index_map,
                compiled=None,
                feasible=False,
                infeasibility_codes=(CODE_COMPILATION_ERROR,),
                infeasibility_details=(str(error),),
                mu=mu,
                sigma=sigma,
                alignment=alignment,
                cost_model=None,
            )
        report = self._checker.check(compiled)
        codes = tuple(cause.code for cause in report.causes)
        details = tuple(f"{cause.code}: {cause.detail}" for cause in report.causes)
        cost_model: TransactionCostModel | None = None
        if alignment.has_current_portfolio and self._costs is not None:
            try:
                cost_model = TransactionCostModel(alignment, self._costs, self._horizon)
            except TransactionCostInputError as error:
                codes, details = (*codes, CODE_MISSING_COSTS), (*details, str(error))
        return PreparedComposition(
            digest, index_map, compiled, not codes, codes, details, mu, sigma, alignment, cost_model
        )
