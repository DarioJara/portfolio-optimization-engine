# CHANGELOG

Formato: una entrada por bloque de implementación. Solo se registran resultados de ejecuciones
reales (CLAUDE.md, MASTER_SPEC §71, §80).

---

## [Bloque 1 — Foundation] — 2026-09-23

### Alcance

Configuración centralizada e inmutable, modelos de datos, validación de inputs, motor de
retornos, interfaz de expected returns, covarianza (Empirical y Ledoit-Wolf), diagnóstico y
reparación PSD, modelo de datos de costes de transacción, estado actual de cartera,
`OptimizationHorizonYears` (E-03) y `RestrictedExistingPositionPolicy` como configuración (E-09).

No se ha implementado nada de los bloques 2–6: no hay optimización, fronteras, CandidateEngine,
escenarios, solvers, paralelismo, caché ni persistencia (verificado por
`tests/unit/test_architecture_rules.py`). OAS y EWMA siguen diferidos (E-07) y no son
seleccionables.

### Baseline de no regresión (MASTER_SPEC §80)

- Commit de partida: `e49c70e` ("Phase 0 - architecture, specification and traceability baseline").
- Tests existentes antes del bloque: **0** (no había código). No hay resultados previos que comparar.

### Entorno

- `pyproject.toml`: runtime (`numpy`, `scipy`, `pandas`, `pyarrow`) separado del grupo `dev`
  (`pytest`, `hypothesis`, `mypy`, `ruff`, `scikit-learn` solo como referencia en tests).
- Entorno local `.venv` (Python 3.13.6). Nada instalado globalmente.
- `requirements-lock.txt`: versiones exactas del entorno validado (numpy 2.5.3, scipy 1.18.1,
  pandas 3.0.6, pyarrow 25.0.1, hypothesis 6.168.1, pytest 9.1.1, mypy 2.3.1, ruff 0.16.8,
  scikit-learn 1.9.1).
- `.gitignore`: artefactos de Python, `.venv/`, `1.-Version Anterior/` e `Instrucciones.txt`
  (no se versionan; no se han borrado del disco).
- No se ha consultado ni reutilizado código de `1.-Version Anterior/`.

### Añadido

- `portfolio_engine/exceptions.py`: jerarquía de excepciones del motor.
- `portfolio_engine/utils/`: hashing canónico (`canonical_json`, `canonical_float`,
  `hash_float_array`), logging estructurado JSON, arrays de solo lectura.
- `portfolio_engine/models/`: enums del Bloque 1, `AssetMetadata`/`Universe`, `AssetIndex`
  (nivel global), `PriceHistory`/`ReturnsMatrix`, `PortfolioSpec`/`WeightBounds`/
  `CurrentPortfolioState` (con `CurrentPortfolioStateHash`, E-06), `ExpectedReturns`/
  `ExternalAlpha`/`CovarianceEstimate`/`PSDDiagnostics`/`PSDRepairReport`/`RiskModel`
  (con `MuSigmaVersion`), `AssetCostVector`.
- `portfolio_engine/config/`: `EngineConfig` (con `optimization_horizon_years`), `DataConfig`,
  `ReturnConfig`, `RiskConfig`, `ConstraintConfig`, `TransactionCostConfig`; loader TOML estricto
  (claves desconocidas o ausentes = error, sin defaults implícitos); `ConfigSnapshot`/`ConfigHash`.
- `config/default_engine.toml`: única ubicación de valores de ejemplo (horizonte 1.0,
  `HOLD_OR_REDUCE`, etc.).
- `portfolio_engine/data/sources/`: `DataSource` (Protocol), `DataFrameSource`, `CSVSource`,
  `ParquetSource` y canonicalización estricta de tipos.
- `portfolio_engine/data/validation/`: `UniverseValidator`, `MarketDataValidator`,
  `PortfolioValidator`, `build_external_alpha`, `resolve_asset_costs`, `DataQualityReport` con
  `CorrectionLog`.
- `portfolio_engine/returns/`: `ReturnsEngine` (aritméticos; log solo con justificación),
  anualización lineal, `ExpectedReturnProvider`, `HistoricalMeanProvider`,
  `ExternalAlphaProvider`, factoría por configuración.
- `portfolio_engine/risk/`: `EmpiricalCovarianceEstimator`, `LedoitWolfCovarianceEstimator`
  (fórmula propia; sklearn solo como referencia en tests), diagnóstico PSD, reparación
  `EIGENVALUE_FLOOR` y `NEAREST_PSD`, `CovarianceBuilder`, `build_risk_model`.
- `README.md` con instalación y ejecución de tests; `CHANGELOG.md`.
- Tests: `tests/unit/` (config, data, costs, returns, risk, arquitectura, infraestructura) y
  `tests/property/` (Hypothesis).

### Modificado

- `ARCHITECTURE.md` e `IMPLEMENTATION_PLAN.md`: referencias obsoletas a "repositorio sin
  commits" sustituidas por el baseline `e49c70e`.
- `TRACEABILITY.md`: estados del Bloque 1 con evidencia real (ver abajo).

### Defecto encontrado y corregido durante el bloque

- `CSVSource`: `pandas.to_numeric` sobre texto no redondea correctamente y alteraba el último
  bit de los precios (diferencia ~1e-14 frente al original). Ahora los números que llegan como
  texto se parsean con `float()` (redondeo correcto). Lo detectó
  `tests/unit/data/test_sources.py`, endurecido a comparación exacta.

### Tests ejecutados (gate del Bloque 1)

| Comprobación | Resultado |
|---|---|
| `pytest` (suite completa) | **252 passed, 0 failed, 0 skipped** (ejecución final tras la corrección del generador) |
| — de ellos, `-m property` (Hypothesis, 60 ejemplos por propiedad) | 8 passed |
| — de ellos, `-m architecture` | 8 passed |
| `mypy` (strict, `portfolio_engine/`) | 0 errores (53 ficheros) |
| `ruff check portfolio_engine tests` | 0 errores |
| `ruff format --check portfolio_engine tests` | 85 ficheros ya formateados |
| Control de mutaciones (script temporal, no versionado) | 19/19 mutaciones matemáticas o de validación hacen fallar la suite |

Tests obligatorios del Bloque 1 presentes y en verde: retornos aritméticos, anualización,
`OptimizationHorizonYears`, NaN, infinitos, duplicados, precios no positivos, histórico
insuficiente, metadatos, pesos actuales, Empirical, Ledoit-Wolf, simetría, autovalores,
número de condición, PSD, matriz casi singular, matriz singular, reparación PSD, inmutabilidad
de configuración, validación de inputs de costes, `RestrictedExistingPositionPolicy` y
propiedades con Hypothesis.

### Trazabilidad

- `VALIDATED` (58): GOV-001, GOV-004, GOV-005, GOV-006, GOV-008, CFG-001 … CFG-004, CFG-006,
  CFG-014, CFG-016, CFG-017, CFG-018, DAT-001 … DAT-006, DAT-009 … DAT-012, DAT-014, DAT-016,
  DAT-020 … DAT-027, DAT-029 … DAT-031, RET-001, RET-002, RET-003, RET-008, RET-010,
  RET-011, RET-012, RSK-001 … RSK-003, RSK-006 … RSK-013, CON-021, TC-005, TST-018.
- `PARTIAL` (13): GOV-002, GOV-003, GOV-007, GOV-009, GOV-010, GOV-011, CFG-015, TST-001,
  TST-003 (transversales hasta el Bloque 6); CFG-005 (base; extensiones B2–B4); DAT-013 (índice
  global; eligible/local en B3); DAT-015 (alpha; resto de entradas opcionales en B4); DAT-028
  (metadatos condicionales a restricciones de grupo en B2).

### Decisiones de implementación que afectan a `ARCHITECTURE.md` (pendientes de reflejar)

`ARCHITECTURE.md` no se ha modificado porque estas decisiones no estaban aprobadas previamente.
Se someten a revisión:

1. **Resolución de costes unitarios** en `data/validation/transaction_cost_inputs.py` (validación
   de inputs) en lugar de `costs/`. El paquete `costs/` queda para el cálculo de
   `TransactionCost(w)` y turnover del Bloque 2.
2. **Dependencia `risk → returns`** (uso de `annualize_covariance`). El grafo de ARCHITECTURE
   §4.1 solo lista `risk → models, config`. El grafo sigue siendo acíclico (test).
3. **`CSVSource` y `ParquetSource` en un único módulo** `data/sources/file_sources.py`.
4. **`NEAREST_PSD` como proyección de Frobenius en forma cerrada** (Higham, 1988:
   `V·max(Λ,0)·Vᵀ`), que es la solución exacta del problema de la matriz PSD más cercana para una
   covarianza. ARCHITECTURE §9.2 (P23) la describía como proyección alterna (NLP convexo): ese
   algoritmo solo es necesario para la matriz de correlación más cercana (diagonal unitaria).
   No es una simplificación. Probado: es PSD, idempotente y no está más lejos que otras
   matrices PSD.
5. **`PSDDiagnostics`, `PSDRepairReport` y `ExternalAlpha` en `models/risk_model.py`**, para
   que `models` no dependa de `risk`.
6. **`EngineConfig` sin campos para subconfiguraciones de bloques posteriores**. Se añadirán en
   su bloque para no crear placeholders.

### Limitaciones conocidas

- Validado solo con Python 3.13.6 en Windows 11. `requires-python >= 3.11` no se ha probado en
  3.11 ni 3.12. mypy no fija `python_version` porque los stubs de numpy 2.5 usan sintaxis ≥ 3.12.
- Alineación de calendario: el calendario de referencia es la unión de fechas. Con
  `EXCLUDE_ASSET`, un activo con fechas espurias haría marcar a los demás como
  `MISSING_OBSERVATION`. El comportamiento es conservador (falla o excluye; nunca rellena).
- Outliers, precios stale y huecos de calendario solo se detectan y registran; nunca se corrigen
  (por diseño, §10).
- `DAT-028`: los metadatos obligatorios condicionales a restricciones de grupo se exigirán en el
  Bloque 2, cuando existan esas restricciones.
