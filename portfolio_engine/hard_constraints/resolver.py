"""Resolución de la configuración efectiva con precedencia documentada (HC-005).

Precedencia (de menor a mayor prioridad de *especificidad*)::

    1. Global      [hard_constraints]  +  campos globales del motor que ya existían
                   (candidates.max_new_assets / max_swaps, constraints.global_min/max_weight,
                    frontier.min_holding_weight, frontier.zero_weight_tolerance)
    2. Perfil      [hard_constraints.profiles.<perfil>]            (perfil de riesgo / mandato)
    3. Cartera     [hard_constraints.portfolios.<id>]  +  PortfolioSpec (VolatilityLimit,
                   TargetPortfolioSize, weight_bound_overrides)

Regla de endurecimiento: un nivel posterior solo puede **endurecer** un límite obligatorio del
anterior (bajar un máximo, subir un mínimo). Relajarlo —o contradecirlo con un override por
activo— exige una ``RelaxationAuthorization`` (``config.hard_constraints_config``) del campo,
en el mismo nivel, con responsable, motivo y referencia; sin ella es un ``ConfigError``.
Las autorizaciones aplicadas se conservan en :class:`EffectiveHardConstraints` y en su hash.

El resultado (:class:`EffectiveHardConstraints`) es la única fuente de verdad de la cartera: lo
consumen el generador de candidatos, la factibilidad previa y la validación final. Guarda el valor
efectivo de cada parámetro, su procedencia, las autorizaciones aplicadas, el ``ConfigHash`` del
motor y su propio hash (``effective_hash``).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping

from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.config.hard_constraints_config import (
    FIELD_SENSE,
    TOLERANCE_CEILING,
    HardConstraintsConfig,
    MandateLevel,
    MandateSettings,
    RelaxationAuthorization,
)
from portfolio_engine.config.hashing import config_hash
from portfolio_engine.exceptions import ConfigError
from portfolio_engine.hard_constraints.counts import positions_of
from portfolio_engine.models.enums import CardinalityPolicy
from portfolio_engine.models.hard_constraints import (
    AppliedRelaxation,
    AssetWeightException,
    EffectiveHardConstraints,
)
from portfolio_engine.models.portfolio import PortfolioSpec
from portfolio_engine.utils.hashing import canonical_json, sha256_hex

SOURCE_GLOBAL = "GLOBAL"
SOURCE_ENGINE = "ENGINE_CONFIG"
SOURCE_PROFILE = "PROFILE"
SOURCE_PORTFOLIO = "PORTFOLIO"
SOURCE_SPEC = "PORTFOLIO_SPEC"

# (campo del mandato, sección.clave del motor, sentido): integración de los campos que ya existían.
_ENGINE_ITEMS = (
    ("max_added_assets", "candidates.max_new_assets", "MAX"),
    ("max_swaps", "candidates.max_swaps", "MAX"),
    ("min_active_weight", "constraints.global_min_weight", "MIN"),
    ("min_active_weight", "frontier.min_holding_weight", "MIN"),
    ("max_active_weight", "constraints.global_max_weight", "MAX"),
)


class _Accumulator:
    """Valores efectivos por campo con su procedencia y las autorizaciones aplicadas."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.source: dict[str, str] = {}
        self.applied: list[RelaxationAuthorization] = []

    def tighten_or_set(self, field: str, value: object, source: str, sense: str) -> None:
        """Combina un valor de un nivel que **no** puede relajar (global): se queda el más duro."""
        current = self.values.get(field)
        if current is None or _tighter(sense, value, current):
            self.values[field] = value
            self.source[field] = source
        elif current is not None and not _same(value, current):
            self.source[field] = f"{self.source[field]}+{source}"

    def override(
        self,
        field: str,
        value: object,
        source: str,
        level_name: str,
        authorizations: Mapping[str, RelaxationAuthorization],
    ) -> None:
        """Aplica el valor de un nivel posterior, exigiendo autorización si relaja."""
        current = self.values.get(field)
        sense = FIELD_SENSE.get(field, "FREE")
        if current is not None and _relaxes(sense, current, value):
            authorization = authorizations.get(field)
            if authorization is None:
                raise ConfigError(
                    f"MANDATE_RELAXATION_NOT_AUTHORIZED: {source} {level_name!r} relaja "
                    f"{field} de {current!r} ({self.source[field]}) a {value!r} sin una "
                    "RelaxationAuthorization explícita."
                )
            self.applied.append(authorization)
        self.values[field] = value
        self.source[field] = f"{source}:{level_name}"


