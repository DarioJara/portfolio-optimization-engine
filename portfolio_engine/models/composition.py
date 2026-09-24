"""Composiciones candidatas y diagnósticos del ``CandidateEngine`` (MASTER_SPEC §26-31, §66).

Una composición es un **conjunto** de ``AssetID``: el orden no distingue composiciones. Los
valores ``estimated_*`` de :class:`CandidateComposition` son estimaciones del screening y de la
búsqueda (``CompositionEstimate``), **no** resultados de la optimización continua: los pesos, el
turnover y el coste finales solo existen tras resolver la frontera de la composición.

``candidate_score`` (heurístico, dimensionless: prior de screening acumulado por los movimientos)
es distinto de ``estimated_utility_gain`` (unidades de utilidad ``μᵀw − λ wᵀΣw − TC``) y ambos son
distintos del ``OptimizedPortfolioObjective`` del Bloque 2.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.enums import (
    CandidateOrigin,
    CandidateType,
    EligibilityStatus,
    EvaluationMode,
    MoveKind,
)
from portfolio_engine.utils.numerics import readonly_float_array, readonly_int_array


@dataclass(frozen=True, slots=True)
class SwapMove:
    """Movimiento entre dos composiciones: sale ``out_asset_ids`` y entra ``in_asset_ids``.

    ``screening_prior`` es la puntuación heurística del movimiento (suma de scores de entrada menos
    la de mantenimiento de los que salen); ``risk_aversion`` identifica el perfil de búsqueda.
    """

    kind: MoveKind
    out_asset_ids: tuple[str, ...]
    in_asset_ids: tuple[str, ...]
    level: int
    risk_aversion: float
    screening_prior: float

    def __post_init__(self) -> None:
        if self.kind is MoveKind.SWAP and len(self.out_asset_ids) != len(self.in_asset_ids):
            raise DataValidationError("Un SWAP exige el mismo número de entradas y salidas.")
        if self.kind is MoveKind.ADD and (self.out_asset_ids or not self.in_asset_ids):
            raise DataValidationError("Un ADD solo tiene activos entrantes.")
        if self.kind is MoveKind.DROP and (self.in_asset_ids or not self.out_asset_ids):
            raise DataValidationError("Un DROP solo tiene activos salientes.")


@dataclass(frozen=True, eq=False, slots=True)
class CompositionEstimate:
    """Estimación de la utilidad de una composición para un perfil de aversión ``λ``.

    ``utility = μᵀw − λ wᵀΣw − TC(w)`` evaluada en ``weights`` (pesos **estimados**, no óptimos si
    ``basis`` es ``PROJECTED_WEIGHTS``); ``utility_gain`` es la utilidad menos la de la cartera
    actual con sus pesos actuales. Sin cartera actual o sin costes, ``turnover`` y los costes son
    ``None`` (MASTER_SPEC §24) y la utilidad no descuenta costes.
    """

    composition_hash: str
    risk_aversion: float
    basis: EvaluationMode
    weights: npt.NDArray[np.float64]
    utility: float
    utility_gain: float
    expected_return_gross: float
    variance: float
    turnover: float | None
    transaction_cost_one_off: float | None
    transaction_cost: float | None
    satisfies_constraints: bool
    violations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights", readonly_float_array(self.weights))


@dataclass(frozen=True, eq=False, slots=True)
class CandidateComposition:
    """Composición candidata generada por el ``CandidateEngine`` (MASTER_SPEC §26, CAN-016).

    Attributes:
        composition_id: identificador de la composición (= ``composition_hash``, que coincide con el
            ``CompositionID`` de la frontera continua del Bloque 2).
        global_indices: posiciones globales de los activos (ascendentes).
        asset_ids: AssetID ordenados (conjunto canónico).
        parent_composition_id: composición de la que se obtuvo (``None`` en la de referencia y en
            la semilla de arranque en frío).
        swap_history: movimientos desde la cartera actual hasta esta composición.
        candidate_score: score heurístico del screening (suma de priors de los movimientos).
        estimated_utility_gain: mejora de utilidad estimada en el perfil de origen
            (``best_risk_aversion``); las de los demás perfiles están en ``estimates``.
        estimated_turnover: turnover estimado con los pesos de esa estimación (``None`` si no hay
            cartera actual); estimación, no valor final.
        estimated_transaction_cost: coste estimado (``None`` si no disponible); estimación.
        candidate_type: origen dominante de los activos entrantes.
        origin: etapa que generó la composición.
        estimates: estimaciones por perfil de aversión al riesgo.
        best_risk_aversion: perfil de aversión al riesgo en cuyo ranking entró la composición
            (el de mejor rango si entró en varios); fija ``estimated_utility_gain``.
        estimate_unavailable_reason: motivo de que turnover/coste estimados no estén disponibles.
    """

    composition_id: str
    global_indices: npt.NDArray[np.int64]
    asset_ids: tuple[str, ...]
    parent_composition_id: str | None
    swap_history: tuple[SwapMove, ...]
    candidate_score: float
    estimated_utility_gain: float
    estimated_turnover: float | None
    estimated_transaction_cost: float | None
    candidate_type: CandidateType
    origin: CandidateOrigin
    estimates: tuple[CompositionEstimate, ...]
    best_risk_aversion: float | None
    estimate_unavailable_reason: str | None

    def __post_init__(self) -> None:
        if list(self.asset_ids) != sorted(set(self.asset_ids)):
            raise DataValidationError("CandidateComposition exige AssetID únicos y ordenados.")
        indices = readonly_int_array(self.global_indices)
        if indices.shape != (len(self.asset_ids),):
            raise DataValidationError("global_indices debe tener un valor por activo.")
        object.__setattr__(self, "global_indices", indices)

    @property
    def composition_hash(self) -> str:
        """``CompositionHash``: hash determinista de los AssetID ordenados."""
        return self.composition_id

    @property
    def asset_set(self) -> frozenset[str]:
        """Conjunto de activos de la composición."""
        return frozenset(self.asset_ids)

    @property
    def is_reference(self) -> bool:
        """``True`` para la composición actual conservada como referencia (CAN-022)."""
        return self.origin is CandidateOrigin.REFERENCE


@dataclass(frozen=True, slots=True)
class RejectedComposition:
    """Composición descartada con las causas explícitas del rechazo (sin relajar restricciones)."""

    composition_hash: str
    asset_ids: tuple[str, ...]
    stage: str
    reasons: tuple[str, ...]
    level: int
    risk_aversion: float | None


@dataclass(frozen=True, slots=True)
class StageDiagnostics:
    """Contadores y tiempos de un nivel de la búsqueda (por perfil de aversión al riesgo)."""

    algorithm: CandidateOrigin
    risk_aversion: float
    level: int
    nodes_expanded: int
    neighbors_generated: int
    duplicates_skipped: int
    rejected_by_reason: tuple[tuple[str, int], ...]
    evaluated: int
    survivors: int
    best_utility_gain: float | None
    screening_time: float
    generation_time: float
    evaluation_time: float


@dataclass(frozen=True, slots=True)
class AssetScreeningRecord:
    """Fila de ``CandidateDiagnostics`` por activo del screening de la cartera actual (§66).

    Los scores están en ``[0, 1]`` con normalización ``RANK`` (z-score con ``ZSCORE``); ``None`` si
    el activo no participó en el screening (``rejection_reason`` lo explica).
    """

    asset_id: str
    status: EligibilityStatus
    eligibility_reasons: tuple[str, ...]
    candidate_type: CandidateType | None
    candidate_score: float | None
    alpha_score: float | None
    diversification_score: float | None
    marginal_utility: float | None
    liquidity_score: float | None
    transaction_cost_estimate: float | None
    missing_signals: tuple[str, ...]
    selected_for_optimization: bool
    rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class CandidateDiagnostics:
    """Trazabilidad completa de una generación de composiciones.

    Permite reconstruir por qué se propuso cada composición (``CandidateComposition.swap_history``
    y ``origin``), qué filtros se aplicaron (``eligibility_counts``), qué restricciones provocaron
    rechazos (``rejected_compositions``, ``rejections_by_reason``) y qué búsqueda las generó
    (``stages``). ``evaluation_cache_hits`` cuenta las evaluaciones ``(composición, λ)`` que se
    reutilizaron dentro de la misma generación en lugar de repetirse.
    """

    portfolio_id: str
    scenario_id: str
    cold_start: bool
    eligibility_counts: tuple[tuple[str, int], ...]
    asset_records: tuple[AssetScreeningRecord, ...]
    stages: tuple[StageDiagnostics, ...]
    rejected_compositions: tuple[RejectedComposition, ...]
    rejections_by_reason: tuple[tuple[str, int], ...]
    stop_reasons: tuple[tuple[float, str], ...]
    total_generated: int
    total_evaluated: int
    screening_time: float
    search_time: float
    total_time: float
    notes: tuple[str, ...]
    evaluation_cache_hits: int = 0


@dataclass(frozen=True, eq=False, slots=True)
class CandidateSearchResult:
    """Composiciones candidatas más sus diagnósticos."""

    compositions: tuple[CandidateComposition, ...]
    diagnostics: CandidateDiagnostics
