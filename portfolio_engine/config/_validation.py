"""Comprobaciones comunes de los dataclasses de configuración (errores ``ConfigError``)."""

from __future__ import annotations

import math

from portfolio_engine.exceptions import ConfigError


def require_finite(value: float, name: str) -> None:
    """Exige que ``value`` sea un número finito."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{name} debe ser un número finito (recibido {value!r}).")


def require_positive(value: float, name: str) -> None:
    """Exige ``value`` finito y > 0."""
    require_finite(value, name)
    if value <= 0:
        raise ConfigError(f"{name} debe ser > 0 (recibido {value!r}).")


def require_non_negative(value: float, name: str) -> None:
    """Exige ``value`` finito y ≥ 0."""
    require_finite(value, name)
    if value < 0:
        raise ConfigError(f"{name} debe ser ≥ 0 (recibido {value!r}).")


def require_int_at_least(value: int, minimum: int, name: str) -> None:
    """Exige un entero (no booleano) ≥ ``minimum``."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{name} debe ser un entero ≥ {minimum} (recibido {value!r}).")
