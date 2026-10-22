"""Validación por escalas y estimación de capacidad (B5.5; BEN-007, GOV-012).

Dos subcomandos:

``run``
    Ejecuta el benchmark de escalado (``scaling.py``) para las escalas pedidas. Las escalas
    oficiales de cierre son 10, 100 y 1.200 carteras; **toda escala que supere
    ``max_portfolios_without_authorization`` (D-12) se rechaza** salvo ``--authorized-by`` con la
    referencia de la autorización expresa del usuario. Una ejecución abortada o con mediciones no
    válidas no cuenta como PASS.

``estimate``
    NO ejecuta nada. Lee resultados ya medidos (``scaling_*.json``) y calcula, para las escalas
    objetivo, duración (rango), horas-núcleo y memoria. Es aritmética sobre una medición concreta
    (``portfolio_engine.benchmark.scaling.project_capacity``): usa solo números de workers medidos,
    no extrapola el número de workers y declara su factor de extrapolación. La eficiencia se estima
    en régimen estacionario (descontando el arranque del pool, que se suma aparte). Sin
    ``--price-per-core-hour`` no se calcula dinero (no se inventan precios).

Uso::

    python benchmarks/scripts/scale_run.py run --scales 10 100 --mix ENG-MIX-BASE
    python benchmarks/scripts/scale_run.py estimate --inputs benchmarks/results/scaling_*.json \\
        --mix ENG-MIX-BASE --targets 1000 1200 5000 22000 --workers 4
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402

from portfolio_engine.benchmark.scaling import (  # noqa: E402
    ProjectionInputs,
    project_capacity,
)
from portfolio_engine.config.scaling_config import load_scaling_benchmark_config  # noqa: E402

DEFAULT_CONFIG = ROOT / "config" / "default_benchmark.toml"
OFFICIAL_SCALES = (10, 100, 1200)


def _run(args: argparse.Namespace) -> None:
    import scaling

    scaling_config = load_scaling_benchmark_config(args.config)
    cap = scaling_config.max_portfolios_without_authorization
    if max(args.scales) > cap and not args.authorized_by:
        raise SystemExit(
            f"Escala {max(args.scales)} > {cap}: requiere autorización expresa (D-12). Este script "
            "NO ejecuta cargas masivas sin --authorized-by con la referencia de la autorización."
        )
    missing = [s for s in OFFICIAL_SCALES if s not in args.scales]
    if missing:
        print(f"Aviso: escalas oficiales NO ejecutadas en esta invocación: {missing}")
    argv = [
        "scaling.py",
        "--config",
        str(args.config),
        "--scales",
        *map(str, args.scales),
        "--mix",
        args.mix,
        "--workers",
        *map(str, args.workers),
        "--methods",
        *args.methods,
        "--out",
        str(args.out),
    ]
    if args.authorized_by:
        argv += ["--authorized-by", args.authorized_by]
    sys.argv = argv
    scaling.main()


def _entries(paths: list[Path], mix: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document["results"]:
            if entry["mix"] == mix:
                found.append({**entry, "_source": path.name, "_metadata": document["metadata"]})
    if not found:
        raise SystemExit(f"No hay mediciones de la mezcla {mix!r} en los ficheros indicados.")
    return found


def _unit_from_classes(
    args: argparse.Namespace,
) -> tuple[tuple[float, float, float], int, dict[str, Any]]:
    """Coste unitario del mix ``--shares-mix`` a partir de costes por clase medidos (clases puras).

    ``Σ sᵢ·cᵢ`` con las fracciones de la mezcla renormalizadas a las clases medidas; las clases sin
    medición a esa dimensión se excluyen y su fracción se informa (nunca se les asigna un coste).
    """
    config = load_scaling_benchmark_config(args.config)
    shares = {s.label: s.fraction for s in config.mix(args.shares_mix or args.mix).shares}
    costs: dict[str, tuple[float, float, float]] = {}
    sizes: dict[str, int] = {}
    for path in args.class_costs:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        for entry in document["results"]:
            if not entry["mix"].startswith("PURE:"):
                continue
            seq = next(c for c in entry["cells"] if c["mode"] == "sequential")
            n_class = entry["portfolios"]
            label = entry["mix"].removeprefix("PURE:")
            costs[label] = (
                seq["wall"]["min"] / n_class,
                seq["wall"]["median"] / n_class,
                seq["wall"]["max"] / n_class,
            )
            sizes[label] = n_class
    used = {label: f for label, f in shares.items() if label in costs}
    if not used:
        raise SystemExit("Ninguna clase de la mezcla tiene coste medido en --class-costs.")
    total = sum(used.values())
    unit = tuple(sum(f / total * costs[label][k] for label, f in used.items()) for k in range(3))
    source = {
        "source": "pure-class costs",
        "shares_mix": args.shares_mix or args.mix,
        "class_cost_files": [Path(p).name for p in args.class_costs],
        "classes_used": sorted(used),
        "share_excluded_without_measurement": 1.0 - total,
        "excluded_classes": sorted(set(shares) - set(used)),
        "portfolios_measured_per_class": dict(sorted(sizes.items())),
    }
    return (unit[0], unit[1], unit[2]), min(sizes[label] for label in used), source


def _unit_from_mix(
    args: argparse.Namespace, entries: list[dict[str, Any]]
) -> tuple[tuple[float, float, float], int, dict[str, Any]]:
    """Rango de coste por cartera: mín., mediana y máx. de TODAS las mediciones secuenciales.

    Se agrupan campañas distintas: la variación de fase de la máquina entra en el rango.
    """
    n = min(e["portfolios"] for e in entries)
    seq_cells = [
        (e["portfolios"], next(c for c in e["cells"] if c["mode"] == "sequential")) for e in entries
    ]
    unit = (
        min(c["wall"]["min"] / size for size, c in seq_cells),
        statistics.median(c["wall"]["median"] / size for size, c in seq_cells),
        max(c["wall"]["max"] / size for size, c in seq_cells),
    )
    source: dict[str, Any] = {
        "source": "mix",
        "mix": args.mix,
        "measured_portfolios": n,
        "measurements_pooled": len(seq_cells),
    }
    return unit, n, source


def _steady_state(
    entries: list[dict[str, Any]], method: str, workers: int
) -> tuple[list[float], list[float], list[int], list[int]]:
    """Eficiencia en régimen estacionario (arranque descontado), arranques y memoria medidos."""
    efficiencies: list[float] = []
    startups: list[float] = []
    worker_rss: list[int] = []
    coordinator_rss: list[int] = []
    for entry in entries:
        seq = next(c for c in entry["cells"] if c["mode"] == "sequential")
        for cell in entry["cells"]:
            if cell["mode"] != method or cell.get("workers") != workers:
                continue
            startup = cell["pool_startup_seconds"]["median"]
            steady = cell["wall"]["min"] - startup
            if steady > 0:
                efficiencies.append(seq["wall"]["min"] / (workers * steady))
            startups.append(startup)
            worker_rss.append(cell["memory"]["worker_peak_rss_bytes_max"])
            coordinator_rss.append(cell["memory"]["coordinator_peak_rss_bytes"])
    return efficiencies, startups, worker_rss, coordinator_rss


def _estimate(args: argparse.Namespace) -> None:
    entries = [
        e
        for e in _entries([Path(p) for p in args.inputs], args.mix)
        if e["portfolios"] >= args.min_portfolios
    ]
    if not entries:
        raise SystemExit(
            f"No hay mediciones de {args.mix!r} con >= {args.min_portfolios} carteras."
        )
    unit, n, unit_source = _unit_from_mix(args, entries)
    if args.class_costs:
        unit, n, unit_source = _unit_from_classes(args)
    projections: list[dict[str, Any]] = []
    for workers in args.workers:
        efficiencies, startups, worker_rss, coordinator_rss = _steady_state(
            entries, args.method, workers
        )
        if not efficiencies:
            raise SystemExit(
                f"No hay mediciones de {args.method} con {workers} workers: no se extrapola el "
                "número de workers."
            )
        capped = [min(e, 1.0) for e in efficiencies]
        inputs = ProjectionInputs(
            unit_seconds=unit,
            efficiency=(min(capped), statistics.median(capped), max(capped)),
            startup_seconds=statistics.median(startups),
            worker_rss_bytes=float(max(worker_rss)),
            coordinator_rss_bytes=float(max(coordinator_rss)),
            measured_portfolios=n,
        )
        for target in args.targets:
            projection = project_capacity(
                inputs, target, workers, price_per_core_hour=args.price_per_core_hour
            )
            projections.append(
                {
                    "target_portfolios": target,
                    "workers": workers,
                    "inputs": {
                        "unit_seconds_min_median_max": inputs.unit_seconds,
                        "steady_efficiency_low_mid_high": inputs.efficiency,
                        "startup_seconds": inputs.startup_seconds,
                        "worker_rss_bytes_max": inputs.worker_rss_bytes,
                        "coordinator_rss_bytes_max": inputs.coordinator_rss_bytes,
                        "efficiency_samples": len(efficiencies),
                    },
                    "wall_seconds_optimistic_central_pessimistic": projection.wall_seconds,
                    "wall_hours_optimistic_central_pessimistic": tuple(
                        w / 3600 for w in projection.wall_seconds
                    ),
                    "core_hours_optimistic_central_pessimistic": projection.core_hours,
                    "peak_memory_bytes": projection.peak_memory_bytes,
                    "money_optimistic_central_pessimistic": projection.money,
                    "extrapolation_factor": projection.extrapolation_factor,
                    "caveat": projection.caveat,
                }
            )
    meta = _common.metadata(
        "capacity_estimate",
        ["BEN-007", "GOV-012"],
        mix=args.mix,
        unit_cost_source=unit_source,
        mode=args.method,
        source_files=[str(Path(p).name) for p in args.inputs],
        executed=False,
        price_per_core_hour=args.price_per_core_hour,
        statement=(
            "ESTIMACIÓN aritmética sobre mediciones concretas; NO se ha ejecutado ninguna carga de "
            "esta escala. Requiere autorización expresa del usuario (D-12) para ejecutarse."
        ),
    )
    document = {"metadata": meta, "projections": projections}
    args.out.mkdir(parents=True, exist_ok=True)
    label = (args.shares_mix or args.mix) + ("-classcosts" if args.class_costs else "")
    path = args.out / f"capacity_estimate_{label}_{meta['execution_timestamp_utc']}.json"
    path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
    header = "objetivo | workers | duración h (opt / central / pes) | horas-núcleo | GB"
    print(header)
    for p in projections:
        opt, mid, pes = p["wall_hours_optimistic_central_pessimistic"]
        print(
            f"{p['target_portfolios']:>8} | {p['workers']:>7} | "
            f"{opt:8.2f} / {mid:8.2f} / {pes:8.2f} | "
            f"{p['core_hours_optimistic_central_pessimistic'][1]:10.2f} | "
            f"{p['peak_memory_bytes'] / 1e9:6.2f}"
        )
    print(f"estimación: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="ejecuta escalas (con guarda D-12)")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run.add_argument("--scales", type=int, nargs="+", required=True)
    run.add_argument("--mix", required=True)
    run.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    run.add_argument("--methods", nargs="+", default=["sequential", "spawn", "forkserver"])
    run.add_argument("--authorized-by")
    run.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    est = sub.add_parser("estimate", help="proyecta capacidad desde mediciones (no ejecuta)")
    est.add_argument("--inputs", nargs="+", required=True)
    est.add_argument("--mix", required=True)
    est.add_argument(
        "--min-portfolios",
        type=int,
        default=100,
        help="mediciones con al menos este nº de carteras (por debajo domina el arranque)",
    )
    est.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    est.add_argument(
        "--class-costs",
        nargs="*",
        help="JSON de clases puras de las que sale el coste unitario (en vez del de --mix)",
    )
    est.add_argument("--shares-mix", help="mezcla cuyas fracciones pesan los costes por clase")
    est.add_argument("--targets", type=int, nargs="+", default=[1000, 1200, 5000, 22000])
    est.add_argument("--workers", type=int, nargs="+", required=True)
    est.add_argument("--method", default="spawn")
    est.add_argument("--price-per-core-hour", type=float, default=None)
    est.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    args = parser.parse_args()
    if args.command == "run":
        _run(args)
    else:
        _estimate(args)


if __name__ == "__main__":
    main()
