"""Referencia de equivalencia entre plataformas (B5.5; C-28 de ``BLOCK_5_BENCHMARK_PLAN.md`` §7.2).

Genera y compara la huella numérica (pesos de todas las soluciones, estados de ejecución y de
solver) de un lote sintético fijo: 10 carteras de ``ENG-MIX-BASE`` con semilla 7 ejecutadas con el
ejecutor secuencial. El fichero de referencia se produjo en Windows/Intel;
``tests/integration/test_cross_platform_reference.py`` lo reproduce en la plataforma que ejecute la
suite (en CI, Linux) y exige T1 (``|Δpeso| ≤ 1e-6``) con igualdad exacta de recuentos y estados.

Uso::

    python benchmarks/scripts/cross_platform_reference.py explain   # diagnóstico de divergencias
    python benchmarks/scripts/cross_platform_reference.py write     # regenerar (razón documentada)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
import synthetic_portfolios  # noqa: E402

from portfolio_engine.config.scaling_config import load_scaling_benchmark_config  # noqa: E402
from portfolio_engine.parallel.executor import SequentialExecutor  # noqa: E402

REFERENCE_PATH = ROOT / "benchmarks" / "results" / "baselines" / "cross_platform_reference.json"
SCALING_CONFIG_PATH = ROOT / "config" / "default_benchmark.toml"
MIX = "ENG-MIX-BASE"
PORTFOLIOS = 10
SEED = 7


def compute() -> dict[str, Any]:
    """Huella del lote de referencia en ESTA plataforma."""
    scaling = load_scaling_benchmark_config(SCALING_CONFIG_PATH)
    batch = synthetic_portfolios.generate(scaling, scaling.mix(MIX), PORTFOLIOS, SEED)
    run = SequentialExecutor(batch.config, batch.snapshot).run(batch.requests)
    return _common.solution_fingerprint(run.results)


def differences(reference: dict[str, Any], current: dict[str, Any], tolerance: float) -> list[str]:
    """Diferencias entre dos huellas: exactas en estados y recuentos, T1 en los pesos."""
    found: list[str] = []
    if set(reference) != set(current):
        return [f"carteras distintas: {sorted(set(reference) ^ set(current))}"]
    for portfolio_id, expected in reference.items():
        got = current[portfolio_id]
        if expected["execution_status"] != got["execution_status"]:
            found.append(f"{portfolio_id}: estado de ejecución distinto")
        if expected["point_statuses"] != got["point_statuses"]:
            found.append(f"{portfolio_id}: estados de solver distintos")
        if len(expected["solutions"]) != len(got["solutions"]):
            found.append(f"{portfolio_id}: nº de soluciones distinto")
            continue
        for position, ((ids_a, w_a), (ids_b, w_b)) in enumerate(
            zip(expected["solutions"], got["solutions"], strict=True)
        ):
            if ids_a != ids_b or len(w_a) != len(w_b):
                found.append(f"{portfolio_id}[{position}]: activos distintos")
                continue
            worst = max((abs(a - b) for a, b in zip(w_a, w_b, strict=True)), default=0.0)
            if worst > tolerance:
                found.append(f"{portfolio_id}[{position}]: |Δpeso| máx = {worst:.3e}")
    return found


def explain(reference: dict[str, Any], current: dict[str, Any], tolerance: float) -> list[str]:
    """Descripción compacta de cada cartera divergente (para diagnóstico en CI)."""
    from collections import Counter

    lines: list[str] = []
    for portfolio_id in sorted(set(reference) & set(current)):
        expected, got = reference[portfolio_id], current[portfolio_id]
        if not differences({portfolio_id: expected}, {portfolio_id: got}, tolerance):
            continue
        ref_ids = {tuple(ids) for ids, _ in expected["solutions"]}
        cur_ids = {tuple(ids) for ids, _ in got["solutions"]}
        lines.append(
            f"{portfolio_id}: soluciones {len(expected['solutions'])} (ref) vs "
            f"{len(got['solutions'])} (actual); composiciones distintas {len(ref_ids)} vs "
            f"{len(cur_ids)}, solo en ref {len(ref_ids - cur_ids)}, solo en actual "
            f"{len(cur_ids - ref_ids)}; estados ref {dict(Counter(expected['point_statuses']))} "
            f"vs actual {dict(Counter(got['point_statuses']))}"
        )
        shared = ref_ids & cur_ids
        worst = 0.0
        for ids, weights in expected["solutions"]:
            if tuple(ids) not in shared:
                continue
            for other_ids, other in got["solutions"]:
                if tuple(other_ids) == tuple(ids) and len(other) == len(weights):
                    worst = max(worst, *(abs(a - b) for a, b in zip(weights, other, strict=True)))
                    break
        lines.append(f"  máx |Δpeso| entre soluciones de composiciones comunes: {worst:.3e}")
    return lines or ["sin divergencias"]


def main() -> None:
    if sys.argv[1:] == ["explain"]:
        document = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
        for line in explain(document["portfolios"], compute(), 1e-6):
            print(line)
        return
    if sys.argv[1:] != ["write"]:
        raise SystemExit(__doc__)
    fingerprint = compute()
    document = {
        "metadata": _common.metadata(
            "cross_platform_reference",
            ["C-28", "PAR-008"],
            mix=MIX,
            portfolios=PORTFOLIOS,
            random_seed=SEED,
            executor="SequentialExecutor",
        ),
        "portfolios": fingerprint,
    }
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(json.dumps(document), encoding="utf-8")
    solutions = sum(len(entry["solutions"]) for entry in fingerprint.values())
    print(f"referencia: {REFERENCE_PATH} ({len(fingerprint)} carteras, {solutions} soluciones)")


if __name__ == "__main__":
    main()