- `DataQualityReport` conserva los errores de los activos excluidos. Un llamador que use
  `EXCLUDE_ASSET` debe consultar `report.corrections` y no `raise_if_errors()` sobre el
  resultado.
- Precisión de LAPACK con entradas cercanas al underflow: con matrices cuyas entradas son del
  orden de 1e-160, `np.linalg.eigvalsh` devuelve autovalores con error relativo ~2e-4, mientras
  que `np.linalg.eigh` (la ruta que usa el motor para diagnóstico y reparación) es exacta.
  Hypothesis lo detectó en el oráculo de un test de propiedades; el generador se restringe a
  magnitudes realistas (|x| ≥ 1e-6 o 0). No afecta a covarianzas reales, pero conviene tenerlo
  presente si se introducen otras rutinas espectrales.
- Fuentes SQL Server y API: Bloque 6.

### Estado

`BLOCK_1_STATUS = PASS`

---

## [Cierre de hallazgos de auditoría — Bloque 1] — 2026-09-23

### Alcance

Cierre de los hallazgos `MEDIUM` y `LOW` de `AUDIT_BLOCK_1.md` (`AUDIT_STATUS = PASS_WITH_CHANGES`).
Cambio exclusivamente documental: **ningún fichero de `portfolio_engine/` se ha modificado**.
No se avanza al Bloque 2; ningún requisito de bloques 2–6 cambia de estado.

### Hallazgos cerrados

| # | Hallazgo (`AUDIT_BLOCK_1.md`) | Acción |
|---|---|---|
| #2 | `ARCHITECTURE.md` desactualizada: no reflejaba las 6 desviaciones del Bloque 1 y contenía la afirmación obsoleta "Estado del código productivo: inexistente" | Cabecera actualizada con el estado real del Bloque 1; nueva §3.1 con las 6 desviaciones (diseño original vs. implementación real vs. racional), grafo §4.1 actualizado con la arista `risk → returns`, tabla §9.2 (P23/P23b/P24) reclasificada y anotada como implementada |
| #1 | `MASTER_SPEC.md` no fija fórmulas cerradas para covarianza empírica, Ledoit-Wolf ni reparación PSD | Añadido Anexo B a `ARCHITECTURE.md` con las fórmulas exactas implementadas y su referencia bibliográfica (Ledoit & Wolf 2004; Higham 1988), sin modificar `MASTER_SPEC.md` (sigue siendo la única autoridad del contrato) |
| #3 | Evidencia circular de `TST-018` (citaba al propio CHANGELOG) | `TRACEABILITY.md`: evidencia sustituida por una enumeración cerrada de 9 tests concretos (`::test_función`), uno por cada categoría obligatoria del gate del Bloque 1 |
| #4 | ~16 requisitos `VALIDATED` citaban solo el fichero de test, sin función concreta | `TRACEABILITY.md`: evidencia ampliada a `::test_función` en CFG-001, CFG-003, CFG-004, CFG-006, CFG-016, CFG-017, DAT-004, DAT-005, DAT-006, DAT-009, DAT-010, DAT-012, DAT-015, DAT-016, DAT-028, DAT-029, RET-002, RSK-013, CON-021, TC-005 (y CFG-005, PARTIAL, con el mismo criterio) |
| #5 | `GOV-007` (DI/Protocol) con evidencia vaga ("tests inyectan...") sin test citado | `TRACEABILITY.md`: evidencia sustituida por 3 tests concretos que ejercitan `DataSource`, `ExpectedReturnProvider` y `CovarianceEstimator` inyectados por configuración |
| #7 / #10 | `ruff format --check` detectaba `README.md` sin formatear (línea 61, falta línea en blanco en un bloque de código) | `README.md` corregido; `ruff format --check .` ahora reporta "95 files already formatted" sin excepciones |
| #8 | Posible doble contabilidad de test entre DAT-022/DAT-023/DAT-024 | `TRACEABILITY.md`: evidencia desglosada por caso parametrizado (`[value-code]`), confirmando que cada requisito depende de una aserción de `IssueCode` distinta e independiente |
| #9 | Racional escueto de la desviación 3 (fusión `CSVSource`/`ParquetSource`) | Ampliado en `ARCHITECTURE.md` §3.1: comparten la canonicalización estricta de `data/sources/base.py`; separarlos duplicaría esa lógica (GOV-009) |

Hallazgos no accionables en este cierre (no requieren cambio de fichero, ya evaluados como aceptables
en `AUDIT_BLOCK_1.md`): #6 (exclusión de pesos cero en `CurrentPortfolioStateHash` — ya documentada
explícitamente en la descripción de DAT-016), #11 y #12 (observaciones informativas sin acción).

### Validación (re-ejecución completa tras los cambios documentales)

| Comprobación | Resultado |
|---|---|
| `pytest -q` | **252 passed, 0 failed, 0 skipped** |
| `mypy --strict portfolio_engine` | **0 errores, 53 ficheros** |
| `ruff check .` | **0 violaciones** |
| `ruff format --check .` | **95 ficheros formateados, 0 pendientes** (incluye `README.md`, antes pendiente) |

Ninguna comprobación reveló una regresión: no fue necesario modificar código productivo.

### Trazabilidad

Sin cambios de `RequirementID` (ningún estado pasa de `PARTIAL`/`VALIDATED`/`NOT_IMPLEMENTED` a
otro). Se amplía evidencia de trazabilidad únicamente — ver `TRACEABILITY.md`, registro de cambios.

### Estado

`BLOCK_1_CLOSURE_STATUS = PASS`

---

## [Bloque 2 — Optimizador continuo y frontera eficiente] — 2026-09-23

### Alcance

Optimización continua sobre **composición fija** (la cartera actual) y construcción de fronteras:
Minimum Variance, Maximum Return (lexicográfico, A-14), malla de aversión al riesgo (`P = 2Σ`
constante, `q(θ) = θ·q1`), malla de retorno objetivo, frontera adaptativa, deduplicación y Pareto,
fronteras `GROSS`, `NET` (costes dentro de la optimización, `min wᵀΣw − θμᵀw + θ·TC(w)`) y
`POST_COST_GROSS` (evaluación ex post, etiquetada distinto de NET), turnover y `MaxTurnover`,
restricciones de grupo, política de activos restringidos (E-09), factibilidad previa sin solver,
`SolutionValidator` independiente, backend OSQP con API nativa (workspace reutilizable, warm start,
reintento en frío), diagnósticos, salidas y benchmark real de reutilización del solver.

**Fuera de alcance (no implementado):** `CandidateEngine`, Global Candidate Frontier, Beam Search,
paralelización, MIQP/SCIP, Clarabel (decisión A-32: no se adopta), Max Sharpe, Volatility Control,
CVaR, escenarios, caché, persistencia, `K_E` de liquidaciones dentro de la optimización (TC-011, B3).
No se ha consultado ni reutilizado código de `1.-Version Anterior/`.

### Baseline de no regresión (MASTER_SPEC §80)

- Rama `block2-continuous-frontier`; etiqueta `block1-validated` presente.
- Baseline antes de modificar módulos validados: `pytest` → **252 passed**.
- Tras el bloque los 252 tests del Bloque 1 siguen en verde. Se modificaron deliberadamente dos
  ficheros de test del Bloque 1 porque codificaban el alcance del Bloque 1:
  `tests/unit/config/test_config_hashing.py::test_snapshot_is_complete_canonical_json` (el snapshot
  de configuración incluye ahora `frontier`, `solver` y `benchmark`) y
  `tests/unit/test_architecture_rules.py` (grafo de capas y lista de paquetes de bloques posteriores
  actualizados; `osqp` confinado a `optimizers/osqp_backend.py`; 4 tests nuevos: OSQP confinado, sin
  CVXPY en el camino de producción, validador independiente de solvers, política de restringidos no
  referenciada fuera de `constraints/`/`validation/`).

### Entorno

- `osqp 1.1.3` instalado en el `.venv` local (nunca global) y declarado en `pyproject.toml`
  (`osqp>=1.1,<2`); `requirements-lock.txt` actualizado (osqp 1.1.3, Jinja2, MarkupSafe, setuptools).
- `mypy` ignora los stubs ausentes de `osqp.*` (como ya hacía con scipy/pandas).

### Añadido

- `config/`: `FrontierConfig`, `SolverConfig`, `BenchmarkConfig`; `ConstraintConfig` con
  `group_limits` (`GroupLimit`) y `global_max_turnover`; el cargador TOML admite listas de tablas
  (`[[constraints.group_limits]]`); `EngineConfig` incorpora las tres secciones nuevas;
  `config/default_engine.toml` declara todos los valores por defecto (20 puntos, tolerancias, OSQP).
- `models/`: enums (`SolverStatus`, `StatusSource`, `ProblemClass`, `OptimizationFamily`,
  `FrontierScope`, `CostTreatment`, `FrontierMethod`, `StrategyID`, `GridScale`, `ThetaGridMode`,
  `GroupDimension`, `CrossCheckPolicy`), `solution.py` (`SolveResult`, `ValidationReport`),
  `frontier.py` (`FrontierPoint`, `PointMetrics`, `CompositionFrontierResult`).
- `costs/` (unión current ∪ composición, coste asimétrico, horizonte E-03, turnover),
  `metrics/` (métricas vectorizadas, contribuciones), `constraints/` (`ConstraintSet`,
  `ConstraintCompiler`, `PreFeasibilityChecker`), `optimizers/` (`OptimizationBackend`,
  `OSQPBackend`, `SolverRouter`, `CanonicalProblem`, mapeo de estados, constructor QP/LP con lifting
  de costes y turnover), `validation/` (`SolutionValidator`), `frontiers/` (sesión, mallas,
  adaptativa, dedup, Pareto, `ContinuousFrontierEngine`), `outputs/` (filas y dataset graficable),
  `benchmark/` (timers, estadísticos, `solver_reuse_benchmark`), `benchmarks/scripts/solver_reuse.py`.
- `universe_validator.py` (DAT-028): con límites de grupo configurados, el atributo de grupo pasa de
  aviso a error.
