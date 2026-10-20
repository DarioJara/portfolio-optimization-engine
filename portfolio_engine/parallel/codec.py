"""Códec JSON no ejecutable para los resultados del diario (Bloque 5.4; P-05).

Serializa los árboles de resultados (dataclasses, enums, arrays NumPy, tuplas, diccionarios,
conjuntos, floats, enteros, cadenas) a JSON **sin** ``pickle`` y los reconstruye de forma exacta
(bit a bit para los floats y los arrays). Decodificar nunca ejecuta código del fichero:

* los tipos se resuelven únicamente por nombre dentro de ``portfolio_engine`` y solo si son
  dataclasses o enums (``ALLOWED_PACKAGE``); cualquier otra etiqueta o clase se rechaza;
* los arrays aceptan solo dtypes numéricos o booleanos (nunca ``object``);
* el fichero lleva una suma SHA-256 que el diario comprueba antes de decodificar (detecta
  corrupción y truncamiento; no es una firma: quien pueda reescribir el fichero y su suma puede
  alterar los resultados, de modo que el diario debe protegerse con permisos del sistema).

Los escalares NumPy (``np.float64`` …) se serializan como el tipo Python equivalente (mismo
valor); los motores no devuelven otros tipos (lo comprueba la prueba de ida y vuelta de todas las
clases de workload).
"""

from __future__ import annotations

import base64
import dataclasses
import enum
import importlib
import math
from types import MappingProxyType
from typing import Any

import numpy as np

from portfolio_engine.exceptions import PortfolioEngineError

ALLOWED_PACKAGE = "portfolio_engine"
#: Kinds de ``numpy.dtype.kind`` admitidos: booleano, entero con/sin signo y float.
ALLOWED_DTYPE_KINDS = "biuf"
#: Etiquetas del formato (una por tipo estructural).
TAG_FLOAT, TAG_ENUM, TAG_ARRAY, TAG_TUPLE, TAG_DICT = "$f", "$e", "$a", "$t", "$d"
TAG_FROZENSET, TAG_SET, TAG_BYTES, TAG_DATACLASS = "$fs", "$s", "$b", "$dc"
ARRAY_PARTS = 3  # dtype, forma, datos
PAIR_PARTS = 2  # (tipo, valor) / (tipo, campos)
NON_FINITE = MappingProxyType({"nan": math.nan, "inf": math.inf, "-inf": -math.inf})


class CodecError(PortfolioEngineError):
    """Un valor no se puede codificar o el documento no se puede decodificar de forma segura."""


def _type_name(cls: type) -> str:
    return f"{cls.__module__}:{cls.__qualname__}"


def _resolve(name: object, kind: str) -> type:
    """Resuelve ``modulo:Clase`` dentro del paquete permitido; solo dataclasses o enums."""
    if not isinstance(name, str) or name.count(":") != 1:
        raise CodecError(f"Nombre de tipo inválido: {name!r}.")
    module_name, qualname = name.split(":")
    if module_name != ALLOWED_PACKAGE and not module_name.startswith(ALLOWED_PACKAGE + "."):
        raise CodecError(f"Tipo fuera de {ALLOWED_PACKAGE}: {name!r}.")
    try:
        target: Any = importlib.import_module(module_name)
        for part in qualname.split("."):
            target = getattr(target, part)
    except (ImportError, AttributeError) as error:
        raise CodecError(f"Tipo desconocido: {name!r}.") from error
    if not isinstance(target, type):
        raise CodecError(f"{name!r} no es una clase.")
    if kind == "enum" and not issubclass(target, enum.Enum):
        raise CodecError(f"{name!r} no es un enum.")
    if kind == "dataclass" and not dataclasses.is_dataclass(target):
        raise CodecError(f"{name!r} no es una dataclass.")
    return target


_UNHANDLED = object()


def _encode_simple(value: object) -> object:
    if isinstance(value, enum.Enum):  # antes que ``str``: los ``StrEnum`` también son cadenas
        return {TAG_ENUM: [_type_name(type(value)), value.name]}
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isfinite(number):
            return number
        return {TAG_FLOAT: "nan" if math.isnan(number) else ("inf" if number > 0 else "-inf")}
    if isinstance(value, np.bool_):
        return bool(value)
    return _UNHANDLED


def _encode_array(value: np.ndarray[Any, Any]) -> object:
    if value.dtype.kind not in ALLOWED_DTYPE_KINDS:
        raise CodecError(f"dtype de array no admitido: {value.dtype}.")
    contiguous = np.ascontiguousarray(value)
    data = base64.b64encode(contiguous.tobytes()).decode("ascii")
    return {TAG_ARRAY: [contiguous.dtype.str, list(contiguous.shape), data]}


