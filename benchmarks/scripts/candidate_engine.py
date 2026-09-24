"""Benchmark descriptivo del pipeline de candidatos (MASTER_SPEC §71).

Evidencia de BEN-001, BEN-002 y BEN-006 (no es un requisito propio).

Mide sobre ejecuciones reales, para universos de tamaño configurable con una cartera de 20 activos,
los tiempos de screening, generación de candidatos, evaluación de las fronteras finalistas y
construcción del Pareto global (``GlobalCandidateFrontierEngine``), y guarda el resultado
**medido** con metadatos en ``benchmarks/results/``. Un proceso, sin paralelismo (Bloque 5): una
medición local no es rendimiento de producción y no se extrapola.

Uso::

    .venv/Scripts/python benchmarks/scripts/candidate_engine.py --universe 50 200 700 \
        --held 20 --seed 7
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

from portfolio_engine.benchmark import (  # noqa: E402
    CandidatePipelineReport,
    candidate_pipeline_benchmark,
)
from portfolio_engine.config import config_hash  # noqa: E402
from portfolio_engine.models.enums import CostTreatment, FrontierMethod  # noqa: E402
from tests.fixtures.candidates import universe_problem  # noqa: E402
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


def _report_dict(report: CandidatePipelineReport, universe: int) -> dict[str, object]:
    return {
        "universe_assets": universe,
        "treatment": report.treatment.value,
        "method": report.method.value,
        "repetitions": report.repetitions,
        "compositions": report.n_compositions,
        "compositions_evaluated": report.n_evaluated,
        "neighbors_generated": report.n_generated,
        "compositions_rejected": report.n_rejected,
        "frontier_points": report.n_frontier_points,
        "envelope_points": report.n_envelope_points,
        "envelope_compositions": report.n_envelope_compositions,
        "timings_seconds": {
            stage: {
                "count": summary.count,
                "mean": summary.mean,
                "max": summary.maximum,
                "percentiles": {str(level): value for level, value in summary.percentiles},
            }
            for stage, summary in report.timings.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=int, nargs="+", required=True)
    parser.add_argument("--held", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=None)
    args = parser.parse_args()
    config = base_config()
    if args.repetitions is not None:
        config = dataclasses.replace(
            config, benchmark=dataclasses.replace(config.benchmark, repetitions=args.repetitions)
        )
    runs: list[dict[str, object]] = []
    for universe in args.universe:
        problem = universe_problem(universe, args.held, args.seed, config)
        for treatment in (CostTreatment.GROSS, CostTreatment.NET):
            report = candidate_pipeline_benchmark(
                config, problem, treatment, FrontierMethod.RISK_AVERSION_GRID
            )
            runs.append(_report_dict(report, universe))
            timings = report.timings
            print(
                f"universo={universe:4d} {treatment.value:5s} "
                f"composiciones={report.n_compositions:3d} "
                f"evaluadas={report.n_evaluated:5d} rechazadas={report.n_rejected:4d} "
                f"screening={timings['screening'].mean:7.3f} s "
                f"generación={timings['candidate_generation'].mean:7.3f} s "
                f"fronteras={timings['frontier_evaluation'].mean:7.3f} s "
                f"pareto={timings['pareto'].mean * 1e3:7.2f} ms "
                f"total={timings['total'].mean:7.3f} s"
            )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "metadata": {
            "benchmark": "candidate_engine",
            "evidence_for": ["BEN-001", "BEN-002", "BEN-006"],
            "execution_timestamp_utc": stamp,
            "git_commit": _git_commit(),
            "config_hash": config_hash(config),
            "random_seed": args.seed,
            "held_assets": args.held,
            "universe_sizes": args.universe,
            "repetitions": config.benchmark.repetitions,
            "warmup_runs": config.benchmark.warmup_runs,
            "candidate_config": dataclasses.asdict(config.candidates),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "osqp": osqp.__version__,
            "note": (
                "Tiempos (s) medidos por este script en un proceso, sin paralelismo. "
                "No son rendimiento de producción."
            ),
        },
        "runs": runs,
    }
    output = ROOT / "benchmarks" / "results" / f"candidate_engine_{stamp}.json"
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Resultados guardados en {output}")


if __name__ == "__main__":
    main()