- Tests: 225 tests nuevos (unitarios por módulo, integración del pipeline B1+B2, propiedades con
  Hypothesis, regresión numérica con `golden/frontiers.json`, reglas de arquitectura). Los
  resultados esperados proceden de fórmulas cerradas, NumPy, SciPy (SLSQP, HiGHS) o análisis por
  tramos; **ningún test usa el propio optimizador como oráculo** (salvo la regresión numérica, que
  solo detecta cambios y no prueba corrección).

### Decisiones e incidencias durante el bloque

- Clarabel no se introduce (A-32): sin caso de uso en el B2. `SOL-005` sigue `NOT_IMPLEMENTED` y el
  router rechaza SOCP/SDP/MIQP/NLP con `RoutingError`; nunca se degradan a OSQP.
- `adaptive_rho_interval` es un parámetro obligatorio y positivo: con `0`, OSQP decide `rho` por
  tiempo de reloj y los resultados dejan de ser reproducibles bit a bit (la reproducibilidad con el
  intervalo fijo está verificada por test).
- OSQP 1.1 deprecó `polish` (se usa `polishing`) y su `solve()` cambiará el valor por defecto de
  `raise_error` (se pasa `raise_error=False` explícito). Una actualización con `lower > upper` o con
  NaN no lanza excepción en OSQP (solo imprime): el backend valida antes de actualizar.
- OSQP devuelve un `x` sin sentido cuando el estado no es óptimo: el backend solo expone `x` si el
  estado es `OPTIMAL`/`OPTIMAL_INACCURATE` y finito.
- La segunda etapa de MaxReturn (`μᵀw ≥ R* − ε`) puede reducir el retorno en ~ε: los tests de
  extremos usan tolerancia `1e-7`. **[Sustituido en la remediación: ver "Bloque 2 — Remediación"; la
  franja `R* − 1e-9` era el origen de H-1.]**
- Test de dominancia NET/POST_COST: comparar contra puntos discretos de la malla NET no es válido
  (un punto POST_COST puede quedar entre dos puntos NET); se resuelve, por cada punto POST_COST, el
  problema NET de retorno objetivo con su mismo retorno neto.

### Tests ejecutados (gate del Bloque 2)

| Comprobación | Resultado |
|---|---|
| `pytest` (suite completa) | **477 passed, 0 failed, 0 skipped** (252 del Bloque 1 + 225 nuevos) |
| — `-m property` (Hypothesis) | 10 passed |
| — `-m architecture` | 12 passed |
| — `-m integration` | 11 passed |
| — `tests/unit/optimizers`, `validation`, `frontiers`, `constraints` | 174 passed |
| `mypy --strict` | 0 errores en 96 ficheros |
| `ruff check .` | 0 violaciones |
| `ruff format --check .` | 177 ficheros formateados |
| Control de mutaciones (script temporal, no versionado) | 18/18 mutaciones detectadas (coste sin escalar por θ, `P=Σ`, turnover sin ½, compra/venta intercambiadas, horizonte ignorado, signo del coste en la fila de retorno, validador sin presupuesto o sin cota superior, HOLD_OR_REDUCE que aumenta, dominancia de Pareto errónea, dedup sin pesos, turnover mínimo sin residuo, reintento en frío desactivado, `*_inaccurate` → INFEASIBLE, sin reutilización de workspace, POST_COST = NET, neto sin costes, θ de referencia sin dividir). La primera pasada dejó **1 superviviente** (turnover mínimo sin ajuste de residuo); se añadió `test_forced_turnover_accounts_for_a_current_portfolio_that_does_not_sum_to_one` y el mutante pasó a detectarse |

### Benchmark real (BEN-003)

Ejecución: `benchmarks/scripts/solver_reuse.py --assets 20 --points 20 --seed 7` (5 repeticiones + 1
calentamiento por modo; Windows 11, un proceso; OSQP 1.1.3, NumPy 2.5.3). Resultado completo con
metadatos en `benchmarks/results/solver_reuse_20assets_20260923T152123Z.json`. Media de la frontera
completa (20 puntos, incluye MinVariance y MaxReturn):

| Frontera | COLD_SETUP | WORKSPACE_REUSE | WARM_START |
|---|---|---|---|
| GROSS / risk aversion | 853,6 ms (21 setups) | 688,2 ms (2 setups) | 268,0 ms (2 setups) |
| GROSS / target return | 280,7 ms | 520,1 ms | 696,8 ms |
| NET / risk aversion | 366,9 ms | 499,3 ms | 231,7 ms |
| NET / target return | 363,3 ms | 514,4 ms | 255,7 ms |

Los tres modos producen los mismos pesos (`max |Δw| = 0`). **Lectura honesta:** reutilizar el
workspace *sin* arranque en caliente fue más lento que crear uno nuevo por punto en 3 de las 4
fronteras, y el arranque en caliente solo mejoró en 3 de las 4 (empeoró en GROSS/target return). No se
ha investigado la causa (hipótesis no verificada: `rho` adaptado que se conserva entre resoluciones).
**[Corrección posterior: estas cifras no son atribuibles al reuse/warm start; estaban dominadas por
MaximumReturn (H-1, `AUDIT_BLOCK_2.md` M-2). Las cifras válidas están en "Bloque 2 — Remediación".]**
Es una única máquina y una única semilla: no se extrae ninguna conclusión general ni se afirma una
aceleración; el benchmark queda como herramienta para el Bloque 5.

### Auditoría interna previa al cierre

- **Hardcoding:** `test_no_business_numeric_literals` en verde (todo literal numérico de negocio
  procede de configuración); todos los campos de `FrontierConfig`, `SolverConfig`, `BenchmarkConfig`
  y las extensiones de `ConstraintConfig` se consumen fuera de `config/` (comprobado por búsqueda).
- **Stubs y parámetros ignorados:** `test_no_disguised_stubs` en verde; la configuración rechaza
  parámetros declarados pero ignorados (`initial_frontier_points`/`adaptive_gap_tolerance` sin
  `adaptive`, `theta_min/max` sin `EXPLICIT`).
- **Dependencias:** grafo de capas acíclico (`test_import_graph_is_acyclic`); `validation` no importa
  `optimizers`/`frontiers`/`osqp` (`test_validator_is_independent_of_solvers`): el solver trabaja con
  el lifting `b/s` y el validador recalcula turnover, costes y política desde los pesos.
- **Bloque 3:** no existe ningún módulo de B3–B6 (`test_no_later_block_packages_exist`).
- **Duplicación conocida (baja) [resuelta en la remediación, R2-05]:** `ConstraintSet` repite en pocas líneas la resolución
  `spec → config` de la política de restringidos que ya existe en
  `data/validation/portfolio_validator.py::effective_restricted_policy` (la capa `constraints` no puede
  importar `data`); pendiente de unificar si se mueve la función a `models`.

### Trazabilidad

`VALIDATED`: +81 (139 en total; ver `TRACEABILITY.md`). `PARTIAL`: 38. `NOT_IMPLEMENTED`: 139 (todos
los de B3–B6 más los residuales de B2 declarados abajo). Ningún requisito de B3–B6 cambia de estado.

### Limitaciones conocidas

- `SOL-005` (Clarabel), `TC-011` (`K_E`; `PARTIAL` tras la remediación) y `CON-010/011/012/015/016/017/019`, `FEA-002/005/006/008`
  quedan `NOT_IMPLEMENTED` por asignación a B3/B4.
- `CON-014`: la caja funciona como activo ordinario con Σ singular PSD; no hay construcción
  automática del activo sintético `CASH` (A-12). `CON-020`: sin overrides de grupo por cartera.
- `SOL-014`/`SOL-002`: reintento en frío con el mismo solver; la verificación cruzada con Clarabel y
  su mapeo de estados son del B4. `INSUFFICIENT_PROGRESS` existe en el enum pero OSQP no lo produce.
- Espaciado del grid de retorno objetivo solo uniforme (A-17 "espaciado configurable" queda cubierto
  por la frontera adaptativa, no por un modo de espaciado); theta admite `LINEAR`/`LOG`.
- `MET-002`: verificado por inspección; no se ha ejecutado un benchmark con `K` grande.
- Sin cartera actual solo existe la frontera bruta de una composición explícita. **[La exigencia de
  que la composición contenga todos los activos actuales se eliminó en la remediación (R2-03).]**
- `EligibleFlag`/`LiquidityFlag` no se aplican todavía (`EligibilityFilter` es B3): un activo
  mantenido pero no elegible se trata como cualquier otro de la composición.
- Validado solo con Python 3.13.6 en Windows 11. Los tiempos del benchmark dependen de la máquina.
- `1.-Version Anterior/` no se ha usado.

### Estado

`BLOCK_2_STATUS = PASS` (pendiente de auditoría independiente; sin commit, merge ni tag, según
instrucciones).

---

## [Bloque 2 — Remediación tras AUDIT_BLOCK_2] — 2026-09-23

### Alcance

Solo los hallazgos accionables de `AUDIT_BLOCK_2.md` (`AUDIT_STATUS = PASS_WITH_CHANGES`) y su
revalidación. **No** se ha avanzado al Bloque 3 (sin `CandidateEngine`, Beam Search, Global Candidate
Frontier, MIQP, SCIP, multiprocessing, `SharedMemory` ni persistencia; comprobado por
`test_no_later_block_packages_exist`, `test_no_forbidden_imports` y búsqueda en el diff). Sin commit,
merge, push, tag ni Pull Request. `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`,
`IMPLEMENTATION_PLAN.md`, `CLAUDE.md` y `AUDIT_BLOCK_1.md` sin modificar; `AUDIT_BLOCK_2.md`
conservado como evidencia histórica (ver "Incidencias").

### Baseline de no regresión

- Rama `block2-continuous-frontier`; etiqueta `block1-validated` presente.
- Antes de modificar código: `pytest` → **477 passed** (baseline de la entrada del Bloque 2).
- Reproducción de H-1 antes de cambiar nada (`benchmarks/scripts/frontier_robustness.py`, mismas
  semillas y generador que la auditoría): 96 fronteras, **72 sanas, 24 degradadas, 4 sin frontera**
  (39,7 s): coincide exactamente con la auditoría.

