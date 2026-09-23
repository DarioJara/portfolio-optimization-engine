"""Fuentes de datos basadas en ficheros CSV y Parquet (MASTER_SPEC §5.1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from portfolio_engine.data.sources.base import Table, canonicalize
from portfolio_engine.exceptions import DataValidationError


@dataclass(frozen=True, slots=True)
class TablePaths:
    """Rutas de los ficheros de cada tabla. Las tablas opcionales pueden ser ``None``."""

    prices: Path
    universe: Path
    holdings: Path
    portfolio_specs: Path | None = None
    weight_overrides: Path | None = None
    external_alpha: Path | None = None

    def path_for(self, table: Table) -> Path | None:
        """Ruta asociada a ``table``."""
        return {
            Table.PRICES: self.prices,
            Table.UNIVERSE: self.universe,
            Table.HOLDINGS: self.holdings,
            Table.PORTFOLIO_SPECS: self.portfolio_specs,
            Table.WEIGHT_OVERRIDES: self.weight_overrides,
            Table.EXTERNAL_ALPHA: self.external_alpha,
        }[table]


class _FileSource(ABC):
    """Base común: lectura cruda por fichero + canonicalización compartida."""

    def __init__(self, paths: TablePaths) -> None:
        self._paths = paths

    @abstractmethod
    def _read(self, path: Path) -> pd.DataFrame:
        """Lee el fichero crudo (formato específico de cada fuente)."""

    def _get(self, table: Table) -> pd.DataFrame | None:
        path = self._paths.path_for(table)
        if path is None:
            return None
        try:
            raw = self._read(path)
        except OSError as error:
            raise DataValidationError(f"No se puede leer {table} desde {path}: {error}") from error
        return canonicalize(raw, table)

    def _require(self, table: Table) -> pd.DataFrame:
        frame = self._get(table)
        if frame is None:
            raise DataValidationError(f"Tabla obligatoria sin ruta: {table}")
        return frame

    def load_prices(self) -> pd.DataFrame:
        """Histórico de mercado canónico."""
        return self._require(Table.PRICES)

    def load_universe(self) -> pd.DataFrame:
        """Universo canónico."""
        return self._require(Table.UNIVERSE)

    def load_current_portfolios(self) -> pd.DataFrame:
        """Carteras actuales canónicas."""
        return self._require(Table.HOLDINGS)

    def load_portfolio_specs(self) -> pd.DataFrame | None:
        """Configuración por cartera canónica o ``None``."""
        return self._get(Table.PORTFOLIO_SPECS)

    def load_weight_overrides(self) -> pd.DataFrame | None:
        """Overrides de límites de peso canónicos o ``None``."""
        return self._get(Table.WEIGHT_OVERRIDES)

    def load_external_alpha(self) -> pd.DataFrame | None:
        """Alpha externo canónico o ``None``."""
        return self._get(Table.EXTERNAL_ALPHA)


class CSVSource(_FileSource):
    """Fuente CSV. Todo se lee como texto y se tipa en la canonicalización (sin inferencias)."""

    def _read(self, path: Path) -> pd.DataFrame:
        return pd.read_csv(path, dtype=str, keep_default_na=True)


class ParquetSource(_FileSource):
    """Fuente Parquet (pyarrow)."""

    def _read(self, path: Path) -> pd.DataFrame:
        return pd.read_parquet(path)
