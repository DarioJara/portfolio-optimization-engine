# portfolio-engine

Motor profesional de optimización cuantitativa de carteras multi-escenario.

- Contrato técnico, matemático y funcional: [`MASTER_SPEC.md`](MASTER_SPEC.md).
- Diseño: [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Estado de cada requisito: [`TRACEABILITY.md`](TRACEABILITY.md).
- Plan por bloques: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
- Historial: [`CHANGELOG.md`](CHANGELOG.md).

Estado actual: **Bloque 3 (CandidateEngine, sustituciones y Global Candidate Frontier)** sobre el
Bloque 2 (optimizador continuo y frontera eficiente de la composición actual fija) y el Bloque 1
(Foundation: configuración, datos, validación, retornos, covarianza y modelo de riesgo).

- **Bloque 2:** frontera eficiente de la **composición actual fija** (solo cambian los pesos; los activos
  actuales que no estén en la composición se liquidan por completo) con OSQP para los QP y HiGHS (vía
  SciPy) para el LP de Maximum Return: Minimum Variance, Maximum Return, malla de aversión al riesgo,
  malla de retorno objetivo, frontera adaptativa y las fronteras `GROSS`, `NET` (costes dentro de la
  optimización) y `POST_COST_GROSS` (ex post). Toda solución pasa un `SolutionValidator` independiente.
- **Bloque 3:** `CandidateEngine` genera **varias composiciones** a partir de la cartera actual
  (filtro de elegibilidad, screening multiseñal vectorizado, 1/2/3-swap, búsqueda local y búsqueda en
  haz con exploración/explotación configurable) y `GlobalCandidateFrontierEngine` resuelve la frontera
  continua de cada composición y calcula la **envolvente de Pareto global**. La frontera continua
  (composición actual) y la global (múltiples composiciones) son pipelines distintos y ambos, junto
  con la cartera actual, se pueden graficar desde `visualization_dataset`.

Todavía **no** hay escenarios, SOCP/CVaR/robustez, MIQP, paralelismo, caché ni persistencia
(Bloques 4-6). La cardinalidad del CandidateEngine se garantiza en la **generación discreta**; no es
una formulación MIQP exacta.

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

## Uso: candidatos y frontera global (Bloque 3)

```python
from portfolio_engine.candidates import CandidateContext, CandidateEngine
from portfolio_engine.frontiers import GlobalCandidateFrontierEngine
from portfolio_engine.outputs import visualization_dataset

# Solo composiciones candidatas (la cartera actual va primero, como referencia):
context = CandidateContext(
    "P1", "BASE", risk_model, universe, current_state, spec=None, costs=asset_costs
)
candidates = CandidateEngine(config).generate_candidate_compositions(
    current_state.composition(), context
)  # list[CandidateComposition], siempre partiendo de la cartera actual

# Frontera global: una frontera continua por composición + envolvente de Pareto global.
result = GlobalCandidateFrontierEngine(config).solve(
    problem, CostTreatment.NET, FrontierMethod.RISK_AVERSION_GRID
)  # problem: FrontierProblem con composition_asset_ids = None
result.continuous  # CONTINUOUS_FRONTIER: solo los activos actuales
result.envelope  # puntos globalmente eficientes (varios CompositionID)
# Capas graficables: CURRENT_PORTFOLIO, CONTINUOUS_FRONTIER y GLOBAL_CANDIDATE_FRONTIER.
plot = visualization_dataset(result)
```

- `estimated_utility_gain`, `estimated_turnover` y `estimated_transaction_cost` de cada candidato son
  **estimaciones** de la búsqueda (pesos proyectados, cota inferior de la utilidad óptima); los pesos,
  el turnover y el coste finales solo existen en los puntos de la frontera de su composición.
- `candidates.evaluation_mode = "QP_UTILITY"` evalúa cada composición con el QP exacto del Bloque 2.
- Un activo restringido con `FREEZE_WEIGHT` nunca desaparece de un candidato; con `FORCE_LIQUIDATE` sale
  de todas las alternativas; un activo no elegible, ilíquido o restringido nunca entra como posición
  nueva. Las composiciones incompatibles se rechazan con su causa (`CandidateDiagnostics`).
- Sin cartera actual y con `candidates.cold_start = true`, la semilla se elige por utilidad individual
  y turnover/costes quedan como no disponibles.
- Posición actual no comprable (E-10): un activo mantenido con `EligibleFlag` o `LiquidityFlag` falsos (o
  desconocido con política conservadora) o fuera del `InvestmentUniverse` cumple
  `0 <= w <= min(w_current, MaxWeight)` en la frontera continua, el `CandidateEngine`, la frontera global y
  el `SolutionValidator`: se mantiene o se reduce, nunca se incrementa.
- Restricción ADV/NAV (A-11, `[constraints.liquidity]`): `LiquidityCapacity = p·ADV·días/NAV`; una posición
  nueva no puede superarla y una existente no puede crecer por encima de `max(w_current, capacidad)` (no se
  fuerza a vender). Sin valores por defecto; con `enabled = true` faltan datos ⇒ error. `ADV` y `NAV` en la
  misma divisa o `fx_rates` explícitos (unidades de NAVCurrency por unidad de ADVCurrency). `ADV` debe ser un
  importe monetario diario (`ADVUnit = NOTIONAL_PER_DAY`, con `ADVCurrency` y `ADVSource`); `NAVCurrency`
  es obligatoria y las divisas ausentes son un error. `ADV` en títulos/contratos se rechaza. Es un límite de
  tamaño, no garantiza que una venta pueda ejecutarse.

## Benchmark del pipeline de candidatos

```bash
.venv/Scripts/python benchmarks/scripts/candidate_engine.py --universe 50 200 700 --held 20 --seed 7
```

Guarda en `benchmarks/results/` los tiempos **medidos** (screening, generación de candidatos,
evaluación de las fronteras finalistas y Pareto global) con sus metadatos. Son mediciones locales de
un proceso, no rendimiento de producción (la paralelización es del Bloque 5).

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