### Tests del Bloque 1 modificados en el Bloque 2 (conclusión de la auditoría)

`AUDIT_BLOCK_2.md` (sección BLOCK_1_TEST_CHANGES) determinó que los **cuatro** tests del Bloque 1
tocados por el Bloque 2 (`test_config_hashing.py::test_snapshot_is_complete_canonical_json`,
`test_architecture_rules.py::test_layered_dependencies`, `::test_no_later_block_packages_exist` y
`::test_no_forbidden_imports`) se modificaron **por cambio de alcance y no por debilitamiento de
aserciones**: las versiones originales extraídas de `block1-validated` fallan exactamente por los
paquetes, secciones de configuración y el import de `osqp` que el Bloque 2 introduce legítimamente, y
las aserciones equivalentes se conservan (igualdad exacta del snapshot; grafo de capas más estricto
para `validation`; `osqp` confinado a su backend). Reserva heredada de la auditoría (L-3):
`test_no_later_block_packages_exist` es lista negra de nombres dentro de paquetes ya permitidos. En
la remediación **no se han modificado** tests del Bloque 1 existentes (solo se añadieron dos tests al
final de `test_architecture_rules.py`); los 252 tests del baseline del Bloque 1 pasan.

### H-1 — MaximumReturn (corregido)

- **Etapa 1 (R2-01):** el LP se resuelve con HiGHS (`scipy.optimize.linprog(method="highs")`,
  `optimizers/highs_backend.py`); OSQP sigue siendo el backend QP. Traducción de la forma canónica
  (igualdades, desigualdades, cotas, lifting de costes/turnover, grupos, política de restringidos,
  fila de retorno neta) sin cambiar el constructor; estados mapeados sin colapsarlos (OPTIMAL,
  MAX_ITERATIONS/TIME_LIMIT, INFEASIBLE, UNBOUNDED, NUMERICAL_ERROR, UNKNOWN) con el texto nativo y
  diagnósticos (iteraciones, residuo primal, multiplicadores por fila). Sin dependencias nuevas.
- **Etapa 2 (R2-02):** el primer intento (ampliar la holgura en la franja `R* − ε`) **no funcionó**:
  con ε ∈ {1e-9 … 1e-7} seguía habiendo 11-12 de 48 fronteras degradadas y, incluso con 1e-5, OSQP
  seguía declarando `primal infeasible` espuriamente en varios casos (su `eps_prim_inf` por defecto es 1e-4, mucho mayor que
  la franja). La causa es el conjunto casi degenerado, no el valor de ε. La corrección es imponer la
  **cara óptima del LP** (por complementariedad, filas con multiplicador `|y_i| >
  lp_feasibility_tolerance` fijadas como igualdades) y, además, `retorno ≥ R* − tol` con
  `tol = max(abs, rel·|R*|)` en `SolverConfig` (`max_return_tie_abs_tolerance = 1e-8`,
  `max_return_tie_rel_tolerance = 1e-7`, unidades de retorno anualizado; única fuente de verdad,
  `frontier.max_return_tie_epsilon` eliminado). La etapa 2 usa un workspace OSQP propio (no
  contamina el `rho` del compartido). La holgura no relaja el objetivo financiero: en la cara el
  retorno es `R*`; los pesos coinciden con el óptimo del LP (desviación medida ~1e-12).
- **NET:** el LP maximiza el retorno neto real `μᵀw − TC(w)`, incluidas las liquidaciones.
- **Reproducción tras la corrección** (mismas semillas y generador, 96 fronteras, 7,9 s):
  **96 sanas, 0 degradadas, 0 sin frontera** (antes 72 / 24 / 4).

### Activos actuales fuera de la composición (R2-03, M-3)

Eliminada la limitación "la composición debe contener todos los activos actuales" (ejemplo:
actual `A,B,C,D`, composición `A,B,E,F`: `C` y `D` se venden por completo). Sin `CandidateEngine`.
Aplicada de forma coherente en costes de transacción (`K_E` constante), turnover
(`0.5·(Σ_comp|w−w0| + Σ_retirados|w0|)`), `MaxTurnover` (`T − exit_turnover`), retorno neto y
objetivo neto (`+ K_E/H` en la fila de retorno), MaximumReturn NET, factibilidad previa
(`REMOVED_ASSETS_TURNOVER_ABOVE_MAX` e `INFEASIBLE` antes de llamar al solver; turnover mínimo forzado
con el offset), `SolutionValidator`, métricas de la cartera actual (sobre la unión) y salidas.
Restringidos retirados: `HOLD_OR_REDUCE` (puede reducirse a cero) y `FORCE_LIQUIDATE` (la venta
completa la satisface) son compatibles; `FREEZE_WEIGHT` con peso > 0 no puede salir de la composición
(`FREEZE_WEIGHT_EXITED`, rechazo previo al solver; el validador lo re-deriva de forma independiente).
Los valores esperados de los tests se calculan de forma independiente (NumPy, `linprog`, SLSQP).

### Frontera adaptativa NET (R2-04, M-1)

La puntuación de huecos y curvatura usa el retorno del tratamiento: `GROSS` bruto, `NET` neto,
`POST_COST_GROSS` neto de los pesos `GROSS` (la curva publicada es (volatilidad, retorno tras
costes); no se resuelve nada nuevo). `test_net_adaptive_frontier_is_scored_with_the_net_return` está
diseñado para fallar si NET vuelve a puntuar con retorno bruto (verificado por mutación).

### Trazabilidad y documentación (M-4, L-6)

`OPT-007` y `FRN-006`: módulo real (`frontiers/session.py`, `optimizers/highs_backend.py`) y `VALIDATED`
**solo** tras la corrección, con tests específicos ejecutados en verde. Corregidos los 16
identificadores previstos inexistentes de filas `VALIDATED`/`PARTIAL` (`check_budget`, `check_bounds`,
`check_turnover`, `check_groups`, `add_cost_lifting`, `PreFeasibilityChecker.check_bounds`,
`composition_counts`, `Availability`, `SolverVersion`, etc.; los restantes son fórmulas o rutas
explícitamente marcadas "prevista" para B3–B6); cabecera `476` → `558`. `TC-011`: `NOT_IMPLEMENTED` →
`PARTIAL`. Conteo actual: **139 `VALIDATED`, 39 `PARTIAL`, 0 `IMPLEMENTED`, 138 `NOT_IMPLEMENTED`**
(316). Ningún requisito de B3–B6 se marca como implementado. `ARCHITECTURE.md` §3.3 registra R2-01…R2-05.

### L-1 — Política de restringidos

La precedencia `spec → global` vive en `models/portfolio.py::resolve_restricted_policy`, usada por
`ConstraintSet` y por `data/validation/portfolio_validator.py` (misma función, sin dependencias
circulares). La semántica HOLD/FREEZE/FORCE **sigue duplicada a propósito** en `ConstraintCompiler` y
`SolutionValidator` para conservar la independencia del validador (§44);
`tests/unit/validation/test_policy_consistency.py` garantiza que aceptan exactamente los mismos pesos.

### Benchmark repetido (M-2)

`benchmarks/scripts/solver_reuse.py --assets 20 --points 20 --seed 7` (5 repeticiones + 1
calentamiento por modo; Windows 11, un proceso; OSQP 1.1.3, SciPy 1.18.1). Resultado completo:
`benchmarks/results/solver_reuse_20assets_20260923T172754Z.json` (el JSON anterior se conserva como
histórico). Media en ms de la frontera completa (20 puntos) y desglose (`min_variance` / `max_return`
/ `grid`); iteraciones de la malla:

| Frontera | Modo | Total | MinVar | MaxRet | Malla | Iter. malla |
|---|---|---|---|---|---|---|
| GROSS / aversión | COLD_SETUP | 158,9 | 7,0 | 20,6 | 126,3 | 1425 |
| | WORKSPACE_REUSE | 53,9 | 7,3 | 20,7 | 20,9 | 1275 |
| | WARM_START | 47,4 | 6,6 | 19,8 | 17,2 | 925 |
| GROSS / retorno objetivo | COLD_SETUP | 164,0 | 6,8 | 21,0 | 131,9 | 3650 |
| | WORKSPACE_REUSE | 63,5 | 7,3 | 21,3 | 30,5 | 4875 |
| | WARM_START | 65,5 | 7,3 | 21,1 | 32,2 | 5150 |
| NET / aversión | COLD_SETUP | 176,7 | 9,0 | 24,8 | 138,0 | 2025 |
| | WORKSPACE_REUSE | 64,4 | 7,2 | 23,2 | 29,5 | 1800 |
| | WARM_START | 63,8 | 7,6 | 23,0 | 29,2 | 1950 |
| NET / retorno objetivo | COLD_SETUP | 183,3 | 7,6 | 23,6 | 147,8 | 4175 |
| | WORKSPACE_REUSE | 89,3 | 8,1 | 24,8 | 51,8 | 5100 |
| | WARM_START | 83,8 | 7,5 | 23,4 | 47,8 | 5125 |

Los tres modos producen los mismos pesos (`max |Δw| = 0`). **Lectura honesta (una máquina, una
semilla, un tamaño):** el coste de los extremos (~20-25 ms, MaxReturn incluido) no depende del modo;
la reutilización del workspace reduce el tiempo de la malla entre ~2,8× y ~6× (126 → 21 ms en
GROSS/aversión; 148 → 52 ms en NET/objetivo) porque elimina ~18 `setup`, aun cuando en las mallas de
retorno objetivo **aumenta** las iteraciones (3650 → 4875-5150 en GROSS/objetivo). El warm start solo
reduce iteraciones en GROSS/aversión (925 frente a 1275); en el resto está dentro de ±7 % del reuse
sin warm start en tiempo y en GROSS/objetivo es ligeramente peor. **No se afirma que el warm start
siempre acelere.** Las cifras del Bloque 2 original (853,6 ms, etc.) no son comparables: estaban
dominadas por el defecto de MaximumReturn. El desglose por fase y las iteraciones totales/extremos/
malla están ahora en `FrontierDiagnostics` (`min_variance_time`, `max_return_time`, `grid_time`,
`total_iterations`, `endpoint_iterations`).

