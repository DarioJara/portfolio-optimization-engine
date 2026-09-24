"""Instantánea numérica de fronteras de referencia para las pruebas de regresión (TST-004).

Los valores dorados (``golden/``) se generan con ``regenerate_golden.py`` desde el motor y sirven
para detectar cambios numéricos involuntarios; **no** son la referencia de corrección (esa
procede de soluciones cerradas y SciPy en los tests unitarios).
"""

from __future__ import annotations

import numpy as np

from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from tests.fixtures.problems import base_config, cov_from_vol_corr, frontier_result, make_problem

CASES = (
    (CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID),
    (CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID),
    (CostTreatment.GROSS, FrontierMethod.TARGET_RETURN_GRID),
    (CostTreatment.NET, FrontierMethod.TARGET_RETURN_GRID),
)


def snapshot() -> dict[str, dict[str, list[list[float]]]]:
    """Pesos, volatilidad y retornos de las cuatro fronteras de un problema fijo de 4 activos."""
    config = base_config()
    sigma = cov_from_vol_corr(
        [0.10, 0.15, 0.25, 0.20],
        [[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.3], [0.2, 0.4, 1, 0.5], [0.1, 0.3, 0.5, 1]],
    )
    problem = make_problem(
        np.array([0.05, 0.08, 0.12, 0.10]),
        sigma,
        [0.4, 0.3, 0.2, 0.1],
        config,
        universe_overrides={
            "MaxWeight": [0.5] * 4,
            "BuyCost": [20.0, 30.0, 40.0, 50.0],
            "SellCost": [60.0, 70.0, 80.0, 90.0],
        },
    )
    output: dict[str, dict[str, list[list[float]]]] = {}
    for treatment, method in CASES:
        result = frontier_result(problem, config, treatment, method)
        points = [p for p in result.points if p.weights is not None and p.metrics is not None]
        output[f"{treatment.value}:{method.value}"] = {
            "weights": [p.weights.tolist() for p in points],  # type: ignore[union-attr]
            "volatility": [[p.metrics.volatility] for p in points],  # type: ignore[union-attr]
            "return_gross": [[p.metrics.expected_return_gross] for p in points],  # type: ignore[union-attr]
            "return_net": [[p.metrics.expected_return_net or 0.0] for p in points],  # type: ignore[union-attr]
        }
    return output
