"""VAL-001, VAL-008: la comprobación de cotas vectorizada equivale al recorrido activo a activo.

``SolutionValidator._bounds`` dejó de iterar sobre todos los activos (optimización del
``CandidateEngine``: se valida cada composición evaluada). El oráculo de este test es el recorrido
explícito original, escrito aquí de forma independiente.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.validation import SolutionValidator, ValidationTolerances
from portfolio_engine.validation.solution_validator import _Collector
from tests.fixtures.non_buyable import non_buyable_problem
from tests.unit.constraints.test_non_buyable_positions import _compile

pytestmark = pytest.mark.unit


def _oracle(weights, compiled, tolerance):  # type: ignore[no-untyped-def]
    """Recorrido escalar: (violaciones en orden, mayor exceso observado)."""
    violations, worst = [], 0.0
    for index, asset_id in enumerate(compiled.asset_ids):
        value = float(weights[index])
        low, high = float(compiled.lower[index]), float(compiled.upper[index])
        checks = [
            (f"BOUNDS:{asset_id}:lower", low - value),
            (f"BOUNDS:{asset_id}:upper", value - high),
        ]
        if compiled.long_only:
            checks.append((f"LONG_ONLY:{asset_id}", -value))
        for name, excess in checks:
            worst = max(worst, excess, 0.0)
            if max(excess, 0.0) > tolerance:
                violations.append((name, max(excess, 0.0)))
    return violations, worst


@pytest.mark.parametrize("seed", range(20))
def test_vectorized_bounds_match_the_scalar_walk(seed: int) -> None:
    config, problem = non_buyable_problem("not_eligible")
    compiled = _compile(config, problem)
    validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
    rng = np.random.default_rng(seed)
    for _ in range(25):
        weights = rng.uniform(-0.3, 1.3, compiled.size)  # con y sin violaciones de cota
        out = _Collector()
        validator._bounds(weights, compiled, out)
        expected, worst = _oracle(weights, compiled, config.solver.bound_tolerance)
        assert [v.constraint_id for v in out.violations] == [name for name, _ in expected]
        assert [v.violation for v in out.violations] == pytest.approx([e for _, e in expected])
        assert out.max_violation == pytest.approx(worst)