### Tests ejecutados (gate de la remediación)

| Comprobación | Resultado |
|---|---|
| `pytest` (suite completa) | **558 passed, 0 failed, 0 skipped** (477 previos + 81 nuevos) |
| — `-m "property or architecture or integration"` | 35 passed |
| — MaximumReturn (`test_maximum_return*.py`) | 30 passed |
| — NET / POST_COST (`test_net_*`, `test_post_cost_gross.py`) | 15 passed |
| — target return | 7 passed |
| — activos retirados (`test_removed_assets.py`) | 16 passed |
| — frontera adaptativa | 12 passed |
| — `SolutionValidator` (`tests/unit/validation`) | 22 passed |
| — reuse de workspace y warm start (optimizers, risk aversion grid, benchmark) | 76 passed |
| `mypy --strict portfolio_engine` | 0 errores en 97 ficheros |
| `ruff check .` | 0 violaciones |
| `ruff format --check --exclude AUDIT_BLOCK_2.md .` | 183 ficheros formateados |
| Control de mutaciones (scripts temporales, no versionados) | 4/4 detectadas: etapa 2 sin cara óptima, `K_E` omitido de la fila de retorno neta, turnover de retirados omitido, NET adaptativa con retorno bruto |

### Auditoría interna previa al cierre

- **Hardcoding:** `test_no_business_numeric_literals` (sin ampliar) en verde; los parámetros nuevos
  (`lp_feasibility_tolerance`, `lp_max_iterations`, `max_return_tie_abs/rel_tolerance`) solo están en
  `default_engine.toml` y se consumen desde `SolverConfig`; `test_max_return_tolerance_has_a_single_source`.
  La tabla de estados de HiGHS se indexa por posición para no introducir literales numéricos.
- **Parámetros declarados y no usados:** eliminados `frontier.max_return_tie_epsilon` y el parámetro
  `frontier_config` de `FrontierSession` (dejó de usarse).
- **Dependencias:** grafo acíclico; `scipy.optimize` confinado a `optimizers/highs_backend.py`; `osqp`
  confinado a `optimizers/osqp_backend.py`; `validation` no importa `optimizers`/`frontiers`.
- **Stubs:** `test_no_disguised_stubs` en verde. **Bloque 3:** ausente (ver Alcance).

### Incidencias

- `ruff format .` (ruff 0.16.8) también reformatea los bloques de código de los ficheros `.md`: durante
  la remediación reescribió el bloque `python` de `AUDIT_BLOCK_2.md` (separó
  `cfg = base_config(); eng = ...` en dos líneas). Se restauró la línea original (344 líneas, contenido
  idéntico) y se dejó una advertencia en el README. Consecuencia: `ruff format --check .` sobre la raíz
  reporta 1 fichero (`AUDIT_BLOCK_2.md`) mientras se conserve intacto; excluyéndolo, 183 ficheros
  están formateados.
- La primera hipótesis para la etapa 2 (ampliar ε) resultó insuficiente y se descartó tras medirla
  (ver H-1).

### Hallazgos de la auditoría no abordados (fuera del alcance solicitado)

L-2 (fragmentación menor: `explicit_portfolios.py`, envoltorios de grids), L-3 (lista negra de nombres
en `test_no_later_block_packages_exist`), L-4 (`COLD_SETUP` hace `setup` con `q = 0` y luego `update`),
L-5 (`status_polish` de OSQP no se inspecciona), L-7 (`SolverConfig` mezcla solver, validador y flags
de benchmark), L-8 (control de mutaciones no versionado; los cuatro de esta remediación tampoco) e I-1…I-7.

### Limitaciones conocidas

- La identificación de la cara óptima depende de `lp_feasibility_tolerance`: una fila con un
  multiplicador genuino por debajo de esa tolerancia no se fija (el coste en retorno está acotado por
  ese multiplicador, y `retorno ≥ R* − tol` sigue garantizado).
- `linprog` no expone warm start: el LP se resuelve siempre en frío (un LP por frontera).
- El código `4` de `linprog` (dificultades numéricas, incluido "inviable o no acotado" de presolve) se
  mapea a `NUMERICAL_ERROR`, nunca a `INFEASIBLE`.
- `current_metrics` de la cartera actual con activos retirados es `None` si algún activo actual no está
  en el modelo de riesgo.
- Validado solo con Python 3.13.6 en Windows 11, `osqp 1.1.3` y `scipy 1.18.1`; los tiempos dependen de
  la máquina y el benchmark es de un solo tamaño y semilla.
- `TC-011` permanece `PARTIAL`: falta la integración con la generación de composiciones (B3) y TST-014.

### Estado

`BLOCK_2_REMEDIATION_STATUS = PASS` (pendiente de auditoría independiente de cierre; sin commit,
merge ni tag, según instrucciones).

---

## [Bloque 2 — Cierre documental y de tooling] — 2026-09-24

Tras `AUDIT_BLOCK_2_CLOSURE.md` (`AUDIT_BLOCK_2_CLOSURE = PASS`). Sin cambios de código productivo,
de comportamiento, de requisitos ni de estados de `TRACEABILITY.md`.

### Cambios

- **Ruff (`pyproject.toml`):** nueva sección `[tool.ruff.format]` con `exclude = ["AUDIT_BLOCK_*.md"]`.
  Excluye los informes de auditoría **solo del formateador** (el formateador de Markdown de ruff 0.16
  reescribía el bloque de código de `AUDIT_BLOCK_2.md`); `ruff check` sigue activo sobre todo el
  repositorio. `ruff format --check .` en la raíz vuelve a pasar sin tocar los informes.
- **`ARCHITECTURE.md` §3.3:** los diagnósticos por fase (M-2), antes un párrafo sin identificador, pasan
  a la decisión **`R2-06`** (fila propia en la tabla; contenido idéntico, sin cambio de comportamiento).
  Cierra la observación `ACCEPT_WITH_CHANGES` de `AUDIT_BLOCK_2_CLOSURE.md`.

### Verificación

Los resultados de las ejecuciones de este cierre constan en el informe final de la sesión (pytest,
mypy, ruff, SHA-256 de los informes). Los informes `AUDIT_BLOCK_*.md` no se modificaron.

### Estado

`BLOCK_2_FINAL_CLOSURE` según el resumen de la sesión; sin commit, merge ni tag.


---

## [Bloque 3 — CandidateEngine, sustituciones y Global Candidate Frontier] — 2026-09-24

### Alcance

Bloque 3 de `IMPLEMENTATION_PROMPTS.md`, sobre el baseline `block2-validated` (commit `6af836c`, rama
`block3-candidate-engine`). RequirementIDs de la fase: `CFG-009`, `CON-010`, `CON-011`, `CON-012`,
`CON-013`, `CON-019`, `CON-022`, `FEA-002`, `FEA-006`, `OPT-002`, `TC-003`, `TC-011`, `CAN-001` … `CAN-022`,
`FRN-002`, `FRN-003`, `FRN-017`, `VAL-010`, `DAT-013`, `PAR-006`, `PAR-009`, `PAR-010`, `REP-003`, `OUT-004`,
`OUT-009`, `TST-012`, `TST-014`, `TST-015`, `TST-016`, `VIS-002` y el nuevo `BEN-009`.

Módulos permitidos usados: `config/candidate_config.py`, `candidates/`, `frontiers/global_frontier.py` (y
`frontiers/candidate_evaluator.py`), `constraints/integer.py`, `constraints/feasibility.py`,
`models/composition.py`, `models/universe_index.py`, `parallel/determinism.py` (solo semillas y orden estable),
`validation/composition_validator.py`, `outputs/candidate_*.py`, `benchmark/candidate_suite.py`. Fuera de
alcance (no tocado): escenarios, SOCP, CVaR, robustez, MIQP/SCIP, `NONCONVEX_RESEARCH`, multiprocessing,
`SharedMemory`, batches HPC, DuckDB, SQL Server, caché y persistencia (verificado por
`tests/unit/test_architecture_rules.py::test_no_later_block_packages_exist`).

### Baseline de no regresión (MASTER_SPEC §80)

- Antes de escribir código: rama `block3-candidate-engine`, tag `block2-validated` presente, árbol limpio.
- `pytest -q`: **558 passed** (44 s); `mypy --strict portfolio_engine`: 97 ficheros sin errores; `ruff check .`
  y `ruff format --check portfolio_engine tests benchmarks`: en verde.

### Añadido

- **Configuración:** `CandidateConfig`, `ScreeningWeights`, `ExplorationMix` (`config/candidate_config.py`),
  sección `[candidates]` (y subtablas) en `config/default_engine.toml`; `EngineConfig.candidates`
  obligatorio; el loader admite subtablas TOML anidadas.
- **Índices en tres niveles (DAT-013, TST-015):** `EligibleUniverseIndex` y `CompositionIndexMap`
  (`models/universe_index.py`); la cartera se mapea siempre por `AssetID`.
- **`EligibilityFilter`** (`candidates/eligibility.py`): roles A–E (mantenido, obligatorio, solo liquidable,
  salida obligatoria, elegible nuevo, excluido) según `EligibleFlag`, `LiquidityFlag` (política explícita
  para banderas desconocidas), restricciones, `InvestmentUniverse` y `RestrictedExistingPositionPolicy`.
- **`CandidateScreening`** (`candidates/screening.py`): 9 señales vectorizadas con dirección y normalización
  definidas (`RANK`/`ZSCORE`), pesos configurables, política explícita de datos ausentes; separado del
  objetivo optimizado.
- **`ExplorationPolicy`**, **`SwapGenerator`** (1/2/3-swap, `ADD`/`DROP`), **`LocalSearch`**, **`BeamSearch`**,
  `NeighborhoodExpander`, `CompositionFactory` (reutiliza el compilador y la factibilidad previa del B2),
  `ProjectedWeightsEvaluator` y `QPCompositionEvaluator`, `CompositionHash`, `CandidateDiagnostics`,
  **`CandidateEngine`** (`generate_candidate_compositions -> list[CandidateComposition]`, arranque en frío,
  perfiles de aversión al riesgo, validación independiente de cada composición devuelta).
