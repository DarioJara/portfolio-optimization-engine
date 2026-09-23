"""Histórico de precios y matriz de retornos (MASTER_SPEC §5.1, §9)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.enums import ReturnKind
from portfolio_engine.utils.numerics import readonly_float_array

DATE = "Date"
ASSET_ID = "AssetID"
TICKER = "Ticker"
ADJUSTED_CLOSE = "AdjustedClose"
OPTIONAL_PRICE_FIELDS = ("Volume", "Bid", "Ask", "FXRate", "MarketCap")
REQUIRED_PRICE_FIELDS = (DATE, ASSET_ID, ADJUSTED_CLOSE)


class PriceHistory:
    """Histórico de precios validado en formato largo (una fila por ``Date`` × ``AssetID``).

    Solo debe construirse a partir de datos ya validados (``MarketDataValidator``): exige
    columnas obligatorias, ausencia de duplicados y ausencia de nulos en las columnas
    obligatorias. El DataFrame interno nunca se expone mutable (se devuelven copias).
    """

    __slots__ = ("_frame",)

    def __init__(self, frame: pd.DataFrame) -> None:
        missing = [column for column in REQUIRED_PRICE_FIELDS if column not in frame.columns]
        if missing:
            raise DataValidationError(f"Columnas obligatorias ausentes en precios: {missing}")
        columns = list(REQUIRED_PRICE_FIELDS) + [
            column for column in OPTIONAL_PRICE_FIELDS if column in frame.columns
        ]
        canonical = frame.loc[:, columns].copy()
        canonical[DATE] = pd.to_datetime(canonical[DATE])
        canonical[ASSET_ID] = canonical[ASSET_ID].astype(str)
        canonical[ADJUSTED_CLOSE] = canonical[ADJUSTED_CLOSE].astype(np.float64)
        if canonical[list(REQUIRED_PRICE_FIELDS)].isna().to_numpy().any():
            raise DataValidationError("PriceHistory no admite nulos en columnas obligatorias.")
        if canonical.duplicated(subset=[DATE, ASSET_ID]).any():
            raise DataValidationError("PriceHistory no admite duplicados (Date, AssetID).")
        canonical = canonical.sort_values([ASSET_ID, DATE], kind="mergesort")
        self._frame = canonical.reset_index(drop=True)

    def frame(self) -> pd.DataFrame:
        """Copia del histórico en formato largo, ordenado por ``AssetID`` y ``Date``."""
        return self._frame.copy()

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """AssetID presentes, ordenados."""
        return tuple(sorted(self._frame[ASSET_ID].unique().tolist()))

    def exclude_assets(self, asset_ids: Iterable[str]) -> PriceHistory:
        """Nuevo histórico sin los activos indicados."""
        excluded = set(asset_ids)
        return PriceHistory(self._frame.loc[~self._frame[ASSET_ID].isin(excluded)])

    def wide_prices(
        self,
    ) -> tuple[npt.NDArray[np.datetime64], tuple[str, ...], npt.NDArray[np.float64]]:
        """Precios en formato ancho: (fechas ascendentes, AssetID ordenados, matriz T×N).

        Las celdas sin observación son ``NaN``; el llamador decide cómo tratarlas.
        """
        wide = self._frame.pivot(index=DATE, columns=ASSET_ID, values=ADJUSTED_CLOSE)
        wide = wide.sort_index().sort_index(axis=1)
        dates = wide.index.to_numpy(dtype="datetime64[ns]")
        return dates, tuple(str(column) for column in wide.columns), wide.to_numpy(np.float64)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PriceHistory) and self._frame.equals(other._frame)

    def __hash__(self) -> int:
        raise TypeError("PriceHistory no es hashable.")


@dataclass(frozen=True, eq=False, slots=True)
class ReturnsMatrix:
    """Matriz de retornos T×N sin valores ausentes, con fechas de fin de periodo.

    ``justification`` es obligatorio cuando ``kind`` es ``LOG`` (MASTER_SPEC §9).
    """

    dates: npt.NDArray[np.datetime64]
    asset_ids: tuple[str, ...]
    values: npt.NDArray[np.float64]
    kind: ReturnKind
    justification: str | None

    def __post_init__(self) -> None:
        values = readonly_float_array(self.values)
        dates = np.array(self.dates, dtype="datetime64[ns]", copy=True)
        dates.setflags(write=False)
        if values.ndim != 2 or values.shape != (dates.shape[0], len(self.asset_ids)):
            raise DataValidationError("Dimensiones incoherentes en ReturnsMatrix.")
        if not np.all(np.isfinite(values)):
            raise DataValidationError("ReturnsMatrix no admite NaN ni infinitos.")
        if list(self.asset_ids) != sorted(set(self.asset_ids)):
            raise DataValidationError("ReturnsMatrix exige AssetID únicos y ordenados.")
        if self.kind is ReturnKind.LOG and not self.justification:
            raise DataValidationError("Los log returns exigen una justificación explícita.")
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "dates", dates)

    @property
    def n_observations(self) -> int:
        """Número de observaciones (filas)."""
        return int(self.values.shape[0])

    def columns_for(self, asset_ids: Iterable[str]) -> npt.NDArray[np.float64]:
        """Submatriz con las columnas de ``asset_ids`` en el orden dado."""
        positions = {asset_id: column for column, asset_id in enumerate(self.asset_ids)}
        wanted = list(asset_ids)
        missing = [asset_id for asset_id in wanted if asset_id not in positions]
        if missing:
            raise DataValidationError(f"Activos sin serie de retornos: {missing}")
        return self.values[:, [positions[asset_id] for asset_id in wanted]]
