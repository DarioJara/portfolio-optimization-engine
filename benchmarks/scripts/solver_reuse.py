"""Benchmark real de reutilización del solver (BEN-003, MASTER_SPEC §47, §71).

Compara ``COLD_SETUP`` (workspace nuevo por punto), ``WORKSPACE_REUSE`` (un workspace, sin warm
start) y ``WARM_START`` sobre fronteras continuas sintéticas de tamaño configurable, y guarda el
resultado **medido** con metadatos de ejecución en ``benchmarks/results/``. No inventa cifras: cada
número del JSON procede de una ejecución de este script.

Uso::

    .venv/Scripts/python benchmarks/scripts/solver_reuse.py --assets 20 --points 20 --seed 7
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

import numpy as np
import osqp
import scipy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.benchmark import SolverReuseReport, solver_reuse_benchmark  # noqa: E402
from portfolio_engine.config import config_hash  # noqa: E402
from portfolio_engine.models.enums import CostTreatment, FrontierMethod  # noqa: E402
from tests.fixtures.problems import base_config, synthetic_problem  # noqa: E402


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


def _report_dict(report: SolverReuseReport) -> dict[str, object]:
    return {
        "treatment": report.treatment.value,
        "method": report.method.value,
        "frontier_points": report.frontier_points,
        "repetitions": report.repetitions,
        "max_weight_difference_vs_cold": report.max_weight_difference,
        "modes": [
            {
                "mode": mode.mode.value,
                "setup_count": mode.setup_count,
                "update_count": mode.update_count,
                "solve_count": mode.solve_count,
                "warm_start_count": mode.warm_start_count,
                "total_solver_iterations": mode.iterations,
                "endpoint_solver_iterations": mode.endpoint_iterations,
                "grid_solver_iterations": mode.grid_iterations,
                "timings_seconds": {
                    stage: {
                        "count": summary.count,
                        "mean": summary.mean,
                        "max": summary.maximum,
                        "percentiles": {str(level): value for level, value in summary.percentiles},
                    }
                    for stage, summary in mode.timings.items()
                },
            }
            for mode in report.modes
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=int, required=True)
    parser.add_argument("--points", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=None)
    args = parser.parse_args()
    config = base_config()
    config = dataclasses.replace(
        config, frontier=dataclasses.replace(config.frontier, frontier_points=args.points)
    )
    if args.repetitions is not None:
        config = dataclasses.replace(
            config, benchmark=dataclasses.replace(config.benchmark, repetitions=args.repetitions)
        )
    problem = synthetic_problem(args.assets, args.seed, config)
    runs = [
        solver_reuse_benchmark(config, problem, treatment, method)
        for treatment in (CostTreatment.GROSS, CostTreatment.NET)
        for method in FrontierMethod
    ]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "metadata": {
            "benchmark": "solver_reuse",
            "requirement": "BEN-003",
            "execution_timestamp_utc": stamp,
            "git_commit": _git_commit(),
            "config_hash": config_hash(config),
            "random_seed": args.seed,
            "n_assets": args.assets,
            "frontier_points": args.points,
            "repetitions": config.benchmark.repetitions,
            "warmup_runs": config.benchmark.warmup_runs,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "osqp": osqp.__version__,
            "note": "Tiempos (s) medidos por este script; un proceso, sin paralelismo.",
        },
        "runs": [_report_dict(run) for run in runs],
    }
    output = ROOT / "benchmarks" / "results" / f"solver_reuse_{args.assets}assets_{stamp}.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Resultados guardados en {output}")
    for run in runs:
        print(f"\n{run.treatment.value} / {run.method.value} ({run.frontier_points} puntos)")
        for mode in run.modes:
            total = mode.timings["frontier_total"]
            print(
                f"  {mode.mode.value:16s} setups={mode.setup_count:3d} iters={mode.iterations:6d} "
                f"frontier_total mean={total.mean * 1e3:8.2f} ms  "
                f"setup={mode.timings['setup'].mean * 1e3:7.2f} ms  "
                f"solve={mode.timings['solve'].mean * 1e3:7.2f} ms"
            )
            print(
                f"  {'':16s} minvar={mode.timings['min_variance'].mean * 1e3:7.2f} ms  "
                f"maxreturn={mode.timings['max_return'].mean * 1e3:7.2f} ms  "
                f"grid={mode.timings['grid'].mean * 1e3:7.2f} ms  "
                f"iters endpoints={mode.endpoint_iterations:6d} grid={mode.grid_iterations:6d}"
            )
        print(f"  max |w_modo - w_cold| = {run.max_weight_difference:.2e}")


if __name__ == "__main__":
    main()
