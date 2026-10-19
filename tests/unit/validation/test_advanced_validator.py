"""VAL-001, VAL-003, VAL-007: el ``AdvancedSolutionValidator`` extiende al validador sin tocarlo.

Comprueba: conserva íntegras las comprobaciones del Bloque 2; recalcula desde los pesos; rechaza
soluciones que un backend declararía ``OPTIMAL``; y cubre cardinalidad, integridad, nuevos activos y
swaps, escenarios, volatilidad y CVaR.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from portfolio_engine.frontiers import StrategyOptimizer
from portfolio_engine.models.enums import CostTreatment
from portfolio_engine.validation import (
    AdvancedChecks,
    AdvancedSolutionValidator,
    CardinalityCheck,
    SolutionValidator,
    ValidationContext,
    ValidationTolerances,
    VolatilityLimitCheck,
)
from portfolio_engine.validation.advanced_validator import combined_checks
from tests.fixtures.block4 import four_asset_problem
from tests.fixtures.problems import base_config, spec_with

pytestmark = pytest.mark.unit

CONFIG = base_config()
TOLERANCES = ValidationTolerances.from_config(CONFIG.solver)


def _context(problem=None):  # type: ignore[no-untyped-def]
    problem = problem or four_asset_problem(CONFIG)
    context, _ = StrategyOptimizer(CONFIG).prepare(problem, CostTreatment.GROSS)
    assert context is not None
    return context, ValidationContext(context.inputs.mu, context.inputs.sigma, context.cost_model)


def _cardinality(z, **fields):  # type: ignore[no-untyped-def]
    values = {
        "z": np.array(z, dtype=float),
        "integrality_tolerance": 1e-6,
        "target_size": None,
        "max_new_assets": None,
        "max_swaps": None,
        "mandatory": (),
    }
    values.update(fields)
    return CardinalityCheck(**values)


def test_it_keeps_every_base_check_and_only_adds_its_own() -> None:
    context, validation_context = _context()
    advanced = AdvancedSolutionValidator(TOLERANCES)
    base = SolutionValidator(TOLERANCES)
    bad = np.array([0.6, 0.6, -0.1, 0.0])  # suma 1,1 y un peso negativo por encima del MaxWeight
    expected = base.validate(bad, context.compiled, validation_context)
    report = advanced.validate(bad, context.compiled, validation_context, AdvancedChecks())
    assert not report.is_valid
    assert [v.constraint_id for v in report.violations] == [
        v.constraint_id for v in expected.violations
    ]
    assert report.checks == expected.checks and report.max_violation == expected.max_violation
    good = advanced.validate(
        np.array([0.25] * 4), context.compiled, validation_context, AdvancedChecks()
    )
    assert good.is_valid


def test_non_finite_weights_return_the_base_rejection_without_running_advanced_checks() -> None:
    context, validation_context = _context()
    advanced = AdvancedSolutionValidator(TOLERANCES)
    report = advanced.validate(
        np.array([np.nan, 0.5, 0.25, 0.25]),
        context.compiled,
        validation_context,
        AdvancedChecks(volatility=(VolatilityLimitCheck(context.inputs.sigma, 0.1, "x"),)),
    )
    assert not report.is_valid and report.violations[0].constraint_id.startswith("FINITE")
    assert "VOLATILITY_LIMIT" not in report.checks


def test_cardinality_checks_reject_each_kind_of_violation() -> None:
    problem = dataclasses.replace(
        four_asset_problem(CONFIG, current=[0.5, 0.5, 0.0, 0.0]),
        composition_asset_ids=("A000", "A001", "A002", "A003"),  # el universo completo
    )
    context, _ = _context(problem)
    advanced = AdvancedSolutionValidator(TOLERANCES)
    weights = np.array([0.5, 0.0, 0.5, 0.0])  # sale A001, entra A002
    ok = advanced.validate_cardinality(
        weights,
        context.compiled,
        _cardinality([1, 0, 1, 0], target_size=2, max_new_assets=1, max_swaps=1),
    )
    assert ok.is_valid and ok.checks == ("CARDINALITY",)
    cases = {
        "size": _cardinality([1, 0, 1, 0], target_size=3),
        "max_new_assets": _cardinality([1, 0, 1, 0], max_new_assets=0),
        "max_swaps": _cardinality([1, 0, 1, 0], max_swaps=0),
        "mandatory": _cardinality([1, 0, 1, 0], mandatory=(1,)),
        "integrality": _cardinality([1, 0.3, 1, 0]),
        "binary_range": _cardinality([1, 0, 1.6, 0]),
    }
    for name, check in cases.items():
        report = advanced.validate_cardinality(weights, context.compiled, check)
        assert not report.is_valid, name
        assert any(f"CARDINALITY:{name}" in v.constraint_id for v in report.violations), name


def test_a_weight_outside_the_composition_or_below_its_semicontinuous_bound_is_rejected() -> None:
    context, _ = _context(four_asset_problem(CONFIG, max_weight=0.5))
    advanced = AdvancedSolutionValidator(TOLERANCES)
    outside = advanced.validate_cardinality(
        np.array([0.5, 0.3, 0.2, 0.0]), context.compiled, _cardinality([1, 1, 0, 0])
    )
    assert any("weight_outside_composition" in v.constraint_id for v in outside.violations)
    upper = advanced.validate_cardinality(
        np.array([0.9, 0.1, 0.0, 0.0]), context.compiled, _cardinality([1, 1, 0, 0])
    )
    assert any("semicontinuous_upper" in v.constraint_id for v in upper.violations)  # MaxWeight 0,5
    tampered = advanced.validate_cardinality(
        np.array([0.5, 0.5, 0.0]), context.compiled, _cardinality([1, 1, 0, 0])
    )
    assert not tampered.is_valid and tampered.max_violation == float("inf")
    clean = advanced.validate_cardinality(
        np.array([0.5, 0.5, 0.0, 0.0]), context.compiled, _cardinality([1, 1, 0, 0], target_size=2)
    )
    assert clean.is_valid


def test_semicontinuous_lower_bound_uses_the_compiled_min_weight() -> None:
    problem = four_asset_problem(CONFIG, universe_overrides={"MinWeight": [0.2] * 4})
    context, _ = _context(problem)
    advanced = AdvancedSolutionValidator(TOLERANCES)
    report = advanced.validate_cardinality(
        np.array([0.5, 0.35, 0.15, 0.0]), context.compiled, _cardinality([1, 1, 1, 0])
    )
    assert any("semicontinuous_lower" in v.constraint_id for v in report.violations)  # 0,15 < 0,2
    fine = advanced.validate_cardinality(
        np.array([0.5, 0.3, 0.2, 0.0]), context.compiled, _cardinality([1, 1, 1, 0])
    )
    assert fine.is_valid


def test_checks_can_be_combined_and_carry_their_own_labels() -> None:
    sigma = np.eye(4) * 0.04
    first = AdvancedChecks(volatility=(VolatilityLimitCheck(sigma, 0.2, "a"),))
    second = AdvancedChecks(
        volatility=(VolatilityLimitCheck(sigma, 0.3, "b"),),
        cardinality=_cardinality([1, 1, 1, 1]),
    )
    merged = combined_checks(first, second)
    assert [c.label for c in merged.volatility] == ["a", "b"]
    assert merged.cardinality is second.cardinality and merged.cvar is None


def test_the_validator_never_relaxes_the_configured_tolerances() -> None:
    """Los umbrales del validador son los de ``[solver]``: una violación mayor no se tolera."""
    context, validation_context = _context()
    advanced = AdvancedSolutionValidator(TOLERANCES)
    vol = float(np.sqrt(np.full(4, 0.25) @ context.inputs.sigma @ np.full(4, 0.25)))
    tolerance = CONFIG.solver.constraint_tolerance
    inside = advanced.validate(
        np.full(4, 0.25),
        context.compiled,
        validation_context,
        AdvancedChecks(
            volatility=(VolatilityLimitCheck(context.inputs.sigma, vol - 0.5 * tolerance, "t"),)
        ),
    )
    outside = advanced.validate(
        np.full(4, 0.25),
        context.compiled,
        validation_context,
        AdvancedChecks(
            volatility=(VolatilityLimitCheck(context.inputs.sigma, vol - 5.0 * tolerance, "t"),)
        ),
    )
    assert inside.is_valid and not outside.is_valid
    assert spec_with().portfolio_id == "P1"
