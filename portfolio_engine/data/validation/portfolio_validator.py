"""Validación de carteras actuales y especificaciones por cartera (MASTER_SPEC §7, §10, §12).

Incluye la política obligatoria para activos restringidos ya en cartera (enmienda E-09) y el
tratamiento explícito de residuos de peso (decisión A-34). Ningún peso se renormaliza en
silencio.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pandas as pd

from portfolio_engine.config.constraint_config import ConstraintConfig
from portfolio_engine.config.data_config import DataConfig
from portfolio_engine.data.validation.report import DataQualityReport, IssueCode, IssueCollector
from portfolio_engine.exceptions import AssetResolutionError, DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.enums import ResidualWeightPolicy, RestrictedExistingPositionPolicy
from portfolio_engine.models.portfolio import (
    CurrentPortfolioState,
    PortfolioSpec,
    WeightBounds,
    resolve_restricted_policy,
)
from portfolio_engine.models.universe_index import AssetIndex

PORTFOLIO_ID = "PortfolioID"
CURRENT_WEIGHT = "CurrentWeight"
INVESTMENT_UNIVERSE_SEPARATOR = ";"


@dataclass(frozen=True, slots=True)
class PortfolioSetResult:
    """Estados actuales y especificaciones validadas, indexados por ``PortfolioID``."""

    states: Mapping[str, CurrentPortfolioState]
    specs: Mapping[str, PortfolioSpec]
    report: DataQualityReport


class PortfolioValidator:
    """Valida carteras actuales, especificaciones y overrides de límites de peso."""

    def __init__(self, constraints: ConstraintConfig, data: DataConfig) -> None:
        self._constraints = constraints
        self._data = data

    def validate(
        self,
        holdings: pd.DataFrame,
        universe: Universe,
        specs: pd.DataFrame | None = None,
        weight_overrides: pd.DataFrame | None = None,
    ) -> PortfolioSetResult:
        """Valida las tablas canónicas y construye los estados actuales.

        Lanza ``DataValidationError`` (con todos los problemas) si existe algún error.
        """
        collector = IssueCollector()
        identifier = _identifier_column(holdings, collector)
        parsed_specs = _SpecParser(universe, self._constraints, collector).parse(
            specs, weight_overrides
        )
        weights = self._collect_weights(holdings, identifier, universe, collector)
        index = AssetIndex.from_universe(universe)
        states: dict[str, CurrentPortfolioState] = {}
        for portfolio_id in sorted(set(weights) | set(parsed_specs)):
            spec = parsed_specs.get(portfolio_id)
            held = self._apply_residual_policy(
                portfolio_id, weights.get(portfolio_id, {}), universe, collector
            )
            self._check_restricted(portfolio_id, held, spec, universe, collector)
            _check_investment_universe(portfolio_id, held, spec, collector)
            states[portfolio_id] = CurrentPortfolioState.from_weights(
                portfolio_id, held, index, spec.nav if spec else None
            )
        report = collector.report()
        report.raise_if_errors("Carteras actuales")
        return PortfolioSetResult(
            MappingProxyType(states), MappingProxyType(dict(parsed_specs)), report
        )

    def _collect_weights(
        self,
        holdings: pd.DataFrame,
        identifier: str,
        universe: Universe,
        collector: IssueCollector,
    ) -> dict[str, dict[str, float]]:
        weights: dict[str, dict[str, float]] = {}
        for row in holdings.to_dict("records"):
            portfolio_id = row.get(PORTFOLIO_ID)
            if not isinstance(portfolio_id, str):
                collector.error(IssueCode.MISSING_METADATA, "Fila sin PortfolioID.")
                continue
            asset_id = _resolve(row.get(identifier), universe, portfolio_id, collector)
            weight = self._checked_weight(
                row.get(CURRENT_WEIGHT), portfolio_id, asset_id, collector
            )
            if asset_id is None or weight is None:
                continue
            portfolio = weights.setdefault(portfolio_id, {})
            if asset_id in portfolio:
                collector.error(
                    IssueCode.DUPLICATE,
                    "Activo repetido en la cartera.",
                    asset_id=asset_id,
                    portfolio_id=portfolio_id,
                )
                continue
            portfolio[asset_id] = weight
        return weights

    def _checked_weight(
        self, value: object, portfolio_id: str, asset_id: str | None, collector: IssueCollector
    ) -> float | None:
        keys = {"asset_id": asset_id, "portfolio_id": portfolio_id}
        if value is None or (isinstance(value, float) and math.isnan(value)):
            collector.error(IssueCode.MISSING_WEIGHT, "CurrentWeight ausente.", **keys)
            return None
        weight = float(value)  # type: ignore[arg-type]
        if not math.isfinite(weight):
            collector.error(IssueCode.NON_FINITE_VALUE, "CurrentWeight no finito.", **keys)
            return None
        if self._constraints.long_only and weight < 0:
            collector.error(IssueCode.NEGATIVE_WEIGHT, "Peso negativo con long_only.", **keys)
            return None
        if weight == 0.0:
            collector.warning(
                IssueCode.ZERO_WEIGHT_IGNORED,
                "Peso cero: el activo no se considera mantenido.",
                **keys,
            )
            return None
        return weight

    def _apply_residual_policy(
        self,
        portfolio_id: str,
        weights: dict[str, float],
        universe: Universe,
        collector: IssueCollector,
    ) -> dict[str, float]:
        if not weights:
            return {}
        total = math.fsum(weights.values())
        residual = 1.0 - total
        if abs(residual) <= self._data.weight_sum_tolerance:
            return dict(weights)
        policy = self._data.residual_weight_policy
        cash = self._data.cash_asset_id
        assign = policy is ResidualWeightPolicy.ASSIGN_TO_CASH and residual > 0
        if assign and cash is not None and cash in universe:
            adjusted = dict(weights)
            adjusted[cash] = adjusted.get(cash, 0.0) + residual
            collector.correct(
                action="ASSIGN_RESIDUAL_TO_CASH",
                target=portfolio_id,
                reason=f"Σw = {total!r}; residuo {residual!r} asignado a {cash}",
                policy=f"residual_weight_policy={policy}",
            )
            return adjusted
        collector.error(
            IssueCode.INCONSISTENT_WEIGHTS,
            f"Σw = {total!r} fuera de tolerancia {self._data.weight_sum_tolerance!r} "
            f"(política {policy}; caja {cash!r}).",
            portfolio_id=portfolio_id,
        )
        return dict(weights)

    def _check_restricted(
        self,
        portfolio_id: str,
        held: Mapping[str, float],
        spec: PortfolioSpec | None,
        universe: Universe,
        collector: IssueCollector,
    ) -> None:
        policy = effective_restricted_policy(spec, self._constraints)
        for asset_id in held:
            restricted = universe.get(asset_id).restricted
            if restricted is None:
                collector.error(
                    IssueCode.RESTRICTED_STATUS_UNKNOWN,
                    "Activo mantenido sin RestrictedAssetFlag.",
                    asset_id=asset_id,
                    portfolio_id=portfolio_id,
                )
            elif restricted and policy is None:
                collector.error(
                    IssueCode.RESTRICTED_POLICY_REQUIRED,
                    "Activo restringido en cartera: RestrictedExistingPositionPolicy debe "
                    "seleccionarse explícitamente (E-09).",
                    asset_id=asset_id,
                    portfolio_id=portfolio_id,
                )


def effective_restricted_policy(
    spec: PortfolioSpec | None, constraints: ConstraintConfig
) -> RestrictedExistingPositionPolicy | None:
    """Política efectiva: override de la cartera si existe; si no, la global (o ``None``)."""
    return resolve_restricted_policy(spec, constraints.restricted_existing_position_policy)


def _identifier_column(frame: pd.DataFrame, collector: IssueCollector) -> str:
    identifier = "AssetID" if "AssetID" in frame.columns else "Ticker"
    missing = [c for c in (PORTFOLIO_ID, CURRENT_WEIGHT, identifier) if c not in frame.columns]
    if missing:
        collector.error(IssueCode.SCHEMA, f"Columnas obligatorias ausentes: {missing}")
        collector.report().raise_if_errors("Carteras actuales")
    return identifier


def _resolve(
    value: object, universe: Universe, portfolio_id: str | None, collector: IssueCollector
) -> str | None:
    if not isinstance(value, str):
        collector.error(
            IssueCode.MISSING_METADATA, "Identificador ausente.", portfolio_id=portfolio_id
        )
        return None
    try:
        return universe.resolve(value)
    except AssetResolutionError as error:
        collector.error(
            IssueCode.UNKNOWN_ASSET, str(error), asset_id=value, portfolio_id=portfolio_id
        )
        return None


def _check_investment_universe(
    portfolio_id: str,
    held: Mapping[str, float],
    spec: PortfolioSpec | None,
    collector: IssueCollector,
) -> None:
    if spec is None or spec.investment_universe is None:
        return
    allowed = set(spec.investment_universe)
    for asset_id in sorted(set(held) - allowed):
        collector.warning(
            IssueCode.HELD_OUTSIDE_INVESTMENT_UNIVERSE,
            "Activo mantenido fuera del InvestmentUniverse de la cartera.",
            asset_id=asset_id,
            portfolio_id=portfolio_id,
        )


class _SpecParser:
    """Convierte las tablas de especificación y overrides en :class:`PortfolioSpec`."""

    def __init__(
        self, universe: Universe, constraints: ConstraintConfig, collector: IssueCollector
    ) -> None:
        self._universe = universe
        self._constraints = constraints
        self._collector = collector

    def parse(
        self, specs: pd.DataFrame | None, overrides: pd.DataFrame | None
    ) -> dict[str, PortfolioSpec]:
        overrides_by_portfolio = self._parse_overrides(overrides)
        parsed: dict[str, PortfolioSpec] = {}
        rows = [] if specs is None else specs.to_dict("records")
        for row in rows:
            portfolio_id = row.get(PORTFOLIO_ID)
            if not isinstance(portfolio_id, str):
                self._invalid(None, "Especificación sin PortfolioID.")
            elif portfolio_id in parsed:
                self._invalid(portfolio_id, "Especificación duplicada.")
            elif (spec := self._build(portfolio_id, row, overrides_by_portfolio)) is not None:
                parsed[portfolio_id] = spec
        for portfolio_id in sorted(set(overrides_by_portfolio) - set(parsed)):
            self._invalid(portfolio_id, "Overrides de límites sin especificación de cartera.")
        return parsed

    def _build(
        self,
        portfolio_id: str,
        row: dict[str, Any],
        overrides: Mapping[str, dict[str, WeightBounds]],
    ) -> PortfolioSpec | None:
        try:
            return PortfolioSpec(
                portfolio_id=portfolio_id,
                target_portfolio_size=_optional_int(row.get("TargetPortfolioSize")),
                volatility_limit=_optional_float(row.get("VolatilityLimit")),
                max_turnover=_optional_float(row.get("MaxTurnover")),
                investment_universe=self._investment_universe(row.get("InvestmentUniverse")),
                restricted_existing_position_policy=_optional_policy(
                    row.get("RestrictedExistingPositionPolicy")
                ),
                nav=_optional_float(row.get("NAV")),
                weight_bound_overrides=overrides.get(portfolio_id, {}),
                nav_currency=_optional_text(row.get("NAVCurrency")),
            )
        except DataValidationError as error:
            self._invalid(portfolio_id, str(error))
            return None

    def _investment_universe(self, value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        tokens = [token.strip() for token in str(value).split(INVESTMENT_UNIVERSE_SEPARATOR)]
        return tuple(sorted({self._universe.resolve(token) for token in tokens if token}))

    def _parse_overrides(self, frame: pd.DataFrame | None) -> dict[str, dict[str, WeightBounds]]:
        result: dict[str, dict[str, WeightBounds]] = {}
        if frame is None:
            return result
        identifier = "AssetID" if "AssetID" in frame.columns else "Ticker"
        for row in frame.to_dict("records"):
            portfolio_id = row.get(PORTFOLIO_ID)
            asset_id = _resolve(row.get(identifier), self._universe, portfolio_id, self._collector)
            if not isinstance(portfolio_id, str) or asset_id is None:
                continue
            try:
                bounds = WeightBounds(
                    _optional_float(row.get("MinWeight")), _optional_float(row.get("MaxWeight"))
                )
            except DataValidationError as error:
                self._invalid(portfolio_id, f"{asset_id}: {error}")
                continue
            if self._constraints.long_only and any(
                value is not None and value < 0 for value in (bounds.min_weight, bounds.max_weight)
            ):
                self._invalid(portfolio_id, f"{asset_id}: límite negativo con long_only.")
                continue
            if asset_id in result.setdefault(portfolio_id, {}):
                self._invalid(portfolio_id, f"{asset_id}: override duplicado.")
                continue
            result[portfolio_id][asset_id] = bounds
        return result

    def _invalid(self, portfolio_id: str | None, message: str) -> None:
        self._collector.error(IssueCode.INVALID_PORTFOLIO_SPEC, message, portfolio_id=portfolio_id)


def _optional_float(value: object) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)  # type: ignore[arg-type]


def _optional_text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    number = _optional_float(value)
    if number is None:
        return None
    if not number.is_integer():
        raise DataValidationError(f"Se esperaba un entero y se recibió {number!r}.")
    return int(number)


def _optional_policy(value: object) -> RestrictedExistingPositionPolicy | None:
    if value is None:
        return None
    try:
        return RestrictedExistingPositionPolicy[str(value)]
    except KeyError as error:
        options = [policy.name for policy in RestrictedExistingPositionPolicy]
        raise DataValidationError(
            f"RestrictedExistingPositionPolicy {value!r} no válida; opciones {options}."
        ) from error
