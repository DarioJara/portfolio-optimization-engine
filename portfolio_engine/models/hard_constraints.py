"""Datos de las restricciones obligatorias efectivas y de su validación final (HC-005, HC-009).

Son solo estructuras de datos inmutables (la lógica vive en ``portfolio_engine.hard_constraints``):

* :class:`EffectiveHardConstraints`: todos los límites obligatorios ya combinados (global, perfil,
  cartera y campos del motor), con su procedencia, las autorizaciones de relajamiento aplicadas, el
  ``ConfigHash`` del motor y su propio hash;
* :class:`FinalProposalReport` y sus piezas: veredicto de la validación final de una propuesta con
  **todas** las causas de rechazo;
* :class:`HardConstraintAudit`: veredicto agregado de una cartera (qué puntos de la frontera global
  se aceptan y por qué se rechaza el resto). Los resultados originales no se modifican: la
  auditoría los referencia por identificador.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from portfolio_engine.models.enums import AuditStatus, CardinalityPolicy, CostTreatment


@dataclass(frozen=True, slots=True)
class AssetWeightException:
    """Override por activo autorizado que se sale de ``[min_active_weight, max_active_weight]``."""

    asset_id: str
    min_weight: float | None
    max_weight: float | None


@dataclass(frozen=True, slots=True)
class AppliedRelaxation:
    """Relajamiento de un límite obligatorio autorizado de forma explícita y trazable."""

    field: str
    authorized_by: str
    reason: str
    reference: str


@dataclass(frozen=True, eq=False, slots=True)
class EffectiveHardConstraints:
    """Restricciones obligatorias efectivas de una cartera (todas las fuentes ya combinadas).

    ``size_min`` / ``size_max`` son el intervalo de cardinalidad de la **política** (``None`` en un
    extremo = no acotado, solo posible sin cartera original); ``target_size`` es el tamaño explícito
    (``None`` = el que permita la política). :attr:`allowed_sizes` es el conjunto final de tamaños
    admisibles. ``max_swaps`` es el ``MaximumSwaps`` de B3 (``max(altas, bajas)``).
    """

    portfolio_id: str
    risk_profile: str | None
    original_size: int
    cardinality_policy: CardinalityPolicy
    size_min: int | None
    size_max: int | None
    target_size: int | None
    max_added_assets: int | None
    max_removed_assets: int | None
    max_total_changed_assets: int | None
    max_replacements: int | None
    max_pure_additions: int | None
    max_pure_removals: int | None
    max_swaps: int | None
    min_volatility: float | None
    max_volatility: float | None
    min_active_weight: float | None
    max_active_weight: float | None
    max_concentration_hhi: float | None
    min_effective_number_of_positions: float | None
    diversification_penalty_weight: float | None
    min_expected_return: float | None
    preserve_original_expected_return: bool
    expected_return_treatment: CostTreatment | None
    max_transaction_cost: float | None
    position_weight_threshold: float
    weight_tolerance: float
    budget_tolerance: float
    volatility_tolerance: float
    hhi_tolerance: float
    return_tolerance: float
    band_max_starts: int | None
    band_max_iterations: int | None
    band_convergence_tolerance: float | None
    asset_exceptions: tuple[AssetWeightException, ...]
    relaxations: tuple[AppliedRelaxation, ...]
    provenance: tuple[tuple[str, str], ...]
    engine_config_hash: str
    effective_hash: str

    @property
    def hhi_cap(self) -> float | None:
        """Cota efectiva de ``Σ w²``: ``min(max_concentration_hhi, 1 / min_effective_number)``."""
        caps = []
        if self.max_concentration_hhi is not None:
            caps.append(self.max_concentration_hhi)
        if self.min_effective_number_of_positions is not None:
            caps.append(1.0 / self.min_effective_number_of_positions)
        return min(caps) if caps else None

    @property
    def has_volatility_band(self) -> bool:
        """``True`` si hay un límite de volatilidad mínimo o máximo."""
        return self.min_volatility is not None or self.max_volatility is not None

    @property
    def allowed_sizes(self) -> tuple[int, ...]:
        """Tamaños de cartera admisibles (vacío = intervalo imposible; véase la factibilidad)."""
        if self.target_size is not None:
            low = self.size_min if self.size_min is not None else self.target_size
            high = self.size_max if self.size_max is not None else self.target_size
            return (self.target_size,) if low <= self.target_size <= high else ()
        if self.size_min is None or self.size_max is None:
            return ()
        return tuple(range(max(self.size_min, 1), self.size_max + 1))

    def provenance_of(self, field: str) -> str:
        """Procedencia (nivel/fuente) del valor efectivo de ``field``."""
        return dict(self.provenance).get(field, "UNSET")

    def exception_for(self, asset_id: str) -> AssetWeightException | None:
        """Override por activo autorizado de ``asset_id``, si existe."""
        return next((e for e in self.asset_exceptions if e.asset_id == asset_id), None)

    def to_payload(self) -> dict[str, object]:
        """Parámetros efectivos como diccionario canónico (persistencia, auditoría y hash)."""
        return {
            field.name: _plain(getattr(self, field.name))
            for field in dataclasses.fields(self)
            if field.name != "effective_hash"
        }


def _plain(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, (CardinalityPolicy, CostTreatment)):
        return value.name
    return value


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Una comprobación: ``excess <= 0`` cumple; ``excess > tolerance`` es una violación."""

    check: str
    passed: bool
    value: float
    limit: float | None
    excess: float
    tolerance: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProposalMetrics:
    """Métricas de la propuesta recalculadas desde los pesos finales."""

    size: int
    added: int
    removed: int
    total_changed: int
    replacements: int
    pure_additions: int
    pure_removals: int
    swaps: int
    weight_sum: float
    min_position_weight: float | None
    max_position_weight: float | None
    hhi: float
    effective_positions: float | None
    volatility: float
    expected_return_gross: float
    expected_return_net: float | None
    original_expected_return: float
    turnover: float
    transaction_cost_one_off: float | None


