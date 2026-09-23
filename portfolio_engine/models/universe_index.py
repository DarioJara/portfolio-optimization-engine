"""Índice global de activos (MASTER_SPEC §59, ARCHITECTURE §5.1).

En el Bloque 1 solo existe el nivel global (``AssetID`` → ``global_idx``). Los niveles
``eligible`` y ``candidate-local`` se añaden en el Bloque 3.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import numpy.typing as npt

from portfolio_engine.exceptions import AssetResolutionError, DataValidationError
from portfolio_engine.models.asset import Universe
from portfolio_engine.utils.numerics import readonly_int_array


class AssetIndex:
    """Mapeo determinista ``AssetID`` ↔ posición global (orden lexicográfico de AssetID)."""

    __slots__ = ("_asset_ids", "_positions")

    def __init__(self, asset_ids: Sequence[str]) -> None:
        ids = tuple(asset_ids)
        if list(ids) != sorted(set(ids)):
            raise DataValidationError("AssetIndex exige AssetID únicos y ordenados.")
        self._asset_ids = ids
        self._positions = {asset_id: position for position, asset_id in enumerate(ids)}

    @classmethod
    def from_universe(cls, universe: Universe) -> AssetIndex:
        """Construye el índice global a partir del universo."""
        return cls(universe.asset_ids)

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """AssetID en orden global."""
        return self._asset_ids

    def index_of(self, asset_id: str) -> int:
        """Posición global de ``asset_id``."""
        try:
            return self._positions[asset_id]
        except KeyError as error:
            raise AssetResolutionError(f"AssetID fuera del índice: {asset_id!r}") from error

    def indices_of(self, asset_ids: Iterable[str]) -> npt.NDArray[np.int64]:
        """Posiciones globales (array int64 no escribible) de ``asset_ids`` en el orden dado."""
        return readonly_int_array([self.index_of(asset_id) for asset_id in asset_ids])

    def asset_id_at(self, position: int) -> str:
        """AssetID en la posición global ``position``."""
        return self._asset_ids[position]

    def __len__(self) -> int:
        return len(self._asset_ids)
