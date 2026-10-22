"""Fusión de las búsquedas por tamaño de cartera admisible (restricciones obligatorias).

Con una política de cardinalidad ``INCREASE`` / ``DECREASE`` o un intervalo ``min_size`` /
``max_size`` el ``CandidateEngine`` ejecuta la búsqueda de B3 una vez por tamaño ``k`` admisible
(la cardinalidad se garantiza en la generación discreta, nunca recortando pesos). Esta función
reúne los resultados en un único :class:`CandidateSearchResult`:

* la composición de referencia (la cartera original, si es válida) va primero y una sola vez;
* el cupo ``max_candidates`` se reparte por rango entre los tamaños (el mejor de cada tamaño
  primero), sin duplicados y en orden determinista (tamaños ascendentes);
* los diagnósticos suman contadores y tiempos y conservan todas las etapas, rechazos y notas.

Con un único tamaño (política ``FIXED``) devuelve ese resultado sin transformarlo.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from portfolio_engine.models.composition import (
    CandidateComposition,
    CandidateDiagnostics,
    CandidateSearchResult,
)

NOTE_SIZES_SEARCHED = "CARDINALITY_SIZES_SEARCHED"


def merge_search_results(
    runs: Sequence[CandidateSearchResult], sizes: Sequence[int], max_candidates: int
) -> CandidateSearchResult:
    """Resultado único de las búsquedas ``runs`` (una por tamaño de ``sizes``)."""
    if len(runs) == 1:
        return runs[0]
    reference = next(
        (candidate for run in runs for candidate in run.compositions if candidate.is_reference),
        None,
    )
    chosen: list[CandidateComposition] = [] if reference is None else [reference]
    seen = {candidate.composition_id for candidate in chosen}
    ranked = [[c for c in run.compositions if not c.is_reference] for run in runs]
    depth = max((len(items) for items in ranked), default=0)
    for rank in range(depth):
        for items in ranked:
            if rank < len(items) and len(chosen) < max_candidates:
                candidate = items[rank]
                if candidate.composition_id not in seen:
                    seen.add(candidate.composition_id)
                    chosen.append(candidate)
    return CandidateSearchResult(tuple(chosen), _merge_diagnostics(runs, sizes))


def _merge_diagnostics(
    runs: Sequence[CandidateSearchResult], sizes: Sequence[int]
) -> CandidateDiagnostics:
    base = runs[0].diagnostics
    diagnostics = [run.diagnostics for run in runs]
    reasons: Counter[str] = Counter()
    for item in diagnostics:
        reasons.update(dict(item.rejections_by_reason))
    notes: list[str] = []
    for item in diagnostics:
        notes.extend(note for note in item.notes if note not in notes)
    notes.append(f"{NOTE_SIZES_SEARCHED}: {list(sizes)}")
    return CandidateDiagnostics(
        portfolio_id=base.portfolio_id,
        scenario_id=base.scenario_id,
        cold_start=base.cold_start,
        eligibility_counts=base.eligibility_counts,
        asset_records=base.asset_records,
        stages=tuple(stage for item in diagnostics for stage in item.stages),
        rejected_compositions=tuple(
            record for item in diagnostics for record in item.rejected_compositions
        ),
        rejections_by_reason=tuple(sorted(reasons.items())),
        stop_reasons=tuple(entry for item in diagnostics for entry in item.stop_reasons),
        total_generated=sum(item.total_generated for item in diagnostics),
        total_evaluated=sum(item.total_evaluated for item in diagnostics),
        screening_time=sum(item.screening_time for item in diagnostics),
        search_time=sum(item.search_time for item in diagnostics),
        total_time=sum(item.total_time for item in diagnostics),
        notes=tuple(notes),
        evaluation_cache_hits=sum(item.evaluation_cache_hits for item in diagnostics),
    )
