"""MIP-001, MIP-003, MIP-004, MIP-005, MIP-006, CON-010, CON-011, CON-019: ``EXACT_MIP`` en modo
validación de heurísticas.

El oráculo es la enumeración exhaustiva de composiciones resueltas con el QP validado del Bloque 2
(y, para el MISOCP, con el SOCP de volatilidad del Bloque 4): independiente del solver mixto.
"""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pytest

from portfolio_engine.constraints.integer import CompositionLimits, move_violations
from portfolio_engine.exceptions import UnsupportedCombinationError
from portfolio_engine.frontiers import (
    ContinuousFrontierEngine,
    ExactMIPValidator,
    GlobalCandidateFrontierEngine,
    HeuristicGapReport,
    StrategyOptimizer,
    calibration_summary,
)
from portfolio_engine.models.enums import (
    CostTreatment,
    FrontierMethod,
    OptimalityClaim,
    RestrictedExistingPositionPolicy,
    SolverStatus,
    StrategyID,
)
from portfolio_engine.models.solution import MipDiagnostics
from portfolio_engine.optimizers import SCIP_AVAILABLE, SCIPBackend
from portfolio_engine.optimizers.formulations.miqp import build_cardinality_miqp
from tests.fixtures.candidates import candidate_config, random_problem, search
from tests.fixtures.problems import policy_config, restricted_universe, spec_with

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(not SCIP_AVAILABLE, reason="PySCIPOpt (opcional, E-24) no instalado"),
]

LAMBDA = 4.0
TOL = 5e-6


def _enumerate(problem, config, treatment, size, limits=None, predicate=None):  # type: ignore[no-untyped-def]
    """Mejor utilidad exacta entre TODAS las composiciones de ``size`` activos factibles."""
    engine = ContinuousFrontierEngine(config)
    optimizer = StrategyOptimizer(config)
    current = tuple(problem.state.asset_ids)
    best = (-np.inf, ())
    for subset in itertools.combinations(problem.risk_model.asset_ids, size):
        if limits is not None and move_violations(limits, current, subset):
            continue
        if predicate is not None and not predicate(subset):
            continue
        sub = dataclasses.replace(problem, composition_asset_ids=subset)
        context, _ = optimizer.prepare(sub, treatment)
        if context is None:
            continue
        session = engine.open_session(sub, treatment, FrontierMethod.RISK_AVERSION_GRID)
        point = session.solve_risk_aversion(1.0 / LAMBDA, strategy=StrategyID.FRONTIER_POINT)
        if not point.is_valid_solution or point.weights is None:
            continue
        value = optimizer.treatment_return(context, point.weights, treatment) - LAMBDA * float(
            point.weights @ context.inputs.sigma @ point.weights
        )
        if value > best[0]:
            best = (value, subset)
    return best


def _report(problem, config, treatment, size, candidates=None, limits=None, **kwargs):  # type: ignore[no-untyped-def]
    problem = dataclasses.replace(problem, spec=spec_with(target_portfolio_size=size))
    candidates = candidates if candidates is not None else search(config, problem).compositions
    validator = ExactMIPValidator(config)
    return problem, validator.validate_heuristic(
        problem,
        treatment,
        LAMBDA,
        problem.risk_model.asset_ids,
        candidates,
        limits=limits,
        **kwargs,
    )


@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_the_miqp_finds_the_best_composition_by_exhaustive_enumeration(
    treatment: CostTreatment,
) -> None:
    """MIP-001 (test_formulation): óptimo del MIQP = mejor composición enumerada (bruto y neto)."""
    config = candidate_config()
    problem = random_problem(8, [0, 1, 2], 3, config)
    problem, report = _report(problem, config, treatment, 3)
    best_value, best_subset = _enumerate(problem, config, treatment, 3)
    assert (
        report.mip_status is SolverStatus.OPTIMAL and report.mip_claim is OptimalityClaim.MIP_PROVEN
    )
    assert report.mip_valid and report.mip_asset_ids == best_subset
    assert report.mip_utility == pytest.approx(best_value, abs=TOL)
    assert report.universe_size == 8 and report.cost_treatment is treatment
    assert report.validation is not None and report.validation.is_valid
    assert {"CARDINALITY", "BUDGET", "TURNOVER"} <= set(report.validation.checks)
    assert report.mip_nodes is not None and report.mip_solve_time is not None


