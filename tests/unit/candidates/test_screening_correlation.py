"""CAN-010, CAN-011 (M-2 de AUDIT_BLOCK_3): redundancia de señales y sensibilidad del score.

Tres señales de riesgo (``marginal_risk_contribution``, ``diversification_contribution`` y
``covariance_with_portfolio``) miden casi lo mismo y ``expected_utility_gain`` ya contiene alpha y
riesgo. No es un error del screening (los pesos son configurables y por defecto no se han
cambiado), pero los pesos **no** son influencias independientes. Estos tests fijan la medida
(semilla explícita, universo de 200 activos, cartera de 20, λ = 4) para que un cambio en la
definición de las señales obligue a revisar la documentación de ``REMEDIATION_BLOCK_3.md``.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.candidates import CandidateScreening, EligibilityFilter, UniverseSnapshot
from portfolio_engine.config.candidate_config import SIGNAL_NAMES
from tests.fixtures.candidates import universe_problem
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

RISK = ("marginal_risk_contribution", "diversification_contribution", "covariance_with_portfolio")
ROW = {name: SIGNAL_NAMES.index(name) for name in SIGNAL_NAMES}
SEEDS = (7, 11, 13)
SHORTLIST = 8
LAM = 4.0


def _entrants(seed: int, **weights: float):  # type: ignore[no-untyped-def]
    config = base_config()
    if weights:
        screening = dataclasses.replace(config.candidates.screening_weights, **weights)
        config = dataclasses.replace(
            config, candidates=dataclasses.replace(config.candidates, screening_weights=screening)
        )
    problem = universe_problem(200, 20, seed, config)
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    eligibility = EligibilityFilter(config.candidates, config.constraints).apply(
        snapshot, problem.state, problem.spec
    )
    held = np.sort(snapshot.index.indices_of(problem.state.asset_ids))
    weights_held = np.array(
        [problem.state.weight_of(snapshot.index.asset_id_at(int(p))) for p in held]
    )
    entrants = np.setdiff1d(eligibility.enterable.global_indices, held)
    screening = CandidateScreening(config.candidates, config.returns.risk_free_rate)
    return screening.screen(snapshot, held, weights_held, entrants, LAM, 1.0 / 20).entrants


def _top(score: np.ndarray) -> set[int]:  # type: ignore[type-arg]
    return set(np.argsort(-score, kind="stable")[:SHORTLIST].tolist())


def test_the_three_risk_signals_are_highly_rank_correlated() -> None:
    """Medido: 0,93-0,97 entre las tres (media de 5 semillas, ``REMEDIATION_BLOCK_3.md``)."""
    z = _entrants(7).normalized
    pairs = [(a, b) for i, a in enumerate(RISK) for b in RISK[i + 1 :]]
    correlations = [float(np.corrcoef(z[ROW[a]], z[ROW[b]])[0, 1]) for a, b in pairs]
    assert min(correlations) > 0.85


def test_utility_gain_overlaps_with_both_alpha_and_risk() -> None:
    z = _entrants(7).normalized
    alpha = float(np.corrcoef(z[ROW["expected_alpha"]], z[ROW["expected_utility_gain"]])[0, 1])
    risk = float(
        np.corrcoef(z[ROW["marginal_risk_contribution"]], z[ROW["expected_utility_gain"]])[0, 1]
    )
    assert alpha > 0.6 and risk > 0.4


def test_the_score_is_exactly_the_weighted_average_of_the_normalized_signals() -> None:
    """Sensibilidad exacta: ``score = Σ w_i·z_i / Σ w_i`` (oráculo desde ``normalized``)."""
    table = _entrants(7)
    weights = np.asarray(base_config().candidates.screening_weights.as_tuple())
    expected = (weights / weights.sum()) @ np.nan_to_num(table.normalized, nan=0.5)
    assert table.score == pytest.approx(expected, abs=1e-12)
    # escalar todos los pesos no cambia nada: solo cuentan los pesos relativos
    scaled = _entrants(7, **{n: v * 3 for n, v in zip(SIGNAL_NAMES, weights.tolist(), strict=True)})
    assert scaled.score == pytest.approx(table.score, abs=1e-12)


@pytest.mark.parametrize("name", SIGNAL_NAMES)
@pytest.mark.parametrize("factor", [0.5, 1.5])
def test_changing_one_weight_by_half_barely_moves_the_shortlist(name: str, factor: float) -> None:
    base_weight = getattr(base_config().candidates.screening_weights, name)
    for seed in SEEDS:
        base = _top(_entrants(seed).score)
        changed = _top(_entrants(seed, **{name: base_weight * factor}).score)
        assert len(base & changed) >= 5  # medido: 7,0-8,0 de 8 en promedio


def test_removing_the_whole_risk_cluster_does_change_the_shortlist() -> None:
    """El grupo de riesgo actúa como una señal de peso relevante: quitarlo sí cambia la lista."""
    common = []
    for seed in SEEDS:
        base = _top(_entrants(seed).score)
        without = _top(_entrants(seed, **dict.fromkeys(RISK, 0.0)).score)
        common.append(len(base & without))
    assert np.mean(common) <= 6.0  # medido: 3,0-4,4 de 8
