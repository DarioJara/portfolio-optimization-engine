"""Resume en anotaciones de GitHub Actions los JSON de benchmark de una ejecución de CI (B5.5).

Los logs de Actions no son públicos sin autenticación, pero las anotaciones sí: este script imprime
líneas ``::notice`` con las cifras que importan (sin interpretarlas) para que la evidencia de Linux
quede consultable por la API pública de *check-runs*. No decide el resultado del paso.

Uso::

    python benchmarks/scripts/ci_summary.py scaling benchmarks/results/ci/scaling_*.json
    python benchmarks/scripts/ci_summary.py h1 benchmarks/results/ci/h1_*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: GitHub limita la longitud de una anotación; se corta con margen.
MAX_ANNOTATION = 3500


def _emit(title: str, message: str) -> None:
    print(f"::notice title={title}::{message[:MAX_ANNOTATION]}")


def _scaling(document: dict[str, Any]) -> None:
    host = document["metadata"]["host"]
    _emit(
        "b55-scaling-env",
        f"{host['os']} | {host['cpu_model']} | logical={host['cpu_logical']} "
        f"physical={host['cpu_physical']} smt={host['smt_enabled']} | python "
        f"{document['metadata']['python']} | commit {document['metadata']['git']['commit']}",
    )
    for entry in document["results"]:
        lines = []
        for cell in entry["cells"]:
            if not cell.get("available", True):
                lines.append(f"{cell['mode']}: NO DISPONIBLE ({cell['reason']})")
                continue
            wall = cell["wall"]
            extra = ""
            if cell["mode"] != "sequential":
                extra = (
                    f" speedup_min={cell.get('speedup_min', float('nan')):.2f}"
                    f" inicio={cell['pool_startup_seconds']['median']:.2f}s"
                    f" T1dif={cell['t1_differences_vs_sequential']}"
                    f" restricciones_limpias={cell['constraint_audit']['budget_violations'] == 0}"
                    f" rssW={cell['memory']['worker_peak_rss_bytes_max'] / 1e6:.0f}MB"
                )
            lines.append(
                f"{cell['mode']} w={cell['workers']} min={wall['min']:.2f}s "
                f"med={wall['median']:.2f}s valida={cell['valid_measurement']}{extra}"
            )
        _emit(f"b55-scaling-{entry['mix']}-{entry['portfolios']}", " ;; ".join(lines))


def _h1(document: dict[str, Any]) -> None:
    host = document["metadata"]["host"]
    _emit(
        "b55-h1-env",
        f"{host['os']} | {host['cpu_model']} | commit {document['metadata']['git']['commit']}",
    )
    for label, cells in document["part_a_engine"].items():
        _emit(
            f"b55-h1-engine-{label}",
            " ".join(
                f"eps={c['relative_perturbation']:g}:{c['valid_fraction']:.2f}" for c in cells
            ),
        )
    configured = next(iter(document["part_a_engine"].values()))
    unperturbed = next(c for c in configured if c["relative_perturbation"] == 0.0)
    _emit(
        "b55-h1-unperturbed",
        f"tolerancia configurada, sin perturbar: estados={unperturbed['states']} "
        f"iteraciones={unperturbed['clarabel_iterations']} "
        f"huecos={unperturbed['max_abs_gap_worst_case_utility_vs_solver_t']}",
    )
    _emit(
        "b55-h1-slsqp",
        " ".join(
            f"ftol={c['ftol']:g}/eps={c['start_point_relative_perturbation']:g}:"
            f"{c['success_fraction']:.2f}"
            for c in document["part_b_slsqp_oracle"]
        ),
    )


def main() -> None:
    kind, paths = sys.argv[1], [Path(p) for p in sys.argv[2:]]
    if not paths:
        raise SystemExit("No hay ficheros que resumir.")
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        {"scaling": _scaling, "h1": _h1}[kind](document)


if __name__ == "__main__":
    main()
