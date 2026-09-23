"""Informe de calidad de datos y registro de correcciones (MASTER_SPEC §10).

Ningún dato se corrige en silencio: toda corrección autorizada por configuración queda en el
``CorrectionLog`` del informe, y todo problema detectado queda como ``DataIssue``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from portfolio_engine.exceptions import DataValidationError
from portfolio_engine.models.enums import IssueSeverity

#: Errores citados en el mensaje de la excepción (presentación; el informe los contiene todos).
SUMMARY_ISSUES = 5


class IssueCode(StrEnum):
    """Códigos de problemas de calidad de datos."""

    SCHEMA = "SCHEMA"
    UNKNOWN_ASSET = "UNKNOWN_ASSET"
    INVALID_DATE = "INVALID_DATE"
    FUTURE_DATE = "FUTURE_DATE"
    DUPLICATE = "DUPLICATE"
    MISSING_PRICE = "MISSING_PRICE"
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    MISSING_OBSERVATION = "MISSING_OBSERVATION"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STALE_PRICE = "STALE_PRICE"
    OUTLIER = "OUTLIER"
    CALENDAR_GAP = "CALENDAR_GAP"
    INVALID_OPTIONAL_FIELD = "INVALID_OPTIONAL_FIELD"
    MISSING_METADATA = "MISSING_METADATA"
    MISSING_RECOMMENDED_METADATA = "MISSING_RECOMMENDED_METADATA"
    AMBIGUOUS_TICKER = "AMBIGUOUS_TICKER"
    INCOMPATIBLE_LIMITS = "INCOMPATIBLE_LIMITS"
    INVALID_VALUE = "INVALID_VALUE"
    RESTRICTED_STATUS_UNKNOWN = "RESTRICTED_STATUS_UNKNOWN"
    MISSING_WEIGHT = "MISSING_WEIGHT"
    NEGATIVE_WEIGHT = "NEGATIVE_WEIGHT"
    ZERO_WEIGHT_IGNORED = "ZERO_WEIGHT_IGNORED"
    INCONSISTENT_WEIGHTS = "INCONSISTENT_WEIGHTS"
    RESTRICTED_POLICY_REQUIRED = "RESTRICTED_POLICY_REQUIRED"
    HELD_OUTSIDE_INVESTMENT_UNIVERSE = "HELD_OUTSIDE_INVESTMENT_UNIVERSE"
    INVALID_PORTFOLIO_SPEC = "INVALID_PORTFOLIO_SPEC"
    NO_VALID_ASSETS = "NO_VALID_ASSETS"


@dataclass(frozen=True, slots=True)
class DataIssue:
    """Problema de calidad de datos detectado (nunca corregido implícitamente)."""

    code: IssueCode
    severity: IssueSeverity
    message: str
    asset_id: str | None = None
    portfolio_id: str | None = None


@dataclass(frozen=True, slots=True)
class Correction:
    """Corrección aplicada porque la configuración la autoriza explícitamente."""

    action: str
    target: str
    reason: str
    policy: str


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """Resultado inmutable de una validación: problemas y correcciones registradas."""

    issues: tuple[DataIssue, ...] = ()
    corrections: tuple[Correction, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[DataIssue, ...]:
        """Problemas de severidad ``ERROR``."""
        return tuple(i for i in self.issues if i.severity is IssueSeverity.ERROR)

    @property
    def warnings(self) -> tuple[DataIssue, ...]:
        """Problemas de severidad ``WARNING``."""
        return tuple(i for i in self.issues if i.severity is IssueSeverity.WARNING)

    @property
    def has_errors(self) -> bool:
        """``True`` si existe al menos un error."""
        return bool(self.errors)

    def codes(self) -> frozenset[IssueCode]:
        """Conjunto de códigos presentes."""
        return frozenset(issue.code for issue in self.issues)

    def issues_for(self, code: IssueCode) -> tuple[DataIssue, ...]:
        """Problemas con el código ``code``."""
        return tuple(issue for issue in self.issues if issue.code is code)

    def raise_if_errors(self, context: str) -> None:
        """Lanza :class:`DataValidationError` con todos los problemas si hay errores."""
        if self.has_errors:
            summary = "; ".join(f"{i.code}: {i.message}" for i in self.errors[:SUMMARY_ISSUES])
            raise DataValidationError(
                f"{context}: {len(self.errors)} error(es) de datos. {summary}", self.issues
            )


class IssueCollector:
    """Acumulador local (mutable) usado durante una validación; produce un informe inmutable."""

    __slots__ = ("_corrections", "_issues")

    def __init__(self) -> None:
        self._issues: list[DataIssue] = []
        self._corrections: list[Correction] = []

    def add(
        self,
        code: IssueCode,
        severity: IssueSeverity,
        message: str,
        *,
        asset_id: str | None = None,
        portfolio_id: str | None = None,
    ) -> None:
        """Registra un problema."""
        self._issues.append(DataIssue(code, severity, message, asset_id, portfolio_id))

    def error(self, code: IssueCode, message: str, **keys: str | None) -> None:
        """Registra un problema de severidad ``ERROR``."""
        self.add(code, IssueSeverity.ERROR, message, **keys)

    def warning(self, code: IssueCode, message: str, **keys: str | None) -> None:
        """Registra un problema de severidad ``WARNING``."""
        self.add(code, IssueSeverity.WARNING, message, **keys)

    def correct(self, action: str, target: str, reason: str, policy: str) -> None:
        """Registra una corrección autorizada por configuración."""
        self._corrections.append(Correction(action, target, reason, policy))

    def report(self) -> DataQualityReport:
        """Informe inmutable con lo acumulado."""
        return DataQualityReport(tuple(self._issues), tuple(self._corrections))
