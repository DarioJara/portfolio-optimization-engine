"""Benchmark de reutilización del solver (MASTER_SPEC §47, §71; BEN-003).

Compara tres modos sobre la misma frontera (mismos datos, misma configuración salvo dos flags de
``SolverConfig``):

* ``COLD_SETUP``: un workspace nuevo por punto (``workspace_reuse = false``).
* ``WORKSPACE_REUSE``: un workspace y actualización de ``q``/``lower``, sin arranque en caliente.
* ``WARM_START``: workspace reutilizado y arranque en caliente desde el punto vecino.

Mide setup, update, solve y frontera total de ejecuciones reales, y desglosa la frontera en
``min_variance`` (extremo de mínima varianza), ``max_return`` (extremo de retorno máximo: LP y
etapa 2) y ``grid`` (malla y refinado): la reutilización del workspace solo afecta a la malla y a
MinVariance, y los extremos pueden dominar el total (AUDIT_BLOCK_2, M-2). Nunca inventa cifras. La
comprobación de que los tres modos producen los mismos puntos es responsabilidad del llamador
(``max_weight_difference`` la reporta).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from portfolio_engine.benchmark.stats import TimingSummary, summarize
from portfolio_engine.benchmark.timers import BenchmarkRecorder
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.frontiers.continuous_frontier import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.models.frontier import CompositionFrontierResult

STAGES = (
    "setup",
    "update",
    "solve",
    "frontier_total",
    "min_variance",
    "max_return",
    "grid",
)


class ReuseMode(StrEnum):
    """Modo de reutilización del solver."""

    COLD_SETUP = "COLD_SETUP"
    WORKSPACE_REUSE = "WORKSPACE_REUSE"
    WARM_START = "WARM_START"


@dataclass(frozen=True, slots=True)
class ModeReport:
    """Resultado de un modo: estadísticos de tiempos y contadores de la última repetición."""

    mode: ReuseMode
    timings: dict[str, TimingSummary]
    setup_count: int
    update_count: int
    solve_count: int
    warm_start_count: int
    iterations: int
    endpoint_iterations: int

    @property
    def grid_iterations(self) -> int:
        """Iteraciones de la malla (y refinado): total menos las de los extremos."""
        return self.iterations - self.endpoint_iterations


@dataclass(frozen=True, slots=True)
class SolverReuseReport:
    """Comparación de los tres modos y desviación de sus soluciones respecto a ``COLD_SETUP``."""

    modes: tuple[ModeReport, ...]
    max_weight_difference: float
    frontier_points: int
    treatment: CostTreatment
    method: FrontierMethod
    repetitions: int


def _mode_config(config: EngineConfig, mode: ReuseMode) -> EngineConfig:
    solver = dataclasses.replace(
        config.solver,
        workspace_reuse=mode is not ReuseMode.COLD_SETUP,
        warm_start=mode is ReuseMode.WARM_START,
    )
    return dataclasses.replace(config, solver=solver)


def _run_mode(
    config: EngineConfig,
    mode: ReuseMode,
    problem: FrontierProblem,
    treatment: CostTreatment,
    method: FrontierMethod,
) -> tuple[ModeReport, CompositionFrontierResult]:
    engine = ContinuousFrontierEngine(_mode_config(config, mode))
    for _ in range(config.benchmark.warmup_runs):
        engine.solve(problem, treatment, method)
    recorder = BenchmarkRecorder()
    results = [
        engine.solve(problem, treatment, method) for _ in range(config.benchmark.repetitions)
    ]
    for result in results:
        recorder.record("setup", result.diagnostics.setup_time)
        recorder.record("update", result.diagnostics.update_time)
        recorder.record("solve", result.diagnostics.solve_time)
        recorder.record("frontier_total", result.diagnostics.frontier_time)
        recorder.record("min_variance", result.diagnostics.min_variance_time)
        recorder.record("max_return", result.diagnostics.max_return_time)
        recorder.record("grid", result.diagnostics.grid_time)
    last = results[-1]
    report = ModeReport(
        mode=mode,
        timings={stage: summarize(recorder.samples()[stage], config.benchmark) for stage in STAGES},
        setup_count=last.diagnostics.setup_count,
        update_count=last.diagnostics.update_count,
        solve_count=last.diagnostics.solve_count,
        warm_start_count=last.diagnostics.warm_start_count,
        iterations=last.diagnostics.total_iterations,
        endpoint_iterations=last.diagnostics.endpoint_iterations,
    )
    return report, last


def _max_weight_difference(
    first: CompositionFrontierResult, second: CompositionFrontierResult
) -> float:
    pairs = zip(first.points, second.points, strict=True)
    return max(
        (
            float(np.max(np.abs(a.weights - b.weights)))
            for a, b in pairs
            if a.weights is not None and b.weights is not None
        ),
        default=0.0,
    )


def solver_reuse_benchmark(
    config: EngineConfig,
    problem: FrontierProblem,
    treatment: CostTreatment,
    method: FrontierMethod,
) -> SolverReuseReport:
    """Ejecuta el benchmark de reutilización con ``config.benchmark`` repeticiones por modo."""
    outcomes = {mode: _run_mode(config, mode, problem, treatment, method) for mode in ReuseMode}
    reference = outcomes[ReuseMode.COLD_SETUP][1]
    difference = max(
        _max_weight_difference(reference, result)
        for mode, (_, result) in outcomes.items()
        if mode is not ReuseMode.COLD_SETUP
    )
    return SolverReuseReport(
        modes=tuple(report for report, _ in outcomes.values()),
        max_weight_difference=difference,
        frontier_points=len(reference.points),
        treatment=treatment,
        method=method,
        repetitions=config.benchmark.repetitions,
    )
