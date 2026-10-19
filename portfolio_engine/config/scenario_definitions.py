"""Definiciones declarativas de escenarios (MASTER_SPEC §53; decisión A-22; SCN-001, SCN-010).

Un :class:`ScenarioDefinition` describe **datos**, no comportamiento: transformaciones
declarativas del modelo de riesgo base (desplazamiento y escala de ``μ`` por grupo, escala de
volatilidad por grupo, estrés de correlación, multiplicador de costes, overrides de restricciones,
límites de estrés) o entradas ``CUSTOM`` suministradas. El tipo de escenario (``BULL``, ``BEAR``,
``RATE_UP``…) es una etiqueta: **ninguna magnitud de shock está en el código**; cada una procede de
la definición. Se cargan desde TOML con :func:`load_scenario_definitions` (claves desconocidas o
ausentes son errores, igual que en la configuración del motor).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from portfolio_engine.config._validation import require_finite, require_positive
from portfolio_engine.config.constraint_config import GroupLimit
from portfolio_engine.config.loader import build_dataclass, read_toml
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.models.enums import CorrelationTarget, ScenarioType, ShockSelector

SCENARIO_TABLE = "scenario"


def _check_selection(selector: ShockSelector, values: tuple[str, ...], owner: str) -> None:
    if selector is ShockSelector.ALL:
        if values:
            raise ConfigError(f"{owner}: selector ALL no admite values.")
    elif not values:
        raise ConfigError(f"{owner}: selector {selector.value} exige al menos un valor.")
    if len(set(values)) != len(values):
        raise ConfigError(f"{owner}: values contiene duplicados.")


@dataclass(frozen=True, slots=True)
class AssetShock:
    """Transformación de ``μ`` y de la volatilidad de un conjunto de activos.

    ``μ' = μ·mu_scale + mu_shift`` (escala primero, luego desplazamiento aditivo anual) y
    ``σ' = σ·vol_scale``. Los shocks se aplican en orden y se componen. Al menos uno de los tres
    parámetros es obligatorio.
    """

    selector: ShockSelector
    values: tuple[str, ...]
    mu_scale: float | None
    mu_shift: float | None
    vol_scale: float | None

    def __post_init__(self) -> None:
        _check_selection(self.selector, self.values, "AssetShock")
        if self.mu_scale is None and self.mu_shift is None and self.vol_scale is None:
            raise ConfigError(
                "AssetShock sin ninguna transformación (mu_scale/mu_shift/vol_scale)."
            )
        if self.mu_scale is not None:
            require_finite(self.mu_scale, "AssetShock.mu_scale")
        if self.mu_shift is not None:
            require_finite(self.mu_shift, "AssetShock.mu_shift")
        if self.vol_scale is not None:
            require_positive(self.vol_scale, "AssetShock.vol_scale")


@dataclass(frozen=True, slots=True)
class CorrelationStress:
    """Estrés de correlación: ``R' = (1 − ρ)·R + ρ·R_objetivo`` con ``ρ`` = ``intensity``.

    ``CONSTANT`` mezcla hacia la matriz de correlación constante ``c``; ``SUPPLIED`` hacia
    ``target_matrix`` (sobre ``target_asset_ids``, que debe cubrir todo el universo del escenario).
    La mezcla convexa de dos matrices de correlación PSD es una matriz de correlación PSD.
    """

    intensity: float
    target: CorrelationTarget
    constant: float | None
    target_asset_ids: tuple[str, ...] | None
    target_matrix: tuple[tuple[float, ...], ...] | None

    def __post_init__(self) -> None:
        require_finite(self.intensity, "CorrelationStress.intensity")
        if not 0.0 <= self.intensity <= 1.0:
            raise ConfigError("CorrelationStress.intensity debe estar en [0, 1].")
        if self.target is CorrelationTarget.CONSTANT:
            if self.constant is None:
                raise ConfigError("CorrelationStress CONSTANT exige constant.")
            require_finite(self.constant, "CorrelationStress.constant")
            if not -1.0 < self.constant < 1.0:
                raise ConfigError("CorrelationStress.constant debe estar en (-1, 1).")
            if self.target_matrix is not None or self.target_asset_ids is not None:
                raise ConfigError("CorrelationStress CONSTANT no admite target_matrix.")
        else:
            if self.target_matrix is None or self.target_asset_ids is None:
                raise ConfigError("CorrelationStress SUPPLIED exige target_matrix y asset_ids.")
            if self.constant is not None:
                raise ConfigError("CorrelationStress SUPPLIED no admite constant.")
            size = len(self.target_asset_ids)
            if any(len(row) != size for row in self.target_matrix) or (
                len(self.target_matrix) != size
            ):
                raise ConfigError("CorrelationStress.target_matrix debe ser n×n.")
            if list(self.target_asset_ids) != sorted(set(self.target_asset_ids)):
                raise ConfigError("CorrelationStress.target_asset_ids: únicos y ordenados.")


@dataclass(frozen=True, slots=True)
class CostShock:
    """Multiplicador de los costes de compra y venta de un conjunto de activos."""

    selector: ShockSelector
    values: tuple[str, ...]
    multiplier: float

    def __post_init__(self) -> None:
        _check_selection(self.selector, self.values, "CostShock")
        require_finite(self.multiplier, "CostShock.multiplier")
        if self.multiplier < 0.0:
            raise ConfigError("CostShock.multiplier no puede ser negativo.")


@dataclass(frozen=True, slots=True)
class ConstraintOverrides:
    """Overrides de restricciones del escenario (``constraints_s``, SCN-009).

    Sustituyen a los valores efectivos de la cartera: ``max_turnover``, los límites de peso
    globales y los límites de grupo (un límite con el mismo ``(dimension, group)`` reemplaza al
    existente; el resto se añade).
    """

    max_turnover: float | None
    global_min_weight: float | None
    global_max_weight: float | None
    group_limits: tuple[GroupLimit, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.max_turnover, "max_turnover"),
            (self.global_min_weight, "global_min_weight"),
            (self.global_max_weight, "global_max_weight"),
        ):
            if value is not None:
                require_finite(value, f"ConstraintOverrides.{name}")
        if self.max_turnover is not None and self.max_turnover < 0.0:
            raise ConfigError("ConstraintOverrides.max_turnover no puede ser negativo.")
        if (
            self.max_turnover is None
            and self.global_min_weight is None
            and self.global_max_weight is None
            and not self.group_limits
        ):
            raise ConfigError("ConstraintOverrides vacío.")

    @property
    def keys(self) -> tuple[str, ...]:
        """Nombres de los overrides efectivos (trazabilidad)."""
        names = []
        if self.max_turnover is not None:
            names.append("max_turnover")
        if self.global_min_weight is not None:
            names.append("global_min_weight")
        if self.global_max_weight is not None:
            names.append("global_max_weight")
        if self.group_limits:
            names.append("group_limits")
        return tuple(names)


@dataclass(frozen=True, slots=True)
class StressLimits:
    """Límites que una solución única debe cumplir **bajo** este escenario (``BaseWithStress``).

    ``max_volatility`` acota ``√(wᵀΣ_s w)`` y ``min_return`` exige un retorno esperado del
    escenario ``μ_sᵀw − TC_s(w) ≥ min_return``. Solo los usa ``BASE_WITH_STRESS_CONSTRAINTS``.
    """

    max_volatility: float | None
    min_return: float | None

    def __post_init__(self) -> None:
        if self.max_volatility is None and self.min_return is None:
            raise ConfigError("StressLimits sin ningún límite.")
        if self.max_volatility is not None:
            require_positive(self.max_volatility, "StressLimits.max_volatility")
        if self.min_return is not None:
            require_finite(self.min_return, "StressLimits.min_return")


@dataclass(frozen=True, slots=True)
class CustomScenarioInputs:
    """Entradas ``CUSTOM``: ``μ_s`` y/o ``Σ_s`` suministradas sobre ``asset_ids`` (ordenados)."""

    asset_ids: tuple[str, ...]
    mu: tuple[float, ...] | None
    covariance: tuple[tuple[float, ...], ...] | None

    def __post_init__(self) -> None:
        size = len(self.asset_ids)
        if size == 0 or list(self.asset_ids) != sorted(set(self.asset_ids)):
            raise ConfigError("CustomScenarioInputs.asset_ids: no vacío, único y ordenado.")
        if self.mu is None and self.covariance is None:
            raise ConfigError("CustomScenarioInputs sin mu ni covariance.")
        if self.mu is not None and (
            len(self.mu) != size or not all(math.isfinite(value) for value in self.mu)
        ):
            raise ConfigError("CustomScenarioInputs.mu: un valor finito por activo.")
        if self.covariance is not None:
            if len(self.covariance) != size or any(len(row) != size for row in self.covariance):
                raise ConfigError("CustomScenarioInputs.covariance debe ser n×n.")
            if not all(math.isfinite(value) for row in self.covariance for value in row):
                raise ConfigError("CustomScenarioInputs.covariance debe ser finita.")


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """Definición declarativa de un escenario.

    Attributes:
        scenario_id: identificador único (``ScenarioID``).
        scenario_type: etiqueta de tipo (no determina ninguna magnitud).
        probability: probabilidad del escenario (``None`` = no configurada; los modos que la
            necesitan la exigen, nunca se supone uniforme).
        description: texto libre de trazabilidad.
        asset_shocks: transformaciones de ``μ`` y volatilidad, aplicadas en orden.
        correlation_stress: estrés de correlación posterior al de volatilidad.
        cost_shocks: multiplicadores de costes.
        constraint_overrides: overrides de restricciones (``constraints_s``).
        stress_limits: límites de estrés de ``BaseWithStress``.
        custom: entradas ``CUSTOM`` (sustituyen a ``μ``/``Σ`` base antes de las transformaciones).
    """

    scenario_id: str
    scenario_type: ScenarioType
    probability: float | None
    description: str | None
    asset_shocks: tuple[AssetShock, ...]
    correlation_stress: CorrelationStress | None
    cost_shocks: tuple[CostShock, ...]
    constraint_overrides: ConstraintOverrides | None
    stress_limits: StressLimits | None
    custom: CustomScenarioInputs | None

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise ConfigError("ScenarioDefinition.scenario_id debe ser un texto no vacío.")
        if self.probability is not None:
            require_finite(self.probability, f"{self.scenario_id}.probability")
            if not 0.0 <= self.probability <= 1.0:
                raise ConfigError(f"{self.scenario_id}: probability debe estar en [0, 1].")
        if self.scenario_type is ScenarioType.CUSTOM and self.custom is None:
            if not self.has_transformations:
                raise ConfigError(
                    f"{self.scenario_id}: un escenario CUSTOM exige entradas custom o "
                    "transformaciones."
                )
        elif self.scenario_type not in (ScenarioType.BASE, ScenarioType.CUSTOM) and not (
            self.has_transformations or self.custom is not None
        ):
            raise ConfigError(
                f"{self.scenario_id}: el escenario {self.scenario_type.value} no define ninguna "
                "transformación; las magnitudes proceden siempre de la configuración y ninguna "
                "se asume por el tipo."
            )

    @property
    def has_transformations(self) -> bool:
        """``True`` si transforma ``μ``, ``Σ``, costes o restricciones."""
        return bool(
            self.asset_shocks
            or self.correlation_stress is not None
            or self.cost_shocks
            or self.constraint_overrides is not None
        )

    @property
    def is_identity(self) -> bool:
        """``True`` si no modifica ningún dato base (``BASE`` sin modificaciones expresas)."""
        return not self.has_transformations and self.custom is None


def validate_scenario_set(definitions: tuple[ScenarioDefinition, ...]) -> None:
    """Exige identificadores únicos y como mucho un escenario ``BASE``."""
    ids = [definition.scenario_id for definition in definitions]
    if len(set(ids)) != len(ids):
        raise ConfigError(f"ScenarioID duplicados: {sorted({i for i in ids if ids.count(i) > 1})}")
    bases = [d.scenario_id for d in definitions if d.scenario_type is ScenarioType.BASE]
    if len(bases) > 1:
        raise ConfigError(f"Más de un escenario BASE: {bases}")


def load_scenario_definitions(
    source: str | Path | Mapping[str, Any],
) -> tuple[ScenarioDefinition, ...]:
    """Carga y valida las definiciones de escenario de una tabla ``[[scenario]]`` (TOML o dict)."""
    raw = read_toml(source) if isinstance(source, (str, Path)) else source
    if not isinstance(raw, Mapping):
        raise ConfigError("Las definiciones de escenario deben ser un diccionario.")
    unknown = sorted(set(raw) - {SCENARIO_TABLE})
    if unknown:
        raise ConfigError(f"Claves desconocidas en el fichero de escenarios: {unknown}")
    entries = raw.get(SCENARIO_TABLE)
    if not isinstance(entries, list) or not entries:
        raise ConfigError("Se exige al menos un [[scenario]].")
    definitions = tuple(
        build_dataclass(ScenarioDefinition, entry, f"{SCENARIO_TABLE}[{index}]", empty_tuples=True)
        for index, entry in enumerate(entries)
    )
    validate_scenario_set(definitions)
    return definitions
