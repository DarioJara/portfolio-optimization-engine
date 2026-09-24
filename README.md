# portfolio-engine

Motor profesional de optimización cuantitativa de carteras multi-escenario.

- Contrato técnico, matemático y funcional: [`MASTER_SPEC.md`](MASTER_SPEC.md).
- Diseño: [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Estado de cada requisito: [`TRACEABILITY.md`](TRACEABILITY.md).
- Plan por bloques: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
- Historial: [`CHANGELOG.md`](CHANGELOG.md).

Estado actual: **Bloque 2 (Optimizador continuo y frontera eficiente)** sobre el Bloque 1 (Foundation:
configuración, datos, validación, retornos, covarianza y modelo de riesgo). El motor genera la frontera
eficiente de la **composición actual fija** (solo cambian los pesos; los activos actuales que no estén
en la composición se liquidan por completo) con OSQP para los QP y HiGHS (vía SciPy) para el LP de
Maximum Return: Minimum Variance, Maximum
Return, malla de aversión al riesgo, malla de retorno objetivo, frontera adaptativa, y las fronteras
`GROSS`, `NET` (costes dentro de la optimización) y `POST_COST_GROSS` (ex post). Toda solución pasa un
`SolutionValidator` independiente. Todavía **no** hay CandidateEngine, Global Frontier, escenarios,
paralelismo ni persistencia (Bloques 3-6).

## Requisitos

- Python ≥ 3.11.
- Dependencias de runtime: `numpy`, `scipy`, `pandas`, `pyarrow`, `osqp` (ver `pyproject.toml`).
- Dependencias de desarrollo (grupo `dev`): `pytest`, `hypothesis`, `mypy`, `ruff`, `scikit-learn` (solo como referencia en tests).

## Instalación (entorno local, nunca global)

```bash
python -m venv .venv
```

Windows (Git Bash / PowerShell):

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

Linux / macOS:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

Versiones exactas con las que se validó el último bloque: `requirements-lock.txt`
(`.venv/Scripts/python -m pip install -r requirements-lock.txt` para reproducirlas).

## Ejecutar tests y controles de calidad

```bash
.venv/Scripts/python -m pytest
```

```bash
.venv/Scripts/python -m mypy
```

```bash
.venv/Scripts/python -m ruff check portfolio_engine tests
```

```bash
.venv/Scripts/python -m ruff format --check portfolio_engine tests benchmarks
```

> Con `ruff` 0.16 no ejecutar `ruff format .` sobre la raíz: también reformatea los bloques de
> código de los `.md` (p. ej. `AUDIT_BLOCK_2.md`, que debe conservarse intacto). Usar los
> directorios de código como arriba.

## Configuración

Toda decisión financiera, matemática u operativa procede de configuración (MASTER_SPEC §4).
El fichero de ejemplo es [`config/default_engine.toml`](config/default_engine.toml) y se carga con:

```python
from portfolio_engine.config import load_engine_config

config = load_engine_config("config/default_engine.toml")
```

Los dataclasses de configuración no tienen valores por defecto para parámetros de negocio:
cada valor debe declararse explícitamente en la configuración.

## Uso: frontera eficiente de una cartera (Bloque 2)

```python
from portfolio_engine.frontiers import ContinuousFrontierEngine, FrontierProblem
from portfolio_engine.models.enums import CostTreatment, FrontierMethod
from portfolio_engine.outputs import frontier_dataset

engine = ContinuousFrontierEngine(
    config
)  # config: EngineConfig (secciones frontier/solver/benchmark)
problem = FrontierProblem(  # entradas ya validadas por el Bloque 1
    portfolio_id="P1",
    scenario_id="BASE",
    risk_model=risk_model,
    universe=universe,
    state=current_state,
    spec=None,
    costs=asset_costs,
)
result = engine.solve(problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID)
dataset = frontier_dataset(result)  # Volatility, ExpectedReturnGross, ExpectedReturnNet
```

- `CostTreatment.GROSS | NET | POST_COST_GROSS` son frontera bruta, neta (costes dentro de la
  optimización, `min wᵀΣw − θμᵀw + θ·TC(w)`) y bruta evaluada tras costes; **no son equivalentes**.
- `FrontierMethod.RISK_AVERSION_GRID | TARGET_RETURN_GRID`; frontera adaptativa con
  `frontier.adaptive = true` en la configuración.
- Sin cartera actual solo es posible la frontera bruta de una composición explícita
  (`composition_asset_ids`); turnover y costes quedan como `None` con su motivo, nunca inventados.
- Una composición explícita puede omitir activos actuales: se venden por completo y su coste
  (`K_E`) y turnover entran como constantes en el retorno neto, `MaxTurnover`, la factibilidad y el
  validador. Un restringido actual con `FREEZE_WEIGHT` no puede salir de la composición (rechazo
  previo al solver).
- Un problema inviable por reglas deterministas (`PreFeasibilityChecker`) devuelve `INFEASIBLE` con
  `StatusSource.PRE_SOLVER_CHECK` sin llamar al solver.

## Benchmark de reutilización del solver

```bash
.venv/Scripts/python benchmarks/scripts/solver_reuse.py --assets 20 --points 20 --seed 7
```

Guarda en `benchmarks/results/` los tiempos **medidos** (cold setup vs workspace reuse vs warm start)
junto con los metadatos de la ejecución.

El benchmark separa el coste de los extremos (MinVariance y MaxReturn: LP y etapa 2) del de la malla
y del refinado adaptativo (`min_variance`, `max_return`, `grid`), y reporta las iteraciones de los
extremos y de la malla por separado. La reutilización del workspace solo afecta a la malla y a
MinVariance.

## Robustez de las fronteras (H-1)

```bash
.venv/Scripts/python benchmarks/scripts/frontier_robustness.py
```

Reproduce el experimento de la auditoría: 96 fronteras sintéticas (N ∈ {5, 10, 20, 40}, 6 semillas,
{GROSS, NET} × {malla de aversión al riesgo, malla de retorno objetivo}) e informa cuántas salen
sanas, degradadas o sin frontera.
