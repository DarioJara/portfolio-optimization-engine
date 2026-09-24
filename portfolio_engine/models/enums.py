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
    """Alcance de una frontera (A-05). ``GLOBAL_CANDIDATE_FRONTIER`` llega en el Bloque 3."""

    CONTINUOUS_FRONTIER = "CONTINUOUS_FRONTIER"


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
