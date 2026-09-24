"""CON-010, CON-011, CON-019, FEA-002: nuevos activos, swaps, cardinalidad y factibilidad de tamaño.

Formulación heurística del Bloque 3 sobre conjuntos de ``AssetID`` (la MIQP exacta con variables
binarias es del Bloque 4). Los valores esperados se enumeran a mano.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.constraints import (
    CompositionLimits,
    check_cardinality,
    limit_violations,
    move_violations,
    new_assets,
    removed_assets,
    swap_count,
)
from portfolio_engine.constraints.integer import (
    CARDINALITY,
    MANDATORY_ASSET_REMOVED,
    MAX_NEW_ASSETS,
    MAX_SWAPS,
)

pytestmark = pytest.mark.unit

CURRENT = {"A", "B", "C", "D"}


def test_new_removed_and_swap_counts_follow_the_set_definitions() -> None:
    assert new_assets(CURRENT, {"A", "B", "X", "Y"}) == {"X", "Y"}
    assert removed_assets(CURRENT, {"A", "B", "X", "Y"}) == {"C", "D"}
    assert swap_count(CURRENT, {"A", "B", "X", "Y"}) == 2
    assert swap_count(CURRENT, {"A", "B", "C", "X"}) == 1
    assert swap_count(CURRENT, CURRENT) == 0
    # con tamaños distintos (ADD/DROP) los swaps son el mayor de nuevos y retirados
    assert swap_count(CURRENT, {"A", "B", "C", "D", "X"}) == 1
    assert swap_count(CURRENT, {"A", "B"}) == 2


def test_maximum_new_assets_is_checked_against_the_current_composition() -> None:
    limits = CompositionLimits(4, max_new_assets=1, max_swaps=None, mandatory=frozenset())
    assert move_violations(limits, CURRENT, {"A", "B", "C", "X"}) == ()
    assert move_violations(limits, CURRENT, {"A", "B", "X", "Y"}) == (MAX_NEW_ASSETS,)
    zero = CompositionLimits(4, 0, None, frozenset())
    assert move_violations(zero, CURRENT, CURRENT) == ()
    assert move_violations(zero, CURRENT, {"A", "B", "C", "X"}) == (MAX_NEW_ASSETS,)


def test_maximum_swaps_is_checked_independently_from_new_assets() -> None:
    limits = CompositionLimits(None, max_new_assets=None, max_swaps=1, mandatory=frozenset())
    assert move_violations(limits, CURRENT, {"A", "B", "C", "X"}) == ()
    assert move_violations(limits, CURRENT, {"A", "B", "X", "Y"}) == (MAX_SWAPS,)
    both = CompositionLimits(None, 1, 1, frozenset())
    assert move_violations(both, CURRENT, {"A", "B", "X", "Y"}) == (MAX_NEW_ASSETS, MAX_SWAPS)


def test_mandatory_assets_cannot_leave() -> None:
    limits = CompositionLimits(4, None, None, mandatory=frozenset({"C"}))
    assert move_violations(limits, CURRENT, {"A", "B", "C", "X"}) == ()
    assert move_violations(limits, CURRENT, {"A", "B", "D", "X"}) == (MANDATORY_ASSET_REMOVED,)


def test_cardinality_is_only_required_of_final_compositions() -> None:
    limits = CompositionLimits(4, None, None, frozenset())
    assert limit_violations(limits, CURRENT, {"A", "B", "C", "X"}) == ()
    assert limit_violations(limits, CURRENT, {"A", "B", "C"}) == (CARDINALITY,)
    assert (
        move_violations(limits, CURRENT, {"A", "B", "C"}) == ()
    )  # intermedia: tamaño en corrección
    assert limit_violations(CompositionLimits(None, None, None, frozenset()), CURRENT, {"A"}) == ()


def test_duplicates_are_not_counted_twice() -> None:
    limits = CompositionLimits(2, None, None, frozenset())
    assert limit_violations(limits, CURRENT, ["A", "A", "B"]) == ()  # el conjunto es {A, B}


@pytest.mark.parametrize(
    ("target", "lower", "upper", "expected"),
    [
        (3, [0.0] * 5, [0.5] * 5, ()),  # 3·0,5 ≥ 1 y Σ mínimos 0
        (2, [0.0] * 5, [0.4] * 5, ("CARDINALITY_MAX_WEIGHTS_BELOW_BUDGET",)),  # 2·0,4 < 1
        (3, [0.4] * 5, [1.0] * 5, ("CARDINALITY_MIN_WEIGHTS_EXCEED_BUDGET",)),  # 3·0,4 > 1
        (6, [0.0] * 5, [1.0] * 5, ("TARGET_SIZE_EXCEEDS_AVAILABLE_ASSETS",)),
        (2, [0.5, 0.5, 0.05, 0.05, 0.05], [1.0] * 5, ()),  # K menores mínimos: 0,05 + 0,05
        (
            3,
            [0.0, 0.1, 0.2, 0.3, 0.6],
            [0.3, 0.3, 0.3, 0.3, 0.3],
            ("CARDINALITY_MAX_WEIGHTS_BELOW_BUDGET",),  # Σ de los 3 mayores MaxWeight = 0,9 < 1
        ),
    ],
)
def test_cardinality_feasibility_uses_the_k_extreme_bounds(
    target: int, lower: list[float], upper: list[float], expected: tuple[str, ...]
) -> None:
    causes = check_cardinality(target, np.array(lower), np.array(upper), 1.0, 1e-9)
    assert tuple(cause.code for cause in causes) == expected
    assert all(cause.detail for cause in causes)


def test_minimum_weight_is_conditional_to_holding_so_only_the_k_smallest_matter() -> None:
    """A-30: un MinWeight alto en muchos activos no impide una composición que elija los baratos."""
    lower = np.array([0.6, 0.6, 0.6, 0.1, 0.1])
    upper = np.ones(5)
    assert check_cardinality(2, lower, upper, 1.0, 1e-9) == ()
    assert check_cardinality(4, lower, upper, 1.0, 1e-9)  # 0,1 + 0,1 + 0,6 + 0,6 > 1
