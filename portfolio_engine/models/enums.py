"""Enumeraciones del Bloque 1.

Solo se definen valores cuya funcionalidad existe. Los métodos diferidos (p. ej. ``OAS`` y
``EWMA`` para covarianza, enmienda E-07) se añadirán junto con su implementación para no
exponer opciones seleccionables sin implementar.
"""

from __future__ import annotations

from enum import StrEnum


class ReturnKind(StrEnum):
    """Tipo de retorno (MASTER_SPEC §9). ``LOG`` exige justificación explícita."""

    ARITHMETIC = "ARITHMETIC"
    LOG = "LOG"


class ExpectedReturnMode(StrEnum):
    """Origen de los expected returns (MASTER_SPEC §8)."""

    INTERNAL_ESTIMATION = "INTERNAL_ESTIMATION"
    EXTERNAL_ALPHA = "EXTERNAL_ALPHA"


class InternalEstimationMethod(StrEnum):
    """Métodos internos implementados. EWMA, factoriales, bayesianos y señales son futuros."""

    HISTORICAL_MEAN = "HISTORICAL_MEAN"


class CovarianceMethod(StrEnum):
    """Estimadores de covarianza implementados (MASTER_SPEC §11; OAS/EWMA diferidos, E-07)."""

    EMPIRICAL = "EMPIRICAL"
    LEDOIT_WOLF = "LEDOIT_WOLF"


class PSDRepairMethod(StrEnum):
    """Reparación de matrices no PSD (MASTER_SPEC §11)."""

    NONE = "NONE"
    EIGENVALUE_FLOOR = "EIGENVALUE_FLOOR"
    NEAREST_PSD = "NEAREST_PSD"


class RestrictedExistingPositionPolicy(StrEnum):
    """Tratamiento de activos restringidos ya presentes en cartera (MASTER_SPEC §12, E-09)."""

    HOLD_OR_REDUCE = "HOLD_OR_REDUCE"
    FREEZE_WEIGHT = "FREEZE_WEIGHT"
    FORCE_LIQUIDATE = "FORCE_LIQUIDATE"


class CostInputUnit(StrEnum):
    """Unidad en la que llegan los costes unitarios del universo."""

    DECIMAL = "DECIMAL"
    BPS = "BPS"


class CostSource(StrEnum):
    """Fuente de coste unitario utilizada para un activo (precedencia configurable)."""

    BUY_SELL = "BUY_SELL"
    ESTIMATED = "ESTIMATED"
    BID_ASK_SPREAD = "BID_ASK_SPREAD"


class IssueSeverity(StrEnum):
    """Severidad de un problema de calidad de datos."""

    WARNING = "WARNING"
    ERROR = "ERROR"


class AssetErrorPolicy(StrEnum):
    """Qué hacer con un activo que tiene errores de datos: detener o excluirlo (registrado)."""

    FAIL = "FAIL"
    EXCLUDE_ASSET = "EXCLUDE_ASSET"


class ResidualWeightPolicy(StrEnum):
    """Qué hacer si los pesos actuales no suman 1 dentro de la tolerancia (decisión A-34)."""

    ERROR = "ERROR"
    ASSIGN_TO_CASH = "ASSIGN_TO_CASH"


class OutlierMethod(StrEnum):
    """Método de detección de outliers en retornos (solo detecta; nunca corrige)."""

    ROBUST_ZSCORE = "ROBUST_ZSCORE"


class BoundSource(StrEnum):
    """Procedencia de un límite de peso efectivo (precedencia de ARCHITECTURE §6.4)."""

    PORTFOLIO_OVERRIDE = "PORTFOLIO_OVERRIDE"
    GLOBAL_CONFIG = "GLOBAL_CONFIG"
    UNIVERSE = "UNIVERSE"
    UNSET = "UNSET"


class SolverStatus(StrEnum):
    """Estado normalizado de una resolución (MASTER_SPEC §45).

    Un fallo numérico nunca se presenta como inviabilidad matemática.
    """

    OPTIMAL = "OPTIMAL"
    OPTIMAL_INACCURATE = "OPTIMAL_INACCURATE"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    TIME_LIMIT = "TIME_LIMIT"
    NUMERICAL_ERROR = "NUMERICAL_ERROR"
    INSUFFICIENT_PROGRESS = "INSUFFICIENT_PROGRESS"
    UNKNOWN = "UNKNOWN"


