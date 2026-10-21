"""Perfilado ``cProfile`` de una clase de coste con el ejecutor secuencial (B5.5; E1).

Ejecuta ``--portfolios`` carteras sintéticas de cada clase pura ``--label`` con ``cProfile`` y
agrupa el tiempo propio (``tottime``) por origen del código: solvers nativos y bibliotecas
numéricas (``osqp``, ``clarabel``, ``scipy``, ``numpy``, ``pyscipopt``), código del motor
(``portfolio_engine``) y resto. No mide rendimiento absoluto (el perfilador añade sobrecoste):
sirve para ver **dónde** se va el tiempo, p. ej. cuánto es Python propio frente a llamadas a
solvers (hipótesis de ``BLOCK_5_HPC_ARCHITECTURE.md`` §4.4: 82–88 % en Python en W1).

Uso::

    python benchmarks/scripts/profile_class.py --label W1-GLOBAL-NET --portfolios 3
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
import synthetic_portfolios  # noqa: E402

from portfolio_engine.config.scaling_config import (  # noqa: E402
    ClassShare,
    WorkloadMix,
    load_scaling_benchmark_config,
)
from portfolio_engine.parallel.executor import SequentialExecutor  # noqa: E402

DEFAULT_CONFIG = ROOT / "config" / "default_benchmark.toml"
TOP_FUNCTIONS = 15
#: Prefijos de ruta (normalizados con ``/``) que definen el origen de una función.
ORIGINS = (
    ("solver nativo / bibliotecas", ("osqp", "clarabel", "pyscipopt")),
    ("scipy", ("scipy",)),
    ("numpy", ("numpy",)),
    ("motor (portfolio_engine)", ("portfolio_engine",)),
)


def _origin(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    for label, markers in ORIGINS:
        if any(f"/{marker}/" in normalized or f"/{marker}." in normalized for marker in markers):
            return label
    if normalized.startswith("~") or normalized == "<built-in>":
        return "intérprete (builtins)"
    return "resto (stdlib, pandas, otros)"


def profile(label: str, portfolios: int, seed: int, config_path: Path) -> dict[str, Any]:
    scaling = load_scaling_benchmark_config(config_path)
    mix = WorkloadMix(f"PROFILE:{label}", (ClassShare(label, 1.0),))
    batch = synthetic_portfolios.generate(scaling, mix, portfolios, seed)
    executor = SequentialExecutor(batch.config, batch.snapshot)
    executor.run(batch.requests)  # calentamiento: importaciones y cachés de módulo
    profiler = cProfile.Profile()
    profiler.enable()
    executor.run(batch.requests)
    profiler.disable()
    stats = pstats.Stats(profiler)
    total = sum(entry[2] for entry in stats.stats.values())  # type: ignore[attr-defined]
    by_origin: dict[str, float] = {}
    rows = []
    for (filename, line, name), (_cc, _nc, tottime, cumtime, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        origin = _origin(filename)
        by_origin[origin] = by_origin.get(origin, 0.0) + tottime
        rows.append((tottime, cumtime, f"{Path(filename).name}:{line}({name})", origin))
    rows.sort(reverse=True)
    return {
        "label": label,
        "portfolios": portfolios,
        "total_profiled_seconds": total,
        "self_time_by_origin_fraction": {
            origin: seconds / total for origin, seconds in sorted(by_origin.items())
        },
        "top_functions_by_self_time": [
            {"function": name, "origin": origin, "self_seconds": t, "cumulative_seconds": c}
            for t, c, name, origin in rows[:TOP_FUNCTIONS]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--label", nargs="+", required=True)
    parser.add_argument("--portfolios", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    args = parser.parse_args()
    meta = _common.metadata(
        "profile_class",
        ["BEN-001", "E1"],
        random_seed=args.seed,
        portfolios=args.portfolios,
        note="cProfile añade sobrecoste: úsese para repartos relativos, no para tiempos absolutos",
    )
    document = {
        "metadata": meta,
        "profiles": [profile(name, args.portfolios, args.seed, args.config) for name in args.label],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"profile_classes_{meta['execution_timestamp_utc']}.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    for entry in document["profiles"]:
        shares = ", ".join(
            f"{origin}: {fraction:.0%}"
            for origin, fraction in entry["self_time_by_origin_fraction"].items()
        )
        print(f"{entry['label']}: {shares}")
    print(f"resultado: {path}")


if __name__ == "__main__":
    main()
