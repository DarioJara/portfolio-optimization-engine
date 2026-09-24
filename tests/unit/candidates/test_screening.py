"""CAN-009, CAN-010, CAN-011, CAN-012: screening multiseñal vectorizado.

Los valores esperados se construyen aquí **explícitamente** (carteras ampliadas con el activo
candidato, varianzas por producto matricial), sin usar las fórmulas cerradas del motor.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import numpy as np
import pytest

from portfolio_engine.candidates import (
    CandidateScreening,
    UniverseSnapshot,
    average_rank_percentile,
)
from portfolio_engine.config import ScreeningWeights
from portfolio_engine.config.candidate_config import SIGNAL_NAMES
from portfolio_engine.exceptions import CandidateError
from portfolio_engine.models.enums import MissingSignalPolicy, ScreeningNormalization
from tests.conftest import REPO_ROOT
from tests.fixtures.candidates import corr_matrix, with_candidates
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem

pytestmark = pytest.mark.unit

N = 12
LAMBDA = 4.0
HELD = [0, 1, 2]
WEIGHTS = np.array([0.5, 0.3, 0.2])
POSITION_WEIGHT = 1.0 / 3.0


def _scenario(config, **overrides):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(21)
    factor = rng.normal(size=(N, N))
    vols = np.round(rng.uniform(0.12, 0.30, N), 3)
    sigma = cov_from_vol_corr(vols, np.corrcoef(factor @ factor.T + N * np.eye(N)))
    mu = np.round(rng.uniform(0.03, 0.14, N), 4)
    current = [0.5, 0.3, 0.2] + [0.0] * (N - 3)
    universe = {
        "MaxWeight": [1.0] * N,
        "ADV": [float(v) for v in np.round(rng.uniform(1e5, 5e6, N), 0)],
        "BuyCost": [float(v) for v in np.round(rng.uniform(2, 40, N), 1)],
        "SellCost": [float(v) for v in np.round(rng.uniform(2, 40, N), 1)],
        **overrides,
    }
    problem = make_problem(mu, sigma, current, config, universe_overrides=universe)
    snapshot = UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)
    return problem, snapshot, mu, sigma


def _screen(config, snapshot, entrants=None):  # type: ignore[no-untyped-def]
    engine = CandidateScreening(config.candidates, config.returns.risk_free_rate)
    entrants = np.arange(3, N) if entrants is None else np.asarray(entrants)
    return engine.screen(snapshot, np.array(HELD), WEIGHTS, entrants, LAMBDA, POSITION_WEIGHT)


def _sector_exposure(problem, weights, holdings):  # type: ignore[no-untyped-def]
    exposure: dict[str, float] = {}
    for position, weight in zip(holdings, weights, strict=True):
        sector = problem.universe.get(f"A{position:03d}").sector
        exposure[sector] = exposure.get(sector, 0.0) + float(weight)
    return exposure


def _explicit_entrant(problem, mu, sigma, config, j):  # type: ignore[no-untyped-def]
    """Señales con dirección de un entrante ``j`` construyendo la cartera ampliada."""
    m = POSITION_WEIGHT
    base = sigma[np.ix_(HELD, HELD)]
    var_old = float(WEIGHTS @ base @ WEIGHTS)
    extended = [*HELD, j]
    w_new = np.append((1.0 - m) * WEIGHTS, m)
    var_new = float(w_new @ sigma[np.ix_(extended, extended)] @ w_new)
    d_var = var_new - var_old
    d_utility = float(mu[extended] @ w_new - mu[HELD] @ WEIGHTS) - LAMBDA * d_var
    cov = float(sigma[j, HELD] @ WEIGHTS)
    asset = problem.universe.get(f"A{j:03d}")
    exposure = _sector_exposure(problem, WEIGHTS, HELD).get(asset.sector, 0.0)
    return np.array(
        [
            mu[j],
            -d_var,
            -cov / (np.sqrt(sigma[j, j]) * np.sqrt(var_old)),
            -cov,
            d_utility,
            (mu[j] - config.returns.risk_free_rate) / np.sqrt(sigma[j, j]),
            np.log(asset.adv),
            -asset.buy_cost / 1e4,
            1.0 - exposure,
        ]
    )


def _explicit_held(problem, mu, sigma, config, k):  # type: ignore[no-untyped-def]
    """Señales con dirección del activo mantenido ``k`` frente al resto renormalizado."""
    others = [i for i in range(len(HELD)) if i != k]
    rest = WEIGHTS[others] / WEIGHTS[others].sum()
    rest_ids = [HELD[i] for i in others]
    var_rest = float(rest @ sigma[np.ix_(rest_ids, rest_ids)] @ rest)
    var_all = float(WEIGHTS @ sigma[np.ix_(HELD, HELD)] @ WEIGHTS)
    d_var = var_all - var_rest
    d_utility = float(mu[HELD] @ WEIGHTS - mu[rest_ids] @ rest) - LAMBDA * d_var
    a = HELD[k]
    cov_rest = float(sigma[a, rest_ids] @ rest)
    asset = problem.universe.get(f"A{a:03d}")
    exposure_rest = _sector_exposure(problem, rest, rest_ids).get(asset.sector, 0.0)
    return np.array(
        [
            mu[a],
            -d_var,
            -cov_rest / (np.sqrt(sigma[a, a]) * np.sqrt(var_rest)),
            -cov_rest,
            d_utility,
            (mu[a] - config.returns.risk_free_rate) / np.sqrt(sigma[a, a]),
            np.log(asset.adv),
            asset.sell_cost / 1e4,
            1.0 - exposure_rest,
        ]
    )


def test_signals_equal_the_explicit_portfolio_construction() -> None:
    config = base_config()
    problem, snapshot, mu, sigma = _scenario(config)
    result = _screen(config, snapshot)
    for column, j in enumerate(result.entrants.positions.tolist()):
        expected = _explicit_entrant(problem, mu, sigma, config, j)
        assert np.allclose(result.entrants.raw[:, column], expected, rtol=1e-9, atol=1e-12), j
    for column in range(len(HELD)):
        expected = _explicit_held(problem, mu, sigma, config, column)
        assert np.allclose(result.held.raw[:, column], expected, rtol=1e-9, atol=1e-12), column


def test_average_rank_percentile_averages_ties() -> None:
    ranks = average_rank_percentile(np.array([10.0, 20.0, 20.0, 30.0]))
    assert np.allclose(ranks, [0.0, 0.5, 0.5, 1.0])
    assert average_rank_percentile(np.array([7.0])).tolist() == [0.5]
    assert average_rank_percentile(np.array([1.0, 1.0, 1.0])).tolist() == [0.5, 0.5, 0.5]
    assert average_rank_percentile(np.empty(0)).size == 0


@pytest.mark.parametrize("signal", SIGNAL_NAMES)
def test_a_single_weighted_signal_orders_assets_by_its_own_direction(signal: str) -> None:
    """Con todos los pesos a 0 salvo uno, el score ordena por esa señal (dirección incluida)."""
    base = base_config()
    one_hot = ScreeningWeights(**{name: float(name == signal) for name in SIGNAL_NAMES})
    config = with_candidates(base, screening_weights=one_hot)
    problem, snapshot, mu, sigma = _scenario(config)
    result = _screen(config, snapshot)
    expected = np.array(
        [
            _explicit_entrant(problem, mu, sigma, config, j)[SIGNAL_NAMES.index(signal)]
            for j in result.entrants.positions.tolist()
        ]
    )
    order_by_score = np.argsort(result.entrants.score, kind="stable")
    order_by_signal = np.argsort(expected, kind="stable")
    assert order_by_score.tolist() == order_by_signal.tolist()


def test_signal_directions_follow_the_specification() -> None:
    """Mayor es mejor tras la dirección: alpha↑, riesgo/covarianza/coste↓, utilidad↑, liquidez↑."""
    config = base_config()
    problem, snapshot, mu, _ = _scenario(config)
    table = _screen(config, snapshot).entrants
    raw = table.raw
    positions = table.positions
    assert np.array_equal(raw[SIGNAL_NAMES.index("expected_alpha")], mu[positions])
    buys = np.array([problem.universe.get(f"A{p:03d}").buy_cost for p in positions]) / 1e4
    assert np.allclose(raw[SIGNAL_NAMES.index("transaction_cost")], -buys)
    adv = np.array([problem.universe.get(f"A{p:03d}").adv for p in positions])
    assert np.allclose(raw[SIGNAL_NAMES.index("liquidity")], np.log(adv))


def test_changing_signal_weights_changes_the_ranking() -> None:
    """CAN-011: no es solo alpha/covarianza; otro peso cambia la preselección."""
    base = base_config()
    outcomes = set()
    for signal in SIGNAL_NAMES:
        one_hot = ScreeningWeights(**{name: float(name == signal) for name in SIGNAL_NAMES})
        config = with_candidates(base, screening_weights=one_hot)
        _, snapshot, _, _ = _scenario(config)
        table = _screen(config, snapshot).entrants
        outcomes.add(int(table.positions[np.argmax(table.score)]))
    assert len(outcomes) > 2  # las nueve señales no producen el mismo ganador


def _adversarial(config):  # type: ignore[no-untyped-def]
    """Tres mantenidos; X = mayor alpha pero casi colineal; Y = menor alpha y diversifica."""
    n = 8
    vols = [0.20, 0.20, 0.20, 0.20, 0.15, 0.30, 0.30, 0.30]
    mu = np.array([0.08, 0.08, 0.08, 0.12, 0.10, 0.02, 0.02, 0.02])
    corr = corr_matrix(n, 0.3, **{f"{i}_{j}": 0.6 for i in range(3) for j in range(i + 1, 3)})
    for held in range(3):
        corr[3, held] = corr[held, 3] = 0.95  # X: concentración
        corr[4, held] = corr[held, 4] = 0.0  # Y: diversificador
    corr[3, 4] = corr[4, 3] = 0.0
    sigma = cov_from_vol_corr(vols, corr)
    problem = make_problem(
        mu, sigma, [1 / 3] * 3 + [0.0] * 5, config, universe_overrides={"MaxWeight": [1.0] * n}
    )
    return problem, UniverseSnapshot.build(problem.risk_model, problem.universe, problem.costs)


def test_alpha_only_ranking_would_pick_the_concentrating_asset_but_the_screening_does_not() -> None:
    """Caso adversarial: por alpha individual saldría X (colineal con la cartera); el score
    multiseñal prefiere Y, que diversifica (menor covarianza y correlación con la cartera)."""
    config = base_config()
    _, snapshot = _adversarial(config)
    engine = CandidateScreening(config.candidates, config.returns.risk_free_rate)
    result = engine.screen(
        snapshot, np.array([0, 1, 2]), np.full(3, 1 / 3), np.arange(3, 8), LAMBDA, 1 / 3
    )
    table = result.entrants
    alpha_top = int(table.positions[np.argmax(table.raw[SIGNAL_NAMES.index("expected_alpha")])])
    composite_top = int(table.positions[np.argmax(table.score)])
    assert alpha_top == 3  # X
    assert composite_top == 4  # Y
    assert (
        table.diversification[list(table.positions).index(4)]
        > table.diversification[list(table.positions).index(3)]
    )


def test_zscore_normalization_has_zero_mean_and_unit_deviation_per_signal() -> None:
    config = with_candidates(base_config(), normalization=ScreeningNormalization.ZSCORE)
    _, snapshot, _, _ = _scenario(config)
    normalized = _screen(config, snapshot).entrants.normalized
    assert np.allclose(normalized.mean(axis=1), 0.0, atol=1e-12)
    assert np.allclose(normalized.std(axis=1), 1.0)


def test_rank_normalization_is_bounded_in_the_unit_interval() -> None:
    config = base_config()
    _, snapshot, _, _ = _scenario(config)
    normalized = _screen(config, snapshot).entrants.normalized
    assert normalized.min() >= 0.0 and normalized.max() <= 1.0


# -------------------------------------------------------------------------- datos ausentes


def _with_missing_adv(policy: MissingSignalPolicy):  # type: ignore[no-untyped-def]
    config = with_candidates(base_config(), missing_signal_policy=policy)
    problem, snapshot, _, _ = _scenario(config)
    adv = np.array(snapshot.adv)
    adv[5] = np.nan
    snapshot = dataclasses.replace(snapshot, adv=adv)
    return config, problem, snapshot


def test_missing_signal_neutral_policy_imputes_and_records_it() -> None:
    config, _, snapshot = _with_missing_adv(MissingSignalPolicy.NEUTRAL)
    table = _screen(config, snapshot).entrants
    item = list(table.positions).index(5)
    liquidity = SIGNAL_NAMES.index("liquidity")
    assert table.missing[liquidity, item] and table.imputed[liquidity, item]
    assert table.missing_names(item) == ("liquidity",)
    assert not table.excluded[item] and np.isfinite(table.score[item])
    assert not table.imputed[:, [i for i in range(len(table.positions)) if i != item]].any()


def test_missing_signal_exclude_policy_drops_the_asset() -> None:
    config, _, snapshot = _with_missing_adv(MissingSignalPolicy.EXCLUDE)
    table = _screen(config, snapshot).entrants
    item = list(table.positions).index(5)
    assert table.excluded[item] and np.isnan(table.score[item])
    assert not np.isnan(np.delete(table.score, item)).any()


def test_missing_signal_error_policy_raises() -> None:
    config, _, snapshot = _with_missing_adv(MissingSignalPolicy.ERROR)
    with pytest.raises(CandidateError, match="ausentes"):
        _screen(config, snapshot)


def test_a_missing_signal_with_zero_weight_does_not_matter() -> None:
    """Una señal con peso 0 no interviene: su ausencia no excluye ni obliga a imputar."""
    weights = dataclasses.replace(base_config().candidates.screening_weights, liquidity=0.0)
    config = with_candidates(
        base_config(), missing_signal_policy=MissingSignalPolicy.ERROR, screening_weights=weights
    )
    _, _, snapshot = _with_missing_adv(MissingSignalPolicy.ERROR)
    table = _screen(config, snapshot).entrants
    assert not table.excluded.any() and not table.imputed.any()
    assert np.isfinite(table.score).all()


def test_screening_is_deterministic_and_does_not_mutate_inputs() -> None:
    config = base_config()
    _, snapshot, _, _ = _scenario(config)
    first, second = _screen(config, snapshot), _screen(config, snapshot)
    assert np.array_equal(first.entrants.score, second.entrants.score)
    assert np.array_equal(first.held.score, second.held.score)


def test_screening_is_vectorized_over_assets() -> None:
    """CAN-012: el único bucle es sobre las nueve señales, nunca sobre los activos."""
    path = REPO_ROOT / "portfolio_engine" / "candidates" / "screening.py"
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    loops = [node for node in ast.walk(tree) if isinstance(node, ast.For)]
    assert len(loops) == 1
    assert ast.unparse(loops[0].iter) == "range(raw.shape[0])"
