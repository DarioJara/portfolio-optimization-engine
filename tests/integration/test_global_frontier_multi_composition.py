"""TST-012, FRN-002, FRN-003, FRN-017, OPT-002, VIS-002: la ``GLOBAL_CANDIDATE_FRONTIER`` contiene
varias composiciones.

Contrato crítico del Bloque 3::

    candidate_compositions = generate(...)
    assert len(candidate_compositions) > 1
    global_points = solve_global_frontier(...)
    assert len(unique(global_points.CompositionID)) > 1

sobre el caso diseñado ``two_region_problem``: la frontera de la cartera actual llega a
volatilidades que ninguna alternativa alcanza y las alternativas llegan a retornos que la cartera
actual nunca alcanza, de modo que varias composiciones aportan puntos no dominados.
"""

from __future__ import annotations

import pytest

from portfolio_engine.candidates import CandidateEngine
from portfolio_engine.exceptions import FrontierError
from portfolio_engine.frontiers import ContinuousFrontierEngine, GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import (
    CostTreatment,
    EvaluationMode,
    FrontierMethod,
    FrontierScope,
)
from portfolio_engine.models.frontier import GlobalFrontierResult
from portfolio_engine.outputs import (
    VISUALIZATION_COLUMNS,
    candidate_composition_rows,
    global_frontier_point_rows,
    visualization_dataset,
)
from tests.fixtures.candidates import context_of, two_region_problem, with_candidates
from tests.fixtures.problems import base_config, make_problem

pytestmark = pytest.mark.integration

METHODS = list(FrontierMethod)
TREATMENTS = list(CostTreatment)


@pytest.fixture(scope="module")
def config():  # type: ignore[no-untyped-def]
    return base_config()


@pytest.fixture(scope="module")
def problem(config):  # type: ignore[no-untyped-def]
    return two_region_problem(config)


@pytest.fixture(scope="module")
def solved(config, problem):  # type: ignore[no-untyped-def]
    """Frontera global por (tratamiento, método), resuelta una sola vez."""
    engine = GlobalCandidateFrontierEngine(config)
    return {
        (treatment, method): engine.solve(problem, treatment, method)
        for treatment in TREATMENTS
        for method in METHODS
    }


def _brute_force_envelope(result: GlobalFrontierResult, config):  # type: ignore[no-untyped-def]
    """Puntos no dominados calculados con bucles explícitos (sin ``pareto_mask``)."""
    tolerance = config.frontier.pareto_tolerance
    net = result.cost_treatment is not CostTreatment.GROSS
    values = {}
    for entry in result.points:
        metrics = entry.point.metrics
        if entry.is_valid_solution and metrics is not None and not entry.is_duplicate:
            ret = metrics.expected_return_net if net else metrics.expected_return_gross
            values[entry.global_point_id] = (metrics.volatility, ret)
    efficient = set()
    for key, (vol, ret) in values.items():
        dominated = any(
            o_vol <= vol + tolerance
            and o_ret >= ret - tolerance
            and (o_vol < vol - tolerance or o_ret > ret + tolerance)
            for other, (o_vol, o_ret) in values.items()
            if other != key
        )
        if not dominated:
            efficient.add(key)
    return efficient


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("treatment", TREATMENTS)
def test_contractual_multiple_compositions_before_and_after_the_pareto_filter(
    config,
    problem,
    solved,
    treatment: CostTreatment,
    method: FrontierMethod,  # type: ignore[no-untyped-def]
) -> None:
    candidate_compositions = CandidateEngine(config).generate_candidate_compositions(
        problem.state.composition(), context_of(problem)
    )
    assert len(candidate_compositions) > 1
    result = solved[(treatment, method)]
    global_points = result.points
    assert len({p.composition_id for p in global_points}) > 1  # antes del filtro Pareto
    assert len(result.composition_ids) > 1  # solo puntos válidos
    assert len(result.envelope_composition_ids) > 1  # varias composiciones no dominadas
    assert {c.composition_id for c in result.candidates} == {
        c.composition_id for c in candidate_compositions
    }


