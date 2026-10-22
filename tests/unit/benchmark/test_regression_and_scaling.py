"""BEN-005 / BEN-004 / BEN-007 / CFG-012 (B5.5): detección de deterioros, aritmética de escalado
y configuración de benchmarks de escala. Oráculos calculados a mano."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from portfolio_engine.benchmark.regression import (
    BaselineCell,
    RegressionVerdict,
    cell_key,
    compare_to_baseline,
    load_baseline,
    mad,
    regression_threshold,
    save_baseline,
)
from portfolio_engine.benchmark.scaling import (
    ProjectionInputs,
    class_contributions,
    efficiency,
    karp_flatt,
    percentile_summary,
    predict_sequential_seconds,
    project_capacity,
    speedup,
)
from portfolio_engine.config.scaling_config import (
    ClassShare,
    WorkloadMix,
    load_scaling_benchmark_config,
)
from portfolio_engine.exceptions import ConfigError, PortfolioEngineError
from tests.conftest import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "config" / "default_benchmark.toml"
HOST = "host-a"

# ------------------------------------------------------------------------------------ regresión


def test_mad_and_threshold_follow_their_definitions() -> None:
    # mediana 10; |x-10| = [1, 0, 2, 1, 3] -> mediana 1
    samples = [9.0, 10.0, 12.0, 11.0, 7.0]
    assert mad(samples) == 1.0
    assert regression_threshold(samples, k=5.0, relative_floor=0.0) == 5.0
    # con MAD = 0 rige el suelo relativo (5 % de la mediana 10 = 0,5)
    assert regression_threshold([10.0, 10.0, 10.0], k=4.0, relative_floor=0.05) == pytest.approx(
        2.0
    )


def _cell(samples: list[float], work: int | None = 100) -> BaselineCell:
    return BaselineCell(tuple(samples), work, HOST)


def test_a_slowdown_beyond_the_threshold_is_detected_and_noise_is_not() -> None:
    baseline = _cell([9.0, 10.0, 12.0, 11.0, 7.0])  # mediana 10, umbral 5
    kwargs = {"host": HOST, "k": 5.0, "relative_floor": 0.0, "current_work": 100}
    assert compare_to_baseline([14.0, 15.0], baseline, **kwargs).verdict is (  # type: ignore[arg-type]
        RegressionVerdict.WITHIN_NOISE
    )  # mediana 14.5: Δ = 4.5 < 5
    slower = compare_to_baseline([16.0, 16.0], baseline, **kwargs)  # type: ignore[arg-type]
    assert slower.verdict is RegressionVerdict.SLOWER and slower.difference == pytest.approx(6.0)
    faster = compare_to_baseline([4.0, 4.0], baseline, **kwargs)  # type: ignore[arg-type]
    assert faster.verdict is RegressionVerdict.FASTER


def test_the_min_statistic_ignores_a_slow_phase_but_still_sees_a_real_slowdown() -> None:
    """Máquinas bimodales: una fase lenta pasajera sube la mediana, no el mínimo."""
    baseline = _cell([10.0, 10.5, 9.5, 10.2, 9.8])  # MAD 0,2 -> umbral con suelo 5 % = 5 x 0,5
    kwargs = {"host": HOST, "k": 5.0, "relative_floor": 0.05}
    mixed = [10.1, 50.0, 49.0]  # una repetición sana y dos en fase lenta
    median_verdict = compare_to_baseline(mixed, baseline, **kwargs)  # type: ignore[arg-type]
    min_verdict = compare_to_baseline(mixed, baseline, statistic="min", **kwargs)  # type: ignore[arg-type]
    assert median_verdict.verdict is RegressionVerdict.SLOWER
    assert min_verdict.verdict is RegressionVerdict.WITHIN_NOISE
    real = compare_to_baseline([20.0, 21.0], baseline, statistic="min", **kwargs)  # type: ignore[arg-type]
    assert real.verdict is RegressionVerdict.SLOWER
    with pytest.raises(PortfolioEngineError):
        compare_to_baseline([1.0], baseline, statistic="mean", **kwargs)  # type: ignore[arg-type]


def test_a_change_of_work_is_not_reported_as_a_change_of_speed() -> None:
    baseline = _cell([10.0, 10.0, 10.0], work=100)
    result = compare_to_baseline(
        [50.0], baseline, host=HOST, k=5.0, relative_floor=0.05, current_work=130
    )
    assert result.verdict is RegressionVerdict.WORK_CHANGED and result.difference is None


def test_other_hosts_and_missing_baselines_give_no_speed_verdict() -> None:
    baseline = _cell([10.0, 10.0])
    other = compare_to_baseline([99.0], baseline, host="host-b", k=5.0, relative_floor=0.05)
    assert other.verdict is RegressionVerdict.HOST_MISMATCH
    none = compare_to_baseline([1.0], None, host=HOST, k=5.0, relative_floor=0.05)
    assert none.verdict is RegressionVerdict.NO_BASELINE
    with pytest.raises(PortfolioEngineError):
        compare_to_baseline([], baseline, host=HOST, k=5.0, relative_floor=0.05)
    with pytest.raises(PortfolioEngineError):
        BaselineCell((), None, HOST)
    with pytest.raises(PortfolioEngineError):
        BaselineCell((0.0,), None, HOST)


def test_a_baseline_round_trips_through_json(tmp_path: Path) -> None:
    cells = {
        cell_key("W0", 10, "spawn-2"): _cell([1.0, 1.1, 0.9], work=7),
        cell_key("W1", 10, "sequential"): _cell([2.0], work=None),
    }
    path = tmp_path / "baseline.json"
    save_baseline(path, cells, {"note": "x"})
    loaded, metadata = load_baseline(path)
    assert loaded == cells and metadata == {"note": "x"}
    path.write_text('{"schema_version": 99, "cells": {}}', encoding="utf-8")
    with pytest.raises(PortfolioEngineError):
        load_baseline(path)
    with pytest.raises(PortfolioEngineError):
        load_baseline(tmp_path / "missing.json")


# ------------------------------------------------------------------------------------- escalado


def test_speedup_efficiency_and_karp_flatt_match_hand_calculations() -> None:
    s = speedup(40.0, 12.5)  # 3,2
    assert s == pytest.approx(3.2)
    assert efficiency(s, 4) == pytest.approx(0.8)
    # e = (1/3,2 - 1/4) / (1 - 1/4) = (0,3125 - 0,25) / 0,75
    assert karp_flatt(s, 4) == pytest.approx((0.3125 - 0.25) / 0.75)
    assert karp_flatt(1.0, 1) is None
    # un speedup perfecto no tiene fracción serie
    assert karp_flatt(4.0, 4) == pytest.approx(0.0)
    with pytest.raises(PortfolioEngineError):
        speedup(0.0, 1.0)
    with pytest.raises(PortfolioEngineError):
        efficiency(1.0, 0)


def test_percentile_summary_uses_the_requested_levels() -> None:
    summary = percentile_summary([1.0, 2.0, 3.0, 4.0, 5.0], [50.0, 95.0])
    assert summary["min"] == 1.0 and summary["max"] == 5.0 and summary["median"] == 3.0
    assert summary["mean"] == 3.0 and summary["p50"] == 3.0
    assert summary["p95"] == pytest.approx(4.8)


def test_the_mix_cost_model_is_n_times_the_weighted_unit_cost() -> None:
    shares = {"A": 0.75, "B": 0.25}
    costs = {"A": 0.2, "B": 2.0}
    assert predict_sequential_seconds(100, shares, costs) == pytest.approx(100 * (0.15 + 0.5))
    contributions = class_contributions(shares, costs)
    assert contributions["A"] == pytest.approx(0.15 / 0.65)
    assert sum(contributions.values()) == pytest.approx(1.0)
    with pytest.raises(PortfolioEngineError):
        predict_sequential_seconds(10, {"C": 1.0}, costs)


def test_the_projection_is_a_range_and_declares_its_extrapolation_factor() -> None:
    inputs = ProjectionInputs(
        unit_seconds=(0.5, 1.0, 2.0),
        efficiency=(0.5, 0.8, 0.9),
        startup_seconds=10.0,
        worker_rss_bytes=100e6,
        coordinator_rss_bytes=200e6,
        measured_portfolios=100,
    )
    p = project_capacity(inputs, portfolios=1000, workers=4, price_per_core_hour=0.1)
    # central: 10 + 1000 · 1,0 / (4 · 0,8) = 322,5 s
    assert p.wall_seconds[1] == pytest.approx(10 + 1000 / 3.2)
    assert p.wall_seconds[0] == pytest.approx(10 + 1000 * 0.5 / (4 * 0.9))
    assert p.wall_seconds[2] == pytest.approx(10 + 1000 * 2.0 / (4 * 0.5))
    assert p.wall_seconds[0] < p.wall_seconds[1] < p.wall_seconds[2]
    assert p.core_hours[1] == pytest.approx(4 * p.wall_seconds[1] / 3600)
    assert p.money is not None and p.money[1] == pytest.approx(p.core_hours[1] * 0.1)
    assert p.peak_memory_bytes == pytest.approx(200e6 + 4 * 100e6)
    assert p.extrapolation_factor == 10.0 and "NO se ha verificado" in p.caveat
    assert project_capacity(inputs, 1000, 4).money is None  # sin precio no se inventa dinero
    with pytest.raises(PortfolioEngineError):
        project_capacity(dataclasses.replace(inputs, unit_seconds=(2.0, 1.0, 0.5)), 10, 1)


# ------------------------------------------------------------------------------- configuración


def test_the_example_benchmark_config_loads_and_every_mix_sums_to_one() -> None:
    config = load_scaling_benchmark_config(CONFIG_PATH)
    assert {m.name for m in config.mixes} == {
        "ENG-MIX-BASE",
        "ENG-MIX-LIGHT",
        "ENG-MIX-HEAVY",
        "ENG-MIX-CONIC",
    }
    assert config.repetitions_for(config.small_scale_max) == config.repetitions_small
    assert config.repetitions_for(config.small_scale_max + 1) == config.repetitions_large
    assert config.mix("ENG-MIX-BASE").shares[0].label == "W0-GROSS-RISK"
    with pytest.raises(ConfigError):
        config.mix("NOPE")


def test_the_benchmark_config_rejects_invalid_values() -> None:
    config = load_scaling_benchmark_config(CONFIG_PATH)
    for change in (
        {"universe_assets": 0},
        {"holdings_max": 99},
        {"degenerate_fraction": 1.0},
        {"mad_k": 0.0},
        {"iteration_relative_tolerance": 1.0},
        {"repetitions_small": 0},
        {"mixes": ()},
        {"max_portfolios_without_authorization": 0},
    ):
        with pytest.raises(ConfigError):
            dataclasses.replace(config, **change)
    with pytest.raises(ConfigError):
        WorkloadMix("M", (ClassShare("A", 0.5), ClassShare("B", 0.4)))  # suma 0,9
    with pytest.raises(ConfigError):
        WorkloadMix("M", (ClassShare("A", 0.5), ClassShare("A", 0.5)))  # repetida
    with pytest.raises(ConfigError):
        ClassShare("A", 0.0)


def test_unknown_or_missing_benchmark_config_keys_are_errors(tmp_path: Path) -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    path = tmp_path / "bad.toml"
    path.write_text(text.replace("mad_k = 5.0\n", ""), encoding="utf-8")
    with pytest.raises(ConfigError, match="mad_k"):
        load_scaling_benchmark_config(path)
    path.write_text(text.replace("mad_k = 5.0\n", "mad_k = 5.0\nsurprise = 1\n"), encoding="utf-8")
    with pytest.raises(ConfigError, match="surprise"):
        load_scaling_benchmark_config(path)