- **`GlobalCandidateFrontierEngine`** (`frontiers/global_frontier.py`): frontera continua por composición con el
  motor del B2, unión de puntos, deduplicación entre composiciones, envolvente de Pareto global (`global_pareto`).
  `FrontierScope.GLOBAL_CANDIDATE_FRONTIER`.
- `constraints/integer.py` (nuevos activos, swaps, cardinalidad), `check_cardinality` (FEA-002),
  `validation/composition_validator.py` (VAL-010), `parallel/determinism.py` (`derive_seed`, `sequence_key`,
  `tie_break_key`), `models/composition.py`, `outputs/candidate_schemas.py`/`candidate_builders.py`
  (`CandidateCompositions`, `CandidateDiagnostics`, puntos globales, `visualization_dataset`),
  `benchmark/candidate_suite.py` y `benchmarks/scripts/candidate_engine.py` (BEN-009).
- Tests nuevos: **238** (ver más abajo); marcador `performance` en `pyproject.toml`.

### Modificado en módulos de bloques anteriores

Solo ampliaciones necesarias; el comportamiento validado de B1/B2 no cambia:
`models/enums.py` (nuevos enums y `FrontierScope.GLOBAL_CANDIDATE_FRONTIER`), `models/frontier.py`
(`GlobalFrontierPoint`, `GlobalFrontierResult`), `models/universe_index.py`, `config/engine_config.py` y
`config/loader.py`, `constraints/feasibility.py` (`check_cardinality`), `exceptions.py` (`CandidateError`), y los
`__init__.py` de `config`, `constraints`, `frontiers`, `outputs`, `validation`, `benchmark`.

Tests de bloques anteriores modificados (ampliación legítima de alcance; ninguno se debilitó):

1. `tests/unit/config/test_config_hashing.py::test_snapshot_is_complete_canonical_json`: el snapshot de
   `ConfigHash` incluye ahora la sección `candidates` (una línea añadida al conjunto esperado de claves).
2. `tests/unit/test_architecture_rules.py`: `LATER_BLOCK_PACKAGES` deja de prohibir `candidates`,
   `frontiers/global_frontier.py`, `constraints/integer.py` y `parallel/` (solo `determinism.py`; se prohíben
   `parallel/batching.py`, `shared_data.py`, `worker.py`, `executor.py`, `threading_control.py`);
   `ALLOWED_DEPENDENCIES` incorpora `candidates` y `parallel` y las nuevas aristas de `frontiers` y `benchmark`;
   y se añaden dos reglas nuevas (sin `hash()` ni estado aleatorio global; `candidates` independiente de
   `optimizers`/`frontiers`/SciPy/OSQP). La cobertura anterior de esas reglas se conserva.

### Decisiones e incidencias durante el bloque

- Diseño registrado en `ARCHITECTURE.md` §3.4 (13 puntos): sin `tabu.py` ni `engine.py`; el evaluador exacto se
  inyecta desde `frontiers` para no crear dependencias `candidates → optimizers/frontiers`; un perfil de aversión
  al riesgo por región de la frontera; `parallel/determinism.py` solo con semillas y orden.
- **Cota inferior de la búsqueda:** el evaluador `PROJECTED_WEIGHTS` nunca sobrestima la utilidad óptima
  (verificado contra SLSQP independiente); por eso los `estimated_*` se etiquetan como estimaciones.
- **Presupuesto de la búsqueda local:** en una primera versión el haz agotaba el presupuesto y la búsqueda local
  nunca se ejecutaba (detectado por `test_diagnostics_reconstruct_the_search`); cada fase tiene ahora su propio
  presupuesto `max_evaluations`.
- **Rendimiento:** el primer benchmark (universo de 50 activos) tardó 28 s por cartera; el perfilado mostró que el
  refinamiento (proyecciones y costes recalculados por iteración) dominaba. Se precalcularon los costes de la
  composición, se vectorizó el mapa elegible↔local, se memoizó el hash por composición y se redujo el ejemplo
  de configuración (`max_evaluations` 200, `refinement_iterations` 15). Los resultados publicados son de la
  versión final.
- Errores del diseño inicial de algunos tests corregidos durante el desarrollo (no de la implementación): cotas
  infactibles generadas por Hypothesis, covarianza cruda no PSD frente a la reparada, degeneración de fronteras
  con composiciones de un solo portafolio eficiente.
- `ruff format` reformatea los bloques de código de los `.md` (recordatorio de la memoria del proyecto): el bloque
  de `README.md` se ajustó a la salida del formateador; `AUDIT_BLOCK_*.md` no se tocó.

### Tests ejecutados (gate del Bloque 3)

Ejecuciones reales:

- `pytest -q`: **796 passed**, 0 failed, 0 skipped en 201,31 s (baseline 558 + 238 nuevos; los 558 originales
  pasan sin cambios salvo los dos ajustes de arriba).
- `mypy --strict portfolio_engine`: 122 ficheros, sin errores (baseline: 97).
- `ruff check .`: All checks passed. `ruff format --check .` (raíz): 233 ficheros ya formateados.

Tests nuevos relevantes: contractual crítico `tests/integration/test_global_frontier_multi_composition.py`
(`len(candidates) > 1` y `len(unique(CompositionID)) > 1` antes y después de Pareto, 3 tratamientos × 2 métodos,
Pareto contrastado con fuerza bruta); `tests/unit/costs/test_liquidation.py` (A 10 %/B 90 % → C 10 %/B 90 %);
`tests/unit/candidates/test_index_mapping.py` (activos elegibles no consecutivos); casos adversariales donde el
ranking por alpha individual elegiría mal por covarianza o por coste, con óptimo exacto SLSQP; beam ≠ greedy
(`B = 3` supera a `B = 1` en tres semillas); búsqueda local con óptimo local y global comprobados por enumeración;
acuerdo exhaustivo (3 políticas × 495 composiciones) entre `EligibilityFilter` y el validador independiente;
estimaciones frente a óptimo exacto; MaxTurnover; determinismo con `PYTHONHASHSEED` distintos; memoria con
`tracemalloc` (N = 700).

### Benchmark real (BEN-009; medición local, un proceso, sin paralelismo)

`benchmarks/results/candidate_engine_20260924T100129Z.json` (commit `6af836c` + cambios sin commit, Python 3.13.6,
Windows 11, 1 warm-up + 3 repeticiones, cartera de 20 activos, semilla 7, `default_engine.toml`). Medias por cartera:

| Universo | Tratamiento | Screening | Generación de candidatos | Fronteras finalistas | Pareto global | Total |
|---:|---|---:|---:|---:|---:|---:|
| 50 | GROSS | 0,100 s | 9,284 s | 0,924 s | 10,5 ms | 10,219 s |
| 50 | NET | 0,073 s | 8,423 s | 1,075 s | 9,5 ms | 9,508 s |
| 200 | GROSS | 0,086 s | 8,657 s | 1,020 s | 11,7 ms | 9,689 s |
| 200 | NET | 0,083 s | 9,092 s | 1,280 s | 12,4 ms | 10,385 s |
| 700 | GROSS | 0,101 s | 8,212 s | 0,829 s | 10,8 ms | 9,052 s |
| 700 | NET | 0,120 s | 9,190 s | 1,036 s | 10,8 ms | 10,237 s |

Cada ejecución generó 12 composiciones tras evaluar 1.200 (presupuesto agotado: 3 perfiles × (haz 200 + búsqueda
local 200)), 240 puntos de frontera y una envolvente con 10-11 composiciones. Observaciones: el screening es
< 1,3 % del tiempo; la generación (≈ 7 ms por composición evaluada) domina; el coste no crece del universo de 50 al
de 700 activos (no hay copias `O(N²)` por cartera); un solo perfil y una máquina no son rendimiento de producción.

### Auditoría interna previa al cierre

Revisado el diff frente a `block2-validated`: candidatos realmente múltiples (tests y benchmark); haz no greedy
(`test_a_wider_beam_finds_compositions_the_greedy_path_misses`); la raíz es la cartera actual y se conserva como
referencia; índices por `AssetID`; ventas completas y costes NET verificados con cálculo manual y con SLSQP;
Pareto global contrastado con fuerza bruta; sin literales de negocio en código (`test_no_business_numeric_literals`);
sin parámetros ignorados (`test_every_candidate_parameter_is_consumed_by_the_engine_code`); sin stubs
(`test_no_disguised_stubs`); grafo de importaciones acíclico y capas respetadas; sin código de B4–B6.

### Trazabilidad

316 → 317 requisitos (`BEN-009`) **[superado por la remediación: `BEN-009` se retiró como requisito, total 316]**. `VALIDATED` 139 → 182; `PARTIAL` 39 → 40; `NOT_IMPLEMENTED` 138 → 95. Pasan a
`PARTIAL` (compartidos con bloques posteriores): `CON-010`, `CON-011`, `CON-019` (MIQP exacto B4), `CON-012`
(solo `LiquidityFlag`), `OPT-002` (sin `engine.py`), `PAR-010` y `REP-003` (B5). `CAN-014` (Tabu, opcional) y
`FEA-006` siguen `NOT_IMPLEMENTED` **[FEA-006 pasa a `PARTIAL` en la remediación]**. `TC-003` y `TC-011` pasan a `VALIDATED` (TST-014 y la integración con la
generación de composiciones están implementados y probados).

### Limitaciones conocidas

- **[Corregido en la remediación (E-10): una posición actual no comprable queda acotada a `w_current` en todas
  las capas.]** El optimizador continuo (B2) no limitaba el **incremento** de peso de una posición actual no
  elegible; el Bloque 3 solo impedía introducir o recomprar posiciones nuevas. La restricción de participación en ADV/NAV (A-11) no está
  implementada (`CON-012` `PARTIAL`, `FEA-006` `NOT_IMPLEMENTED`).
