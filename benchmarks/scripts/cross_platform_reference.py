"""Referencia de equivalencia entre plataformas (B5.5; C-28 de ``BLOCK_5_BENCHMARK_PLAN.md`` §7.2).

Genera y compara la huella numérica (pesos de todas las soluciones, estados de ejecución y de
solver) de un lote sintético fijo: 10 carteras de ``ENG-MIX-BASE`` con semilla 7 ejecutadas con el
ejecutor secuencial. El fichero de referencia se produjo en Windows/Intel;
``tests/integration/test_cross_platform_reference.py`` lo reproduce en la plataforma que ejecute la
suite (en CI, Linux) y exige T1 (``|Δpeso| ≤ 1e-6``) con igualdad exacta de recuentos y estados.

Uso (regenerar la referencia; solo con una razón documentada)::

    python benchmarks/scripts/cross_platform_reference.py write
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


def main() -> None:
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
