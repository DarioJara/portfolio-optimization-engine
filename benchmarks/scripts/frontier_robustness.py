"""Reproducción del experimento de robustez de fronteras (AUDIT_BLOCK_2, hallazgo H-1, Anexo A-2).

Resuelve 96 fronteras sintéticas: ``N ∈ {5, 10, 20, 40}`` × 6 semillas (0..5) ×
``{GROSS, NET}`` × ``{RISK_AVERSION_GRID, TARGET_RETURN_GRID}`` con la configuración por defecto y
clasifica cada una:

* ``healthy``: ``FrontierPoints`` puntos válidos y sin notas de degradación.
* ``no_frontier``: MaxReturn o MinVariance sin resolver (la malla se omite).
* ``degraded``: cualquier otra frontera con notas o con menos puntos válidos que el objetivo
  (incluye ``no_frontier``, como en la auditoría original).

Las semillas y el generador (``tests.fixtures.problems.synthetic_problem``) son los de
``benchmarks/scripts/solver_reuse.py``; no se cambian para
mejorar el resultado. Uso::

    .venv/Scripts/python benchmarks/scripts/frontier_robustness.py
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.frontiers import ContinuousFrontierEngine  # noqa: E402
from portfolio_engine.frontiers.continuous_frontier import (  # noqa: E402
    NOTE_MAX_RETURN_FAILED,
    NOTE_MIN_VARIANCE_FAILED,
)
from portfolio_engine.models.enums import CostTreatment, FrontierMethod  # noqa: E402
from tests.fixtures.problems import base_config, synthetic_problem  # noqa: E402

SIZES = (5, 10, 20, 40)
SEEDS = range(6)


def main() -> None:
    config = base_config()
    engine = ContinuousFrontierEngine(config)
    counts: Counter[str] = Counter()
    rows: list[str] = []
    started = time.perf_counter()
    for n_assets in SIZES:
        for seed in SEEDS:
            problem = synthetic_problem(n_assets, seed, config)
            for treatment in (CostTreatment.GROSS, CostTreatment.NET):
                for method in FrontierMethod:
                    result = engine.solve(problem, treatment, method)
                    missing = len(result.valid_points) < config.frontier.frontier_points
                    no_frontier = (
                        NOTE_MAX_RETURN_FAILED in result.notes
                        or NOTE_MIN_VARIANCE_FAILED in result.notes
                    )
                    degraded = missing or bool(result.notes)
                    counts["total"] += 1
                    counts["degraded"] += degraded
                    counts["no_frontier"] += no_frontier
                    counts["healthy"] += not degraded
                    if degraded:
                        rows.append(
                            f"N={n_assets} seed={seed} {treatment.value}/{method.value}: "
                            f"valid={len(result.valid_points)} notes={list(result.notes)}"
                        )
    print(f"Total frontiers: {counts['total']}")
    print(f"Healthy:         {counts['healthy']}")
    print(f"Degraded:        {counts['degraded']}")
    print(f"No frontier:     {counts['no_frontier']}")
    print(f"Elapsed:         {time.perf_counter() - started:.1f} s")
    for row in rows:
        print("  " + row)


if __name__ == "__main__":
    main()
