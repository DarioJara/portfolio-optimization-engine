"""CFG-008 (remediación F-3): parámetros de la recuperación numérica en ``SolverConfig``."""

from __future__ import annotations

import pytest

from portfolio_engine.config import load_engine_config
from portfolio_engine.exceptions import ConfigError
from tests.conftest import DEFAULT_CONFIG_PATH
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit


def test_the_default_configuration_enables_the_recovery_with_a_scale_ladder() -> None:
    solver = load_engine_config(DEFAULT_CONFIG_PATH).solver
    assert solver.numerical_recovery is True
    assert solver.recovery_row_scales == (10.0, 1.0, 100.0)


def test_the_recovery_can_be_disabled() -> None:
    assert base_config(solver={"numerical_recovery": False}).solver.numerical_recovery is False


@pytest.mark.parametrize("scales", [(), (0.0,), (10.0, -1.0)])
def test_the_scale_ladder_must_be_non_empty_and_positive(scales: tuple[float, ...]) -> None:
    with pytest.raises(ConfigError):
        base_config(solver={"recovery_row_scales": scales})


def test_an_empty_ladder_is_accepted_only_without_recovery() -> None:
    config = base_config(solver={"numerical_recovery": False, "recovery_row_scales": ()})
    assert config.solver.recovery_row_scales == ()


def test_the_recovery_flag_must_be_boolean() -> None:
    with pytest.raises(ConfigError):
        base_config(solver={"numerical_recovery": 1})
