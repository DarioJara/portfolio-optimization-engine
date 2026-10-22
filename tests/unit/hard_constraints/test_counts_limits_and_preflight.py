"""HC-002, HC-003, HC-008: recuento de cambios, límites de composición y factibilidad previa.

El recuento se contrasta con una enumeración explícita independiente y la factibilidad previa con
configuraciones matemáticamente inviables cuya causa se conoce de antemano: el solver nunca se
invoca (la prueba de integración comprueba además que no se genera ninguna frontera).
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from portfolio_engine.constraints.integer import (
    CompositionLimits,
    limit_violations,
    move_violations,
)
from portfolio_engine.hard_constraints.counts import change_counts, positions_of
from portfolio_engine.hard_constraints.preflight import PreflightData, check_preflight
from portfolio_engine.models.enums import CardinalityPolicy
from tests.fixtures.hard_constraints import (
    BAND_PARAMS,
    HELD,
    effective_of,
    eleven_asset_problem,
    with_mandate,
)

pytestmark = pytest.mark.unit

ORIGINAL = frozenset({"a", "b", "c", "d"})


def test_counts_distinguish_one_to_one_replacements_from_independent_changes() -> None:
    cases = {
        # final: (added, removed, replacements, pure_add, pure_rem, total, swaps)
        frozenset({"a", "b", "c", "d"}): (0, 0, 0, 0, 0, 0, 0),
        frozenset({"a", "b", "c", "x"}): (1, 1, 1, 0, 0, 2, 1),
        frozenset({"a", "b", "x", "y"}): (2, 2, 2, 0, 0, 4, 2),
        frozenset({"a", "b", "c", "d", "x"}): (1, 0, 0, 1, 0, 1, 1),
        frozenset({"a", "b", "c"}): (0, 1, 0, 0, 1, 1, 1),
        frozenset({"a", "b", "x", "y", "z"}): (3, 2, 2, 1, 0, 5, 3),
        frozenset({"a", "x"}): (1, 3, 1, 0, 2, 4, 3),
        frozenset({"x", "y"}): (2, 4, 2, 0, 2, 6, 4),
    }
    for final, expected in cases.items():
        counts = change_counts(ORIGINAL, final)
        assert (
            counts.added,
            counts.removed,
            counts.replacements,
            counts.pure_additions,
            counts.pure_removals,
            counts.total_changed,
            counts.swaps,
        ) == expected, final
        assert counts.final_size - counts.original_size == counts.added - counts.removed


def test_counts_match_an_exhaustive_set_enumeration() -> None:
    universe = ["a", "b", "c", "d", "e", "f"]
    for size in range(1, 6):
        for final in itertools.combinations(universe, size):
            counts = change_counts(ORIGINAL, final)
            added = [x for x in final if x not in ORIGINAL]
            removed = [x for x in ORIGINAL if x not in final]
            assert counts.added == len(added) and counts.removed == len(removed)
            assert counts.replacements == min(len(added), len(removed))
            assert counts.pure_additions + counts.replacements == counts.added
            assert counts.pure_removals + counts.replacements == counts.removed


def test_positive_weight_uses_one_threshold() -> None:
    weights = {"a": 0.5, "b": 0.5 - 1e-9, "c": 1e-9, "d": 0.0, "e": 1e-6}
    assert positions_of(weights, 1e-8) == frozenset({"a", "b", "e"})
    assert positions_of(weights, 1e-6) == frozenset({"a", "b"})  # estrictamente mayor


def test_composition_limits_cover_every_component_budget() -> None:
    limits = CompositionLimits(
        None, 3, None, frozenset(),
        min_size=3, max_size=5, max_removed_assets=1, max_total_changed=3,
        max_replacements=1, max_pure_additions=1, max_pure_removals=0,
    )  # fmt: skip
    ok = frozenset({"a", "b", "c", "x"})
    assert limit_violations(limits, ORIGINAL, ok) == ()
    assert move_violations(limits, ORIGINAL, frozenset({"a", "b", "x", "y"})) == (
        "MAX_REMOVED_ASSETS",
        "MAX_TOTAL_CHANGED_ASSETS",
        "MAX_REPLACEMENTS",
    )
    assert "CARDINALITY_BELOW_MIN" in limit_violations(limits, ORIGINAL, frozenset({"a", "b"}))
    big = frozenset({"a", "b", "c", "d", "x", "y"})
    codes = limit_violations(limits, ORIGINAL, big)
    assert "CARDINALITY_ABOVE_MAX" in codes and "MAX_NEW_ASSETS" not in codes
    assert "MAX_PURE_ADDITIONS" in codes
    removal = limit_violations(limits, ORIGINAL, frozenset({"a", "b", "c"}))
    assert removal == ("MAX_PURE_REMOVALS",) and "MAX_REMOVED_ASSETS" not in removal


def test_legacy_limits_behave_exactly_as_before() -> None:
    legacy = CompositionLimits(4, 1, 1, frozenset({"a"}))
    assert limit_violations(legacy, ORIGINAL, ORIGINAL) == ()
    assert limit_violations(legacy, ORIGINAL, frozenset({"b", "c", "d", "x"})) == (
        "MANDATORY_ASSET_REMOVED",
    )
    assert limit_violations(legacy, ORIGINAL, frozenset({"a", "b", "x", "y"})) == (
        "MAX_NEW_ASSETS",
        "MAX_SWAPS",
    )


# ------------------------------------------------------------------------ factibilidad previa


def _data(**changes: object) -> PreflightData:
    values: dict[str, object] = {
        "original_size": HELD,
        "enterable_count": 5,
        "forced_exits": 0,
        "mandatory_holds": 0,
        "long_only": True,
        "mu": np.linspace(0.04, 0.10, 16),
        "sigma": np.diag(np.full(16, 0.04)),
        "budget": 1.0,
    }
    values.update(changes)
    return PreflightData(**values)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def problem():  # type: ignore[no-untyped-def]
    return eleven_asset_problem()


def _codes(config, problem, data=None, sizes=None):  # type: ignore[no-untyped-def]
    effective = effective_of(config, problem)
    return {c.code for c in check_preflight(effective, data or _data(), sizes)}


def test_a_coherent_mandate_has_no_infeasibility_causes(problem) -> None:  # type: ignore[no-untyped-def]
    config = with_mandate(max_replacements=3, max_volatility=0.30, max_active_weight=0.25)
    assert _codes(config, problem) == set()


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"min_active_weight": 0.10}, "HC_ALL_SIZES_INFEASIBLE"),  # 11·0,10 > 1
        ({"max_active_weight": 0.05}, "HC_ALL_SIZES_INFEASIBLE"),  # 11·0,05 < 1
        ({"min_active_weight": 0.2, "max_active_weight": 0.1}, "HC_ACTIVE_WEIGHT_RANGE_EMPTY"),
        ({"max_concentration_hhi": 0.05}, "HC_ALL_SIZES_INFEASIBLE"),  # Σw² >= 1/11 = 0,0909
        ({"min_effective_number_of_positions": 12.0}, "HC_ALL_SIZES_INFEASIBLE"),  # N_eff <= 11
        (
            {"min_volatility": 0.20, "max_volatility": 0.10, **BAND_PARAMS},
            "HC_VOLATILITY_BAND_EMPTY",
        ),
        ({"max_volatility": 0.001}, "HC_VOLATILITY_MAX_BELOW_DETERMINISTIC_BOUND"),
        ({"min_volatility": 0.50, **BAND_PARAMS}, "HC_VOLATILITY_MIN_ABOVE_ATTAINABLE"),
        (
            {"min_expected_return": 0.50, "expected_return_treatment": "GROSS"},
            "HC_RETURN_FLOOR_UNATTAINABLE",
        ),
    ],
)
def test_mathematically_infeasible_configurations_are_declared_before_solving(
    problem, fields: dict[str, object], code: str
) -> None:  # type: ignore[no-untyped-def]
    from portfolio_engine.models.enums import CostTreatment

    fields = dict(fields)
    if fields.get("expected_return_treatment") == "GROSS":
        fields["expected_return_treatment"] = CostTreatment.GROSS
    assert code in _codes(with_mandate(**fields), problem)


def test_change_budgets_are_compared_with_what_each_size_requires(problem) -> None:  # type: ignore[no-untyped-def]
    # FIXED con 2 salidas forzosas exige 2 altas y 2 retiros: 2 sustituciones
    forced = _data(forced_exits=2)
    assert _codes(with_mandate(max_replacements=2), problem, forced) == set()
    assert "HC_ALL_SIZES_INFEASIBLE" in _codes(with_mandate(max_replacements=1), problem, forced)
    assert "HC_ALL_SIZES_INFEASIBLE" in _codes(with_mandate(max_added_assets=1), problem, forced)
    assert "HC_ALL_SIZES_INFEASIBLE" in _codes(
        with_mandate(max_total_changed_assets=3), problem, forced
    )
    # no hay activos incorporables suficientes
    assert "HC_ALL_SIZES_INFEASIBLE" in _codes(
        with_mandate(), problem, _data(forced_exits=2, enterable_count=1)
    )


def test_decrease_with_forced_exits_needs_removal_budget_but_no_additions(problem) -> None:  # type: ignore[no-untyped-def]
    config = with_mandate(
        cardinality_policy=CardinalityPolicy.DECREASE, max_size_decrease=2,
        max_added_assets=0, max_removed_assets=2,
    )  # fmt: skip
    forced = _data(forced_exits=2)
    # k = 9: 2 retiros, 0 altas → factible
    assert _codes(config, problem, forced) == set()
    assert "HC_ALL_SIZES_INFEASIBLE" in _codes(config, problem, _data(forced_exits=3))


def test_mandatory_holds_cannot_exceed_the_size(problem) -> None:  # type: ignore[no-untyped-def]
    config = with_mandate()
    assert "HC_ALL_SIZES_INFEASIBLE" in _codes(config, problem, _data(mandatory_holds=HELD + 1))


def test_target_outside_the_policy_and_missing_cardinality_are_infeasible(problem) -> None:  # type: ignore[no-untyped-def]
    assert "HC_CARDINALITY_TARGET_OUTSIDE_POLICY" in _codes(
        with_mandate(target_size=HELD + 3), problem
    )
    assert _codes(with_mandate(), problem, sizes=()).issuperset({"HC_CARDINALITY_UNDEFINED"})


def test_non_long_only_problems_skip_the_simplex_bounds(problem) -> None:  # type: ignore[no-untyped-def]
    config = with_mandate(min_volatility=0.50, **BAND_PARAMS)
    assert "HC_VOLATILITY_MIN_ABOVE_ATTAINABLE" not in _codes(
        config, problem, _data(long_only=False)
    )