def _same(first: object, second: object) -> bool:
    return bool(first == second)


def _tighter(sense: str, new: object, old: object) -> bool:
    if sense == "MAX":
        return float(new) < float(old)  # type: ignore[arg-type]
    if sense == "MIN":
        return float(new) > float(old)  # type: ignore[arg-type]
    return False


def _relaxes(sense: str, old: object, new: object) -> bool:
    """``True`` si pasar de ``old`` a ``new`` hace el límite menos estricto."""
    if sense == "MAX":
        return float(new) > float(old)  # type: ignore[arg-type]
    if sense == "MIN":
        return float(new) < float(old)  # type: ignore[arg-type]
    if sense == "EXACT":
        return new != old
    if sense == "FLAG_TRUE":
        return bool(old) and not bool(new)
    if sense == "POLICY":
        return new is not CardinalityPolicy.FIXED and new != old
    return False


def _engine_value(config: EngineConfig, path: str) -> object | None:
    section, key = path.split(".")
    value: object = getattr(getattr(config, section), key)
    if path == "constraints.global_min_weight" and isinstance(value, float) and value <= 0:
        return None  # un mínimo global nulo no impone posición mínima
    return value


def _authorizations(level: MandateLevel | None) -> dict[str, RelaxationAuthorization]:
    return {} if level is None else {a.field: a for a in level.relaxations}


def _apply_settings(
    acc: _Accumulator,
    settings: MandateSettings,
    source: str,
    level_name: str,
    authorizations: Mapping[str, RelaxationAuthorization],
) -> None:
    for field, value in settings.set_fields().items():
        acc.override(field, value, source, level_name, authorizations)


def _apply_spec(
    acc: _Accumulator,
    spec: PortfolioSpec | None,
    authorizations: Mapping[str, RelaxationAuthorization],
) -> tuple[AssetWeightException, ...]:
    """Campos específicos de la cartera: ``VolatilityLimit``, tamaño objetivo y overrides."""
    exceptions: list[AssetWeightException] = []
    if spec is None:
        return ()
    if spec.volatility_limit is not None:
        acc.override(
            "max_volatility", spec.volatility_limit, SOURCE_SPEC, "volatility_limit", authorizations
        )
    if spec.target_portfolio_size is not None:
        acc.override(
            "target_size",
            spec.target_portfolio_size,
            SOURCE_SPEC,
            "target_portfolio_size",
            authorizations,
        )
    cap = acc.values.get("max_active_weight")
    floor = acc.values.get("min_active_weight")
    for asset_id, bounds in sorted(spec.weight_bound_overrides.items()):
        widens_max = (
            cap is not None and bounds.max_weight is not None and bounds.max_weight > float(cap)  # type: ignore[arg-type]
        )
        widens_min = (
            floor is not None
            and bounds.min_weight is not None
            and 0.0 < bounds.min_weight < float(floor)  # type: ignore[arg-type]
        )
        for field, relaxes in (
            ("max_active_weight", widens_max),
            ("min_active_weight", widens_min),
        ):
            if not relaxes:
                continue
            authorization = authorizations.get(field)
            if authorization is None:
                raise ConfigError(
                    f"MANDATE_RELAXATION_NOT_AUTHORIZED: el override de peso de {asset_id!r} "
                    f"({bounds.min_weight!r}, {bounds.max_weight!r}) relaja {field} "
                    f"({acc.values[field]!r}) sin una RelaxationAuthorization explícita."
                )
            if authorization not in acc.applied:
                acc.applied.append(authorization)
            exceptions.append(AssetWeightException(asset_id, bounds.min_weight, bounds.max_weight))
    return tuple(exceptions)


