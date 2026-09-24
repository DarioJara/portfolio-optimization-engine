"""TST-004: regresión numérica de fronteras de referencia frente a valores dorados."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tests.numerical_regression.snapshot import snapshot

pytestmark = pytest.mark.numerical_regression

GOLDEN = Path(__file__).parent / "golden" / "frontiers.json"
#: Tolerancia de regresión: cambios de plataforma/BLAS mueven los resultados ~1e-12; 1e-6 detecta
#: cualquier cambio de modelo o de tolerancias del solver.
TOLERANCE = 1e-6


def test_frontiers_match_the_golden_files() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = snapshot()
    assert set(current) == set(golden)
    for case, expected in golden.items():
        for name, values in expected.items():
            assert np.array(current[case][name]) == pytest.approx(
                np.array(values), abs=TOLERANCE
            ), (
                case,
                name,
            )
