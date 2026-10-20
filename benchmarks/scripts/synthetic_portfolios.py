"""Generador determinista de carteras sintéticas para los benchmarks de escala (B5.5).

Todo es función de ``(ScalingBenchmarkConfig, mezcla, nº de carteras, semilla)``: mismas entradas,
mismas carteras, byte a byte. Ningún parámetro del generador está en el código: universo,
posiciones, fracción de carteras degeneradas, periodos de retorno y mezclas salen de
``config/default_benchmark.toml``.

* Reparto de clases: método del mayor resto sobre las fracciones de la mezcla (los recuentos suman
  exactamente ``N``) y posición de cada clase barajada con ``derive_seed(semilla, "mix")``.
* Diversidad: cada cartera tiene activos y pesos distintos (``requests_for`` con semilla derivada) y
  un nº de posiciones dentro de ``[holdings_min, holdings_max]``.
* Degeneradas (``degenerate_fraction``), para ejercitar rutas de error sin romper el lote:
  ``VOL-TARGET`` con una volatilidad objetivo inferior a σ_min (termina ``COMPLETED`` con estado de
  solver ``INFEASIBLE``) y una composición no ordenada (termina ``FAILED_INPUT_VALIDATION``).

Los datos de mercado son sintéticos (modelo factorial de ``tests/fixtures``): sin datos reales.
"""

from __future__ import annotations

import dataclasses
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.config import EngineConfig  # noqa: E402
from portfolio_engine.config.scaling_config import (  # noqa: E402
    ScalingBenchmarkConfig,
    WorkloadMix,
)
from portfolio_engine.models.enums import CostTreatment  # noqa: E402
from portfolio_engine.parallel.determinism import derive_seed  # noqa: E402
from portfolio_engine.parallel.task import MarketSnapshot, PortfolioRequest  # noqa: E402
from portfolio_engine.parallel.workload import (  # noqa: E402
    OperationKind,
    OperationSpec,
    WorkloadSpec,
)
from tests.fixtures.candidates import random_problem  # noqa: E402
from tests.fixtures.parallel import class_workloads, requests_for, snapshot_of  # noqa: E402
from tests.fixtures.problems import base_config  # noqa: E402

#: Volatilidad objetivo (anualizada) muy inferior a σ_min de cualquier universo sintético.
DEGENERATE_VOLATILITY_LIMIT = 1e-4
SNAPSHOT_SEED = 11


@dataclass(frozen=True, slots=True)
class SyntheticBatch:
    """Lote sintético reproducible.

    Attributes:
        config: configuración del motor usada para generarlo.
        snapshot: datos de mercado (universo, riesgo, escenarios y retornos).
        requests: solicitudes en orden de generación (``PortfolioID`` únicos).
        labels: clase de coste de cada solicitud (mismo orden).
        counts: carteras por clase.
    """

    config: EngineConfig
    snapshot: MarketSnapshot
    requests: tuple[PortfolioRequest, ...]
    labels: tuple[str, ...]
    counts: dict[str, int]


def allocate_counts(mix: WorkloadMix, portfolios: int) -> dict[str, int]:
    """Recuentos por clase por el método del mayor resto (suman exactamente ``portfolios``)."""
    if portfolios < 1:
        raise ValueError("portfolios debe ser >= 1.")
    exact = {share.label: share.fraction * portfolios for share in mix.shares}
    counts = {label: math.floor(value) for label, value in exact.items()}
    remaining = portfolios - sum(counts.values())
    by_remainder = sorted(exact, key=lambda label: (-(exact[label] - counts[label]), label))
    for label in by_remainder[:remaining]:
        counts[label] += 1
    return counts


def _degenerate_workload(kind_index: int, base: WorkloadSpec) -> tuple[WorkloadSpec, bool]:
    """Workload degenerado ``kind_index``-ésimo y si lleva composición no ordenada."""
    if kind_index % 2 == 0:
        vol = OperationSpec(
            OperationKind.STRATEGY_VOL_TARGET,
            CostTreatment.GROSS,
            volatility_limit=DEGENERATE_VOLATILITY_LIMIT,
        )
        return WorkloadSpec((vol,)), False
    return base, True


def generate(
    scaling: ScalingBenchmarkConfig,
    mix: WorkloadMix,
    portfolios: int,
    seed: int,
    *,
    engine_config: EngineConfig | None = None,
) -> SyntheticBatch:
    """Genera ``portfolios`` carteras de la mezcla ``mix`` (determinista por ``seed``)."""
    config = engine_config if engine_config is not None else base_config()
    held_pool = list(range(scaling.holdings_max))
    problem = random_problem(scaling.universe_assets, held_pool, SNAPSHOT_SEED, config)
    snapshot = snapshot_of(
        problem,
        with_scenarios=True,
        return_periods=scaling.return_periods,
        seed=SNAPSHOT_SEED,
    )
    workloads = {label: workload for label, (_, workload) in class_workloads().items()}
    counts = allocate_counts(mix, portfolios)
    unknown = sorted(set(counts) - set(workloads))
    if unknown:
        raise ValueError(f"La mezcla {mix.name!r} usa clases desconocidas: {unknown}.")

    order = [label for label, count in counts.items() for _ in range(count)]
    rng = np.random.default_rng(derive_seed(seed, "mix", mix.name))
    order = [order[i] for i in rng.permutation(len(order))]
    degenerate_total = round(scaling.degenerate_fraction * portfolios)
    degenerate_positions = set(
        rng.choice(portfolios, size=degenerate_total, replace=False).tolist()
        if degenerate_total
        else ()
    )

    requests: list[PortfolioRequest] = []
    labels: list[str] = []
    degenerate_seen = 0
    for position, label in enumerate(order):
        holdings = int(
            np.random.default_rng(derive_seed(seed, "holdings", str(position))).integers(
                scaling.holdings_min, scaling.holdings_max + 1
            )
        )
        workload = workloads[label]
        unsorted_composition = False
        if position in degenerate_positions:
            workload, unsorted_composition = _degenerate_workload(degenerate_seen, workload)
            degenerate_seen += 1
        request = requests_for(
            problem,
            workload,
            1,
            holdings=holdings,
            seed=derive_seed(seed, "portfolio", str(position)),
            prefix=f"{label}-{position:06d}-",
        )[0]
        if unsorted_composition:
            held = tuple(reversed(request.state.asset_ids))
            request = dataclasses.replace(request, composition_asset_ids=held)
        requests.append(request)
        labels.append(label)
    return SyntheticBatch(config, snapshot, tuple(requests), tuple(labels), counts)
