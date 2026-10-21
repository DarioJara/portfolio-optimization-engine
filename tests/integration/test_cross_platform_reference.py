"""C-28 (B5.5): equivalencia numérica entre plataformas bajo T1.

La referencia (``benchmarks/results/baselines/cross_platform_reference.json``) se generó en
Windows 11 / Intel i7-13620H / Python 3.13. Esta prueba reproduce el mismo lote sintético
(10 carteras de ``ENG-MIX-BASE``, semilla 7) en la plataforma actual y exige: mismos estados de
ejecución y de solver, mismo nº de soluciones y activos, y ``|Δpeso| ≤ 1e-6`` (T1). En Windows es
una comprobación de reproducibilidad; en Linux (CI) es la prueba de equivalencia entre plataformas.
Un fallo en Linux no se enmascara: se investiga (puede ser un síntoma de H-1, véase
``INVESTIGATION_H1_B4.md``).
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.benchmark_scripts import load_script
from tests.fixtures.parallel import T1_ABS_TOLERANCE

pytestmark = pytest.mark.integration

REFERENCE = load_script("cross_platform_reference")


def test_the_reference_batch_matches_the_committed_cross_platform_fingerprint() -> None:
    document = json.loads(REFERENCE.REFERENCE_PATH.read_text(encoding="utf-8"))
    assert document["metadata"]["git"]["commit"] and document["metadata"]["host"]["os"]
    found = REFERENCE.differences(document["portfolios"], REFERENCE.compute(), T1_ABS_TOLERANCE)
    assert found == [], found


def test_the_comparison_detects_a_weight_a_status_and_a_count_change() -> None:
    base = {
        "P": {
            "execution_status": "COMPLETED",
            "solutions": [[["A", "B"], [0.4, 0.6]]],
            "point_statuses": ["OPTIMAL"],
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
    count = json.loads(json.dumps(base))
    count["P"]["solutions"].append([["A", "B"], [0.5, 0.5]])
    assert REFERENCE.differences(base, count, T1_ABS_TOLERANCE)
