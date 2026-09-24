"""CFG-005 (extensión), CFG-007, CFG-008, CFG-012 (subset), DAT-028, FRN-018: configuración del
Bloque 2."""

from __future__ import annotations

import copy
import dataclasses
import tomllib

import pytest

from portfolio_engine.config import (
    BenchmarkConfig,
    FrontierConfig,
    GroupLimit,
    SolverConfig,
    config_hash,
    load_engine_config,
)
from portfolio_engine.data.validation import UniverseValidator
from portfolio_engine.exceptions import ConfigError, DataValidationError
from portfolio_engine.models.enums import (
    CrossCheckPolicy,
    GridScale,
    GroupDimension,
    ThetaGridMode,
)
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.problems import base_config, with_group_limits
from tests.fixtures.synthetic import universe_frame

pytestmark = pytest.mark.unit


def _raw() -> dict[str, dict[str, object]]:
    with DEFAULT_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_default_configuration_declares_the_block_2_sections() -> None:
    """Los valores por defecto (20 puntos, OSQP, tolerancias) viven solo en la configuración
    (A-29)."""
    config = load_engine_config(_raw())
    assert isinstance(config.frontier, FrontierConfig) and config.frontier.frontier_points == 20
    assert not config.frontier.adaptive and config.frontier.theta_grid_mode is ThetaGridMode.AUTO
    assert config.frontier.theta_scale is GridScale.LOG
    assert (
        isinstance(config.solver, SolverConfig)
        and config.solver.workspace_reuse
        and config.solver.warm_start
    )
    assert config.solver.ambiguous_status_policy is CrossCheckPolicy.COLD_RETRY
    assert isinstance(config.benchmark, BenchmarkConfig) and config.benchmark.percentiles == (
        50.0,
        95.0,
        99.0,
    )
    assert config.constraints.group_limits == () and config.constraints.global_max_turnover is None


@pytest.mark.parametrize("section", ["frontier", "solver", "benchmark"])
def test_block_2_sections_are_mandatory_and_strict(section: str) -> None:
    raw = _raw()
    del raw[section]
    with pytest.raises(ConfigError, match="ausentes"):
        load_engine_config(raw)
    raw = _raw()
    raw[section]["unknown_key"] = 1
    with pytest.raises(ConfigError, match="desconocidas"):
        load_engine_config(raw)
    raw = _raw()
    first_key = next(iter(raw[section]))
    del raw[section][first_key]
    with pytest.raises(ConfigError, match="obligatoria ausente"):
        load_engine_config(raw)


def test_group_limits_are_loaded_from_arrays_of_tables_and_change_the_hash() -> None:
    """CFG-005: ``[[constraints.group_limits]]`` → tupla de :class:`GroupLimit` inmutable,
    incluida en el hash."""
    raw = copy.deepcopy(_raw())
    raw["constraints"]["group_limits"] = [
        {"dimension": "SECTOR", "group": "Tech", "max_weight": 0.6},
        {"dimension": "CURRENCY", "group": "EUR", "min_weight": 0.2, "max_weight": 0.9},
    ]
    config = load_engine_config(raw)
    assert config.constraints.group_limits == (
        GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.6),
        GroupLimit(GroupDimension.CURRENCY, "EUR", 0.2, 0.9),
    )
    assert config_hash(config) != config_hash(load_engine_config(_raw()))
    raw["constraints"]["group_limits"][0]["unknown"] = 1
    with pytest.raises(ConfigError, match="desconocidas"):
        load_engine_config(raw)


def test_group_limit_validation() -> None:
    with pytest.raises(ConfigError, match="ningún límite"):
        GroupLimit(GroupDimension.SECTOR, "Tech", None, None)
    with pytest.raises(ConfigError, match="min_weight > max_weight"):
        GroupLimit(GroupDimension.SECTOR, "Tech", 0.7, 0.6)
    constraints = base_config().constraints
    with pytest.raises(ConfigError, match="duplicado"):
        dataclasses.replace(
            constraints,
            group_limits=(
                GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.6),
                GroupLimit(GroupDimension.SECTOR, "Tech", 0.1, None),
            ),
        )
    with pytest.raises(ConfigError, match="global_max_turnover"):
        dataclasses.replace(constraints, global_max_turnover=-0.1)


def test_frontier_config_validation() -> None:
    frontier = base_config().frontier
    with pytest.raises(ConfigError):
        dataclasses.replace(frontier, frontier_points=1)
    with pytest.raises(ConfigError, match="EXPLICIT exige"):
        dataclasses.replace(frontier, theta_grid_mode=ThetaGridMode.EXPLICIT)
    with pytest.raises(ConfigError, match="solo se admiten con"):
        dataclasses.replace(frontier, theta_min=0.1, theta_max=1.0)
    with pytest.raises(ConfigError, match="menor"):
        dataclasses.replace(
            frontier, theta_grid_mode=ThetaGridMode.EXPLICIT, theta_min=2.0, theta_max=1.0
        )
    with pytest.raises(ConfigError, match="theta_auto_min_multiplier"):
        dataclasses.replace(frontier, theta_auto_min_multiplier=10.0, theta_auto_max_multiplier=1.0)
    for field in (
        "dedup_weight_tolerance",
        "pareto_tolerance",
        "zero_weight_tolerance",
        "min_holding_weight",
    ):
        with pytest.raises(ConfigError):
            dataclasses.replace(frontier, **{field: -1.0})


