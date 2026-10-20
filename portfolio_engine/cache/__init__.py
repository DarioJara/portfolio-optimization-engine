"""Caché de resultados (MASTER_SPEC §31, §62; Bloque 5.3: CCH-001…005).

La construcción de claves a partir de solicitudes y datos de mercado vive en
``portfolio_engine.parallel.operation_cache``; este paquete solo define la clave canónica y la
caché.
"""

from portfolio_engine.cache.keys import OFFICIAL_COMPONENTS, UNSPECIFIED, CacheKey, CacheKeyError
from portfolio_engine.cache.result_cache import (
    CacheError,
    CacheEvent,
    CacheMetrics,
    ResultCache,
)

__all__ = (
    "OFFICIAL_COMPONENTS",
    "UNSPECIFIED",
    "CacheError",
    "CacheEvent",
    "CacheKey",
    "CacheKeyError",
    "CacheMetrics",
    "ResultCache",
)
