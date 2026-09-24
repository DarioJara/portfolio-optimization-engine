"""CAN-015, CAN-007 (L-4 de AUDIT_BLOCK_3): una composición ya visitada no se reevalúa.

El mutante ``dedup_off`` (ignorar ``visited``) sobrevivió a la suite del Bloque 3: nada comprobaba
que una composición alcanzada de nuevo no se evalúe otra vez. Un evaluador contador registra cada
llamada ``(CompositionHash, λ)``: con la deduplicación intacta ninguna pareja se evalúa dos veces.
"""

from __future__ import annotations

import itertools
from collections import Counter

import pytest

from portfolio_engine.candidates import (
    CandidateEngine,
    EvaluationBudget,
    MemoizedEvaluator,
    NeighborhoodExpander,
    ProjectedWeightsEvaluator,
    composition_hash_of,
)
from portfolio_engine.models.enums import CandidateOrigin, EvaluationMode
from portfolio_engine.validation import SolutionValidator, ValidationTolerances
from tests.fixtures.candidates import context_of, random_problem, root_node, services_for
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

LAM = 4.0
HELD = [0, 1, 2, 3]
BASELINE_LEVEL = 1


class CountingEvaluator:
    """Envuelve el evaluador real y cuenta las evaluaciones por ``(CompositionHash, λ)``."""

    def __init__(self, config) -> None:  # type: ignore[no-untyped-def]
        validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
        self._inner = ProjectedWeightsEvaluator(config.candidates.refinement_iterations, validator)
        self.calls: Counter[tuple[str, float]] = Counter()

    @property
    def mode(self) -> EvaluationMode:
        return self._inner.mode

    def evaluate(self, prepared, risk_aversion, baseline_utility):  # type: ignore[no-untyped-def]
        self.calls[(prepared.composition_hash, risk_aversion)] += 1
        return self._inner.evaluate(prepared, risk_aversion, baseline_utility)

    def evaluations_of(self, digest: str) -> int:
        return sum(count for (key, _), count in self.calls.items() if key == digest)


def _config(**changes):  # type: ignore[no-untyped-def]
    values = {
        "beam_width": 3,
        "max_levels": 3,
        "swap_orders": (1,),
        "local_search_starts": 2,
        "utility_risk_aversions": (LAM,),
        "max_candidates": 40,
        "refinement_iterations": 5,
        "max_evaluations": 400,
        "stagnation_levels": 5,
        "shortlist_in": 6,
        "shortlist_out": 4,
    }
    values.update(changes)
    return base_config(candidates=values)


def _setup(config, seed=5):  # type: ignore[no-untyped-def]
    problem = random_problem(10, HELD, seed, config)
    counting = CountingEvaluator(config)
    services = services_for(problem, config, counting)
    root, baseline = root_node(services, problem, LAM)
    return problem, services, counting, root, baseline


def _expand(expander, node, visited, baseline):  # type: ignore[no-untyped-def]
    return expander.expand(
        node,
        LAM,
        BASELINE_LEVEL,
        visited,
        EvaluationBudget(10_000),
        baseline,
        CandidateOrigin.BEAM_SEARCH,
    )


def test_a_composition_reached_from_two_different_parents_is_evaluated_once() -> None:
    config = _config()
    _, services, counting, root, baseline = _setup(config)
    expander = NeighborhoodExpander(services)
    visited = {root.composition_hash}
    first_level = _expand(expander, root, visited, baseline).children
    parent_p, parent_q = first_level[0], first_level[1]
    # composiciones que cada padre produciría por separado (con su propio ``visited``)
    alone_p = _expand(
        expander, parent_p, {root.composition_hash, parent_p.composition_hash}, baseline
    )
    alone_q = _expand(
        expander, parent_q, {root.composition_hash, parent_q.composition_hash}, baseline
    )
    shared = {c.composition_hash for c in alone_p.children} & {
        c.composition_hash for c in alone_q.children
    }
    assert shared, "el escenario debe tener descendientes comunes para que el test no sea vacío"
    counting.calls.clear()
    visited = {root.composition_hash, parent_p.composition_hash, parent_q.composition_hash}
    from_p = _expand(expander, parent_p, visited, baseline)
    from_q = _expand(expander, parent_q, visited, baseline)
    assert from_q.duplicates >= len(shared)
    assert not shared & {c.composition_hash for c in from_q.children}
    assert set(counting.calls.values()) == {1}
    for digest in shared:
        assert counting.evaluations_of(digest) == 1
    assert from_p.evaluated + from_q.evaluated == sum(counting.calls.values())