class StatusSource(StrEnum):
    """Quién determinó el estado de una solución (decisión A-15)."""

    SOLVER = "SOLVER"
    PRE_SOLVER_CHECK = "PRE_SOLVER_CHECK"
    VALIDATOR = "VALIDATOR"
    CROSS_CHECK = "CROSS_CHECK"


class RecoveryOutcome(StrEnum):
    """Resultado de la recuperación numérica de un punto de retorno objetivo (F-3)."""

    RECOVERED = "RECOVERED"
    CONFIRMED_INFEASIBLE = "CONFIRMED_INFEASIBLE"
    NOT_RECOVERED = "NOT_RECOVERED"


class ProblemClass(StrEnum):
    """Clase matemática de un problema de optimización (ARCHITECTURE §9.2)."""

    QP = "QP"
    LP = "LP"
    SOCP = "SOCP"
    SDP = "SDP"
    MIQP = "MIQP"
    MIQCP = "MIQCP"
    MISOCP = "MISOCP"
    NLP_CONVEX = "NLP_CONVEX"
    NLP_NONCONVEX = "NLP_NONCONVEX"
    HEURISTIC = "HEURISTIC"


class OptimizationFamily(StrEnum):
    """Familias de optimización separadas (MASTER_SPEC §14)."""

    FAST_PRODUCTION = "FAST_PRODUCTION"
    EXACT_MIP = "EXACT_MIP"
    NONCONVEX_RESEARCH = "NONCONVEX_RESEARCH"


class FrontierScope(StrEnum):
    """Alcance de una frontera (A-05): composición actual fija o múltiples composiciones."""

    CONTINUOUS_FRONTIER = "CONTINUOUS_FRONTIER"
    GLOBAL_CANDIDATE_FRONTIER = "GLOBAL_CANDIDATE_FRONTIER"


class CostTreatment(StrEnum):
    """Tratamiento de costes de una frontera (MASTER_SPEC §37-39, decisión A-05)."""

    GROSS = "GROSS"
    NET = "NET"
    POST_COST_GROSS = "POST_COST_GROSS"


class FrontierMethod(StrEnum):
    """Método de generación de puntos de frontera (MASTER_SPEC §35-36)."""

    RISK_AVERSION_GRID = "RISK_AVERSION_GRID"
    TARGET_RETURN_GRID = "TARGET_RETURN_GRID"


class StrategyID(StrEnum):
    """Estrategias nombradas implementadas (decisión A-20; el resto llega con su bloque)."""

    CURRENT = "CURRENT"
    MIN_VARIANCE = "MIN_VARIANCE"
    MAX_RETURN = "MAX_RETURN"
    FRONTIER_POINT = "FRONTIER_POINT"


class GridScale(StrEnum):
    """Espaciado de una malla de parámetros."""

    LINEAR = "LINEAR"
    LOG = "LOG"


class ThetaGridMode(StrEnum):
    """Origen del rango de theta (decisión A-16)."""

    EXPLICIT = "EXPLICIT"
    AUTO = "AUTO"


class GroupDimension(StrEnum):
    """Dimensiones de restricciones de grupo (MASTER_SPEC §12)."""

    SECTOR = "SECTOR"
    COUNTRY = "COUNTRY"
    ASSET_CLASS = "ASSET_CLASS"
    CURRENCY = "CURRENCY"


class CrossCheckPolicy(StrEnum):
    """Política ante estados ambiguos del solver (decisiones A-32, A-33).

    ``COLD_RETRY`` reintenta desde cero con más iteraciones. La verificación cruzada con un
    segundo solver (Clarabel) llega en el Bloque 4.
    """

    NONE = "NONE"
    COLD_RETRY = "COLD_RETRY"


class EligibilityStatus(StrEnum):
    """Rol de un activo respecto a una cartera en la generación de composiciones (Bloque 3).

    ``HELD`` (A) y ``MANDATORY_HOLD`` (C) están en la cartera actual; ``ELIGIBLE_NEW`` (B) puede
    comprarse; ``LIQUIDATE_ONLY`` (D) está en cartera pero no puede comprarse; ``MANDATORY_EXIT``
    debe liquidarse (``FORCE_LIQUIDATE``); ``EXCLUDED`` (E) queda fuera por completo.
    """

    HELD = "HELD"
    MANDATORY_HOLD = "MANDATORY_HOLD"
    LIQUIDATE_ONLY = "LIQUIDATE_ONLY"
    MANDATORY_EXIT = "MANDATORY_EXIT"
    ELIGIBLE_NEW = "ELIGIBLE_NEW"
    EXCLUDED = "EXCLUDED"


