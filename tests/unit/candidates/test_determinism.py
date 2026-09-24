"""REP-003, PAR-009, PAR-010 (parte del Bloque 3): semillas derivadas, orden estable y
reproducibilidad independiente del ``hash()`` de Python."""

from __future__ import annotations

import subprocess
import sys

import pytest

from portfolio_engine.frontiers import GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.parallel import derive_seed, sequence_key, tie_break_key
from tests.conftest import REPO_ROOT
from tests.fixtures.candidates import two_region_problem
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def _run(code: str, hash_seed: str) -> str:
    return subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(REPO_ROOT)},
    ).stdout.strip()


def test_derive_seed_is_identical_across_processes_and_hash_seeds() -> None:
    code = (
        "from portfolio_engine.parallel import derive_seed;"
        "print(derive_seed(20260923, 'P1', 'BASE', 'level-2'))"
    )
    outputs = {_run(code, seed) for seed in ("0", "1", "4242")}
    assert outputs == {str(derive_seed(20260923, "P1", "BASE", "level-2"))}


def test_candidate_generation_does_not_depend_on_the_python_hash_seed() -> None:
    """Con exploración activa (semilla derivada), tres procesos con PYTHONHASHSEED distintos dan
    exactamente las mismas composiciones, orden y estimaciones."""
    code = (
        "from tests.fixtures.candidates import random_problem, search;"
        "from tests.fixtures.problems import base_config;"
        "c = base_config(candidates={'max_evaluations': 30, 'refinement_iterations': 5,"
        " 'shortlist_in': 3, 'max_levels': 2});"
        "r = search(c, random_problem(10, [0, 1, 2, 3], 5, c));"
        "print([(x.composition_hash[:12], round(x.estimated_utility_gain, 12),"
        " round(x.candidate_score, 12))"
        " for x in r.compositions])"
    )
    outputs = {_run(code, seed) for seed in ("0", "7", "99")}
    assert len(outputs) == 1 and next(iter(outputs)).startswith("[(")


def test_sequence_key_orders_by_portfolio_scenario_scope_treatment_composition_and_point() -> None:
    base = ("P1", "BASE", "GLOBAL_CANDIDATE_FRONTIER", "NET", "hash-b", "P002")
    variants = [
        ("P0", "BASE", "GLOBAL_CANDIDATE_FRONTIER", "NET", "hash-z", "P009"),
        ("P1", "ALPHA", "GLOBAL_CANDIDATE_FRONTIER", "NET", "hash-z", "P009"),
        ("P1", "BASE", "CONTINUOUS_FRONTIER", "NET", "hash-z", "P009"),
        ("P1", "BASE", "GLOBAL_CANDIDATE_FRONTIER", "GROSS", "hash-z", "P009"),
        ("P1", "BASE", "GLOBAL_CANDIDATE_FRONTIER", "NET", "hash-a", "P009"),
        ("P1", "BASE", "GLOBAL_CANDIDATE_FRONTIER", "NET", "hash-b", "P001"),
    ]
    for variant in variants:  # cada variante es menor que ``base`` por un solo componente
        assert sequence_key(*variant) < sequence_key(*base)
    assert sequence_key(*base) == sequence_key(*base)


def test_tie_break_orders_by_descending_score_then_by_composition_hash() -> None:
    items = [(0.5, "b"), (0.9, "z"), (0.5, "a"), (0.9, "c")]
    ordered = sorted(items, key=lambda item: tie_break_key(*item))
    assert ordered == [(0.9, "c"), (0.9, "z"), (0.5, "a"), (0.5, "b")]


def test_global_points_follow_the_canonical_sequence_order() -> None:
    config = base_config()
    problem = two_region_problem(config)
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    keys = [
        sequence_key(
            result.portfolio_id,
            result.scenario_id,
            "GLOBAL_CANDIDATE_FRONTIER",
            result.cost_treatment.value,
            p.composition_id,
            p.point.point_id,
        )
        for p in result.points
    ]
    assert keys == sorted(keys)
    assert [p.sequence_id for p in result.points] == list(range(len(keys)))
