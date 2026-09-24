"""Correlación entre señales del screening y sensibilidad del score a sus pesos (M-2, B3).

Mide, sobre universos sintéticos reproducibles (semillas explícitas), (1) la correlación de rango
entre las señales normalizadas de los activos entrantes y de los mantenidos, (2) la parte real de
la varianza del score que aporta cada señal frente a su peso nominal (descomposición de varianza:
``cov(score, w_i·z_i) / var(score)``, que suma 1) y (3) cuánto cambia el ranking y la lista corta
al modificar los pesos. **No** cambia ninguna ponderación por defecto: solo mide.

Uso::

    .venv/Scripts/python benchmarks/scripts/screening_correlation.py --universe 200 --held 20
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

import numpy as np
import numpy.typing as npt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.candidates import (  # noqa: E402
    CandidateScreening,
    EligibilityFilter,
    UniverseSnapshot,
)
from portfolio_engine.config.candidate_config import SIGNAL_NAMES  # noqa: E402
from tests.fixtures.candidates import universe_problem  # noqa: E402
from tests.fixtures.problems import base_config  # noqa: E402

RISK_CLUSTER = (
    "marginal_risk_contribution",
    "diversification_contribution",
    "covariance_with_portfolio",
)
ORTHOGONAL = (
    "expected_alpha",
    "expected_utility_gain",
    "liquidity",
    "transaction_cost",
    "sector_fit",
)


def entrant_table(universe: int, held: int, seed: int, risk_aversion: float, weights=None):  # type: ignore[no-untyped-def]
    """Tabla de señales de los entrantes (y de los mantenidos) con los pesos dados."""
    config = base_config()
    if weights is not None:
        screening_weights = dataclasses.replace(config.candidates.screening_weights, **weights)
        config = dataclasses.replace(
            config,
            candidates=dataclasses.replace(config.candidates, screening_weights=screening_weights),
        )
    problem = universe_problem(universe, held, seed, config)
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    eligibility = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    positions = np.array(sorted(snapshot.index.indices_of(problem.state.asset_ids).tolist()))
    node_weights = np.array(
        [problem.state.weight_of(snapshot.index.asset_id_at(int(p))) for p in positions]
    )
    entrants = np.setdiff1d(eligibility.enterable.global_indices, positions)
    screening = CandidateScreening(config.candidates, config.returns.risk_free_rate)
    return screening.screen(
        snapshot, positions, node_weights, entrants, risk_aversion, 1.0 / held
    ), config


def spearman(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> float:
    ranks_a = np.argsort(np.argsort(a)).astype(np.float64)
    ranks_b = np.argsort(np.argsort(b)).astype(np.float64)
    return float(np.corrcoef(ranks_a, ranks_b)[0, 1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=int, default=200)
    parser.add_argument("--held", type=int, default=20)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 13, 17, 19])
    parser.add_argument("--risk-aversion", type=float, default=4.0)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    correlations = []
    shares = []
    for seed in args.seeds:
        result, config = entrant_table(args.universe, args.held, seed, args.risk_aversion)
        table = result.entrants
        z = table.normalized
        with np.errstate(invalid="ignore", divide="ignore"):  # señal constante: sin correlación
            correlations.append(np.corrcoef(z))
        weights = np.asarray(config.candidates.screening_weights.as_tuple())
        weights = weights / weights.sum()
        contribution = weights[:, None] * z
        score = contribution.sum(axis=0)
        variance = float(score.var())
        shares.append(
            [
                float(np.cov(score, contribution[i])[0, 1] / variance)
                for i in range(len(SIGNAL_NAMES))
            ]
        )
    mean_corr = np.mean(correlations, axis=0)
    print(
        f"Correlación (Pearson sobre percentiles = Spearman) media de {len(args.seeds)} semillas, "
        f"universo {args.universe}, cartera {args.held}, lambda {args.risk_aversion}"
    )
    header = "".join(f"{name[:9]:>10}" for name in SIGNAL_NAMES)
    print(f"{'':<30}{header}")
    for i, name in enumerate(SIGNAL_NAMES):
        print(
            f"{name:<30}" + "".join(f"{mean_corr[i, j]:>10.2f}" for j in range(len(SIGNAL_NAMES)))
        )
    print("\nPeso nominal vs. aportación real a la varianza del score (media de semillas):")
    default = np.asarray(base_config().candidates.screening_weights.as_tuple())
    for i, name in enumerate(SIGNAL_NAMES):
        print(
            f"  {name:<30} nominal {default[i] / default.sum():6.1%}"
            f"   varianza {np.mean([s[i] for s in shares]):6.1%}"
        )
    cluster = [SIGNAL_NAMES.index(n) for n in RISK_CLUSTER]
    print(
        f"  cluster de riesgo (3 señales)  nominal {default[cluster].sum() / default.sum():6.1%}"
        f"   varianza {np.mean([sum(s[i] for i in cluster) for s in shares]):6.1%}"
    )
    print(
        "\nSensibilidad del score/lista corta a los pesos "
        "(Spearman con el score por defecto; solapamiento top-8):"
    )
    scenarios: dict[str, dict[str, float]] = {
        "riesgo: solo marginal (div=cov=0)": {
            "diversification_contribution": 0.0,
            "covariance_with_portfolio": 0.0,
        },
        "riesgo x0 (las 3 a 0)": dict.fromkeys(RISK_CLUSTER, 0.0),
        "conjunto ortogonal (alpha, dU, liq, coste, sector)": {
            n: (getattr(base_config().candidates.screening_weights, n) if n in ORTHOGONAL else 0.0)
            for n in SIGNAL_NAMES
        },
        "pesos iguales (todos 1)": dict.fromkeys(SIGNAL_NAMES, 1.0),
    }
    for name in SIGNAL_NAMES:
        base = getattr(base_config().candidates.screening_weights, name)
        scenarios[f"{name} x1.5"] = {name: base * 1.5}
        scenarios[f"{name} x0.5"] = {name: base * 0.5}
    for label, weights in scenarios.items():
        spear, overlap = [], []
        for seed in args.seeds:
            base_result, _ = entrant_table(args.universe, args.held, seed, args.risk_aversion)
            alt_result, _ = entrant_table(
                args.universe, args.held, seed, args.risk_aversion, weights
            )
            a, b = base_result.entrants.score, alt_result.entrants.score
            spear.append(spearman(a, b))
            top_a, top_b = set(np.argsort(-a)[:8].tolist()), set(np.argsort(-b)[:8].tolist())
            overlap.append(len(top_a & top_b))
        print(
            f"  {label:<52} spearman {np.mean(spear):5.3f}"
            f"   top-8 comunes {np.mean(overlap):4.1f}/8"
        )


if __name__ == "__main__":
    main()
