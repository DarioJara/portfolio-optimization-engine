"""Diagnósticos del ``CandidateEngine`` (MASTER_SPEC §66; CAN-017, OUT-004).

* :class:`RejectionLog`: registro acotado de composiciones rechazadas y contadores por causa
  (qué restricciones o filtros provocaron rechazos).
* :func:`build_asset_records`: una fila por activo con el screening de la cartera actual, su
  clasificación de elegibilidad, si se seleccionó para optimización y, si no, por qué.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence

import numpy as np

from portfolio_engine.candidates.eligibility import EligibilityResult
from portfolio_engine.candidates.screening import (
    ROW_ALPHA,
    ROW_COST,
    ROW_LIQUIDITY,
    ROW_UTILITY,
    ScreeningResult,
    SignalTable,
)
from portfolio_engine.models.composition import AssetScreeningRecord, RejectedComposition
from portfolio_engine.models.enums import CandidateType, EligibilityStatus

REASON_NOT_SHORTLISTED = "NOT_SHORTLISTED"
REASON_MISSING_SIGNAL = "MISSING_SIGNAL_EXCLUDED"
REASON_MANDATORY_EXIT = "MANDATORY_EXIT"


class RejectionLog:
    """Conserva las primeras ``max_recorded`` composiciones rechazadas y cuenta todas por causa."""

    def __init__(self, max_recorded: int) -> None:
        self._max = max_recorded
        self._records: list[RejectedComposition] = []
        self._counts: Counter[str] = Counter()

    def record(
        self,
        composition_hash: str,
        asset_ids: tuple[str, ...],
        stage: str,
        reasons: Sequence[str],
        level: int,
        risk_aversion: float | None,
    ) -> None:
        """Registra un rechazo con todas sus causas."""
        for reason in reasons:
            self._counts[reason] += 1
        if len(self._records) < self._max:
            self._records.append(
                RejectedComposition(
                    composition_hash, asset_ids, stage, tuple(reasons), level, risk_aversion
                )
            )

    @property
    def records(self) -> tuple[RejectedComposition, ...]:
        """Rechazos conservados (acotados por ``max_recorded_rejections``)."""
        return tuple(self._records)

    def by_reason(self) -> tuple[tuple[str, int], ...]:
        """Número de rechazos por causa, en orden alfabético."""
        return tuple(sorted(self._counts.items()))


def _score_of(table: SignalTable, row: int, item: int) -> float | None:
    value = table.normalized[row, item]
    return None if np.isnan(value) else float(value)


def _record_from_table(
    table: SignalTable,
    item: int,
    asset_id: str,
    status: EligibilityStatus,
    reasons: tuple[str, ...],
    candidate_type: CandidateType | None,
    selected: bool,
) -> AssetScreeningRecord:
    excluded = bool(table.excluded[item])
    score = float(table.score[item])
    cost = table.raw[ROW_COST, item]
    return AssetScreeningRecord(
        asset_id=asset_id,
        status=status,
        eligibility_reasons=reasons,
        candidate_type=candidate_type,
        candidate_score=None if excluded or np.isnan(score) else score,
        alpha_score=_score_of(table, ROW_ALPHA, item),
        diversification_score=(
            None if np.isnan(table.diversification[item]) else float(table.diversification[item])
        ),
        marginal_utility=_score_of(table, ROW_UTILITY, item),
        liquidity_score=_score_of(table, ROW_LIQUIDITY, item),
        transaction_cost_estimate=None if np.isnan(cost) else float(abs(cost)),
        missing_signals=table.missing_names(item),
        selected_for_optimization=selected,
        rejection_reason=None
        if selected
        else (REASON_MISSING_SIGNAL if excluded else REASON_NOT_SHORTLISTED),
    )


def build_asset_records(
    screening: ScreeningResult | None,
    eligibility: EligibilityResult,
    asset_ids: tuple[str, ...],
    shortlisted_types: dict[int, CandidateType],
    selected_positions: Collection[int],
) -> tuple[AssetScreeningRecord, ...]:
    """Una fila por activo del modelo de riesgo (orden global) con su screening y su destino.

    ``screening`` es el screening de la composición de referencia (``None`` sin él, p. ej. si no
    hay composición); ``shortlisted_types`` el tipo de los entrantes de la lista corta raíz;
    ``selected_positions`` las posiciones que forman parte de alguna composición devuelta.
    """
    entrant_item: dict[int, int] = {}
    held_item: dict[int, int] = {}
    if screening is not None:
        entrant_item = {int(p): i for i, p in enumerate(screening.entrants.positions.tolist())}
        held_item = {int(p): i for i, p in enumerate(screening.held.positions.tolist())}
    selected = set(selected_positions)
    records: list[AssetScreeningRecord] = []
    for position, asset_id in enumerate(asset_ids):
        status = eligibility.status[position]
        reasons = tuple(reason.value for reason in eligibility.reasons[position])
        chosen = position in selected
        if position in held_item and screening is not None:
            records.append(
                _record_from_table(
                    screening.held,
                    held_item[position],
                    asset_id,
                    status,
                    reasons,
                    CandidateType.CURRENT_HOLDING,
                    chosen,
                )
            )
        elif position in entrant_item and screening is not None:
            records.append(
                _record_from_table(
                    screening.entrants,
                    entrant_item[position],
                    asset_id,
                    status,
                    reasons,
                    shortlisted_types.get(position),
                    chosen,
                )
            )
        else:
            records.append(_unscreened(asset_id, status, reasons, chosen))
    return tuple(records)


def _unscreened(
    asset_id: str, status: EligibilityStatus, reasons: tuple[str, ...], selected: bool
) -> AssetScreeningRecord:
    """Activo que no participó en el screening: excluido, salida obligatoria u otro motivo."""
    if status is EligibilityStatus.MANDATORY_EXIT:
        reason: str | None = REASON_MANDATORY_EXIT
    elif status is EligibilityStatus.EXCLUDED:
        reason = reasons[0] if reasons else EligibilityStatus.EXCLUDED.value
    else:
        reason = None if selected else REASON_NOT_SHORTLISTED
    return AssetScreeningRecord(
        asset_id=asset_id,
        status=status,
        eligibility_reasons=reasons,
        candidate_type=None,
        candidate_score=None,
        alpha_score=None,
        diversification_score=None,
        marginal_utility=None,
        liquidity_score=None,
        transaction_cost_estimate=None,
        missing_signals=(),
        selected_for_optimization=selected,
        rejection_reason=reason,
    )
