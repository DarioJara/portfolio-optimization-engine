"""Configuración de los benchmarks de escala y de la detección de deterioros (B5.5; CFG-012).

Complementa a :class:`~portfolio_engine.config.benchmark_config.BenchmarkConfig` (sección
``[benchmark]`` de ``default_engine.toml``, micro-benchmark del Bloque 2) con un fichero propio,
``config/default_benchmark.toml``. Son ajustes de MEDIDA: no forman parte del ``ConfigHash`` del
motor ni de las claves de caché, y los valores del fichero de ejemplo son supuestos de ingeniería,
no resultados medidos ni datos reales. Se aplican las reglas estrictas del cargador: toda clave
obligatoria debe estar presente y toda clave desconocida es un error.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from portfolio_engine.config._validation import require_finite, require_int_at_least
from portfolio_engine.config.loader import build_dataclass, read_toml
from portfolio_engine.exceptions import ConfigError

SCALING_SECTION = "scaling"


@dataclass(frozen=True, slots=True)
class ClassShare:
    """Proporción del número de carteras que ejecuta una clase de coste (``label``)."""

    label: str
    fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ConfigError("scaling.mixes[].shares[].label debe ser un texto no vacío.")
        require_finite(self.fraction, "scaling.mixes[].shares[].fraction")
        if not 0.0 < self.fraction <= 1.0:
            raise ConfigError("scaling.mixes[].shares[].fraction debe estar en (0, 1].")


@dataclass(frozen=True, slots=True)
class WorkloadMix:
    """Mezcla sintética de clases de coste: SUPUESTO DE INGENIERÍA, no una distribución real."""

    name: str
    shares: tuple[ClassShare, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ConfigError("scaling.mixes[].name debe ser un texto no vacío.")
        if not self.shares:
            raise ConfigError(f"La mezcla {self.name!r} no tiene clases.")
        labels = [share.label for share in self.shares]
        if len(set(labels)) != len(labels):
            raise ConfigError(f"La mezcla {self.name!r} repite una clase.")
        total = sum(share.fraction for share in self.shares)
        # Las fracciones deben sumar 1 salvo el redondeo de la suma en coma flotante.
        if abs(total - 1.0) > sys.float_info.epsilon * len(self.shares):
            raise ConfigError(f"Las fracciones de la mezcla {self.name!r} suman {total}, no 1.")


@dataclass(frozen=True, slots=True)
class ScalingBenchmarkConfig:
    """Parámetros de los benchmarks de escala y de la detección de deterioros (B5.5).

    Attributes:
        universe_assets: activos del universo sintético.
        holdings_min / holdings_max: rango de posiciones por cartera sintética.
        degenerate_fraction: proporción de carteras intencionadamente degeneradas (rutas de error).
        return_periods: observaciones de los escenarios de retorno sintéticos (CVaR).
        small_scale_max: hasta este nº de carteras se usan ``repetitions_small`` repeticiones.
        repetitions_small / repetitions_large: repeticiones medidas por celda.
        warmup_runs: ejecuciones descartadas (informadas) antes de medir.
        max_portfolios_without_authorization: tope de carteras por ejecución sin autorización
            expresa (D-12). Superarlo exige ``--authorized-by`` en el script.
        mad_k: factor ``k`` del umbral de deterioro ``k × MAD`` (BEN-005).
        mad_relative_floor: suelo relativo de la MAD (fracción de la mediana) cuando la MAD
            medida es ~0 con pocas repeticiones; evita un umbral nulo.
        iteration_relative_tolerance: variación relativa admitida del contador de iteraciones de
            solver frente al baseline (puede cambiar en una unidad entre CPU).
        mixes: mezclas sintéticas de referencia.
    """

    universe_assets: int
    holdings_min: int
    holdings_max: int
    degenerate_fraction: float
    return_periods: int
    small_scale_max: int
    repetitions_small: int
    repetitions_large: int
    warmup_runs: int
    max_portfolios_without_authorization: int
    mad_k: float
    mad_relative_floor: float
    iteration_relative_tolerance: float
    mixes: tuple[WorkloadMix, ...]

    def __post_init__(self) -> None:
        require_int_at_least(self.universe_assets, 1, "scaling.universe_assets")
        require_int_at_least(self.holdings_min, 1, "scaling.holdings_min")
        require_int_at_least(self.holdings_max, self.holdings_min, "scaling.holdings_max")
        if self.holdings_max > self.universe_assets:
            raise ConfigError("scaling.holdings_max no puede superar scaling.universe_assets.")
        require_finite(self.degenerate_fraction, "scaling.degenerate_fraction")
        if not 0.0 <= self.degenerate_fraction < 1.0:
            raise ConfigError("scaling.degenerate_fraction debe estar en [0, 1).")
        require_int_at_least(self.return_periods, 2, "scaling.return_periods")
        require_int_at_least(self.small_scale_max, 1, "scaling.small_scale_max")
        require_int_at_least(self.repetitions_small, 1, "scaling.repetitions_small")
        require_int_at_least(self.repetitions_large, 1, "scaling.repetitions_large")
        require_int_at_least(self.warmup_runs, 0, "scaling.warmup_runs")
        require_int_at_least(
            self.max_portfolios_without_authorization,
            1,
            "scaling.max_portfolios_without_authorization",
        )
        require_finite(self.mad_k, "scaling.mad_k")
        require_finite(self.mad_relative_floor, "scaling.mad_relative_floor")
        if self.mad_k <= 0 or self.mad_relative_floor < 0:
            raise ConfigError("scaling.mad_k debe ser > 0 y scaling.mad_relative_floor >= 0.")
        require_finite(self.iteration_relative_tolerance, "scaling.iteration_relative_tolerance")
        if not 0.0 <= self.iteration_relative_tolerance < 1.0:
            raise ConfigError("scaling.iteration_relative_tolerance debe estar en [0, 1).")
        names = [mix.name for mix in self.mixes]
        if not names or len(set(names)) != len(names):
            raise ConfigError("scaling.mixes debe tener al menos una mezcla y nombres únicos.")

    def mix(self, name: str) -> WorkloadMix:
        """Mezcla por nombre (error si no existe)."""
        for candidate in self.mixes:
            if candidate.name == name:
                return candidate
        available = [m.name for m in self.mixes]
        raise ConfigError(f"Mezcla {name!r} no definida (disponibles: {available}).")

    def repetitions_for(self, portfolios: int) -> int:
        """Repeticiones medidas para una escala de ``portfolios`` carteras."""
        if portfolios <= self.small_scale_max:
            return self.repetitions_small
        return self.repetitions_large


def load_scaling_benchmark_config(
    source: str | Path | Mapping[str, Any],
) -> ScalingBenchmarkConfig:
    """Carga y valida un :class:`ScalingBenchmarkConfig` desde un TOML o un diccionario."""
    raw = read_toml(source) if isinstance(source, (str, Path)) else source
    if not isinstance(raw, Mapping) or set(raw) != {SCALING_SECTION}:
        raise ConfigError(
            f"La configuración de escala debe tener solo la sección [{SCALING_SECTION}]."
        )
    return build_dataclass(ScalingBenchmarkConfig, raw[SCALING_SECTION], SCALING_SECTION)