@pytest.mark.parametrize("treatment", TREATMENTS)
def test_the_envelope_equals_an_independent_brute_force_pareto(
    config,
    solved,
    treatment: CostTreatment,  # type: ignore[no-untyped-def]
) -> None:
    result = solved[(treatment, FrontierMethod.RISK_AVERSION_GRID)]
    expected = _brute_force_envelope(result, config)
    assert {p.global_point_id for p in result.envelope} == expected
    dominated = [
        p for p in result.valid_points if p.global_point_id not in expected and not p.is_duplicate
    ]
    assert dominated  # hay puntos dominados y se conservan en el resultado
    assert all(p in result.points for p in dominated)


def test_the_two_regions_of_the_design_are_covered_by_different_compositions(
    config,
    problem,
    solved,  # type: ignore[no-untyped-def]
) -> None:
    result = solved[(CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)]
    current_id = problem.state.composition_hash
    lowest_risk = min(result.envelope, key=lambda p: p.point.metrics.volatility)  # type: ignore[union-attr]
    highest_return = max(
        result.envelope,
        key=lambda p: p.point.metrics.expected_return_gross,  # type: ignore[union-attr]
    )
    assert lowest_risk.composition_id == current_id  # la cartera actual domina el extremo de riesgo
    assert highest_return.composition_id != current_id
    assert "A002" in highest_return.asset_ids  # alternativa con el activo de mayor retorno
    assert highest_return.point.metrics.expected_return_gross > 0.15  # type: ignore[union-attr]
    current_max = max(
        p.point.metrics.expected_return_gross  # type: ignore[union-attr]
        for p in result.valid_points
        if p.composition_id == current_id
    )
    assert current_max < 0.06  # la cartera actual nunca alcanza esos retornos


def test_continuous_and_global_frontiers_are_different_pipelines(
    problem,
    solved,  # type: ignore[no-untyped-def]
) -> None:
    result = solved[(CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)]
    continuous = result.continuous
    assert continuous is not None
    assert continuous.scope is FrontierScope.CONTINUOUS_FRONTIER
    assert continuous.frontier_type == "CONTINUOUS_FRONTIER:NET"
    assert result.frontier_type == "GLOBAL_CANDIDATE_FRONTIER:NET"
    # continua: exactamente los activos actuales y un solo CompositionID (TST-011)
    assert continuous.asset_set == frozenset(problem.state.asset_ids)
    assert {p.composition_id for p in continuous.points} == {problem.state.composition_hash}
    assert all(p.scope is FrontierScope.CONTINUOUS_FRONTIER for p in continuous.points)
    # global: varias composiciones, todas etiquetadas con su propio alcance
    assert len(result.composition_results) > 1
    for composition in result.composition_results:
        assert composition.scope is FrontierScope.GLOBAL_CANDIDATE_FRONTIER
        assert all(p.scope is FrontierScope.GLOBAL_CANDIDATE_FRONTIER for p in composition.points)


def test_the_current_composition_frontier_is_reused_not_recomputed(solved) -> None:  # type: ignore[no-untyped-def]
    result = solved[(CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)]
    assert result.continuous is not None
    reference = next(
        r
        for r in result.composition_results
        if r.composition_id == result.continuous.composition_id
    )
    assert reference.diagnostics is result.continuous.diagnostics  # la misma resolución
    for own, relabelled in zip(result.continuous.points, reference.points, strict=True):
        assert own.point_id == relabelled.point_id and (own.weights == relabelled.weights).all()


def test_each_global_point_keeps_its_origin_and_solver_information(solved) -> None:  # type: ignore[no-untyped-def]
    result = solved[(CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)]
    ids = [p.global_point_id for p in result.points]
    assert len(ids) == len(set(ids))
    assert [p.sequence_id for p in result.points] == list(range(len(result.points)))
    for entry in result.valid_points:
        point = entry.point
        assert entry.composition_id == point.composition_id
        assert point.weights is not None and len(entry.asset_ids) == point.weights.shape[0]
        assert point.solve is not None and point.solve.solver_name  # diagnósticos del solver
        assert point.validation is not None and point.validation.is_valid  # SolutionValidator
        assert point.metrics is not None
        assert point.metrics.expected_return_net is not None
        assert point.metrics.expected_return_net <= point.metrics.expected_return_gross + 1e-12
        assert point.metrics.turnover is not None and point.metrics.transaction_cost is not None
    rows = global_frontier_point_rows(result)
    assert (
        len(rows) == len(result.points)
        and rows[0].composition_id == result.points[0].composition_id
    )