def _encode_container(value: object) -> object:
    if isinstance(value, np.ndarray):
        return _encode_array(value)
    if isinstance(value, tuple):
        return {TAG_TUPLE: [encode(item) for item in value]}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, (frozenset, set)):
        items = sorted((encode(item) for item in value), key=repr)
        return {TAG_FROZENSET if isinstance(value, frozenset) else TAG_SET: items}
    if isinstance(value, dict):
        return {TAG_DICT: [[encode(key), encode(item)] for key, item in value.items()]}
    if isinstance(value, bytes):
        return {TAG_BYTES: base64.b64encode(value).decode("ascii")}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {
            field.name: encode(getattr(value, field.name)) for field in dataclasses.fields(value)
        }
        return {TAG_DATACLASS: [_type_name(type(value)), fields]}
    return _UNHANDLED


def encode(value: object) -> object:
    """Convierte ``value`` en una estructura compuesta solo por tipos JSON."""
    for encoder in (_encode_simple, _encode_container):
        encoded = encoder(value)
        if encoded is not _UNHANDLED:
            return encoded
    raise CodecError(f"Tipo no serializable en el diario: {type(value).__name__}.")


def _decode_array(payload: object) -> np.ndarray[Any, Any]:
    if not isinstance(payload, list) or len(payload) != ARRAY_PARTS:
        raise CodecError("Array mal formado.")
    dtype_text, shape, data = payload
    dtype = np.dtype(dtype_text)
    if dtype.kind not in ALLOWED_DTYPE_KINDS:
        raise CodecError(f"dtype de array no admitido: {dtype}.")
    raw = base64.b64decode(data, validate=True)
    array = np.frombuffer(raw, dtype=dtype).reshape(tuple(int(n) for n in shape))
    return array


def _decode_dataclass(payload: object) -> object:
    if not isinstance(payload, list) or len(payload) != PAIR_PARTS:
        raise CodecError("Dataclass mal formada.")
    name, stored = payload
    cls = _resolve(name, "dataclass")
    if not isinstance(stored, dict):
        raise CodecError("Campos de dataclass mal formados.")
    fields = {field.name: field for field in dataclasses.fields(cls)}
    if set(stored) != set(fields):
        raise CodecError(f"Los campos de {name} no coinciden con la clase actual.")
    decoded = {key: decode(item) for key, item in stored.items()}
    init_kwargs = {key: item for key, item in decoded.items() if fields[key].init}
    instance = cls(**init_kwargs)
    for key, item in decoded.items():
        if not fields[key].init:
            object.__setattr__(instance, key, item)
    return instance


def _decode_enum(payload: object) -> object:
    if not isinstance(payload, list) or len(payload) != PAIR_PARTS:
        raise CodecError("Enum mal formado.")
    cls: Any = _resolve(payload[0], "enum")
    try:
        return cls[payload[1]]
    except KeyError as error:
        raise CodecError(f"Miembro de enum desconocido: {payload!r}.") from error


def _decode_simple_tag(tag: str, payload: object) -> object:
    if tag == TAG_FLOAT:
        if payload not in NON_FINITE:
            raise CodecError(f"Float no finito desconocido: {payload!r}.")
        return NON_FINITE[str(payload)]
    if tag == TAG_ENUM:
        return _decode_enum(payload)
    if tag == TAG_ARRAY:
        return _decode_array(payload)
    if tag == TAG_BYTES and isinstance(payload, str):
        return base64.b64decode(payload, validate=True)
    return _UNHANDLED


def _decode_container_tag(tag: str, payload: object) -> object:
    if tag == TAG_TUPLE and isinstance(payload, list):
        return tuple(decode(item) for item in payload)
    if tag in (TAG_FROZENSET, TAG_SET) and isinstance(payload, list):
        items = [decode(item) for item in payload]
        return frozenset(items) if tag == TAG_FROZENSET else set(items)
    if tag == TAG_DICT and isinstance(payload, list):
        return {decode(key): decode(item) for key, item in payload}
    if tag == TAG_DATACLASS:
        return _decode_dataclass(payload)
    return _UNHANDLED


def decode(document: object) -> Any:
    """Reconstruye el valor codificado por :func:`encode` (sin ejecutar código del documento)."""
    if document is None or isinstance(document, (bool, int, float, str)):
        return document
    if isinstance(document, list):
        return [decode(item) for item in document]
    if not isinstance(document, dict) or len(document) != 1:
        raise CodecError("Documento mal formado.")
    ((tag, payload),) = document.items()
    for decoder in (_decode_simple_tag, _decode_container_tag):
        decoded = decoder(tag, payload)
        if decoded is not _UNHANDLED:
            return decoded
    raise CodecError(f"Etiqueta desconocida o mal formada: {tag!r}.")
