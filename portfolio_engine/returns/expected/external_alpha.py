"""Expected returns a partir de alpha externo (MASTER_SPEC §8)."""

from __future__ import annotations

from collections.abc import Sequence

from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.enums import ExpectedReturnMode
from portfolio_engine.models.market_data import ReturnsMatrix
from portfolio_engine.models.risk_model import (
    EXTERNAL_ALPHA_METHOD,
    ExpectedReturns,
    ExternalAlpha,
)


class ExternalAlphaProvider:
    """Devuelve el alpha externo anualizado; exige cobertura completa (nunca rellena ceros)."""

    def __init__(self, alpha: ExternalAlpha) -> None:
        self._alpha = alpha

    @property
    def mode(self) -> ExpectedReturnMode:
        """Siempre ``EXTERNAL_ALPHA``."""
        return ExpectedReturnMode.EXTERNAL_ALPHA

    def estimate(self, asset_ids: Sequence[str], returns: ReturnsMatrix | None) -> ExpectedReturns:
        """Alpha anualizado de ``asset_ids``; ``returns`` no se utiliza."""
        positions = {asset_id: i for i, asset_id in enumerate(self._alpha.asset_ids)}
        missing = [asset_id for asset_id in asset_ids if asset_id not in positions]
        if missing:
            raise DataValidationError(f"Activos sin alpha externo: {missing}")
        values = self._alpha.annualized_values[[positions[a] for a in asset_ids]]
        return ExpectedReturns(
            asset_ids=tuple(asset_ids),
            values=values,
            mode=self.mode,
            method=EXTERNAL_ALPHA_METHOD,
        )