@dataclass(frozen=True, eq=False, slots=True)
class FinalProposalReport:
    """Veredicto de la validación final: aceptación, causas de rechazo y comprobaciones."""

    label: str
    accepted: bool
    rejection_codes: tuple[str, ...]
    checks: tuple[CheckResult, ...]
    metrics: ProposalMetrics | None
    effective_hash: str

    @property
    def violations(self) -> tuple[CheckResult, ...]:
        """Comprobaciones que no se cumplen."""
        return tuple(check for check in self.checks if not check.passed)


@dataclass(frozen=True, eq=False, slots=True)
class PointVerdict:
    """Veredicto de un punto de la frontera global (identificado por ``global_point_id``)."""

    global_point_id: str
    composition_id: str
    report: FinalProposalReport


@dataclass(frozen=True, eq=False, slots=True)
class BandProposal:
    """Propuesta de máximo retorno bajo **todas** las restricciones obligatorias de una composición.

    Se calcula con la estrategia de banda de volatilidad (convexa si solo hay ``max_volatility``;
    no convexa con ``min_volatility``, véase ``HARD_CONSTRAINTS_DESIGN.md`` §5) y se valida con la
    validación final como cualquier otra propuesta. ``outcome`` es ``OPTIMAL_CERTIFIED`` (óptimo
    global del problema con banda), ``FEASIBLE_LOCAL`` (admisible, sin certificado global; ``gap``
    acota lo que podría mejorarse), ``NO_FEASIBLE_SOLUTION_FOUND`` (la búsqueda no halló un punto
    admisible: **no** demuestra inviabilidad), ``INFEASIBLE_PROVEN`` o ``SOLVER_FAILURE``.
    """

    composition_id: str
    asset_ids: tuple[str, ...]
    outcome: str
    weights: tuple[float, ...] | None
    objective_value: float | None
    upper_bound: float | None
    gap: float | None
    starts_tried: int
    iterations: int
    notes: tuple[str, ...]
    report: FinalProposalReport | None

    @property
    def accepted(self) -> bool:
        """``True`` si hay pesos y superan la validación final."""
        return self.report is not None and self.report.accepted


@dataclass(frozen=True, eq=False, slots=True)
class HardConstraintAudit:
    """Auditoría de restricciones obligatorias de una frontera global.

    ``accepted_point_ids`` son los puntos que superan **todas** las comprobaciones y
    ``accepted_envelope_ids`` los que además son eficientes (Pareto) entre los aceptados; el resto
    se conserva en el resultado original y aquí aparece con todas sus causas de rechazo.
    ``status`` es ``FEASIBLE``, ``NO_FEASIBLE_SOLUTION`` (nada cumple tras buscar) o ``INFEASIBLE``
    (la factibilidad previa lo demuestra). ``ranked_point_ids`` ordena la envolvente aceptada por
    la puntuación secundaria ``retorno − diversification_penalty_weight·Σw²`` (solo entre puntos
    que ya cumplen todo lo obligatorio; nunca rescata uno rechazado). La aceptación garantiza
    **admisibilidad** de lo devuelto;
    no garantiza completitud de la búsqueda ni optimalidad global (véase ``optimality_scope``).
    """

    portfolio_id: str
    effective: EffectiveHardConstraints
    status: AuditStatus
    preflight_causes: tuple[str, ...]
    verdicts: tuple[PointVerdict, ...]
    accepted_point_ids: tuple[str, ...]
    accepted_envelope_ids: tuple[str, ...]
    rejections_by_code: tuple[tuple[str, int], ...]
    optimality_scope: str
    notes: tuple[str, ...] = ()
    band_proposals: tuple[BandProposal, ...] = ()
    ranked_point_ids: tuple[str, ...] = ()
