"""``ScenarioEngine``: transformaciones declarativas del modelo de riesgo (MASTER_SPEC §53).

Requisitos: SCN-001, SCN-002, SCN-003, SCN-009, TC-013.

Aplica una :class:`ScenarioDefinition` al modelo base y produce, **explícitamente**, ``μ_s``,
``Σ_s``, ``cost_s`` y ``constraints_s`` (:class:`ScenarioData`). Las transformaciones (todas datos
de la definición, nada hardcodeado; ARCHITECTURE §10.5) se aplican en este orden:

1. entradas ``CUSTOM`` (sustituyen a ``μ`` y/o ``Σ`` base sobre el mismo universo);
2. ``AssetShock`` en orden: ``μ' = μ·escala + desplazamiento`` y escala de volatilidad por grupo;
3. escala de volatilidad: ``Σ' = D Σ D`` con ``D = diag(escala_i)`` (preserva simetría y PSD);
4. estrés de correlación: ``R' = (1 − ρ) R + ρ R_objetivo``, ``Σ'' = S R' S`` con
   ``S = diag(σ')`` (las varianzas no cambian; activos de varianza nula conservan covarianza 0);
5. costes: multiplicadores de compra/venta por grupo;
6. overrides de restricciones: ``max_turnover``, límites de peso globales y de grupo.

``Σ_s`` pasa siempre por la validación del ``CovarianceBuilder`` (finitud, simetría, diagnóstico
espectral PSD y, solo si la configuración lo autoriza, reparación registrada). Nada se modifica
in situ: cada escenario es una copia. Un escenario ``BASE`` sin modificaciones es **el mismo
objeto** que el modelo base. Un selector que no coincide con ningún activo es un error (una
transformación que no actúa jamás se ignora en silencio).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from portfolio_engine.config.constraint_config import ConstraintConfig, GroupLimit
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.hashing import config_to_dict
from portfolio_engine.config.scenario_definitions import (
    AssetShock,
    ConstraintOverrides,
    CorrelationStress,
    CostShock,
    ScenarioDefinition,
    validate_scenario_set,
)
from portfolio_engine.exceptions import ConfigError, ScenarioError
from portfolio_engine.models.asset import AssetMetadata, Universe
from portfolio_engine.models.costs import AssetCostVector
from portfolio_engine.models.enums import CorrelationTarget, ScenarioType, ShockSelector
from portfolio_engine.models.portfolio import PortfolioSpec
from portfolio_engine.models.risk_model import ExpectedReturns, PSDRepairReport, RiskModel
from portfolio_engine.risk.risk_model_builder import CovarianceBuilder
from portfolio_engine.scenarios.data import ScenarioConstraints, ScenarioData, ScenarioSet
from portfolio_engine.utils.hashing import canonical_json, sha256_hex


def scenario_hash(definition: ScenarioDefinition) -> str:
    """``ScenarioHash`` determinista de la definición (clave de caché de B5)."""
    return sha256_hex(canonical_json(config_to_dict(definition)))


def _attribute(asset: AssetMetadata, selector: ShockSelector) -> str | None:
    if selector is ShockSelector.SECTOR:
        return asset.sector
    if selector is ShockSelector.COUNTRY:
        return asset.country
    if selector is ShockSelector.ASSET_CLASS:
        return asset.asset_class
    if selector is ShockSelector.CURRENCY:
        return asset.currency
    return asset.asset_id


class ScenarioEngine:
    """Construye los datos de cada escenario a partir del modelo base y las definiciones."""

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._covariance = CovarianceBuilder(config.risk, config.returns.trading_days_per_year)

    def build(
        self,
        base: RiskModel,
        universe: Universe,
        costs: AssetCostVector | None,
        constraints: ConstraintConfig,
        spec: PortfolioSpec | None,
        definitions: Sequence[ScenarioDefinition],
    ) -> ScenarioSet:
        """Escenarios de ``definitions`` sobre ``base`` (un :class:`ScenarioData` por definición).

        Lanza :class:`ConfigError` por definiciones duplicadas y :class:`ScenarioError` por una
        transformación imposible (selector vacío, universo distinto, costes ausentes…).
        """
        ordered = tuple(definitions)
        try:
            validate_scenario_set(ordered)
        except ConfigError as error:
            raise ScenarioError(str(error)) from error
        built = tuple(
            self._build_one(base, universe, costs, constraints, spec, definition)
            for definition in ordered
        )
        return ScenarioSet(built, base.mu_sigma_version)

    # ------------------------------------------------------------------------------------ uno

    def _build_one(
        self,
        base: RiskModel,
        universe: Universe,
        costs: AssetCostVector | None,
        constraints: ConstraintConfig,
        spec: PortfolioSpec | None,
        definition: ScenarioDefinition,
    ) -> ScenarioData:
        notes: list[str] = []
        risk_model, repair = self._risk_model(base, universe, definition, notes)
        scenario_costs = self._costs(costs, universe, base.asset_ids, definition, notes)
        scenario_constraints = self._constraints(constraints, spec, definition.constraint_overrides)
        if scenario_constraints.overrides_applied:
            notes.append("constraints:" + ",".join(scenario_constraints.overrides_applied))
        return ScenarioData(
            scenario_id=definition.scenario_id,
            scenario_type=definition.scenario_type,
            probability=definition.probability,
            risk_model=risk_model,
            costs=scenario_costs,
            constraints=scenario_constraints,
            stress_limits=definition.stress_limits,
            scenario_hash=scenario_hash(definition),
            is_identity=definition.is_identity,
            transformations=tuple(notes),
            covariance_repair=repair,
            definition=definition,
        )

    # ---------------------------------------------------------------------------- mu y Sigma

    def _risk_model(
        self, base: RiskModel, universe: Universe, definition: ScenarioDefinition, notes: list[str]
    ) -> tuple[RiskModel, PSDRepairReport | None]:
        ids = base.asset_ids
        mu, sigma = self._custom_inputs(base, definition, notes)
        vol = np.ones(len(ids), dtype=np.float64)
        for index, shock in enumerate(definition.asset_shocks):
            mask = self._mask(universe, ids, shock.selector, shock.values, definition, index)
            self._apply_shock(shock, mask, mu, vol)
            notes.append(f"asset_shock[{index}]:{shock.selector.value}")
        if not np.all(vol == 1.0):
            sigma = vol[:, None] * sigma * vol[None, :]
        if definition.correlation_stress is not None:
            sigma = self._stress_correlation(sigma, ids, definition, definition.correlation_stress)
            notes.append("correlation_stress")
        return self._assemble(base, mu, sigma)

    @staticmethod
    def _custom_inputs(
        base: RiskModel, definition: ScenarioDefinition, notes: list[str]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """``μ`` y ``Σ`` de partida: los del modelo base o las entradas ``CUSTOM`` (copias)."""
        mu = np.array(base.mu, dtype=np.float64)
        sigma = np.array(base.sigma, dtype=np.float64)
        custom = definition.custom
        if custom is None:
            return mu, sigma
        if custom.asset_ids != base.asset_ids:
            raise ScenarioError(
                f"{definition.scenario_id}: las entradas CUSTOM deben cubrir exactamente el "
                "universo del modelo base (mismos AssetID, mismo orden)."
            )
        if custom.mu is not None:
            mu = np.array(custom.mu, dtype=np.float64)
            notes.append("custom_mu")
        if custom.covariance is not None:
            sigma = np.array(custom.covariance, dtype=np.float64)
            notes.append("custom_covariance")
        return mu, sigma

    def _assemble(
        self,
        base: RiskModel,
        mu: npt.NDArray[np.float64],
        sigma: npt.NDArray[np.float64],
    ) -> tuple[RiskModel, PSDRepairReport | None]:
        """Modelo de riesgo del escenario; el mismo objeto base si nada cambió (``BASE``)."""
        mu_changed = not np.array_equal(mu, base.mu)
        sigma_changed = not np.array_equal(sigma, base.sigma)
        if not (mu_changed or sigma_changed):
            return base, None
        covariance = base.covariance
        if sigma_changed:
            covariance = self._covariance.validate(
                sigma,
                base.asset_ids,
                base.covariance.method,
                base.covariance.shrinkage,
                base.covariance.n_observations,
            )
        expected = base.expected_returns
        if mu_changed:
            expected = ExpectedReturns(base.asset_ids, mu, expected.mode, expected.method)
        repair = covariance.repair if sigma_changed else None
        return RiskModel(expected, covariance), repair

    @staticmethod
    def _apply_shock(
        shock: AssetShock,
        mask: npt.NDArray[np.bool_],
        mu: npt.NDArray[np.float64],
        vol: npt.NDArray[np.float64],
    ) -> None:
        if shock.mu_scale is not None:
            mu[mask] *= shock.mu_scale
        if shock.mu_shift is not None:
            mu[mask] += shock.mu_shift
        if shock.vol_scale is not None:
            vol[mask] *= shock.vol_scale

    @staticmethod
    def _mask(
        universe: Universe,
        ids: tuple[str, ...],
        selector: ShockSelector,
        values: tuple[str, ...],
        definition: ScenarioDefinition,
        index: int,
    ) -> npt.NDArray[np.bool_]:
        if selector is ShockSelector.ALL:
            return np.ones(len(ids), dtype=bool)
        wanted = set(values)
        if selector is ShockSelector.ASSET:
            unknown = sorted(wanted - set(ids))
            if unknown:
                raise ScenarioError(
                    f"{definition.scenario_id}[{index}]: AssetID desconocidos {unknown}."
                )
        mask = np.array(
            [_attribute(universe.get(asset_id), selector) in wanted for asset_id in ids],
            dtype=bool,
        )
        if not mask.any():
            raise ScenarioError(
                f"{definition.scenario_id}[{index}]: el selector {selector.value} {sorted(wanted)} "
                "no coincide con ningún activo; una transformación que no actúa no se ignora."
            )
        return mask

    def _stress_correlation(
        self,
        sigma: npt.NDArray[np.float64],
        ids: tuple[str, ...],
        definition: ScenarioDefinition,
        stress: CorrelationStress,
    ) -> npt.NDArray[np.float64]:
        std = np.sqrt(np.maximum(np.diag(sigma), 0.0))
        active = np.flatnonzero(std > 0.0)
        if active.shape[0] < 2:
            raise ScenarioError(
                f"{definition.scenario_id}: el estrés de correlación necesita al menos dos activos "
                "con varianza positiva."
            )
        scale = np.outer(std[active], std[active])
        correlation = sigma[np.ix_(active, active)] / scale
        np.fill_diagonal(correlation, 1.0)
        target = self._target_correlation(stress, ids, active, definition)
        mixed = (1.0 - stress.intensity) * correlation + stress.intensity * target
        stressed = np.zeros_like(sigma)
        stressed[np.ix_(active, active)] = mixed * scale
        return np.asarray((stressed + stressed.T) / 2.0, dtype=np.float64)

    def _target_correlation(
        self,
        stress: CorrelationStress,
        ids: tuple[str, ...],
        active: npt.NDArray[np.int64],
        definition: ScenarioDefinition,
    ) -> npt.NDArray[np.float64]:
        size = active.shape[0]
        if stress.target is CorrelationTarget.CONSTANT:
            constant = float(stress.constant or 0.0)
            matrix = np.full((size, size), constant, dtype=np.float64)
            np.fill_diagonal(matrix, 1.0)
            return matrix
        if stress.target_asset_ids is None or stress.target_matrix is None:
            raise ScenarioError(
                f"{definition.scenario_id}: falta la matriz de correlación objetivo."
            )
        if stress.target_asset_ids != ids:
            raise ScenarioError(
                f"{definition.scenario_id}: la correlación objetivo debe cubrir exactamente el "
                "universo del modelo (mismos AssetID, mismo orden)."
            )
        full = np.array(stress.target_matrix, dtype=np.float64)
        tolerance = self._config.scenarios.correlation_tolerance
        if not np.all(np.isfinite(full)) or float(np.max(np.abs(full - full.T))) > tolerance:
            raise ScenarioError(f"{definition.scenario_id}: correlación objetivo no simétrica.")
        if float(np.max(np.abs(np.diag(full) - 1.0))) > tolerance:
            raise ScenarioError(f"{definition.scenario_id}: la diagonal objetivo debe ser 1.")
        if float(np.linalg.eigvalsh((full + full.T) / 2.0)[0]) < -tolerance:
            raise ScenarioError(f"{definition.scenario_id}: correlación objetivo no PSD.")
        return np.asarray(full[np.ix_(active, active)], dtype=np.float64)

    # ------------------------------------------------------------------------------ costes

    @staticmethod
    def _costs(
        costs: AssetCostVector | None,
        universe: Universe,
        ids: tuple[str, ...],
        definition: ScenarioDefinition,
        notes: list[str],
    ) -> AssetCostVector | None:
        if not definition.cost_shocks:
            return costs
        if costs is None:
            raise ScenarioError(
                f"{definition.scenario_id}: hay multiplicadores de coste pero no costes de partida."
            )
        buy = np.array(costs.buy_costs, dtype=np.float64)
        sell = np.array(costs.sell_costs, dtype=np.float64)
        for index, shock in enumerate(definition.cost_shocks):
            mask = ScenarioEngine._cost_mask(universe, costs.asset_ids, shock, definition, index)
            buy[mask] *= shock.multiplier
            sell[mask] *= shock.multiplier
            notes.append(f"cost_shock[{index}]:{shock.selector.value}")
        del ids
        return AssetCostVector(costs.asset_ids, buy, sell, costs.sources)

    @staticmethod
    def _cost_mask(
        universe: Universe,
        asset_ids: tuple[str, ...],
        shock: CostShock,
        definition: ScenarioDefinition,
        index: int,
    ) -> npt.NDArray[np.bool_]:
        return ScenarioEngine._mask(
            universe, asset_ids, shock.selector, shock.values, definition, index
        )

    # ------------------------------------------------------------------------- restricciones

    @staticmethod
    def _constraints(
        constraints: ConstraintConfig,
        spec: PortfolioSpec | None,
        overrides: ConstraintOverrides | None,
    ) -> ScenarioConstraints:
        if overrides is None:
            return ScenarioConstraints(constraints, spec, ())
        changes: dict[str, object] = {}
        if overrides.global_min_weight is not None:
            changes["global_min_weight"] = overrides.global_min_weight
        if overrides.global_max_weight is not None:
            changes["global_max_weight"] = overrides.global_max_weight
        if overrides.max_turnover is not None:
            changes["global_max_turnover"] = overrides.max_turnover
        if overrides.group_limits:
            changes["group_limits"] = _merge_group_limits(
                constraints.group_limits, overrides.group_limits
            )
        scenario_spec = spec
        if (
            spec is not None
            and overrides.max_turnover is not None
            and spec.max_turnover is not None
        ):
            scenario_spec = dataclasses.replace(spec, max_turnover=overrides.max_turnover)
        try:
            new_config = dataclasses.replace(constraints, **changes)  # type: ignore[arg-type]
        except ConfigError as error:
            raise ScenarioError(f"overrides de restricciones inválidos: {error}") from error
        return ScenarioConstraints(new_config, scenario_spec, overrides.keys)


def _merge_group_limits(
    current: tuple[GroupLimit, ...], overrides: tuple[GroupLimit, ...]
) -> tuple[GroupLimit, ...]:
    """Límites de grupo; los del escenario sustituyen a los de igual ``(dimensión, grupo)``."""
    replaced = {(limit.dimension, limit.group) for limit in overrides}
    kept = tuple(limit for limit in current if (limit.dimension, limit.group) not in replaced)
    return (*kept, *overrides)


def is_base(definition: ScenarioDefinition) -> bool:
    """``True`` si la definición es un ``BASE`` sin modificaciones expresas."""
    return definition.scenario_type is ScenarioType.BASE and definition.is_identity
