"""Activos y universo de inversión (MASTER_SPEC §6).

``AssetID`` es la clave canónica interna; ``Ticker`` es un alias que debe resolverse de forma
inequívoca (decisión A-31).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from portfolio_engine.exceptions import AssetResolutionError, DataValidationError


@dataclass(frozen=True, slots=True)
class AssetMetadata:
    """Metadatos de un activo del universo. Los campos opcionales ausentes son ``None``."""

    asset_id: str
    ticker: str
    eligible: bool
    sector: str | None
    industry: str | None
    country: str | None
    currency: str | None
    asset_class: str | None
    liquidity_flag: bool | None
    min_weight: float | None
    max_weight: float | None
    estimated_transaction_cost: float | None
    buy_cost: float | None
    sell_cost: float | None
    bid_ask_spread: float | None
    adv: float | None
    market_cap: float | None
    restricted: bool | None


class Universe:
    """Colección inmutable de activos ordenada por ``asset_id``.

    Garantiza unicidad de ``asset_id``. Los tickers duplicados se permiten en la estructura
    pero no pueden usarse para resolver identificadores (error de ambigüedad).
    """

    __slots__ = ("_assets", "_by_id", "_by_ticker")

    def __init__(self, assets: Iterable[AssetMetadata]) -> None:
        ordered = tuple(sorted(assets, key=lambda asset: asset.asset_id))
        by_id: dict[str, AssetMetadata] = {}
        for asset in ordered:
            if asset.asset_id in by_id:
                raise DataValidationError(f"AssetID duplicado en el universo: {asset.asset_id!r}")
            by_id[asset.asset_id] = asset
        by_ticker: dict[str, list[str]] = {}
        for asset in ordered:
            by_ticker.setdefault(asset.ticker, []).append(asset.asset_id)
        self._assets = ordered
        self._by_id = by_id
        self._by_ticker = {ticker: tuple(ids) for ticker, ids in by_ticker.items()}

    @property
    def assets(self) -> tuple[AssetMetadata, ...]:
        """Activos ordenados por ``asset_id``."""
        return self._assets

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """``asset_id`` ordenados."""
        return tuple(asset.asset_id for asset in self._assets)

    def get(self, asset_id: str) -> AssetMetadata:
        """Devuelve el activo con ``asset_id`` o lanza :class:`AssetResolutionError`."""
        try:
            return self._by_id[asset_id]
        except KeyError as error:
            raise AssetResolutionError(f"AssetID desconocido: {asset_id!r}") from error

    def resolve(self, identifier: str) -> str:
        """Resuelve un AssetID o Ticker a su AssetID canónico, exigiendo que sea inequívoco."""
        candidates = set(self._by_ticker.get(identifier, ()))
        if identifier in self._by_id:
            candidates.add(identifier)
        if not candidates:
            raise AssetResolutionError(f"Identificador de activo desconocido: {identifier!r}")
        if len(candidates) > 1:
            raise AssetResolutionError(
                f"Identificador ambiguo {identifier!r}: corresponde a {sorted(candidates)}"
            )
        return next(iter(candidates))

    def __contains__(self, asset_id: object) -> bool:
        return asset_id in self._by_id

    def __len__(self) -> int:
        return len(self._assets)

    def __iter__(self) -> Iterator[AssetMetadata]:
        return iter(self._assets)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Universe) and self._assets == other._assets

    def __hash__(self) -> int:
        return hash(self._assets)
