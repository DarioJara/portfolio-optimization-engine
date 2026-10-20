"""D-01, P-09: ``WorkloadSpec`` (catálogo cerrado, validación de parámetros y hash canónico)."""

from __future__ import annotations

import dataclasses
import pickle

import pytest

from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    FrontierMethod,
    FrontierScope,
    MultiScenarioMode,
)
from portfolio_engine.parallel.workload import (
    WORKLOAD_CLASS,
    OperationKind,
    OperationSpec,
    WorkloadSpec,
)
from tests.fixtures.parallel import class_workloads

pytestmark = pytest.mark.unit

GROSS = CostTreatment.GROSS
RISK = FrontierMethod.RISK_AVERSION_GRID
K = OperationKind


def _problems(*operations: OperationSpec) -> tuple[str, ...]:
    return WorkloadSpec(operations).problems()


def test_every_reference_workload_is_valid() -> None:
    for label, (_, workload) in class_workloads().items():
        assert workload.problems() == (), label


def test_every_operation_kind_has_a_cost_class() -> None:
    assert set(WORKLOAD_CLASS) == set(OperationKind)
    assert set(WORKLOAD_CLASS.values()) == {"W0", "W1", "W2", "W3", "W4", "W5"}
    classes = {label: workload.classes for label, (_, workload) in class_workloads().items()}
    assert classes["W0-GROSS-RISK"] == {"W0"}
    assert classes["W5-EXACT-MIP"] == {"W1", "W5"}
    assert classes["PIPELINE"] == {"W1", "W3", "W4"}


def test_an_empty_workload_is_invalid() -> None:
    assert any("ninguna operación" in problem for problem in WorkloadSpec(()).problems())


def test_an_unknown_schema_version_is_invalid() -> None:
    workload = WorkloadSpec((OperationSpec(K.GLOBAL_FRONTIER, GROSS, method=RISK),), 99)
    assert any("schema_version" in problem for problem in workload.problems())


@pytest.mark.parametrize(
    "operation, missing",
    [
        (OperationSpec(K.FRONTIER_FIXED_COMPOSITION, GROSS), "method"),
        (OperationSpec(K.GLOBAL_FRONTIER, GROSS), "method"),
        (OperationSpec(K.MULTI_SCENARIO, GROSS), "mode"),
        (OperationSpec(K.STRATEGY_CVAR, GROSS), "cvar_objective"),
        (OperationSpec(K.STRATEGY_ROBUST, GROSS), "risk_aversion"),
        (OperationSpec(K.EXACT_MIP_VALIDATION, GROSS), "risk_aversion"),
        (
            OperationSpec(K.MULTI_SCENARIO, GROSS, mode=MultiScenarioMode.WORST_CASE),
            "risk_aversion",
        ),
        (
            OperationSpec(K.MULTI_SCENARIO, GROSS, mode=MultiScenarioMode.SCENARIO_INDEPENDENT),
            "method",
        ),
        (
            OperationSpec(
                K.MULTI_SCENARIO,
                GROSS,
                mode=MultiScenarioMode.SCENARIO_INDEPENDENT,
                method=RISK,
            ),
            "scope",
        ),
    ],
)
def test_missing_mandatory_parameters_are_reported(operation: OperationSpec, missing: str) -> None:
    problems = _problems(OperationSpec(K.GLOBAL_FRONTIER, GROSS, method=RISK), operation)
    assert any(f"'{missing}'" in problem and "obligatorio" in problem for problem in problems)


@pytest.mark.parametrize(
    "operation, extra",
    [
        (
            OperationSpec(K.FRONTIER_FIXED_COMPOSITION, GROSS, method=RISK, risk_aversion=1.0),
            "risk_aversion",
        ),
        (
            OperationSpec(K.GLOBAL_FRONTIER, GROSS, method=RISK, mode=MultiScenarioMode.WORST_CASE),
            "mode",
        ),
        (OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=1.0, max_cvar=0.1), "max_cvar"),
        (OperationSpec(K.STRATEGY_MAX_SHARPE, GROSS, method=RISK), "method"),
        (
            OperationSpec(
                K.MULTI_SCENARIO,
                GROSS,
                mode=MultiScenarioMode.WORST_CASE,
                risk_aversion=1.0,
                method=RISK,
            ),
            "method",
        ),
        (
            OperationSpec(K.STRATEGY_VOL_TARGET, GROSS, include_max_sharpe=True),
            "include_max_sharpe",
        ),
    ],
)
def test_parameters_that_do_not_apply_are_rejected(operation: OperationSpec, extra: str) -> None:
    problems = _problems(operation)
    assert any(f"'{extra}'" in problem and "no aplica" in problem for problem in problems)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan")])