def _size_interval(
    policy: CardinalityPolicy,
    original: int,
    values: Mapping[str, object],
) -> tuple[int | None, int | None]:
    """Intervalo de tamaños que permite la política, antes de aplicar ``target_size``."""
    low: int | None
    high: int | None
    if policy is CardinalityPolicy.FIXED:
        low, high = (original, original) if original > 0 else (None, None)
    elif policy is CardinalityPolicy.INCREASE:
        increase = values.get("max_size_increase")
        low = original
        high = None if increase is None else original + int(increase)  # type: ignore[call-overload]
    else:
        decrease = values.get("max_size_decrease")
        high = original
        low = None if decrease is None else max(original - int(decrease), 1)  # type: ignore[call-overload]
    if values.get("min_size") is not None:
        floor = int(values["min_size"])  # type: ignore[call-overload]
        low = floor if low is None else max(low, floor)
    if values.get("max_size") is not None:
        ceiling = int(values["max_size"])  # type: ignore[call-overload]
        high = ceiling if high is None else min(high, ceiling)
    if policy is CardinalityPolicy.INCREASE and high is None:
        raise ConfigError(
            "cardinality_policy = INCREASE exige max_size_increase o max_size (sin límite no se "
            "puede acotar el aumento)."
        )
    if policy is CardinalityPolicy.DECREASE and low is None:
        raise ConfigError(
            "cardinality_policy = DECREASE exige max_size_decrease o min_size (sin límite no se "
            "puede acotar la reducción)."
        )
    return low, high


def _tolerance(
    values: Mapping[str, object], source: dict[str, str], field: str, fallback: float, origin: str
) -> float:
    configured = values.get(field)
    value = float(configured) if configured is not None else fallback  # type: ignore[arg-type]
    source.setdefault(field, origin if configured is None else f"{SOURCE_GLOBAL}")
    if not math.isfinite(value) or value < 0.0 or value > TOLERANCE_CEILING:
        raise ConfigError(
            f"Tolerancia {field} = {value!r} fuera de [0, {TOLERANCE_CEILING}]: una tolerancia "
            "numérica no puede ser lo bastante grande como para aceptar una violación material."
        )
    return value


def _accumulate(
    config: EngineConfig,
    hard: HardConstraintsConfig,
    portfolio_id: str,
    spec: PortfolioSpec | None,
    risk_profile: str | None,
) -> tuple[_Accumulator, str | None, tuple[AssetWeightException, ...]]:
    """Valores por campo tras aplicar global, perfil y cartera (con sus relajamientos)."""
    portfolio_level = hard.portfolio(portfolio_id)
    profile_name = risk_profile or (None if portfolio_level is None else portfolio_level.profile)
    profile_level = None if profile_name is None else hard.profile(profile_name)
    if profile_name is not None and profile_level is None:
        raise ConfigError(f"Perfil de riesgo desconocido en hard_constraints: {profile_name!r}.")
    acc = _Accumulator()
    # 1. Global: [hard_constraints] y los campos globales que el motor ya tenía.
    for field, value in hard.global_settings.set_fields().items():
        acc.values[field] = value
        acc.source[field] = SOURCE_GLOBAL
    for field, path, sense in _ENGINE_ITEMS:
        value = _engine_value(config, path)
        if value is not None:
            acc.tighten_or_set(field, value, f"{SOURCE_ENGINE}:{path}", sense)
    if "cardinality_policy" not in acc.values:
        # FIXED es la política efectiva por defecto y cuenta como límite global: un nivel posterior
        # no puede relajarla sin autorización.
        acc.values["cardinality_policy"] = CardinalityPolicy.FIXED
        acc.source["cardinality_policy"] = "DEFAULT_FIXED"
    # 2. Perfil y 3. Cartera (cada uno solo puede endurecer salvo autorización explícita).
    if profile_level is not None:
        _apply_settings(
            acc,
            profile_level.settings,
            SOURCE_PROFILE,
            profile_level.name,
            _authorizations(profile_level),
        )
    portfolio_auth = _authorizations(portfolio_level)
    if portfolio_level is not None:
        _apply_settings(
            acc, portfolio_level.settings, SOURCE_PORTFOLIO, portfolio_level.name, portfolio_auth
        )
    return acc, profile_name, _apply_spec(acc, spec, portfolio_auth)


