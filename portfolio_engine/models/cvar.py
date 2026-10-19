"""Escenarios de retorno para el CVaR (MASTER_SPEC §22; decisión A-35; OPT-011, OPT-012).

Un :class:`ReturnScenarioSet` es una medida discreta sobre retornos **por periodo** (históricos o
simulados) de un conjunto de activos: ``T`` observaciones ``r_t ∈ R^n`` con pesos ``π_t``. Se
valida al construirlo; nada se inventa ni se imputa (un dato faltante es un error) y las
probabilidades iguales solo se admiten si la configuración las declara (``EQUAL``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.enums import CVaRSource, ScenarioWeighting
from portfolio_engine.utils.numerics import readonly_float_array


@dataclass(frozen=True, eq=False, slots=True)
class ReturnScenarioSet:
    """``T`` escenarios de retorno por periodo de ``n`` activos, con sus pesos.

    Attributes:
        asset_ids: ``AssetID`` únicos y ordenados (columnas de ``returns``).
        returns: matriz ``T × n`` de retornos por periodo (fracción decimal).
        weights: pesos ``π_t`` (``≥ 0``, suman 1).
        source: procedencia (histórica o simulada).
        weighting: cómo se obtuvieron los pesos (``EQUAL`` = medida empírica uniforme declarada).
        weight_sum_tolerance: desviación máxima de ``Σ π_t`` respecto de 1 (de configuración).
    """

    asset_ids: tuple[str, ...]
    returns: npt.NDArray[np.float64]
    weights: npt.NDArray[np.float64]
    source: CVaRSource
    weighting: ScenarioWeighting
    weight_sum_tolerance: float

    def __post_init__(self) -> None:
        if not self.asset_ids or list(self.asset_ids) != sorted(set(self.asset_ids)):
            raise DataValidationError("ReturnScenarioSet exige AssetID únicos y ordenados.")
        data = readonly_float_array(self.returns)
        weights = readonly_float_array(self.weights)
        if data.ndim != 2 or data.shape[1] != len(self.asset_ids):
            raise DataValidationError("returns debe ser T × n con una columna por activo.")
        if data.shape[0] < 2:
            raise DataValidationError("Se necesitan al menos dos escenarios de retorno.")
        if weights.shape != (data.shape[0],):
            raise DataValidationError("weights debe tener un peso por escenario.")
        if not np.all(np.isfinite(data)):
            raise DataValidationError(
                "returns contiene NaN o infinitos: los datos faltantes no se imputan."
            )
        if np.any(weights < 0.0) or not np.all(np.isfinite(weights)):
            raise DataValidationError("Los pesos de escenario deben ser finitos y no negativos.")
        if not math.isclose(
            float(weights.sum()), 1.0, rel_tol=0.0, abs_tol=self.weight_sum_tolerance
        ):
            raise DataValidationError("Los pesos de escenario deben sumar 1.")
        object.__setattr__(self, "returns", data)
        object.__setattr__(self, "weights", weights)

    @property
    def n_scenarios(self) -> int:
        """Número de escenarios ``T``."""
        return int(self.returns.shape[0])

    def columns_for(self, asset_ids: Sequence[str]) -> npt.NDArray[np.float64]:
        """Submatriz ``T × k`` de ``asset_ids`` (error si falta alguno)."""
        position = {asset_id: index for index, asset_id in enumerate(self.asset_ids)}
        missing = [asset_id for asset_id in asset_ids if asset_id not in position]
        if missing:
            raise DataValidationError(f"Activos sin escenarios de retorno: {missing}")
        indices = np.array([position[asset_id] for asset_id in asset_ids], dtype=np.int64)
        return np.array(self.returns[:, indices], dtype=np.float64)


def build_return_scenario_set(
    asset_ids: Sequence[str],
    returns: npt.ArrayLike,
    source: CVaRSource,
    weighting: ScenarioWeighting,
    weights: npt.ArrayLike | None,
    weight_sum_tolerance: float,
) -> ReturnScenarioSet:
    """Construye un :class:`ReturnScenarioSet` respetando la política de pesos declarada.

    Con ``EQUAL`` no se admiten pesos (medida uniforme explícita); con ``EXPLICIT`` son
    obligatorios y no se renormalizan.
    """
    matrix = np.asarray(returns, dtype=np.float64)
    if matrix.ndim != 2:
        raise DataValidationError("returns debe ser una matriz T × n.")
    if weighting is ScenarioWeighting.EQUAL:
        if weights is not None:
            raise DataValidationError("weighting = EQUAL no admite pesos explícitos.")
        vector = np.full(matrix.shape[0], 1.0 / matrix.shape[0], dtype=np.float64)
    else:
        if weights is None:
            raise DataValidationError("weighting = EXPLICIT exige pesos de escenario.")
        vector = np.asarray(weights, dtype=np.float64)
    return ReturnScenarioSet(
        tuple(asset_ids), matrix, vector, source, weighting, weight_sum_tolerance
    )
