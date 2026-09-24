"""Benchmark descriptivo del pipeline de candidatos (MASTER_SPEC §71).

Evidencia de BEN-001, BEN-002 y BEN-006 (no es un requisito propio).

Mide, sobre ejecuciones reales de :class:`GlobalCandidateFrontierEngine`, el tiempo de:

* ``screening``: puntuación multiseñal de entrantes y salientes (suma de todos los nodos);
* ``candidate_generation``: generación completa de composiciones (screening, sustituciones,
  evaluación, haz y búsqueda local);
* ``frontier_evaluation``: frontera continua de todas las composiciones finalistas;
* ``pareto``: unión de puntos, deduplicación y envolvente global;
* ``total``: pipeline completo,

y reporta el número de composiciones generadas, evaluadas y rechazadas de la última repetición.
Nunca inventa cifras: una medición de un proceso y una máquina no es rendimiento de producción (la
paralelización y los umbrales pertenecen al Bloque 5).
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.benchmark.stats import TimingSummary, summarize
from portfolio_engine.benchmark.timers import BenchmarkRecorder
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.frontiers.continuous_frontier import FrontierProblem
from portfolio_engine.frontiers.global_frontier import GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod

CANDIDATE_STAGES = (
    "screening",
    "candidate_generation",
    "frontier_evaluation",
    "pareto",
    "total",
)


@dataclass(frozen=True, slots=True)
class CandidatePipelineReport:
    """Tiempos y contadores de una medición del pipeline de candidatos."""

    timings: dict[str, TimingSummary]
    n_universe_assets: int
    n_compositions: int
    n_evaluated: int
    n_generated: int
    n_rejected: int
    n_frontier_points: int
    n_envelope_points: int
    n_envelope_compositions: int
    repetitions: int
    treatment: CostTreatment
    method: FrontierMethod


def candidate_pipeline_benchmark(
    config: EngineConfig,
    problem: FrontierProblem,
    treatment: CostTreatment,
    method: FrontierMethod,
) -> CandidatePipelineReport:
    """Mide ``config.benchmark.repetitions`` ejecuciones del pipeline tras el calentamiento."""
    engine = GlobalCandidateFrontierEngine(config)
    for _ in range(config.benchmark.warmup_runs):
        engine.solve(problem, treatment, method)
    recorder = BenchmarkRecorder()
    results = [
        engine.solve(problem, treatment, method) for _ in range(config.benchmark.repetitions)
    ]
    for result in results:
        recorder.record("screening", result.candidate_diagnostics.screening_time)
        recorder.record("candidate_generation", result.diagnostics.candidate_time)
        recorder.record("frontier_evaluation", result.diagnostics.frontier_time)
        recorder.record("pareto", result.diagnostics.pareto_time)
        recorder.record("total", result.diagnostics.total_time)
    last = results[-1]
    diagnostics = last.candidate_diagnostics
    return CandidatePipelineReport(
        timings={
            stage: summarize(recorder.samples()[stage], config.benchmark)
            for stage in CANDIDATE_STAGES
        },
        n_universe_assets=len(diagnostics.asset_records),
        n_compositions=len(last.candidates),
        n_evaluated=diagnostics.total_evaluated,
        n_generated=diagnostics.total_generated,
        n_rejected=sum(count for _, count in diagnostics.rejections_by_reason),
        n_frontier_points=len(last.points),
        n_envelope_points=len(last.envelope),
        n_envelope_compositions=len(last.envelope_composition_ids),
        repetitions=config.benchmark.repetitions,
        treatment=treatment,
        method=method,
    )
