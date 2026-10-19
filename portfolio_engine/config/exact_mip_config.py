"""Configuración de ``EXACT_MIP`` (MASTER_SPEC §49, enmienda E-24; CFG-001, CFG-015).

``EXACT_MIP`` es un modo de **validación** de heurísticas, nunca del bucle interno de producción:
sus límites (tiempo, brecha, tamaño del universo) son explícitos y obligatorios.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import (
    require_int_at_least,
    require_non_negative,
    require_positive,
)


@dataclass(frozen=True, slots=True)
class ExactMIPConfig:
    """Parámetros del solver mixto entero de validación.

    Attributes:
        time_limit_seconds: límite de tiempo por resolución (obligatorio: sin límite implícito).
        relative_gap_tolerance: brecha relativa a la que el solver declara optimalidad.
        absolute_gap_tolerance: brecha absoluta a la que el solver declara optimalidad.
        integrality_tolerance: distancia a un entero con la que un valor binario se considera
            entero (y con la que se valida a posteriori).
        max_universe_size: tamaño máximo del universo del MIQP (guarda de escala: el problema
            exacto no es apto para universos de cientos de activos).
        threads: hilos del solver (1 = determinista).
        node_limit: nodos máximos del árbol (``None`` = sin límite).
    """

    time_limit_seconds: float
    relative_gap_tolerance: float
    absolute_gap_tolerance: float
    integrality_tolerance: float
    max_universe_size: int
    threads: int
    node_limit: int | None

    def __post_init__(self) -> None:
        require_positive(self.time_limit_seconds, "exact_mip.time_limit_seconds")
        require_non_negative(self.relative_gap_tolerance, "exact_mip.relative_gap_tolerance")
        require_non_negative(self.absolute_gap_tolerance, "exact_mip.absolute_gap_tolerance")
        require_positive(self.integrality_tolerance, "exact_mip.integrality_tolerance")
        require_int_at_least(self.max_universe_size, 1, "exact_mip.max_universe_size")
        require_int_at_least(self.threads, 1, "exact_mip.threads")
        if self.node_limit is not None:
            require_int_at_least(self.node_limit, 1, "exact_mip.node_limit")