def test_net_frontiers_are_solved_per_composition_with_the_block_2_engine(
    config,
    problem,
    solved,  # type: ignore[no-untyped-def]
) -> None:
    """La frontera global no reutiliza una frontera ajena: cada composición coincide con el
    resultado del motor continuo del Bloque 2 para esa misma composición."""
    from dataclasses import replace

    result = solved[(CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)]
    engine = ContinuousFrontierEngine(config)
    for composition in result.composition_results[:3]:
        direct = engine.solve(
            replace(problem, composition_asset_ids=composition.asset_ids),
            CostTreatment.NET,
            FrontierMethod.RISK_AVERSION_GRID,
        )
        assert direct.composition_id == composition.composition_id
        assert len(direct.points) == len(composition.points)
        for a, b in zip(direct.points, composition.points, strict=True):
            assert (a.weights == b.weights).all() and a.metrics == b.metrics


def test_post_cost_gross_keeps_its_own_semantics(solved) -> None:  # type: ignore[no-untyped-def]
    gross = solved[(CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)]
    post = solved[(CostTreatment.POST_COST_GROSS, FrontierMethod.RISK_AVERSION_GRID)]
    assert post.frontier_type == "GLOBAL_CANDIDATE_FRONTIER:POST_COST_GROSS"
    assert len(gross.composition_results) == len(post.composition_results)
    for g, p in zip(gross.composition_results, post.composition_results, strict=True):
        assert p.cost_treatment is CostTreatment.POST_COST_GROSS
        for gp, pp in zip(g.points, p.points, strict=True):  # mismos pesos que la frontera bruta
            assert (gp.weights == pp.weights).all()
    # la envolvente se calcula con el retorno neto de esos pesos: nunca con el bruto
    flagged = post.envelope
    assert flagged and all(p.is_global_net_efficient for p in flagged)


def test_generation_and_global_frontier_are_deterministic(config, problem, solved) -> None:  # type: ignore[no-untyped-def]
    first = solved[(CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)]
    second = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert [p.global_point_id for p in first.points] == [p.global_point_id for p in second.points]
    assert [p.is_global_gross_efficient for p in first.points] == [
        p.is_global_gross_efficient for p in second.points
    ]
    assert [c.composition_id for c in first.candidates] == [
        c.composition_id for c in second.candidates
    ]


def test_visualization_dataset_holds_the_three_layers(problem, solved) -> None:  # type: ignore[no-untyped-def]
    """VIS-002: cartera actual, frontera continua y frontera global se grafican sin recalcular."""
    result = solved[(CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)]
    frame = visualization_dataset(result)
    assert tuple(frame.columns) == VISUALIZATION_COLUMNS
    layers = frame.groupby("Layer").size().to_dict()
    assert layers["CURRENT_PORTFOLIO"] == 1
    assert layers["CONTINUOUS_FRONTIER"] == len(result.continuous.points)  # type: ignore[union-attr]
    assert layers["GLOBAL_CANDIDATE_FRONTIER"] == len(result.points)
    current = frame[frame["Layer"] == "CURRENT_PORTFOLIO"].iloc[0]
    assert current["Volatility"] == pytest.approx(result.current_metrics.volatility)  # type: ignore[union-attr]
    assert current["CompositionID"] == problem.state.composition_hash
    continuous = frame[frame["Layer"] == "CONTINUOUS_FRONTIER"]
    assert set(continuous["CompositionID"]) == {problem.state.composition_hash}
    global_layer = frame[frame["Layer"] == "GLOBAL_CANDIDATE_FRONTIER"]
    assert global_layer["CompositionID"].nunique() > 1
    assert (
        global_layer[["Volatility", "ExpectedReturnGross", "ExpectedReturnNet"]].notna().all().all()
    )
    assert set(global_layer["FrontierType"]) == {"GLOBAL_CANDIDATE_FRONTIER:NET"}
    efficient = global_layer[(global_layer["IsEfficient"] == True) & ~global_layer["IsDuplicate"]]  # noqa: E712
    assert len(efficient) == len(result.envelope) and efficient["CompositionID"].nunique() > 1
    # los duplicados heredan la eficiencia de su representante (con IsDuplicate = True)
    assert global_layer[global_layer["IsDuplicate"]]["IsEfficient"].notna().all()


