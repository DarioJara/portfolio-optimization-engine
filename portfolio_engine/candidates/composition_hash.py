"""``CompositionHash`` determinista de una composición (MASTER_SPEC §29, §31; CAN-015).

La composición es un **conjunto** de ``AssetID``: se serializa de forma canónica con los AssetID
ordenados y se resume con SHA-256, de modo que el orden de entrada no importa, dos composiciones
distintas dan hashes distintos y el resultado es estable entre procesos y ejecuciones (nunca se usa
``hash()`` de Python, aleatorizado). Es el ``CompositionID`` que usa la frontera continua del
Bloque 2 para la misma composición.

El hash **no basta** como clave de una caché de resultados: la clave completa (escenario,
restricciones, versión de ``mu``/``Sigma``, costes, configuración de frontera, marca temporal de
mercado y ``CurrentPortfolioStateHash``, §31) pertenece al Bloque 5; en el Bloque 3 el hash solo
identifica y deduplica composiciones dentro de una misma ejecución.
"""

from __future__ import annotations

from collections.abc import Iterable

from portfolio_engine.exceptions import CandidateError
from portfolio_engine.models.portfolio import composition_hash


def composition_hash_of(asset_ids: Iterable[str]) -> str:
    """``CompositionHash`` de ``asset_ids`` (cualquier orden; los duplicados son un error)."""
    ids = list(asset_ids)
    if not ids:
        raise CandidateError("Una composición no puede estar vacía.")
    unique = frozenset(ids)
    if len(unique) != len(ids):
        raise CandidateError(f"La composición contiene AssetID repetidos: {sorted(ids)}")
    return composition_hash(unique)
