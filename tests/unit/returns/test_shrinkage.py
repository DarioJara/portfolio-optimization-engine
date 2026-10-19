"""ROB-001: shrinkage de expected returns: un estimador, no optimización robusta.

Valores a mano (intensidad fija) y forma cerrada de Jorion (Bayes-Stein) sobre un caso pequeño.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_engine.config import RobustConfig
from portfolio_engine.exceptions import ConfigError, DataValidationError
from portfolio_engine.models.enums import (
    ExpectedReturnMode,
    InternalEstimationMethod,
    MuUncertaintyKind,
    ShrinkageMethod,
    ShrinkageTarget,
)
from portfolio_engine.models.risk_model import ExpectedReturns
from portfolio_engine.returns.shrinkage import shrink_expected_returns
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

IDS = ("A", "B", "C")
MU = np.array([0.02, 0.06, 0.10])
SIGMA = np.array([[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.16]])
DAYS = 252


def _expected(mode: ExpectedReturnMode = ExpectedReturnMode.INTERNAL_ESTIMATION) -> ExpectedReturns:
    method = (
        InternalEstimationMethod.HISTORICAL_MEAN.value
        if mode is ExpectedReturnMode.INTERNAL_ESTIMATION
        else "EXTERNAL_ALPHA"
    )
    return ExpectedReturns(IDS, MU, mode, method)


def _config(**changes: object) -> RobustConfig:
    values: dict[str, object] = {
        "mu_uncertainty": MuUncertaintyKind.NONE,
        "box_z": None,
        "ellipsoid_confidence": None,
        "covariance_scale_max": None,
        "shrinkage_method": ShrinkageMethod.FIXED_INTENSITY,
        "shrinkage_intensity": 0.25,
        "shrinkage_target": ShrinkageTarget.GRAND_MEAN,
    }
    values.update(changes)
    return RobustConfig(**values)  # type: ignore[arg-type]


def test_fixed_intensity_towards_the_grand_mean_by_hand() -> None:
    result = shrink_expected_returns(_expected(), SIGMA, 500, DAYS, 0.02, _config())
    grand = MU.mean()
    np.testing.assert_allclose(result.expected_returns.values, 0.75 * MU + 0.25 * grand)
    assert result.intensity == 0.25 and result.method is ShrinkageMethod.FIXED_INTENSITY
    np.testing.assert_allclose(result.target, np.full(3, grand))
    # el resultado se etiqueta como media encogida, nunca como la media histórica ni como alpha
    assert result.expected_returns.method == InternalEstimationMethod.SHRUNK_HISTORICAL_MEAN.value
    assert result.expected_returns.mode is ExpectedReturnMode.INTERNAL_ESTIMATION
    assert not result.expected_returns.is_external_alpha
    np.testing.assert_allclose(_expected().values, MU)  # el original no se modifica


@pytest.mark.parametrize("intensity", [0.0, 1.0])
def test_extreme_intensities(intensity: float) -> None:
    result = shrink_expected_returns(
        _expected(), SIGMA, 500, DAYS, 0.02, _config(shrinkage_intensity=intensity)
    )
    expected = MU if intensity == 0.0 else np.full(3, MU.mean())
    np.testing.assert_allclose(result.expected_returns.values, expected)


def test_targets_risk_free_and_supplied() -> None:
    risk_free = shrink_expected_returns(
        _expected(),
        SIGMA,
        500,
        DAYS,
        0.03,
        _config(shrinkage_target=ShrinkageTarget.RISK_FREE, shrinkage_intensity=0.5),
    )
    np.testing.assert_allclose(risk_free.expected_returns.values, 0.5 * MU + 0.5 * 0.03)
    prior = np.array([0.05, 0.05, 0.05])
    supplied = shrink_expected_returns(
        _expected(),
        SIGMA,
        500,
        DAYS,
        0.03,
        _config(shrinkage_target=ShrinkageTarget.SUPPLIED, shrinkage_intensity=0.4),
        prior,
    )
    np.testing.assert_allclose(supplied.expected_returns.values, 0.6 * MU + 0.4 * prior)
    with pytest.raises(DataValidationError, match="SUPPLIED"):
        shrink_expected_returns(
            _expected(), SIGMA, 500, DAYS, 0.03, _config(shrinkage_target=ShrinkageTarget.SUPPLIED)
        )


def test_jorion_matches_its_closed_form() -> None:
    """Bayes-Stein: ``δ = (N+2)/((N+2) + Y·q)`` con ``q = (μ̂−μ₀1)ᵀΣ⁻¹(μ̂−μ₀1)`` y ``μ₀`` GMV."""
    config = _config(shrinkage_method=ShrinkageMethod.JORION, shrinkage_intensity=None)
    result = shrink_expected_returns(_expected(), SIGMA, 504, DAYS, 0.02, config)
    inverse = np.linalg.inv(SIGMA)
    ones = np.ones(3)
    grand = float(ones @ inverse @ MU / (ones @ inverse @ ones))
    deviation = MU - grand
    quadratic = float(deviation @ inverse @ deviation)
    years = 504 / DAYS
    weight = 5.0 / (5.0 + years * quadratic)
    assert result.intensity == pytest.approx(weight, rel=1e-12)
    np.testing.assert_allclose(result.target, np.full(3, grand))
    np.testing.assert_allclose(
        result.expected_returns.values, (1.0 - weight) * MU + weight * grand, rtol=1e-12
    )
    # más datos ⇒ menos shrinkage
    more = shrink_expected_returns(_expected(), SIGMA, 5040, DAYS, 0.02, config)
    assert more.intensity < result.intensity
    assert 0.0 < more.intensity < result.intensity < 1.0


def test_jorion_requires_a_positive_definite_covariance_and_the_grand_mean_target() -> None:
    config = _config(shrinkage_method=ShrinkageMethod.JORION, shrinkage_intensity=None)
    with pytest.raises(DataValidationError, match="definida positiva"):
        shrink_expected_returns(_expected(), np.ones((3, 3)) * 0.04, 504, DAYS, 0.02, config)
    with pytest.raises(DataValidationError, match="observaciones"):
        shrink_expected_returns(_expected(), SIGMA, 0, DAYS, 0.02, config)
    wrong = _config(
        shrinkage_method=ShrinkageMethod.JORION,
        shrinkage_intensity=None,
        shrinkage_target=ShrinkageTarget.RISK_FREE,
    )
    with pytest.raises(ConfigError, match="GRAND_MEAN"):
        shrink_expected_returns(_expected(), SIGMA, 504, DAYS, 0.02, wrong)


def test_an_external_alpha_is_never_shrunk() -> None:
    with pytest.raises(DataValidationError, match="alpha externo"):
        shrink_expected_returns(
            _expected(ExpectedReturnMode.EXTERNAL_ALPHA), SIGMA, 500, DAYS, 0.02, _config()
        )


def test_shrinkage_is_not_selectable_as_a_returns_estimation_method_and_is_not_robust() -> None:
    """La media encogida se aplica a un ``RiskModel``; no es una opción de ``[returns]`` y no
    convierte nada en optimización robusta (la formulación robusta la rechaza sin conjunto)."""
    import dataclasses

    config = base_config()
    with pytest.raises(ConfigError, match="no es seleccionable"):
        dataclasses.replace(
            config.returns,
            internal_estimation_method=InternalEstimationMethod.SHRUNK_HISTORICAL_MEAN,
        )
    with pytest.raises(ConfigError, match="shrinkage_method"):
        shrink_expected_returns(
            _expected(),
            SIGMA,
            500,
            DAYS,
            0.02,
            _config(shrinkage_method=None, shrinkage_intensity=None, shrinkage_target=None),
        )


def test_robust_configuration_is_strict() -> None:
    with pytest.raises(ConfigError, match="box_z"):
        RobustConfig(MuUncertaintyKind.BOX, None, None, None, None, None, None)
    with pytest.raises(ConfigError, match="solo se admite"):
        RobustConfig(MuUncertaintyKind.NONE, 1.0, None, None, None, None, None)
    with pytest.raises(ConfigError, match="ellipsoid_confidence"):
        RobustConfig(MuUncertaintyKind.ELLIPSOIDAL, None, None, None, None, None, None)
    with pytest.raises(ConfigError, match=r"\(0, 1\)"):
        RobustConfig(MuUncertaintyKind.ELLIPSOIDAL, None, 1.0, None, None, None, None)
    with pytest.raises(ConfigError, match=">= 1"):
        RobustConfig(MuUncertaintyKind.NONE, None, None, 0.5, None, None, None)
    with pytest.raises(ConfigError, match="shrinkage_method"):
        RobustConfig(MuUncertaintyKind.NONE, None, None, None, None, 0.1, None)
    with pytest.raises(ConfigError, match="shrinkage_target"):
        RobustConfig(
            MuUncertaintyKind.NONE, None, None, None, ShrinkageMethod.FIXED_INTENSITY, 0.1, None
        )
    with pytest.raises(ConfigError, match=r"\[0, 1\]"):
        _config(shrinkage_intensity=1.5)
    with pytest.raises(ConfigError, match="estima la intensidad"):
        _config(shrinkage_method=ShrinkageMethod.JORION, shrinkage_intensity=0.2)
