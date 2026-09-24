"""Determinismo de las ejecuciones (MASTER_SPEC §61; PAR-009, PAR-010).

En el Bloque 3 solo existen las utilidades de determinismo (semillas y orden estable). El
paralelismo real (``PortfolioBatch``, memoria compartida, ejecutores) pertenece al Bloque 5.
"""

from portfolio_engine.parallel.determinism import derive_seed, sequence_key, tie_break_key

__all__ = ("derive_seed", "sequence_key", "tie_break_key")
