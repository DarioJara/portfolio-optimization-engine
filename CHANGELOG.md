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


## [Revisión posterior al merge del PR #3 de F-3 — P2-01 y P2-02] — 2026-09-25

Rama `fix/f3-oracle-iteration-accounting` sobre `main` (`b59e446`, posterior al merge del PR #3). Hallazgos de la
revisión de GitHub posterior al merge; informe en `F3_POST_MERGE_REVIEW.md`. **No pertenece al Bloque 4.** Sin
commit, merge, push, tag ni PR. Los informes históricos de auditoría no se alteran.

### Cambios

- `optimizers/formulations/qp_builder.py`: `normalize_return_row` calcula la escala sobre toda la fila centrada
  cuando el bloque de pesos centrado es despreciable (`<= √eps`; retornos idénticos con costes en `NET`), y
  devuelve `None` solo si la fila es nula o ruido de redondeo. Con pesos informativos la escala es la de antes.
- `frontiers/numerical_recovery.py`: `SolveResult.iterations` suma todos los intentos, oráculo de HiGHS incluido.
- `models/solution.py`: `sum_iterations_by_solver`, `RecoveryTrace.iterations_by_solver`,
  `SolveResult.iterations_by_solver` (desglose OSQP/HiGHS; suma = `iterations`).
- `models/frontier.py`, `frontiers/session.py`: `FrontierDiagnostics.iterations_by_solver` (campo nuevo con valor
  por defecto) y `FrontierSession.iterations_by_solver`.
- Tests nuevos: `tests/unit/frontiers/test_f3_post_merge_review.py`.

### Efecto

`total_iterations` de las fronteras con recuperación por `INFEASIBLE`/`NUMERICAL_ERROR`/`UNKNOWN` aumenta en las
iteraciones del oráculo (+24…+54 **por frontera** en las instancias contractuales y del barrido que la activan; +2…+8 por punto recuperado); pesos, estados y métricas no cambian.
`iterations` mezcla algoritmos distintos (ADMM, símplex/punto interior): métrica agregada de actividad, no de
esfuerzo homogéneo.


## [Cierre de hallazgos no bloqueantes de la auditoría posterior al merge de F-3 — RF-01…RF-05] — 2026-09-25

Rama `fix/f3-oracle-iteration-accounting`. Auditoría: `AUDIT_F3_POST_MERGE.md` (`PASS_WITH_CHANGES`, sin
hallazgos bloqueantes). **Solo documentación y un test focalizado; sin cambio de código productivo, tolerancias,
algoritmo de recuperación, criterios de aceptación, `RequirementID` ni estados.** No pertenece al Bloque 4. Sin
commit, merge, push, tag ni PR.

- RF-02 (documentación): corregida la unidad del efecto en las iteraciones del oráculo: +24…+54 **por frontera**
  (+2…+8 por punto recuperado) en `F3_POST_MERGE_REVIEW.md` y en la entrada anterior de este fichero.
- RF-01 (test): `tests/unit/frontiers/test_f3_near_identical_net_budget.py`, NET con diferencia de retorno
  1e-9, 2e-9 y 5e-9: recuperación `OPTIMAL` válida frente al objetivo original (`SolutionValidator`), varianza
  igual a la referencia analítica, traza original → oráculo → reintentos, y respeto del presupuesto de
  iteraciones configurado; frontera completa sin puntos inválidos. Sin umbral de tiempo.
- Limitaciones residuales documentadas (no son defectos financieros resueltos):
  - RF-01: en esa banda la recuperación es correcta pero puede consumir una proporción elevada del presupuesto de
    iteraciones de reintento (medido hasta 192 475 de 200 000).
  - RF-03: `iterations_by_solver` está en los diagnósticos agregados, no en todas las salidas por punto.
  - RF-04: sin test específico de aditividad de tiempos.
  - RF-05: la ruta degenerada de P2-01 se verifica con fallo inicial inducido; sin activación espontánea en el barrido.


## [Bloque 4 — Escenarios, optimización robusta, cónica y validación EXACT_MIP] — 2026-09-25

Rama `block4-scenarios-robust-optimization`, sobre el baseline `numerical-f3-validated` (1193 tests). **Sin
commit, merge, push, tag ni PR; no se avanza al Bloque 5.** Módulos fuera de alcance: paralelización, caché,
persistencia, visualización y `PersistenceDataset` (Bloques 5–6). `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`
y los informes de auditoría históricos no se modifican; no se usa código de `1.-Version Anterior/`.

### Añadido

- **Backends**: `ClarabelBackend` (forma `A x + s = b`; igualdades → `ZeroCone`, cotas → `Nonneg`, filas
  `SOC`), `MixedIntegerBackend` sobre SCIP/PySCIPOpt (backends comerciales enchufables y opcionales),
  `NonConvexBackend` (solo arquitectura, registro de algoritmos vacío: E-25). `map_clarabel_status` y
  `map_scip_status` distinguen `OPTIMAL`, `OPTIMAL_INACCURATE` (nunca promovido), infactible, no acotado,
  errores numéricos y límites de iteración/tiempo.
- **Router**: `SolverRouter(config, *, conic, exact_mip, seed, nonconvex_algorithms, inner_loop)`;
  QP→OSQP, LP→HiGHS, SOCP→Clarabel, MIQP/MIQCP/MISOCP→mixto entero, NLP no convexo→NonConvex; SDP rechazado;
  ninguna clase se degrada a OSQP. `inner_loop=True` (motores de producción) rechaza EXACT_MIP y NONCONVEX
  (MIP-005). `cross_check_with_second_solver` y `CrossCheckReport` como API explícita.
- **Formulaciones** (`optimizers/formulations/`): factor PSD `Σ=LLᵀ` por autodescomposición (Σ singular
  admitida), cono de volatilidad, cono rotado, Max Sharpe (Charnes–Cooper, SOCP), control de volatilidad,
  CVaR Rockafellar–Uryasev (mínimo y restricción, con escalado de horizonte), utilidad esperada multiescenario,
  peor caso (epígrafe), BaseWithStress, robusta (caja, elipsoidal, covarianza escalada) y MIQP/MISOCP
  semicontinuo (`MinWeight·z ≤ w ≤ MaxWeight·z`, `Σz=K`, límites de nuevos activos y swaps).
- **`scenarios/`**: `ScenarioEngine` con los 10 `ScenarioType` (`mu_s`, `Σ_s`, `cost_s`, `constraints_s` desde
  choques configurables, sin magnitudes por defecto), `MultiScenarioOptimizer` (ScenarioIndependent,
  ExpectedScenarioUtility, WorstCase, BaseWithStressConstraints), intersección de restricciones.
- **`frontiers/strategy_optimizer.py`** (MAX_SHARPE, VOL_TARGET, MIN_CVAR, CVAR_LIMITED, ROBUST) y
  **`frontiers/exact_mip_validation.py`** (EXACT_MIP solo como modo de validación; el gap se informa solo si
  el solver da una cota dual válida; nunca se inventa).
- **Validación**: `AdvancedSolutionValidator` (volatilidad, CVaR, Sharpe, escenarios, cardinalidad; recalcula
  desde los pesos y conserva todas las comprobaciones base).
- **Métricas/retornos**: `metrics/cvar_metric.py`, `metrics/robust_metric.py`, `returns/shrinkage.py`
  (intensidad fija y Jorion; `SHRUNK_HISTORICAL_MEAN` no seleccionable en `[returns]`).
- **Configuración**: secciones `[conic]`, `[sharpe]`, `[cvar]`, `[exact_mip]`, `[robust]`, `[scenarios]`
  (todas obligatorias, sin defaults implícitos; entran en `ConfigHash`); definiciones de escenarios en
  `config/scenario_definitions.py`.
- **Salidas y benchmark**: `outputs/strategy_rows.py`; `benchmark/block4_suite.py` y
  `benchmarks/scripts/block4_formulations.py` (mediciones descriptivas de un proceso local).
- **Dependencias**: `clarabel>=0.11,<1` (obligatoria), `pyscipopt>=6` (grupo opcional `exact-mip`);
  `requirements-lock.txt` con `clarabel==0.11.1` y `pyscipopt==6.2.1`.

### Modificado (deliberado)

- `OSQPBackend`/`HiGHSLPBackend` rechazan problemas no exactos; el `CanonicalProblem` conserva su contrato.
- `ContinuousFrontierEngine.prepare()`/`open_session(..., volatility_limit_handled)` y
  `reject_unenforced_constraints`: un `PortfolioSpec.volatility_limit` **deja de ignorarse** en las fronteras
  QP y se rechaza explícitamente (antes no se aplicaba); no cambia ningún resultado válido de B1–B3/F-3.
- `constraints/integer.py` (`membership_rules`) y `constraints/feasibility.py` (`check_volatility`).
- `tests/unit/test_architecture_rules.py`: `clarabel` y `pyscipopt` dejan de estar prohibidos y quedan
  confinados a sus backends; nuevos paquetes `scenarios`/`benchmark` en el grafo; nuevas reglas (MIP-005,
  confinamiento de solvers). `tests/unit/config/test_config_hashing.py`: lista de secciones del snapshot.
  `tests/unit/optimizers/test_router.py`: mensajes de rechazo de MIQP y SOCP/SDP actualizados.

### Defectos encontrados y corregidos durante el bloque

- WorstCase conservaba el objetivo LP base en lugar del epígrafe (corregido con `set_objective(None, epigraph)`).
- Utilidad esperada/peor caso se validaban contra los límites de estrés: ahora solo BaseWithStress los aplica.
- El argumento `inner_loop` por llamada rompía siete tests que sustituyen `route`: pasa a ser argumento del
  constructor del router.

### Desviaciones arquitectónicas (documentadas en `ARCHITECTURE.md`)

1. CVaR y Max Sharpe no viven en un módulo `constraints/conic.py`: son formulaciones en
   `optimizers/formulations/` (`CON-004` se satisface con el cono de volatilidad).
2. `CrossCheckPolicy` no se amplió con un segundo solver; la verificación cruzada es una API explícita.
3. La validación EXACT_MIP reside en `frontiers/exact_mip_validation.py` (no en `candidates/`).
4. `ScenarioConfig` solo guarda tolerancias; el modo multiescenario es un argumento de API (`CFG-010` PARTIAL).
5. `MIP-004`: resumen de calibración sobre instancias probadas, sin recalibrar el `CandidateEngine`.

### Limitaciones conocidas

- No implementados: TrackingError, Beta y Factor limits (`CON-015/016/017`, `VAL-006`, `FEA-008`), OAS/EWMA
  (`RSK-004/005`), Σ robusta por SDP (A-23), multi-start y algoritmos no convexos (E-25), `VIS-003`.
- EXACT_MIP acotado por `exact_mip.max_universe_size`; valida una composición fija por instancia y es
  exponencial en el peor caso.
- Los conjuntos de incertidumbre de μ asumen error muestral iid y se rechazan con alpha externo salvo que sea explícito.
- Benchmarks descriptivos de un proceso (10 y 20 activos, 3 escenarios, 5 repeticiones, seed 7, `NET`); los
  tiempos de esta máquina son bimodales y no son rendimiento de producción. Resultado guardado en
  `benchmarks/results/block4_formulations_20260925T175532Z.json`.

### Tests

Gate ejecutado el 2026-09-25 (sin skipped):

- `pytest -q` completo: **1454 passed** (baseline 1193 + 261 tests nuevos del Bloque 4), 0 failed, 387 s.
- Regresión F-3 (7 instancias / 77 puntos): `test_numerical_recovery.py`, `test_f3_post_merge_review.py`,
  `test_f3_near_identical_net_budget.py`: 132 passed. B1/B2/B3 incluidos en la suite completa.
- `mypy --strict portfolio_engine`: sin errores (158 ficheros). `ruff check .`: sin hallazgos.
  `ruff format --check portfolio_engine tests benchmarks`: 303 ficheros ya formateados.

Estados finales: 224 `VALIDATED`, 38 `PARTIAL`, 54 `NOT_IMPLEMENTED`, 0 `IMPLEMENTED` (total 316).


## [Remediación del Bloque 4 tras `AUDIT_BLOCK_4.md` — F-01, F-02, F-03, F-10] — 2026-10-19

Rama `block4-scenarios-robust-optimization`, sin commit/push/merge/PR/tag; no se avanza al Bloque 5. Informe:
`REMEDIATION_BLOCK_4.md`. El Bloque 4 **no se declara validado** hasta la auditoría independiente de cierre.

- **F-01 (HIGH)**: `PortfolioSpec.volatility_limit` se aplica (cono `‖Lᵀw‖ <= σ_max`) o se rechaza antes del solver
  (FEA-005) en `cvar`, `robust`, `solve_worst_case` y `solve_base_with_stress`; el validador independiente recibe
  `VolatilityLimitCheck`. Nuevo `VolatilityCap`/`add_volatility_cap`, argumento `volatility_cap` en cuatro
  constructores, `StrategyOptimizer.volatility_mandate`/`volatility_checks`. Tests: `test_volatility_mandate.py`
  (27; Σ no diagonal, oráculos SLSQP/aleatorio, mutación, escenarios incompatibles).
- **F-02 (MEDIUM)**: `README.md` (único fichero con `ruff format --check` fallido) corregido a mano.
- **F-03 (MEDIUM)**: `SharpeOutcome.OPTIMAL` exige resultado válido; si no, `SOLVER_FAILURE` +
  `SHARPE_SOLUTION_NOT_VALIDATED`. Justificado: tolerancia de volatilidad cero de configuración y
  `status=OPTIMAL` del LP de aplicabilidad en `NOT_APPLICABLE`.
- **F-10 (MEDIUM)**: `NCV-001` pasa a `PARTIAL` (solo arquitectura); `SOL-002` sin «prevista». Estados: 223
  `VALIDATED`, 39 `PARTIAL`, 54 `NOT_IMPLEMENTED`, 0 `IMPLEMENTED` (316).
- Tests ejecutados: `pytest -q` **1482 passed**, 0 failed; `mypy --strict` sin errores (158 ficheros); `ruff check .`
  y `ruff format --check .` limpios (319 ficheros); `git diff --check` sin errores de espacios.
- Abiertos con constancia: F-04…F-09, F-11…F-13 (ver `REMEDIATION_BLOCK_4.md` §5).

## [Bloque 5.2 — Ejecutor secuencial de referencia y ejecutor paralelo] — 2026-10-19

Rama `block5-hpc-architecture` (desde `origin/main` = `271eaeb`, integración del PR #5), **sin commit/push/PR/merge/tag**.
Diseño: `BLOCK_5_HPC_ARCHITECTURE.md`, `BLOCK_5_IMPLEMENTATION_PLAN.md`, `BLOCK_5_BENCHMARK_PLAN.md`. Decisiones
aprobadas: D-01, D-02, D-05 (condicional), D-07 (con ajustes), D-09, D-13; las diferidas (D-03, D-04, D-06, D-08, D-10,
D-11, D-12) se respetaron. No se tocó `MASTER_SPEC.md`, ni algoritmos, tolerancias o estados de B1–B4, ni `main`.

### Baseline de no regresión (antes de modificar nada)

`pytest -q`: **1482 passed** (304 s); `mypy --strict portfolio_engine`: sin errores (158 ficheros); `ruff format --check .`:
limpio; `ruff check .`: solo marcó un fichero de test propio recién creado durante la ejecución (el árbol previo estaba
limpio). Entorno: `.venv` aislado (Python 3.13.6); no se modificó el Python del sistema.

### Añadido

- `config/parallel_config.py`, `config/default_parallel.toml`: `ParallelConfig` (workers explícito, tamaño de lote o AUTO,
  hilos BLAS, método de arranque `SPAWN`/`FORKSERVER`, contrapresión, reciclado). Fichero propio, fuera de `EngineConfig`
  y de su `ConfigHash` (ajustes de ejecución; el cargador de `EngineConfig` rechaza secciones desconocidas).
- `parallel/workload.py`: `WorkloadSpec` y catálogo cerrado de operaciones (W0–W5) con validación y hash canónico.
- `parallel/task.py`: `run_portfolio` (referencia secuencial; compone motores existentes), `PortfolioRequest`,
  `MarketSnapshot`, `ExecutionContext`, `TaskResult`, `ExecutionStatus`, `input_problems`, `stable_form`.
- `parallel/batching.py`: `SequenceID`, `PortfolioBatch`, `resolve_batch_size` (fijo/AUTO), `ParallelExecutionError`.
- `parallel/threading_control.py`: variables de entorno + `threadpoolctl` (1 hilo numérico por worker).
- `parallel/worker.py`: `initialize_worker`, `WorkerContext`, `run_batch`, `WorkerBundle` (fichero de arranque
  hash-verificado), huella de `mu`/`Σ` antes y después de cada lote.
- `parallel/executor.py`: `SequentialExecutor`, `ParallelExecutor` (`ProcessPoolExecutor`, `spawn`/`forkserver`, cola
  acotada, planificación dinámica, reconstrucción del pool ante `BrokenProcessPool`, orden canónico, comprobación de
  «exactamente una vez», `RunManifest`).
- `benchmarks/scripts/parallel_scaling.py`; tests `tests/unit/parallel/` (132), `tests/integration/test_parallel_equivalence.py`
  (41), `tests/integration/test_determinism.py` (7), tres reglas nuevas en `tests/unit/test_architecture_rules.py`.
- Dependencia directa `threadpoolctl>=3.5,<4` (ya estaba en `requirements-lock.txt` como transitiva; sin cambios de lock).

### Modificado (sin cambiar comportamiento matemático)

`config/__init__.py` (exporta `ParallelConfig`), `pyproject.toml` (dependencia y override de mypy para `threadpoolctl`),
`tests/conftest.py` (ruta del TOML paralelo), `tests/unit/test_architecture_rules.py` (grafo de capas: `parallel` puede
importar los paquetes que orquesta; las capas inferiores solo `parallel.determinism`; `multiprocessing`/`concurrent`
confinados a `parallel/`; retirados de «bloques posteriores» los módulos de B5.2), `ARCHITECTURE.md` (§3.7),
`TRACEABILITY.md`, `README.md`.

### Resultados de la verificación (gate final)

- `pytest -q`: **1664 passed**, 0 failed, 0 omitidos (462 s) = 1482 + 182. Tras esa ejecución se añadió un test
  (`test_the_integrity_check_detects_lost_duplicated_and_swapped_results`), ejecutado de forma aislada: pasa.
- `mypy --strict portfolio_engine`: sin errores (165 ficheros). `ruff check .` y `ruff format --check .`: limpios
  (342 ficheros). `git diff --check`: sin errores de espacios (avisos LF/CRLF).
- Equivalencia secuencial↔paralelo bajo T1 (tolerancia 1e-6 absoluta de la regresión dorada, estados exactos) para
  W0–W5 (13 workloads, 3 carteras por workload; spawn, 2 workers) y para 1/2/3 workers, lotes 1/2/AUTO/único, orden de
  envío barajado y repetición: **0 diferencias**. Diagnóstico T0 (no es criterio): 104.734 comparaciones de float en
  39 carteras, 0 inexactas (idénticas bit a bit en esta máquina, 2 workers, lote 4).

### Benchmark local (sintético, pequeño; no es rendimiento de producción)

Windows 11, Intel (Family 6 Model 186), Python 3.13.6, `spawn`, 1 hilo BLAS por worker, 3 repeticiones (mínimo/mediana),
universo de 8 activos, 3 posiciones, semilla 7. Resultados: `benchmarks/results/parallel_scaling_24portfolios_20261019T212151Z.json`
y `parallel_scaling_20portfolios_20261019T212756Z.json` (mezclas = supuestos de ingeniería). Cada ejecución paralela
se verificó contra la secuencial (T1): 0 diferencias.

| Mezcla | Secuencial (mín.) | 1 worker | 2 workers | 4 workers |
|---|---|---|---|---|
| 24 carteras ligeras (W0/W3/W4/W1) | 2,73 s | 9,01 s | 7,40 s | 8,55 s |
| 20 carteras (12 W1 + 4 W4 + 4 W0) | 11,94 s | 18,29 s | 12,49 s | 10,95 s |

Lectura (medición, no proyección): a este tamaño **el ejecutor paralelo no compensa el arranque de los workers**
(≈6–7 s de pool, con un `import` de ≈5 s por worker en `spawn`); solo con 4 workers y la mezcla pesada se llega a
speedup ≈1,09 en tiempo de pared. El camino crítico del cómputo (carga del worker más ocupado) fue 4,08 s frente a
11,94 s secuenciales con 4 workers (≈2,9×; derivado de las latencias por tarea, no es tiempo de pared), y la suma de
tiempos de tarea creció de 12,1 s (1 worker) a 15,9 s (4 workers) por contención. Snapshot serializado 25 KB;
solicitud media 0,8 KB; resultado medio 17–70 KB. Sin proyecciones a 22.000 carteras.

**Hallazgo medido (E-8 de `ARCHITECTURE.md`)**: la primera versión pasaba el snapshot por los argumentos del
*initializer*; con `spawn` en Windows el arranque se serializaba (`parallel_scaling_24portfolios_20261019T205808Z.json`:
pool de 1/2/4 workers = 6,1/12,0/22,8 s). Una sonda confirmó la causa (payload mayor que el búfer del *pipe* de arranque
con un `__main__` pesado: 14,1 s frente a 5,3 s con 100 B). Se sustituyó por un fichero de arranque hash-verificado
(1/2/4 workers = 6,0/6,0/7,1 s). Ese resultado previo se conserva como evidencia.

### Requisitos (ver `TRACEABILITY.md`)

`VALIDATED`: PAR-001, PAR-002, PAR-007, PAR-008, PAR-010, PAR-011, PAR-012, PAR-013. `PARTIAL`: CFG-011, PAR-003, PAR-005,
BEN-004, GOV-012 (+ evidencia en BEN-001/002/006). Estados: 231 `VALIDATED`, 43 `PARTIAL`, 42 `NOT_IMPLEMENTED`,
0 `IMPLEMENTED` (316).

### Limitaciones y deuda técnica (abiertas)

- Sin memoria compartida definitiva ni caché (B5.3: PAR-004, CCH-*), sin plazos, cancelación, reintentos, diario ni
  interfaces de integración (B5.4). Un worker caído rompe el pool y marca como `WORKER_CRASHED` **todos los lotes en vuelo** (hasta
  `workers × max_in_flight_batches_per_worker` lotes; incluye carteras sanas y trabajo ya calculado), sin aislar la tarea
  culpable (corregido en la remediación de B5.2; el texto original decía «todo el lote»).
- AUTO sin calibrar; arranque de ≈5 s por worker (import) que penaliza cargas pequeñas; `FORKSERVER` **NO VALIDADO**
  (nunca ejecutado; `SPAWN` solo probado en Windows): la compatibilidad Linux queda pendiente de ejecutarse en Ubuntu.
- No se ha perfilado (`cProfile`) el reparto de tiempo entre fases (paso 1 del plan de B5.2): pendiente.
- `STRATEGY_ROBUST` no admite `mu_set` explícito (solo `covariance_scale_max` o derivado de `[robust]`).
- El directorio temporal del fichero de arranque se elimina siempre salvo muerte brusca del coordinador (`kill -9`).
- Memoria (RSS) y CPU del sistema no recogidas: `psutil` no está instalado en el entorno.
- Deuda de B4 (F-03b, F-04…F-09, F-11…F-13) sin cambios.

## [Remediación de B5.2 tras `AUDIT_BLOCK_5_2.md`] — 2026-10-20

Rama `block5-hpc-architecture`, sin commit/push/PR/merge/tag; no se inicia B5.3. Informe: `REMEDIATION_BLOCK_5_2.md`.
Sin cambios de lógica de producción ni de tolerancias; `MASTER_SPEC.md` intacto.

- **H-1**: corregida la descripción de `WORKER_CRASHED` («todos los lotes en vuelo cuando el pool detecta la caída», no «el
  lote del worker caído») en este fichero, `ARCHITECTURE.md` §3.7, `README.md`, plan y docstring de `executor.py`.
- **Pruebas de caída**: `test_a_crash_mid_task_marks_every_in_flight_batch_as_worker_crashed` (2 workers, caída a mitad de
  tarea con vecino sano, determinista) y `test_a_crash_without_warm_up_keeps_exactly_once_and_bounded_damage`
  (invariantes). Hallazgo: con `ProcessPoolExecutor` en Windows/CPython 3.13.6 la caída del último worker creado bajo demanda
  puede detectarse tarde; la prueba determinista calienta el pool antes de enviar trabajo. Deuda D-DET (B5.4).
- **M-2**: `STRATEGY_ROBUST` con `mu_set` explícito documentado como capacidad pendiente del `WorkloadSpec`.
- **M-3**: `FORKSERVER` rotulado NO VALIDADO (nunca ejecutado); `SPAWN` probado solo en Windows.
- **M-4**: `PAR-013` `VALIDATED` → `PARTIAL`. Estados de `TRACEABILITY.md`: **230 `VALIDATED`, 44 `PARTIAL`, 42
  `NOT_IMPLEMENTED`, 0 `IMPLEMENTED`** (316). Esto sustituye a los recuentos y a la lista de `VALIDATED` de la entrada anterior
  de B5.2 (231/43/42, con PAR-013).
- **L-5**: `parallel/__init__.py` y README (rutas Windows/Linux, `threadpoolctl`).
- Deuda trazable (M-1, L-1…L-4, D-DET) registrada en `ARCHITECTURE.md` §3.7.
- Verificación: `pytest -q` **1668 passed** (654 s); `mypy --strict` sin errores (165 ficheros); `ruff check .` y
  `ruff format --check .` limpios (342 ficheros); `git diff --check` sin errores de espacios. Un gate intermedio previo a
  corregir la prueba de caída dio 2 fallos de esa prueba; se corrigió y se repitió el gate completo.

---

## [Bloque 5.3 — Datos de mercado compartidos y caché de resultados] — 2026-10-20

Rama `block5-shared-memory-cache` (desde `main` = `539d4b7`, integración de B5.2). **Pendiente de auditoría independiente**
(`AUDIT_REQUEST_BLOCK_5_3.md`); sin PR ni merge. Contratos: `BLOCK_5_3_EXECUTION_BRIEF.md`, `BLOCK_5_IMPLEMENTATION_PLAN.md`,
`BLOCK_5_HPC_ARCHITECTURE.md` §7-9. No se modificó `MASTER_SPEC.md`, ni algoritmos, solvers, tolerancias, estados ni
restricciones de B1–B4, ni `EngineConfig.ConfigHash`. Decisiones diferidas respetadas (D-03, D-04, D-06, D-08, D-10, D-11, D-12).

### Baseline de no regresión (antes de modificar nada)

Windows 11 / Python 3.13.6 (`.venv`), rama a `e00762e`: `pytest -q` **1668 passed, 1 skipped** (prueba `forkserver` solo
Linux; 349 s), `mypy --strict` sin errores (165 ficheros), `ruff check` y `ruff format --check` limpios.

### Añadido

- `parallel/shared_data.py`: `SharedDataMode` {`BUNDLE_FILE` (B5.2, reserva), `FILE_MMAP`, `SHARED_MEMORY`}; `publish_snapshot`
  / `attach_snapshot` con `pickle` de protocolo 5 y *buffers* fuera de banda (SHA-256 de cabecera, manifiesto y cada *buffer*,
  alineación a 64 B), referencia de tamaño constante, arrays de solo lectura sin copia, limpieza en `finally` (con reintentos
  de borrado en Windows), `owner.json` y `inventory_orphans`/`remove_orphans` (directorios y segmentos `pe_<pid>_*`).
- `cache/keys.py`, `cache/result_cache.py`: `CacheKey` (10 componentes oficiales de CCH-002 + `portfolio_id`,
  `operation_hash`, `snapshot_key`), `ResultCache` (LRU por entradas y bytes, copias nuevas, métricas).
- `parallel/operation_cache.py`: `OperationCache` por worker a nivel de operación; solo estados definitivos; nada con límites
  de tiempo de pared ni con `EXACT_MIP`.
- `config/parallel_config.py`: `SharedDataMode`, `CacheConfig`; claves obligatorias `shared_data_mode` y `[parallel.cache]`
  (`enabled = false` por defecto).
- `STRATEGY_ROBUST`: `OperationSpec.mu_half_width` (incertidumbre `BOX` de `μ` por `AssetID`, M-2 parcial).
- `MarketSnapshot.market_data_timestamp`; `RunResult.cache_metrics`/`publication`; `OperationOutcome.cache_event`;
  `RunManifest.shared_data_mode`/`cache_enabled`; diagnósticos de worker (`attach_seconds`, `sigma_backing`, memoria).
- Dependencia opcional `psutil` (extra `bench`) para RSS/USS/PSS; `benchmarks/scripts/shared_data_cache.py` (E4/E8);
  `.github/workflows/b53-branch-ci.yml` (validación temporal en Ubuntu; **eliminado** en la remediación, véase abajo).
- Tests: `tests/unit/parallel/test_shared_data.py`, `test_operation_cache.py`, `tests/unit/cache/` (claves y almacén),
  `tests/integration/test_shared_data_equivalence.py`; reglas de arquitectura (`cache`, constantes de formato).

### Verificación

Windows 11 / Python 3.13.6 sobre el código de B5.3 (`7d4632a`, sin cambios de lógica desde entonces salvo el punto 3 de
«Linux»): `pytest -q -rs` **1757 passed, 2 skipped** (`forkserver` y el inventario de `/dev/shm`, solo Linux; 684 s),
`mypy --strict portfolio_engine` sin errores (170 ficheros), `ruff check .` limpio, `ruff format --check .` (358 ficheros)
y `git diff --check` limpios. Tras el commit `d3ecd53` se repitieron en Windows ruff, `ruff format --check`, mypy del módulo
y los 27 tests de datos compartidos/equivalencia (27 passed, 1 skipped). Sobre el baseline (1668 + 1) hay 89 tests nuevos
y ninguna regresión. El diff respecto de `539d4b7` no toca ningún módulo fuera de `parallel/`, `cache/` y `config/`, ni
`tests/unit/scenarios`.

### Resultados E4 (datos compartidos) y E8 (caché): medidas locales, sintéticas y pequeñas

`benchmarks/results/shared_data_cache_20261020T132518Z.json` (Windows 11, Intel, Python 3.13.6, `spawn`, 1 hilo BLAS,
2 repeticiones, universos de 50 y 500 activos, 8 carteras W0 con 160 puntos de frontera válidos por celda, T1 = 0 diferencias en
las 18 celdas, 0 recursos residuales). **No es rendimiento de producción ni se extrapola.**

| Medida | `BUNDLE_FILE` | `FILE_MMAP` | `SHARED_MEMORY` |
|---|---|---|---|
| Pool listo (1/2/4 workers), mín. | 6,2–8,3 s | 6,3–9,0 s | 6,2–9,9 s (el `import` de ≈ 5 s por worker domina; sin diferencia atribuible al modo) |
| Adjunción dentro del worker (N = 500) | 49–72 ms | 82–120 ms | 67–71 ms (verificar el hash de cada *buffer* cuesta más que deserializar a este tamaño) |
| Referencia por el pipe de arranque | 228 B | 559 B | 504 B (constante con el universo) |
| USS por worker, N = 50 | 111,8–112,8 MB | 112,4–112,9 MB | 112,2–113,0 MB |
| USS por worker, N = 500 | 115,7–116,5 MB | 112,4–113,4 MB | 112,4–113,3 MB |
| Origen de la memoria de `Σ` | copia privada (`bytes`) | vista sobre `mmap` | vista sobre `mmap` del segmento |

Lectura: los modos fuera de banda **sí evitan la copia privada** (`sigma_backing = mmap`) y la memoria privada por worker baja
en torno al tamaño de los datos (≈ 3 MB con N = 500: `Σ` 2,0 MB + retornos 1,2 MB, un 3 % de los ≈ 113 MB que ocupa
un worker); con N = 50 la diferencia es ruido. **No hay mejora de tiempo de arranque.** Por eso el modo por defecto sigue siendo
`BUNDLE_FILE` (más simple y con el fallback incorporado); los otros dos son alternativas validadas cuando los datos compartidos
sean grandes (muchos escenarios `Σ_s`: hipótesis, no medida). Ninguna cifra se extrapola a 22.000 carteras.

E8 (secuencial, 12 carteras W0 NET, operación repetida `k` veces, mín. de 2): `k = 1` 1,03 s sin caché / 0,99 s con caché (264 llamadas
al solver en ambos casos, 0 aciertos: el coste de serializar no es medible frente al ruido); `k = 2` 1,93 s → 1,06 s (528 → 264
llamadas, 12 aciertos); `k = 4` 3,65 s → 1,11 s (1056 → 264 llamadas, 36 aciertos). Cada acierto elimina por completo las llamadas al
solver; el resultado es idéntico (T1 = 0). 12 entradas ocupan ≈ 263 KB. Entre carteras distintas hay 0 aciertos por diseño.
Este JSON (`git_commit` = `bcada735…`, árbol limpio) sustituye al primero, que se generó con `e00762e+dirty` (auditoría L-7); los
valores de las tablas de arriba son los del JSON nuevo.

### Linux (GitHub Actions, workflow temporal `b53-branch-ci.yml`, eliminado después)

Ubuntu 22.04, Python 3.11.17, numpy 2.4.6, scipy 1.17.1, clarabel 0.11.1, osqp 1.1.3, PySCIPOpt 6.3.0, psutil 7.2.2; runner de
**1 CPU** (los tiempos con 2 y 4 workers no son representativos). Run `39414610396` sobre `d3ecd53` (runner AMD EPYC 9V45, donde los dos tests de B4 no fallaron): `mypy --strict`, ruff,
tests de `forkserver`/datos compartidos/caché y suite completa **1762 passed** (108 s); benchmark pequeño `spawn` y
`forkserver` × 3 modos × {1, 2, 4} workers × N {50, 500}: **T1 = 0 en todas las celdas**, 160 puntos válidos por celda. Orden de
magnitud: pool listo 0,7–1,3 s (el `import` es mucho más rápido que en Windows), adjunción 0,8–1,3 ms (N = 50) y 4–8 ms
(N = 500), referencia 199/472/444 B, USS por worker con N = 500: 116 MB (`BUNDLE_FILE`) frente a 111–112 MB (`FILE_MMAP`,
`SHARED_MEMORY`) en `spawn`; E8 `k = 4`: 0,44 s / 1056 llamadas sin caché frente a 0,13 s / 264 llamadas con 36 aciertos.

Hallazgos:

1. **Defecto corregido (`d3ecd53`)**: con Python < 3.13 el adjuntar un segmento en el worker lo registraba y anulaba en el
   `resource_tracker` compartido, y el `unlink` del coordinador producía `KeyError` en el rastreador (visible en el run
   `39409385018`, sin efecto sobre resultados ni limpieza). Los workers ya no lo registran; en el run `39414610396`
   hay 0 líneas `KeyError`. El camino de Python ≥ 3.13 (`track=False`, usado en Windows) no cambia.
2. **Intermitencia en dos tests de B4 (causa indeterminada)**: véase «Historial completo de CI» en la entrada de remediación
   de B5.3. **Corrección (auditoría M-3):** la comparación «main 0/12 frente a rama 12/12» que figuraba aquí era una coincidencia de
   runners y se retira; en un run posterior (`39415376791`) el resultado se invirtió (main 12/12, rama 0/12).
3. El workflow temporal se eliminó antes de integrar (véase la remediación).

### Requisitos (ver `TRACEABILITY.md`)

`VALIDATED`: PAR-004, PAR-005, CCH-001, CCH-002, CCH-003, CCH-004, CCH-005, CFG-011. Siguen `PARTIAL`: PAR-013, BEN-004,
GOV-012. Estados: `NOT_IMPLEMENTED` 36, `PARTIAL` 42, `IMPLEMENTED` 0, `VALIDATED` 238 (total 316).

### Limitaciones y deuda técnica (abiertas)

- **No se calibra AUTO ni se mide la escala** (BEN-004 completo, B5.5); no hay medidas a 1.000+ carteras (D-12).
- Los datos compartidos solo ahorran memoria del orden del tamaño de los datos por worker; el arranque (≈ 5 s de `import` por worker)
  no mejora. La memoria compartida real con varios escenarios `Σ_s` no se ha medido.
- La caché no produce aciertos entre carteras distintas (por diseño: `CurrentPortfolioStateHash` y `PortfolioID` en la clave) ni en
  workers de un solo uso; su valor está en operaciones repetidas y reejecuciones en procesos de larga vida (B5.4+).
- `mu_set` `ELLIPSOIDAL` sigue sin expresarse en el `WorkloadSpec` (M-2 parcial).
- B5.4 abierto: M-1 (initializer sin corte), D-DET (detección tardía de la caída del último worker), L-1 (huella solo `mu`/`Σ`),
  L-2 (mensajes sin truncar), L-4 (`os.environ`), reintentos, plazos y diario.
- Los segmentos de memoria compartida huérfanos de Linux se inventarían pero nunca se eliminan automáticamente
  (`remove_orphans` es una acción explícita).
- Intermitencia **preexistente** de dos pruebas de B4 en Linux (véase «Linux»), no atribuible a B5.3.

---

## [Bloque 5.3 — Remediación tras AUDIT_BLOCK_5_3] — 2026-10-20

Rama `block5-shared-memory-cache`, PR #7 (borrador, sin merge). Informe: `AUDIT_BLOCK_5_3.md` (`PASS_WITH_CHANGES`: sin BLOCKER;
M-1…M-4 obligatorios). No se modificó ningún algoritmo, solver, tolerancia, estado, `MASTER_SPEC.md` ni código/tests de B1–B4, y no
se desactivó ni relajó ningún test. No se inició B5.4.

### Hallazgos corregidos

| Hallazgo | Corrección | Prueba |
|---|---|---|
| **M-1** `_statuses_final` ignoraba `GlobalFrontierResult.continuous` | Se comprueba también `continuous` (`parallel/operation_cache.py`) | `test_a_global_frontier_with_a_non_final_continuous_frontier_is_not_cached` (falla sin la corrección, verificado) |
| **M-2** `pid_alive` (Windows) trataba «acceso denegado» como proceso muerto | `nt_pid_alive`: `ERROR_ACCESS_DENIED` (5) ⇒ vivo; cualquier otro fallo ⇒ no existe; `kernel32` con `use_last_error` y tipos de argumentos | 3 pruebas con un doble de `kernel32` (multiplataforma) + 2 reales en Windows: PID 4 (System) vivo, PID inexistente muerto; directorio de un proceso privilegiado vivo no es huérfano |
| **M-3** Evidencia de CI incompleta | Historial completo de ejecuciones (abajo); se retira la comparación sesgada «main 0/12, rama 12/12» | — (documental) |
| **M-4** Faltaban dos pruebas de aceptación de PAR-004 | `test_no_resources_leak_after_100_publish_cycles` (3 modos, la mitad con excepción, 0 residuos, un segmento nuevo por ciclo) y `test_resources_of_a_killed_coordinator_are_found_and_recovered` (`kill` de un coordinador real, inventario y `remove_orphans`) | `tests/unit/parallel/test_shared_data_lifecycle.py` |
| **L-2** Segmento no liberado si fallaba la publicación | Liberación en `_publish_out_of_band` | `test_a_failure_after_creating_the_segment_does_not_leave_it_behind` |
| **L-3** Fallo de borrado silencioso | `ResourceWarning` si no se puede eliminar el directorio | `test_a_directory_that_cannot_be_removed_is_reported` |
| **L-4** `SHARED_MEMORY` sin comprobar espacio | `SharedDataError` claro antes de escribir si `/dev/shm` no tiene espacio (sin degradación silenciosa de modo) | `test_shared_memory_without_room_fails_before_writing` |
| **L-5** Prefijo genérico en `/dev/shm` | El inventario exige `pe_<pid>_<12 hex>` | `test_only_segments_with_the_exact_name_shape_are_orphan_candidates` |
| **L-6** W2 fuera de la equivalencia por modo | `test_multi_scenario_results_match_in_every_shared_data_mode` (W2 × 3 modos) | T1 = 0 |
| **L-7** JSON de benchmark con árbol sucio | Regenerado con árbol limpio (`bcada735`); el anterior se elimina | `shared_data_cache_20261020T132518Z.json` |

### Hallazgos LOW documentados y no cambiados (decisión consciente)

- **L-1** (integridad solo en el momento de adjuntar; el fichero `FILE_MMAP` es escribible por el mismo usuario; la huella de B5.2 solo
  cubre `μ`/`Σ`): el límite de confianza es el **mismo usuario del sistema**, igual que el del fichero de arranque de B5.2; marcar el fichero
  de solo lectura rompería el borrado en Windows. Ampliar la huella sigue siendo la deuda L-1 de B5.4.
- **L-8** `OPTIMAL_INACCURATE` se considera definitivo y se cachea: es determinista para la misma clave; se mantiene y queda documentado
  (`ARCHITECTURE.md` §3.8). `REMOVE_RETRIES`/`REMOVE_DELAY_SECONDS` son constantes de infraestructura (no financieras), documentadas como tales.
- **ConstraintHash**: la desviación E-14 (hash de las entradas) sigue documentada en `ARCHITECTURE.md`; formalizarla como enmienda de
  `MASTER_SPEC.md` requiere decisión del propietario y no se hace aquí.

### Verificación (Windows 11, Python 3.13.6)

Sobre `8a18102`: `pytest -q -rs` **1775 passed, 2 skipped** (909 s; los 2 skips son Linux-only), `mypy --strict portfolio_engine` limpio
(170 ficheros), `ruff check .` y `ruff format --check .` (359 ficheros) limpios. Sobre el árbol final (`d121a75`, mismo código que `bcada73`): `pytest -q -rs` **1775 passed, 2 skipped** (864 s), `mypy --strict` en las
plataformas Windows y Linux, `ruff check .` y `ruff format --check .` limpios, y `ci.yml` (Linux) en verde en el run 39430640797.
T1: las pruebas de equivalencia por modo (incluida W2) y con caché pasan con 0 diferencias; el benchmark regenerado da T1 = 0 en las 18 celdas.
La CI de Linux detectó además un fallo real de tipado que Windows no ve (`ctypes.get_last_error` en `mypy --strict` con la plataforma
Linux): corregido en `bcada73`; desde ahora `mypy --strict --platform linux` se ejecuta también en local.

### Historial completo de CI (GitHub Actions, rama `block5-shared-memory-cache`)

Todos los runs ejecutados sobre la rama, incluidos los fallidos. «Suite» = job Ubuntu 22.04 / Python 3.11 (1 CPU) del workflow
temporal o de `ci.yml`; «sonda» = 12 repeticiones de los dos tests de B4 sobre `539d4b7` (main) y sobre el commit de la rama.

| Run | Commit | Job | CPU del runner | Resultado |
|---|---|---|---|---|
| 39407121823 | `d5a17fb` | suite | no registrada (workflow aún sin anotaciones) | success |
| 39407952385 | `dfc9c69` | suite | EPYC 7763 | **failure** (exit 1; sin detalle de tests en las anotaciones) |
| 39408612070 | `a600ae0` | suite | EPYC 7763 | **failure**: 2 failed, 1760 passed (los dos tests de B4) |
| 39409385018 | `7d4632a` | suite | EPYC 9V45 | success (1762 passed) |
| ídem | `539d4b7` / rama | sonda | EPYC 9V74 / Xeon 6973P | **0/12** / 12/12 |
| 39414610396 | `d3ecd53` | suite | EPYC 9V45 | success (1762 passed) |
| ídem | `539d4b7` / rama | sonda | EPYC 7763 / Xeon 8573C | **0/12** / 12/12 |
| 39415376791 | `ff835d0` | suite | EPYC 7763 | **failure**: 2 failed, 1760 passed (los dos tests de B4) |
| ídem | `539d4b7` / rama | sonda | EPYC 9V74 / EPYC 7763 | 12/12 / **0/12** |
| 39415881644 | `ff835d0` | `ci.yml` (PR #7) | no registrada | success |
| 39426793670 | `8a18102` | suite | Xeon 8573C | **failure** en *Static checks* (`mypy --strict` en Linux: `ctypes.get_last_error`) |
| ídem | `539d4b7` / rama | sonda | Xeon 6973P / EPYC 7763 | 12/12 / **0/12** |
| 39426799994 | `8a18102` | `ci.yml` (PR #7) | no registrada | **failure** en *Static checks* (el mismo error de tipado) |
| 39428998923 | `bcada73` | suite | EPYC 7763 | **failure**: 2 failed, **1776 passed**, 2 skipped (solo fallan los dos tests de B4) |
| ídem | `539d4b7` / rama | sonda | EPYC 7763 / EPYC 7763 | **0/12** / **0/12** |
| 39429009105 | `bcada73` | `ci.yml` (PR #7) | no registrada | **failure** en *Full test suite* (sin anotaciones de detalle; su runner no se registra) |
| 39430640797 | `d121a75` | `ci.yml` (PR #7) | no registrada | success |
| 39432929217 | `1cae068` (solo documentación) | `ci.yml` (PR #7) | no registrada | **failure** en *Full test suite*; `ci.yml` no publicaba detalle, por lo que **no se puede confirmar qué tests fallaron** |

Lectura, sin atribuir una causa:

- Los dos tests (`test_single_solutions_satisfy_the_constraints_of_every_scenario`, `test_worst_case_maximizes_the_minimum_scenario_utility`)
  son de `tests/unit/scenarios/test_multi_scenario.py` (B4). **B5.3 no toca ningún módulo ni test de B4** (el diff frente a `539d4b7` solo
  alcanza `parallel/`, `cache/`, `config/`, tests nuevos, benchmarks y documentación).
- En el run `39428998923`, **el commit `539d4b7` (main) y la rama fallan 0/12 en el mismo tipo de CPU (EPYC 7763)**: el fallo no lo
  introduce B5.3. Todas las observaciones sobre EPYC 7763 (siete) fallaron, para ambos árboles; sobre Xeon y EPYC 9V45 no se observó el fallo;
  `539d4b7` en EPYC 9V74 dio 0/12 y después 12/12. La CPU del runner **no se controla** y es una correlación observada, no una causa
  demostrada: no se ha determinado el mecanismo (el mensaje muestra dos utilidades del peor caso que difieren en ≈ 5·10⁻¹⁵ y, en el
  otro test, «Positive directional derivative» del oráculo SLSQP del propio test).
- Un intento local del auditor con núcleos OpenBLAS forzados (Haswell, Sandybridge, Nehalem, Katmai) no reprodujo el fallo.
- `ci.yml` (el workflow permanente) se amplió solo con diagnóstico: `-rfE`, anotaciones con los tests fallidos y la CPU del runner. Su
  resultado sigue decidiendo el job; no se ha enmascarado ningún fallo. Los runs posteriores a este cambio no se listan aquí: constan en la
  pestaña *Actions* del PR #7.
- Consecuencia: la CI permanente (`ci.yml`) puede salir en rojo en función del runner sorteado, también para B5.4. **No se han relajado
  tolerancias ni desactivado tests.** Queda abierta la remediación B4 independiente propuesta por la auditoría (H-1).

### Estado de requisitos

Sin cambios de estado respecto a la entrada anterior: `VALIDATED` PAR-004, PAR-005, CCH-001…005, CFG-011; `PARTIAL` PAR-013, BEN-004,
GOV-012. Recuento 316 = 238 `VALIDATED` / 42 `PARTIAL` / 36 `NOT_IMPLEMENTED` / 0 `IMPLEMENTED`.

### Deuda abierta tras la remediación

H-1 (fragilidad numérica B4 dependiente del hardware, fuera del alcance); L-1; ELLIPSOIDAL (M-2 del diseño, parcial); B5.4 (M-1 del
initializer, D-DET, L-2 del diseño, L-4, reintentos, plazos, diario); reproducir en Linux real `forkserver`, `/dev/shm` y Python 3.13
`track=False` fuera de CI; el workflow temporal ya está eliminado.

---

## [Bloque 5.4 — Recuperación de workers, reintentos, plazos, cancelación, diario y reanudación] — 2026-10-20

Rama `block5-recovery-journal`, sobre `main` `bf74f97` (B5.3 integrado; merge sin conflictos). Pendiente de auditoría independiente. Diseño y
semántica completa en `ARCHITECTURE.md` §3.9; informe en `REPORT_BLOCK_5_4.md`.

### Alcance

`RequirementID` oficiales afectados: `PAR-011` (completo), `PAR-013`, `BEN-001` (sin cambio de estado). Propuestos (D-05): `P-01`, `P-03`…`P-08`.
Módulos permitidos: `parallel/{supervisor,markers,journal,codec,protocols,cli}.py` (nuevos), `parallel/{executor,worker,task,shared_data}.py`,
`config/parallel_config.py`, `config/default_parallel.toml`, tests y documentación. **Fuera de alcance y no tocados:** `MASTER_SPEC.md`, B1–B4
(motores, solvers, tolerancias), caché y memoria compartida de B5.3 (solo se añadió `scratch_directory` a `shared_data.py`), persistencia SQL, red,
`engine.py` y B5.5 (benchmarks masivos, auditoría). Sin Arsys, sin datos reales, sin cargas ≥ 1.000.

### Baseline de no regresión

Sobre el árbol integrado antes de modificar nada (`.venv`, Python 3.13.6, Windows 11): **1775 passed, 2 skipped** (13 min 20 s).

### Añadido

- **`parallel/supervisor.py` — `BatchSupervisor`**: recuperación de caídas con cuarentena (solo la tarea en curso de cada worker es
  sospechosa y se reintenta **sola**; `WORKER_CRASHED` solo tras `max_task_attempts` intentos aislados), reenvío intacto de las carteras
  no sospechosas, captura de `BrokenProcessPool` también en `submit`, cotas de reconstrucción (sin bucle infinito), plazos por tarea y por
  lote con terminación del proceso del worker, cancelación con periodo de gracia, vigilancia de PID (D-DET). `RecoveryReport` con
  contadores, eventos acotados y tiempo de recuperación.
- **`parallel/markers.py`**: marcas de progreso por nombre de fichero (`w.<pid>`, `t.<lote>.<pos>.<pid>`); sin canales compartidos ni claves
  privadas de `ProcessPoolExecutor`.
- **`parallel/journal.py` + `parallel/codec.py`**: diario local no ejecutable (JSON; sin `pickle`), escritura atómica, sumas SHA-256,
  manifiesto con identidad (`ConfigHash`, `snapshot_key`, hash del código, versiones, hash del conjunto de `TaskID`), reanudación
  verificada (rechazo sin modificar el diario), bloqueo del sistema operativo, eventos con suma por línea, `inspect_journal`.
- **`parallel/protocols.py`**: `MarketDataProvider`, `PortfolioRequestSource`, `ResultSink`, `RunControl`, `ProgressReporter` + versiones locales.
- **`parallel/cli.py`**: `python -m portfolio_engine.parallel.cli journal-info <dir>` (JSON estable, solo lectura).
- `ExecutionStatus`: `WORKER_INIT_FAILED`, `TIMED_OUT`, `CANCELLED`, `ABORTED`, `SKIPPED_BY_RESUME` (este último solo en la contabilidad).
- `RunAccounting` (enviadas = Σ estados finales, verificado en cada ejecución), `JournalSpec`, `RunResult.{accounting,recovery,journal_scan,resumed_task_ids}`.
- `ParallelExecutor.run(requests, *, journal, control, progress, sink)`.
- `RecoveryConfig` (`[parallel.recovery]` en `default_parallel.toml`): sin valores por defecto en el código; plazos opcionales; diario
  desactivado por defecto (opt-in doble: configuración + directorio explícito).
- `shared_data.scratch_directory` (marcas bajo el barrido de huérfanos de B5.3).
- Worker: *initializer* supervisado (captura su propio fallo → `WorkerInitializationError`), marcas por tarea, mensajes y trazas acotados
  (L-2), huella ampliada a costes y escenarios de retorno (L-1 parcial).

### Cambiado (semántica de B5.2, documentada y justificada)

- Una caída de worker **ya no** marca `WORKER_CRASHED` a todos los lotes en vuelo. Las cinco pruebas que fijaban esa semántica
  (`test_a_worker_crash_is_reported…`, `test_a_crash_mid_task_marks_every_in_flight_batch_as_worker_crashed[×2]`,
  `test_a_crash_without_warm_up_keeps_exactly_once_and_bounded_damage`, `…leaves_no_temporary_run_directories`) se reescribieron
  (su propio docstring pedía actualizarlas si se mejoraba): ahora esperan `COMPLETED` para toda cartera sana, T1 contra la referencia
  secuencial y `WORKER_CRASHED` solo para la venenosa confirmada.
- `test_no_later_block_packages_exist`: `parallel/journal.py` deja de figurar como módulo de un bloque posterior (lo entrega B5.4);
  `staging`, `persistence` y `engine.py` siguen prohibidos.
- `ALLOWED_NAMED_CONSTANTS`: 8 constantes de formato del diario, del códec y de las marcas (anchuras, permisos, partes de un par); ningún
  parámetro de negocio.

### Pruebas (ejecutadas realmente, `.venv`, Windows 11, Python 3.13.6)

| Conjunto | Resultado |
|---|---|
| Suite completa tras el bloque | **1925 passed, 3 skipped** (19 min 20 s); +150 pruebas respecto al baseline; 0 regresiones |
| Skipped | `test_forkserver_linux` y `test_shared_data` (`/dev/shm`), solo Linux, ya omitidos; `test_journal` (permisos POSIX), nuevo, solo POSIX |
| `mypy --strict portfolio_engine` | sin errores (176 ficheros) |
| `ruff check .` / `ruff format --check portfolio_engine tests benchmarks` | limpios (no se ejecutó `ruff format .` en la raíz) |
| Equivalencia T1 | `test_parallel_equivalence.py`, `test_determinism.py`, `test_shared_data_equivalence.py` (sin cambios, en la suite completa) y, en B5.4, comparación T1 contra la referencia secuencial en cada prueba de recuperación; el códec reconstruye las 14 clases de workload con **0 floats distintos** (tolerancia 0) |

Pruebas nuevas por área: `test_supervisor.py` (pool simulado: cuarentena, intentos, cotas, plazos, cancelación y 12 patrones aleatorios de
caídas con invariante de conteo), `tests/integration/test_recovery.py` (procesos reales: workers 1/2/3, tarea venenosa, *initializer* roto ×3,
plazos de tarea y de lote, cancelación, diario y reanudación, muerte real del coordinador, dos coordinadores simultáneos, `TIME_LIMIT` del
solver), `test_journal.py`, `test_codec.py`, `test_markers.py`, `test_protocols.py`, ampliaciones de `test_parallel_config.py`, `test_worker.py`
y dos reglas nuevas en `test_architecture_rules.py` (sin `pickle.load` de fuentes externas; el diario no usa `eval`/`exec`).

### Criterios de la tarea

Cada `TaskID` una sola vez (`RunAccounting.balanced`, `_verify_exactly_once`); la caída de un worker no falla carteras sanas; un *initializer*
siempre roto termina con cotas (`WORKER_INIT_FAILED`/`ABORTED`, 2 reconstrucciones en las pruebas); reanudar con otra fuente, configuración,
snapshot o código se rechaza sin tocar el diario; la equivalencia T1 y los estados exactos se conservan; el diario no contiene `pickle`,
solicitudes ni credenciales.

### Limitaciones y deuda (abiertas; los requisitos afectados quedan `PARTIAL`)

- **Linux no ejecutado** (`forkserver`, zombis vía `/proc`, `fcntl`, permisos 0700): `ci.yml` solo corre en PR/push a `main` y no se ha
  lanzado. H-1 de B4 (fragilidad dependiente del CPU del runner) sigue abierto y puede volver rojo ese job con independencia de B5.4.
- El diario cubre `ParallelExecutor`, no `SequentialExecutor`. El contrato exacto del diario (D-04) sigue siendo una propuesta no aprobada.
- La unidad de entrega es el lote: lo calculado dentro de un lote cuyo worker se termina se recalcula (o se pierde si se cancela).
- Un kill externo repetido `max_task_attempts` veces sobre la misma tarea es indistinguible de una venenosa.
- Plazos medidos desde que el coordinador observa el inicio (resolución `supervision_poll_seconds`).
- L-1 parcial (universo y definiciones de escenario no se vigilan); L-4 abierta (`os.environ`: un `run()` a la vez por proceso).
- Sin benchmark de recuperación: solo `RecoveryReport.recovery_seconds` en las pruebas, sin umbral (los tiempos con `spawn` dependen del
  arranque de ≈ 5 s por worker y son bimodales en esta máquina). No se ejecutó ningún benchmark masivo ni en Arsys.
- B5.5 (benchmarks de recuperación y escala, auditoría) no iniciado.

---

## [Bloque 5.4 — Remediación tras AUDIT_BLOCK_5_4] — 2026-10-20

Auditoría independiente: `PASS_WITH_CHANGES` sobre `436a7eb` (0 BLOCKER, 0 HIGH, 1 MEDIUM, 4 LOW). Detalle y evidencia en
`REMEDIATION_BLOCK_5_4.md`. Sin cambios en motores, solvers, tolerancias ni `MASTER_SPEC.md`; B5.5 no iniciado.

### Corregido

- **M-1** — los plazos vencidos ya no consumen `max_total_rebuilds`: presupuesto aparte, finito (`DEADLINE_REBUILDS_PER_TASK = 2` por tarea);
  nuevo `RecoveryReport.deadline_rebuilds`. Regresiones: más plazos que el presupuesto de caídas dejan terminar a las carteras sanas
  (pool simulado y procesos reales).
- **L-2** — el supervisor solo termina procesos que son hijos vivos del coordinador y cuya hora de creación coincide con la registrada
  (`w.<pid>.<inicio>`; `GetProcessTimes` / `starttime` de `/proc`); la vigilancia de caídas compara la misma identidad. Prueba con un
  proceso ajeno real al que apuntan las marcas.
- **L-1** — un *shard* con suma válida y contenido inválido o demasiado profundo se aparta como `.corrupt`; códec con `MAX_DEPTH = 200`
  (recorrido no recursivo) y `RecursionError` traducido.
- **L-4** — **cambio incompatible documentado**: `[parallel.recovery]` obligatoria (sin valores por defecto en el código); el error remite a
  `config/default_parallel.toml`. Cualquier TOML de ejecución de B5.2/B5.3 debe añadir la sección.
- **R-1** (nuevo, hallado por la CI Linux) — `events.jsonl` se creaba con modo `0644`; ahora `0600`. La prueba POSIX recorre todos los ficheros.

### Añadido

- `tests/integration/test_recovery_linux.py` (7 pruebas, solo Linux): `forkserver` con caída y veneno, plazos y reanudación; `flock` entre
  procesos; permisos; zombis; identidad por `starttime`; ausencia de procesos hijo residuales.
- Paso de CI «B5.4 Linux recovery evidence» con anotaciones verificables (entorno, resumen, fallos, pruebas pasadas) y `evidence/b5_4_remediation/`.
- Constantes de formato adicionales en `ALLOWED_NAMED_CONSTANTS` (identidad de proceso, profundidad del códec, cota de plazos).

### Pruebas (ejecutadas realmente)

| Entorno | Resultado |
|---|---|
| Linux — GitHub Actions `ubuntu-22.04`, Python 3.11.17, run `39466030525` (cabeza `a2992ec`) | **suite completa 1957 passed, 2 skipped**; evidencia B5.4: **56 passed**; mypy `--strict`, Ruff check/format ✔ |
| Windows 11 — Python 3.13.6, cabeza de la remediación (`a2992ec`) | **1946 passed, 10 skipped** (22 min 07 s); mypy `--strict` y Ruff limpios |

### Limitaciones (abiertas)

`P-05` y `PAR-013` siguen `PARTIAL` hasta la re-auditoría; H-1 de B4 (CPU del runner) abierto y no manifestado en este run; sin benchmark de
recuperación (B5.5); la identidad por hora de creación solo existe en Windows y Linux.

---

## [Remediación numérica H-1 (B4) y F-B55-1 (B3)] — 2026-10-21

Rama `fix/h1-fb551-numerical-remediation` (desde `main` = `8ceaf3a`; `REMEDIATION_H1_FB551.md`). No toca B5 ni `main`; sin benchmarks de ≥ 1.000 carteras.

### Corregido

- **H-1 (B4)** — el reintento en frío de Clarabel (`COLD_RETRY`) repetía el mismo método determinista y caía en el mismo estancamiento (`AlmostSolved`, residuo primal en 4·10⁻⁹…10⁻⁸ > `tol_feas = 1e-9`).
  Tras un estancamiento usa ahora otro equilibrado (`conic.retry_equilibrate`, **clave obligatoria nueva**) con las **mismas tolerancias**; tras `MaxIterations` conserva el primario; el estado del reintento
  nunca se promueve. Primer intento sin cambios. El oráculo SLSQP del test usa `ftol = 1e-12` (el anterior, 1e-15, estaba por debajo de la resolución de coma flotante).
- **F-B55-1 (B3)** — `rank_nodes`: las mejoras de utilidad a menos de `candidates.improvement_tolerance` del mejor del grupo son un empate y se desempatan por hash (antes, solo con mejoras idénticas bit a bit:
  el ruido de ulp decidía los finalistas y W1 devolvía 11 o 12 composiciones según el núcleo de OpenBLAS). Sin parámetro nuevo.

### Cambio incompatible

`[conic] retry_equilibrate` obligatoria en el TOML del motor (sin valores por defecto implícitos); `config_hash` cambia (claves de caché y diarios previos no coinciden).

### Pruebas (ejecutadas realmente)

| Entorno | Resultado |
|---|---|
| Windows 11, Python 3.13.6 (lock), baseline `main` `8ceaf3a`: `tests/unit/{candidates,frontiers,scenarios,optimizers,config}` | **910 passed** (5 min 32 s) |
| Mismo conjunto, rama de remediación | **926 passed** (5 min 28 s): +16 pruebas nuevas, 0 regresiones |
| Windows 11, suite **completa** de la rama (sola, en un worktree limpio) | **1962 passed, 10 skipped** (20 min 12 s; los 10 omitidos son pruebas solo-Linux/POSIX, los mismos que en B5.4) |
| mypy `--strict portfolio_engine`; Ruff check y format | limpios |
| GitHub Actions, run `3b1cc5c` (anotaciones públicas) | CI: **1973 passed, 2 skipped**, mypy/Ruff ✔; 12 runners: **926 passed** en los módulos afectados; ver `REMEDIATION_H1_FB551.md` §9 |

### Limitaciones (abiertas)

El efecto sobre B5.5 (PR #9) requiere rebasarlo (`xfail` de F-B55-1, baselines de trabajo y `config_hash`); hipótesis pendientes en `REMEDIATION_H1_FB551.md` §8; la CI no instala el lock.

---

## [Cierre tras AUDIT_H1_FB551 (PR #10)] — 2026-10-22

Auditoría independiente: `PASS_WITH_CHANGES` (0 BLOCKER, 0 HIGH, 2 MEDIUM, 4 LOW, 5 INFO). Esta fase es **solo documental y de herramientas**: sin cambios en código de producción, tolerancias, solvers ni algoritmos.

### Corregido

- **M-1** — `REMEDIATION_H1_FB551.md` §5.2/§7/§10.1: el cambio de B3 respecto a `main` se cuantifica (12/24 problemas aleatorios con conjunto de composiciones distinto, misma mejora, mejor mejora nunca peor; empates exactos en 14/14) en lugar de presentarse como caso marginal; «continuo» → «estable casi seguro».
- **M-2** — decisiones D-1…D-5 registradas con fundamento y consecuencias (`REMEDIATION_H1_FB551.md` §10.2): `retry_equilibrate = false`; desempate por `improvement_tolerance` con invariancia de conjunto; τ = 1e-9 absoluto; conservar `OPTIMAL_INACCURATE` sin relajar tolerancias; integrar el PR #10 antes de rebasar B5.5.
- Hallazgos LOW (L-1…L-4) e INFO documentados como pendientes (§10.3), sin corrección en esta fase.

### Añadido

- `AUDIT_H1_FB551.md` y `evidence/audit_h1_fb551/` (scripts reproducibles del auditor, sin modificar). `pyproject.toml`: esos scripts y el informe quedan fuera de Ruff (solo herramientas; `ruff check .` y `ruff format --check .` siguen activos sobre el resto).

### Verificación (ejecutada realmente, Windows 11, Python 3.13.6, lock)

| Comprobación | Resultado |
|---|---|
| Configuración por defecto | `retry_equilibrate = false`, `equilibrate = true`, `tol_feas = 1e-9`, `improvement_tolerance = 1e-9`, `accept_inaccurate_solutions = false` |
| `tests/unit/{candidates,frontiers,scenarios,optimizers,config}` (incluye `test_h1_clarabel_numerics.py` y `test_tie_stability.py`) | **926 passed** (5 min 30 s) |
| `mypy --strict portfolio_engine` | sin errores (176 ficheros) |
| `ruff check .` y `ruff format --check .` | limpios (381 ficheros) |
| CI de GitHub Actions | se consulta tras el push (ver informe de la fase) |

### Limitaciones (abiertas)

L-1…L-4 e I-1…I-3 (ver `REMEDIATION_H1_FB551.md` §10.3); PR #9 pendiente de rebase tras el merge del PR #10; la CI no instala el lock.

---

## [Cuelgue de CI en `_terminate_pool` (B5.4) — PR #10] — 2026-10-22

El run `39748508753` se canceló a los 44 min en la suite completa. Diagnóstico con ejecuciones acotadas y `py-spy` (`REMEDIATION_H1_FB551.md` §11): cuelgue **preexistente de B5.4**, no causado por H-1/F-B55-1 (4 de 10 ejecuciones de `test_recovery.py`, tres modelos de CPU).

### Corregido

- `kill_pool_workers(pool)` en `portfolio_engine/parallel/supervisor.py`, llamada por `_terminate_pool` antes de `shutdown(wait=True)`: terminar solo a los workers registrados podía dejar tomado el semáforo de lectura de `call_queue` y bloquear el cierre para siempre. Sin cambios en tolerancias, solvers ni algoritmos.

### Añadido

- `tests/integration/test_pool_shutdown_orphan_lock.py` (3 pruebas): cierre con cada worker como víctima (subproceso con vigilante) y orden determinista de `_terminate_pool`. Un control inicial no determinista falló en Linux y se sustituyó (documentado).

### Pruebas (ejecutadas realmente)

| Entorno | Resultado |
|---|---|
| CI, diagnóstico `test_recovery.py` ×10, antes de la corrección | **4/10 cuelgues** (EPYC 9V74, EPYC 7763, Xeon 8573C) |
| CI, mismo diagnóstico, después (runs `39761730686`, `39762891716`) | **0/20 cuelgues**, 21 passed por trabajo |
| CI completa `39762897683` (`fdef2ba`, EPYC 9V74) | **1976 passed, 2 skipped** (245 s), mypy/Ruff ✔ |
| Windows: `test_recovery.py`, `test_supervisor.py`, tests nuevos | 21 + 31 + 3 passed; mypy `--strict` y Ruff limpios |

### Limitaciones (abiertas)

Suite de integración completa de Windows no repetida tras la corrección; que el run cancelado fuese este cuelgue es coherente pero no demostrable (sin logs); `ci.yml` sigue sin tope por prueba (propuesta: `faulthandler_timeout`, no aplicada).

---

## [Bloque 5.5 — Benchmarks reproducibles, regresión de rendimiento y preparación de la auditoría final] — 2026-10-21

Rama `block5-benchmarks-final-audit` sobre `main` `8ceaf3a` (B5.4 integrado). Pendiente de auditoría independiente. Informe completo: `REPORT_BLOCK_5_5.md`; estimación de
gran escala y decisiones: `BLOCK_5_5_LARGE_SCALE_PLAN.md`; investigación de H-1: `INVESTIGATION_H1_B4.md`.

### Alcance

`RequirementID`: CFG-012, BEN-001, BEN-002, BEN-004, BEN-005, BEN-006, BEN-007, TST-005, GOV-012 (y PAR-003 por la calibración de AUTO). Módulos: `benchmark/` (`regression.py`,
`scaling.py`), `config/` (`scaling_config.py`, `default_benchmark.toml`), `benchmarks/`, `tests/performance/`, `tests/integration/`, `tests/unit/benchmark/`, documentación y CI.
Fuera de alcance y **sin tocar**: solvers, algoritmos, formulaciones, tolerancias y tests de B1–B5.4. Sin merge, sin despliegue, sin Arsys/Oracle/SQL Server, sin datos reales,
**sin ninguna carga de ≥ 1.000 carteras**.

### Añadido

- `ScalingBenchmarkConfig` (mezclas `ENG-MIX-BASE/LIGHT/HEAVY/CONIC` como supuestos de ingeniería, repeticiones, tope D-12, umbral `k × MAD`, tolerancia de iteraciones) con carga estricta.
- `benchmark/regression.py`: `compare_to_baseline` (umbral `k × MAD` del baseline, mínimo o mediana, guardas de host y de contador de trabajo, baselines JSON).
- `benchmark/scaling.py`: speedup, eficiencia, Karp–Flatt, modelo de coste del mix y `project_capacity` (rango, factor de extrapolación, sin precios inventados).
- `benchmarks/scripts/`: `synthetic_portfolios.py` (generador determinista con carteras degeneradas), `scaling.py` (secuencial/`spawn`/`forkserver` × workers × lote × hilos BLAS × modo de datos;
  T1, integridad y auditoría independiente de restricciones como condición de validez; topes `--max-wall` y `--max-rss-mb`), `scale_run.py` (`run` con guarda D-12; `estimate` sin ejecutar),
  `recovery_bench.py`, `profile_class.py`, `h1_numerical_probe.py`, `baseline.py`/`perf_reference.py`, `cross_platform_reference.py`, `ci_summary.py`, `_common.py`.
- Pruebas: `tests/unit/benchmark/test_regression_and_scaling.py` y `test_result_metadata.py`; `tests/integration/test_benchmark_harness.py` (generador, degeneradas, mutación del auditor, pool real ≡ secuencial,
  guarda D-12, `Watchdog`, tasas) y `test_cross_platform_reference.py` (por cartera); `tests/performance/test_performance_regression.py`.
- CI (`ci.yml`): instala el extra `bench` (`psutil`); pasos «B5.5 cross-platform diagnostic», «B5.5 Linux benchmark evidence» y «B5.5 H-1 numerical probe» (siempre se ejecutan, anotaciones públicas);
  disparador **temporal** por push a la rama (retirado al cerrar).
- `SECONDS_PER_HOUR` en `ALLOWED_NAMED_CONSTANTS` (conversión de unidades; única modificación de `test_architecture_rules.py`).
- Resultados versionados en `benchmarks/results/` (todos con commit limpio, versiones, host, comando y semilla).

### Resultados medidos (Windows 11, i7-13620H, memoria saturada: 6,7–8,8 GB de swap; datos sintéticos; detalle y límites en el informe)

- **Correctitud:** 100 celdas paralelas, **T1 = 0 y T0 = 0** (idénticas bit a bit a la secuencial), 208.452 soluciones revalidadas con **0 violaciones**, integridad de conteo al 100 %.
- **Modelo de coste del mix** `N·Σ sᵢ·cᵢ`: error de −1,3 % a +1,3 % en cuatro mezclas. **W1 domina** (82 % del tiempo de `BASE` con el 20 % de las carteras).
- **Escalado** (`BASE`, 100 carteras): 2 workers 1,12×; 4 workers 1,48×; 8 workers 1,68× (eficiencia 0,56 / 0,37 / 0,21; régimen estacionario 0,64–0,90 con 4). Arranque `spawn` en Windows 7–8 s (p95 21 s), en Linux 1,1–1,4 s.
- **Lote:** 1–5 y AUTO equivalentes (±1,5 %); 10 y 20 pierden +21 % y +72 %. **Hilos BLAS:** 2 no aportan. **Memoria:** worker RSS 163–198 MB, pico 880 MB (4 workers), 1,5 GB (8).
- **Recuperación:** diario +0,12 s/12 carteras; muerte de worker +13,6 s; tarea venenosa +21 s; cuelgue con plazo 3 s +1,8 s; cancelación 0,6 s; reanudación rehace exactamente lo no persistido.
- **Dimensión realista** (20 posiciones, universo 50/200/700): W1 2,7–3,3 s/cartera (+22 % de 50 a 700); resto 0,013–0,075 s.
- **Caché:** sin duplicados +9 % de tiempo; con 50 % / 75 % de duplicados 1,85× / 3,13×. **Datos compartidos:** modos equivalentes, sin ventaja de arranque.

### Hallazgos

- **F-B55-1 (Medio, abierto):** la búsqueda de candidatos de W1 devuelve una composición más en Linux que en Windows para 1 de las 2 carteras W1 de la referencia (12 frente a 11; 506 frente a 484 llamadas al solver); en las comunes
  `|Δpeso|` ≤ 3,5·10⁻¹². Pruebas con `xfail` no estricto solo fuera de Windows; baseline con variantes por plataforma. Remediación B3 independiente.
- **H-1 (B4):** mecanismo identificado y reproducido en Windows y Linux (tolerancia cónica 1e-9 en el borde + oráculo SLSQP `ftol=1e-15`); sin cambios (`INVESTIGATION_H1_B4.md`).
- Defecto propio corregido: `psutil` (extra `bench`) no estaba en la instalación de CI ⇒ 3 errores de colección en el primer run de la rama.

### Pruebas (ejecutadas realmente)

| Entorno | Resultado |
|---|---|
| Windows 11 — Python 3.13.6, baseline `8ceaf3a` (worktree limpio, sin carga concurrente) | **1946 passed, 10 skipped** (20 min 40 s); mypy `--strict` y Ruff limpios |
| Windows 11 — cabeza de código final | **1994 passed, 11 skipped, 0 failed** (16 min 09 s; +48 pruebas nuevas frente al baseline de 1946) |
| Linux — GitHub Actions `ubuntu-22.04`, Python 3.11.17, run `39527318745` (`933c0cc`, Xeon 8573C) | **2004 passed, 3 skipped, 1 xfailed** (4 min 33 s); benchmark de escala 10 con `spawn` y `forkserver` válido; 56 pruebas de B5.4 |
| Linux — GitHub Actions, run `39529975173` (`ed3eab4`, cabeza de documentación, AMD EPYC 9V45) | **2004 passed, 3 skipped, 1 xfailed** (3 min 21 s); F-B55-1 idéntica a la de los Xeon |
| Linux — runs previos | `f650607` (EPYC 7763): 3 errores de colección (extra `bench`); `6a8e79b` (Xeon 8573C) y `0e05505` (Xeon 6973P-C): 2 failed (C-28), diagnosticados |

### Estado de requisitos

Total 316 = **244 `VALIDATED` / 39 `PARTIAL` / 33 `NOT_IMPLEMENTED`**. `VALIDATED`: CFG-012, BEN-002, BEN-004, BEN-005, TST-005, PAR-003. `PARTIAL`: BEN-001, BEN-006, BEN-007 (10 y 100 ejecutadas; 1.200 no), GOV-012.
No se emite `BLOCK_5_STATUS`.

### Limitaciones

Medición local de una máquina con la memoria saturada (tiempos ×1,67 de variación observada con el mismo trabajo); nada medido en Arsys ni a ≥ 1.000 carteras; W2 y W5 sin medir a dimensión realista; E5 `fork`,
E7, E11, E12 y E14 no ejecutados; el fallo original de H-1 (EPYC 7763) no se ha vuelto a observar ni se ha descartado; la validación de `forkserver` en Windows es imposible (no existe).


---

## [Bloque 5.5 — Cierre tras AUDIT_BLOCK_5_5] — 2026-10-22

Rama `block5-benchmarks-final-audit` (PR #9) con `main` `75d8bb5` integrado (PR #10). Detalle y verificación en `REMEDIATION_BLOCK_5_5.md`. Sin merge, sin cambios directos en `main`, sin cargas de ≥ 1.000 carteras.

### Integrado y configurado

- `git merge origin/main` (conflictos solo de documentación en `CHANGELOG.md` y `TRACEABILITY.md`, resueltos conservando ambos lados). Entran: `conic.retry_equilibrate` (reintento en frío con otra numérica y las
  mismas tolerancias), desempate por banda en `rank_nodes`, `kill_pool_workers` y las pruebas asociadas.
- `conic.retry_equilibrate = false` en la configuración del motor usada por B5.5; `config_hash` **`5d3cdc5e…` → `86af211e…`**. Referencia multiplataforma, baselines de rendimiento, sonda H-1 y lote `ENG-MIX-BASE` regenerados sobre árbol limpio.

### Cambios numéricos y de composiciones (medidos)

- **Ninguno en la CPU de medida (Windows, núcleo `Haswell`)**: huella de 10 carteras / 565 soluciones bit a bit idéntica; W1 = 11 composiciones / 240 soluciones; contadores de `ENG-MIX-BASE` 10 y 100 idénticos
  (72.728 / 688.707 iteraciones; 652 / 6.404 llamadas al solver). En Linux/`SkylakeX` desaparece la variante de 12 composiciones (506 → 484 llamadas, 47.009 iteraciones frente a 46.934 en Windows, +0,16 %).
- Sonda H-1 con la tolerancia configurada: validez 1,00 en todas las perturbaciones (antes 0,35–1,00); el reintento termina `OPTIMAL` con las tolerancias configuradas, sin promover ningún estado.

### Corregido (AUDIT_BLOCK_5_5)

- **A-01/A-02/M-1/M-2:** `xfail` de F-B55-1 retirado; F-B55-1 reescrito como dependiente del núcleo de OpenBLAS; pruebas por cartera y de subproceso con `OPENBLAS_CORETYPE` forzado; paso de CI «OpenBLAS kernel matrix»;
  informe, investigación de H-1, trazabilidad y changelog sin las afirmaciones «no se ha vuelto a observar».
- **A-03/M-3:** contador `valid_weights_but_rejected` en la puerta de validez; cifras presentadas como re-auditorías; familias revalidadas declaradas. **A-04/M-4:** proyecciones rotuladas «orden de magnitud».
  **A-05/M-5:** `BEN-005`, `TST-005`, `PAR-003` → `PARTIAL`; `BEN-004` `VALIDATED` con criterio justificado. **A-06:** estados de estrategia en la huella. **A-07:** swap 6,7–11,1 GB.

### Estado de requisitos

Total 316 = **241 `VALIDATED` / 42 `PARTIAL` / 33 `NOT_IMPLEMENTED`** (B5.5 había llegado a 244 / 39 / 33). Sin cambios en los requisitos de B1–B4 (la evidencia de PR #10 ya figura en `main`).

### Pruebas (ejecutadas realmente)

| Entorno | Resultado |
|---|---|
| Windows 11 — Python 3.13.6, *worktree* limpio de `0be043a` (cabeza de código; los commits posteriores solo son documentación), sin carga concurrente | **2016 passed, 12 skipped, 0 failed** (16 min 30 s) |
| Ídem, baseline previo de B5.5 (`933c0cc`) | 1994 passed, 11 skipped; la diferencia son las pruebas de la remediación de `main` y las nuevas de este cierre |
| Linux — GitHub Actions, run `39774545136` (`0be043a`, Xeon Platinum 8573C, núcleo `SkylakeX`, Python 3.11.17) | **2028 passed, 3 skipped** (4 min 13 s); huella con 0 divergencias en los núcleos nativo, `Haswell` y `SkylakeX`; H-1 + desempate + multiescenario: 33 passed por núcleo |
| (CI de la cabeza final) | se añade tras publicar: ver la sección 9 de `REMEDIATION_BLOCK_5_5.md` en la rama |
| `mypy --strict portfolio_engine` | 0 errores (179 ficheros) |
| `ruff check .` y `ruff format --check .` | limpios |

### Limitaciones (abiertas)

BEN-007 (1.200 carteras) sin ejecutar por falta de autorización; W2/W5 y C-28 a dimensión realista/otras mezclas sin medir; sin comparación de tiempos en el destino; sin run nativo en EPYC 7763 posterior a la integración.
