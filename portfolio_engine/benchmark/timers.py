"""Temporizadores por etapa (MASTER_SPEC §71; BEN-001, subconjunto B2).

``BenchmarkRecorder.stage(nombre)`` mide con ``time.perf_counter`` y acumula una muestra por
ejecución de la etapa. Sin estado global: cada recorder es una instancia independiente.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager


class BenchmarkRecorder:
    """Acumula muestras de tiempo por etapa."""

    def __init__(self) -> None:
        self._samples: defaultdict[str, list[float]] = defaultdict(list)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Mide el bloque ``with`` y registra su duración (segundos) en la etapa ``name``."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self._samples[name].append(time.perf_counter() - started)

    def record(self, name: str, seconds: float) -> None:
        """Registra una muestra ya medida (p. ej. los tiempos del solver)."""
        self._samples[name].append(seconds)

    def samples(self) -> Mapping[str, tuple[float, ...]]:
        """Muestras por etapa."""
        return {name: tuple(values) for name, values in self._samples.items()}
