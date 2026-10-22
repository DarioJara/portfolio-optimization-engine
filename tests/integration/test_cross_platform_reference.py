"""C-28 (B5.5): equivalencia numérica entre plataformas y entre CPU bajo T1.

La referencia (``benchmarks/results/baselines/cross_platform_reference.json``) se generó en
Windows 11 / Intel i7-13620H / Python 3.13 con el código posterior a la remediación H-1/F-B55-1
(``REMEDIATION_H1_FB551.md``). Esta prueba reproduce el mismo lote sintético (10 carteras de
``ENG-MIX-BASE``, semilla 7) en la máquina actual y exige, **cartera a cartera**: mismos estados de
ejecución y de solver (de puntos y de estrategias), mismo nº de soluciones y activos, y
``|Δpeso| ≤ 1e-6`` (T1).

**F-B55-1 (cerrado por la remediación de B3).** Antes de ella la cartera
``W1-GLOBAL-NET-000005-0000`` devolvía 11 o 12 composiciones según el núcleo de OpenBLAS que cargara
la CPU (``SkylakeX`` frente a ``Haswell``; no según el SO ni el fabricante). Ya no hay
``xfail``: toda divergencia hace fallar la prueba. Para no depender de la lotería de CPU del
runner, otra prueba fuerza cada núcleo (``OPENBLAS_CORETYPE``) en un subproceso; ``SkylakeX`` solo
se puede forzar en una CPU con AVX-512 y en las demás se **omite** (una omisión no cuenta como
validación).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.benchmark_scripts import SCRIPTS_DIR, load_script
from tests.fixtures.parallel import T1_ABS_TOLERANCE

pytestmark = pytest.mark.integration

REFERENCE = load_script("cross_platform_reference")
DOCUMENT = json.loads(REFERENCE.REFERENCE_PATH.read_text(encoding="utf-8"))
PORTFOLIOS: dict[str, Any] = DOCUMENT["portfolios"]
W1_PORTFOLIO = "W1-GLOBAL-NET-000005-0000"
#: Composiciones distintas de la cartera W1 del hallazgo F-B55-1 en la referencia.
W1_COMPOSITIONS = 11


def _has_avx512() -> bool:
    try:
        return "avx512f" in Path("/proc/cpuinfo").read_text(encoding="utf-8").lower()
    except OSError:
        return False


@pytest.fixture(scope="module")
def current() -> dict[str, Any]:
    return REFERENCE.compute()  # type: ignore[no-any-return]


def test_the_reference_covers_ten_portfolios_with_provenance() -> None:
    assert len(PORTFOLIOS) == 10 and W1_PORTFOLIO in PORTFOLIOS
    assert DOCUMENT["metadata"]["git"]["commit"] and DOCUMENT["metadata"]["host"]["os"]
    assert all("strategy_statuses" in entry for entry in PORTFOLIOS.values())


def test_the_current_machine_produces_the_same_portfolios(current: dict[str, Any]) -> None:
    assert set(current) == set(PORTFOLIOS)


@pytest.mark.parametrize("portfolio_id", sorted(PORTFOLIOS))
def test_each_portfolio_matches_the_committed_fingerprint(
    portfolio_id: str, current: dict[str, Any]
) -> None:
    found = REFERENCE.differences(
        {portfolio_id: PORTFOLIOS[portfolio_id]},
        {portfolio_id: current[portfolio_id]},
        T1_ABS_TOLERANCE,
    )
    assert found == [], (REFERENCE.openblas_kernel(), found)


def test_the_w1_candidate_set_is_the_same_composition_count_as_the_reference(
    current: dict[str, Any],
) -> None:
    """F-B55-1: el conjunto de candidatos de la cartera W1 ya no depende del núcleo BLAS."""
    for source in (PORTFOLIOS, current):
        compositions = {tuple(ids) for ids, _ in source[W1_PORTFOLIO]["solutions"]}
        assert len(compositions) == W1_COMPOSITIONS, REFERENCE.openblas_kernel()


def _run_forced(kernel: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, OPENBLAS_CORETYPE=kernel, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "cross_platform_reference.py"), "check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=False,
    )


@pytest.mark.parametrize("kernel", ["Haswell", "SkylakeX"])
def test_forcing_each_openblas_kernel_gives_the_same_fingerprint(kernel: str) -> None:
    """La equivalencia entre CPU no se deja a la lotería del runner: se fuerza el núcleo."""
    if kernel == "SkylakeX" and not _has_avx512():
        pytest.skip(
            "SkylakeX solo se puede forzar en una CPU con AVX-512 (no cuenta como validación)"
        )
    if sys.platform == "win32" and kernel == "SkylakeX":
        pytest.skip("sin AVX-512 comprobable en Windows (no cuenta como validación)")
    outcome = _run_forced(kernel)
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert f"kernel={kernel}" in outcome.stdout, outcome.stdout  # el núcleo forzado es el cargado


def test_the_comparison_detects_a_weight_a_status_and_a_count_change() -> None:
    base = {
        "P": {
            "execution_status": "COMPLETED",
            "solutions": [[["A", "B"], [0.4, 0.6]]],
            "point_statuses": ["OPTIMAL"],
            "strategy_statuses": [],
        }
    }
    same = json.loads(json.dumps(base))
    assert REFERENCE.differences(base, same, T1_ABS_TOLERANCE) == []
    shifted = json.loads(json.dumps(base))
    shifted["P"]["solutions"][0][1][0] = 0.4 + 2 * T1_ABS_TOLERANCE
    assert REFERENCE.differences(base, shifted, T1_ABS_TOLERANCE)
    inside = json.loads(json.dumps(base))
    inside["P"]["solutions"][0][1][0] = 0.4 + T1_ABS_TOLERANCE / 2
    assert REFERENCE.differences(base, inside, T1_ABS_TOLERANCE) == []
    status = json.loads(json.dumps(base))
    status["P"]["point_statuses"] = ["OPTIMAL_INACCURATE"]
    assert REFERENCE.differences(base, status, T1_ABS_TOLERANCE)
    strategy = json.loads(json.dumps(base))
    strategy["P"]["strategy_statuses"] = ["OPTIMAL_INACCURATE"]
    assert REFERENCE.differences(base, strategy, T1_ABS_TOLERANCE)  # A-06
    count = json.loads(json.dumps(base))
    count["P"]["solutions"].append([["A", "B"], [0.5, 0.5]])
    assert REFERENCE.differences(base, count, T1_ABS_TOLERANCE)
