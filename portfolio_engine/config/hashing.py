"""``ConfigSnapshot`` y ``ConfigHash`` deterministas (MASTER_SPEC §31, §70)."""

from __future__ import annotations

import dataclasses
from enum import Enum

from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.utils.hashing import canonical_json, sha256_hex

#: Campos opcionales añadidos después de las líneas base de hashes publicadas: si valen ``None`` no
#: forman parte del ``ConfigSnapshot``, de modo que activar su ausencia no cambia ``ConfigHash``
#: (compatibilidad con cachés, diarios y líneas base existentes). Con un valor sí se incluyen.
_OMITTED_WHEN_NONE = frozenset({"hard_constraints"})


def config_to_dict(config: object) -> dict[str, object]:
    """Convierte un dataclass de configuración (recursivamente) en un diccionario canónico."""
    if not dataclasses.is_dataclass(config) or isinstance(config, type):
        raise TypeError("config_to_dict espera una instancia de dataclass.")
    return {
        field.name: _value(getattr(config, field.name))
        for field in dataclasses.fields(config)
        if not (field.name in _OMITTED_WHEN_NONE and getattr(config, field.name) is None)
    }


def _value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return config_to_dict(value)
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, tuple):
        return [_value(item) for item in value]
    return value


def config_snapshot(config: EngineConfig) -> str:
    """JSON canónico de toda la configuración (claves ordenadas, floats exactos)."""
    return canonical_json(config_to_dict(config))


def config_hash(config: EngineConfig) -> str:
    """SHA-256 del ``ConfigSnapshot``; cambia ante cualquier cambio de parámetro."""
    return sha256_hex(config_snapshot(config))
