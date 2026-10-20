"""Caché acotada de resultados completos (MASTER_SPEC §62; CCH-001, CCH-003, CCH-005).

* Almacena **resultados reales** (el objeto que devuelve el motor), nunca banderas: se guardan
  serializados (``pickle``) y cada lectura devuelve un objeto **nuevo**. Así ningún objeto mutable
  se
  comparte entre carteras ni entre llamadas, y el tamaño en bytes es exacto para el límite.
* Un acierto (*hit*) **no invoca** la función de cálculo: ``get_or_compute`` solo la llama en un
  fallo.
* Capacidad acotada por ``max_entries`` y ``max_bytes`` con expulsión LRU; un resultado mayor que
  ``max_bytes`` no se guarda. Métricas de aciertos, fallos, expulsiones y rechazos.
* Una instancia por proceso (worker): sin hilos ni bloqueos. ``pickle`` se usa solo con objetos
  generados por esta misma instancia en este mismo proceso (nunca se lee de disco ni de la red).
"""

from __future__ import annotations

import pickle
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from portfolio_engine.cache.keys import CacheKey
from portfolio_engine.exceptions import PortfolioEngineError

T = TypeVar("T")


class CacheError(PortfolioEngineError):
    """Configuración inválida de la caché."""


class CacheEvent(StrEnum):
    """Qué ocurrió con la caché en una consulta."""

    DISABLED = "DISABLED"
    HIT = "HIT"
    MISS = "MISS"


@dataclass(frozen=True, slots=True)
class CacheMetrics:
    """Contadores de la caché (acumulados desde su creación).

    Attributes:
        hits: consultas servidas desde la caché (sin ejecutar el cálculo).
        misses: consultas que ejecutaron el cálculo.
        stores: resultados guardados.
        evictions: entradas expulsadas por capacidad (LRU).
        rejected: resultados no guardados (mayores que ``max_bytes`` o no serializables).
        skipped: resultados no guardados por política (estados no definitivos).
        entries: entradas actuales.
        bytes: bytes serializados actuales.
    """

    hits: int = 0
    misses: int = 0
    stores: int = 0
    evictions: int = 0
    rejected: int = 0
    skipped: int = 0
    entries: int = 0
    bytes: int = 0

    def __add__(self, other: CacheMetrics) -> CacheMetrics:
        return CacheMetrics(
            self.hits + other.hits,
            self.misses + other.misses,
            self.stores + other.stores,
            self.evictions + other.evictions,
            self.rejected + other.rejected,
            self.skipped + other.skipped,
            self.entries + other.entries,
            self.bytes + other.bytes,
        )

    def since(self, earlier: CacheMetrics) -> CacheMetrics:
        """Variación de los contadores desde ``earlier``; ``entries``/``bytes`` son los actuales."""
        return CacheMetrics(
            self.hits - earlier.hits,
            self.misses - earlier.misses,
            self.stores - earlier.stores,
            self.evictions - earlier.evictions,
            self.rejected - earlier.rejected,
            self.skipped - earlier.skipped,
            self.entries,
            self.bytes,
        )

    @property
    def hit_ratio(self) -> float | None:
        """Proporción de aciertos (``None`` sin consultas)."""
        total = self.hits + self.misses
        return None if total == 0 else self.hits / total


class ResultCache:
    """Caché LRU acotada de resultados serializados."""

    def __init__(self, max_entries: int, max_bytes: int) -> None:
        if max_entries < 1 or max_bytes < 1:
            raise CacheError("max_entries y max_bytes deben ser >= 1.")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._bytes = 0
        self._hits = self._misses = self._stores = 0
        self._evictions = self._rejected = self._skipped = 0

    @property
    def metrics(self) -> CacheMetrics:
        """Contadores actuales."""
        return CacheMetrics(
            self._hits,
            self._misses,
            self._stores,
            self._evictions,
            self._rejected,
            self._skipped,
            len(self._entries),
            self._bytes,
        )

    def __contains__(self, key: CacheKey) -> bool:
        return key.digest in self._entries

    def get(self, key: CacheKey) -> Any | None:
        """Copia nueva del resultado guardado (``None`` si no está). Cuenta acierto o fallo."""
        payload = self._entries.get(key.digest)
        if payload is None:
            self._misses += 1
            return None
        self._entries.move_to_end(key.digest)
        self._hits += 1
        return pickle.loads(payload)  # bytes creados por esta instancia en este proceso

    def put(self, key: CacheKey, value: Any) -> bool:
        """Guarda ``value`` (serializado). Devuelve ``False`` si se rechaza por tamaño o tipo."""
        try:
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            self._rejected += 1
            return False
        if len(payload) > self._max_bytes:
            self._rejected += 1
            return False
        digest = key.digest
        previous = self._entries.pop(digest, None)
        if previous is not None:
            self._bytes -= len(previous)
        self._entries[digest] = payload
        self._bytes += len(payload)
        self._stores += 1
        while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
            _, evicted = self._entries.popitem(last=False)
            self._bytes -= len(evicted)
            self._evictions += 1
        return True

    def get_or_compute(
        self,
        key: CacheKey,
        compute: Callable[[], T],
        *,
        cacheable: Callable[[T], bool] | None = None,
    ) -> tuple[T, CacheEvent]:
        """Resultado de ``key``: de la caché (sin llamar a ``compute``) o calculado y guardado.

        Una excepción de ``compute`` se propaga y no se guarda nada. Si ``cacheable`` devuelve
        ``False`` el resultado se devuelve pero no se guarda (``skipped``).
        """
        payload = self._entries.get(key.digest)
        if payload is not None:
            self._entries.move_to_end(key.digest)
            self._hits += 1
            return pickle.loads(payload), CacheEvent.HIT  # copia nueva, bytes propios
        self._misses += 1
        value = compute()
        if cacheable is not None and not cacheable(value):
            self._skipped += 1
        else:
            self.put(key, value)
        return value, CacheEvent.MISS

    def clear(self) -> None:
        """Vacía la caché (los contadores acumulados se conservan)."""
        self._entries.clear()
        self._bytes = 0
