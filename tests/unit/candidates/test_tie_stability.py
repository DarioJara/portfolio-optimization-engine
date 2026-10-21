"""F-B55-1 (AUDIT_BLOCK_5_5, INVESTIGATION_F_B55_1): estabilidad de la búsqueda ante empates de ulp.

Composiciones con la **misma utilidad matemática** (p. ej. un entrante que recibe peso cero, o dos
activos idénticos) difieren en el último ulp de su mejora según el orden de las sumas de la CPU. El
orden por ``(válida, -mejora, hash)`` solo desempata por hash si las mejoras son idénticas en coma
flotante, así que el ruido decidía qué finalistas se conservaban: en un lote de referencia la
búsqueda devolvía 11 o 12 composiciones según la CPU. ``rank_nodes`` trata como empate las mejoras a
menos de ``improvement_tolerance`` (la tolerancia con la que el propio motor decide que dos
utilidades no difieren) y desempata por hash.

Los tests no dependen de la CPU: inyectan los ulp de forma determinista.
"""

from __future__ import annotations

import dataclasses
import random

import numpy as np
import pytest

from portfolio_engine.candidates import (
    EvaluationBudget,
    NeighborhoodExpander,
    SearchNode,
    rank_nodes,
    select_survivors,
)
from portfolio_engine.models.enums import CandidateOrigin
from tests.fixtures.candidates import (
    random_problem,
    root_node,
    search,
    services_for,
    with_candidates,
)
from tests.fixtures.problems import base_config, make_problem

pytestmark = pytest.mark.unit

LAM = 4.0
HELD = [0, 1, 2, 3]
TOLERANCE = 1e-9


def _children() -> list[SearchNode]:
    config = base_config(
        candidates={
            "beam_width": 6,
            "swap_orders": (1,),
            "utility_risk_aversions": (LAM,),
            "shortlist_in": 8,
            "shortlist_out": 4,
            "max_evaluations": 500,
        }
    )
    problem = random_problem(10, HELD, 5, config)
    services = services_for(problem, config)
    root, baseline = root_node(services, problem, LAM)
    expansion = NeighborhoodExpander(services).expand(
        root,
        LAM,
        1,
        {root.composition_hash},
        EvaluationBudget(500),
        baseline,
        CandidateOrigin.BEAM_SEARCH,
    )
    children = list(expansion.children)
    assert len(children) >= 8
    return children


def _with_gain(node: SearchNode, gain: float) -> SearchNode:
    return dataclasses.replace(node, estimate=dataclasses.replace(node.estimate, utility_gain=gain))


def _tied(children: list[SearchNode], ulps: list[int], group: int = 4) -> list[SearchNode]:
    """Los ``group`` primeros hijos con la misma mejora ± ``ulps`` ulp; el resto sin tocar."""
    base = max(node.gain for node in children) + 1.0  # por encima del resto: el empate es el mejor
    tied = []
    for node, shift in zip(children[:group], ulps, strict=False):
        gain = base
        for _ in range(abs(shift)):
            gain = float(np.nextafter(gain, np.inf if shift > 0 else -np.inf))
        tied.append(_with_gain(node, gain))
    return tied + list(children[group:])


def test_tied_gains_are_ordered_by_hash_whatever_the_last_ulp() -> None:
    children = _children()
    expected_hashes = sorted(node.composition_hash for node in children[:4])
    rng = random.Random(0)
    for _ in range(200):
        nodes = _tied(children, [rng.randint(-3, 3) for _ in range(4)])
        ranked = rank_nodes(nodes, TOLERANCE)
        assert [n.composition_hash for n in ranked[:4]] == expected_hashes
        assert [n.composition_hash for n in ranked] == [
            n.composition_hash for n in rank_nodes(list(reversed(nodes)), TOLERANCE)
        ]  # independiente del orden de entrada


def test_the_exact_float_order_is_not_stable_under_ulp_noise() -> None:
    """Demuestra el defecto: ordenar solo por ``ranking_key`` cambia con 1 ulp (F-B55-1)."""
    children = _children()
    expected = sorted(node.composition_hash for node in children[:4])
    rng = random.Random(0)
    orders = {
        tuple(
            n.composition_hash
            for n in sorted(
                _tied(children, [rng.randint(-3, 3) for _ in range(4)]), key=SearchNode.ranking_key
            )[:4]
        )
        for _ in range(200)
    }
    assert len(orders) > 1 and tuple(expected) in orders


