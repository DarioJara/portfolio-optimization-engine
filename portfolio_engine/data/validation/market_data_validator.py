"""Validación del histórico de mercado (MASTER_SPEC §5.1, §10).

Comprueba esquema, identificadores, fechas inválidas o futuras, duplicados, precios ausentes,
no finitos o no positivos, alineación de calendario, histórico insuficiente, precios stale,
outliers y huecos de calendario. Nunca modifica valores: un activo con errores se detiene
(``FAIL``) o se excluye completo (``EXCLUDE_ASSET``) dejando constancia en el
``CorrectionLog``. Nunca se eliminan observaciones sueltas de una serie.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from portfolio_engine.config.data_config import DataConfig
from portfolio_engine.data.validation.report import DataQualityReport, IssueCode, IssueCollector
from portfolio_engine.exceptions import AssetResolutionError, DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.models.enums import AssetErrorPolicy, IssueSeverity
from portfolio_engine.models.market_data import (
    ADJUSTED_CLOSE,
    ASSET_ID,
    DATE,
    OPTIONAL_PRICE_FIELDS,
    TICKER,
    PriceHistory,
)

#: Constante de consistencia del MAD con la desviación típica de una normal: 1/Φ⁻¹(3/4).
MAD_TO_STD_NORMAL = 1.482602218505602
_ONE_DAY = np.timedelta64(1, "D")
_MUST_BE_POSITIVE = frozenset({"Bid", "Ask", "FXRate"})


@dataclass(frozen=True, slots=True)
class MarketDataResult:
    """Histórico validado (activos excluidos ya retirados) y su informe."""

    prices: PriceHistory
    report: DataQualityReport


class MarketDataValidator:
    """Valida el histórico de precios canónico frente al universo y la configuración."""

    def __init__(self, config: DataConfig) -> None:
        self._config = config

    def validate(
        self,
        frame: pd.DataFrame,
        universe: Universe,
        as_of: np.datetime64 | None = None,
    ) -> MarketDataResult:
        """Valida ``frame`` y devuelve el histórico limpio.

        Con ``FAIL`` cualquier error lanza ``DataValidationError``. Con ``EXCLUDE_ASSET`` los
        activos con errores se excluyen completos: sus errores permanecen en el informe y la
        exclusión queda en ``report.corrections``.
        """
        collector = IssueCollector()
        _check_schema(frame, collector)
        data = _resolve_identifiers(frame, universe, collector)
        row_ok = self._check_rows(data, as_of, collector)
        clean = data.loc[row_ok & data[ASSET_ID].notna()]
        self._check_series(clean, collector)
        excluded = self._apply_policy(collector)
        remaining = clean.loc[~clean[ASSET_ID].isin(excluded)]
        if remaining.empty:
            collector.error(IssueCode.NO_VALID_ASSETS, "No queda ningún activo con datos válidos.")
            collector.report().raise_if_errors("Histórico de mercado")
        report = collector.report()
        columns = [DATE, ASSET_ID, ADJUSTED_CLOSE] + [
            column for column in OPTIONAL_PRICE_FIELDS if column in remaining.columns
        ]
        return MarketDataResult(PriceHistory(remaining.loc[:, columns]), report)

    def _check_rows(
        self, data: pd.DataFrame, as_of: np.datetime64 | None, collector: IssueCollector
    ) -> pd.Series:
        """Comprobaciones por fila; devuelve la máscara de filas sin errores."""
        prices = data[ADJUSTED_CLOSE].to_numpy(dtype=np.float64)
        dates = data[DATE]
        checks: list[tuple[IssueCode, pd.Series, str]] = [
            (IssueCode.INVALID_DATE, dates.isna(), "fecha inválida o ausente"),
            (IssueCode.MISSING_PRICE, pd.Series(np.isnan(prices), index=data.index), "precio NaN"),
            (
                IssueCode.NON_FINITE_VALUE,
                pd.Series(np.isinf(prices), index=data.index),
                "precio infinito",
            ),
            (
                IssueCode.NON_POSITIVE_PRICE,
                pd.Series(np.isfinite(prices) & (prices <= 0), index=data.index),
                "precio ≤ 0",
            ),
            (
                IssueCode.DUPLICATE,
                data.duplicated(subset=[DATE, ASSET_ID], keep=False) & dates.notna(),
                "observación duplicada (Date, AssetID)",
            ),
        ]
        if as_of is not None:
            checks.append((IssueCode.FUTURE_DATE, dates > as_of, f"fecha posterior a {as_of}"))
        row_ok = pd.Series(True, index=data.index)
        for code, mask, label in checks:
            row_ok &= ~mask
            _report_rows(data.loc[mask], code, label, collector)
        _check_optional_fields(data, collector)
        return row_ok

    def _check_series(self, clean: pd.DataFrame, collector: IssueCollector) -> None:
        """Comprobaciones por serie sobre filas válidas: calendario, histórico, stale, etc."""
        calendar = np.sort(clean[DATE].unique())
        for asset_id, group in clean.groupby(ASSET_ID, sort=True):
            series = group.sort_values(DATE)
            asset = str(asset_id)
            dates = series[DATE].to_numpy(dtype="datetime64[ns]")
            prices = series[ADJUSTED_CLOSE].to_numpy(dtype=np.float64)
            missing = calendar.size - np.unique(dates).size
            if missing > 0:
                collector.error(
                    IssueCode.MISSING_OBSERVATION,
                    f"Faltan {missing} observaciones respecto al calendario común.",
                    asset_id=asset,
                )
            self._check_history(asset, prices, collector)
            self._check_stale(asset, prices, collector)
            self._check_outliers(asset, prices, collector)
            self._check_gaps(asset, dates, collector)

    def _check_history(
        self, asset: str, prices: npt.NDArray[np.float64], collector: IssueCollector
    ) -> None:
        n_returns = max(prices.size - 1, 0)
        if n_returns < self._config.min_return_observations:
            collector.error(
                IssueCode.INSUFFICIENT_HISTORY,
                f"{n_returns} retornos < mínimo {self._config.min_return_observations}.",
                asset_id=asset,
            )

    def _check_stale(
        self, asset: str, prices: npt.NDArray[np.float64], collector: IssueCollector
    ) -> None:
        longest = longest_unchanged_run(prices)
        if longest > self._config.max_stale_run:
            collector.add(
                IssueCode.STALE_PRICE,
                self._config.stale_price_severity,
                f"{longest} retornos nulos consecutivos > máximo {self._config.max_stale_run}.",
                asset_id=asset,
            )

    def _check_outliers(
        self, asset: str, prices: npt.NDArray[np.float64], collector: IssueCollector
    ) -> None:
        if prices.size < 2:
            return
        scores = robust_zscores(prices[1:] / prices[:-1] - 1.0)
        count = int(np.sum(scores > self._config.outlier_threshold))
        if count:
            collector.add(
                IssueCode.OUTLIER,
                self._config.outlier_severity,
                f"{count} retornos con z-score robusto > {self._config.outlier_threshold} "
                f"(máximo {float(np.max(scores)):.3g}). No se corrigen.",
                asset_id=asset,
            )

    def _check_gaps(
        self, asset: str, dates: npt.NDArray[np.datetime64], collector: IssueCollector
    ) -> None:
        if dates.size < 2:
            return
        gaps = np.diff(dates) / _ONE_DAY
        largest = float(np.max(gaps))
        if largest > self._config.max_calendar_gap_days:
            collector.add(
                IssueCode.CALENDAR_GAP,
                self._config.calendar_gap_severity,
                f"Hueco de {largest:g} días > máximo {self._config.max_calendar_gap_days}.",
                asset_id=asset,
            )

    def _apply_policy(self, collector: IssueCollector) -> frozenset[str]:
        """Aplica ``asset_error_policy`` y devuelve los activos excluidos."""
        report = collector.report()
        global_errors = [issue for issue in report.errors if issue.asset_id is None]
        if global_errors:
            report.raise_if_errors("Histórico de mercado")
        failing = sorted({issue.asset_id for issue in report.errors if issue.asset_id})
        if not failing:
            return frozenset()
        if self._config.asset_error_policy is AssetErrorPolicy.FAIL:
            report.raise_if_errors("Histórico de mercado")
        for asset in failing:
            reasons = sorted({str(i.code) for i in report.errors if i.asset_id == asset})
            collector.correct(
                action="EXCLUDE_ASSET",
                target=asset,
                reason=", ".join(reasons),
                policy=f"asset_error_policy={self._config.asset_error_policy}",
            )
        return frozenset(failing)


def longest_unchanged_run(prices: npt.NDArray[np.float64]) -> int:
    """Mayor número de retornos nulos consecutivos (precios idénticos seguidos)."""
    if prices.size < 2:
        return 0
    unchanged = np.concatenate(([0], (prices[1:] == prices[:-1]).astype(np.int64), [0]))
    edges = np.diff(unchanged)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return int(np.max(ends - starts)) if starts.size else 0


def robust_zscores(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """``|x − mediana| / (MAD_TO_STD_NORMAL · MAD)``; ceros si el MAD es nulo (no definido)."""
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0.0:
        return np.zeros_like(values)
    return np.abs(values - median) / (MAD_TO_STD_NORMAL * mad)


def _check_schema(frame: pd.DataFrame, collector: IssueCollector) -> None:
    if frame.empty:
        raise DataValidationError("El histórico de mercado está vacío.")
    has_identifier = ASSET_ID in frame.columns or TICKER in frame.columns
    missing = [column for column in (DATE, ADJUSTED_CLOSE) if column not in frame.columns]
    if missing or not has_identifier:
        collector.error(
            IssueCode.SCHEMA,
            f"Faltan columnas obligatorias {missing} o un identificador (AssetID/Ticker).",
        )
        collector.report().raise_if_errors("Histórico de mercado")


def _resolve_identifiers(
    frame: pd.DataFrame, universe: Universe, collector: IssueCollector
) -> pd.DataFrame:
    """Sustituye el identificador de entrada por el AssetID canónico (``None`` si no resuelve)."""
    source = ASSET_ID if ASSET_ID in frame.columns else TICKER
    data = frame.copy()
    resolved: dict[str, str | None] = {}
    for identifier in data[source].dropna().unique():
        try:
            resolved[identifier] = universe.resolve(identifier)
        except AssetResolutionError as error:
            resolved[identifier] = None
            collector.error(IssueCode.UNKNOWN_ASSET, str(error), asset_id=str(identifier))
    if data[source].isna().any():
        collector.error(IssueCode.SCHEMA, f"{source} ausente en alguna fila.")
    data[ASSET_ID] = data[source].map(resolved).astype(object)
    return data


def _report_rows(
    rows: pd.DataFrame, code: IssueCode, label: str, collector: IssueCollector
) -> None:
    for asset_id, group in rows.groupby(ASSET_ID, sort=True, dropna=False):
        asset = None if pd.isna(asset_id) else str(asset_id)
        collector.error(code, f"{len(group)} fila(s) con {label}.", asset_id=asset)


def _check_optional_fields(data: pd.DataFrame, collector: IssueCollector) -> None:
    """Campos opcionales inválidos: avisos (no se usan en cálculos del Bloque 1)."""
    for column in OPTIONAL_PRICE_FIELDS:
        if column not in data.columns:
            continue
        values = data[column].to_numpy(dtype=np.float64)
        present = ~np.isnan(values)
        finite = np.where(present & np.isfinite(values), values, np.nan)
        out_of_range = finite <= 0 if column in _MUST_BE_POSITIVE else finite < 0
        bad = present & (~np.isfinite(values) | out_of_range)
        _warn_rows(data.loc[bad], column, collector)
    if "Bid" in data.columns and "Ask" in data.columns:
        crossed = data["Bid"] > data["Ask"]
        _warn_rows(data.loc[crossed], "Bid > Ask", collector)


def _warn_rows(rows: pd.DataFrame, label: str, collector: IssueCollector) -> None:
    for asset_id, group in rows.groupby(ASSET_ID, sort=True, dropna=False):
        asset = None if pd.isna(asset_id) else str(asset_id)
        collector.add(
            IssueCode.INVALID_OPTIONAL_FIELD,
            IssueSeverity.WARNING,
            f"{len(group)} fila(s) con {label} inválido.",
            asset_id=asset,
        )
