"""Mide qué publica el motor SIN mandato para una cartera de 11 posiciones (hallazgos G-1/G-2).

Uso (desde la raíz del repositorio, con el entorno ``.venv``)::

    PYTHONPATH=. .venv/Scripts/python.exe evidence/hard_constraints/legacy_gap_measurement.py

Genera la ``GLOBAL_CANDIDATE_FRONTIER`` de ``random_problem(16, held=[0..10], seed=11)`` con la
configuración de ejemplo (sin ``[hard_constraints]``) y cuenta, para cada punto marcado
``is_valid_solution``, las posiciones reales (``w_i > 1e-8``) y las sustituciones uno a uno respecto
a la cartera original. Todo se calcula aquí desde los pesos publicados.
"""

from __future__ import annotations

from collections import Counter

from portfolio_engine.frontiers import GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from tests.fixtures.candidates import random_problem
from tests.fixtures.problems import base_config

THRESHOLD = 1e-8


def main() -> None:
    config = base_config()
    problem = random_problem(16, list(range(11)), 11, config, max_weight=0.6)
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    original = set(problem.state.asset_ids)
    sizes: Counter[int] = Counter()
    replacements: Counter[int] = Counter()
    for point in result.valid_points:
        weights = point.point.weights
        assert weights is not None
        held = {a for a, w in zip(point.asset_ids, weights.tolist(), strict=True) if w > THRESHOLD}
        sizes[len(held)] += 1
        replacements[min(len(held - original), len(original - held))] += 1
    volatilities = [p.point.metrics.volatility for p in result.valid_points if p.point.metrics]
    print(f"puntos publicados: {len(result.points)}; marcados validos: {len(result.valid_points)}")
    print(f"posiciones por punto: {dict(sorted(sizes.items()))}")
    print(f"sustituciones uno a uno por punto: {dict(sorted(replacements.items()))}")
    candidate_sizes = Counter(len(c.asset_ids) for c in result.candidates)
    print(f"tamano de las composiciones candidatas: {dict(candidate_sizes)}")
    print(f"volatilidad de los puntos validos: {min(volatilities):.4f} - {max(volatilities):.4f}")


if __name__ == "__main__":
    main()