def _position_threshold(config: EngineConfig, acc: _Accumulator) -> float:
    """Umbral único de «peso positivo» y comprobación de que el suelo por posición lo supera."""
    threshold = acc.values.get("position_weight_threshold")
    if threshold is None:
        threshold = config.frontier.zero_weight_tolerance
        acc.source["position_weight_threshold"] = f"{SOURCE_ENGINE}:frontier.zero_weight_tolerance"
    value = float(threshold)  # type: ignore[arg-type]
    floor = acc.values.get("min_active_weight")
    if floor is None:
        raise ConfigError(
            "hard_constraints exige un peso mínimo estrictamente positivo por posición "
            "(min_active_weight, constraints.global_min_weight o frontier.min_holding_weight): "
            "sin él el optimizador puede asignar peso nulo a un miembro de la composición y la "
            "cardinalidad real dejaría de ser la contada. No se simula eliminando pesos después."
        )
    if value >= float(floor):  # type: ignore[arg-type]
        raise ConfigError(
            f"position_weight_threshold ({value!r}) debe ser menor que el peso mínimo "
            f"por posición ({floor!r}): si no, una posición válida podría contarse como cero."
        )
    return value


def _tolerances(config: EngineConfig, acc: _Accumulator) -> dict[str, float]:
    """Tolerancias efectivas: las de ``[hard_constraints]`` o, en su defecto, las del solver."""
    solver = config.solver
    fallbacks = {
        "weight_tolerance": ("solver.bound_tolerance", solver.bound_tolerance),
        "budget_tolerance": ("solver.budget_tolerance", solver.budget_tolerance),
        "volatility_tolerance": ("solver.constraint_tolerance", solver.constraint_tolerance),
        "hhi_tolerance": ("solver.constraint_tolerance", solver.constraint_tolerance),
        "return_tolerance": ("solver.constraint_tolerance", solver.constraint_tolerance),
    }
    return {
        field: _tolerance(acc.values, acc.source, field, value, origin)
        for field, (origin, value) in fallbacks.items()
    }


def _require_declared_strategy(values: Mapping[str, object]) -> None:
    """Parámetros que no pueden tener valor implícito: tratamiento del retorno y búsqueda DC."""
    floor_configured = values.get("min_expected_return") is not None or bool(
        values.get("preserve_original_expected_return")
    )
    if floor_configured and values.get("expected_return_treatment") is None:
        raise ConfigError(
            "hard_constraints: un retorno esperado mínimo exige expected_return_treatment "
            "explícito (GROSS o NET); no hay valor implícito."
        )
    if values.get("min_volatility") is not None:
        missing = [
            name
            for name in ("band_max_starts", "band_max_iterations", "band_convergence_tolerance")
            if values.get(name) is None
        ]
        if missing:
            raise ConfigError(
                "hard_constraints: min_volatility hace el problema no convexo y exige declarar "
                f"explícitamente la estrategia de búsqueda: faltan {missing}."
            )


#: Campos que pasan tal cual del acumulador al mandato efectivo.
_PASSTHROUGH = (
    "target_size",
    "max_added_assets",
    "max_removed_assets",
    "max_total_changed_assets",
    "max_replacements",
    "max_pure_additions",
    "max_pure_removals",
    "max_swaps",
    "min_volatility",
    "max_volatility",
    "min_active_weight",
    "max_active_weight",
    "max_concentration_hhi",
    "min_effective_number_of_positions",
    "diversification_penalty_weight",
    "min_expected_return",
    "expected_return_treatment",
    "max_transaction_cost",
    "band_max_starts",
    "band_max_iterations",
    "band_convergence_tolerance",
)


