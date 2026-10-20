"""Determinismo y ejecución paralela (MASTER_SPEC §56-61; PAR-001…PAR-013).

Este ``__init__`` solo reexporta las utilidades de determinismo (semillas y orden estable, B3):
las capas inferiores (``candidates``, ``frontiers``) importan ``parallel.determinism`` y no pueden
depender de la orquestación. La ejecución por lotes (Bloque 5.2) se importa explícitamente desde
sus módulos, que sí dependen de los motores de B1-B4:

* ``parallel.workload``: ``WorkloadSpec`` y catálogo de operaciones;
* ``parallel.task``: ``run_portfolio`` (referencia secuencial), ``TaskResult``;
* ``parallel.batching``: ``SequenceID`` y lotes;
* ``parallel.executor``: ``SequentialExecutor`` y ``ParallelExecutor``;
* ``parallel.worker`` y ``parallel.threading_control``: proceso worker y control de hilos.

Pendiente (B5.3/B5.4): memoria compartida definitiva, caché, plazos, reintentos y diario.
"""

from portfolio_engine.parallel.determinism import derive_seed, sequence_key, tie_break_key

__all__ = ("derive_seed", "sequence_key", "tie_break_key")