def test_reordering_the_asset_ids_never_creates_a_new_composition() -> None:
    config = _config()
    _, services, counting, root, baseline = _setup(config)
    expander = NeighborhoodExpander(services)
    child = _expand(expander, root, {root.composition_hash}, baseline).children[0]
    ids = list(child.prepared.asset_ids)
    hashes = {composition_hash_of(order) for order in itertools.permutations(ids)}
    assert hashes == {child.composition_hash}  # determinista e invariante al orden
    assert composition_hash_of([*ids[:-1], "ZZZ"]) != child.composition_hash
    # ``visited`` contiene el hash calculado con los AssetID al revés: no se reevalúa
    visited = {root.composition_hash, composition_hash_of(reversed(ids))}
    counting.calls.clear()
    again = _expand(expander, root, visited, baseline)
    assert counting.evaluations_of(child.composition_hash) == 0
    assert again.duplicates >= 1
    assert child.composition_hash not in {c.composition_hash for c in again.children}


def test_a_cycle_of_swaps_does_not_reevaluate_the_composition_it_came_from() -> None:
    config = _config()
    _, services, counting, root, baseline = _setup(config)
    expander = NeighborhoodExpander(services)
    visited = {root.composition_hash}
    child = _expand(expander, root, visited, baseline).children[0]
    counting.calls.clear()
    grandchildren = _expand(expander, child, visited, baseline)
    # el vecino que deshace el intercambio es la propia raíz: ya vista, no se evalúa
    assert counting.evaluations_of(root.composition_hash) == 0
    assert root.composition_hash not in {c.composition_hash for c in grandchildren.children}
    assert grandchildren.duplicates >= 1


def test_no_composition_is_evaluated_twice_in_a_full_search() -> None:
    """Búsqueda completa (haz + pulido, varios perfiles λ): ninguna ``(composición, λ)`` se repite
    y las evaluaciones del contador coinciden con las declaradas en los diagnósticos."""
    profiles = (1.0, 4.0, 16.0)
    config = _config(utility_risk_aversions=profiles)
    problem = random_problem(10, HELD, 5, config)
    counting = CountingEvaluator(config)
    result = CandidateEngine(config, counting).search(
        problem.state.composition(), context_of(problem)
    )
    assert set(counting.calls.values()) == {1}
    diagnostics = result.diagnostics
    roots = len(
        profiles
    )  # la composición actual de cada perfil se evalúa una vez fuera del presupuesto
    # cada evaluación del presupuesto y cada raíz llegó al evaluador real; el ensamblado añade solo
    # las estimaciones en perfiles ajenos que aún no existían
    assert sum(counting.calls.values()) >= diagnostics.total_evaluated + roots
    assert sum(stage.duplicates_skipped for stage in diagnostics.stages) > 0
    # la referencia se reevaluaba una vez por perfil en el ensamblado: ahora sale de la memoria
    assert diagnostics.evaluation_cache_hits >= len(profiles)


def test_the_memo_key_includes_lambda_and_the_reference_utility() -> None:
    config = _config()
    _, _, counting, root, baseline = _setup(config)
    memo = MemoizedEvaluator(counting)
    prepared = root.prepared
    counting.calls.clear()
    first = memo.evaluate(prepared, LAM, baseline)
    assert memo.evaluate(prepared, LAM, baseline) is first and memo.hits == 1
    memo.evaluate(prepared, LAM * 2, baseline)  # otro perfil λ: se evalúa
    memo.evaluate(prepared, LAM, baseline + 0.01)  # otra utilidad de referencia: se evalúa
    assert sum(counting.calls.values()) == 3 and memo.hits == 1
