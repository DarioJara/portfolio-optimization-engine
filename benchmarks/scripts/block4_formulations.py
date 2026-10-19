"""Benchmark descriptivo de las formulaciones del Bloque 4 (MASTER_SPEC §71).

Evidencia de BEN-001 y BEN-002 (no es un requisito propio).

Mide, sobre ejecuciones reales y para universos de tamaño configurable (cartera actual de ``--held``
activos), los tiempos de construcción de escenarios, compilación de restricciones, formulación
(residual), solver, validación independiente y frontera por escenario de Max Sharpe, control de
volatilidad, CVaR mínimo y los tres modos multiescenario de solución única, y guarda el resultado
**medido** con metadatos en ``benchmarks/results/``. Un proceso, sin paralelismo (Bloque 5): una
medición local no es rendimiento de producción y no se extrapola.

Uso::

    .venv/Scripts/python benchmarks/scripts/block4_formulations.py --universe 10 20 40 --held 8
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import clarabel
import numpy as np
import osqp
import scipy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.benchmark.block4_suite import Block4Report, block4_benchmark  # noqa: E402
from portfolio_engine.config import config_hash  # noqa: E402
from portfolio_engine.models.cvar import build_return_scenario_set  # noqa: E402
from portfolio_engine.models.enums import CostTreatment, CVaRSource, ScenarioWeighting  # noqa: E402
from tests.fixtures.block4 import scenario_definitions  # noqa: E402
from tests.fixtures.candidates import random_problem  # noqa: E402
from tests.fixtures.problems import base_config  # noqa: E402


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        return completed.stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _as_dict(report: Block4Report, universe: int) -> dict[str, object]:
    return {
        "universe_assets": universe,
        "n_scenarios": report.n_scenarios,
        "treatment": report.treatment.value,
        "repetitions": report.repetitions,
        "formulations": [
            {
                "name": item.name,
                "status": item.status,
                "solver_names": list(item.solver_names),
                "iterations": item.iterations,
                "is_valid": item.is_valid,
                "timings_seconds": {
                    stage: {
                        "mean": summary.mean,
                        "max": summary.maximum,
                        "percentiles": {str(level): value for level, value in summary.percentiles},
                        "samples": summary.count,
                    }
                    for stage, summary in item.timings.items()
                },
            }
            for item in report.formulations
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=int, nargs="+", default=[10, 20])
    parser.add_argument("--held", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--periods", type=int, default=500)
    parser.add_argument("--risk-aversion", type=float, default=4.0)
    args = parser.parse_args()

    config = base_config()
    results = []
    for size in args.universe:
        held = list(range(min(args.held, size)))
        problem = random_problem(size, held, args.seed, config, max_weight=0.6)
        model = problem.risk_model
        returns = np.random.default_rng(args.seed).multivariate_normal(
            model.mu / 252, model.sigma / 252, size=args.periods
        )
        cvar_scenarios = build_return_scenario_set(
            model.asset_ids,
            returns,
            CVaRSource.SIMULATED,
            ScenarioWeighting.EQUAL,
            None,
            config.scenarios.probability_sum_tolerance,
        )
        reference = np.full(len(held), 1.0 / len(held))
        volatility_limit = float(np.sqrt(reference @ model.sigma[np.ix_(held, held)] @ reference))
        report = block4_benchmark(
            config,
            problem,
            CostTreatment.NET,
            scenario_definitions(),
            cvar_scenarios,
            risk_aversion=args.risk_aversion,
            volatility_limit=volatility_limit,
        )
        results.append(_as_dict(report, size))
        for item in report.formulations:
            total = item.timings.get("total") or next(iter(item.timings.values()))
            print(
                f"universo={size:4d} {item.name:32s} "
                f"media={total.mean * 1000:9.2f} ms  ({item.status})"
            )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = {
        "benchmark": "block4_formulations",
        "timestamp_utc": stamp,
        "note": "Mediciones descriptivas de un proceso local; no son rendimiento de producción.",
        "git_commit": _git_commit(),
        "config_hash": config_hash(config),
        "seed": args.seed,
        "python": sys.version,
        "platform": platform.platform(),
        "versions": {
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "osqp": osqp.__version__,
            "clarabel": clarabel.__version__,
        },
        "parameters": dataclasses.asdict(config.benchmark),
        "results": results,
    }
    target = ROOT / "benchmarks" / "results" / f"block4_formulations_{stamp}.json"
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"guardado: {target}")


if __name__ == "__main__":
    main()
