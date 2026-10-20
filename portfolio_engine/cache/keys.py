"""Clave canónica de la caché de resultados (MASTER_SPEC §31, §62; CCH-002, CCH-004).

Una clave identifica **todo** lo que determina un resultado: no se deduce de ``CompositionHash``
aislado. Contiene los componentes oficiales de CCH-002 —``CompositionHash``, ``ScenarioID``,
``ScenarioHash``, ``ConstraintHash``, ``MuSigmaVersion``, ``TransactionCostHash``,
``FrontierConfigHash``, ``ConfigHash`` (que incluye ``OptimizationHorizonYears``),
``MarketDataTimestamp`` y **``CurrentPortfolioStateHash`` siempre** (enmienda E-06)— más tres
componentes que exige la reutilización de resultados completos entre operaciones:

* ``portfolio_id``: los resultados llevan el ``PortfolioID`` en sus campos, de modo que dos carteras
  distintas nunca comparten entrada aunque coincidan en todo lo demás (conservador; evita servir un
  resultado etiquetado con otra cartera);
* ``operation_hash``: qué operación y con qué parámetros se calculó (estrategia, tratamiento de
  costes, método, aversión al riesgo…);
* ``snapshot_key``: huella de contenido de los datos de mercado completos (universo, costes,
  escenarios y retornos), que cubre lo que ``MuSigmaVersion`` no cubre.

Este módulo es de bajo nivel (solo depende de ``utils``): quien conoce las solicitudes y los datos
de mercado construye los componentes (véase ``parallel.operation_cache``).
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from portfolio_engine.exceptions import PortfolioEngineError
from portfolio_engine.utils.hashing import canonical_json, sha256_hex

#: Valor explícito de «no informado» (la ausencia forma parte de la identidad, nunca se omite).
UNSPECIFIED = "UNSPECIFIED"


class CacheKeyError(PortfolioEngineError):
    """Componente de clave ausente o con tipo inválido."""


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Clave compuesta de la caché. Todos los componentes son obligatorios y no vacíos."""

    portfolio_id: str
    operation_hash: str
    composition_hash: str
    scenario_id: str
    scenario_hash: str
    constraint_hash: str
    mu_sigma_version: str
    transaction_cost_hash: str
    frontier_config_hash: str
    config_hash: str
    market_data_timestamp: str
    current_portfolio_state_hash: str
    snapshot_key: str

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, str) or not value:
                raise CacheKeyError(
                    f"Componente de clave '{field.name}' ausente o vacío (use {UNSPECIFIED!r} "
                    "si el dato no se informa)."
                )

    @property
    def components(self) -> tuple[tuple[str, str], ...]:
        """Pares ``(nombre, valor)`` de todos los componentes, en orden de declaración."""
        return tuple((field.name, getattr(self, field.name)) for field in fields(self))

    @property
    def digest(self) -> str:
        """SHA-256 canónico de la clave completa (identidad en la caché)."""
        return sha256_hex(canonical_json(dict(self.components)))


#: Componentes oficiales de CCH-002 (los demás son extensiones documentadas arriba).
OFFICIAL_COMPONENTS = (
    "composition_hash",
    "scenario_id",
    "scenario_hash",
    "constraint_hash",
    "mu_sigma_version",
    "transaction_cost_hash",
    "frontier_config_hash",
    "config_hash",
    "market_data_timestamp",
    "current_portfolio_state_hash",
)
