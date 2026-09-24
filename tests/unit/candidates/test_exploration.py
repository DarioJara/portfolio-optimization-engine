"""CAN-008: exploración vs explotación parametrizable, con semilla determinista."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.candidates import ExplorationPolicy, component_counts
from portfolio_engine.config import ExplorationMix
from portfolio_engine.models.enums import CandidateType
from portfolio_engine.parallel import derive_seed

pytestmark = pytest.mark.unit

HC, DIV, EXP = (
    CandidateType.HIGH_CONVICTION,
    CandidateType.DIVERSIFICATION,
    CandidateType.EXPLORATION,
)


def test_component_counts_follow_the_configured_shares_with_largest_remainder() -> None:
    mix = ExplorationMix(7.0, 2.0, 1.0)
    assert component_counts(mix, 10) == (7, 2, 1)
    assert component_counts(mix, 20) == (14, 4, 2)
    assert component_counts(mix, 0) == (0, 0, 0)
    for k in range(0, 40):
        assert sum(component_counts(mix, k)) == k  # nunca se pierde ni sobra un puesto
    # Resto mayor: 5 · (0.7, 0.2, 0.1) = (3.5, 1.0, 0.5) → el resto 0.5 empata y gana el primero.
    assert component_counts(mix, 5) == (4, 1, 0)


def test_shares_are_relative_weights_not_percentages() -> None:
    assert component_counts(ExplorationMix(70, 20, 10), 10) == component_counts(
        ExplorationMix(0.7, 0.2, 0.1), 10
    )
    assert component_counts(ExplorationMix(1.0, 0.0, 0.0), 6) == (6, 0, 0)
    assert component_counts(ExplorationMix(0.0, 0.0, 1.0), 6) == (0, 0, 6)


def _data(size: int = 20):  # type: ignore[no-untyped-def]
    score = np.linspace(0.0, 1.0, size)  # el mejor es el último
    diversification = score[::-1].copy()  # el mejor diversificador es el primero
    return score, diversification, np.ones(size, dtype=bool)


def test_components_pick_conviction_diversifiers_and_a_random_sample() -> None:
    score, diversification, usable = _data()
    policy = ExplorationPolicy(ExplorationMix(5.0, 3.0, 2.0))
    rng = np.random.default_rng(derive_seed(7, "P1", "BASE"))
    chosen, kinds = policy.select(score, diversification, usable, 10, rng)
    by_kind = {
        kind: [int(i) for i, k in zip(chosen, kinds, strict=True) if k is kind]
        for kind in (HC, DIV, EXP)
    }
    assert by_kind[HC] == [15, 16, 17, 18, 19]  # mayor score
    assert by_kind[DIV] == [0, 1, 2]  # mayor diversificación entre los restantes
    assert len(by_kind[EXP]) == 2 and set(by_kind[EXP]) <= set(range(3, 15))
    assert sorted(chosen.tolist()) == chosen.tolist() and len(set(chosen.tolist())) == 10


def test_exploration_is_deterministic_and_depends_on_the_seed() -> None:
    score, diversification, usable = _data(60)
    policy = ExplorationPolicy(ExplorationMix(1.0, 1.0, 8.0))

    def run(seed: int) -> list[int]:
        rng = np.random.default_rng(derive_seed(seed, "P1", "BASE", "level-1"))
        return policy.select(score, diversification, usable, 10, rng)[0].tolist()

    assert run(1) == run(1)
    assert run(1) != run(2)


def test_unusable_assets_are_never_chosen_and_short_pools_fall_back_to_conviction() -> None:
    score, diversification, usable = _data(8)
    usable[[0, 7]] = False
    policy = ExplorationPolicy(ExplorationMix(1.0, 1.0, 1.0))
    chosen, kinds = policy.select(score, diversification, usable, 10, np.random.default_rng(0))
    assert set(chosen.tolist()) == {1, 2, 3, 4, 5, 6}  # solo los 6 utilizables
    assert len(kinds) == 6
    empty, no_kinds = policy.select(
        score, diversification, np.zeros(8, dtype=bool), 3, np.random.default_rng(0)
    )
    assert empty.size == 0 and no_kinds == ()


def test_assets_without_a_diversification_value_skip_only_that_component() -> None:
    score, diversification, usable = _data(10)
    diversification[:] = np.nan
    policy = ExplorationPolicy(ExplorationMix(1.0, 1.0, 0.0))
    chosen, kinds = policy.select(score, diversification, usable, 4, np.random.default_rng(0))
    assert len(chosen) == 4 and set(kinds) == {HC}  # el cupo de diversificación pasa a convicción


def test_derive_seed_is_stable_and_sensitive_to_every_key() -> None:
    assert derive_seed(1, "a", "b") == derive_seed(1, "a", "b")
    assert (
        len(
            {
                derive_seed(1, "a", "b"),
                derive_seed(2, "a", "b"),
                derive_seed(1, "b", "a"),
                derive_seed(1, "a"),
            }
        )
        == 4
    )
