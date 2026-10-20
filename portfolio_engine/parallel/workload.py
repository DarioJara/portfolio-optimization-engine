"""``WorkloadSpec``: qué operaciones ejecuta una cartera (decisión D-01; requisito propuesto P-09).

Cada cartera lleva su propio workload: una estrategia individual o un pipeline compuesto de
operaciones **ya implementadas** (catálogo cerrado :class:`OperationKind`). No se asume que todas
las carteras ejecuten todas las estrategias. Este módulo solo describe y valida el workload (datos
puros, serializables y con hash canónico); la ejecución está en
:mod:`portfolio_engine.parallel.task`.

Catálogo (clases de coste W0-W5 de ``BLOCK_5_BENCHMARK_PLAN.md``):

========================  =====  ==============================================================
Operación                 Clase  Motor existente
========================  =====  ==============================================================
FRONTIER_FIXED_COMPOSITION  W0   ``ContinuousFrontierEngine.solve``
GLOBAL_FRONTIER             W1   ``GlobalCandidateFrontierEngine.solve`` (incluye la búsqueda
                                 de candidatos: el motor la ejecuta internamente)
MULTI_SCENARIO              W2   ``ScenarioEngine.build`` + ``MultiScenarioOptimizer.solve_*``
STRATEGY_CVAR               W3   ``StrategyOptimizer.cvar``
STRATEGY_ROBUST             W4   ``StrategyOptimizer.robust``
STRATEGY_MAX_SHARPE         W4   ``StrategyOptimizer.max_sharpe``
STRATEGY_VOL_TARGET         W4   ``StrategyOptimizer.volatility_target``
EXACT_MIP_VALIDATION        W5   ``ExactMIPValidator.validate_heuristic``
========================  =====  ==============================================================

Capacidad pendiente: ``STRATEGY_ROBUST`` no admite un ``mu_set`` explícito (``MuUncertaintySet``
con arrays por activo de una composición); solo ``covariance_scale_max`` o el conjunto derivado de
``[robust]``. Un mandato con alpha externo y ``[robust].mu_uncertainty`` distinto de ``NONE`` falla
con ``UnsupportedCombinationError`` (``FAILED_EXCEPTION``). Exponerlo exige una especificación
serializable de la incertidumbre (B5.3/B5.4); el motor robusto de B4 no se modifica.

Diferencia respecto del borrador de diseño (``BLOCK_5_HPC_ARCHITECTURE.md`` §14.3): la búsqueda de
candidatos y la construcción de escenarios no son operaciones separadas, porque los motores las
ejecutan internamente; separarlas obligaría a ejecutarlas dos veces o a modificar B3-B4.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType

from portfolio_engine.models.enums import (
    CostTreatment,
    CVaRObjective,
    FrontierMethod,
    FrontierScope,
    MultiScenarioMode,
)
from portfolio_engine.utils.hashing import canonical_json, sha256_hex

#: Versión del esquema del workload (entra en el hash: cambiar el contrato cambia la identidad).
WORKLOAD_SCHEMA_VERSION = 1


class OperationKind(StrEnum):
    """Operaciones del catálogo cerrado (cada una compone un motor existente)."""

    FRONTIER_FIXED_COMPOSITION = "FRONTIER_FIXED_COMPOSITION"
    GLOBAL_FRONTIER = "GLOBAL_FRONTIER"
    MULTI_SCENARIO = "MULTI_SCENARIO"
    STRATEGY_CVAR = "STRATEGY_CVAR"
    STRATEGY_ROBUST = "STRATEGY_ROBUST"
    STRATEGY_MAX_SHARPE = "STRATEGY_MAX_SHARPE"
    STRATEGY_VOL_TARGET = "STRATEGY_VOL_TARGET"
    EXACT_MIP_VALIDATION = "EXACT_MIP_VALIDATION"


#: Clase de coste (W0-W5) de cada operación, para informes y mezclas de benchmark.
WORKLOAD_CLASS: Mapping[OperationKind, str] = MappingProxyType(
    {
        OperationKind.FRONTIER_FIXED_COMPOSITION: "W0",
        OperationKind.GLOBAL_FRONTIER: "W1",
        OperationKind.MULTI_SCENARIO: "W2",
        OperationKind.STRATEGY_CVAR: "W3",
        OperationKind.STRATEGY_ROBUST: "W4",
        OperationKind.STRATEGY_MAX_SHARPE: "W4",
        OperationKind.STRATEGY_VOL_TARGET: "W4",
        OperationKind.EXACT_MIP_VALIDATION: "W5",
    }
)

_FRONTIER_KINDS = frozenset(
    {OperationKind.FRONTIER_FIXED_COMPOSITION, OperationKind.GLOBAL_FRONTIER}
)
_SINGLE_SOLUTION_MODES = frozenset(
    {
        MultiScenarioMode.EXPECTED_SCENARIO_UTILITY,
        MultiScenarioMode.WORST_CASE,
        MultiScenarioMode.BASE_WITH_STRESS_CONSTRAINTS,
    }
)


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Una operación del workload con sus parámetros (``None`` = no aplica / no configurado).

    Los parámetros que cada operación exige o prohíbe se comprueban en
    :meth:`WorkloadSpec.problems`; una combinación inválida nunca llega a ejecutarse.
    """

    kind: OperationKind
    treatment: CostTreatment
    method: FrontierMethod | None = None
    mode: MultiScenarioMode | None = None
    scope: FrontierScope | None = None
    include_max_sharpe: bool = False
    risk_aversion: float | None = None
    cvar_objective: CVaRObjective | None = None
    max_cvar: float | None = None
    volatility_limit: float | None = None
    covariance_scale_max: float | None = None

    @property
    def workload_class(self) -> str:
        """Clase de coste W0-W5."""
        return WORKLOAD_CLASS[self.kind]


