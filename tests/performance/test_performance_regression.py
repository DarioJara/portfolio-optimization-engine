"""TST-005 / BEN-005: regresión de rendimiento frente a un baseline versionado.

Dos niveles, con honestidad sobre lo que cada uno demuestra:

1. **Trabajo (siempre se ejecuta, independiente del host).** Las llamadas reales a ``solve()`` y las
   iteraciones de solver de cada carga de referencia deben coincidir con el baseline
   (``benchmarks/results/baselines/perf_reference_work.json``). Un cambio aquí es un cambio de
   **trabajo** (otro algoritmo, otra malla, otro presupuesto de búsqueda) y se detecta aunque el
   reloj no cambie. Las iteraciones de solver pueden variar por hardware en una unidad; las
   llamadas, que son estructurales, no.
2. **Tiempo (opt-in).** Los tiempos de pared solo son comparables en el MISMO host y esta máquina es
   bimodal; por eso la comparación de tiempos solo se ejecuta con
   ``PE_RUN_TIMING_REGRESSION=1``, compara el MÍNIMO de las repeticiones con un umbral
   ``k × MAD`` derivado del baseline (``ScalingBenchmarkConfig``) y, ante un posible deterioro,
   confirma con repeticiones adicionales antes de fallar. Si el host no coincide con el del
   baseline, el test se omite **y esa omisión no cuenta como validación**.
"""

from __future__ import annotations

import json
import os

import pytest

from portfolio_engine.benchmark.regression import (
    RegressionVerdict,
    cell_key,
    compare_to_baseline,
    load_baseline,
)
from tests.fixtures.benchmark_scripts import load_script

pytestmark = pytest.mark.performance

PERF = load_script("perf_reference")
COMMON = load_script("_common")
TIMING_ENV = "PE_RUN_TIMING_REGRESSION"
#: Repeticiones y rondas de confirmación del test de tiempo (no son parámetros del motor).
CONFIRMATION_ROUNDS = 3


def _work_baseline() -> dict[str, dict[str, int]]:
    document = json.loads(PERF.WORK_BASELINE.read_text(encoding="utf-8"))
    return {key: value for key, value in document["cells"].items()}


@pytest.mark.parametrize(("label", "portfolios"), PERF.REFERENCE_CELLS)
def test_the_work_of_every_reference_cell_matches_the_versioned_baseline(
    label: str, portfolios: int
) -> None:
    """El trabajo determinista (llamadas al solver) no cambia respecto al baseline."""
    expected = _work_baseline()[cell_key(label, portfolios, "sequential")]
    measured = PERF.measure_cell(label, portfolios, repetitions=1)
    assert measured.solver_calls == expected["solver_calls"], (
        f"{label}: el trabajo cambió ({expected['solver_calls']} -> {measured.solver_calls} "
        "llamadas al solver): es un cambio de trabajo, no de velocidad."
    )
    # Las iteraciones pueden variar en una unidad entre CPU: tolerancia relativa configurada.
    tolerance = max(
        1,
        round(PERF.scaling_config().iteration_relative_tolerance * expected["frontier_iterations"]),
    )
    assert abs(measured.frontier_iterations - expected["frontier_iterations"]) <= tolerance


def test_the_baseline_covers_every_reference_cell_and_records_its_provenance() -> None:
    document = json.loads(PERF.WORK_BASELINE.read_text(encoding="utf-8"))
    keys = {cell_key(label, n, "sequential") for label, n in PERF.REFERENCE_CELLS}
    assert set(document["cells"]) == keys
    meta = document["metadata"]
    assert meta["git"]["commit"] and meta["host_fingerprint"] and meta["random_seed"] == PERF.SEED


def test_the_committed_timing_baseline_detects_a_synthetic_slowdown_and_a_change_of_work() -> None:
    """Mutación de la detección: sobre el baseline real, ×3 de tiempo es ``SLOWER``, el mismo tiempo
    está dentro del ruido y un contador de trabajo distinto es ``WORK_CHANGED`` (no un juicio de
    velocidad). No depende del host que ejecute la prueba (usa la huella del propio baseline)."""
    paths = sorted(PERF.BASELINE_DIR.glob("perf_reference_*.json"))
    timing_paths = [p for p in paths if p.name != PERF.WORK_BASELINE.name]
    assert timing_paths, "no hay baselines de tiempos versionados"
    cells, _ = load_baseline(timing_paths[0])
    scaling = PERF.scaling_config()
    for key, cell in cells.items():
        kwargs = {
            "host": cell.host,
            "k": scaling.mad_k,
            "relative_floor": scaling.mad_relative_floor,
            "current_work": cell.work_counter,
        }
        same = compare_to_baseline(list(cell.samples), cell, **kwargs)
        assert same.verdict is RegressionVerdict.WITHIN_NOISE, key
        slower = compare_to_baseline([3.0 * v for v in cell.samples], cell, **kwargs)
        assert slower.verdict is RegressionVerdict.SLOWER, key
        more_work = dict(kwargs, current_work=(cell.work_counter or 0) + 1)
        changed = compare_to_baseline([3.0 * v for v in cell.samples], cell, **more_work)
        assert changed.verdict is RegressionVerdict.WORK_CHANGED, key


@pytest.mark.skipif(
    os.environ.get(TIMING_ENV) != "1",
    reason=f"comparación de tiempos opt-in (exporte {TIMING_ENV}=1); no cuenta como validación",
)
def test_wall_time_has_not_regressed_beyond_the_measured_noise() -> None:
    fingerprint = COMMON.host_fingerprint()
    path = PERF.BASELINE_DIR / f"perf_reference_{fingerprint}.json"
    if not path.exists():
        pytest.skip(f"no hay baseline de tiempos para este host ({fingerprint}); no es validación")
    cells, _ = load_baseline(path)
    scaling = PERF.scaling_config()
    failures: list[str] = []
    for label, portfolios in PERF.REFERENCE_CELLS:
        key = cell_key(label, portfolios, "sequential")
        verdict = None
        for _ in range(CONFIRMATION_ROUNDS):
            measured = PERF.measure_cell(label, portfolios, repetitions=scaling.repetitions_small)
            verdict = compare_to_baseline(
                list(measured.samples),
                cells[key],
                host=fingerprint,
                k=scaling.mad_k,
                relative_floor=scaling.mad_relative_floor,
                current_work=measured.solver_calls,
                statistic="min",
            )
            if verdict.verdict is not RegressionVerdict.SLOWER:
                break  # una ronda dentro del ruido (o más rápida) descarta la fase lenta
        assert verdict is not None
        if verdict.verdict is RegressionVerdict.SLOWER:
            failures.append(f"{key}: {verdict.detail}")
        assert verdict.verdict is not RegressionVerdict.WORK_CHANGED, f"{key}: {verdict.detail}"
    assert not failures, "deterioro de rendimiento confirmado en todas las rondas: " + "; ".join(
        failures
    )
