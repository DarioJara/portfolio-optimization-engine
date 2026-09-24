"""CAN-001, CAN-002, CAN-016, CAN-018, CAN-020, CAN-021, CAN-022, OPT-002 (parte de candidatos).

Contrato: ``generate_candidate_compositions`` devuelve varias composiciones que parten de la
cartera actual; cada una es reconstruible desde su historial de movimientos; se respetan
elegibilidad, política de restringidos, límites y cardinalidad.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.candidates import CandidateContext, CandidateEngine
from portfolio_engine.candidates.composition_hash import composition_hash_of
from portfolio_engine.exceptions import CandidateError
from portfolio_engine.frontiers import QPCompositionEvaluator
from portfolio_engine.models.composition import CandidateComposition
from portfolio_engine.models.enums import (
    CandidateOrigin,
    EvaluationMode,
    MoveKind,
    RestrictedExistingPositionPolicy,
)
from tests.fixtures.candidates import (
    context_of,
    corr_matrix,
    exact_net_utility,
    random_problem,
    search,
    with_candidates,
)
from tests.fixtures.problems import (
    base_config,
    cov_from_vol_corr,
    make_problem,
    policy_config,
    restricted_universe,
    spec_with,
)

pytestmark = pytest.mark.unit

N = 12
HELD = [0, 1, 2, 3]
Policy = RestrictedExistingPositionPolicy


def _config(**changes):  # type: ignore[no-untyped-def]
    defaults = {"max_evaluations": 80, "max_candidates": 8, "refinement_iterations": 8}
    return base_config(candidates={**defaults, **changes})


def _run(config=None, seed=5, **kwargs):  # type: ignore[no-untyped-def]
    config = config or _config()
    problem = random_problem(N, HELD, seed, config, **kwargs)
    return config, problem, search(config, problem)


def test_generates_several_compositions_starting_from_the_current_one() -> None:
    config, problem, result = _run()
    compositions = result.compositions
    assert len(compositions) > 1  # contrato: nunca una sola composición
    reference = compositions[0]
    assert reference.is_reference and reference.origin is CandidateOrigin.REFERENCE
    assert reference.composition_hash == problem.state.composition_hash
    assert reference.asset_set == frozenset(problem.state.asset_ids)
    assert reference.parent_composition_id is None and reference.swap_history == ()
    assert len(compositions) <= config.candidates.max_candidates
    others = compositions[1:]
    assert others and all(c.asset_set != reference.asset_set for c in others)
    assert all(len(c.asset_ids) == len(HELD) for c in compositions)


def test_generate_candidate_compositions_returns_the_same_list_as_search() -> None:
    config, problem, result = _run()
    engine = CandidateEngine(config)
    listed = engine.generate_candidate_compositions(
        problem.state.composition(), context_of(problem)
    )
    assert isinstance(listed, list) and len(listed) > 1
    assert [c.composition_hash for c in listed] == [c.composition_hash for c in result.compositions]


def test_each_candidate_is_reachable_from_the_current_composition_by_its_swap_history() -> None:
    """Se reconstruye la composición aplicando los movimientos, sin usar ningún dato del motor."""
    _, problem, result = _run()
    current = set(problem.state.asset_ids)
    for candidate in result.compositions[1:]:
        state = set(current)
        hashes = [composition_hash_of(state)]
        for move in candidate.swap_history:
            assert set(move.out_asset_ids) <= state and not set(move.in_asset_ids) & state
            state = (state - set(move.out_asset_ids)) | set(move.in_asset_ids)
            hashes.append(composition_hash_of(state))
        assert state == set(candidate.asset_ids)
        assert (
            candidate.parent_composition_id == hashes[-2]
        )  # padre = composición anterior del camino
        assert candidate.swap_history and all(
            m.kind is MoveKind.SWAP for m in candidate.swap_history
        )
        assert candidate.composition_hash == hashes[-1]


def test_candidates_are_distinct_sets_and_reorderings_do_not_count() -> None:
    _, _, result = _run()
    hashes = [c.composition_hash for c in result.compositions]
    assert len(hashes) == len(set(hashes))
    sets = {frozenset(c.asset_ids) for c in result.compositions}
    assert len(sets) == len(hashes)
    for candidate in result.compositions:
        assert list(candidate.asset_ids) == sorted(candidate.asset_ids)
        assert candidate.global_indices.tolist() == sorted(candidate.global_indices.tolist())
        assert candidate.composition_id == composition_hash_of(reversed(candidate.asset_ids))


def test_estimates_are_labelled_as_estimates_not_optimized_results() -> None:
    _, _, result = _run()
    assert "ESTIMATES_ARE_NOT_OPTIMIZED_RESULTS" in result.diagnostics.notes
    for candidate in result.compositions:
        assert candidate.estimates and all(
            e.basis is EvaluationMode.PROJECTED_WEIGHTS for e in candidate.estimates
        )
        assert (
            candidate.estimated_turnover is not None
            and candidate.estimated_transaction_cost is not None
        )
        assert (
            0.0 <= candidate.estimated_turnover <= 1.0
            and candidate.estimated_transaction_cost >= 0.0
        )
    alternatives = result.compositions[1:]
    # el score heurístico (prior de screening) y la mejora de utilidad son magnitudes distintas
    assert any(not np.isclose(c.candidate_score, c.estimated_utility_gain) for c in alternatives)
    assert all(
        c.candidate_score == pytest.approx(sum(m.screening_prior for m in c.swap_history))
        for c in alternatives
    )


def test_estimated_gain_is_relative_to_the_current_portfolio_utility() -> None:
    _, _problem, result = _run()
    reference = result.compositions[0]
    # rebalancear la cartera actual nunca es peor que dejarla como está
    assert reference.estimated_utility_gain >= -1e-12
    assert reference.best_risk_aversion is not None
    assert {e.risk_aversion for e in reference.estimates} == set(
        base_config().candidates.utility_risk_aversions
    )


def test_all_risk_profiles_contribute_candidates() -> None:
    config, _, result = _run(_config(max_candidates=12))
    profiles = {c.best_risk_aversion for c in result.compositions[1:]}
    assert len(profiles) > 1
    assert profiles <= set(config.candidates.utility_risk_aversions)
    for candidate in result.compositions[1:]:
        assert {e.risk_aversion for e in candidate.estimates} <= set(
            config.candidates.utility_risk_aversions
        )


# --------------------------------------------------------------------- elegibilidad y política


def test_ineligible_illiquid_and_restricted_assets_never_enter() -> None:
    eligible = [True] * N
    eligible[5] = False
    liquid: list[bool | None] = [True] * N
    liquid[6] = False
    restricted = [False] * N
    restricted[7] = True
    overrides = {
        "EligibleFlag": eligible,
        "LiquidityFlag": liquid,
        "RestrictedAssetFlag": restricted,
    }
    _, _, result = _run(universe_overrides=overrides)
    entered = {a for c in result.compositions for a in c.asset_ids} - {f"A{i:03d}" for i in HELD}
    assert entered and not entered & {"A005", "A006", "A007"}


def test_freeze_weight_asset_never_disappears_from_a_candidate() -> None:
    config = policy_config(_config(), Policy.FREEZE_WEIGHT)
    _, _problem, result = _run(config, universe_overrides=restricted_universe(N, [1]))
    assert len(result.compositions) > 1
    assert all("A001" in c.asset_ids for c in result.compositions)
    removed = {a for c in result.compositions[1:] for m in c.swap_history for a in m.out_asset_ids}
    assert "A001" not in removed


def test_force_liquidate_asset_leaves_every_alternative_but_stays_in_the_reference() -> None:
    config = policy_config(_config(), Policy.FORCE_LIQUIDATE)
    _, _, result = _run(config, universe_overrides=restricted_universe(N, [1]))
    reference, alternatives = result.compositions[0], result.compositions[1:]
    assert "A001" in reference.asset_ids  # la referencia es la cartera actual (peso 0 al optimizar)
    assert alternatives and all("A001" not in c.asset_ids for c in alternatives)
    assert all(len(c.asset_ids) == len(HELD) for c in alternatives)  # se repone el tamaño objetivo
    # la composición sin A001 y con tamaño 3 se completa con un ADD: los movimientos lo reflejan
    assert any(m.kind is MoveKind.ADD for c in alternatives for m in c.swap_history)


def test_hold_or_reduce_asset_may_be_swapped_out_but_not_bought() -> None:
    config = policy_config(_config(), Policy.HOLD_OR_REDUCE)
    _, _, result = _run(config, universe_overrides=restricted_universe(N, [1, 9]))
    assert len(result.compositions) > 1
    entered = {a for c in result.compositions for a in c.asset_ids} - {f"A{i:03d}" for i in HELD}
    assert "A009" not in entered  # restringido no mantenido: nunca se incorpora


def test_investment_universe_of_the_portfolio_is_respected() -> None:
    allowed = tuple(f"A{i:03d}" for i in (0, 1, 2, 3, 4, 8, 10))
    config = _config()
    _, _, result = _run(config, spec=spec_with(investment_universe=allowed))
    used = {a for c in result.compositions for a in c.asset_ids}
    assert used <= set(allowed)


# ----------------------------------------------------------------------------- límites


def test_max_new_assets_and_max_swaps_are_respected_and_rejections_explained() -> None:
    config = _config(swap_orders=(1, 2, 3), max_new_assets=1, max_swaps=1)
    _, problem, result = _run(config)
    current = set(problem.state.asset_ids)
    for candidate in result.compositions:
        assert len(set(candidate.asset_ids) - current) <= 1
        assert len(current - set(candidate.asset_ids)) <= 1
    reasons = dict(result.diagnostics.rejections_by_reason)
    assert reasons.get("MAX_NEW_ASSETS", 0) > 0 and reasons.get("MAX_SWAPS", 0) > 0
    recorded = {
        r for rejected in result.diagnostics.rejected_compositions for r in rejected.reasons
    }
    assert {"MAX_NEW_ASSETS", "MAX_SWAPS"} <= recorded
    assert all(
        rejected.stage == "GENERATION"
        for rejected in result.diagnostics.rejected_compositions
        if set(rejected.reasons) <= {"MAX_NEW_ASSETS", "MAX_SWAPS"}
    )


def test_zero_new_assets_leaves_only_the_reference() -> None:
    config = _config(max_new_assets=0)
    _, _, result = _run(config)
    assert [c.origin for c in result.compositions] == [CandidateOrigin.REFERENCE]


def test_target_size_larger_than_the_current_uses_add_moves() -> None:
    config = _config()
    _, _problem, result = _run(config, spec=spec_with(target_portfolio_size=5))
    reference, alternatives = result.compositions[0], result.compositions[1:]
    assert len(reference.asset_ids) == 4  # la referencia es la cartera actual
    assert alternatives and all(len(c.asset_ids) == 5 for c in alternatives)
    assert all(
        m.kind in (MoveKind.ADD, MoveKind.SWAP) for c in alternatives for m in c.swap_history
    )
    assert all(
        c.swap_history[0].kind is MoveKind.ADD for c in alternatives
    )  # primero se corrige el tamaño


def test_target_size_smaller_than_the_current_uses_drop_moves() -> None:
    _, _, result = _run(spec=spec_with(target_portfolio_size=3))
    alternatives = result.compositions[1:]
    assert alternatives and all(len(c.asset_ids) == 3 for c in alternatives)
    assert all(c.swap_history[0].kind is MoveKind.DROP for c in alternatives)


def test_infeasible_cardinality_returns_only_the_reference_with_the_cause() -> None:
    """MaxWeight 0.6 con K = 1 no alcanza el presupuesto: ninguna composición es posible."""
    _, _, result = _run(spec=spec_with(target_portfolio_size=1))
    assert [c.origin for c in result.compositions] == [CandidateOrigin.REFERENCE]
    notes = result.diagnostics.notes
    assert "ONLY_REFERENCE_COMPOSITION_POSSIBLE" in notes
    assert any("CARDINALITY_MAX_WEIGHTS_BELOW_BUDGET" in note for note in notes)
    assert result.diagnostics.total_evaluated == 0  # no se inventa ni evalúa nada


def test_no_alternative_when_no_other_asset_is_eligible() -> None:
    eligible = [i in HELD for i in range(N)]
    _, _, result = _run(universe_overrides={"EligibleFlag": eligible})
    assert [c.origin for c in result.compositions] == [CandidateOrigin.REFERENCE]
    assert all(reason == "NO_NEIGHBORS" for _, reason in result.diagnostics.stop_reasons)


def test_current_composition_must_match_the_context() -> None:
    config, problem, _ = _run()
    other = random_problem(N, [4, 5, 6, 7], 5, config)
    with pytest.raises(CandidateError, match="no coincide"):
        CandidateEngine(config).search(other.state.composition(), context_of(problem))


# ------------------------------------------------------------------------ determinismo


def test_generation_is_deterministic() -> None:
    config = _config()
    problem = random_problem(N, HELD, 5, config)
    first, second = search(config, problem), search(config, problem)
    assert [c.composition_hash for c in first.compositions] == [
        c.composition_hash for c in second.compositions
    ]
    for a, b in zip(first.compositions, second.compositions, strict=True):
        assert (
            a.estimated_utility_gain == b.estimated_utility_gain
            and a.candidate_score == b.candidate_score
        )
        assert [e.utility for e in a.estimates] == [e.utility for e in b.estimates]
    assert [s.best_utility_gain for s in first.diagnostics.stages] == [
        s.best_utility_gain for s in second.diagnostics.stages
    ]


def test_exploration_is_the_only_seed_dependent_component() -> None:
    def hashes(seed: int, explore: float):  # type: ignore[no-untyped-def]
        from portfolio_engine.config import ExplorationMix

        exploit_only = 0.0 if explore else 1.0
        config = dataclasses.replace(
            _config(shortlist_in=3, exploration=ExplorationMix(exploit_only, 0.0, explore or 0.0)),
            random_seed=seed,
        )
        problem = random_problem(N, HELD, 5, config)
        return [c.composition_hash for c in search(config, problem).compositions]

    assert hashes(1, 0.0) == hashes(2, 0.0)  # sin exploración el resultado no depende de la semilla
    assert hashes(1, 1.0) == hashes(1, 1.0)  # con exploración es reproducible para una semilla
    assert hashes(1, 1.0) != hashes(2, 1.0)  # y depende de ella


# ---------------------------------------------------------------------------- diagnósticos


def test_diagnostics_reconstruct_the_search() -> None:
    config, problem, result = _run()
    diagnostics = result.diagnostics
    assert diagnostics.portfolio_id == problem.portfolio_id and not diagnostics.cold_start
    algorithms = {stage.algorithm for stage in diagnostics.stages}
    assert CandidateOrigin.BEAM_SEARCH in algorithms
    assert CandidateOrigin.LOCAL_SEARCH in algorithms  # local_search_starts > 0
    assert {lam for _, lam in [(0, s.risk_aversion) for s in diagnostics.stages]} == set(
        config.candidates.utility_risk_aversions
    )
    assert len(diagnostics.stop_reasons) == len(config.candidates.utility_risk_aversions)
    assert diagnostics.total_evaluated == sum(s.evaluated for s in diagnostics.stages) > 0
    assert diagnostics.total_generated >= diagnostics.total_evaluated
    assert diagnostics.search_time > 0 and diagnostics.total_time >= diagnostics.search_time
    counts = dict(diagnostics.eligibility_counts)
    assert counts["HELD"] == len(HELD) and sum(counts.values()) == N
    assert len(diagnostics.asset_records) == N
    selected = {r.asset_id for r in diagnostics.asset_records if r.selected_for_optimization}
    assert selected == {a for c in result.compositions for a in c.asset_ids}
    for record in diagnostics.asset_records:
        assert record.selected_for_optimization or record.rejection_reason


def test_beam_survivors_per_level_are_bounded_by_the_beam_width() -> None:
    config = _config(beam_width=3)
    _, _, result = _run(config)
    beam_stages = [
        s for s in result.diagnostics.stages if s.algorithm is CandidateOrigin.BEAM_SEARCH
    ]
    assert beam_stages and all(s.survivors <= 3 for s in beam_stages)
    assert any(s.survivors == 3 for s in beam_stages)  # el haz mantiene B composiciones distintas


def test_budget_and_stop_reasons_are_reported() -> None:
    config = _config(max_evaluations=6)
    _, _, result = _run(config)
    assert any(reason == "BUDGET_EXHAUSTED" for _, reason in result.diagnostics.stop_reasons)
    beam_evaluations = [
        sum(
            s.evaluated
            for s in result.diagnostics.stages
            if s.risk_aversion == lam and s.algorithm is CandidateOrigin.BEAM_SEARCH
        )
        for lam in config.candidates.utility_risk_aversions
    ]
    assert all(count <= 6 for count in beam_evaluations)


# --------------------------------------------------------------------------- arranque en frío


def test_cold_start_seeds_from_the_screening_without_turnover_or_cost() -> None:
    config = _config()
    problem = random_problem(N, [0, 1, 2, 3], 5, config)
    empty = make_problem(
        problem.risk_model.mu,
        problem.risk_model.sigma,
        None,
        config,
        universe_overrides={"MaxWeight": [0.6] * N},
        spec=spec_with(target_portfolio_size=4),
    )
    result = search(config, empty)
    assert len(result.compositions) > 1 and result.diagnostics.cold_start
    assert not any(c.is_reference for c in result.compositions)
    assert {c.origin for c in result.compositions} <= {
        CandidateOrigin.COLD_START_SEED,
        CandidateOrigin.BEAM_SEARCH,
        CandidateOrigin.LOCAL_SEARCH,
    }
    for candidate in result.compositions:
        assert len(candidate.asset_ids) == 4
        assert candidate.estimated_turnover is None and candidate.estimated_transaction_cost is None
        assert candidate.estimate_unavailable_reason == "NO_CURRENT_PORTFOLIO"


def test_cold_start_can_be_disabled_and_requires_a_target_size() -> None:
    config = _config()
    base = random_problem(N, HELD, 5, config)
    empty = make_problem(
        base.risk_model.mu,
        base.risk_model.sigma,
        None,
        config,
        universe_overrides={"MaxWeight": [0.6] * N},
    )
    with pytest.raises(CandidateError, match="TargetPortfolioSize"):
        search(config, empty)
    disabled = with_candidates(config, cold_start=False)
    result = search(disabled, empty)
    assert (
        result.compositions == ()
        and "COLD_START_DISABLED_NO_CURRENT_PORTFOLIO" in result.diagnostics.notes
    )


# -------------------------------------------------------------------------- modo de evaluación


def test_qp_mode_requires_an_injected_exact_evaluator_and_uses_it() -> None:
    config = with_candidates(
        _config(), evaluation_mode=EvaluationMode.QP_UTILITY, refinement_iterations=0
    )
    problem = random_problem(N, HELD, 5, config)
    with pytest.raises(CandidateError, match="evaluador exacto"):
        search(config, problem)
    engine = CandidateEngine(config, QPCompositionEvaluator(config))
    result = engine.search(problem.state.composition(), context_of(problem))
    assert len(result.compositions) > 1
    assert all(
        e.basis is EvaluationMode.QP_UTILITY for c in result.compositions for e in c.estimates
    )


# ------------------------------------------------------- casos adversariales (alpha individual)


def _single_swap_config():  # type: ignore[no-untyped-def]
    """Solo sustituciones simples de un nivel: cada candidato incorpora un único activo."""
    return _config(
        swap_orders=(1,),
        max_levels=1,
        local_search_starts=0,
        beam_width=20,
        max_candidates=24,
        utility_risk_aversions=(4.0,),
        refinement_iterations=30,
    )


def _adversarial_problem(config, *, buy_x=5.0, buy_y=5.0):  # type: ignore[no-untyped-def]
    """A000-A002 en cartera (1/3 cada uno). A003 = X: mayor alpha pero casi colineal con la cartera.
    A004 = Y: menor alpha, riesgo bajo y sin correlación. El resto son activos malos."""
    n = 8
    vols = [0.20, 0.20, 0.20, 0.20, 0.15, 0.30, 0.30, 0.30]
    mu = np.array([0.08, 0.08, 0.08, 0.12, 0.10, 0.02, 0.02, 0.02])
    corr = corr_matrix(n, 0.3, **{f"{i}_{j}": 0.6 for i in range(3) for j in range(i + 1, 3)})
    for held in range(3):
        corr[3, held] = corr[held, 3] = 0.95
        corr[4, held] = corr[held, 4] = 0.0
    corr[3, 4] = corr[4, 3] = 0.0
    buy = [5.0] * n
    buy[3], buy[4] = buy_x, buy_y
    sigma = cov_from_vol_corr(vols, corr)
    problem = make_problem(
        mu, sigma, [1 / 3] * 3 + [0.0] * 5, config,
        universe_overrides={"MaxWeight": [1.0] * n, "BuyCost": buy},
    )  # fmt: skip
    # Σ validada del modelo de riesgo (la cruda no es PSD y se repara): es la que usa el motor.
    return problem, mu, np.array(problem.risk_model.sigma)


def _single_swap_gain(result, entering):  # type: ignore[no-untyped-def]
    """Mejora estimada de la composición que solo incorpora ``entering`` (una sustitución)."""
    held = {"A000", "A001", "A002"}
    gains = [
        c.estimated_utility_gain
        for c in result.compositions[1:]
        if set(c.asset_ids) - held == {entering}
    ]
    return max(gains) if gains else None


def _exact_swap_utility(problem, mu, sigma, entering, lam, costs_bps):  # type: ignore[no-untyped-def]
    """Utilidad óptima de sustituir A002 por ``entering`` (SLSQP independiente, con costes)."""
    idx = [0, 1, entering]
    current = np.array([1 / 3, 1 / 3, 0.0])
    buy = np.array([costs_bps[i] for i in idx]) / 1e4
    sell = np.full(3, 7.0 / 1e4)
    return exact_net_utility(
        mu[idx], sigma[np.ix_(idx, idx)], current, buy, sell, (1 / 3) * (7.0 / 1e4), 1.0,
        np.zeros(3), np.ones(3), lam,
    )[0]  # fmt: skip


def test_covariance_beats_individual_alpha_in_the_generated_candidates() -> None:
    """X tiene el mayor alpha, pero concentra riesgo; la mejor sustitución es Y (diversifica).
    El valor exacto (SLSQP) confirma que Y es la elección correcta y X la incorrecta."""
    config = _single_swap_config()
    problem, mu, sigma = _adversarial_problem(config)
    result = search(config, problem)
    gain_x, gain_y = _single_swap_gain(result, "A003"), _single_swap_gain(result, "A004")
    assert gain_x is not None and gain_y is not None
    assert gain_y > gain_x  # Y, no X
    costs = [5.0] * 8
    exact_x = _exact_swap_utility(problem, mu, sigma, 3, 4.0, costs)
    exact_y = _exact_swap_utility(problem, mu, sigma, 4, 4.0, costs)
    assert exact_y > exact_x  # el valor exacto confirma el orden
    assert mu[3] > mu[4]  # por alpha individual saldría X
    baseline = float(
        mu[:3] @ np.full(3, 1 / 3) - 4.0 * np.full(3, 1 / 3) @ sigma[:3, :3] @ np.full(3, 1 / 3)
    )
    assert gain_y <= exact_y - baseline + 1e-9  # la estimación es una cota inferior del óptimo


def test_transaction_cost_beats_individual_alpha_in_the_generated_candidates() -> None:
    """Sin colinealidad: X = mayor alpha pero con coste de compra alto (4 %); Y ligeramente menor
    alpha y barato. Neto de costes gana Y; por alpha individual saldría X."""
    config = _single_swap_config()
    n = 6
    mu = np.array([0.06, 0.06, 0.06, 0.135, 0.13, 0.02])
    vols = [0.2, 0.2, 0.2, 0.2, 0.2, 0.3]
    sigma = cov_from_vol_corr(vols, corr_matrix(n, 0.0))
    buy = [5.0, 5.0, 5.0, 400.0, 5.0, 5.0]
    problem = make_problem(
        mu, sigma, [1 / 3] * 3 + [0.0] * 3, config,
        universe_overrides={"MaxWeight": [1.0] * n, "BuyCost": buy},
    )  # fmt: skip
    result = search(config, problem)
    gain_x, gain_y = _single_swap_gain(result, "A003"), _single_swap_gain(result, "A004")
    assert gain_x is not None and gain_y is not None
    assert gain_y > gain_x
    assert mu[3] > mu[4]
    exact_x = _exact_swap_utility(problem, mu, sigma, 3, 4.0, buy)
    exact_y = _exact_swap_utility(problem, mu, sigma, 4, 4.0, buy)
    assert exact_y > exact_x


def test_the_engine_does_not_mutate_its_inputs() -> None:
    config = _config()
    problem = random_problem(N, HELD, 5, config)
    before_mu, before_sigma = problem.risk_model.mu.copy(), problem.risk_model.sigma.copy()
    before_hash = problem.state.state_hash
    search(config, problem)
    assert np.array_equal(problem.risk_model.mu, before_mu)
    assert np.array_equal(problem.risk_model.sigma, before_sigma)
    assert problem.state.state_hash == before_hash
    assert isinstance(CandidateComposition, type)
    assert CandidateContext.__dataclass_fields__["snapshot"].default is None


def test_search_estimates_are_lower_bounds_of_the_exact_optimum_of_each_composition() -> None:
    """Las estimaciones de la búsqueda (pesos proyectados) nunca superan la utilidad óptima real
    de la misma composición y perfil, calculada con el QP exacto del Bloque 2; los valores
    estimados de turnover y coste son estimaciones distintas de los del óptimo."""
    from portfolio_engine.candidates import current_portfolio_utility
    from tests.fixtures.candidates import prepared_for

    config, problem, result = _run()
    exact = QPCompositionEvaluator(config)
    mu, sigma = problem.risk_model.mu, problem.risk_model.sigma
    held = [problem.risk_model.asset_ids.index(a) for a in problem.state.asset_ids]
    differing = 0
    for candidate in result.compositions:
        prepared = prepared_for(problem, config, candidate.asset_ids)
        for estimate in candidate.estimates:
            lam = estimate.risk_aversion
            baseline = current_portfolio_utility(
                mu[held], sigma[np.ix_(held, held)], problem.state.weights, lam
            )
            optimum = exact.evaluate(prepared, lam, baseline)
            assert not isinstance(optimum, type(None)) and hasattr(optimum, "utility")
            assert estimate.utility <= optimum.utility + 1e-7  # type: ignore[union-attr]
            differing += not np.isclose(estimate.turnover, optimum.turnover, atol=1e-4)  # type: ignore[arg-type,union-attr]
    assert differing > 0  # la estimación de turnover no es el turnover optimizado


def test_max_turnover_rejects_compositions_that_cannot_respect_it_with_an_explicit_cause() -> None:
    """MaxTurnover = 0,30 con cuatro posiciones del 25 %: una sustitución exige al menos
    0,5·(0,25 + 0,25) = 0,25 (factible); dos exigen 0,50 (inviable antes del solver). Toda
    composición devuelta respeta el límite con sus pesos óptimos (QP exacto)."""
    from portfolio_engine.candidates import current_portfolio_utility
    from tests.fixtures.candidates import prepared_for

    limit = 0.30
    config = _config(swap_orders=(1, 2))
    problem = random_problem(N, HELD, 5, config, spec=spec_with(max_turnover=limit))
    result = search(config, problem)
    current = set(problem.state.asset_ids)
    assert len(result.compositions) > 1
    assert all(len(current - set(c.asset_ids)) <= 1 for c in result.compositions)  # sin 2-swaps
    reasons = dict(result.diagnostics.rejections_by_reason)
    assert reasons.get("TURNOVER_FORCED_ABOVE_MAX", 0) > 0  # las de 2 sustituciones se rechazan
    exact = QPCompositionEvaluator(config)
    held = [problem.risk_model.asset_ids.index(a) for a in problem.state.asset_ids]
    for candidate in result.compositions:
        prepared = prepared_for(problem, config, candidate.asset_ids)
        assert prepared.feasible
        baseline = current_portfolio_utility(
            problem.risk_model.mu[held],
            problem.risk_model.sigma[np.ix_(held, held)],
            problem.state.weights,
            4.0,
        )
        optimum = exact.evaluate(prepared, 4.0, baseline)
        assert hasattr(optimum, "turnover") and optimum.turnover <= limit + 1e-7  # type: ignore[union-attr]


def test_max_evaluations_is_a_budget_per_risk_profile_and_per_phase() -> None:
    """Contrato de ``max_evaluations`` (L-3 de AUDIT_BLOCK_3): cada fase (haz o pulido) de cada
    perfil λ consume su propio presupuesto, y el tope total es ``perfiles × 2 × máximo``."""
    limit = 12
    config = _config(max_evaluations=limit, local_search_starts=2, max_levels=6)
    _, _, result = _run(config)
    profiles = config.candidates.utility_risk_aversions
    per_phase = {
        (lam, phase): sum(
            s.evaluated
            for s in result.diagnostics.stages
            if s.risk_aversion == lam and s.algorithm is phase
        )
        for lam in profiles
        for phase in (CandidateOrigin.BEAM_SEARCH, CandidateOrigin.LOCAL_SEARCH)
    }
    assert all(count <= limit for count in per_phase.values())
    # con un presupuesto tan pequeño el haz lo agota y el pulido conserva el suyo (no lo hereda)
    assert all(per_phase[(lam, CandidateOrigin.BEAM_SEARCH)] == limit for lam in profiles)
    assert all(per_phase[(lam, CandidateOrigin.LOCAL_SEARCH)] > 0 for lam in profiles)
    assert result.diagnostics.total_evaluated == sum(per_phase.values())
    assert result.diagnostics.total_evaluated <= len(profiles) * 2 * limit
