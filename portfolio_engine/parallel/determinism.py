"""Semillas derivadas y orden estable de los resultados (MASTER_SPEC §61, §70).

* ``derive_seed``: semilla determinista por (semilla raíz, claves); nunca usa ``hash()`` de Python,
  que está aleatorizado entre procesos (PAR-009, REP-003).
* ``sequence_key``: clave de ordenación canónica ``(PortfolioID, ScenarioID, FrontierScope,
  CostTreatment, CompositionID, FrontierPointID)`` que da un ``SequenceID`` estable (PAR-010).
* ``tie_break_key``: desempate determinista por score, luego ``CompositionHash`` (PAR-010).
"""

from __future__ import annotations

import hashlib

from portfolio_engine.utils.hashing import canonical_json


def derive_seed(root_seed: int, *keys: str) -> int:
    """Semilla entera determinista derivada de ``root_seed`` y ``keys`` (SHA-256 canónico).

    Es estable entre procesos y ejecuciones y sensible a cada clave y a su orden.
    """
    payload = canonical_json({"root": root_seed, "keys": list(keys)}).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")


def sequence_key(
    portfolio_id: str,
    scenario_id: str,
    frontier_scope: str,
    cost_treatment: str,
    composition_id: str,
    frontier_point_id: str,
) -> tuple[str, str, str, str, str, str]:
    """Clave canónica de ordenación de un punto de frontera (base del ``SequenceID``)."""
    return (
        portfolio_id,
        scenario_id,
        frontier_scope,
        cost_treatment,
        composition_id,
        frontier_point_id,
    )


def tie_break_key(score: float, composition_hash: str) -> tuple[float, str]:
    """Clave para ordenar de mayor a menor ``score`` con desempate por ``CompositionHash``."""
    return (-score, composition_hash)
