"""Carga estricta de configuración desde TOML o diccionario (MASTER_SPEC §4).

Reglas:

* toda clave desconocida es un error (evita parámetros ignorados en silencio);
* toda clave obligatoria ausente es un error: no hay valores por defecto implícitos;
* solo los campos declarados opcionales (``X | None``) pueden omitirse, y valen ``None``;
* los enums se indican por nombre y los tipos se comprueban (``bool`` no es un ``int``);
* las listas de tablas TOML (``[[seccion.clave]]``) se convierten en tuplas de dataclasses y
  las subtablas (``[seccion.clave]``) en dataclasses anidados.
"""

from __future__ import annotations

import dataclasses
import tomllib
import types
import typing
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from portfolio_engine.config.benchmark_config import BenchmarkConfig
from portfolio_engine.config.candidate_config import CandidateConfig
from portfolio_engine.config.constraint_config import ConstraintConfig
from portfolio_engine.config.data_config import DataConfig
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.frontier_config import FrontierConfig
from portfolio_engine.config.return_config import ReturnConfig
from portfolio_engine.config.risk_config import RiskConfig
from portfolio_engine.config.solver_config import SolverConfig
from portfolio_engine.config.transaction_cost_config import TransactionCostConfig
from portfolio_engine.exceptions import ConfigError

ENGINE_SECTION = "engine"
_SECTIONS: Mapping[str, type[Any]] = types.MappingProxyType(
    {
        "data": DataConfig,
        "returns": ReturnConfig,
        "risk": RiskConfig,
        "constraints": ConstraintConfig,
        "transaction_costs": TransactionCostConfig,
        "frontier": FrontierConfig,
        "solver": SolverConfig,
        "benchmark": BenchmarkConfig,
        "candidates": CandidateConfig,
    }
)

T = TypeVar("T")


def load_engine_config(source: str | Path | Mapping[str, Any]) -> EngineConfig:
    """Carga y valida un :class:`EngineConfig` desde un fichero TOML o un diccionario."""
    raw = _read(source) if isinstance(source, (str, Path)) else source
    if not isinstance(raw, Mapping):
        raise ConfigError("La configuración debe ser un diccionario de secciones.")
    known = {ENGINE_SECTION, *_SECTIONS}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"Secciones de configuración desconocidas: {unknown}")
    missing = sorted(known - set(raw))
    if missing:
        raise ConfigError(f"Secciones de configuración ausentes: {missing}")
    sections = {name: _build(cls, raw[name], name) for name, cls in _SECTIONS.items()}
    engine = raw[ENGINE_SECTION]
    if not isinstance(engine, Mapping):
        raise ConfigError("La sección [engine] debe ser una tabla.")
    engine_fields = {"optimization_horizon_years", "random_seed"}
    unknown_engine = sorted(set(engine) - engine_fields)
    if unknown_engine:
        raise ConfigError(f"Claves desconocidas en [engine]: {unknown_engine}")
    missing_engine = sorted(engine_fields - set(engine))
    if missing_engine:
        raise ConfigError(f"Claves ausentes en [engine]: {missing_engine}")
    return EngineConfig(
        **sections,
        optimization_horizon_years=_convert(
            engine["optimization_horizon_years"], float, "engine.optimization_horizon_years"
        ),
        random_seed=_convert(engine["random_seed"], int, "engine.random_seed"),
    )


def _read(path: str | Path) -> Mapping[str, Any]:
    try:
        with Path(path).open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"No se puede leer la configuración {path}: {error}") from error


def _build(cls: type[T], values: object, section: str) -> T:
    if not isinstance(values, Mapping):
        raise ConfigError(f"La sección [{section}] debe ser una tabla.")
    hints = typing.get_type_hints(cls)
    fields = {field.name for field in dataclasses.fields(cls)}  # type: ignore[arg-type]
    unknown = sorted(set(values) - fields)
    if unknown:
        raise ConfigError(f"Claves desconocidas en [{section}]: {unknown}")
    kwargs: dict[str, object] = {}
    for name in sorted(fields):
        hint = hints[name]
        path = f"{section}.{name}"
        if name not in values:
            if not _is_optional(hint):
                raise ConfigError(f"Clave obligatoria ausente: {path}")
            kwargs[name] = None
            continue
        kwargs[name] = _convert(values[name], hint, path)
    return cls(**kwargs)


def _is_optional(hint: object) -> bool:
    return type(None) in typing.get_args(hint)


def _convert(value: object, hint: Any, path: str) -> Any:
    args = typing.get_args(hint)
    origin = typing.get_origin(hint)
    if origin in (types.UnionType, typing.Union):
        non_null = [arg for arg in args if arg is not type(None)]
        if len(non_null) != 1:
            raise ConfigError(f"Tipo de configuración no soportado en {path}: {hint}")
        return _convert(value, non_null[0], path)
    if origin is tuple:
        if not isinstance(value, list):
            raise ConfigError(f"{path} debe ser una lista.")
        element = args[0]
        if dataclasses.is_dataclass(element) and isinstance(element, type):
            return tuple(
                _build(element, item, f"{path}[{index}]") for index, item in enumerate(value)
            )
        return tuple(_convert(item, element, f"{path}[]") for item in value)
    if isinstance(hint, type) and issubclass(hint, Enum):
        return _convert_enum(value, hint, path)
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        return _build(hint, value, path)
    return _convert_scalar(value, hint, path)


def _convert_enum(value: object, enum_type: type[Enum], path: str) -> Enum:
    if not isinstance(value, str) or value not in enum_type.__members__:
        options = sorted(enum_type.__members__)
        raise ConfigError(f"{path} debe ser uno de {options} (recibido {value!r}).")
    return enum_type[value]


def _convert_scalar(value: object, hint: Any, path: str) -> object:
    if hint is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{path} debe ser booleano.")
        return value
    if hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{path} debe ser entero.")
        return value
    if hint is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path} debe ser numérico.")
        return float(value)
    if hint is str:
        if not isinstance(value, str):
            raise ConfigError(f"{path} debe ser texto.")
        return value
    raise ConfigError(f"Tipo de configuración no soportado en {path}: {hint}")
