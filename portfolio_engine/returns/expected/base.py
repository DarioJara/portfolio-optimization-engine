"""Contrato de proveedores de expected returns (MASTER_SPEC §8).

Un proveedor declara su ``mode`` (``INTERNAL_ESTIMATION`` o ``EXTERNAL_ALPHA``) y su método;
el resultado queda etiquetado para que una media histórica nunca se tome por alpha. Los
métodos internos futuros (EWMA, factoriales, bayesianos, señales) implementarán esta misma
interfaz; no existen todavía.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from portfolio_engine.models.enums import ExpectedReturnMode
from portfolio_engine.models.market_data import ReturnsMatrix
from portfolio_engine.models.risk_model import ExpectedReturns


class ExpectedReturnProvider(Protocol):
    """Proveedor de expected returns anualizados para un conjunto ordenado de activos."""

    @property
    def mode(self) -> ExpectedReturnMode:
        """Modo del proveedor."""
        ...

    def estimate(self, asset_ids: Sequence[str], returns: ReturnsMatrix | None) -> ExpectedReturns:
        """Expected returns anualizados de ``asset_ids`` (ordenados y únicos)."""
        ...