def test_numeric_parameters_must_be_finite_and_positive(bad: float) -> None:
    problems = _problems(OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=bad))
    assert any("finito" in problem for problem in problems)


def test_exact_mip_requires_an_earlier_global_frontier() -> None:
    mip = OperationSpec(K.EXACT_MIP_VALIDATION, GROSS, risk_aversion=4.0)
    frontier = OperationSpec(K.GLOBAL_FRONTIER, GROSS, method=RISK)
    assert any("GLOBAL_FRONTIER anterior" in p for p in _problems(mip))
    assert any("GLOBAL_FRONTIER anterior" in p for p in _problems(mip, frontier))
    assert _problems(frontier, mip) == ()


def test_the_hash_is_stable_and_sensitive_to_every_parameter() -> None:
    base = WorkloadSpec((OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=3.0),))
    same = WorkloadSpec((OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=3.0),))
    assert base.workload_hash == same.workload_hash
    variants = [
        dataclasses.replace(base.operations[0], risk_aversion=3.5),
        dataclasses.replace(base.operations[0], treatment=CostTreatment.NET),
        dataclasses.replace(base.operations[0], covariance_scale_max=1.1),
    ]
    hashes = {WorkloadSpec((variant,)).workload_hash for variant in variants}
    assert len(hashes) == len(variants)
    assert base.workload_hash not in hashes
    assert WorkloadSpec((*base.operations, *base.operations)).workload_hash != base.workload_hash


def test_the_order_of_operations_is_part_of_the_identity() -> None:
    first = OperationSpec(K.GLOBAL_FRONTIER, GROSS, method=RISK)
    second = OperationSpec(K.STRATEGY_MAX_SHARPE, GROSS)
    assert (
        WorkloadSpec((first, second)).workload_hash != WorkloadSpec((second, first)).workload_hash
    )


def test_data_requirements_are_derived_from_the_operations() -> None:
    cvar = OperationSpec(K.STRATEGY_CVAR, GROSS, cvar_objective=CVaRObjective.MIN_CVAR)
    multi = OperationSpec(
        K.MULTI_SCENARIO,
        GROSS,
        mode=MultiScenarioMode.SCENARIO_INDEPENDENT,
        method=RISK,
        scope=FrontierScope.CONTINUOUS_FRONTIER,
    )
    assert WorkloadSpec((cvar,)).requires_return_scenarios()
    assert not WorkloadSpec((multi,)).requires_return_scenarios()
    assert WorkloadSpec((multi,)).requires_scenario_definitions()
    assert not WorkloadSpec((cvar,)).requires_scenario_definitions()


def test_workloads_are_serializable() -> None:
    """Viajan a los workers: deben sobrevivir a ``pickle`` con la misma identidad."""
    for _, workload in class_workloads().values():
        restored = pickle.loads(pickle.dumps(workload))
        assert restored.workload_hash == workload.workload_hash
        assert restored.problems() == ()


@pytest.mark.parametrize(
    "half_width, fragment",
    [
        ((), "no vacío"),
        ((("A1", 0.1), ("A0", 0.1)), "ordenados"),
        ((("A0", 0.1), ("A0", 0.2)), "únicos"),
        ((("A0", -0.1),), ">= 0"),
        ((("A0", float("nan")),), ">= 0"),
        ((("A0", float("inf")),), ">= 0"),
    ],
)
def test_the_box_mu_uncertainty_must_be_valid(
    half_width: tuple[tuple[str, float], ...], fragment: str
) -> None:
    operation = OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=3.0, mu_half_width=half_width)
    assert any(fragment in problem for problem in _problems(operation))


def test_the_box_mu_uncertainty_only_applies_to_the_robust_strategy() -> None:
    valid = (("A0", 0.1), ("A1", 0.2))
    assert (
        _problems(OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=3.0, mu_half_width=valid))
        == ()
    )
    other = OperationSpec(K.STRATEGY_MAX_SHARPE, GROSS, mu_half_width=valid)
    assert any("'mu_half_width'" in p and "no aplica" in p for p in _problems(other))
    zero = OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=3.0, mu_half_width=(("A0", 0.0),))
    assert _problems(zero) == ()  # δ = 0 es una incertidumbre nula pero válida


def test_the_half_width_is_part_of_the_workload_identity() -> None:
    base = OperationSpec(K.STRATEGY_ROBUST, GROSS, risk_aversion=3.0, mu_half_width=(("A0", 0.1),))
    changed = dataclasses.replace(base, mu_half_width=(("A0", 0.2),))
    assert WorkloadSpec((base,)).workload_hash != WorkloadSpec((changed,)).workload_hash
