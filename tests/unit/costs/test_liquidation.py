"""TST-014, TC-003, TC-011: liquidación completa de un activo que sale de la composición.

Cartera actual ``A = 10 %``, ``B = 90 %``; nueva cartera ``B = 90 %``, ``C = 10 %``:

* venta de ``A``: ``0,10`` con coste ``SellCost_A``;
* compra de ``C``: ``0,10`` con coste ``BuyCost_C``;
* turnover ``0,5·(0,10 + 0,10) = 0,10`` y coste único ``0,10·(Sell_A + Buy_C)``.

Los valores esperados se calculan aquí a mano; se comprueban el modelo de costes, la frontera
continua del Bloque 2 y la cadena completa CandidateEngine → frontera global → filas de salida.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.costs import TransactionCostModel, align_union
from portfolio_engine.frontiers import ContinuousFrontierEngine, GlobalCandidateFrontierEngine
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.models.portfolio import WeightBounds
from portfolio_engine.outputs import WeightContext, weight_rows
from tests.fixtures.problems import base_config, cov_from_vol_corr, make_problem, spec_with

pytestmark = pytest.mark.unit

MU = np.array([0.06, 0.08, 0.12])
SIGMA = cov_from_vol_corr([0.15, 0.20, 0.30], np.full((3, 3), 0.2) + 0.8 * np.eye(3))
BUY_BPS, SELL_BPS = [10.0, 20.0, 30.0], [50.0, 60.0, 70.0]
BUY, SELL = np.array(BUY_BPS) / 1e4, np.array(SELL_BPS) / 1e4
SALE_A, PURCHASE_C = 0.10, 0.10
EXPECTED_TURNOVER = 0.5 * (SALE_A + PURCHASE_C)
EXPECTED_COST = SALE_A * SELL[0] + PURCHASE_C * BUY[2]
FIXED = {"A001": WeightBounds(0.9, 0.9), "A002": WeightBounds(0.1, 0.1)}


def _problem(config, **kwargs):  # type: ignore[no-untyped-def]
    return make_problem(
        MU,
        SIGMA,
        [0.1, 0.9, 0.0],
        config,
        universe_overrides={"BuyCost": BUY_BPS, "SellCost": SELL_BPS, "MaxWeight": [1.0] * 3},
        spec=spec_with(weight_bound_overrides=FIXED),
        **kwargs,
    )


def test_cost_model_charges_the_sale_of_a_and_the_purchase_of_c() -> None:
    config = base_config()
    problem = _problem(config)
    alignment = align_union(problem.state, ("A001", "A002"))
    assert alignment.asset_ids == ("A000", "A001", "A002")  # unión current ∪ nueva
    assert alignment.exited_asset_ids() == ("A000",)
    model = TransactionCostModel(alignment, problem.costs, config.optimization_horizon_years)  # type: ignore[arg-type]
    new = np.array([0.9, 0.1])
    per_asset = model.asset_costs_one_off(new)
    assert per_asset.tolist() == pytest.approx([SALE_A * SELL[0], 0.0, PURCHASE_C * BUY[2]])
    assert float(model.cost_one_off(new)) == pytest.approx(EXPECTED_COST)
    assert float(model.turnover(new)) == pytest.approx(EXPECTED_TURNOVER) == pytest.approx(0.10)
    assert float(model.cost(new)) == pytest.approx(EXPECTED_COST)  # H = 1
    assert model.exit_cost_one_off() == pytest.approx(SALE_A * SELL[0])
    # el coste no se calcula solo sobre los activos de la nueva composición
    assert PURCHASE_C * BUY[2] < EXPECTED_COST


@pytest.mark.parametrize("treatment", [CostTreatment.GROSS, CostTreatment.NET])
def test_continuous_engine_accounts_for_the_complete_liquidation(treatment: CostTreatment) -> None:
    config = base_config()
    problem = _problem(config, composition=("A001", "A002"))
    result = ContinuousFrontierEngine(config).solve(
        problem, treatment, FrontierMethod.RISK_AVERSION_GRID
    )
    assert result.pre_check_feasible and result.valid_points
    gross = float(MU[1:] @ np.array([0.9, 0.1]))
    for point in result.valid_points:
        assert point.weights is not None and point.metrics is not None
        assert point.weights.tolist() == pytest.approx([0.9, 0.1], abs=1e-6)
        metrics = point.metrics
        assert metrics.turnover == pytest.approx(EXPECTED_TURNOVER, abs=1e-6)
        assert metrics.transaction_cost_one_off == pytest.approx(EXPECTED_COST, abs=1e-8)
        assert metrics.expected_return_gross == pytest.approx(gross, abs=1e-6)
        assert metrics.expected_return_net == pytest.approx(gross - EXPECTED_COST, abs=1e-6)
        assert (metrics.number_new_assets, metrics.number_removed_assets) == (1, 1)


def test_candidate_engine_and_global_frontier_produce_the_liquidation_case() -> None:
    """A10 %/B90 % → C10 %/B90 %: la sustitución la genera el CandidateEngine y su frontera
    contiene la venta de A, la compra de C, el turnover y el coste correctos."""
    config = base_config()
    problem = _problem(config)
    result = GlobalCandidateFrontierEngine(config).solve(
        problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    by_assets = {frozenset(c.asset_ids): c for c in result.candidates}
    assert set(by_assets) == {
        frozenset({"A000", "A001"}),  # referencia
        frozenset({"A001", "A002"}),  # A → C
        frozenset({"A000", "A002"}),  # B → C
    }
    swap = by_assets[frozenset({"A001", "A002"})]
    assert [(m.out_asset_ids, m.in_asset_ids) for m in swap.swap_history] == [
        (("A000",), ("A002",))
    ]
    points = [p for p in result.valid_points if p.composition_id == swap.composition_id]
    assert points
    for entry in points:
        metrics = entry.point.metrics
        assert metrics is not None and entry.point.weights is not None
        assert entry.point.weights.tolist() == pytest.approx([0.9, 0.1], abs=1e-6)
        assert metrics.turnover == pytest.approx(0.10, abs=1e-6)
        assert metrics.transaction_cost_one_off == pytest.approx(EXPECTED_COST, abs=1e-8)
        assert metrics.expected_return_net == pytest.approx(
            metrics.expected_return_gross - EXPECTED_COST, abs=1e-8
        )
    # el caso simétrico B → C: A al 90 %, B vendido por completo (peso 0,9), C comprado (0,1)
    other = by_assets[frozenset({"A000", "A002"})]
    metrics = next(
        p.point.metrics for p in result.valid_points if p.composition_id == other.composition_id
    )
    assert metrics is not None
    assert metrics.turnover == pytest.approx(0.5 * (0.8 + 0.9 + 0.1), abs=1e-6)
    expected_cost = 0.8 * BUY[0] + 0.9 * SELL[1] + 0.1 * BUY[2]
    assert metrics.transaction_cost_one_off == pytest.approx(expected_cost, abs=1e-8)


def test_weight_rows_expose_the_sale_of_a_and_the_purchase_of_c_per_asset() -> None:
    config = base_config()
    problem = _problem(config, composition=("A001", "A002"))
    result = ContinuousFrontierEngine(config).solve(
        problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
    )
    alignment = align_union(problem.state, result.asset_ids)
    context = WeightContext(
        tickers={asset.asset_id: asset.ticker for asset in problem.universe},
        mu=MU[1:],
        sigma=SIGMA[1:, 1:],
        alignment=alignment,
        cost_model=TransactionCostModel(alignment, problem.costs, 1.0),  # type: ignore[arg-type]
        zero_volatility_tolerance=config.frontier.zero_volatility_tolerance,
        zero_weight_tolerance=config.frontier.zero_weight_tolerance,
    )
    rows = weight_rows(result, result.valid_points[:1], context)
    by_asset = {row.asset_id: row for row in rows}
    assert set(by_asset) == {"A000", "A001", "A002"}
    removed, kept, new = by_asset["A000"], by_asset["A001"], by_asset["A002"]
    assert removed.is_removed_asset and not removed.is_new_asset
    assert removed.optimized_weight == 0.0 and removed.weight_change == pytest.approx(-SALE_A)
    assert removed.transaction_cost_asset == pytest.approx(SALE_A * SELL[0])
    assert new.is_new_asset and new.transaction_cost_asset == pytest.approx(PURCHASE_C * BUY[2])
    assert new.weight_change == pytest.approx(PURCHASE_C, abs=1e-6)
    assert not kept.is_new_asset and not kept.is_removed_asset
    assert kept.transaction_cost_asset == pytest.approx(0.0, abs=1e-8)
    assert sum(row.transaction_cost_asset or 0.0 for row in rows) == pytest.approx(EXPECTED_COST)
