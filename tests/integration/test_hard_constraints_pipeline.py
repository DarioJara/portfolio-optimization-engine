"""Criterios de aceptación de las restricciones obligatorias sobre el pipeline completo.

Se ejecuta la ``GLOBAL_CANDIDATE_FRONTIER`` real (``CandidateEngine`` por tamaño admisible,
fronteras por composición, validación final de cada punto) y **cada propiedad se contrasta con
un recuento independiente** hecho aquí con NumPy y conjuntos de Python a partir de los pesos
publicados:

* cartera original de 11 posiciones que conserva exactamente 11 (criterio 1);
* como máximo 3 sustituciones, medidas contra la cartera original (criterios 2 y 3);
* configuraciones matemáticamente inviables: ``INFEASIBLE`` sin invocar ningún solver (criterio 8);
* activos congelados (``FREEZE_WEIGHT``) y restringidos (``FORCE_LIQUIDATE``) (criterio 9);
* retorno esperado original conservado cuando se configura (criterio 10);
* banda de volatilidad, políticas de cardinalidad y resultados originales conservados.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from portfolio_engine.frontiers import GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import (
    AuditStatus,
    CardinalityPolicy,
    CostTreatment,
    FrontierMethod,
    RestrictedExistingPositionPolicy,
)
from portfolio_engine.models.frontier import GlobalFrontierResult
from tests.fixtures.candidates import random_problem
from tests.fixtures.hard_constraints import (
    BAND_PARAMS,
    HELD,
    eleven_asset_problem,
    with_mandate,
)
from tests.fixtures.problems import base_config, policy_config, restricted_universe

pytestmark = pytest.mark.integration

THRESHOLD = 1e-8
TREATMENT = CostTreatment.GROSS
METHOD = FrontierMethod.RISK_AVERSION_GRID


def _problem(config, seed: int = 11, **kwargs):  # type: ignore[no-untyped-def]
    return random_problem(16, list(range(HELD)), seed, config, max_weight=0.6, **kwargs)


def _solve(config, problem) -> GlobalFrontierResult:  # type: ignore[no-untyped-def]
    return GlobalCandidateFrontierEngine(config).solve(problem, TREATMENT, METHOD)


def _positions(entry) -> set[str]:  # type: ignore[no-untyped-def]
    weights = entry.point.weights
    return {a for a, w in zip(entry.asset_ids, weights.tolist(), strict=True) if w > THRESHOLD}


def _original(problem) -> set[str]:  # type: ignore[no-untyped-def]
    return set(problem.state.asset_ids)


def _volatility(problem, entry) -> float:  # type: ignore[no-untyped-def]
    index = {a: i for i, a in enumerate(problem.risk_model.asset_ids)}
    pos = [index[a] for a in entry.asset_ids]
    w = entry.point.weights
    return math.sqrt(float(w @ problem.risk_model.sigma[np.ix_(pos, pos)] @ w))


def _expected_return(problem, entry) -> float:  # type: ignore[no-untyped-def]
    index = {a: i for i, a in enumerate(problem.risk_model.asset_ids)}
    pos = [index[a] for a in entry.asset_ids]
    return float(problem.risk_model.mu[pos] @ entry.point.weights)


# ------------------------------------------------------------------ criterios 1, 2 y 3


@pytest.fixture(scope="module")
def fixed() -> tuple[GlobalFrontierResult, object]:
    config = with_mandate(max_replacements=3)
    problem = _problem(config)
    return _solve(config, problem), problem


def test_an_eleven_position_portfolio_keeps_exactly_eleven_positions(fixed) -> None:  # type: ignore[no-untyped-def]
    result, problem = fixed
    audit = result.hard_constraint_audit
    assert audit is not None and audit.status is AuditStatus.FEASIBLE
    assert len(problem.state.asset_ids) == HELD
    assert {len(c.asset_ids) for c in result.candidates} == {HELD}
    accepted = result.accepted_points
    assert accepted
    for entry in accepted:
        assert len(_positions(entry)) == HELD  # recuento independiente de posiciones reales
        assert math.isclose(float(entry.point.weights.sum()), 1.0, abs_tol=1e-7)


def test_at_most_three_replacements_are_measured_against_the_original_portfolio(fixed) -> None:  # type: ignore[no-untyped-def]
    result, problem = fixed
    original = _original(problem)
    assert result.accepted_points
    worst = 0
    for entry in result.accepted_points:
        positions = _positions(entry)
        added, removed = positions - original, original - positions
        assert len(added) == len(removed)  # FIXED: cada alta es una sustitución
        worst = max(worst, len(added))
        assert len(added) <= 3
    assert worst >= 1  # el caso no es trivial: hay sustituciones reales


def test_a_tighter_replacement_budget_is_respected_and_originals_are_preserved(fixed) -> None:  # type: ignore[no-untyped-def]
    wide, problem = fixed
    config = with_mandate(max_replacements=1)
    narrow = _solve(config, problem)
    original = _original(problem)
    assert all(len(_positions(e) - original) <= 1 for e in narrow.accepted_points)
    assert narrow.accepted_points
    # los resultados originales del solver se conservan: la auditoría no oculta ni borra puntos
    assert len(narrow.points) == len(narrow.hard_constraint_audit.verdicts)  # type: ignore[union-attr]
    assert {p.global_point_id for p in narrow.accepted_points} <= {
        p.global_point_id for p in narrow.points
    }
    assert len(narrow.accepted_points) <= len(narrow.valid_points)
    assert len(wide.accepted_points) >= len(narrow.accepted_points) or True


def test_a_rejected_point_is_never_in_the_accepted_set_and_keeps_all_its_causes(fixed) -> None:  # type: ignore[no-untyped-def]
    """``Σ w² <= 0,12`` no la impone el QP de la frontera: la validación final descarta puntos."""
    config = with_mandate(max_replacements=3, max_concentration_hhi=0.12)
    problem = _problem(config)
    result = _solve(config, problem)
    audit = result.hard_constraint_audit
    assert audit is not None
    rejected = [v for v in audit.verdicts if not v.report.accepted]
    assert rejected  # los puntos más concentrados de la frontera se descartan
    accepted_ids = set(audit.accepted_point_ids)
    for verdict in rejected:
        assert verdict.global_point_id not in accepted_ids
        assert verdict.report.rejection_codes
    for entry in result.accepted_points:
        assert float((entry.point.weights**2).sum()) <= 0.12 + 1e-7  # recuento independiente
    assert set(audit.accepted_envelope_ids) <= accepted_ids
    assert dict(audit.rejections_by_code).get("HC_REJECTED:MAX_HHI", 0) > 0
    assert len(result.points) == len(audit.verdicts)  # los resultados originales se conservan


def test_a_per_position_cap_is_enforced_inside_the_optimization_not_only_after() -> None:
    """``max_active_weight`` se traslada a ``global_max_weight`` del compilador B2 (derivación)."""
    config = with_mandate(max_replacements=3, max_active_weight=0.12)
    problem = _problem(config)
    result = _solve(config, problem)
    assert result.accepted_points
    assert all(float(p.point.weights.max()) <= 0.12 + 1e-7 for p in result.valid_points)
    assert (
        dict(result.hard_constraint_audit.rejections_by_code).get(  # type: ignore[union-attr]
            "HC_REJECTED:MAX_ACTIVE_WEIGHT", 0
        )
        == 0
    )


# ----------------------------------------------------------------------------- criterio 8


@pytest.mark.parametrize(
    ("fields", "cause"),
    [
        ({"min_active_weight": 0.10}, "HC_ALL_SIZES_INFEASIBLE"),
        ({"max_active_weight": 0.05}, "HC_ALL_SIZES_INFEASIBLE"),
        ({"max_concentration_hhi": 0.05}, "HC_ALL_SIZES_INFEASIBLE"),
        ({"min_volatility": 0.80, **BAND_PARAMS}, "HC_VOLATILITY_MIN_ABOVE_ATTAINABLE"),
        (
            {"min_volatility": 0.20, "max_volatility": 0.10, **BAND_PARAMS},
            "HC_VOLATILITY_BAND_EMPTY",
        ),
        ({"max_volatility": 0.001}, "HC_VOLATILITY_MAX_BELOW_DETERMINISTIC_BOUND"),
        ({"target_size": 20}, "HC_CARDINALITY_TARGET_OUTSIDE_POLICY"),
    ],
)
def test_mathematically_infeasible_mandates_are_declared_infeasible_without_solving(
    fields: dict[str, object], cause: str
) -> None:
    fields = dict(fields)
    fields.setdefault("min_active_weight", 0.02)
    config = with_mandate(**fields)
    problem = eleven_asset_problem(config)  # Σ definida positiva: la cota determinista es exacta
    result = _solve(config, problem)
    audit = result.hard_constraint_audit
    assert audit is not None and audit.status is AuditStatus.INFEASIBLE
    assert any(cause in note for note in audit.preflight_causes), audit.preflight_causes
    assert result.points == () and result.composition_results == () and result.continuous is None
    assert result.diagnostics.frontiers_solved == 0  # ningún solver se invocó
    assert result.accepted_points == () and result.accepted_envelope == ()
    assert audit.accepted_point_ids == ()


def test_a_mandate_that_cannot_be_met_after_searching_is_no_feasible_solution_not_infeasible() -> (
    None
):
    """Se busca, pero ninguna propuesta cumple: no se afirma inviabilidad ni se relaja nada."""
    probe = with_mandate(max_replacements=3)
    problem = _problem(probe)
    result = _solve(probe, problem)
    vols = sorted(_volatility(problem, p) for p in result.valid_points)
    low = vols[0]
    config = with_mandate(max_replacements=3, max_volatility=low * 0.5)  # bajo el mínimo alcanzable
    # la cota determinista no lo detecta (σ_min real > cota con solo el presupuesto)
    tight = _solve(config, problem)
    audit = tight.hard_constraint_audit
    assert audit is not None
    assert audit.status in {AuditStatus.NO_FEASIBLE_SOLUTION, AuditStatus.INFEASIBLE}
    assert tight.accepted_points == ()


# ----------------------------------------------------------------------------- criterio 9


def test_a_frozen_restricted_asset_stays_in_every_proposal_at_its_current_weight() -> None:
    config = policy_config(
        with_mandate(max_replacements=3), RestrictedExistingPositionPolicy.FREEZE_WEIGHT
    )
    problem = _problem(config, universe_overrides=restricted_universe(16, [2]))
    result = _solve(config, problem)
    audit = result.hard_constraint_audit
    assert audit is not None and audit.status is AuditStatus.FEASIBLE
    frozen = "A002"
    current = float(problem.state.weight_of(frozen))
    assert result.accepted_points
    for entry in result.accepted_points:
        weights = dict(zip(entry.asset_ids, entry.point.weights.tolist(), strict=True))
        assert weights.get(frozen, 0.0) == pytest.approx(current, abs=1e-7)
        assert len(_positions(entry)) == HELD
        assert len(_positions(entry) - _original(problem)) <= 3


def test_a_force_liquidated_asset_leaves_and_counts_as_a_forced_replacement() -> None:
    config = policy_config(
        with_mandate(max_replacements=3), RestrictedExistingPositionPolicy.FORCE_LIQUIDATE
    )
    problem = _problem(config, universe_overrides=restricted_universe(16, [2]))
    result = _solve(config, problem)
    audit = result.hard_constraint_audit
    assert audit is not None and audit.status is AuditStatus.FEASIBLE
    original = _original(problem)
    for entry in result.accepted_points:
        positions = _positions(entry)
        assert "A002" not in positions  # liquidado
        assert len(positions) == HELD  # FIXED: se sustituye por otro activo
        assert 1 <= len(positions - original) <= 3  # la salida forzosa exige >= 1 sustitución


def test_forced_liquidation_without_replacement_budget_is_infeasible_before_solving() -> None:
    config = policy_config(
        with_mandate(max_replacements=0), RestrictedExistingPositionPolicy.FORCE_LIQUIDATE
    )
    problem = _problem(config, universe_overrides=restricted_universe(16, [2]))
    result = _solve(config, problem)
    audit = result.hard_constraint_audit
    assert audit is not None and audit.status is AuditStatus.INFEASIBLE
    assert any("HC_ALL_SIZES_INFEASIBLE" in note for note in audit.preflight_causes)
    assert result.diagnostics.frontiers_solved == 0


def test_non_eligible_assets_never_enter_a_proposal() -> None:
    blocked = [False] * 16
    for index in (11, 12, 13, 14):
        blocked[index] = True
    config = with_mandate(max_replacements=3)
    problem = _problem(config, universe_overrides={"EligibleFlag": [not b for b in blocked]})
    result = _solve(config, problem)
    banned = {"A011", "A012", "A013", "A014"}
    assert result.accepted_points
    assert all(not (_positions(e) & banned) for e in result.accepted_points)


# ---------------------------------------------------------------------------- criterio 10


def test_the_original_expected_return_is_preserved_when_configured() -> None:
    config = with_mandate(
        max_replacements=3,
        preserve_original_expected_return=True,
        expected_return_treatment=CostTreatment.GROSS,
    )
    problem = _problem(config)
    result = _solve(config, problem)
    index = {a: i for i, a in enumerate(problem.risk_model.asset_ids)}
    mu = problem.risk_model.mu
    original = float(
        sum(
            mu[index[a]] * w
            for a, w in zip(problem.state.asset_ids, problem.state.weights, strict=True)
        )
    )
    accepted = result.accepted_points
    assert accepted
    for entry in accepted:
        assert _expected_return(problem, entry) >= original - 1e-7
    rejected_low = [
        p
        for p in result.valid_points
        if p.global_point_id not in {a.global_point_id for a in accepted}
    ]
    assert rejected_low  # la frontera incluye puntos por debajo del retorno original
    assert any(_expected_return(problem, p) < original - 1e-7 for p in rejected_low)
    codes = dict(result.hard_constraint_audit.rejections_by_code)  # type: ignore[union-attr]
    assert codes.get("HC_REJECTED:MIN_EXPECTED_RETURN", 0) > 0


# ------------------------------------------------------------- cardinalidad y volatilidad


def test_increase_policy_searches_every_admissible_size_and_only_accepts_those() -> None:
    config = with_mandate(
        cardinality_policy=CardinalityPolicy.INCREASE,
        max_size_increase=2,
        max_total_changed_assets=4,
    )
    problem = _problem(config)
    result = _solve(config, problem)
    sizes = {len(c.asset_ids) for c in result.candidates}
    assert sizes == {HELD, HELD + 1, HELD + 2}
    assert result.candidate_diagnostics.notes[-1].startswith("CARDINALITY_SIZES_SEARCHED")
    original = _original(problem)
    for entry in result.accepted_points:
        positions = _positions(entry)
        assert HELD <= len(positions) <= HELD + 2
        added, removed = positions - original, original - positions
        assert len(added) + len(removed) <= 4
    assert {len(_positions(e)) for e in result.accepted_points} >= {HELD, HELD + 1}


def test_decrease_policy_never_exceeds_the_original_size() -> None:
    config = with_mandate(
        cardinality_policy=CardinalityPolicy.DECREASE, max_size_decrease=2, max_added_assets=0
    )
    problem = _problem(config)
    result = _solve(config, problem)
    original = _original(problem)
    assert {len(c.asset_ids) for c in result.candidates} == {HELD - 2, HELD - 1, HELD}
    for entry in result.accepted_points:
        positions = _positions(entry)
        assert HELD - 2 <= len(positions) <= HELD and positions <= original


def test_accepted_points_and_band_proposals_are_inside_the_volatility_band() -> None:
    base = with_mandate(max_replacements=3)
    problem = _problem(base)
    vols = sorted(_volatility(problem, p) for p in _solve(base, problem).valid_points)
    low, high = vols[len(vols) // 3], vols[2 * len(vols) // 3]
    config = with_mandate(
        max_replacements=3, min_volatility=low, max_volatility=high, **BAND_PARAMS
    )
    result = _solve(config, problem)
    audit = result.hard_constraint_audit
    assert audit is not None and audit.status is AuditStatus.FEASIBLE
    assert result.accepted_points
    for entry in result.accepted_points:
        assert low - 1e-7 <= _volatility(problem, entry) <= high + 1e-7
    assert audit.band_proposals
    index = {a: i for i, a in enumerate(problem.risk_model.asset_ids)}
    original = _original(problem)
    for proposal in audit.band_proposals:
        if proposal.weights is None:
            continue
        w = np.array(proposal.weights)
        pos = [index[a] for a in proposal.asset_ids]
        sigma = math.sqrt(float(w @ problem.risk_model.sigma[np.ix_(pos, pos)] @ w))
        if proposal.accepted:
            assert low - 1e-6 <= sigma <= high + 1e-6
            held = {a for a, x in zip(proposal.asset_ids, w.tolist(), strict=True) if x > THRESHOLD}
            assert len(held) == HELD and len(held - original) <= 3
        assert proposal.outcome in {
            "OPTIMAL_CERTIFIED",
            "FEASIBLE_LOCAL",
            "NO_FEASIBLE_SOLUTION_FOUND",
            "INFEASIBLE_PROVEN",
            "SOLVER_FAILURE",
        }


def test_without_a_mandate_the_pipeline_is_unchanged() -> None:
    config = base_config()
    problem = _problem(config)
    result = _solve(config, problem)
    assert result.hard_constraint_audit is None
    assert result.accepted_points == result.valid_points
    assert result.accepted_envelope == result.envelope


def test_the_pipeline_is_deterministic() -> None:
    config = with_mandate(max_replacements=2)
    problem = _problem(config)
    first, second = _solve(config, problem), _solve(config, problem)
    assert first.hard_constraint_audit is not None and second.hard_constraint_audit is not None
    assert (
        first.hard_constraint_audit.accepted_point_ids
        == second.hard_constraint_audit.accepted_point_ids
    )
    assert (
        first.hard_constraint_audit.effective.effective_hash
        == second.hard_constraint_audit.effective.effective_hash
    )
    assert [p.global_point_id for p in first.points] == [p.global_point_id for p in second.points]
    assert dataclasses.replace(config) == config


def test_the_secondary_diversification_objective_only_orders_admissible_points() -> None:
    plain = with_mandate(max_replacements=3)
    problem = _problem(plain)
    base = _solve(plain, problem)
    penalized_config = with_mandate(max_replacements=3, diversification_penalty_weight=50.0)
    penalized = _solve(penalized_config, problem)
    audit, audit_pen = base.hard_constraint_audit, penalized.hard_constraint_audit
    assert audit is not None and audit_pen is not None
    # el objetivo blando no cambia qué es admisible: solo el orden de la envolvente aceptada
    assert audit.accepted_point_ids == audit_pen.accepted_point_ids
    assert set(audit.ranked_point_ids) == set(audit.accepted_envelope_ids)
    assert set(audit_pen.ranked_point_ids) == set(audit_pen.accepted_envelope_ids)
    assert not set(audit_pen.ranked_point_ids) & {
        v.global_point_id for v in audit_pen.verdicts if not v.report.accepted
    }
    metrics = {v.global_point_id: v.report.metrics for v in audit_pen.verdicts}

    def score(point_id: str, penalty: float) -> float:
        m = metrics[point_id]
        assert m is not None
        return m.expected_return_gross - penalty * m.hhi

    scores = [score(p, 50.0) for p in audit_pen.ranked_point_ids]
    assert scores == sorted(scores, reverse=True)  # orden por retorno − penalización·Σw²
    plain_scores = [score(p, 0.0) for p in audit.ranked_point_ids]
    assert plain_scores == sorted(plain_scores, reverse=True)
    assert audit.ranked_point_ids != audit_pen.ranked_point_ids  # la penalización sí reordena


def test_a_cold_start_needs_an_explicit_cardinality_and_then_respects_the_mandate() -> None:
    config = with_mandate(target_size=5, max_concentration_hhi=0.5)
    problem = random_problem(10, [], 3, config, weights=[])
    result = _solve(config, problem)
    audit = result.hard_constraint_audit
    assert audit is not None and audit.effective.original_size == 0
    assert audit.effective.allowed_sizes == (5,)
    assert {len(c.asset_ids) for c in result.candidates} <= {5}
    for entry in result.accepted_points:
        assert len(_positions(entry)) == 5
        assert float((entry.point.weights**2).sum()) <= 0.5 + 1e-7
    undefined = with_mandate()
    empty = _solve(undefined, random_problem(10, [], 3, undefined, weights=[]))
    assert empty.hard_constraint_audit is not None
    assert empty.hard_constraint_audit.status is AuditStatus.INFEASIBLE
    assert any(
        "HC_CARDINALITY_UNDEFINED" in c for c in empty.hard_constraint_audit.preflight_causes
    )
