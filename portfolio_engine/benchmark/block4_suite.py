"""Benchmark descriptivo de las formulaciones del Bloque 4 (MASTER_SPEC §71).

Evidencia de BEN-001 y BEN-002 (no es un requisito propio). Mide sobre ejecuciones reales de
:class:`StrategyOptimizer`, :class:`ScenarioEngine` y :class:`MultiScenarioOptimizer` los
tiempos de:

* ``scenario_build``: construcción de los escenarios (transformación de ``μ``/``Σ``/costes);
* ``prepare``: compilación de restricciones y submatrices de la composición;
* ``solver_setup`` y ``solver_solve``: tiempos que reporta el backend (``SolveResult``);
* ``validation``: validación independiente y métricas recalculadas;
* ``formulation_build``: **residual** ``total − prepare − solver − validation`` (construcción de la
  formulación, factorización PSD y enrutado);
* ``frontier``: frontera continua por escenario (``SCENARIO_INDEPENDENT``);
* ``total``.

Solo son medidas descriptivas de un proceso y una máquina: no se extrapolan a producción (la
paralelización y los umbrales pertenecen al Bloque 5) y no se compara con ningún objetivo.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from portfolio_engine.benchmark.stats import TimingSummary, summarize
from portfolio_engine.benchmark.timers import BenchmarkRecorder
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.scenario_definitions import ScenarioDefinition
from portfolio_engine.constraints.feasibility import FeasibilityReport
from portfolio_engine.frontiers.continuous_frontier import FrontierProblem
from portfolio_engine.frontiers.session import FrontierContext
from portfolio_engine.frontiers.strategy_optimizer import StrategyOptimizer
from portfolio_engine.models.cvar import ReturnScenarioSet
from portfolio_engine.models.enums import CostTreatment, CVaRObjective, FrontierMethod
from portfolio_engine.models.solution import SolveResult, ValidationReport
from portfolio_engine.models.strategy import StrategyResult
from portfolio_engine.optimizers.problem import CanonicalProblem
from portfolio_engine.scenarios.multi_scenario import MultiScenarioOptimizer
from portfolio_engine.scenarios.scenario_engine import ScenarioEngine

BLOCK4_STAGES = (
    "scenario_build",
    "prepare",
    "formulation_build",
    "solver_setup",
    "solver_solve",
    "validation",
    "frontier",
    "total",
)


@dataclass(frozen=True, slots=True)
class FormulationTiming:
    """Tiempos y diagnóstico de una formulación (última repetición para los contadores)."""

    name: str
    timings: dict[str, TimingSummary]
    solver_names: tuple[str, ...]
    status: str
    iterations: int | None
    is_valid: bool | None
    repetitions: int


@dataclass(frozen=True, slots=True)
class Block4Report:
    """Informe descriptivo de todas las formulaciones medidas."""

    formulations: tuple[FormulationTiming, ...]
    n_assets: int
    n_scenarios: int
    treatment: CostTreatment
    repetitions: int


class _TimedOptimizer(StrategyOptimizer):
    """``StrategyOptimizer`` que acumula el tiempo de cada etapa en un recorder."""

    def __init__(self, config: EngineConfig, recorder: BenchmarkRecorder) -> None:
        super().__init__(config)
        self._recorder = recorder
        self._prepare = 0.0
        self._solver = 0.0
        self._validation = 0.0

    def reset(self) -> None:
        """Pone a cero los acumuladores de una repetición."""
        self._prepare = self._solver = self._validation = 0.0

    def prepare(
        self, problem: FrontierProblem, treatment: CostTreatment
    ) -> tuple[FrontierContext | None, FeasibilityReport]:
        """``prepare`` cronometrado."""
        started = time.perf_counter()
        try:
            return super().prepare(problem, treatment)
        finally:
            self._prepare += time.perf_counter() - started

    def solve_problem(self, problem: CanonicalProblem) -> SolveResult:
        """``solve_problem`` cronometrado (setup y solve del backend registrados aparte)."""
        started = time.perf_counter()
        result: SolveResult = super().solve_problem(problem)
        self._solver += time.perf_counter() - started
        self._recorder.record("solver_setup", result.setup_time)
        self._recorder.record("solver_solve", result.solve_time)
        return result

    def assemble(self, **kwargs: Any) -> StrategyResult:
        """``assemble`` (validación independiente y métricas) cronometrado."""
        started = time.perf_counter()
        try:
            return super().assemble(**kwargs)
        finally:
            self._validation += time.perf_counter() - started

    def flush(self, total: float) -> None:
        """Registra las etapas de una repetición (``formulation_build`` es el residual)."""
        self._recorder.record("prepare", self._prepare)
        self._recorder.record("validation", self._validation)
        residual = total - self._prepare - self._solver - self._validation
        self._recorder.record("formulation_build", max(residual, 0.0))
        self._recorder.record("total", total)


def _timing(
    name: str,
    config: EngineConfig,
    runner: Callable[[_TimedOptimizer], StrategyResult],
) -> FormulationTiming:
    recorder = BenchmarkRecorder()
    optimizer = _TimedOptimizer(config, recorder)
    for _ in range(config.benchmark.warmup_runs):
        runner(optimizer)
    recorder = BenchmarkRecorder()
    optimizer = _TimedOptimizer(config, recorder)
    last: StrategyResult | None = None
    for _ in range(config.benchmark.repetitions):
        optimizer.reset()
        started = time.perf_counter()
        last = runner(optimizer)
        optimizer.flush(time.perf_counter() - started)
    if last is None:
        raise ValueError("repetitions debe ser positivo.")
    samples = recorder.samples()
    timings = {
        stage: summarize(samples[stage], config.benchmark)
        for stage in BLOCK4_STAGES
        if stage in samples
    }
    return _describe(name, timings, last, config.benchmark.repetitions)


def _describe(
    name: str, timings: dict[str, TimingSummary], result: StrategyResult, repetitions: int
) -> FormulationTiming:
    report: ValidationReport | None = result.validation
    return FormulationTiming(
        name=name,
        timings=timings,
        solver_names=result.solver_names,
        status=result.status.value,
        iterations=None if result.solve is None else result.solve.iterations,
        is_valid=None if report is None else result.is_valid_solution,
        repetitions=repetitions,
    )


def block4_benchmark(
    config: EngineConfig,
    problem: FrontierProblem,
    treatment: CostTreatment,
    definitions: Sequence[ScenarioDefinition],
    return_scenarios: ReturnScenarioSet | None,
    *,
    risk_aversion: float,
    volatility_limit: float,
) -> Block4Report:
    """Mide las formulaciones del Bloque 4 sobre ``problem`` con las ``definitions`` dadas."""
    formulations = [
        _timing("MAX_SHARPE", config, lambda opt: opt.max_sharpe(problem, treatment)),
        _timing(
            "VOL_TARGET",
            config,
            lambda opt: opt.volatility_target(
                problem, treatment, volatility_limit=volatility_limit
            ),
        ),
    ]
    if return_scenarios is not None:
        formulations.append(
            _timing(
                "MIN_CVAR",
                config,
                lambda opt: opt.cvar(problem, treatment, return_scenarios, CVaRObjective.MIN_CVAR),
            )
        )
    formulations.extend(
        _multi_scenario_timings(config, problem, treatment, definitions, risk_aversion)
    )
    return Block4Report(
        formulations=tuple(formulations),
        n_assets=len(problem.risk_model.asset_ids),
        n_scenarios=len(definitions),
        treatment=treatment,
        repetitions=config.benchmark.repetitions,
    )


def _multi_scenario_timings(
    config: EngineConfig,
    problem: FrontierProblem,
    treatment: CostTreatment,
    definitions: Sequence[ScenarioDefinition],
    risk_aversion: float,
) -> list[FormulationTiming]:
    engine = ScenarioEngine(config)
    optimizer = MultiScenarioOptimizer(config)
    build_recorder = BenchmarkRecorder()
    scenarios = None
    for _ in range(config.benchmark.warmup_runs + config.benchmark.repetitions):
        started = time.perf_counter()
        scenarios = engine.build(
            problem.risk_model,
            problem.universe,
            problem.costs,
            config.constraints,
            problem.spec,
            definitions,
        )
        build_recorder.record("scenario_build", time.perf_counter() - started)
    if scenarios is None:
        raise ValueError("Sin escenarios.")
    build = summarize(build_recorder.samples()["scenario_build"], config.benchmark)
    results: list[FormulationTiming] = [
        FormulationTiming(
            "SCENARIO_BUILD",
            {"scenario_build": build},
            (),
            "OK",
            None,
            None,
            config.benchmark.repetitions,
        )
    ]
    modes: dict[str, Callable[[], StrategyResult | None]] = {
        "EXPECTED_SCENARIO_UTILITY": lambda: (
            optimizer.solve_expected_utility(
                problem, scenarios, treatment, risk_aversion
            ).single_solution
        ),
        "WORST_CASE": lambda: (
            optimizer.solve_worst_case(problem, scenarios, treatment, risk_aversion).single_solution
        ),
        "BASE_WITH_STRESS": lambda: (
            optimizer.solve_base_with_stress(
                problem, scenarios, treatment, risk_aversion
            ).single_solution
        ),
    }
    for name, run in modes.items():
        results.append(_total_only(name, config, run))
    frontier_recorder = BenchmarkRecorder()
    for _ in range(config.benchmark.repetitions):
        started = time.perf_counter()
        optimizer.solve_independent(
            problem, scenarios, treatment, FrontierMethod.RISK_AVERSION_GRID
        )
        frontier_recorder.record("frontier", time.perf_counter() - started)
    results.append(
        FormulationTiming(
            "SCENARIO_INDEPENDENT_FRONTIERS",
            {"frontier": summarize(frontier_recorder.samples()["frontier"], config.benchmark)},
            (),
            "OK",
            None,
            None,
            config.benchmark.repetitions,
        )
    )
    return results


def _total_only(
    name: str, config: EngineConfig, run: Callable[[], StrategyResult | None]
) -> FormulationTiming:
    """Tiempo total de un modo de solución única y contadores del backend (última repetición)."""
    for _ in range(config.benchmark.warmup_runs):
        run()
    recorder = BenchmarkRecorder()
    last: StrategyResult | None = None
    for _ in range(config.benchmark.repetitions):
        started = time.perf_counter()
        last = run()
        recorder.record("total", time.perf_counter() - started)
        if last is not None and last.solve is not None:
            recorder.record("solver_setup", last.solve.setup_time)
            recorder.record("solver_solve", last.solve.solve_time)
    if last is None:
        raise ValueError(f"{name}: sin resultado.")
    samples = recorder.samples()
    timings = {stage: summarize(values, config.benchmark) for stage, values in samples.items()}
    return _describe(name, timings, last, config.benchmark.repetitions)
