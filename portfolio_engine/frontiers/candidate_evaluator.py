"""``QPCompositionEvaluator``: utilidad óptima exacta de una composición (CAN-021, modo QP).

Resuelve, con el motor continuo del Bloque 2 (``FrontierSession``, OSQP y ``SolutionValidator``),
el problema de utilidad de la composición para un perfil ``λ``::

    max  μᵀw − λ·wᵀΣw − TC(w)      ⇔      min  wᵀΣw − θ·μᵀw + θ·TC(w),   θ = 1/λ

con **todas** las restricciones compiladas de la composición (límites, grupos, turnover, política de
restringidos y liquidación de los activos que salen). Con cartera actual y costes es la
formulación ``NET`` (el coste está dentro de la optimización); sin ellos, ``GROSS``. La estimación
se recalcula desde los pesos (no desde el objetivo del solver). Una composición cuyo QP no produce
una solución válida se rechaza con el estado del solver, sin confundir fallo numérico con
inviabilidad.
"""

from __future__ import annotations

from portfolio_engine.candidates.evaluation import (
    EvaluationRejection,
    build_estimate,
)
from portfolio_engine.candidates.prepared import PreparedComposition
from portfolio_engine.config.engine_config import EngineConfig
from portfolio_engine.frontiers.session import FrontierContext, FrontierSession
from portfolio_engine.metrics.portfolio_metrics import MetricsTolerances
from portfolio_engine.models.composition import CompositionEstimate
from portfolio_engine.models.enums import CostTreatment, EvaluationMode, FrontierMethod, StrategyID
from portfolio_engine.optimizers.formulations.qp_builder import CompositionInputs
from portfolio_engine.optimizers.router import SolverRouter
from portfolio_engine.validation.solution_validator import SolutionValidator
from portfolio_engine.validation.tolerances import ValidationTolerances


class QPCompositionEvaluator:
    """Evaluador ``QP_UTILITY``: un QP pequeño por composición y perfil de aversión."""

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._router = SolverRouter(config.solver)
        self._validator = SolutionValidator(ValidationTolerances.from_config(config.solver))
        self._tolerances = MetricsTolerances.from_config(config.solver, config.frontier)

    @property
    def mode(self) -> EvaluationMode:
        """``QP_UTILITY``."""
        return EvaluationMode.QP_UTILITY

    def evaluate(
        self, prepared: PreparedComposition, risk_aversion: float, baseline_utility: float
    ) -> CompositionEstimate | EvaluationRejection:
        """Utilidad óptima de ``prepared`` para ``λ`` o rechazo con el estado del solver."""
        compiled = prepared.compiled
        if not prepared.feasible or compiled is None:
            return EvaluationRejection(prepared.infeasibility_codes, prepared.infeasibility_details)
        treatment = CostTreatment.GROSS if prepared.cost_model is None else CostTreatment.NET
        context = FrontierContext(
            composition_id=prepared.composition_hash,
            inputs=CompositionInputs(prepared.mu, prepared.sigma, compiled, prepared.cost_model),
            alignment=prepared.alignment,
            risk_free_rate=self._config.returns.risk_free_rate,
        )
        session = FrontierSession(
            context,
            treatment,
            FrontierMethod.RISK_AVERSION_GRID,
            self._config.solver,
            self._router,
            self._validator,
            self._tolerances,
        )
        point = session.solve_risk_aversion(1.0 / risk_aversion, strategy=StrategyID.FRONTIER_POINT)
        if not point.is_valid_solution or point.weights is None:
            return EvaluationRejection(
                (f"QP_{point.status.value}",),
                (
                    "QP de utilidad sin solución válida: "
                    f"{point.status.value} ({point.status_source.value})",
                ),
            )
        return build_estimate(
            prepared, point.weights, risk_aversion, baseline_utility, self.mode, self._validator
        )