def test_new_asset_and_swap_limits_are_linear_constraints_in_the_binaries() -> None:
    """CON-010, CON-011: ``Σ_{i∉actual} z_i <= N`` y swaps, frente a la enumeración."""
    config = candidate_config()
    problem = random_problem(8, [0, 1, 2], 5, config)
    for limits in (
        CompositionLimits(3, 1, None, frozenset()),
        CompositionLimits(3, None, 2, frozenset()),
        CompositionLimits(3, 0, None, frozenset()),
    ):
        problem_k, report = _report(problem, config, CostTreatment.NET, 3, limits=limits)
        best_value, best_subset = _enumerate(problem_k, config, CostTreatment.NET, 3, limits=limits)
        assert report.mip_valid and report.mip_asset_ids == best_subset, limits
        assert report.mip_utility == pytest.approx(best_value, abs=TOL)
        assert not move_violations(limits, problem.state.asset_ids, report.mip_asset_ids)
    zero_new = _report(
        problem, config, CostTreatment.GROSS, 3, limits=CompositionLimits(3, 0, None, frozenset())
    )[1]
    assert set(zero_new.mip_asset_ids) == {"A000", "A001", "A002"}  # solo la cartera actual


def test_semicontinuous_positions_min_and_max_weight() -> None:
    """``MinWeight·z <= w <= MaxWeight·z``: los miembros pesan entre ambos y los demás 0."""
    config = candidate_config()
    problem = random_problem(
        8,
        [0, 1, 2, 3],
        7,
        config,
        universe_overrides={"MinWeight": [0.12] * 8, "MaxWeight": [0.4] * 8},
    )
    problem = dataclasses.replace(problem, spec=spec_with(target_portfolio_size=4))
    universe = tuple(problem.risk_model.asset_ids)
    context, _ = StrategyOptimizer(config).prepare(
        dataclasses.replace(problem, composition_asset_ids=universe), CostTreatment.GROSS
    )
    assert context is not None
    limits = CompositionLimits(4, None, None, frozenset())
    extended, _ = build_cardinality_miqp(context.inputs, CostTreatment.GROSS, LAMBDA, limits)
    backend = StrategyOptimizer(config).router.route(extended.problem)
    assert isinstance(backend, SCIPBackend)
    backend.setup(extended.problem)
    result = backend.solve()
    assert result.status is SolverStatus.OPTIMAL and result.x is not None
    weights = result.x[:8]
    z = np.round(result.x[extended.role("z") : extended.role("z") + 8])
    assert int(z.sum()) == 4
    assert np.all(weights[z == 1] >= 0.12 - 1e-7) and np.all(weights[z == 1] <= 0.4 + 1e-7)
    assert np.all(np.abs(weights[z == 0]) <= 1e-7)
    assert float(weights.sum()) == pytest.approx(1.0, abs=1e-7)
    problem, report = _report(problem, config, CostTreatment.GROSS, 4)
    best_value, best_subset = _enumerate(problem, config, CostTreatment.GROSS, 4)
    assert report.mip_asset_ids == best_subset and report.mip_utility == pytest.approx(
        best_value, abs=TOL
    )


