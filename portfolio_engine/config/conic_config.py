"""Configuración del backend cónico (Clarabel) y de Max Sharpe (MASTER_SPEC §20-21, §48; CFG-008).

Todo parámetro numérico de las formulaciones cónicas (tolerancias de Clarabel, factorización PSD de
``Σ``) y de Max Sharpe procede de estas secciones; sus valores de ejemplo viven únicamente en
``config/default_engine.toml`` (decisión A-29).
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_engine.config._validation import (
    require_int_at_least,
    require_non_negative,
    require_positive,
)
from portfolio_engine.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class ConicSolverConfig:
    """Parámetros de Clarabel y de la factorización ``Σ = L Lᵀ`` de las formulaciones SOCP.

    Attributes:
        tol_gap_abs: tolerancia absoluta de la brecha dual de Clarabel.
        tol_gap_rel: tolerancia relativa de la brecha dual.
        tol_feas: tolerancia de factibilidad primal y dual.
        tol_infeas_abs: tolerancia absoluta de los certificados de inviabilidad.
        tol_infeas_rel: tolerancia relativa de los certificados de inviabilidad.
        max_iterations: iteraciones máximas del punto interior.
        time_limit_seconds: límite de tiempo por resolución (``None`` = sin límite).
        equilibrate: activa el equilibrado de las matrices de Clarabel.
        psd_eigenvalue_relative_tolerance: los autovalores de ``Σ`` por debajo de esta fracción de
            ``λ_max`` se descartan al factorizar (rango numérico).
        psd_negative_tolerance: un autovalor por debajo de ``−tol · max|λ|`` significa que ``Σ``
            no es PSD y se rechaza (criterio de ``diagnose_psd``); por encima es ruido numérico.
        factorization_tolerance: error máximo relativo ``max|LLᵀ − Σ| / max|Σ|`` admitido; por
            encima se rechaza la factorización (nunca se aproxima ``Σ`` en silencio).
    """

    tol_gap_abs: float
    tol_gap_rel: float
    tol_feas: float
    tol_infeas_abs: float
    tol_infeas_rel: float
    max_iterations: int
    time_limit_seconds: float | None
    equilibrate: bool
    psd_eigenvalue_relative_tolerance: float
    psd_negative_tolerance: float
    factorization_tolerance: float

    def __post_init__(self) -> None:
        for name in ("tol_gap_abs", "tol_gap_rel", "tol_feas", "tol_infeas_abs", "tol_infeas_rel"):
            require_positive(getattr(self, name), f"conic.{name}")
        require_int_at_least(self.max_iterations, 1, "conic.max_iterations")
        if self.time_limit_seconds is not None:
            require_positive(self.time_limit_seconds, "conic.time_limit_seconds")
        if not isinstance(self.equilibrate, bool):
            raise ConfigError("conic.equilibrate debe ser booleano.")
        require_non_negative(
            self.psd_eigenvalue_relative_tolerance, "conic.psd_eigenvalue_relative_tolerance"
        )
        require_non_negative(self.psd_negative_tolerance, "conic.psd_negative_tolerance")
        require_positive(self.factorization_tolerance, "conic.factorization_tolerance")


@dataclass(frozen=True, slots=True)
class SharpeConfig:
    """Parámetros de Maximum Sharpe (MASTER_SPEC §20, decisión A-13).

    Attributes:
        min_excess_return: exceso de retorno mínimo ``(μ−rf)ᵀw`` (neto de costes) por encima del
            cual el ratio se considera definido; con un máximo alcanzable menor o igual el
            problema es ``NOT_APPLICABLE`` (no se inventa un Sharpe máximo).
        agreement_tolerance: discrepancia relativa máxima admitida entre el Sharpe recalculado
            desde los pesos y el que implica el óptimo del SOCP (``1/r*``).
    """

    min_excess_return: float
    agreement_tolerance: float

    def __post_init__(self) -> None:
        require_positive(self.min_excess_return, "sharpe.min_excess_return")
        require_positive(self.agreement_tolerance, "sharpe.agreement_tolerance")