def resolve_hard_constraints(
    config: EngineConfig,
    portfolio_id: str,
    spec: PortfolioSpec | None,
    current_weights: Mapping[str, float],
    *,
    risk_profile: str | None = None,
) -> EffectiveHardConstraints:
    """Restricciones obligatorias efectivas de ``portfolio_id`` (única fuente de verdad).

    ``current_weights`` son los pesos de la cartera original (``AssetID → peso``); el número de
    posiciones originales se cuenta con el umbral efectivo ``position_weight_threshold``.
    ``risk_profile`` sustituye al perfil declarado en el nivel de la cartera (si lo hay).
    """
    hard = config.hard_constraints
    if hard is None:
        raise ConfigError("EngineConfig.hard_constraints no está configurado.")
    acc, profile_name, exceptions = _accumulate(config, hard, portfolio_id, spec, risk_profile)
    values = acc.values
    threshold = _position_threshold(config, acc)
    tolerances = _tolerances(config, acc)
    _require_declared_strategy(values)
    original_size = len(positions_of(current_weights, threshold))
    policy = values["cardinality_policy"]
    assert isinstance(policy, CardinalityPolicy)
    size_min, size_max = _size_interval(policy, original_size, values)
    fields: dict[str, object] = {name: values.get(name) for name in _PASSTHROUGH}
    fields.update(
        portfolio_id=portfolio_id,
        risk_profile=profile_name,
        original_size=original_size,
        cardinality_policy=policy,
        size_min=size_min,
        size_max=size_max,
        preserve_original_expected_return=bool(values.get("preserve_original_expected_return")),
        position_weight_threshold=threshold,
        asset_exceptions=exceptions,
        relaxations=tuple(
            AppliedRelaxation(a.field, a.authorized_by, a.reason, a.reference) for a in acc.applied
        ),
        provenance=tuple(sorted(acc.source.items())),
        engine_config_hash=config_hash(config),
        **tolerances,
    )
    draft = EffectiveHardConstraints(effective_hash="", **fields)  # type: ignore[arg-type]
    digest = sha256_hex(canonical_json(draft.to_payload()))
    return dataclasses.replace(draft, effective_hash=digest)


def derive_engine_config(config: EngineConfig, effective: EffectiveHardConstraints) -> EngineConfig:
    """Copia de ``config`` con los campos del motor que ya existían alineados con el mandato.

    El compilador de restricciones, el ``CandidateEngine`` y los validadores B1–B4 leen
    ``frontier.min_holding_weight``, ``constraints.global_min/max_weight`` y
    ``candidates.max_new_assets`` / ``max_swaps``; derivarlos desde el mandato efectivo hace que
    todo el motor trabaje con **la misma** fuente de verdad sin tocar el código de los bloques ya
    validados. Es idempotente y conserva ``hard_constraints``. El ``ConfigHash`` de la copia cambia
    si cambia cualquier parámetro efectivo, de modo que cachés y diarios no pueden mezclar
    restricciones distintas.
    """
    constraints = config.constraints
    global_min = constraints.global_min_weight
    if global_min is not None and effective.min_active_weight is not None:
        global_min = min(global_min, effective.min_active_weight)
    global_max = (
        effective.max_active_weight
        if effective.max_active_weight is not None
        else constraints.global_max_weight
    )
    frontier = config.frontier
    if effective.min_active_weight is not None:
        frontier = dataclasses.replace(frontier, min_holding_weight=effective.min_active_weight)
    candidates = dataclasses.replace(
        config.candidates,
        max_new_assets=effective.max_added_assets,
        max_swaps=effective.max_swaps,
    )
    return dataclasses.replace(
        config,
        constraints=dataclasses.replace(
            constraints, global_min_weight=global_min, global_max_weight=global_max
        ),
        frontier=frontier,
        candidates=candidates,
    )
