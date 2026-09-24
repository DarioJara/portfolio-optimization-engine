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
