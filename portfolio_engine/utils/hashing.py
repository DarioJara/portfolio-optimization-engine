"""Serialización canónica y hashing determinista.

Los hashes se usan para reproducibilidad y claves de caché (MASTER_SPEC §31, §70). Deben ser
estables entre procesos y ejecuciones: no se usa nunca ``hash()`` de Python.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import Enum

import numpy as np
import numpy.typing as npt


def _normalize(value: object) -> object:
    """Convierte ``value`` en una estructura JSON con orden y tipos canónicos."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, (frozenset, set)):
        return sorted(_normalize(item) for item in value)  # type: ignore[type-var]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"Tipo no serializable de forma canónica: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Serializa ``value`` a JSON canónico: claves ordenadas, sin espacios, sin NaN/inf."""
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    """Devuelve el SHA-256 hexadecimal de ``text`` codificado en UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_float(value: float) -> str:
    """Representación exacta y canónica de un float (``float.hex``), con ``-0.0`` → ``0.0``.

    No redondea: dos floats distintos (aunque difieran en el último bit) producen
    representaciones distintas.
    """
    number = float(value)
    if number == 0.0:
        number = 0.0
    return number.hex()


def hash_float_array(array: npt.NDArray[np.float64]) -> str:
    """Hash SHA-256 de la forma y de los bytes exactos (float64, little-endian, orden C)."""
    canonical = np.ascontiguousarray(array, dtype="<f8")
    digest = hashlib.sha256()
    digest.update(repr(canonical.shape).encode("utf-8"))
    digest.update(canonical.tobytes(order="C"))
    return digest.hexdigest()
