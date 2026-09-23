"""Fuentes de datos intercambiables (DataFrame, CSV, Parquet). SQL Server: Bloque 6."""

from portfolio_engine.data.sources.base import SCHEMAS, DataSource, Table, canonicalize
from portfolio_engine.data.sources.dataframe_source import DataFrameSource
from portfolio_engine.data.sources.file_sources import CSVSource, ParquetSource, TablePaths

__all__ = (
    "SCHEMAS",
    "CSVSource",
    "DataFrameSource",
    "DataSource",
    "ParquetSource",
    "Table",
    "TablePaths",
    "canonicalize",
)
