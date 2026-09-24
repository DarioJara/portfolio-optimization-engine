"""Configuración del benchmark de rendimiento (MASTER_SPEC §4, §71; CFG-012, subconjunto B2).

No confundir con un benchmark financiero (decisión A-10). Solo incluye lo necesario para el
micro-benchmark del Bloque 2; el resto se añade en el Bloque 5.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import require_finite, require_int_at_least
from portfolio_engine.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Repeticiones, calentamiento y percentiles reportados.

    Attributes:
        repetitions: repeticiones medidas de cada modo.
        warmup_runs: ejecuciones previas descartadas.
        percentiles: percentiles reportados (``> 0``; NumPy rechaza los superiores a 100).
    """

    repetitions: int
    warmup_runs: int
    percentiles: tuple[float, ...]

    def __post_init__(self) -> None:
        require_int_at_least(self.repetitions, 1, "benchmark.repetitions")
        require_int_at_least(self.warmup_runs, 0, "benchmark.warmup_runs")
        if not isinstance(self.percentiles, tuple) or not self.percentiles:
            raise ConfigError("benchmark.percentiles debe ser una tupla no vacía.")
        for value in self.percentiles:
            require_finite(value, "benchmark.percentiles")
            if value <= 0:
                raise ConfigError("benchmark.percentiles debe contener valores > 0.")
