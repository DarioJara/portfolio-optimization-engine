"""CON-013, CON-022, VAL-005 (L-1 de AUDIT_BLOCK_2): la política de restringidos tiene una única
regla de precedencia y el compilador y el validador (duplicados a propósito) coinciden.

El validador re-deriva la política desde ``RestrictedExistingPositionPolicy`` y ``w_current``, sin
usar los límites compilados, para no heredar un error del compilador (VAL-001). Esa duplicación
es deliberada; este test garantiza que ambas implementaciones aceptan exactamente los mismos pesos.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.constraints import build_constraint_set
from portfolio_engine.data.validation import effective_restricted_policy
from portfolio_engine.models.enums import RestrictedExistingPositionPolicy
from portfolio_engine.models.portfolio import resolve_restricted_policy
from portfolio_engine.validation import SolutionValidator, ValidationContext, ValidationTolerances
from tests.fixtures.problems import (
    base_config,
    composition_inputs,
    make_problem,
    policy_config,
    restricted_universe,
    spec_with,
)

pytestmark = pytest.mark.unit

Policy = RestrictedExistingPositionPolicy
MU = np.array([0.05, 0.08, 0.12, 0.10])
SIGMA = np.diag([0.01, 0.02, 0.03, 0.04])
CURRENT = [0.4, 0.3, 0.2, 0.1]
HELD_INDEX, HELD_WEIGHT = 1, 0.3
CANDIDATES = (0.0, 0.1, 0.3, 0.35, 0.5)  # reducción, igual, aumento; dentro de los límites de peso


def _context(  # type: ignore[no-untyped-def]
    policy: Policy, overrides: dict[str, list[object]], current: list[float] = CURRENT
):
    config = policy_config(base_config(), policy)
    problem = make_problem(
        MU,
        SIGMA,
        current,
        config,
        universe_overrides=overrides,
        composition=("A000", "A001", "A002", "A003"),
    )
    inputs = composition_inputs(problem, config)
    context = ValidationContext(inputs.mu, inputs.sigma, inputs.cost_model)
    validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
    return inputs.compiled, context, validator


@pytest.mark.parametrize("policy", list(Policy))
def test_compiler_and_validator_accept_the_same_weights_for_a_held_restricted_asset(
    policy: RestrictedExistingPositionPolicy,
) -> None:
    compiled, context, validator = _context(policy, restricted_universe(4, [HELD_INDEX]))
    for value in CANDIDATES:
        weights = np.array(CURRENT, dtype=np.float64)
        weights[HELD_INDEX] = value
        weights[0] += HELD_WEIGHT - value  # el resto del presupuesto va al activo 0
        low, high = compiled.lower[HELD_INDEX], compiled.upper[HELD_INDEX]
        admitted_by_compiler = bool(low - 1e-9 <= value <= high + 1e-9)
        report = validator.validate(weights, compiled, context)
        violated = {v.constraint_id.split(":")[0] for v in report.violations}
        assert admitted_by_compiler == ("RESTRICTED_POLICY" not in violated), (policy, value)


@pytest.mark.parametrize("policy", list(Policy))
def test_compiler_and_validator_agree_that_a_restricted_asset_not_held_is_never_bought(
    policy: RestrictedExistingPositionPolicy,
) -> None:
    current = [0.4, 0.3, 0.3, 0.0]  # el activo 3 es restringido y no está en cartera
    compiled, context, validator = _context(policy, restricted_universe(4, [3]), current)
    for value in (0.0, 0.05, 0.1):
        weights = np.array([0.4, 0.3, 0.3 - value, value])
        admitted = bool(compiled.lower[3] - 1e-9 <= value <= compiled.upper[3] + 1e-9)
        report = validator.validate(weights, compiled, context)
        violated = {v.constraint_id.split(":")[0] for v in report.violations}
        assert admitted == ("RESTRICTED_POLICY" not in violated), (policy, value)
        assert admitted == (value == 0.0)


def test_policy_precedence_has_a_single_implementation() -> None:
    """Override de cartera > política global > ``None``; ``ConstraintSet`` y el validador de
    carteras (``data``) delegan en la misma función de ``models``."""
    base = base_config()
    global_policy = base.constraints.restricted_existing_position_policy
    assert global_policy is not None
    override = next(p for p in Policy if p is not global_policy)
    spec = spec_with(restricted_existing_position_policy=override)
    no_policy = dataclasses.replace(base.constraints, restricted_existing_position_policy=None)
    cases = [
        (None, base.constraints, global_policy),
        (spec_with(), base.constraints, global_policy),
        (spec, base.constraints, override),
        (None, no_policy, None),
        (spec, no_policy, override),
    ]
    for portfolio_spec, constraints, expected in cases:
        assert (
            resolve_restricted_policy(
                portfolio_spec, constraints.restricted_existing_position_policy
            )
            is expected
        )
        assert effective_restricted_policy(portfolio_spec, constraints) is expected
        built = build_constraint_set(constraints, portfolio_spec, "P1", None)
        assert built.restricted_policy is expected