class EligibilityReason(StrEnum):
    """Causa explícita por la que un activo no puede entrar en una composición (Bloque 3)."""

    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    NOT_LIQUID = "NOT_LIQUID"
    UNKNOWN_LIQUIDITY_FLAG = "UNKNOWN_LIQUIDITY_FLAG"
    RESTRICTED = "RESTRICTED"
    UNKNOWN_RESTRICTED_FLAG = "UNKNOWN_RESTRICTED_FLAG"
    OUTSIDE_INVESTMENT_UNIVERSE = "OUTSIDE_INVESTMENT_UNIVERSE"
    NO_RISK_MODEL_DATA = "NO_RISK_MODEL_DATA"
    FREEZE_WEIGHT = "FREEZE_WEIGHT"
    FORCE_LIQUIDATE = "FORCE_LIQUIDATE"


class AdvUnit(StrEnum):
    """Unidad en la que un dato de origen expresa el ``ADV`` (A-11, E-11).

    Solo ``NOTIONAL_PER_DAY`` (importe monetario medio negociado por día, en la divisa de
    ``ADVCurrency``) es utilizable por la restricción ADV/NAV. Las unidades físicas se reconocen
    para poder rechazarlas con un diagnóstico específico; su conversión a importe exigiría un precio
    y una política de valoración aprobados y no está definida.
    """

    NOTIONAL_PER_DAY = "NOTIONAL_PER_DAY"
    SHARES_PER_DAY = "SHARES_PER_DAY"
    CONTRACTS_PER_DAY = "CONTRACTS_PER_DAY"


class UnknownFlagPolicy(StrEnum):
    """Tratamiento explícito de un ``LiquidityFlag`` desconocido (sin sustitución silenciosa)."""

    EXCLUDE = "EXCLUDE"
    ALLOW = "ALLOW"
    ERROR = "ERROR"


class ScreeningNormalization(StrEnum):
    """Normalización de las señales de screening dentro de cada conjunto comparado."""

    RANK = "RANK"
    ZSCORE = "ZSCORE"


class MissingSignalPolicy(StrEnum):
    """Tratamiento explícito de una señal de screening ausente (siempre se registra)."""

    EXCLUDE = "EXCLUDE"
    NEUTRAL = "NEUTRAL"
    ERROR = "ERROR"


class EvaluationMode(StrEnum):
    """Cómo se estima la utilidad de una composición durante la búsqueda (CAN-021).

    ``PROJECTED_WEIGHTS``: pesos heredados de la cartera actual proyectados sobre las cotas y
    refinados (cota inferior de la utilidad óptima). ``QP_UTILITY``: utilidad óptima exacta de la
    composición con el motor continuo del Bloque 2 (un QP pequeño por composición).
    """

    PROJECTED_WEIGHTS = "PROJECTED_WEIGHTS"
    QP_UTILITY = "QP_UTILITY"


class MoveKind(StrEnum):
    """Tipo de movimiento entre composiciones."""

    SWAP = "SWAP"
    ADD = "ADD"
    DROP = "DROP"


class CandidateType(StrEnum):
    """Origen de la señal que propone un activo entrante (MASTER_SPEC §28, §66)."""

    HIGH_CONVICTION = "HIGH_CONVICTION"
    DIVERSIFICATION = "DIVERSIFICATION"
    EXPLORATION = "EXPLORATION"
    CURRENT_HOLDING = "CURRENT_HOLDING"


class CandidateOrigin(StrEnum):
    """Etapa del CandidateEngine que generó una composición."""

    REFERENCE = "REFERENCE"
    REFERENCE_ADJUSTED = "REFERENCE_ADJUSTED"
    COLD_START_SEED = "COLD_START_SEED"
    BEAM_SEARCH = "BEAM_SEARCH"
    LOCAL_SEARCH = "LOCAL_SEARCH"