- La cardinalidad se garantiza en la generación discreta (`SWAP`/`ADD`/`DROP`), no con una formulación MIQP exacta
  (Bloque 4); no hay medida del gap frente al óptimo exacto (`MIP-*`).
- `PROJECTED_WEIGHTS` exige cotas de peso finitas tras el ajuste por presupuesto (con `long_only = false` y sin
  cotas usar `QP_UTILITY`) y solo comprueba después las restricciones de grupo y turnover (`violations`).
- La búsqueda es heurística: un óptimo global del espacio de composiciones no está garantizado y el vecindario de
  2-/3-swap está restringido a listas cortas (decisión A-18). El coste por composición evaluada (≈ 7 ms) es alto
  para 1.200 carteras en un solo proceso; la paralelización pertenece al Bloque 5.
- No hay caché de resultados (Bloque 5): la frontera de la composición actual se reutiliza solo dentro de una
  misma llamada.
- Validado solo con Python 3.13.6 en Windows 11, `osqp 1.1.3` y `scipy 1.18.1`.

### Estado

`BLOCK_3_STATUS = PASS` según el resumen de la sesión (pendiente de auditoría independiente); sin commit, merge,
push, tag ni PR, según instrucciones.

---

## [Remediación del Bloque 3] — 2026-09-24

Tras `AUDIT_BLOCK_3.md` (`AUDIT_BLOCK_3_STATUS = PASS_WITH_CHANGES`). Detalle y mediciones en
`REMEDIATION_BLOCK_3.md`. Sin commit, merge, push, tag ni PR; sin avance al Bloque 4.

### Baseline de no regresión

`pytest -q` antes de modificar código: **796 passed** (0 failed, 0 skipped) en la rama con el Bloque 3 sin
commit. Los 51 ficheros de test del baseline `block2-validated` se ejecutan de nuevo sobre el código final
(ver «Resultados»).

### Cambios

- **H-1 / E-10 (Existing Non-Buyable Position Policy).** Un activo actual no comprable (`EligibleFlag` o
  `LiquidityFlag` falsos, `LiquidityFlag` desconocido con política conservadora, o fuera del
  `InvestmentUniverse`) y no restringido cumple `0 <= w <= min(w_current, MaxWeight)`; si no está en cartera,
  `w = 0`. Nuevo `models/purchasability.py`; `ConstraintSet.unknown_liquidity_policy`
  (`build_constraint_set` recibe la política); `ConstraintCompiler` fija las cotas y emite
  `NonBuyablePositionRule`; `PreFeasibilityChecker._non_buyable`; `SolutionValidator._non_buyable` (desde
  `w_current`); `EligibilityResult.weight_cap` y screening de entrantes con peso de entrada topado;
  diagnóstico `E10_NON_BUYABLE_POSITIONS_CAPPED_AT_CURRENT_WEIGHT`. Precedencia de E-09 intacta. Enmienda E-10
  en `MASTER_SPEC.md` §12 y Anexo A; `ARCHITECTURE.md` §3.4 (filas 12-15); `README.md`.
- **BEN-009 retirado como requisito** (D-1): total contractual 316; el benchmark queda como evidencia de
  `BEN-001`, `BEN-002`, `BEN-006` (JSON y resultados conservados; el script emite `evidence_for`).
- **FEA-006** `NOT_IMPLEMENTED` → `PARTIAL`: las incompatibilidades por `LiquidityFlag` se detectan antes del
  solver (E-10); el chequeo ADV/NAV de A-11 sigue pendiente de una decisión funcional (no se reasigna).
- **Rendimiento del `CandidateEngine`** (sin cambiar la búsqueda): `composition_id` y `constraint_hash` bajo
  demanda; `composition_hash` con serialización directa; `SolutionValidator._bounds` vectorizado;
  `MemoizedEvaluator` (memoria local de evaluaciones de una generación; `evaluation_cache_hits`). Llamadas a
  funciones por búsqueda −45 %; salida bit a bit idéntica en 4 escenarios. Nuevos
  `benchmarks/scripts/candidate_profile.py` y `benchmarks/scripts/screening_correlation.py`.
- **`max_evaluations`**: contrato explícito (por perfil λ y por fase; tope `perfiles × 2 × máximo`) alineado en
  docstrings, `config/default_engine.toml` y `ARCHITECTURE.md`; sin cambiar su significado.
- Screening (M-2): correlaciones y sensibilidad medidas y documentadas; ponderaciones por defecto **sin
  cambios**.

### Tests nuevos (todos con oráculos independientes de las funciones bajo prueba)

`tests/unit/constraints/test_non_buyable_positions.py`, `tests/integration/test_non_buyable_pipelines.py`,
`tests/unit/candidates/test_non_buyable_screening.py` (E-10); `tests/unit/candidates/test_deduplication.py`
(L-4; el mutante `dedup_off` ahora se detecta); `tests/unit/candidates/test_screening_correlation.py` (M-2);
`tests/unit/frontiers/test_known_inaccurate_point.py` (causa del fallo intermitente de B2);
`tests/unit/validation/test_bounds_vectorization.py`; ampliaciones en `test_composition_hash.py` y
`test_candidate_engine.py`. Los tests anteriores no se debilitaron: solo se adaptó la llamada a
`build_constraint_set` (nuevo argumento) en `tests/fixtures/problems.py`,
`tests/unit/constraints/test_constraint_compiler.py`, `test_prefeasibility.py`,
`tests/unit/frontiers/test_removed_assets.py` y `tests/unit/validation/test_policy_consistency.py`, sin tocar
ninguna aserción.

### Resultados

- `pytest -q -p no:cacheprovider`: **929 passed** en 155,24 s (0 failed, 0 skipped): 796 del baseline + 133 nuevos.
- Los 51 ficheros de test del baseline `block2-validated` sobre el código final: **560 passed** en 34,13 s
  (558 + 2 tests de arquitectura añadidos en el B3).
- `mypy --strict portfolio_engine`: 0 errores en 123 ficheros. `ruff check .`: limpio. `ruff format --check .`:
  245 ficheros ya formateados.
- Control de mutación: 4/4 mutantes de E-10 y el mutante `dedup_off` detectados.
- Rendimiento (búsqueda de candidatos, universo 50, cartera 20): llamadas a funciones 2.296.734 → 1.261.180;
  CPU mínima de 5 repeticiones alternas 1,17-1,23 s → 1,03-1,08 s; 1.200 evaluaciones y salida idénticas bit a
  bit. Benchmark real adicional: `benchmarks/results/candidate_engine_20260924T124637Z.json` (árbol sin commit;
  tiempos absolutos dependientes del estado de la máquina).

### Trazabilidad

316 `RequirementID` (reconciliados por script): `VALIDATED` 182 → 181 (BEN-009 retirado), `PARTIAL` 40 → 41
(`FEA-006`), `NOT_IMPLEMENTED` 95 → 94. `CAN-013` conserva `VALIDATED` con H-1 corregido y probado. Ningún
estado de B4–B6 avanza.

### Limitaciones conocidas

- **[Resuelto en la segunda tanda: ADV/NAV implementada, `FEA-006` y `CON-012` `VALIDATED`.]**
- El test de propiedades de B2 `test_every_frontier_point_satisfies_the_financial_invariants` puede fallar de
  forma esporádica (≈ 0,2 % de los ejemplos): OSQP no converge o declara infactible en algunas fronteras
  `TARGET_RETURN_GRID` casi degeneradas (idéntico en `block2-validated`); no se han relajado tolerancias.
- El tiempo de CPU de esta máquina alterna entre dos estados (≈ 1 s y ≈ 5 s para la misma búsqueda): las cifras
  absolutas de los benchmarks no son comparables entre ejecuciones; el JSON de B3 se generó sobre un árbol sin
  commit.

### Estado

Ver `REMEDIATION_BLOCK_3.md` §9 y la respuesta de la sesión (`BLOCK_3_REMEDIATION_STATUS`).

---

## [Remediación del Bloque 3 — segunda tanda: ADV/NAV] — 2026-09-24

Decisiones funcionales del usuario sobre `FEA-006` y A-11 (registradas como **E-11** en `MASTER_SPEC.md` §12 y
Anexo A, y en A-11 de `ARCHITECTURE.md`). Sin avance al Bloque 4; sin commit, merge, push, tag ni PR.

### Cambios

- **Restricción ADV/NAV** `LiquidityCapacity = max_adv_participation·ADV·liquidation_days/NAV`: posición nueva
  `w ≤ capacidad`; existente `w ≤ max(w_current, capacidad)` (protegida, sin liquidación forzosa). Nuevos
  `constraints/liquidity.py`, `LiquidityConfig`/`FxRate`, `[constraints.liquidity]` (sin valores por defecto;
  `enabled = false`), `AssetMetadata.adv_currency`, `PortfolioSpec.nav_currency`; compilador
  (`LiquidityCapRule`), `PreFeasibilityChecker.check_liquidity`, `SolutionValidator._liquidity`,
  `CandidateEngine` (validación de datos al iniciar, peso de entrada del screening, cardinalidad, nota
  `A11_ADV_NAV_LIQUIDITY_CAPS_ACTIVE`). Datos o parámetros ausentes/inválidos con la restricción activa ⇒ error;
  `ADV` y `NAV` en la misma divisa o `fx_rates` explícitos. No es un límite de volumen negociable por operación
  ni garantiza la ejecutabilidad de una venta. E-09 y E-10 sin regresión.
- **Hallazgo separado de B2** (test de propiedades inestable): `tests/unit/frontiers/test_known_solver_status_cases.py`
  fija las 7 instancias con un oráculo LP independiente: 0 casos verdaderamente infactibles; el resto son fallos
  numéricos del solver (`INFEASIBLE` espurio, `NUMERICAL_ERROR`/`MAX_ITERATIONS`, `OPTIMAL_INACCURATE`) con estado
  reportado correctamente. **No resuelto**; requiere una remediación específica posterior (B4/B2).

### Resultados

