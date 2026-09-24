"""``EligibilityFilter``: qué activos pueden mantenerse, comprarse o deben salir (MASTER_SPEC §12).

Requisitos: CAN-013, CON-013, CON-022 (traducción de la política en la búsqueda), CON-012 (solo
``LiquidityFlag``; la restricción de participación en ADV/NAV no está implementada).

Clasifica cada activo del modelo de riesgo respecto a **una cartera** en seis roles (vectorizado
con máscaras booleanas sobre el índice global):

===================  =====================================================================
``ELIGIBLE_NEW``     (B) no está en cartera y puede comprarse
``HELD``             (A) está en cartera y puede seguir o venderse (y también comprarse)
``LIQUIDATE_ONLY``   (D) está en cartera y puede seguir o venderse, pero no comprarse
``MANDATORY_HOLD``   (C) restringido con ``FREEZE_WEIGHT``: no puede desaparecer
``MANDATORY_EXIT``   restringido con ``FORCE_LIQUIDATE``: debe liquidarse
``EXCLUDED``         (E) fuera por completo (no está en cartera y no puede comprarse)
===================  =====================================================================

Un activo puede comprarse si ``EligibleFlag`` y ``LiquidityFlag`` lo permiten, no es restringido
(un restringido nunca se incorpora ni incrementa, E-09) y pertenece al ``InvestmentUniverse`` de la
cartera (si lo define). Un activo actual no elegible **no** se liquida automáticamente: puede
conservarse. Las banderas desconocidas siguen una política explícita (``unknown_liquidity_policy``;
un ``RestrictedAssetFlag`` desconocido excluye la compra, coherente con el compilador de
restricciones que rechaza ese caso). La política de restringidos ya en cartera procede de la
configuración (``resolve_restricted_policy``) y nunca se fija aquí.

E-10 (existing non-buyable position policy): un activo ``LIQUIDATE_ONLY`` puede mantenerse o
reducirse, nunca incrementarse: ``0 <= w <= min(w_current, MaxWeight)``. El filtro clasifica; el
``ConstraintCompiler`` traduce el estado en cotas (``models.purchasability`` es la definición
única del predicado) y el ``SolutionValidator`` lo comprueba desde ``w_current``. Un restringido
conserva su propia política (E-09), igual o más estricta.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from portfolio_engine.candidates.universe_data import UniverseSnapshot
from portfolio_engine.config.candidate_config import CandidateConfig
from portfolio_engine.config.constraint_config import ConstraintConfig
from portfolio_engine.exceptions import AssetResolutionError, CandidateError
from portfolio_engine.models.enums import (
    EligibilityReason,
    EligibilityStatus,
    RestrictedExistingPositionPolicy,
    UnknownFlagPolicy,
)
from portfolio_engine.models.portfolio import (
    CurrentPortfolioState,
    PortfolioSpec,
    resolve_restricted_policy,
)
from portfolio_engine.models.universe_index import EligibleUniverseIndex

#: Estados cuyos activos pueden formar parte de una composición candidata.
ENTERABLE_STATUSES = frozenset(
    {
        EligibilityStatus.HELD,
        EligibilityStatus.MANDATORY_HOLD,
        EligibilityStatus.LIQUIDATE_ONLY,
        EligibilityStatus.ELIGIBLE_NEW,
    }
)


@dataclass(frozen=True, eq=False, slots=True)
class EligibilityResult:
    """Clasificación de todos los activos del modelo de riesgo para una cartera.

    Attributes:
        status: rol de cada activo (índice global).
        reasons: causas explícitas por activo (vacío si no hay ninguna restricción aplicable).
        held_positions: posiciones globales de la cartera actual (ascendentes).
        purchasable: máscara global de activos que pueden comprarse.
        enterable: universo elegible de la cartera: activos que pueden estar en una composición.
        mandatory_hold: posiciones globales que no pueden salir (``FREEZE_WEIGHT``).
        mandatory_exit: posiciones globales que deben liquidarse (``FORCE_LIQUIDATE``).
        weight_cap: tope de peso de cada activo (posición global) cuando volver a añadirlo a una
            composición no puede superar lo que ya tiene (E-10): ``w_current`` para los activos
            ``LIQUIDATE_ONLY`` y ``inf`` para el resto. El screening lo usa para no suponer un peso
            de entrada ``1/T`` que el compilador no permitiría.
        restricted_policy: política efectiva de restringidos (``None`` si no aplica).
        universe_only_ids: activos del universo sin datos de riesgo (``NO_RISK_MODEL_DATA``).
    """

    status: tuple[EligibilityStatus, ...]
    reasons: tuple[tuple[EligibilityReason, ...], ...]
    held_positions: npt.NDArray[np.int64]
    purchasable: npt.NDArray[np.bool_]
    enterable: EligibleUniverseIndex
    mandatory_hold: frozenset[int]
    mandatory_exit: frozenset[int]
    weight_cap: npt.NDArray[np.float64]
    restricted_policy: RestrictedExistingPositionPolicy | None
    universe_only_ids: tuple[str, ...]

    def counts(self) -> tuple[tuple[str, int], ...]:
        """Número de activos por estado (orden estable de :class:`EligibilityStatus`)."""
        return tuple(
            (status.value, sum(1 for item in self.status if item is status))
            for status in EligibilityStatus
        )

    def positions_with(self, status: EligibilityStatus) -> npt.NDArray[np.int64]:
        """Posiciones globales con el estado indicado."""
        return np.array(
            [position for position, item in enumerate(self.status) if item is status],
            dtype=np.int64,
        )


class EligibilityFilter:
    """Aplica ``EligibleFlag``, ``LiquidityFlag``, restricciones e ``InvestmentUniverse``."""

    def __init__(self, candidates: CandidateConfig, constraints: ConstraintConfig) -> None:
        self._candidates = candidates
        self._constraints = constraints

    def apply(
        self,
        snapshot: UniverseSnapshot,
        state: CurrentPortfolioState,
        spec: PortfolioSpec | None,
    ) -> EligibilityResult:
        """Clasifica el universo de ``snapshot`` respecto a la cartera ``state``."""
        held = self._held_mask(snapshot, state)
        restricted_true = snapshot.restricted_known & snapshot.restricted
        held_restricted = held & restricted_true
        policy = resolve_restricted_policy(
            spec, self._constraints.restricted_existing_position_policy
        )
        if held_restricted.any() and policy is None:
            names = [snapshot.index.asset_id_at(int(p)) for p in np.flatnonzero(held_restricted)]
            raise CandidateError(
                f"Activos restringidos en cartera sin RestrictedExistingPositionPolicy: {names}"
            )
        liquidity_ok = self._liquidity_ok(snapshot)
        in_universe = self._investment_universe_mask(snapshot, spec)
        purchasable = (
            snapshot.eligible_flag
            & liquidity_ok
            & in_universe
            & ~restricted_true
            & (snapshot.restricted_known | held)
        )
        freeze = held_restricted & (policy is RestrictedExistingPositionPolicy.FREEZE_WEIGHT)
        force = held_restricted & (policy is RestrictedExistingPositionPolicy.FORCE_LIQUIDATE)
        status = self._status(held, purchasable, freeze, force)
        weight_cap = self._weight_cap(snapshot, state, status)
        reasons = self._reasons(
            snapshot, held, purchasable, liquidity_ok, in_universe, freeze, force
        )
        enterable = EligibleUniverseIndex(
            snapshot.index,
            [position for position, item in enumerate(status) if item in ENTERABLE_STATUSES],
        )
        return EligibilityResult(
            status=status,
            reasons=reasons,
            held_positions=np.flatnonzero(held).astype(np.int64),
            purchasable=purchasable,
            enterable=enterable,
            mandatory_hold=frozenset(int(p) for p in np.flatnonzero(freeze)),
            mandatory_exit=frozenset(int(p) for p in np.flatnonzero(force)),
            weight_cap=weight_cap,
            restricted_policy=policy,
            universe_only_ids=snapshot.universe_only_ids,
        )

    # ------------------------------------------------------------------------------ máscaras

    def _held_mask(
        self, snapshot: UniverseSnapshot, state: CurrentPortfolioState
    ) -> npt.NDArray[np.bool_]:
        try:
            positions = snapshot.index.indices_of(state.asset_ids)
        except AssetResolutionError as error:
            raise CandidateError(
                f"La cartera actual contiene activos sin datos en el modelo de riesgo: {error}"
            ) from error
        held = np.zeros(snapshot.size, dtype=np.bool_)
        held[positions] = True
        return held

    def _liquidity_ok(self, snapshot: UniverseSnapshot) -> npt.NDArray[np.bool_]:
        unknown = ~snapshot.liquidity_known
        policy = self._candidates.unknown_liquidity_policy
        if policy is UnknownFlagPolicy.ERROR and (unknown & snapshot.eligible_flag).any():
            names = [snapshot.index.asset_id_at(int(p)) for p in np.flatnonzero(unknown)]
            raise CandidateError(f"LiquidityFlag desconocido (política ERROR): {names}")
        allowed = snapshot.liquidity_ok | (unknown & (policy is UnknownFlagPolicy.ALLOW))
        return np.asarray(allowed, dtype=np.bool_)

    def _investment_universe_mask(
        self, snapshot: UniverseSnapshot, spec: PortfolioSpec | None
    ) -> npt.NDArray[np.bool_]:
        if spec is None or spec.investment_universe is None:
            return np.ones(snapshot.size, dtype=np.bool_)
        mask = np.zeros(snapshot.size, dtype=np.bool_)
        known = [asset_id for asset_id in spec.investment_universe if asset_id in snapshot.index]
        mask[snapshot.index.indices_of(known)] = True
        return mask

    def _weight_cap(
        self,
        snapshot: UniverseSnapshot,
        state: CurrentPortfolioState,
        status: tuple[EligibilityStatus, ...],
    ) -> npt.NDArray[np.float64]:
        """Tope ``w_current`` de los activos ``LIQUIDATE_ONLY`` (E-10) e ``inf`` para el resto."""
        cap = np.full(snapshot.size, np.inf, dtype=np.float64)
        if state.asset_ids:
            positions = snapshot.index.indices_of(state.asset_ids)
            capped = np.array(
                [
                    status[int(position)] is EligibilityStatus.LIQUIDATE_ONLY
                    for position in positions
                ],
                dtype=np.bool_,
            )
            cap[positions[capped]] = state.weights[capped]
        return cap

    def _status(
        self,
        held: npt.NDArray[np.bool_],
        purchasable: npt.NDArray[np.bool_],
        freeze: npt.NDArray[np.bool_],
        force: npt.NDArray[np.bool_],
    ) -> tuple[EligibilityStatus, ...]:
        statuses: list[EligibilityStatus] = []
        for position in range(held.shape[0]):
            if force[position]:
                statuses.append(EligibilityStatus.MANDATORY_EXIT)
            elif freeze[position]:
                statuses.append(EligibilityStatus.MANDATORY_HOLD)
            elif held[position]:
                statuses.append(
                    EligibilityStatus.HELD
                    if purchasable[position]
                    else EligibilityStatus.LIQUIDATE_ONLY
                )
            else:
                statuses.append(
                    EligibilityStatus.ELIGIBLE_NEW
                    if purchasable[position]
                    else EligibilityStatus.EXCLUDED
                )
        return tuple(statuses)

    def _reasons(
        self,
        snapshot: UniverseSnapshot,
        held: npt.NDArray[np.bool_],
        purchasable: npt.NDArray[np.bool_],
        liquidity_ok: npt.NDArray[np.bool_],
        in_universe: npt.NDArray[np.bool_],
        freeze: npt.NDArray[np.bool_],
        force: npt.NDArray[np.bool_],
    ) -> tuple[tuple[EligibilityReason, ...], ...]:
        """Causas de cada activo que no puede comprarse (o está sujeto a la política)."""
        result: list[tuple[EligibilityReason, ...]] = []
        for position in range(snapshot.size):
            causes: list[EligibilityReason] = []
            if force[position]:
                causes.append(EligibilityReason.FORCE_LIQUIDATE)
            if freeze[position]:
                causes.append(EligibilityReason.FREEZE_WEIGHT)
            if not purchasable[position]:
                if not snapshot.eligible_flag[position]:
                    causes.append(EligibilityReason.NOT_ELIGIBLE)
                if not liquidity_ok[position]:
                    causes.append(
                        EligibilityReason.NOT_LIQUID
                        if snapshot.liquidity_known[position]
                        else EligibilityReason.UNKNOWN_LIQUIDITY_FLAG
                    )
                if snapshot.restricted_known[position] and snapshot.restricted[position]:
                    causes.append(EligibilityReason.RESTRICTED)
                if not snapshot.restricted_known[position] and not held[position]:
                    causes.append(EligibilityReason.UNKNOWN_RESTRICTED_FLAG)
                if not in_universe[position]:
                    causes.append(EligibilityReason.OUTSIDE_INVESTMENT_UNIVERSE)
            result.append(tuple(dict.fromkeys(causes)))
        return tuple(result)
