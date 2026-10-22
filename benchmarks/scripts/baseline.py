"""Crea los baselines de rendimiento de referencia (B5.5; BEN-005, TST-005).

Mide las celdas de ``perf_reference.REFERENCE_CELLS`` con el ejecutor secuencial y escribe:

* ``benchmarks/results/baselines/perf_reference_work.json``: contadores deterministas de trabajo
  (llamadas al solver e iteraciones), independientes del host;
* ``benchmarks/results/baselines/perf_reference_<huella-del-host>.json``: tiempos de pared de ESTE
  host (huella = SO, CPU, núcleos, versión de Python y de las librerías). Los tiempos de otro host
  no son comparables (``HOST_MISMATCH``).

No se sobreescribe un baseline existente sin ``--replace`` (el baseline anterior se conserva
versionado en git).

Uso::

    python benchmarks/scripts/baseline.py --repetitions 7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common
import perf_reference

from portfolio_engine.benchmark.regression import (
    BaselineCell,
    cell_key,
    save_baseline,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--show-work",
        action="store_true",
        help="solo imprime los contadores de trabajo de esta plataforma (no escribe nada)",
    )
    args = parser.parse_args()
    if args.show_work:
        for label, portfolios in perf_reference.REFERENCE_CELLS:
            measured = perf_reference.measure_cell(label, portfolios, 1)
            print(
                f"{cell_key(label, portfolios, 'sequential')}: "
                f"solver_calls={measured.solver_calls} "
                f"frontier_iterations={measured.frontier_iterations}"
            )
        return
    meta = _common.metadata(
        "perf_reference_baseline",
        ["BEN-005", "TST-005"],
        repetitions=args.repetitions,
        random_seed=perf_reference.SEED,
        cells=[list(cell) for cell in perf_reference.REFERENCE_CELLS],
    )
    fingerprint = meta["host_fingerprint"]
    timing_path = perf_reference.BASELINE_DIR / f"perf_reference_{fingerprint}.json"
    for path in (timing_path, perf_reference.WORK_BASELINE):
        if path.exists() and not args.replace:
            raise SystemExit(f"{path.name} ya existe: use --replace para sustituirlo.")
    timing: dict[str, BaselineCell] = {}
    work: dict[str, dict[str, int]] = {}
    for label, portfolios in perf_reference.REFERENCE_CELLS:
        measured = perf_reference.measure_cell(label, portfolios, args.repetitions)
        key = cell_key(label, portfolios, "sequential")
        timing[key] = BaselineCell(measured.samples, measured.solver_calls, fingerprint)
        work[key] = {
            "variants": [
                {
                    "solver_calls": measured.solver_calls,
                    "frontier_iterations": measured.frontier_iterations,
                    "observed_on": f"{meta['host']['os']} / {meta['host']['cpu_model']} / "
                    f"Python {meta['python']}",
                }
            ]
        }
        print(f"{key}: min={min(measured.samples):.3f} s llamadas={measured.solver_calls}")
    save_baseline(timing_path, timing, meta)
    perf_reference.WORK_BASELINE.parent.mkdir(parents=True, exist_ok=True)
    perf_reference.WORK_BASELINE.write_text(
        json.dumps({"metadata": meta, "cells": work}, indent=2, default=str), encoding="utf-8"
    )
    print(f"baseline de tiempos: {timing_path}")
    print(f"baseline de trabajo: {perf_reference.WORK_BASELINE}")


if __name__ == "__main__":
    main()
