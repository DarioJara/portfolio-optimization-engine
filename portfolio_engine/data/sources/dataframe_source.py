"""Fuente de datos a partir de DataFrames en memoria (MASTER_SPEC §5.1)."""

from __future__ import annotations

import pandas as pd

from portfolio_engine.data.sources.base import Table, canonicalize
from portfolio_engine.exceptions import DataValidationError


class DataFrameSource:
    """Implementa ``DataSource`` sobre DataFrames ya cargados (se canonicalizan copias)."""

    def __init__(
        self,
        prices: pd.DataFrame,
        universe: pd.DataFrame,
        holdings: pd.DataFrame,
        portfolio_specs: pd.DataFrame | None = None,
        weight_overrides: pd.DataFrame | None = None,
        external_alpha: pd.DataFrame | None = None,
    ) -> None:
        self._tables: dict[Table, pd.DataFrame | None] = {
            Table.PRICES: prices,
            Table.UNIVERSE: universe,
            Table.HOLDINGS: holdings,
            Table.PORTFOLIO_SPECS: portfolio_specs,
            Table.WEIGHT_OVERRIDES: weight_overrides,
            Table.EXTERNAL_ALPHA: external_alpha,
        }

    def _get(self, table: Table) -> pd.DataFrame | None:
        frame = self._tables[table]
        return None if frame is None else canonicalize(frame, table)

    def _require(self, table: Table) -> pd.DataFrame:
        frame = self._get(table)
        if frame is None:
            raise DataValidationError(f"Tabla obligatoria ausente: {table}")
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