def test_solver_config_validation() -> None:
    solver = base_config().solver
    for field, value in (
        ("eps_abs", 0.0),
        ("max_iterations", 0),
        ("adaptive_rho_interval", 0),  # 0 haría el resultado dependiente del reloj
        ("retry_iteration_multiplier", 0),
        ("time_limit_seconds", -1.0),
        ("bound_tolerance", -1e-9),
        ("polish", "yes"),
        ("ambiguous_status_policy", "COLD_RETRY"),
    ):
        with pytest.raises(ConfigError):
            dataclasses.replace(solver, **{field: value})
    assert dataclasses.replace(solver, time_limit_seconds=5.0).time_limit_seconds == 5.0


def test_benchmark_config_validation() -> None:
    bench = base_config().benchmark
    for changes in (
        {"repetitions": 0},
        {"warmup_runs": -1},
        {"percentiles": ()},
        {"percentiles": (0.0,)},
    ):
        with pytest.raises(ConfigError):
            dataclasses.replace(bench, **changes)


def test_block_2_parameters_change_the_config_hash() -> None:
    base = base_config()
    changes = {
        "frontier": {"frontier_points": 30},
        "solver": {"eps_abs": 1e-8},
        "benchmark": {"repetitions": 6},
    }
    for section, values in changes.items():
        other = dataclasses.replace(
            base, **{section: dataclasses.replace(getattr(base, section), **values)}
        )
        assert config_hash(other) != config_hash(base)


def test_universe_requires_grouping_metadata_when_group_limits_exist() -> None:
    """DAT-028: con límites de grupo configurados, el atributo de grupo pasa de recomendado a
    obligatorio."""
    frame = universe_frame(
        4, Sector=["Tech", None, "Tech", "Energy"], Country=["ES", "ES", None, "ES"]
    )
    plain = base_config()
    assert not UniverseValidator(plain.constraints).validate(frame).report.has_errors  # solo avisos
    limited = with_group_limits(plain, [GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.5)])
    with pytest.raises(DataValidationError, match="Sector es obligatorio") as error:
        UniverseValidator(limited.constraints).validate(frame)
    severities = [issue.severity.value for issue in error.value.issues]  # type: ignore[attr-defined]
    assert severities.count("ERROR") == 1  # Country sigue siendo solo un aviso
    both = with_group_limits(plain, [GroupLimit(GroupDimension.COUNTRY, "ES", None, 1.0)])
    with pytest.raises(DataValidationError, match="Country es obligatorio"):
        UniverseValidator(both.constraints).validate(frame)


# --------------------------------------------- MaximumReturn: LP (HiGHS) y holgura de la etapa 2


def test_max_return_tolerance_is_in_the_solver_section_only() -> None:
    """La holgura de la etapa 2 tiene una única fuente (``[solver]``); ``frontier`` ya no la
    declara y ``default_engine.toml`` es el único lugar con sus valores."""
    raw = _raw()
    assert "max_return_tie_epsilon" not in raw["frontier"]
    assert not hasattr(base_config().frontier, "max_return_tie_epsilon")
    for name in (
        "max_return_tie_abs_tolerance",
        "max_return_tie_rel_tolerance",
        "lp_feasibility_tolerance",
        "lp_max_iterations",
    ):
        assert name in raw["solver"] and hasattr(base_config().solver, name)


def test_max_return_tie_tolerance_is_absolute_or_relative_in_return_units() -> None:
    solver = dataclasses.replace(
        base_config().solver,
        max_return_tie_abs_tolerance=1e-8,
        max_return_tie_rel_tolerance=1e-6,
    )
    assert solver.max_return_tie_tolerance(0.0) == 1e-8  # domina el criterio absoluto
    assert solver.max_return_tie_tolerance(0.001) == 1e-8  # 1e-6 · 1e-3 = 1e-9 < 1e-8
    assert solver.max_return_tie_tolerance(0.10) == pytest.approx(1e-7)  # domina el relativo
    assert solver.max_return_tie_tolerance(-0.10) == pytest.approx(1e-7)  # simétrico en signo
    absolute_only = dataclasses.replace(solver, max_return_tie_rel_tolerance=0.0)
    assert absolute_only.max_return_tie_tolerance(5.0) == 1e-8
    relative_only = dataclasses.replace(
        solver, max_return_tie_abs_tolerance=0.0, max_return_tie_rel_tolerance=1e-6
    )
    assert relative_only.max_return_tie_tolerance(0.10) == pytest.approx(1e-7)


def test_max_return_and_lp_parameters_are_validated() -> None:
    solver = base_config().solver
    for field, value in (
        ("max_return_tie_abs_tolerance", -1e-9),
        ("max_return_tie_rel_tolerance", -1e-9),
        ("lp_feasibility_tolerance", 0.0),
        ("lp_max_iterations", 0),
    ):
        with pytest.raises(ConfigError):
            dataclasses.replace(solver, **{field: value})
    with pytest.raises(ConfigError, match="no puede ser nula"):
        dataclasses.replace(
            solver, max_return_tie_abs_tolerance=0.0, max_return_tie_rel_tolerance=0.0
        )


def test_max_return_and_lp_parameters_change_the_config_hash() -> None:
    base = base_config()
    for field, value in (
        ("max_return_tie_abs_tolerance", 2e-8),
        ("max_return_tie_rel_tolerance", 2e-7),
        ("lp_feasibility_tolerance", 1e-8),
        ("lp_max_iterations", 5),
    ):
        other = dataclasses.replace(base, solver=dataclasses.replace(base.solver, **{field: value}))
        assert config_hash(other) != config_hash(base), field
