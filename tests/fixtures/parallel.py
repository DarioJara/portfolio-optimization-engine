"""Constructores sintéticos deterministas para las pruebas del ejecutor paralelo (Bloque 5.2).

Todos los datos proceden de semillas explícitas. Los comparadores de equivalencia T1 recorren los
resultados de forma genérica (dataclasses, arrays, enums) para que **ningún campo** quede sin
comparar; solo se excluyen los campos de tiempo, que dependen del reloj y no del cálculo.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from enum import Enum
from typing import Any

import numpy as np

from portfolio_engine.config import EngineConfig
from portfolio_engine.config.parallel_config import ParallelConfig, load_parallel_config
from portfolio_engine.frontiers import FrontierProblem
from portfolio_engine.models.cvar import build_return_scenario_set
from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    CVaRSource,
    FrontierMethod,
    FrontierScope,
    MultiScenarioMode,
    ScenarioWeighting,
)
from portfolio_engine.models.portfolio import CurrentPortfolioState
from portfolio_engine.models.universe_index import AssetIndex
from portfolio_engine.parallel.task import MarketSnapshot, PortfolioRequest
from portfolio_engine.parallel.workload import OperationKind, OperationSpec, WorkloadSpec
from tests.conftest import DEFAULT_PARALLEL_CONFIG_PATH
from tests.fixtures.block4 import four_asset_problem, scenario_definitions
from tests.fixtures.candidates import random_problem
from tests.fixtures.problems import spec_with

#: Cota absoluta T1 (D-07): la de la regresión dorada (``tests/numerical_regression``), que su
#: autor justifica como «cambios de plataforma/BLAS mueven los resultados ~1e-12; 1e-6 detecta
#: cualquier cambio de modelo o de tolerancias del solver». No se introduce ninguna nueva.
T1_ABS_TOLERANCE = 1e-6

#: Campos que miden tiempo de pared (no son resultado del cálculo). Se listan por nombre exacto o
#: sufijo y el test de comparación comprueba cuáles se han excluido realmente.
TIMING_SUFFIXES = ("_time", "_seconds")
TIMING_NAMES = frozenset({"elapsed", "started_at", "finished_at"})
#: Campos de diagnóstico del proceso que ejecutó la tarea (no del cálculo).
PROCESS_NAMES = frozenset({"worker_pid", "traceback"})


def parallel_config(**changes: Any) -> ParallelConfig:
    """``ParallelConfig`` de ejemplo con cambios (se validan de nuevo)."""
    config = load_parallel_config(DEFAULT_PARALLEL_CONFIG_PATH)
    return dataclasses.replace(config, **changes) if changes else config


def snapshot_of(
    problem: FrontierProblem,
    *,
    with_scenarios: bool = False,
    return_periods: int | None = None,
    seed: int = 0,
    tolerance: float = 1e-9,
) -> MarketSnapshot:
    """``MarketSnapshot`` con los datos de ``problem`` (escenarios y retornos opcionales)."""
    returns = None
    if return_periods is not None:
        rng = np.random.default_rng(seed)
        mu = np.asarray(problem.risk_model.mu, dtype=np.float64)
        sigma = np.asarray(problem.risk_model.sigma, dtype=np.float64)
        draws = rng.multivariate_normal(mu / 252, sigma / 252, size=return_periods)
        returns = build_return_scenario_set(
            problem.risk_model.asset_ids,
            draws,
            CVaRSource.HISTORICAL,
            ScenarioWeighting.EQUAL,
            None,
            tolerance,
        )
    return MarketSnapshot(
        risk_model=problem.risk_model,
        universe=problem.universe,
        costs=problem.costs,
        return_scenarios=returns,
        scenario_definitions=scenario_definitions() if with_scenarios else (),
        base_scenario_id=problem.scenario_id,
    )


def requests_for(
    problem: FrontierProblem,
    workload: WorkloadSpec,
    count: int,
    *,
    holdings: int = 3,
    seed: int = 0,
    with_spec: bool = False,
    prefix: str = "PF",
) -> list[PortfolioRequest]:
    """``count`` carteras distintas (activos y pesos actuales deterministas) con un workload."""
    rng = np.random.default_rng(seed)
    index = AssetIndex.from_universe(problem.universe)
    ids = problem.universe.asset_ids
    requests: list[PortfolioRequest] = []
    for position in range(count):
        portfolio_id = f"{prefix}{position:04d}"
        chosen = sorted(rng.choice(len(ids), size=holdings, replace=False).tolist())
        raw = rng.uniform(0.5, 1.5, size=holdings)
        shares = (raw / raw.sum()).tolist()
        weights = {ids[i]: float(share) for i, share in zip(chosen, shares, strict=True)}
        state = CurrentPortfolioState.from_weights(portfolio_id, weights, index, None)
        spec = spec_with(portfolio_id=portfolio_id) if with_spec else None
        requests.append(
            PortfolioRequest(
                portfolio_id=portfolio_id,
                state=state,
                spec=spec,
                workload=workload,
                composition_asset_ids=None,
            )
        )
    return requests


# ----------------------------------------------------------------------- comparación T1 genérica


def _is_timing(name: str) -> bool:
    return name in TIMING_NAMES or name.endswith(TIMING_SUFFIXES)


class Comparison:
    """Acumula diferencias entre dos resultados (T1) y el máximo desvío numérico (T0)."""

    def __init__(self, tolerance: float = T1_ABS_TOLERANCE) -> None:
        self.tolerance = tolerance
        self.differences: list[str] = []
        self.excluded: set[str] = set()
        self.max_abs_difference = 0.0
        self.float_comparisons = 0
        self.inexact_floats = 0

    def compare(self, left: object, right: object, path: str = "result") -> None:
        if dataclasses.is_dataclass(left) and not isinstance(left, type):
            self._dataclass(left, right, path)
        elif isinstance(left, np.ndarray):
            self._array(left, right, path)
        elif isinstance(left, float):
            self._float(left, right, path)
        elif isinstance(left, (tuple, list)):
            self._sequence(left, right, path)
        elif isinstance(left, dict):
            self._mapping(left, right, path)
        elif isinstance(left, (frozenset, set)):
            if left != right:
                self.differences.append(f"{path}: {left!r} != {right!r}")
        elif isinstance(left, Enum) or left is None or isinstance(left, (bool, int, str, bytes)):
            if left != right or type(left) is not type(right):
                self.differences.append(f"{path}: {left!r} != {right!r}")
        else:
            self.differences.append(f"{path}: tipo no comparable {type(left).__name__}")

    def _dataclass(self, left: Any, right: Any, path: str) -> None:
        if type(left) is not type(right):
            self.differences.append(f"{path}: {type(left).__name__} != {type(right).__name__}")
            return
        for field in dataclasses.fields(left):
            if _is_timing(field.name) or field.name in PROCESS_NAMES:
                self.excluded.add(f"{type(left).__name__}.{field.name}")
                continue
            self.compare(
                getattr(left, field.name), getattr(right, field.name), f"{path}.{field.name}"
            )

    def _sequence(self, left: Sequence[Any], right: object, path: str) -> None:
        if not isinstance(right, (tuple, list)) or len(left) != len(right):
            self.differences.append(f"{path}: longitudes distintas")
            return
        for position, (a, b) in enumerate(zip(left, right, strict=True)):
            self.compare(a, b, f"{path}[{position}]")

    def _mapping(self, left: dict[Any, Any], right: object, path: str) -> None:
        if not isinstance(right, dict) or set(left) != set(right):
            self.differences.append(f"{path}: claves distintas")
            return
        for key in sorted(left, key=repr):
            self.compare(left[key], right[key], f"{path}[{key!r}]")

    def _float(self, left: float, right: object, path: str) -> None:
        if not isinstance(right, float):
            self.differences.append(f"{path}: {left!r} != {right!r}")
            return
        self.float_comparisons += 1
        if math.isnan(left) and math.isnan(right):
            return
        if left == right:
            return
        self.inexact_floats += 1
        delta = abs(left - right)
        if math.isfinite(delta):
            self.max_abs_difference = max(self.max_abs_difference, delta)
        if not (delta <= self.tolerance):
            self.differences.append(f"{path}: {left!r} != {right!r} (|Δ|={delta:.3e})")

    def _array(self, left: np.ndarray, right: object, path: str) -> None:  # type: ignore[type-arg]
        if not isinstance(right, np.ndarray) or left.shape != right.shape:
            self.differences.append(f"{path}: formas distintas")
            return
        if left.dtype.kind != "f":
            if not np.array_equal(left, right):
                self.differences.append(f"{path}: arrays distintos")
            return
        both_nan = np.isnan(left) & np.isnan(right)
        delta = np.where(both_nan, 0.0, np.abs(left - right))
        self.float_comparisons += int(left.size)
        self.inexact_floats += int(np.count_nonzero(delta))
        if delta.size:
            peak = float(np.nanmax(delta))
            if math.isfinite(peak):
                self.max_abs_difference = max(self.max_abs_difference, peak)
            if not bool(np.all(delta <= self.tolerance)):
                self.differences.append(f"{path}: |Δ| máx = {peak:.3e} > {self.tolerance}")


def compare_results(left: object, right: object, tolerance: float = T1_ABS_TOLERANCE) -> Comparison:
    """Compara dos ``TaskResult`` (o cualquier resultado) campo a campo bajo T1."""
    comparison = Comparison(tolerance)
    comparison.compare(left, right)
    return comparison


# ------------------------------------------------------------------------ workloads de referencia


def _op(kind: OperationKind, treatment: CostTreatment, **parameters: Any) -> OperationSpec:
    return OperationSpec(kind, treatment, **parameters)


_GROSS, _NET = CostTreatment.GROSS, CostTreatment.NET
_RISK_AVERSION_GRID, _TARGET_RETURN_GRID = (
    FrontierMethod.RISK_AVERSION_GRID,
    FrontierMethod.TARGET_RETURN_GRID,
)
_LAMBDA = 3.0
_MIP_LAMBDA = 4.0
_VOLATILITY_LIMIT = 0.2
_SCALE_MAX = 1.2


def class_workloads() -> dict[str, tuple[str, WorkloadSpec]]:
    """Un workload por subclase W0-W5: ``{etiqueta: (universo, WorkloadSpec)}``.

    ``universo`` es ``"p8"`` (8 activos aleatorios, 3 posiciones) o ``"p4"`` (4 activos del
    Bloque 4, 2 posiciones; el que usan los tests existentes de escenarios). Todos los valores son
    datos de prueba, no parámetros del motor.
    """
    k = OperationKind
    m = MultiScenarioMode
    return {
        "W0-GROSS-RISK": (
            "p8",
            WorkloadSpec((_op(k.FRONTIER_FIXED_COMPOSITION, _GROSS, method=_RISK_AVERSION_GRID),)),
        ),
        "W0-NET-TARGET": (
            "p8",
            WorkloadSpec((_op(k.FRONTIER_FIXED_COMPOSITION, _NET, method=_TARGET_RETURN_GRID),)),
        ),
        "W1-GLOBAL-NET": (
            "p8",
            WorkloadSpec((_op(k.GLOBAL_FRONTIER, _NET, method=_RISK_AVERSION_GRID),)),
        ),
        "W2-INDEPENDENT": (
            "p4",
            WorkloadSpec(
                (
                    _op(
                        k.MULTI_SCENARIO,
                        _GROSS,
                        mode=m.SCENARIO_INDEPENDENT,
                        method=_RISK_AVERSION_GRID,
                        scope=FrontierScope.CONTINUOUS_FRONTIER,
                        include_max_sharpe=True,
                    ),
                )
            ),
        ),
        "W2-EXPECTED": (
            "p4",
            WorkloadSpec(
                (
                    _op(
                        k.MULTI_SCENARIO,
                        _GROSS,
                        mode=m.EXPECTED_SCENARIO_UTILITY,
                        risk_aversion=_LAMBDA,
                    ),
                )
            ),
        ),
        "W2-WORST-CASE": (
            "p4",
            WorkloadSpec(
                (_op(k.MULTI_SCENARIO, _GROSS, mode=m.WORST_CASE, risk_aversion=_LAMBDA),)
            ),
        ),
        "W2-STRESS": (
            "p4",
            WorkloadSpec(
                (
                    _op(
                        k.MULTI_SCENARIO,
                        _GROSS,
                        mode=m.BASE_WITH_STRESS_CONSTRAINTS,
                        risk_aversion=_LAMBDA,
                    ),
                )
            ),
        ),
        "W3-MIN-CVAR": (
            "p8",
            WorkloadSpec((_op(k.STRATEGY_CVAR, _GROSS, cvar_objective=CVaRObjective.MIN_CVAR),)),
        ),
        "W4-ROBUST": (
            "p8",
            WorkloadSpec(
                (
                    _op(
                        k.STRATEGY_ROBUST,
                        _GROSS,
                        risk_aversion=_LAMBDA,
                        covariance_scale_max=_SCALE_MAX,
                    ),
                )
            ),
        ),
        "W4-MAX-SHARPE": ("p8", WorkloadSpec((_op(k.STRATEGY_MAX_SHARPE, _NET),))),
        "W4-VOL-TARGET": (
            "p8",
            WorkloadSpec((_op(k.STRATEGY_VOL_TARGET, _GROSS, volatility_limit=_VOLATILITY_LIMIT),)),
        ),
        "W5-EXACT-MIP": (
            "p8",
            WorkloadSpec(
                (
                    _op(k.GLOBAL_FRONTIER, _GROSS, method=_RISK_AVERSION_GRID),
                    _op(k.EXACT_MIP_VALIDATION, _GROSS, risk_aversion=_MIP_LAMBDA),
                )
            ),
        ),
        "PIPELINE": (
            "p8",
            WorkloadSpec(
                (
                    _op(k.GLOBAL_FRONTIER, _GROSS, method=_RISK_AVERSION_GRID),
                    _op(k.STRATEGY_CVAR, _GROSS, cvar_objective=CVaRObjective.MIN_CVAR),
                    _op(k.STRATEGY_MAX_SHARPE, _GROSS),
                )
            ),
        ),
    }


# ------------------------------------------------------------------------- carteras de referencia

#: Posiciones por cartera en cada universo de referencia.
UNIVERSE_HOLDINGS = {"p8": 3, "p4": 2}
#: Periodos de los escenarios de retorno sintéticos (CVaR).
RETURN_PERIODS = 300


def reference_universes(
    config: EngineConfig,
) -> dict[str, tuple[FrontierProblem, MarketSnapshot]]:
    """Universos de referencia: ``p8`` (8 activos aleatorios) y ``p4`` (4 activos del Bloque 4)."""
    p8 = random_problem(8, [0, 1, 2], 3, config)
    p4 = four_asset_problem(config)
    return {
        "p8": (p8, snapshot_of(p8, return_periods=RETURN_PERIODS, seed=11)),
        "p4": (p4, snapshot_of(p4, with_scenarios=True)),
    }


def reference_requests(
    config: EngineConfig, per_class: int, *, seed: int = 0
) -> tuple[dict[str, MarketSnapshot], dict[str, list[PortfolioRequest]]]:
    """Snapshots por universo y solicitudes por universo (``per_class`` carteras por workload).

    Los ``PortfolioID`` llevan la etiqueta del workload (``<etiqueta>-<nnn>``); son únicos en todo
    el conjunto.
    """
    universes = reference_universes(config)
    snapshots = {key: snapshot for key, (_, snapshot) in universes.items()}
    by_universe: dict[str, list[PortfolioRequest]] = {key: [] for key in universes}
    for label, (key, workload) in class_workloads().items():
        problem, _ = universes[key]
        by_universe[key].extend(
            requests_for(
                problem,
                workload,
                per_class,
                holdings=UNIVERSE_HOLDINGS[key],
                seed=seed + len(label),
                prefix=f"{label}-",
            )
        )
    return snapshots, by_universe
