"""OUT-004, OUT-009, CAN-016, CAN-017: tablas de composiciones y diagnósticos de candidatos."""

from __future__ import annotations

import dataclasses
import json

import pytest

from portfolio_engine.models.enums import RestrictedExistingPositionPolicy
from portfolio_engine.outputs import (
    CandidateCompositionRow,
    CandidateDiagnosticsRow,
    candidate_composition_rows,
    candidate_diagnostics_rows,
)
from tests.fixtures.candidates import ROLES_N, random_problem, roles_problem, search
from tests.fixtures.problems import base_config, policy_config

pytestmark = pytest.mark.unit

#: Campos exigidos por MASTER_SPEC §66 (CandidateDiagnostics) en su forma snake_case.
SPEC_66 = {
    "portfolio_id",
    "ticker",
    "candidate_type",
    "candidate_score",
    "alpha_score",
    "diversification_score",
    "marginal_utility",
    "liquidity_score",
    "transaction_cost_estimate",
    "selected_for_optimization",
    "rejection_reason",
}
#: Campos del contrato de salida del Bloque 3 (IMPLEMENTATION_PROMPTS, "CANDIDATE OUTPUT").
CONTRACT_B3 = {
    "composition_id",
    "assets",
    "parent_composition_id",
    "swap_history",
    "candidate_score",
    "estimated_utility_gain",
    "estimated_turnover",
    "estimated_transaction_cost",
}


def _result():  # type: ignore[no-untyped-def]
    config = base_config(candidates={"max_evaluations": 50, "refinement_iterations": 5})
    problem = random_problem(12, [0, 1, 2, 3], 5, config)
    return problem, search(config, problem)


def test_candidate_composition_rows_carry_the_contract_fields() -> None:
    problem, result = _result()
    rows = candidate_composition_rows(
        problem.portfolio_id, problem.scenario_id, result.compositions
    )
    assert {f.name for f in dataclasses.fields(CandidateCompositionRow)} >= CONTRACT_B3
    assert len(rows) == len(result.compositions)
    for row, candidate in zip(rows, result.compositions, strict=True):
        assert row.composition_id == candidate.composition_id == row.composition_hash
        assert (
            row.assets == candidate.asset_ids
            and row.parent_composition_id == candidate.parent_composition_id
        )
        assert row.candidate_score == candidate.candidate_score
        assert row.estimated_utility_gain == candidate.estimated_utility_gain
        assert row.estimated_turnover == candidate.estimated_turnover
        assert row.estimated_transaction_cost == candidate.estimated_transaction_cost
        history = json.loads(row.swap_history)
        assert len(history) == row.number_of_moves == len(candidate.swap_history)
        for move, record in zip(candidate.swap_history, history, strict=True):
            assert record["kind"] == move.kind.value and record["out"] == list(move.out_asset_ids)
            assert record["in"] == list(move.in_asset_ids)
    assert rows[0].is_reference and rows[0].origin == "REFERENCE" and rows[0].swap_history == "[]"


def test_estimates_are_labelled_as_such_in_the_rows() -> None:
    problem, result = _result()
    rows = candidate_composition_rows(
        problem.portfolio_id, problem.scenario_id, result.compositions
    )
    assert all(row.estimate_basis == "PROJECTED_WEIGHTS" for row in rows)
    assert all(row.estimate_unavailable_reason is None for row in rows)  # hay cartera y costes


def test_candidate_diagnostics_rows_cover_every_asset_and_the_spec_fields() -> None:
    problem, result = _result()
    tickers = {asset.asset_id: asset.ticker for asset in problem.universe}
    rows = candidate_diagnostics_rows(result.diagnostics, tickers)
    assert {f.name for f in dataclasses.fields(CandidateDiagnosticsRow)} >= SPEC_66
    assert len(rows) == 12 and [r.asset_id for r in rows] == sorted(r.asset_id for r in rows)
    assert all(
        r.ticker == tickers[r.asset_id] and r.portfolio_id == problem.portfolio_id for r in rows
    )
    by_asset = {r.asset_id: r for r in rows}
    selected_assets = {a for c in result.compositions for a in c.asset_ids}
    for asset_id, row in by_asset.items():
        assert row.selected_for_optimization == (asset_id in selected_assets)
        assert row.selected_for_optimization or row.rejection_reason
    held = [by_asset[f"A{i:03d}"] for i in range(4)]
    assert all(
        r.candidate_type == "CURRENT_HOLDING" and r.eligibility_status == "HELD" for r in held
    )
    for row in rows:
        for score in (
            row.candidate_score,
            row.alpha_score,
            row.diversification_score,
            row.marginal_utility,
            row.liquidity_score,
        ):
            assert score is None or 0.0 <= score <= 1.0  # normalización por rango
        assert row.transaction_cost_estimate is None or row.transaction_cost_estimate >= 0.0
    entrants = [r for r in rows if r.eligibility_status == "ELIGIBLE_NEW"]
    assert entrants and all(r.candidate_score is not None for r in entrants)
    assert any(r.candidate_type == "HIGH_CONVICTION" for r in entrants)  # los de la lista corta


def test_excluded_assets_report_the_reason_and_stay_out_of_the_screening() -> None:
    config = policy_config(base_config(), RestrictedExistingPositionPolicy.HOLD_OR_REDUCE)
    problem = roles_problem(config)
    result = search(config, problem)
    tickers = {asset.asset_id: asset.ticker for asset in problem.universe}
    by_asset = {r.asset_id: r for r in candidate_diagnostics_rows(result.diagnostics, tickers)}
    assert len(by_asset) == ROLES_N
    expected = {
        "A005": "NOT_ELIGIBLE",
        "A006": "NOT_LIQUID",
        "A007": "RESTRICTED",
        "A008": "UNKNOWN_LIQUIDITY_FLAG",
        "A009": "UNKNOWN_RESTRICTED_FLAG",
    }
    for asset_id, reason in expected.items():
        row = by_asset[asset_id]
        assert row.eligibility_status == "EXCLUDED" and row.rejection_reason == reason
        assert not row.selected_for_optimization and row.candidate_score is None
        assert row.candidate_type is None
    assert by_asset["A001"].eligibility_status == "LIQUIDATE_ONLY"  # mantenido no elegible
    assert "NOT_ELIGIBLE" in by_asset["A001"].eligibility_reasons


def test_diagnostics_rows_are_json_friendly_and_deterministic() -> None:
    problem, result = _result()
    tickers = {asset.asset_id: asset.ticker for asset in problem.universe}
    first = candidate_diagnostics_rows(result.diagnostics, tickers)
    second = candidate_diagnostics_rows(result.diagnostics, tickers)
    assert first == second
    json.dumps([dataclasses.asdict(row) for row in first], default=list)