def test_a_frozen_position_must_stay_and_a_force_liquidated_one_must_leave_with_its_cost() -> None:
    """E-09 en el MIQP: ``FREEZE_WEIGHT`` ⇒ ``z = 1``; ``FORCE_LIQUIDATE`` ⇒ ``z = 0``."""
    base = candidate_config()
    freeze = policy_config(base, RestrictedExistingPositionPolicy.FREEZE_WEIGHT)
    problem = random_problem(
        7,
        [0, 1, 2],
        11,
        freeze,
        universe_overrides=restricted_universe(7, [0]),
    )
    problem, report = _report(problem, freeze, CostTreatment.NET, 3)
    assert "A000" in report.mip_asset_ids and report.mip_valid  # congelado: no puede salir
    best_value, best_subset = _enumerate(
        problem, freeze, CostTreatment.NET, 3, predicate=lambda subset: "A000" in subset
    )
    assert report.mip_asset_ids == best_subset
    assert report.mip_utility == pytest.approx(best_value, abs=TOL)

    liquidate = policy_config(base, RestrictedExistingPositionPolicy.FORCE_LIQUIDATE)
    problem = random_problem(
        7,
        [0, 1, 2],
        11,
        liquidate,
        universe_overrides=restricted_universe(7, [0]),
    )
    problem, report = _report(problem, liquidate, CostTreatment.NET, 3)
    assert "A000" not in report.mip_asset_ids and report.mip_valid
    best_value, best_subset = _enumerate(
        problem, liquidate, CostTreatment.NET, 3, predicate=lambda subset: "A000" not in subset
    )
    assert report.mip_asset_ids == best_subset
    assert report.mip_utility == pytest.approx(best_value, abs=TOL)


def test_a_non_buyable_asset_never_enters_and_a_restricted_new_asset_is_excluded() -> None:
    config = candidate_config()
    problem = random_problem(
        7,
        [0, 1, 2],
        13,
        config,
        universe_overrides={"EligibleFlag": [True] * 3 + [False] + [True] * 3},  # A003 no comprable
    )
    problem, report = _report(problem, config, CostTreatment.GROSS, 3)
    assert "A003" not in report.mip_asset_ids and report.mip_valid
    best_value, _ = _enumerate(
        problem, config, CostTreatment.GROSS, 3, predicate=lambda s: "A003" not in s
    )
    assert report.mip_utility == pytest.approx(best_value, abs=TOL)


def test_the_universe_must_contain_the_whole_current_portfolio_and_respect_the_size_guard() -> None:
    config = candidate_config()
    problem = random_problem(8, [0, 1, 2], 3, config)
    problem = dataclasses.replace(problem, spec=spec_with(target_portfolio_size=3))
    validator = ExactMIPValidator(config)
    with pytest.raises(UnsupportedCombinationError, match="todos los activos de la cartera actual"):
        validator.validate_heuristic(
            problem, CostTreatment.GROSS, LAMBDA, ("A000", "A001", "A003", "A004", "A005"), ()
        )
    small = dataclasses.replace(
        config, exact_mip=dataclasses.replace(config.exact_mip, max_universe_size=4)
    )
    with pytest.raises(UnsupportedCombinationError, match="max_universe_size"):
        ExactMIPValidator(small).validate_heuristic(
            problem, CostTreatment.GROSS, LAMBDA, problem.risk_model.asset_ids, ()
        )
    with pytest.raises(UnsupportedCombinationError, match="risk_aversion"):
        validator.validate_heuristic(
            problem, CostTreatment.GROSS, -1.0, problem.risk_model.asset_ids, ()
        )


def test_the_gap_report_compares_the_heuristic_with_the_proven_optimum() -> None:
    """MIP-003 (test_gap_report): utilidades recalculadas y gap frente a incumbente y cota."""
    config = candidate_config()
    problem = random_problem(9, [0, 1, 2], 3, config)
    problem, report = _report(problem, config, CostTreatment.NET, 3)
    assert isinstance(report, HeuristicGapReport)
    assert report.mip_claim is OptimalityClaim.MIP_PROVEN and report.mip_valid
    assert report.heuristic_utility is not None and report.mip_utility is not None
    assert (
        report.gap_to_incumbent is not None and report.gap_to_incumbent >= -TOL
    )  # MIP >= heurístico
    assert report.mip_utility_upper_bound is not None
    assert report.mip_utility_upper_bound >= report.mip_utility - 1e-6  # cota dual válida
    assert report.gap_to_optimum_bound is not None and report.gap_to_optimum_bound >= -TOL
    assert report.mip_relative_gap == pytest.approx(0.0, abs=1e-6)
    assert report.heuristic_matches_optimum is (report.gap_to_incumbent <= TOL)
    assert len(report.heuristic_utilities) >= 1 and report.heuristic_asset_ids
    best_value, _ = _enumerate(problem, config, CostTreatment.NET, 3)
    assert report.mip_utility == pytest.approx(best_value, abs=TOL)  # y nadie supera al MIP
    assert max(v for _, v in report.heuristic_utilities) <= report.mip_utility + TOL