def test_survivor_selection_is_invariant_to_ulp_noise_in_tied_gains() -> None:
    children = _children()
    rng = random.Random(1)
    selections = {
        tuple(
            n.composition_hash
            for n in select_survivors(
                _tied(children, [rng.randint(-3, 3) for _ in range(4)]), 3, 1, TOLERANCE
            )
        )
        for _ in range(200)
    }
    assert len(selections) == 1


def test_gains_that_differ_by_more_than_the_tolerance_keep_their_gain_order() -> None:
    children = _children()
    nodes = [_with_gain(node, 1.0 + 10 * TOLERANCE * k) for k, node in enumerate(children[:6])]
    ranked = rank_nodes(nodes, TOLERANCE)
    assert [n.gain for n in ranked] == sorted((n.gain for n in nodes), reverse=True)
    assert rank_nodes(nodes, 0.0) == sorted(nodes, key=SearchNode.ranking_key)


def test_a_near_tie_inside_the_tolerance_is_resolved_by_hash_not_by_gain() -> None:
    children = _children()
    low, high = children[0], children[1]
    nodes = [_with_gain(low, 1.0), _with_gain(high, 1.0 + TOLERANCE / 10)]
    ranked = rank_nodes(nodes, TOLERANCE)
    assert [n.composition_hash for n in ranked] == sorted(n.composition_hash for n in ranked)
    far = [_with_gain(low, 1.0), _with_gain(high, 1.0 + 3 * TOLERANCE)]
    assert rank_nodes(far, TOLERANCE)[0].composition_hash == high.composition_hash


def test_valid_estimates_still_come_before_invalid_ones_even_with_a_better_gain() -> None:
    children = _children()
    invalid = dataclasses.replace(
        children[0],
        estimate=dataclasses.replace(
            children[0].estimate, satisfies_constraints=False, utility_gain=5.0
        ),
    )
    valid = _with_gain(children[1], 0.1)
    assert rank_nodes([invalid, valid], TOLERANCE)[0] is valid
    assert rank_nodes([], TOLERANCE) == []


# ---------------------------------------------------------------------------- nivel de motor


def _clone_problem(config):  # type: ignore[no-untyped-def]
    """Universo con dos pares de activos idénticos (clones): sustituir uno por su clon da la misma
    utilidad, es decir, empates exactos entre composiciones."""
    base = random_problem(8, HELD, 7, config)
    mu = base.risk_model.expected_returns.values
    sigma = base.risk_model.covariance.matrix
    source = [0, 1, 2, 3, 4, 5, 6, 7, 4, 5]  # los activos 8 y 9 clonan 4 y 5
    mu_c = mu[source]
    sigma_c = sigma[np.ix_(source, source)].copy()
    current = [0.25, 0.25, 0.25, 0.25] + [0.0] * 6
    return make_problem(
        mu_c, sigma_c, current, config, universe_overrides={"MaxWeight": [0.6] * 10}
    )


def _perturbed(problem, seed: int, eps: float):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(seed)
    risk = problem.risk_model
    n = risk.covariance.matrix.shape[0]
    noise = rng.standard_normal((n, n))
    noise = (noise + noise.T) / 2
    covariance = dataclasses.replace(
        risk.covariance, matrix=risk.covariance.matrix * (1 + eps * noise)
    )
    expected = dataclasses.replace(
        risk.expected_returns,
        values=risk.expected_returns.values
        * (1 + eps * rng.standard_normal(risk.expected_returns.values.shape)),
    )
    return dataclasses.replace(
        problem,
        risk_model=dataclasses.replace(risk, covariance=covariance, expected_returns=expected),
    )


def test_the_candidate_set_does_not_depend_on_ulp_noise_with_tied_compositions() -> None:
    """Misma lista de composiciones candidatas con y sin ruido de 1 ulp en ``μ`` y ``Σ``."""
    config = with_candidates(
        base_config(),
        beam_width=3,
        max_levels=2,
        swap_orders=(1,),
        local_search_starts=1,
        utility_risk_aversions=(1.0, 4.0, 16.0),
        max_candidates=12,
        shortlist_in=10,
        shortlist_out=4,
        max_evaluations=300,
    )
    problem = _clone_problem(config)
    reference = {c.composition_id for c in search(config, problem).compositions}
    assert len(reference) > 4
    for seed in range(12):
        noisy = _perturbed(problem, seed, 1e-16)
        got = {c.composition_id for c in search(config, noisy).compositions}
        assert got == reference, (seed, sorted(got ^ reference))