#: Parámetros de ``OperationSpec`` que cada operación **exige** y **admite** (el resto, prohibidos).
_REQUIRED: Mapping[OperationKind, frozenset[str]] = MappingProxyType(
    {
        OperationKind.FRONTIER_FIXED_COMPOSITION: frozenset({"method"}),
        OperationKind.GLOBAL_FRONTIER: frozenset({"method"}),
        OperationKind.MULTI_SCENARIO: frozenset({"mode"}),
        OperationKind.STRATEGY_CVAR: frozenset({"cvar_objective"}),
        OperationKind.STRATEGY_ROBUST: frozenset({"risk_aversion"}),
        OperationKind.STRATEGY_MAX_SHARPE: frozenset(),
        OperationKind.STRATEGY_VOL_TARGET: frozenset(),
        OperationKind.EXACT_MIP_VALIDATION: frozenset({"risk_aversion"}),
    }
)
_OPTIONAL: Mapping[OperationKind, frozenset[str]] = MappingProxyType(
    {
        OperationKind.FRONTIER_FIXED_COMPOSITION: frozenset(),
        OperationKind.GLOBAL_FRONTIER: frozenset(),
        OperationKind.MULTI_SCENARIO: frozenset(
            {"method", "scope", "include_max_sharpe", "risk_aversion"}
        ),
        OperationKind.STRATEGY_CVAR: frozenset({"max_cvar", "risk_aversion", "volatility_limit"}),
        OperationKind.STRATEGY_ROBUST: frozenset({"covariance_scale_max"}),
        OperationKind.STRATEGY_MAX_SHARPE: frozenset({"volatility_limit"}),
        OperationKind.STRATEGY_VOL_TARGET: frozenset({"volatility_limit", "risk_aversion"}),
        OperationKind.EXACT_MIP_VALIDATION: frozenset({"volatility_limit"}),
    }
)
_PARAMETERS = (
    "method",
    "mode",
    "scope",
    "include_max_sharpe",
    "risk_aversion",
    "cvar_objective",
    "max_cvar",
    "volatility_limit",
    "covariance_scale_max",
)


def _provided(operation: OperationSpec, name: str) -> bool:
    value = getattr(operation, name)
    return bool(value) if name == "include_max_sharpe" else value is not None


def _operation_problems(position: int, operation: OperationSpec) -> list[str]:
    label = f"operations[{position}] ({operation.kind.value})"
    required = set(_REQUIRED[operation.kind])
    allowed = required | _OPTIONAL[operation.kind]
    problems: list[str] = []
    if operation.kind is OperationKind.MULTI_SCENARIO and operation.mode is not None:
        if operation.mode is MultiScenarioMode.SCENARIO_INDEPENDENT:
            required |= {"method", "scope"}
        elif operation.mode in _SINGLE_SOLUTION_MODES:
            required.add("risk_aversion")
            allowed -= {"method", "scope", "include_max_sharpe"}
    for name in _PARAMETERS:
        provided = _provided(operation, name)
        if name in required and not provided:
            problems.append(f"{label}: falta el parámetro obligatorio '{name}'.")
        elif provided and name not in allowed:
            problems.append(f"{label}: el parámetro '{name}' no aplica a esta operación.")
    for name in ("risk_aversion", "max_cvar", "volatility_limit", "covariance_scale_max"):
        value = getattr(operation, name)
        if value is not None and (not math.isfinite(value) or value <= 0.0):
            problems.append(f"{label}: '{name}' debe ser finito y > 0.")
    return problems


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    """Lista ordenada de operaciones que ejecuta una cartera (todas en el mismo worker)."""

    operations: tuple[OperationSpec, ...]
    schema_version: int = WORKLOAD_SCHEMA_VERSION

    def problems(self) -> tuple[str, ...]:
        """Problemas de validez del workload (vacío si es válido). No lanza excepciones."""
        found: list[str] = []
        if self.schema_version != WORKLOAD_SCHEMA_VERSION:
            found.append(
                f"schema_version {self.schema_version} no soportada "
                f"(esperada {WORKLOAD_SCHEMA_VERSION})."
            )
        if not self.operations:
            found.append("El workload no contiene ninguna operación.")
        for position, operation in enumerate(self.operations):
            found.extend(_operation_problems(position, operation))
        for position, operation in enumerate(self.operations):
            if operation.kind is OperationKind.EXACT_MIP_VALIDATION and not any(
                earlier.kind is OperationKind.GLOBAL_FRONTIER
                for earlier in self.operations[:position]
            ):
                found.append(
                    f"operations[{position}] (EXACT_MIP_VALIDATION): requiere una operación "
                    "GLOBAL_FRONTIER anterior (usa sus composiciones candidatas)."
                )
        return tuple(found)

    @property
    def classes(self) -> frozenset[str]:
        """Clases de coste W0-W5 presentes."""
        return frozenset(operation.workload_class for operation in self.operations)

    def requires_return_scenarios(self) -> bool:
        """``True`` si alguna operación necesita escenarios de retorno (CVaR)."""
        return any(op.kind is OperationKind.STRATEGY_CVAR for op in self.operations)

    def requires_scenario_definitions(self) -> bool:
        """``True`` si alguna operación necesita definiciones de escenario (multiescenario)."""
        return any(op.kind is OperationKind.MULTI_SCENARIO for op in self.operations)

    @property
    def workload_hash(self) -> str:
        """SHA-256 canónico del workload (parte de la identidad ``TaskID``)."""
        payload = {
            "schema_version": self.schema_version,
            "operations": [asdict(operation) for operation in self.operations],
        }
        return sha256_hex(canonical_json(payload))