def test_a_poor_heuristic_shows_a_positive_gap_and_is_not_declared_optimal() -> None:
    config = candidate_config()
    problem = random_problem(9, [0, 1, 2], 5, config)
    problem = dataclasses.replace(problem, spec=spec_with(target_portfolio_size=3))
    current_only = search(config, problem).compositions[:1]  # solo la cartera actual
    assert current_only[0].asset_ids == ("A000", "A001", "A002")
    _, report = _report(problem, config, CostTreatment.GROSS, 3, candidates=current_only)
    assert report.mip_claim is OptimalityClaim.MIP_PROVEN and report.mip_valid
    assert report.gap_to_incumbent is not None and report.gap_to_incumbent > 1e-4
    assert report.heuristic_matches_optimum is False
    assert report.heuristic_asset_ids == ("A000", "A001", "A002")


def test_no_gap_is_reported_when_the_solver_gives_no_valid_dual_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MIP-003: sin cota dual válida no se inventa ningún gap; con brecha abierta es una cota."""
    config = candidate_config()
    problem = random_problem(8, [0, 1, 2], 3, config)
    real_solve = SCIPBackend.solve

    def without_bound(self: SCIPBackend):  # type: ignore[no-untyped-def]
        result = real_solve(self)
        assert result.mip is not None
        stripped = MipDiagnostics(
            result.mip.primal_bound, None, None, result.mip.nodes, 1, result.mip.incumbent
        )
        return dataclasses.replace(
            result,
            status=SolverStatus.TIME_LIMIT,
            x=None,
            mip=stripped,
            optimality_claim=OptimalityClaim.FEASIBLE_ONLY,
            objective_value=None,
        )

    monkeypatch.setattr(SCIPBackend, "solve", without_bound)
    _, report = _report(problem, config, CostTreatment.GROSS, 3)
    assert (
        report.mip_status is SolverStatus.TIME_LIMIT
        and report.mip_claim is OptimalityClaim.FEASIBLE_ONLY
    )
    assert report.mip_utility_upper_bound is None and report.mip_relative_gap is None
    assert report.gap_to_optimum_bound is None  # nada inventado
    assert "NO_VALID_DUAL_BOUND_NO_GAP_CLAIMED" in report.notes
    assert "MIP_NOT_PROVEN_OPTIMAL_GAP_IS_AN_UPPER_BOUND" in report.notes
    assert (
        report.heuristic_matches_optimum is None and not report.mip_valid
    )  # no aceptado como óptimo
    assert report.mip_utility is not None  # el incumbente se valida de forma independiente

    def with_open_gap(self: SCIPBackend):  # type: ignore[no-untyped-def]
        result = real_solve(self)
        assert result.mip is not None and result.mip.dual_bound is not None
        loose = MipDiagnostics(
            result.mip.primal_bound,
            result.mip.dual_bound - 0.01,
            0.5,
            result.mip.nodes,
            1,
            result.mip.incumbent,
        )
        return dataclasses.replace(
            result,
            status=SolverStatus.TIME_LIMIT,
            x=None,
            mip=loose,
            optimality_claim=OptimalityClaim.MIP_INCUMBENT,
            objective_value=None,
        )

    monkeypatch.setattr(SCIPBackend, "solve", with_open_gap)
    _, open_report = _report(problem, config, CostTreatment.GROSS, 3)
    assert open_report.mip_claim is OptimalityClaim.MIP_INCUMBENT
    assert (
        open_report.mip_utility_upper_bound is not None
        and open_report.gap_to_optimum_bound is not None
    )
    assert open_report.mip_utility_upper_bound > open_report.mip_utility  # type: ignore[operator]
    assert open_report.heuristic_matches_optimum is None  # no probado: no se afirma
    assert "MIP_NOT_PROVEN_OPTIMAL_GAP_IS_AN_UPPER_BOUND" in open_report.notes


def test_the_misocp_with_a_volatility_limit_matches_enumeration_with_the_conic_oracle() -> None:
    """MIP-006: MISOCP con ``‖Lᵀw‖ <= σ_max`` frente a la enumeración con el SOCP."""
    config = candidate_config()
    problem = random_problem(7, [0, 1, 2], 17, config)
    problem = dataclasses.replace(problem, spec=spec_with(target_portfolio_size=3))
    optimizer = StrategyOptimizer(config)
    reference = optimizer.volatility_target(
        dataclasses.replace(problem, composition_asset_ids=("A000", "A001", "A002")),
        CostTreatment.GROSS,
        volatility_limit=1.0,
        risk_aversion=LAMBDA,
    )
    assert reference.metrics is not None
    limit = reference.metrics.volatility * 0.95  # ligeramente por debajo de la cartera actual
    _, report = _report(problem, config, CostTreatment.GROSS, 3, volatility_limit=limit)
    assert report.mip_claim is OptimalityClaim.MIP_PROVEN
    best = (-np.inf, ())
    for subset in itertools.combinations(problem.risk_model.asset_ids, 3):
        sub = dataclasses.replace(problem, composition_asset_ids=subset)
        result = optimizer.volatility_target(
            sub, CostTreatment.GROSS, volatility_limit=limit, risk_aversion=LAMBDA
        )
        if not result.is_valid_solution or result.weights is None or result.metrics is None:
            continue
        context, _ = optimizer.prepare(sub, CostTreatment.GROSS)
        assert context is not None
        value = optimizer.treatment_return(
            context, result.weights, CostTreatment.GROSS
        ) - LAMBDA * float(result.weights @ context.inputs.sigma @ result.weights)
        if value > best[0]:
            best = (value, subset)
    assert report.mip_asset_ids == best[1]
    assert report.mip_utility == pytest.approx(best[0], abs=1e-4)


def test_calibration_summary_counts_only_proven_instances() -> None:
    """MIP-004 (test_calibration_output): resumen del ajuste del CandidateEngine con el MIP."""
    config = candidate_config()
    reports = []
    for seed in (3, 4, 5):
        problem = random_problem(8, [0, 1, 2], seed, config)
        reports.append(_report(problem, config, CostTreatment.GROSS, 3)[1])
    summary = calibration_summary(reports)
    assert (
        summary.instances == 3 and summary.proven_instances == 3 and summary.unproven_instances == 0
    )
    assert 0 <= summary.heuristic_optimal_count <= 3
    assert summary.heuristic_optimal_share == pytest.approx(summary.heuristic_optimal_count / 3)
    assert summary.max_gap_to_incumbent is not None and summary.mean_gap_to_incumbent is not None
    unproven = dataclasses.replace(reports[0], mip_claim=OptimalityClaim.FEASIBLE_ONLY)
    partial = calibration_summary([unproven, reports[1]])
    assert partial.proven_instances == 1 and partial.unproven_instances == 1
    empty = calibration_summary([unproven])
    assert empty.heuristic_optimal_share is None and empty.max_gap_to_incumbent is None


def test_exact_mip_is_never_touched_by_the_production_inner_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MIP-005: una frontera global completa (bucle de producción) no crea ningún solver mixto."""
    calls: list[str] = []

    def forbidden(self: SCIPBackend, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("setup")
        raise AssertionError("EXACT_MIP en el bucle interno de producción")

    monkeypatch.setattr(SCIPBackend, "setup", forbidden)
    monkeypatch.setattr(SCIPBackend, "__init__", lambda self, *a, **k: calls.append("init"))
    config = candidate_config()
    problem = random_problem(8, [0, 1, 2], 3, config)
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    assert result.points and calls == []
