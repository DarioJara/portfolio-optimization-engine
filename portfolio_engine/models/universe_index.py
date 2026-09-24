"""Índices de activos en tres niveles (MASTER_SPEC §59, ARCHITECTURE §5.1; DAT-013).

* ``GlobalAssetIndex`` (:class:`AssetIndex`): ``AssetID`` → posición en ``mu_global`` y
  ``Sigma_global`` (orden lexicográfico de AssetID).
* ``EligibleUniverseIndex``: subconjunto de posiciones globales elegibles para una cartera; puede
  ser no consecutivo dentro del universo global.
* ``CandidateLocalIndex`` (:class:`CompositionIndexMap`): posición dentro de una composición
  (``0 .. n-1``, en orden ascendente de AssetID = de posición global) y su correspondencia con
  los niveles anteriores.

``AssetID`` es la identidad funcional del activo: un índice de la covarianza global nunca se
interpreta como índice local, y viceversa.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

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

    def __contains__(self, asset_id: object) -> bool:
        return asset_id in self._positions

    def __len__(self) -> int:
        return len(self._asset_ids)


class EligibleUniverseIndex:
    """Posiciones globales elegibles de una cartera y su correspondencia con la posición elegible.

    ``eligible_idx`` es la posición dentro del vector ordenado de índices globales elegibles; no
    coincide con el índice global salvo que todo el universo sea elegible.
    """

    __slots__ = ("_asset_index", "_global", "_lookup")

    def __init__(self, asset_index: AssetIndex, global_indices: Iterable[int]) -> None:
        unique = sorted({int(position) for position in global_indices})
        if unique and (unique[0] < 0 or unique[-1] >= len(asset_index)):
            raise DataValidationError("Índice global fuera del universo del AssetIndex.")
        self._asset_index = asset_index
        self._global = readonly_int_array(unique)
        lookup = np.full(len(asset_index), -1, dtype=np.int64)
        lookup[self._global] = np.arange(len(unique), dtype=np.int64)
        lookup.setflags(write=False)
        self._lookup = lookup

    @property
    def asset_index(self) -> AssetIndex:
        """Índice global sobre el que se define el universo elegible."""
        return self._asset_index

    @property
    def global_indices(self) -> npt.NDArray[np.int64]:
        """Posiciones globales elegibles, ascendentes (no escribible)."""
        return self._global

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """AssetID elegibles en orden ascendente."""
        return tuple(self._asset_index.asset_id_at(int(position)) for position in self._global)

    def contains_global(self, position: int) -> bool:
        """``True`` si la posición global es elegible."""
        return 0 <= position < len(self._lookup) and bool(self._lookup[position] >= 0)

    def eligible_of(self, global_positions: npt.ArrayLike) -> npt.NDArray[np.int64]:
        """Posición elegible de cada posición global; error si alguna no es elegible."""
        positions = np.asarray(global_positions, dtype=np.int64)
        found = self._lookup[positions]
        if np.any(found < 0):
            raise AssetResolutionError(
                f"Posiciones globales no elegibles: {positions[found < 0].tolist()}"
            )
        return np.asarray(found, dtype=np.int64)

    def eligible_or_missing(self, global_positions: npt.ArrayLike) -> npt.NDArray[np.int64]:
        """Posición elegible de cada posición global, o ``-1`` si no es elegible."""
        return np.asarray(self._lookup[np.asarray(global_positions, dtype=np.int64)])

    def global_of(self, eligible_positions: npt.ArrayLike) -> npt.NDArray[np.int64]:
        """Posición global de cada posición elegible."""
        return np.asarray(self._global[np.asarray(eligible_positions, dtype=np.int64)])

    def __len__(self) -> int:
        return len(self._global)


@dataclass(frozen=True, eq=False, slots=True)
class CompositionIndexMap:
    """Correspondencia global ↔ elegible ↔ local de una composición (``CandidateLocalIndex``).

    ``asset_ids`` está ordenado; ``global_indices[local]`` es la posición del activo en
    ``mu_global``/``Sigma_global`` y ``eligible_indices[local]`` su posición elegible (``-1`` si
    el activo, p. ej. una posición actual no comprable, no pertenece al universo elegible).
    """

    asset_ids: tuple[str, ...]
    global_indices: npt.NDArray[np.int64]
    eligible_indices: npt.NDArray[np.int64]

    def __post_init__(self) -> None:
        if list(self.asset_ids) != sorted(set(self.asset_ids)):
            raise DataValidationError("CompositionIndexMap exige AssetID únicos y ordenados.")
        global_indices = readonly_int_array(self.global_indices)
        eligible_indices = readonly_int_array(self.eligible_indices)
        expected = (len(self.asset_ids),)
        if global_indices.shape != expected or eligible_indices.shape != expected:
            raise DataValidationError("Dimensiones incoherentes en CompositionIndexMap.")
        if np.any(np.diff(global_indices) <= 0):
            raise DataValidationError("Las posiciones globales deben ser estrictamente crecientes.")
        object.__setattr__(self, "global_indices", global_indices)
        object.__setattr__(self, "eligible_indices", eligible_indices)

    @classmethod
    def build(
        cls, eligible: EligibleUniverseIndex, asset_ids: Iterable[str]
    ) -> CompositionIndexMap:
        """Mapa de la composición ``asset_ids`` (cualquier orden; se ordena de forma canónica)."""
        ordered = tuple(sorted(set(asset_ids)))
        global_indices = eligible.asset_index.indices_of(ordered)
        eligible_indices = eligible.eligible_or_missing(global_indices)
        return cls(ordered, global_indices, eligible_indices)

    @property
    def size(self) -> int:
        """Número de activos de la composición."""
        return len(self.asset_ids)

    def local_of_global(self, position: int) -> int:
        """Posición local de una posición global de la composición."""
        found = np.flatnonzero(self.global_indices == position)
        if found.size == 0:
            raise AssetResolutionError(f"Posición global {position} fuera de la composición.")
        return int(found[0])

    def extract_vector(self, global_vector: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Subvector local (copia) de un vector global (``mu_global``)."""
        return np.array(global_vector[self.global_indices], dtype=np.float64)

    def extract_submatrix(self, global_matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Submatriz local ``n×n`` (copia explícita, no una vista) de ``Sigma_global``."""
        return np.array(global_matrix[np.ix_(self.global_indices, self.global_indices)])