def test_candidate_composition_rows_document_how_each_composition_was_proposed(solved) -> None:  # type: ignore[no-untyped-def]
    result = solved[(CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)]
    rows = candidate_composition_rows("P1", "BASE", result.candidates)
    assert len(rows) == len(result.candidates) > 1
    assert rows[0].is_reference and rows[0].number_of_moves == 0
    assert all(r.number_of_moves >= 1 for r in rows[1:])
    assert all(r.estimate_basis == "PROJECTED_WEIGHTS" for r in rows)


def test_cold_start_frontier_is_gross_only(config, problem) -> None:  # type: ignore[no-untyped-def]
    from portfolio_engine.models.portfolio import PortfolioSpec  # noqa: F401
    from tests.fixtures.problems import spec_with

    empty = make_problem(
        problem.risk_model.mu,
        problem.risk_model.sigma,
        None,
        config,
        universe_overrides={"MaxWeight": [1.0] * 6},
        spec=spec_with(target_portfolio_size=2),
    )
    engine = GlobalCandidateFrontierEngine(config)
    result = engine.solve(empty, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)
    assert result.continuous is None and result.current_metrics is None
    assert len(result.composition_ids) > 1 and result.envelope
    assert not result.has_current_portfolio and result.current_composition_id is None
    with pytest.raises(FrontierError, match="NET exige cartera actual"):
        engine.solve(empty, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)


def test_the_global_frontier_requires_the_current_portfolio_as_starting_composition(
    config,
    problem,  # type: ignore[no-untyped-def]
) -> None:
    from dataclasses import replace

    bad = replace(problem, composition_asset_ids=("A000", "A002"))
    with pytest.raises(FrontierError, match="composition_asset_ids debe ser None"):
        GlobalCandidateFrontierEngine(config).solve(
            bad, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
        )


def test_qp_evaluation_mode_builds_the_same_kind_of_global_frontier(config, problem) -> None:  # type: ignore[no-untyped-def]
    qp_config = with_candidates(
        config, evaluation_mode=EvaluationMode.QP_UTILITY, refinement_iterations=0
    )
    result = GlobalCandidateFrontierEngine(qp_config).solve(
        problem, CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID
    )
    assert all(e.basis is EvaluationMode.QP_UTILITY for c in result.candidates for e in c.estimates)
    assert len(result.composition_ids) > 1 and len(result.envelope_composition_ids) > 1
    assert result.diagnostics.frontiers_solved == len(result.candidates)


def test_each_composition_uses_its_own_workspace_with_reuse_and_warm_start(  # type: ignore[no-untyped-def]
    solved,
) -> None:
    """Dentro de cada composición se reutiliza el workspace y se arranca en caliente; entre
    composiciones no se comparte ninguno (cada resultado cuenta sus propias resoluciones)."""
    result = solved[(CostTreatment.GROSS, FrontierMethod.RISK_AVERSION_GRID)]
    assert len(result.composition_results) > 1
    for composition in result.composition_results:
        diagnostics = composition.diagnostics
        assert diagnostics.setup_count == 3  # QP compartido + LP + etapa 2 de MaxReturn
        assert diagnostics.solve_count == len(composition.points) + 1
        assert composition.pre_check_feasible
        if len(composition.points) > 2:  # una frontera degenerada solo tiene los dos extremos
            assert diagnostics.warm_start_count > 0
            assert diagnostics.update_count > 0  # se actualizan q/lower en el mismo workspace
    assert any(len(c.points) > 2 for c in result.composition_results)
    assert len({id(c.diagnostics) for c in result.composition_results}) == len(
        result.composition_results
    )