- `pytest -q -p no:cacheprovider`: **1003 passed** en 255,47 s (0 failed): 929 + 74 nuevos.
- 51 ficheros de test del baseline `block2-validated`: **560 passed**.
- `mypy --strict portfolio_engine`: 0 errores en 124 ficheros; `ruff check .` limpio; `ruff format --check .`:
  250 ficheros ya formateados. Mutación: 4/4 mutantes de ADV/NAV detectados.

### Trazabilidad

316 `RequirementID`: `CON-012` PARTIAL → `VALIDATED` y `FEA-006` PARTIAL → `VALIDATED` (`VALIDATED` 181 → 183,
`PARTIAL` 41 → 39, `NOT_IMPLEMENTED` 94). Ningún otro estado cambia.

### Limitaciones conocidas

- Sin `ADVCurrency`/`NAVCurrency` declaradas se asume la misma divisa; no hay conversión FX automática.
- Fallo esporádico del test de propiedades de B2 (≈ 0,21 % por ejemplo): abierto.

---

## [Remediación final de datos del Bloque 3 — F-1, F-2, F-4, F-6] — 2026-09-24

Respuesta a `AUDIT_BLOCK_3_CLOSURE.md` (`PASS_WITH_CHANGES`). Detalle en `REMEDIATION_BLOCK_3_CLOSURE.md`.
Sin avance al Bloque 4; sin commit, merge, push, tag ni PR. `AUDIT_BLOCK_3.md` y `AUDIT_BLOCK_3_CLOSURE.md`
intactos.

### Cambios

- **F-1 (unidad de ADV):** nuevo enum `AdvUnit` (`NOTIONAL_PER_DAY`, `SHARES_PER_DAY`, `CONTRACTS_PER_DAY`),
  `AssetMetadata.adv_unit`/`adv_source` (columnas `ADVUnit`/`ADVSource`), con validación de tipo. Solo
  `NOTIONAL_PER_DAY` es utilizable; títulos/contratos se rechazan con diagnóstico específico y sin conversión
  (requeriría precio y política de valoración aprobados); unidad ausente o desconocida ⇒ error. Comprobación
  dimensional documentada en `constraints/liquidity.py`.
- **F-2 (divisas):** con ADV/NAV activo `ADVCurrency` y `NAVCurrency` son obligatorias (ausentes ⇒ error; ya no
  se supone igualdad); FX = unidades de NAVCurrency por unidad de ADVCurrency (`ADV_en_NAV = ADV·FX`), par
  exacto, positivo y finito; orientación inversa no aceptada.
- **F-4:** los activos restringidos (cualquier política E-09) ya no evitan la validación de datos ADV/NAV.
- **F-8:** los mensajes de `BOUNDS_CROSSED` muestran floats de Python (`float(...)`).
- **F-5:** documentado por qué cambia `ConstraintHash` (`ARCHITECTURE.md` §3.4 fila 16).
- `SolutionValidator` comprueba de nuevo el contrato de datos desde la `LiquidityCapRule` (unidad, divisas,
  FX, capacidad) además del tope.
- Documentación localizada: `MASTER_SPEC.md` (E-11), `ARCHITECTURE.md`, `TRACEABILITY.md`, `README.md`.

### Resultados

- `pytest -q -p no:cacheprovider`: **1039 passed** en 179,81 s (0 failed): 1003 + 36 nuevos.
- 51 ficheros de test del baseline: **560 passed** (558 históricos + 2 tests de arquitectura del B3).
- E-09/E-10/E-11 (10 ficheros específicos): 230 passed. `mypy --strict`: 0 errores en 124 ficheros;
  `ruff check .` limpio; `ruff format --check .`: 251 ficheros ya formateados.
- Mutantes de F-1/F-2/F-4/validador: 10/10 detectados sobre una copia; 2 detectores dentro de la suite.

### Trazabilidad (F-6)

`CON-012` y `FEA-006` se consideraron `PARTIAL` durante la corrección y vuelven a `VALIDATED` al corregir F-1 y
F-2 y pasar sus tests. 316 `RequirementID` (183 `VALIDATED`, 39 `PARTIAL`, 94 `NOT_IMPLEMENTED`); sin nuevos
`RequirementID`.

### Limitaciones conocidas

- Remediación numérica independiente pendiente antes del Bloque 4 (F-3, heredado de B2; no se tocaron tolerancias
  ni estados del solver).
- La conversión de ADV desde títulos no existe (requiere precio y política de valoración aprobados).

---

## [Remediación numérica independiente F-3 (heredada de B2)] — 2026-09-24

Rama `fix/b2-numerical-f3` sobre el baseline `block3-validated` (`4089909`). Detalle y evidencias en
`REMEDIATION_F3_NUMERICAL.md`; decisiones `F3-01…F3-08` en `ARCHITECTURE.md` §3.5. **No pertenece al Bloque 4**;
sin SOCP, CVaR, escenarios, robustez, MIQP, multiprocessing ni persistencia. Sin commit, merge, push, tag ni PR.
Los cierres históricos de B2 y B3 no se alteran.

### Incidencia

F-3: fronteras `TARGET_RETURN_GRID` con región factible en franja casi degenerada (retornos casi idénticos en
`GROSS`; costes que casi anulan la pendiente del retorno en `NET`). OSQP declaraba `INFEASIBLE` (certificado
espurio), `NUMERICAL_ERROR`, `MAX_ITERATIONS` u `OPTIMAL_INACCURATE` en puntos que un LP independiente demuestra
factibles (hasta 18 de 20 puntos por frontera). Los puntos inválidos nunca se aceptaron.

### Cambios

- `optimizers/feasibility_oracle.py` (nuevo): LP de factibilidad de HiGHS con las mismas filas (`lp_feasibility`).
- `optimizers/formulations/qp_builder.py`: `BuiltProblem.normalize_return_row` → `NormalizedReturnProblem`
  (fila de retorno centrada con la de presupuesto y escalada; transformación exacta del conjunto factible).
- `frontiers/numerical_recovery.py` (nuevo) y `frontiers/session.py`: recuperación determinista y acotada de los
  puntos de retorno objetivo no óptimos; un reintento solo se acepta si es `OPTIMAL` y supera el
  `SolutionValidator` con el retorno objetivo original; `OPTIMAL_INACCURATE` no se promueve; un `INFEASIBLE` que el
  LP halla factible y no se recupera pasa a `NUMERICAL_ERROR`; un `INFEASIBLE` confirmado por el LP se conserva.
- `models/solution.py`, `models/enums.py`: `SolveResult.recovery` (`RecoveryTrace`, `RecoveryAttempt`,
  `RecoveryOutcome`) con estado inicial, veredicto del LP, todos los intentos y resultado.
- `config/solver_config.py`, `config/default_engine.toml`: `solver.numerical_recovery`, `solver.recovery_row_scales`
  (`[10.0, 1.0, 100.0]`). Ninguna tolerancia ni estado del solver se relaja. El `ConfigHash` cambia respecto a
  `block3-validated` por los dos campos nuevos.
- Backends, router, `SolutionValidator`, compilador, costes, `CandidateEngine`, frontera global y Pareto: sin cambios.

### Resultados

- 7 instancias contractuales × GROSS/NET/POST_COST_GROSS: de 77 puntos inválidos a **0**; puntos recuperados óptimos
  frente a referencias independientes (solución analítica `n = 2`, SLSQP por regiones `n = 3`, LP de HiGHS).
- Barrido `n = 2…5`, semillas 0-1399, GROSS y NET (11 200 fronteras, 224 000 puntos): de 17 fronteras / **212**
  puntos inválidos a **0** (10 instancias adicionales al contrato, incorporadas como tests). Barrido adicional,
  semillas 1400-2999: 12 800 fronteras / 255 982 puntos, **0** puntos inválidos.
- No regresión: las 11 183 fronteras sin defecto tienen el mismo número de iteraciones; 54 configuraciones de B2/B3
  idénticas bit a bit a `block3-validated`.
- `pytest -q`: **1148 passed** en 131,78 s (0 failed, 0 skipped): 1039 + 109 nuevos.
  `mypy --strict portfolio_engine`: 0 errores en 126 ficheros; `ruff check .` limpio;
  `ruff format --check .`: 259 ficheros ya formateados.
- Rendimiento: +2,8 % de iteraciones OSQP en el barrido (solo en las fronteras defectuosas); las sanas no cambian.

### Trazabilidad

316 `RequirementID` (183 `VALIDATED`, 39 `PARTIAL`, 94 `NOT_IMPLEMENTED`); ningún estado cambia. Evidencia ampliada en
`FRN-008`, `FRN-023`, `VAL-001`, `SOL-002` (sigue `PARTIAL` por Clarabel/B4), `OPT-005` y `CFG-008`.

### Cierre de cobertura de la auditoría (AF3-01, AF3-02)

Solo tests y documentación; sin cambios en código productivo. Tres tests adicionales en
`tests/unit/frontiers/test_numerical_recovery.py` cubren AF3-01 (reintento que devuelve realmente
`OPTIMAL_INACCURATE`, no se promueve ni se acepta) y AF3-02 (oráculo LP `INCONCLUSIVE` conserva el `INFEASIBLE`
original, sin reclasificar ni confirmar infactibilidad, con traza). Los dos mutantes supervivientes (M3 y M7b) son
ahora detectados (ejecución en copia aislada). `pytest -q`: 1151 passed (1148 + 3). `TRACEABILITY.md`: evidencia de
`SOL-002` y `FRN-023` corregida sin cambio de estados. El test `test_an_inaccurate_retry_is_never_promoted_to_optimal`
se conserva como evidencia del límite de escalas, pero no ejercita `OPTIMAL_INACCURATE`. AF3-03 sigue como limitación
conocida; la diferencia de varianza de 1.3e-7 (AF3-04) no corresponde a un punto recuperado defectuoso.

### Limitaciones conocidas

- La escalera de escalas es empírica; un punto que ninguna escala recupere queda inválido y etiquetado.
- Solo cubre puntos con retorno objetivo (no la malla de `theta`, MinVariance ni la etapa 2 de MaximumReturn).
- Pendientes: barridos con `n > 5`, límites de grupo/turnover, activos que salen de la composición, frontera
  adaptativa y benchmark del proyecto (no regenerado).
