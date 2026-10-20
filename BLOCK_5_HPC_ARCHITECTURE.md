# BLOCK_5_HPC_ARCHITECTURE — Auditoría arquitectónica y diseño HPC (Bloque 5.1)

Fecha: 2026-10-19. Rama: `block5-hpc-architecture` (desde `origin/main` = `271eaeb`, merge del PR #5).
Alcance de esta entrega: **solo diseño**. No se ha modificado código de producción, `MASTER_SPEC.md`, auditorías
previas ni configuración; no hay commit, push, PR, merge ni tag; no se ha accedido a SQL Server ni a datos
confidenciales; no se han ejecutado pruebas masivas.

Documentos hermanos: `BLOCK_5_IMPLEMENTATION_PLAN.md` (entregas B5.2–B5.5) y `BLOCK_5_BENCHMARK_PLAN.md`
(benchmarks y pruebas de regresión).

## 0. Convenciones de evidencia

| Etiqueta | Significado |
|---|---|
| **[H]** | Hecho verificado en el repositorio (fichero/línea o documento citado). |
| **[M]** | Medición real hecha o consultada en esta auditoría (fuente y condiciones indicadas). |
| **[HIP]** | Hipótesis **no medida**: debe confirmarse en B5.2–B5.5 antes de apoyarse en ella. |
| **[DEC]** | Decisión de diseño propuesta; las que requieren autorización figuran en el §14. |

Ninguna cifra de este documento es una promesa de rendimiento. Las mediciones [M] proceden de **otra máquina**
(Windows 11, CPU Intel, Python 3.13.6) distinta del servidor objetivo (Ubuntu 22.04, Ryzen 5 PRO 3600); sirven
para ordenar magnitudes y priorizar, no para predecir.

---

## 1. Resumen ejecutivo

1. **El cuello de botella medido no es el solver, es la generación de candidatos en Python/NumPy.** En las
   ejecuciones existentes (cartera de 20 activos, universo 50/200/700, 12 composiciones finalistas, 1 escenario)
   `candidate_generation` ocupa ~82–88 % del tiempo por cartera; la evaluación de las fronteras finalistas
   (donde está el solver QP) ocupa ~12–15 % [M, §4.2]. Esto favorece **paralelismo por procesos a nivel de
   cartera** (el trabajo es Python que retiene el GIL) y hace irrelevante, de momento, afinar hilos internos de
   los solvers.
2. **El coste por cartera depende enormemente de lo que se pida.** La frontera continua de una composición fija
   (20 puntos, 20 activos) cuesta del orden de 0,05–0,18 s; el pipeline completo con candidatos, ~6–7 s [M]. Por
   aritmética directa sobre esa medición, 22.000 carteras con el pipeline completo serían ~37–43 h en **un**
   proceso de aquella máquina (no es un pronóstico). **Qué incluye una «optimización de cartera» en la
   operación masiva es la decisión de mayor impacto (D-01)** y condiciona todo el dimensionamiento.
3. **La memoria compartida tiene poco que aportar hoy.** `mu`/`Σ` de 500 activos ocupan ~2 MB y el problema
   completo serializa a 2,1 MB (desempaquetado en 12 ms) [M]. Además, los modelos del repositorio **copian**
   los arrays al construirse (`readonly_float_array` usa `copy=True`) [H], de modo que un `SharedMemory`/`memmap`
   no evitaría la copia privada por worker sin tocar código de B1–B4 (fuera de alcance). El requisito PAR-004
   se cumple de todos modos con un mecanismo simple y auditable (§7).
4. **La caché de resultados casi no producirá aciertos entre carteras distintas.** La enmienda E-06 obliga a
   incluir siempre `CurrentPortfolioStateHash` en la clave [H]. Su valor real es: reanudación, reintentos y
   solicitudes duplicadas; no «acelerar 22.000 carteras distintas». Se diseña igualmente (CCH-*) pero con
   expectativas honestas (§8).
5. **La arquitectura propuesta** es: coordinador único + pool de procesos de larga vida (contexto
   `forkserver`/`spawn`, nunca `fork` por defecto en producción) + lotes de carteras con `SequenceID` + datos de
   mercado inmutables y direccionables por hash + planificación dinámica acotada (contrapresión) + diario
   (journal) local de ejecución para reanudar + métricas por tarea. El motor matemático **no** conoce SQL
   Server, Windmill ni HERMES: se integra mediante `Protocol`s (§11).
6. **Hay divergencias entre la petición y la documentación oficial** (escala, sistema operativo, ubicación de
   checkpoint/persistencia, `engine.py` inexistente). No se resuelven unilateralmente: §3 y §14.

Estado de diseño (v2, tras las decisiones del usuario del 2026-10-19): `BLOCK_5_DESIGN_STATUS = READY` para
iniciar B5.2 **previa aprobación expresa**; ver §14. (v1 era `NEEDS_DECISIONS`.)

---

## 2. Estado del repositorio y verificación inicial

| Comprobación | Resultado |
|---|---|
| Repositorio | `https://github.com/DarioJara/portfolio-optimization-engine.git`, directorio de trabajo `…\2.-Codigo\3.-Optimizador` |
| Rama al llegar | `block4-scenarios-robust-optimization`, HEAD `d964102`, árbol limpio, sincronizada con su remota |
| `origin/main` | HEAD `271eaeb` (merge del PR #5). `git merge-base --is-ancestor 271eaeb origin/main` → verdadero; `origin/main` contiene `d964102` y los commits del B4 (`105d6be`, `409eef3`, `878a07e`, `97f9129`) |
| `main` **local** | **Desactualizada**: va 6 commits por detrás de `origin/main` (su HEAD es `1c079f6`). No se modificó (no se hace merge ni pull sobre `main`) |
| Rama de trabajo | `block5-hpc-architecture`, creada con `git checkout -b … origin/main --no-track` (sin sobrescribir ninguna rama existente; solo se hizo `git fetch`) |
| Cambios locales previos | Ninguno (`git status` limpio antes de intervenir) |
| Suites | **No se ejecutaron en esta fase** (solo diseño). El baseline declarado en `AUDIT_BLOCK_4_CLOSURE.md` es 1.482 passed, `mypy --strict`, `ruff` verdes; esta auditoría no lo ha reproducido |

Observación: el tamaño real del baseline debe re-ejecutarse al inicio de B5.2 (regla de no regresión de
`CLAUDE.md`).

---

## 3. Divergencias entre la petición y la documentación oficial

La documentación oficial manda (`CLAUDE.md`, `MASTER_SPEC.md`). Nada de lo siguiente se ha modificado; se
documenta para decisión del usuario (§14).

| ID | Petición del Bloque 5.1 | Documentación oficial | Impacto |
|---|---|---|---|
| X-1 | ~22.000 carteras, universo ≤ 500 activos | GOV-012 / BEN-007 / `IMPLEMENTATION_PLAN`: ~1.200 carteras, ~20 activos, ~700 universo; «validar 10, 100 y 1.200 si los recursos lo permiten» | La capacidad objetivo es ~18× mayor que la oficial. Cambia el dimensionamiento y la Definition of Done del B5 |
| X-2 | Servidor Ubuntu 22.04 (Arsys) | `ARCHITECTURE.md` §11.3, `PAR-004` y el riesgo «Windows `spawn`» asumen Windows 11 | El diseño debe cubrir **ambos** (desarrollo Windows, producción Linux); `fork` es posible en Linux pero no recomendable (§6.2) |
| X-3 | B5.4 «Gestión de lotes, fallos y **recuperación**»; checkpoints y reanudación; persistencia de resultados | `IMPLEMENTATION_PLAN` B5: *fuera de alcance* SQL Server, staging, coordinador de persistencia (B6). B6 posee «Error Recovery», inyección de fallos, idempotencia | Se propone un **diario local de ejecución** en B5.4 (sin DB) y dejar la persistencia duradera en B6 (D-04) |
| X-4 | Integración futura con SQL Server, Windmill, HERMES, AAA-A | B6 (persistencia/SQL); no hay requisito para Windmill/HERMES/AAA-A | Solo `Protocol`s desacoplados en B5; nada concreto (D-10) |
| X-5 | Subfases B5.1–B5.5 | Un único «Bloque 5» con salida `BLOCK_5_STATUS = PASS | FAIL` | Compatible (subdivisión del mismo bloque); el estado oficial se emite al cerrar B5.5 |
| X-6 | El motor «ejecuta una optimización de cartera» | **No existe `engine.py` ni `PortfolioEngine.run`** [H]: `portfolio_engine/` no contiene `engine.py`; GOV-012 los prevé (`NOT_IMPLEMENTED`) y `TRACEABILITY` asigna el orquestador al B6 aunque el plan lo permite en B5 (`engine.py` integración de ejecución paralela) | Falta la «unidad de trabajo por cartera». Hay que definirla (D-02) |
| X-7 | Python en servidor | `pyproject.toml`: `requires-python >= 3.11`; Ubuntu 22.04 trae Python 3.10 | Requiere intérprete gestionado (uv/pyenv/deadsnakes) y verificar *wheels* manylinux de osqp/clarabel/pyscipopt (D-09) |
| X-8 | Dependencias | `threadpoolctl`, `psutil`, `duckdb`: **no** están en `dependencies` de `pyproject.toml`; `threadpoolctl` llega en el `.venv` solo vía `scikit-learn` (grupo `dev`); `psutil`/`duckdb` no están en el `.venv` [H] | PAR-007 y métricas de CPU/memoria exigen declararlas (D-09) |

---

## 4. Diagnóstico del motor actual

### 4.1 Flujo de ejecución de una optimización [H]

No hay orquestador de extremo a extremo. Los componentes existentes y su encadenamiento lógico:

```
RiskModel (mu_global, Sigma_global; MuSigmaVersion) + Universe + CurrentPortfolioState + PortfolioSpec + AssetCostVector
  └─ CandidateEngine.search()            candidates/candidate_engine.py   (screening, BeamSearch, LocalSearch)
       └─ UniverseSnapshot (referencias a mu/Sigma, sin copia)  +  CompositionFactory.prepare() (Σ_C n×n, compilación, factibilidad)
  └─ GlobalCandidateFrontierEngine.solve()   frontiers/global_frontier.py  (Pareto global de composiciones finalistas)
       └─ ContinuousFrontierEngine.solve()   frontiers/continuous_frontier.py
            └─ FrontierSession               frontiers/session.py   (1 workspace por composición × tratamiento; reutilizado entre puntos)
                 └─ SolverRouter → {OSQP, HiGHS(linprog), Clarabel, SCIP}  + SolutionValidator independiente
  └─ ScenarioEngine / MultiScenarioOptimizer / StrategyOptimizer   (B4: CVaR, robusto, Max Sharpe, VolTarget, EXACT_MIP)
```

La «unidad de trabajo por cartera» para el paralelismo (una *tarea*) es la composición de estas llamadas para un
`PortfolioID`. Hoy solo existe en scripts/tests (`tests/fixtures/candidates.py::search`,
`benchmark/candidate_suite.py`).

### 4.2 Hechos y mediciones disponibles

| # | Hecho / medición | Fuente | Tipo |
|---|---|---|---|
| 1 | Universo 50/200/700, 20 activos, 12 composiciones, 1.200 evaluaciones, 240 puntos de frontera: `candidate_generation` p50 ≈ 5,3 / 5,6 / 6,3 s (GROSS); `frontier_evaluation` ≈ 0,73–0,96 s; `total` ≈ 6,1 / 6,4 / 7,2 s. En NET con universo 700 el total fue 4,1 s | `benchmarks/results/candidate_engine_20260924T124637Z.json` (5 repeticiones; commit `6af836c+dirty`; Windows 11, Intel, Py 3.13.6) | [M] |
| 2 | Variabilidad: el mismo script dio 7,2 s (700, GROSS) y 4,1 s (700, NET) con las mismas 1.200 evaluaciones; la memoria del proyecto registra que los tiempos de esta máquina son **bimodales** (~5×) | resultados anteriores + `MEMORY.md` («Machine timing is bimodal») | [M] |
| 3 | Frontera de 20 activos, 21 resoluciones: `COLD_SETUP` ≈ 0,16 s (setup 0,11 s, 21 *setups*) frente a `WORKSPACE_REUSE` ≈ 0,05 s (setup 0,011 s, 3 *setups*); el solve medio por punto es ≈ 13–38 ms según tratamiento/método | `benchmarks/results/solver_reuse_20assets_20260923T172754Z.json` | [M] |
| 4 | Problema sintético de 500 activos (cartera de 20): `FrontierProblem` serializa con `pickle` (protocolo 5) en **2,1 MB**, se deserializa en **12 ms**; `Σ` = 2,0 MB | medición de esta auditoría (una muestra, `.venv`, Windows) | [M] |
| 5 | `CandidateEngine.search` sobre ese problema (universo 500, 20 activos, `base_config()`): **5,0 s** en un proceso (una sola muestra, indicativa) y `CandidateSearchResult` serializa a **61 KB** y hace *round-trip* con `pickle` sin error | idem | [M] |
| 6 | Importar `portfolio_engine.frontiers/candidates/scenarios` en un proceso nuevo: **4,6–5,2 s** (3 muestras, caché de bytecode caliente) | idem | [M] |
| 7 | Los modelos copian arrays al construirse: `readonly_float_array(...)` → `np.array(values, copy=True)` | `portfolio_engine/utils/numerics.py:9-13` | [H] |
| 8 | `UniverseSnapshot` guarda **referencias** a `mu` y `Σ` (no copia la covarianza global) y existe un test de no-copia con `tracemalloc` (PAR-006, `VALIDATED`) | `candidates/universe_data.py`; `tests/performance/test_no_full_sigma_copy.py` | [H] |
| 9 | `CompositionFactory` memoiza composiciones **dentro de una búsqueda**; no es la caché del B5 | `candidates/prepared.py`, `ARCHITECTURE.md` §3.4 #15 | [H] |
| 10 | No hay `lru_cache`/`functools.cache` ni estado global mutable detectable por *grep* en `portfolio_engine/` (revisión por búsqueda, no por análisis exhaustivo) | `grep -rn "lru_cache\|functools.cache" portfolio_engine` | [H] limitado |
| 11 | `derive_seed` (SHA-256 canónico) y `sequence_key`/`tie_break_key` existen y están validados; el orden de resultados por workers y batches es del B5 | `parallel/determinism.py`; `TRACEABILITY` PAR-009 (VALIDATED), PAR-010 (PARTIAL) | [H] |
| 12 | Toda la configuración de reproducibilidad del solver evita el reloj salvo `time_limit_seconds` (opcional) y los límites de tiempo de HiGHS, Clarabel, OSQP y SCIP | `config/default_engine.toml` (`adaptive_rho_interval` fijo «garantiza resultados reproducibles»); backends `*_backend.py` | [H] |
| 13 | HiGHS se invoca vía `scipy.optimize.linprog` (el motor no fija hilos de HiGHS); Clarabel no fija `max_threads`; OSQP no fija hilos; SCIP sí configura `parallel/maxnthreads = config.threads` | `highs_backend.py`, `clarabel_backend.py`, `osqp_backend.py`, `scip_backend.py:207` | [H] |
| 14 | Hardware de las mediciones: Windows 11, Intel Family 6 Model 186, Python 3.13.6, numpy 2.5.3, scipy 1.18.1, osqp 1.1.3, clarabel 0.11.1 | metadatos de los JSON | [H] |
| 15 | La cadena de B4 mide por formulación un orden de decenas de milisegundos con 10 activos y 3 escenarios (p. ej. MAX_SHARPE ≈ 43 ms, VOL_TARGET ≈ 28 ms de `total`) | `benchmarks/results/block4_formulations_20260925T175532Z.json` | [M] (escala pequeña) |

### 4.3 Diagnóstico por área

| # | Área solicitada | Estado observado | Hipótesis a medir |
|---|---|---|---|
| 1 | Flujo | Ver §4.1. No hay orquestador | Definir `run_portfolio` secuencial de referencia (D-02) |
| 2 | Matrices y restricciones | Σ_C (n×n) se extrae solo con composición definida; restricciones compiladas **por composición** (`ConstraintCompiler`), con `ConstraintHash`; cada composición candidata recompila [H] | [HIP] compilación y factibilidad previa pesan en los 5 s de `candidate_generation`; **perfilar con `cProfile` antes de optimizar** (B5.2, prerrequisito) |
| 3 | Escenarios | `ScenarioEngine.build` genera `mu_s`, `Σ_s` (PSD validada) por escenario [H]; S escenarios ⇒ S × (N×N) | [HIP] con S ≤ ~10 y N = 500, S·2 MB es asumible; medir |
| 4 | Solvers | Enrutador `SolverRouter`; OSQP (QP/LP), HiGHS (LP), Clarabel (SOCP/QP homogeneizado/CVaR con mandato), SCIP (EXACT_MIP, solo validación) [H] | Hilos internos: ver §6.5 [HIP] |
| 5 | Instancias de optimización | Un workspace por (composición, tratamiento) y reutilizado entre puntos (`FrontierSession`) [H]; el *setup* en frío cuesta ~10× el de reutilización [M] | Mantener **todos los puntos de una frontera en el mismo worker** (PAR-002) |
| 6 | Creación/reutilización | Objetos inmutables (`frozen`, `slots`) salvo workspaces y memoizaciones locales [H] | Un worker no debe conservar workspaces ni memoización entre carteras (§9.2) |
| 7 | Serialización | Problema 2,1 MB / resultado de candidatos 61 KB, ambos picklables [M] | Medir resultado completo (frontera + puntos + pesos) por cartera (B5.2) |
| 8 | Memoria | Σ global 2–4 MB; matriz de retornos T×N típica ≈ 5 MB con T=1.260, N=500 (cálculo, no medición) | Medir RSS/PSS por worker (B5.2/B5.5); el `import` carga numpy+scipy+pandas+pyarrow [HIP: cientos de MB] |
| 9 | Operaciones redundantes | Re-preparar `UniverseSnapshot`/`EligibleUniverseIndex` por cartera | [HIP] coste de construir el snapshot por cartera; medir en B5.3 antes de compartirlo |
| 10 | Dependencias compartidas | Compartible: `mu`, `Σ` (y `Σ_s`), matriz de retornos, índice de activos, metadatos numéricos. **No compartible**: restricciones compiladas, costes, `P/A/q/l/u` del solver, pesos actuales | Ver §9 |

### 4.4 Cuellos de botella: demostrados vs hipótesis

* **Demostrado [M]:** en el pipeline completo, la generación de candidatos domina (≈ 82–88 %); la evaluación de las
  fronteras finalistas es el resto; la variabilidad de tiempos de la máquina de desarrollo es alta.
* **Demostrado [M]:** el *setup* en frío del solver cuesta ~10× el de reutilización; la reutilización de workspace
  ya está implementada y debe preservarse en cada worker.
* **Hipótesis [HIP]:** (a) la compilación de restricciones + factibilidad + construcción de `PreparedComposition`
  explican gran parte de `candidate_generation`; (b) el arranque de un worker (`import` ≈ 5 s) es relevante solo
  si los workers se reciclan; (c) el coste de IPC es despreciable frente a segundos de cómputo por cartera
  (2 MB vs ~5 s), salvo en cargas W0 (frontera sola, ~0,05–0,2 s) donde puede pesar; (d) cuando HiGHS/Clarabel/OSQP
  corren en 1 hilo no hay pérdida apreciable; (e) el aumento de tiempo con SMT (12 hilos lógicos) es sublineal.

---

## 5. Requisitos oficiales del Bloque 5 y relación con B1–B4

Fuente: `IMPLEMENTATION_PLAN.md` (Bloque 5), `IMPLEMENTATION_PROMPTS.md` (Bloque 5), `TRACEABILITY.md`. Estado
actual: todos `NOT_IMPLEMENTED` salvo los marcados.

| RequirementID | Contenido (resumen) | Estado hoy | Relación con B1–B4 |
|---|---|---|---|
| CFG-011 | `ParallelConfig` (workers, `PortfolioBatchSize`/AUTO, modo de memoria compartida, hilos BLAS) | NOT_IMPLEMENTED | B1 `EngineConfig` lo prevé como opcional; sin defaults de negocio en código |
| CFG-012 | `BenchmarkConfig` completo | PARTIAL (subset micro, B2) | `benchmark/stats.py` (`summarize`) |
| PAR-001 | Unidad = `PortfolioID`/`PortfolioBatch`, nunca `FrontierPoint` | NOT_IMPLEMENTED | `FrontierSession` (B2) |
| PAR-002 | Puntos de una frontera en el mismo worker | NOT_IMPLEMENTED | SOL-009 (reutilización de workspace) |
| PAR-003 | `PortfolioBatchSize` + AUTO | NOT_IMPLEMENTED | — |
| PAR-004 | Memoria compartida read-only (shared_memory / memmap / worker-local) elegida por benchmark | NOT_IMPLEMENTED | BEN-004 |
| PAR-005 | No copiar/transmitir matrices globales por tarea | NOT_IMPLEMENTED | PAR-006 (B3, VALIDATED) |
| PAR-006 | Regla de submatrices | VALIDATED (B3) | — |
| PAR-007 | Control de sobresuscripción (threadpoolctl/env) | NOT_IMPLEMENTED | — |
| PAR-008 | Resultados independientes del orden de finalización (1 vs N workers, batch sizes) | NOT_IMPLEMENTED | PAR-010 |
| PAR-009 | Semillas deterministas por PortfolioID/ScenarioID | VALIDATED (B3) | `derive_seed` |
| PAR-010 | `SequenceID` y desempate | PARTIAL (B3: claves; B5: orden de workers/batches) | `sequence_key`, `tie_break_key` |
| PAR-011 | Planificación dinámica | NOT_IMPLEMENTED | — |
| PAR-012 | Nº de workers configurable; nunca `CPU_COUNT` implícito | NOT_IMPLEMENTED | — |
| PAR-013 | `WorkerInitializer`/`WorkerContext` | NOT_IMPLEMENTED | — |
| CCH-001…005 | Caché de resultados reales; clave compuesta con `CurrentPortfolioStateHash` siempre; hit evita el solver; no basta `CompositionHash`; límite por worker + métricas | NOT_IMPLEMENTED | E-06, `current_portfolio_state_hash` (B1), `ConstraintHash`, `config_hash` |
| BEN-001/002 | Timers y estadísticos completos (IPC, portfolios/s, solver calls/s) | PARTIAL | `benchmark/timers.py`, `stats.py` |
| BEN-004/005/007 | Barrido BatchSize/workers/memoria; baseline y detección de deterioro; 10/100/1.200 carteras | NOT_IMPLEMENTED | — |
| BEN-006 | Solo resultados de ejecuciones reales con metadatos | PARTIAL | `benchmarks/results/` |
| TST-005 | Tests de regresión de rendimiento | NOT_IMPLEMENTED | `tests/performance/` (hoy solo no-copia de Σ) |
| GOV-012 | Escala objetivo (1.200 carteras, 20 activos, 700 universo) | NOT_IMPLEMENTED | Ver X-1 |

Fuera de alcance oficial (se mantiene): SQL Server, staging, coordinador de persistencia (B6); cambios en
formulaciones matemáticas (si se detecta un error, se detiene y se reporta).

Deuda técnica LOW/INFO de `AUDIT_BLOCK_4_CLOSURE.md` que **interactúa** con B5 (se conserva, no se corrige aquí):

| Hallazgo | Interacción con B5 |
|---|---|
| F-03b (`StrategyResult.status` sigue `OPTIMAL` con `outcome=SOLVER_FAILURE`) | El agregador de resultados debe leer `is_valid_solution`/`outcome`, **no** solo `status` (§10) |
| F-04 (sin test del estado SCIP `timelimit`) | El mapeo de `TIME_LIMIT` debe tener test antes de apoyarse en él para timeouts de MIP (B5.4) |
| F-09 (`NonConvexBackend` mapea convergencia local a `OPTIMAL`) | Latente; no hay no-convexo concreto; el executor no debe asumir `OPTIMAL` = óptimo global |
| F-07 (`max_universe_size` solo en `ExactMIPValidator`) | Los lotes con EXACT_MIP deben limitar el tamaño por política propia (§6.6) |
| Nota de rendimiento (Clarabel con mandato vinculante, sin medir) | Medir en la clase W4 del plan de benchmarks |

---

## 6. Arquitectura HPC propuesta

### 6.1 Principios de diseño (invariantes)

1. **Corrección antes que velocidad.** Cada resultado paralelo debe ser equivalente al secuencial (§12 del
   plan de benchmarks). Ninguna optimización cambia tolerancias, estados ni formulaciones.
2. **Aislamiento total entre tareas.** Un worker mantiene únicamente (a) el *snapshot* de mercado inmutable y
   (b) la configuración inmutable. Todo lo demás (workspaces de solver, memoizaciones, restricciones compiladas,
   caches locales) se crea **por tarea** y se descarta al terminar. Esta invariante es la que hace verosímil la
   reproducibilidad independiente del orden y del número de workers.
3. **Estados de ejecución separados de estados de solver.** El executor añade un `ExecutionStatus` propio
   (`COMPLETED`, `FAILED_INPUT_VALIDATION`, `FAILED_EXCEPTION`, `TIMED_OUT`, `WORKER_CRASHED`, `CANCELLED`,
   `SKIPPED_BY_RESUME`); **nunca** reetiqueta `SolverStatus` (`OPTIMAL`, `OPTIMAL_INACCURATE`, `INFEASIBLE`, límites
   de iteración/tiempo, errores numéricos) ni lo convierte en `OPTIMAL`.
4. **La integridad prima sobre la velocidad:** un resultado solo se acepta si pasó la validación independiente
   dentro del worker (ya forma parte de cada sesión/estrategia); el coordinador verifica además integridad del
   transporte (hash del payload, `TaskID` esperado, sin duplicados).
5. **Sin acoplamiento externo.** El paquete matemático no importa DB, HTTP ni agentes (regla de arquitectura
   comprobable, §11).
6. **Configuración, no constantes.** Workers, tamaños de lote, límites de memoria y tiempo, política de
   reintentos, modo de datos compartidos y umbrales de benchmark proceden de `ParallelConfig`/`BenchmarkConfig`
   (CFG-011/012); ningún `os.cpu_count()` implícito (PAR-012).

### 6.2 Pool de procesos y política de arranque

Opción recomendada [DEC]: `concurrent.futures.ProcessPoolExecutor` (exigido por `IMPLEMENTATION_PROMPTS.md`) con
`mp_context` explícito, envuelto por un **supervisor** propio (`BatchExecutor`) que añade contrapresión,
reconstrucción del pool ante `BrokenProcessPool`, reintentos y cuarentena (§6.4).

| Opción | Evaluación |
|---|---|
| `ProcessPoolExecutor` + `forkserver` (Linux) / `spawn` (Windows) | **Recomendada.** Evita heredar hilos de OpenBLAS/HiGHS/SCIP o *locks* en estado inconsistente; con `set_forkserver_preload(["portfolio_engine…"])` el `import` (~5 s [M]) se paga una vez por *servidor*, no por worker (efecto a medir [HIP]) |
| `fork` | Más rápido de arrancar y comparte páginas por *copy-on-write*, pero **inseguro con librerías con hilos** (BLAS, SCIP) y con estado de hilos del padre; además Python 3.14 cambia el método por defecto en Linux a `forkserver`. Se mantiene solo como experimento de benchmark (E5), **no** como modo de producción |
| `multiprocessing.Pool` | Mismas limitaciones que `ProcessPoolExecutor` (sin timeout por tarea, un worker muerto puede bloquear), con API menos expresiva; sin ventaja |
| Procesos propios (`multiprocessing.Process` + colas) | Permite matar un worker concreto por *timeout duro* y aislar un fallo a una tarea; más código y más superficie de error. **Alternativa condicionada:** se evaluará en B5.4 solo si las pruebas de inyección de fallos muestran que `ProcessPoolExecutor` + supervisor no basta (D-06) |
| `joblib/loky` | Reutiliza executors y serializa con `cloudpickle`; añade dependencia y menos control del ciclo de vida. Rechazada como núcleo; admisible como referencia en benchmarks |
| Hilos (`ThreadPoolExecutor`) | La mayor parte del tiempo medido es Python con GIL (§4.4); los solvers pueden liberar el GIL pero eso no está verificado y no cubre el 82–88 % dominante. Rechazada [HIP: verificable midiendo GIL-release por solver] |
| Ray / Dask / Celery / RQ | Infraestructura distribuida innecesaria para un solo nodo (6 núcleos) y nueva superficie operativa/seguridad. Rechazadas en esta fase; la interfaz `RunControl` (§11) permite adoptar un orquestador externo después |
| Reescritura en C++/Numba/GPU | Riesgo matemático y de mantenimiento; contraria a «no sacrificar precisión». Rechazada |

Parámetros del pool (todos de configuración): `workers`; `max_tasks_per_child` (reciclado preventivo ante fugas
de memoria; por defecto sin reciclado hasta que B5.5 mida crecimiento de RSS; el reciclado cuesta ~5 s de
`import` por worker si no se usa `forkserver` con preload [M/HIP]); `mp_start_method` ∈ {`forkserver`,
`spawn`}; `max_in_flight_batches` (contrapresión).

### 6.3 Flujo de trabajo

```
RunRequest (lista de PortfolioRequest, manifiesto, configuración)         ← entrada externa vía Protocol
 1. Validación de entradas (esquema, unicidad de PortfolioID, hashes, universo/estado/spec coherentes)
 2. Resolución del MarketSnapshot (mu, Σ, Σ_s, retornos, índice, MuSigmaVersion, MarketDataTimestamp)  → SnapshotKey + hash
 3. Publicación inmutable del snapshot (§7)
 4. Planificación: clasificación por clase de coste → ordenación (LPT) → formación de PortfolioBatch con SequenceID
 5. Despacho con contrapresión (cola acotada) al pool; WorkerInitializer adjunta el snapshot UNA vez por worker
 6. Cada worker: por cada tarea → entradas frescas → pipeline matemático → validación independiente → TaskResult
 7. Coordinador: recibe ResultBatch → verifica integridad → anota en el diario (journal) → métricas
 8. Al terminar: ordenación canónica por SequenceID → resultados auditables + RunManifest + informe de errores
```

### 6.4 Concurrencia, contrapresión, fallos y reanudación

* **Cola acotada:** el coordinador mantiene como máximo `max_in_flight_batches` (≈ `workers` × factor de
  configuración) lotes enviados. Evita materializar 22.000 tareas y 22.000 resultados en memoria, y acota la
  memoria del coordinador.
* **Planificación dinámica (PAR-011):** los lotes se asignan a medida que los workers quedan libres (ya es el
  comportamiento de un executor con cola); el orden de envío es *longest-processing-time first* según el coste
  estimado (§6.7) para reducir la cola larga.
* **Fallos individuales:** una excepción dentro de una tarea se captura **dentro del worker**, se devuelve como
  `TaskResult` con `ExecutionStatus=FAILED_EXCEPTION` (tipo, mensaje truncado, traza acotada, hash de entrada) y
  el resto del lote continúa. Un fallo no contamina otras carteras ni el lote.
* **Caída de worker (`BrokenProcessPool`):** el supervisor reconstruye el pool, devuelve a la cola los lotes
  cuyo resultado no llegó con `attempt+1` y, tras `max_attempts` (configuración), aísla las tareas del lote
  sospechoso una a una (cuarentena) para identificar la «tarea venenosa», que queda `WORKER_CRASHED`.
* **Timeouts en tres capas [DEC]:** (1) *límite del solver* (`time_limit_seconds`, ya existente; cooperativo);
  (2) *plazo por tarea* comprobado por el worker entre fases del pipeline (cooperativo, produce `TIMED_OUT`);
  (3) *plazo de lote* en el coordinador (vigilante). Un cuelgue duro dentro de código nativo solo se resuelve
  matando el proceso: con `ProcessPoolExecutor` esto implica reciclar el pool y reintentar/aislar (la opción de
  procesos propios del §6.2 lo haría más fino). La semántica de `TIMED_OUT` y su relación con los estados de
  solver se define en el plan de pruebas.
* **Cancelación:** la solicitud de cancelación (señal `SIGTERM`/archivo-bandera/`RunControl.cancel`) detiene
  nuevos envíos; los lotes en curso terminan o expiran tras un periodo de gracia; todo lo completado se conserva
  en el diario. Los workers ignoran `SIGINT` (lo gestiona el coordinador).
* **Reanudación:** un `RunManifest` (identidad de la ejecución: hashes de config, snapshot, solicitudes y commit)
  + diario append-only por lotes permiten reanudar: al reiniciar se leen los `TaskID` ya `COMPLETED` y se
  vuelven a encolar solo los demás. Una reanudación **exige** coincidencia exacta de hashes del manifiesto; si
  cambian config, snapshot o código, se rechaza (no se mezclan resultados de configuraciones distintas).
* **Idempotencia:** `TaskID = hash(PortfolioID, hash de entradas, ConfigHash, SnapshotKey)`; reejecutar una tarea
  produce el mismo `TaskID` y, bajo las condiciones de determinismo (§9), el mismo resultado.

### 6.5 Solvers, hilos internos y sobresuscripción

No todos los solvers admiten el mismo esquema ni se comportan igual con varios procesos [HIP: verificar cada
uno en B5.2 con `threadpoolctl.threadpool_info()`, recuento de hilos del SO por proceso y medida de CPU].

| Solver | Uso en el repositorio [H] | Hilos internos | Tratamiento propuesto |
|---|---|---|---|
| OSQP 1.1.3 | QP/LP de fronteras (`osqp_backend.py`), reutilización de workspace | El backend `builtin` es mono-hilo [HIP: verificar en la build instalada] | Un proceso por cartera; sin ajuste adicional |
| HiGHS (vía `scipy.optimize.linprog`) | LP de MaximumReturn/MinCVaR | No se fijan hilos desde el motor; el valor por defecto de HiGHS podría usar hilos [HIP] | Medir hilos reales; si >1, limitar mediante variable de entorno/opción de HiGHS accesible desde SciPy o controlar con afinidad; si no es posible limitarlo, reducir `workers` en la clase LP |
| Clarabel 0.11.1 | Cono de segundo orden: Sharpe, mandato de volatilidad, robusta, CVaR con mandato (`clarabel_backend.py`) | El motor no fija `max_threads`; el valor por defecto podría ser «automático» para ciertos métodos de factorización [HIP] | Fijar explícitamente 1 hilo mediante `ConicConfig`/ajuste del backend **solo si se demuestra** que cambia el uso de hilos; cambiar un ajuste de solver requiere autorización (afecta a B4) → D-08 |
| SCIP/PySCIPOpt 6.2.1 | EXACT_MIP (solo validación) | `parallel/maxnthreads = config.threads` ya configurable; `threads = 1` = determinista [H] | `threads = 1` obligatorio bajo el pool; tarea MIP en carril propio (§6.6) |
| NumPy/SciPy (OpenBLAS/MKL) | Screening, factorizaciones, métricas | BLAS multihilo por defecto | `threadpoolctl.threadpool_limits(1)` en el initializer + `OMP_NUM_THREADS`/`OPENBLAS_NUM_THREADS`/`MKL_NUM_THREADS`=1 **antes** de importar numpy en el worker (`forkserver`/`spawn` lo permiten fijando el entorno del servidor) |
| Solvers comerciales (Gurobi/CPLEX/MOSEK) | Opcionales y **no obligatorios** (E-24); no están en el repositorio | Licencias por proceso/máquina/token | Fuera de alcance; el diseño reserva una `SolverFactory` por worker con comprobación de licencia en el initializer y fallo explícito. No se asume ningún solver comercial |

Licencias (informativo; **verificar con el equipo legal/operaciones antes de producción**): OSQP, Clarabel,
HiGHS y SciPy son de código abierto permisivo; SCIP pasó a Apache 2.0 en versiones recientes (verificar la
versión instalada). No se ha comprobado el texto de licencia de las *wheels* instaladas en esta fase.

Sobresuscripción: el modelo es *procesos × (1 hilo numérico + 1 hilo de solver)*. El total de hilos activos del
motor debe ser ≤ `workers` (+ coordinador, ligero). Como SQL Server y otras aplicaciones comparten el host,
**`workers` no se deduce de `nproc`** (PAR-012): se fija en configuración tras el barrido E2/E11/E12 del plan de
benchmarks, partiendo de un valor conservador (≤ núcleos físicos − reserva para SQL Server) hasta tener datos.

### 6.6 Agrupación por complejidad y carriles

Clases de coste (alineadas con los benchmarks W0–W5 del plan):

| Clase | Contenido | Solvers típicos | Notas |
|---|---|---|---|
| W0 | Frontera continua de composición fija | OSQP, HiGHS | Muy corta; el IPC puede pesar → lotes grandes |
| W1 | `CandidateEngine` + frontera global (FAST_PRODUCTION) | OSQP, HiGHS | Dominado por Python (82–88 % [M]) |
| W2 | W1/W0 × múltiples escenarios (modos B4) | OSQP, Clarabel | Coste ∝ S |
| W3 | CVaR | HiGHS (LP) / Clarabel con mandato | — |
| W4 | Robusta, Max Sharpe, VolTarget | Clarabel | Medir coste de Clarabel con mandato (nota B4) |
| W5 | EXACT_MIP (validación) | SCIP | Límite de tiempo y de tamaño propios (F-07); **carril aparte** con concurrencia propia y `threads=1` |

El `BatchPlanner` agrupa por `SnapshotKey` (obligatorio: un lote nunca mezcla snapshots) y por clase de coste;
los lotes W5 nunca se mezclan con W0–W4. El coste estimado por tarea se calibra con una tabla medida
(`n_held`, tamaño del universo, S, presupuestos de búsqueda de `CandidateConfig`); sin calibración se usa lote
fijo. El tamaño AUTO (PAR-003) apunta a un tiempo de pared objetivo por lote **configurable** (no se fija aquí),
con mínimo 1, máximo configurable, y al menos varios lotes por worker para equilibrar carga.

### 6.7 Persistencia de resultados, métricas y trazabilidad

* **Diario de ejecución (B5.4):** ficheros inmutables por lote en disco local (formato autodescriptivo:
  Parquet/JSON para escalares, `npz` o Arrow para pesos; **no `pickle`** como formato de reanudación, §6.8),
  más un índice atómico (escritura temporal + `fsync` + `rename`). Escritor **único** (coordinador): los
  workers nunca escriben en un almacén compartido (coherente con la regla de B6 de no escritura concurrente).
* **Métricas por tarea (BEN-001 completo):** `DataLoad`, `RiskModel`, `CandidateSelection`, `SolverSetup`,
  `SolverUpdate`, `SolverSolve`, `Frontier`, `Validation`, `IPC`, `PortfolioTotal`, `BatchTotal`; recuentos
  deterministas (llamadas a solver, iteraciones, evaluaciones de candidatos), PID del worker, `attempt`, bytes de
  entrada/salida serializados, RSS máximo, hilos de SO.
* **Trazabilidad / auditabilidad:** `RunManifest` (commit con indicador *dirty*, `ConfigHash`, `SnapshotKey` y
  hash de contenido, versiones de librerías, semilla raíz, hilos/entorno, `mp_start_method`, `workers`, host);
  por tarea: `TaskID`, `SequenceID`, hashes de entrada y salida; registro estructurado (JSON lines) con
  correlación `RunID/BatchID/TaskID`. `RunMetadata` formal y persistencia SQL son de B6.

### 6.8 Seguridad de procesos y datos

* `pickle` solo para IPC entre procesos de confianza de **la misma ejecución**; nunca se deserializa un fichero
  de procedencia no controlada (reanudación y datos externos usan formatos no ejecutables y hash).
* Los directorios temporales/snapshots se crean con permisos restrictivos (0700) y se limpian en `finally`;
  los segmentos `SharedMemory` (si se usan) tienen nombre aleatorio y se eliminan en el coordinador, con
  limpieza al arranque de segmentos huérfanos con el prefijo propio.
* Los workers no reciben credenciales ni cadenas de conexión. El acceso a SQL Server (B6) usará la cuenta
  `aaa_reader` de solo lectura desde un `MarketDataProvider` en el coordinador, nunca desde los workers.
* Sin `shell=True`, sin ejecución de código de la entrada; los mensajes de excepción se truncan y se escapan antes
  de registrarse (evitar volcar datos de cartera en logs de nivel INFO).

---

## 7. Datos compartidos de solo lectura (PAR-004/005, §58–59)

### 7.1 Qué se comparte y qué no

| Elemento | Compartible entre carteras | Condición de validez |
|---|---|---|
| `mu_global`, `Sigma_global`, `Σ_s`/`mu_s` por escenario, matriz de retornos, índice de activos, metadatos numéricos del universo | Sí | Mismo `MuSigmaVersion`, `MarketDataTimestamp`, conjunto de escenarios (`ScenarioHash`) y universo; el `SnapshotKey` lo identifica; el contenido lleva hash |
| `UniverseSnapshot`/`EligibleUniverseIndex` | **Solo si** coinciden banderas de elegibilidad, restricciones y política de restringidos | [HIP: puede depender de la cartera] — decidir con perfil en B5.3 |
| Restricciones compiladas, `AssetCostVector`, pesos actuales, `CurrentPortfolioStateHash`, `P/A/q/l/u`, workspaces de solver, resultados | **No** | Dependen de mandato, costes, pesos actuales y fecha de valoración |
| `Σ_C` (n×n) por `CompositionHash` | Matemáticamente válido (depende solo de Σ global y de la composición) pero de coste ~µs; **no se cachea** | — |

### 7.2 Mecanismos evaluados

| Mecanismo | Pros | Contras | Veredicto |
|---|---|---|---|
| A. Datos pasados al initializer (pickle una vez por worker) | Trivial, portable (spawn/forkserver/Windows), sin ciclo de vida del SO. A 2–4 MB × workers es insignificante | Una copia privada por worker (pero ya es el caso, §3 de hechos) | **Candidata de referencia** |
| B. Worker-local desde ficheros (`np.load` de un bundle direccionado por hash) | Robusta ante reinicios de worker y reanudación; auditable; sin IPC | I/O de arranque (pequeña) | **Recomendada por defecto** [DEC]: bundle de solo lectura en directorio 0700 |
| C. `np.load(mmap_mode="r")` / `np.memmap` | Páginas compartidas vía caché de páginas del SO; sin IPC | Los modelos del repo **copian** al construirse (`copy=True`) → el beneficio se anula salvo cambio en B1–B4 | Medir; probablemente equivale a B en memoria privada |
| D. `multiprocessing.shared_memory` | Memoria física única | Riesgo de segmentos huérfanos tras caída (`/dev/shm`), advertencias del *resource tracker*, ciclo de vida complejo; sin beneficio real si el modelo copia | Rechazada como defecto; incluida en el benchmark E4 para cumplir la regla del spec («según benchmark») |

La elección final (A vs B vs C vs D) se hará **por medición** (BEN-004) en B5.3; la recomendación B es
provisional. Pruebas: arrays con `flags.writeable == False`, el hash del bundle se verifica al adjuntar, un
intento de escritura falla, el tamaño de la carga útil de cada tarea es pequeño y acotado (PAR-005), y el
conjunto de segmentos/ficheros temporales queda vacío tras éxito, excepción y caída forzada.

---

## 8. Caché (CCH-001…005)

* **Qué se cachea:** `CompositionFrontierResult` completo (no banderas), por worker, con límite configurable de
  entradas/bytes y métricas de aciertos/fallos (CCH-001, CCH-005).
* **Clave (CCH-002/004):** `CompositionHash`, `ScenarioID`, `ScenarioHash`, `ConstraintHash`, `MuSigmaVersion`,
  `TransactionCostHash`, `FrontierConfigHash`, `ConfigHash` (incluye `OptimizationHorizonYears`),
  `MarketDataTimestamp` y **`CurrentPortfolioStateHash` siempre** (E-06). Igualdad de `CompositionHash` es
  insuficiente (CCH-004).
* **Un acierto elimina el cálculo (CCH-003):** el contador de llamadas a `solve()` debe quedar a cero.
* **Expectativa realista [HIP, a medir con cargas con duplicados]:** al incluir siempre los pesos actuales, los
  aciertos entre carteras con distinto estado serán prácticamente nulos. Casos de acierto: solicitudes
  duplicadas, reintentos, misma cartera con distintos escenarios que comparten tratamiento, y reanudaciones.
* **Riesgos de corrección:** contaminación entre carteras (clave incompleta) y claves dependientes de la
  representación de flotantes. Mitigación: claves a partir de hashes canónicos ya existentes (`canonical_json`,
  `hash_float_array`), prueba de sensibilidad por componente y prueba «caché activada = caché desactivada
  bit a bit» sobre cargas con duplicados. La caché se entrega **desactivada por defecto** (`cache.enabled=false`)
  hasta pasar la auditoría.
* **No se cachea:** resultados de solver individuales, workspaces, nada entre scopes con claves distintas.

---

## 9. Determinismo y reproducibilidad

### 9.1 Clases de igualdad

| Clase | Definición | Cuándo se exige |
|---|---|---|
| T1 — numérico (**criterio de aceptación, D-07**) | Igualdad dentro de las tolerancias ya existentes y justificadas (§9.2) | Siempre: secuencial vs paralelo, distintos `workers`/`BatchSize`/orden, entre máquinas |
| T0 — idéntico (**solo diagnóstico**) | Igualdad bit a bit tras ordenar por `SequenceID` | **No es requisito** (D-07 aprobado con ajustes). Se mide y se informa como indicador de determinismo; si no se cumple en la misma máquina se investiga la causa, pero no falla la fase por sí solo si T1 se cumple |
| T2 — estadístico | Distribuciones de tiempos/consumos | Solo benchmarks |

Comparación bajo T1 (D-07): se comparan **restricciones** (revalidación independiente), **estados** (de solver y
de ejecución), **pesos**, **resultados** (objetivo, composición, puntos de frontera) y **métricas**, según
corresponda a la clase de carga. **Una diferencia de estado de solver nunca se acepta automáticamente:** se
investiga (causa, reproducibilidad, tolerancias implicadas) y se documenta en el informe de fase antes de
cualquier decisión. Las instrucciones BLAS/AVX de distintas CPUs pueden producir diferencias de redondeo, de ahí
que T1 sea el criterio. Se conserva la hipótesis [HIP] de que, con 1 hilo BLAS y estado aislado por tarea, el
resultado es idéntico en la misma máquina (el repositorio fija `adaptive_rho_interval` y deriva semillas con
`derive_seed`); se verifica como diagnóstico en B5.2 (PAR-008).

### 9.2 Tolerancias para T1 (propuesta; no se modifican las existentes)

Se reutilizan, sin cambiarlas, las tolerancias ya aceptadas: las de validación del `SolutionValidator`
(`budget/bound/constraint_tolerance = 1e-7`, `variance_tolerance = 1e-12`), las de deduplicación (`1e-6` en
pesos, `1e-8` en retorno/volatilidad) y la de regresión numérica dorada del repositorio
(`tests/numerical_regression/test_frontier_golden.py::TOLERANCE = 1e-6`). La propuesta de T1 es: **pesos
y métricas dentro de `1e-6` absoluto** (misma que la regresión dorada), estados de solver **idénticos** (un
cambio de estado nunca se tolera), `ConstraintHash`/`CompositionHash`/`CurrentPortfolioStateHash` idénticos.
Una tolerancia distinta requiere justificación en el informe de la fase y aprobación (D-07).

### 9.3 Fuentes de no determinismo a eliminar o controlar

Orden de finalización (se ordena por `SequenceID`); lotes distintos (el resultado de una cartera no depende de
sus vecinas de lote); semillas (`derive_seed` por `PortfolioID`/`ScenarioID`, no `hash()` de Python);
`PYTHONHASHSEED` (no se usa `hash()`; test ya existente en B3); límites de tiempo de pared del solver y del
pipeline (provocan resultados dependientes de la carga: **las ejecuciones de equivalencia se hacen sin límites de
pared, o el estado `TIME_LIMIT` se compara aparte**); hilos BLAS (fijados a 1); reutilización de estado entre
tareas (prohibida por la invariante 2); orden de iteración de colecciones (`dict`/`set`) en el pipeline [HIP:
revisar con la prueba de permutación]; coma flotante en reducciones paralelas (no se hacen reducciones entre
carteras).

---

## 10. Integridad de resultados

* El agregador usa `is_valid_solution`/`outcome` y no solo `status` (deuda F-03b).
* Una cartera cuyo estado de solver sea `INFEASIBLE`, `OPTIMAL_INACCURATE` o límite de iteración/tiempo se
  registra tal cual en `TaskResult` (con el estado de solver original), **no** como error de ejecución.
* Conteo de invariantes por ejecución: `|tareas enviadas| = |COMPLETED| + |FAILED_*| + |TIMED_OUT| +
  |WORKER_CRASHED| + |CANCELLED|`; cada `TaskID` aparece exactamente una vez en el diario final; cualquier
  discrepancia aborta el cierre de la ejecución como inválido.
* Revalidación independiente: el worker ya valida; el coordinador, en modo de verificación configurable,
  re-valida una muestra (o el 100 % en pruebas) con `SolutionValidator` sobre los pesos recibidos.

---

## 11. Integración futura desacoplada (no implementada en B5)

Interfaces mínimas (`typing.Protocol`) en el paquete `parallel/` (o `parallel/protocols.py`), sin dependencias de
DB/HTTP:

| Interfaz | Responsabilidad | Implementaciones en B5 | Implementaciones futuras (B6 / fuera) |
|---|---|---|---|
| `MarketDataProvider` | `load_snapshot(request_key) -> MarketSnapshot` | `SyntheticProvider`, `FileSnapshotProvider` | `SqlServerProvider` sobre `CopilotMapfre` con cuenta `aaa_reader` (solo lectura; B6) |
| `PortfolioRequestSource` | iterador de `PortfolioRequest` validados | lista en memoria, JSONL | lectura de tablas/colas; productores de Risk Budget, Asset Allocation y Fund Picking (AAA-A) solo emiten `PortfolioRequest` |
| `ResultSink` | `append(batch)`, `finalize(manifest)` | diario local | staging Parquet/DuckDB y SQL Server (B6, escritor único) |
| `RunControl` | `submit / status / cancel / resume`, eventos de progreso | API Python + CLI que lee/escribe JSON | envoltorio invocado por Windmill/HERMES (SSH/HTTP sobre Tailscale) sin importarse desde el paquete matemático |
| `ProgressReporter` | eventos estructurados | log JSON lines | métricas hacia un panel |

Reglas: (1) los modelos de petición/resultado son datos puros serializables y versionados (`schema_version`);
(2) ningún módulo de `portfolio_engine` importa `pyodbc`, `sqlalchemy`, `requests` ni SDKs de agentes
(*test de arquitectura* en `tests/unit/test_architecture_rules.py`); (3) la orquestación Oracle/HERMES→Arsys es
una decisión de despliegue: el coordinador corre en Arsys y expone `RunControl`; no se diseña ni se prueba red
alguna en esta fase.

---

## 12. Decisiones arquitectónicas y alternativas rechazadas

| ID | Decisión | Alternativas rechazadas | Motivo |
|---|---|---|---|
| AD-1 | Paralelismo por **procesos**, unidad = cartera/lote (PAR-001) | Hilos; paralelismo por `FrontierPoint` | GIL en el 82–88 % del tiempo [M]; la reutilización del workspace (10×) se perdería con granularidad fina [M] |
| AD-2 | `ProcessPoolExecutor` con contexto `forkserver`/`spawn` y supervisor | `fork`; `Pool`; `loky`; Ray/Dask/Celery | Seguridad con librerías con hilos; requisito del prompt; un solo nodo; ver §6.2 |
| AD-3 | Estado de worker = snapshot inmutable + config; el resto por tarea | Workers con caché/warm-start entre carteras | Garantiza T0 y evita contaminación; el warm-start entre carteras distintas no es matemáticamente trasladable |
| AD-4 | Datos compartidos: elegir por benchmark; referencia B (ficheros hash-direccionados) | `SharedMemory` por defecto | Beneficio nulo mientras los modelos copien; riesgos de ciclo de vida |
| AD-5 | Caché por worker, con clave completa + `CurrentPortfolioStateHash`, desactivada por defecto | Caché global compartida entre procesos; clave por `CompositionHash` | Corrección (E-06, CCH-004); sin evidencia de ganancia |
| AD-6 | Estados de ejecución separados de los de solver | Mapear fallos de ejecución a estados de solver | Mantiene el contrato de `SolverStatus` |
| AD-7 | Diario local append-only con escritor único | Que cada worker escriba; DuckDB compartido por todos | Seguridad ante concurrencia; coherente con B6 |
| AD-8 | Contrapresión + LPT + lotes dimensionados por tiempo objetivo | Enviar todo de golpe; lotes de 1 | Memoria acotada, buen balance de carga, bajo sobrecoste |
| AD-9 | Interfaces `Protocol` para integración | Importar SQL/Windmill/HERMES en el motor | Aislamiento matemático/seguridad |
| AD-10 | No optimizar algoritmos matemáticos en B5; perfilar y **reportar** | Modificar `CandidateEngine` para acelerar | Fuera de alcance (módulos permitidos); riesgo matemático |

---

## 13. Matriz de riesgos técnicos

Probabilidad (P) e impacto (I): B/M/A. «Medir» = hipótesis que se confirma/refuta en B5.2–B5.5.

| ID | Riesgo | P | I | Mitigación | Detección/prueba |
|---|---|---|---|---|---|
| R-01 | Coste por cartera × 22.000 inviable con el pipeline completo (≈ decenas de horas por proceso [M]) | A | A | Definir el alcance por clase (D-01); perfilar; reducir presupuestos de búsqueda por **configuración** (no por código); más workers solo hasta el límite de la máquina | Barridos E1–E2; proyección a partir de 1.000 carteras antes de lanzar 22.000 |
| R-02 | Resultados paralelos ≠ secuenciales (contaminación, orden, estado compartido) | M | A | Invariante AD-3; sin estado entre tareas; pruebas de permutación/aislamiento | PAR-008, §12 del plan de benchmarks |
| R-03 | Sobresuscripción de hilos (BLAS, HiGHS, Clarabel por defecto) | M | M | `threadpoolctl` + env antes de importar; inspección de hilos por proceso | Prueba de hilos por worker |
| R-04 | Competencia con SQL Server por CPU/RAM | A | M | Workers < núcleos disponibles; límites de memoria por worker; prueba E12 con carga sintética | Medición de latencia de cola y de RSS bajo carga |
| R-05 | Fugas de memoria/segmentos tras caídas | M | M | Context managers; `max_tasks_per_child` configurable; limpieza de huérfanos | Prueba de caída forzada (kill -9) + listado de `/dev/shm` y temporales |
| R-06 | `BrokenProcessPool` deja tareas perdidas/duplicadas | M | A | Supervisor con reintento por `TaskID`; contabilidad de invariantes | Inyección de fallos; invariante de conteo |
| R-07 | Tareas venenosas (segfault en SCIP/Clarabel) bloquean un lote | B | M | Cuarentena una a una; carril W5 aparte | Test con tarea que mata el proceso |
| R-08 | Límites de tiempo de pared hacen el resultado dependiente de la carga | M | M | Límites de iteración para ejecuciones de equivalencia; estado `TIMED_OUT` independiente; documentarlo | Pruebas con y sin límite |
| R-09 | Diferencias numéricas entre Windows/Intel y Linux/Ryzen | A | B | Clases T0/T1; baseline por host | Comparación cruzada con tolerancias §9.2 |
| R-10 | Caché con clave incompleta devuelve resultado de otra cartera | B | A | Clave completa; prueba por componente; desactivada por defecto | CCH-002/004 |
| R-11 | Python 3.10 en Ubuntu 22.04 incompatible con `>=3.11`; wheels no disponibles | M | M | Intérprete gestionado; verificar wheels manylinux x86_64 | Instalación limpia en CI/servidor (D-09) |
| R-12 | Dependencias no declaradas (`threadpoolctl`, `psutil`) | A | B | Declararlas y fijarlas en `requirements-lock.txt` | `pip check` en entorno limpio |
| R-13 | Timings ruidosos/bimodales de la máquina invalidan comparaciones | A | M | Contadores deterministas, mínimo de N repeticiones, mediana + mínimo, metadatos de carga | Protocolo del plan de benchmarks |
| R-14 | Deserialización de datos no confiables (pickle) | B | A | Formatos no ejecutables para disco/red; pickle solo IPC local | Revisión + test de arquitectura |
| R-15 | Ejecución de EXACT_MIP degrada el resto (tiempo, memoria) | M | M | Carril aparte, `threads=1`, límites de tiempo y tamaño | Benchmark W5 |
| R-16 | Cambios de B5 rompen B1–B4 | B | A | Reglas de no regresión; B5 no toca módulos matemáticos; interruptor `parallel.enabled=false` | Suite completa (1.482 tests) en cada entrega |
| R-17 | Alcance deriva (persistencia/SQL en B5) | M | M | Límite explícito (X-3, X-4); diario local sin DB | Revisión de alcance en cada gate |
| R-18 | Cuello de botella en el coordinador (serialización, journal, ordenación) | B | M | Lotes grandes; escritura por lotes; medir `IPC` y tiempo del coordinador | Utilización de CPU del coordinador |
| R-19 | Colisión de ficheros temporales/snapshots entre ejecuciones concurrentes | B | M | Directorio por `RunID` con permisos 0700; bloqueo por ejecución | Prueba de dos ejecuciones simultáneas |

---

## 14. Registro de decisiones (v2, 2026-10-19) y estado de lo abierto

Las decisiones del usuario sobre D-01…D-13 se incorporan aquí. En caso de conflicto con el texto anterior del
documento, **prevalece este apartado** (el §14b conserva el texto original de las preguntas, ya superado).

### 14.1 Aprobadas

| ID | Decisión del usuario | Efecto sobre el diseño |
|---|---|---|
| D-01 | El motor admite un **workload configurable por cartera**: cada trabajo ejecuta una estrategia individual o un pipeline compuesto de operaciones existentes; no se asume que las 22.000 carteras ejecuten todas las estrategias | `WorkloadSpec` por `PortfolioRequest` (§14.3). Clases W0–W5 definidas formalmente a partir de operaciones reales en `BLOCK_5_BENCHMARK_PLAN.md` §2. El mix de benchmark es un **supuesto de ingeniería** configurable, no datos de AAA-A |
| D-02 | Se creará después una función secuencial de referencia que compone los motores existentes sin cambiar sus algoritmos | `parallel/task.py::run_portfolio` (B5.2) |
| D-13 | Ubicación en `parallel/task.py`; `engine.py` reservado al Bloque 6 | X-6 resuelta |
| D-07 (con ajustes) | No se impone igualdad bit a bit como requisito universal; se usan las tolerancias existentes de `MASTER_SPEC.md` y los tests dorados; se comparan restricciones, estados, pesos, resultados y métricas según corresponda; las diferencias de estado se investigan, no se aceptan automáticamente | §9.1 reescrito: T1 es el criterio; T0 es solo diagnóstico |
| D-09 | Python ≥ 3.11 en entorno aislado, sin tocar el Python del sistema; dependencias justificadas, con versiones compatibles y bloqueo reproducible | Entorno propio (uv/venv/pyenv) en Arsys; `threadpoolctl` y `psutil` se justifican en `pyproject.toml` y se fijan en `requirements-lock.txt` en B5.2 (paso 0); se verificará la disponibilidad de *wheels* manylinux de osqp/clarabel/pyscipopt y se regenerará el lock en Linux |
| D-05 (condicional) | P-01…P-08 se documentan como **requisitos propuestos**, con fuentes y criterios de aceptación; no `VALIDATED` sin pruebas; sin modificar `MASTER_SPEC.md` | Tabla en `BLOCK_5_IMPLEMENTATION_PLAN.md` §2.2. No se añaden a `TRACEABILITY.md` en esta fase |

### 14.2 Diferidas (no bloquean B5.2)

| ID | Posición vigente | Cuándo se reabre |
|---|---|---|
| D-03 | Se mantienen los criterios oficiales 10/100/1.200. 5.000 y 22.000 son **objetivos adicionales de capacidad** para AAA-A, sujetos a benchmarks y a una eventual actualización formal del plan | Al cerrar B5.5 con datos medidos |
| D-04 | Aprobado **conceptualmente** un diario local mínimo de recuperación en B5.4; contrato exacto por definir | Inicio de B5.4 |
| D-06 | Preferencia inicial por `ProcessPoolExecutor` + supervisor; pendiente de pruebas de fallos y timeouts | B5.4 |
| D-08 | Ningún backend de solver se modifica sin evidencia de sobresuscripción y regresión completa | Tras E7 (B5.2/B5.3) |
| D-10 | Interfaces abstractas y CLI; sin conexiones externas en este bloque | B5.4 |
| D-11 | Workers y límites de RAM se dimensionan tras benchmarks controlados, reservando recursos para SQL Server y otros servicios de Arsys | B5.5 |
| D-12 | **No** hay autorización para benchmarks masivos en Arsys. Se solicitará aprobación específica antes de cualquier carga ≥ 1.000 carteras | Antes de E-≥1.000 |

### 14.3 Diseño derivado de D-01: `WorkloadSpec`

Cada `PortfolioRequest` lleva un `WorkloadSpec` (datos puros, serializable, con `schema_version` y hash que entra
en `TaskID`):

* `operations`: lista ordenada de operaciones, cada una un nombre del catálogo cerrado siguiente con sus
  parámetros, **todos procedentes de configuración**:

| Operación (catálogo) | Motor existente que la implementa [H] |
|---|---|
| `FRONTIER_FIXED_COMPOSITION` (tratamiento GROSS/NET/POST_COST, método de malla) | `ContinuousFrontierEngine.solve` |
| `CANDIDATE_SEARCH` + `GLOBAL_FRONTIER` | `CandidateEngine.search` + `GlobalCandidateFrontierEngine.solve` |
| `SCENARIO_BUILD` | `ScenarioEngine.build` |
| `MULTI_SCENARIO` (modo: `SCENARIO_INDEPENDENT`, `EXPECTED_SCENARIO_UTILITY`, `WORST_CASE`, `BASE_WITH_STRESS_CONSTRAINTS`) | `MultiScenarioOptimizer.solve_independent / solve_expected_utility / solve_worst_case / solve_base_with_stress` |
| `STRATEGY_CVAR` (`MIN_CVAR`, `CVAR_LIMITED`) | `StrategyOptimizer.cvar` |
| `STRATEGY_ROBUST` | `StrategyOptimizer.robust` |
| `STRATEGY_MAX_SHARPE`, `STRATEGY_VOL_TARGET` | `StrategyOptimizer.max_sharpe / volatility_target` |
| `EXACT_MIP_VALIDATION` | `ExactMIPValidator.validate_heuristic` |

* Las dependencias entre operaciones (p. ej. `GLOBAL_FRONTIER` requiere `CANDIDATE_SEARCH`; `EXACT_MIP_VALIDATION`
  requiere una composición heurística) se validan **antes** de despachar (validación de entradas); una
  combinación inválida es `FAILED_INPUT_VALIDATION`, no un fallo de ejecución.
* La unidad de paralelización sigue siendo la cartera (PAR-001): todas las operaciones de un `WorkloadSpec`
  corren en el mismo worker, de modo que puedan compartir objetos intermedios **dentro** de la tarea
  (composiciones, `Σ_C`) sin estado entre tareas.
* Una cartera puede pedir una sola operación (p. ej. solo `STRATEGY_ROBUST`) o un pipeline; el motor no impone
  un conjunto fijo.
* El catálogo es un contrato de B5.2; añadir operaciones nuevas no cambia algoritmos. Si una operación del
  catálogo no puede invocarse sin modificar un motor de B1–B4, se reporta y no se implementa (regla de alcance).

### 14.4 Bloqueantes frente a diferidas

* **Bloqueantes para iniciar B5.2:** ninguna decisión de las listadas queda sin resolver (D-01, D-02, D-13, D-07,
  D-09, D-05 resueltas con las condiciones de §14.1). Condiciones de entrada propias de B5.2 (no decisiones):
  aprobación expresa del usuario, baseline de la suite completa re-ejecutado y entorno aislado creado.
* **Diferidas:** §14.2. Ninguna bloquea B5.2.
* **Abiertas sin bloqueo (a cerrar durante B5.2):** forma exacta del `TaskResult` serializado (se mide su tamaño
  real); valores de configuración por defecto de `ParallelConfig` (nunca en código); mecanismo exacto de comparación
  T1 por clase de carga (qué campos y qué tolerancia de las existentes aplica a cada uno; se documenta en el test).

---

## 14b. Texto original de las preguntas (v1, superado por §14)

| ID | Pregunta | Recomendación | Bloquea |
|---|---|---|---|
| **D-01** | ¿Qué incluye cada «optimización de cartera» en la operación masiva de 22.000? (solo W0; W1 completo; + escenarios B4; + estrategias; con o sin EXACT_MIP) y ¿qué proporción por clase? | Definir un *mix* de referencia por clase; sin él no hay dimensionamiento válido | B5.2 (y objetivos de B5.5) |
| **D-02** | La unidad de trabajo por cartera no existe: ¿se crea una función secuencial de referencia `run_portfolio` (en `engine.py` o `parallel/task.py`) en B5.2? | Sí, mínima, sin lógica matemática nueva (composición de motores existentes), como referencia de equivalencia | B5.2 |
| **D-03** | Escala oficial (1.200 × 20 × 700) vs petición (22.000 × 500): ¿se amplía GOV-012/BEN-007 y la Definition of Done del B5, o se mantiene lo oficial y 22.000 es un objetivo de capacidad medido (sin PASS/FAIL)? | Mantener 10/100/1.200 como DoD oficial y tratar 5.000/22.000 como **capacidad medida** hasta que usted modifique el plan | Cierre de B5 |
| **D-04** | Diario local de reanudación en B5.4 (frente a plan oficial: persistencia/error recovery en B6) | Aprobar un `parallel/journal.py` mínimo en B5.4 (sin DB); persistencia duradera sigue en B6 | B5.4 |
| **D-05** | Nuevos IDs de requisito para lo no cubierto (journal, reanudación, cancelación, timeouts, contrapresión, carriles, `Protocol`s): ¿se añaden a `TRACEABILITY.md` como `PAR-014…`? | Sí, previa aprobación; hoy están propuestos como «P-*» en el plan de implementación | B5.2 |
| **D-06** | Timeout duro y aislamiento de tarea venenosa: ¿`ProcessPoolExecutor` + supervisor, o procesos propios con colas? | Empezar con PPE + supervisor; pasar a procesos propios solo si las pruebas de fallos lo exigen | B5.4 |
| **D-07** | Tolerancias T1 (propuesta `1e-6` absoluto, igual a la regresión dorada) y exigencia T0 en la misma máquina | Aprobar tal cual o fijar otras | B5.2 |
| **D-08** | ¿Se autoriza fijar hilos de Clarabel/HiGHS (ajuste de backend, afecta a B4) si la medición muestra sobresuscripción? | Solo con evidencia y con regresión B4 completa | B5.2/B5.3 |
| **D-09** | Entorno de despliegue: intérprete ≥3.11 en Ubuntu 22.04, declarar `threadpoolctl`/`psutil` (¿y DuckDB?) como dependencias, lock de versiones | Aprobar | B5.2 |
| **D-10** | Alcance de las interfaces de integración (Windmill/HERMES/AAA-A): ¿solo `Protocol`s + CLI JSON? | Sí; nada de red en B5 | B5.4 |
| **D-11** | Número máximo de workers permitido en Arsys (reserva para SQL Server y otras apps) y límites de RAM | Fijar tras E2/E11/E12; mientras tanto ≤ núcleos físicos − reserva | B5.5 |
| **D-12** | ¿Se permite ejecutar los benchmarks de ≥1.000 carteras en el servidor Arsys (sin datos reales), y con qué ventana horaria? | Sí, en ventana acordada y con datos sintéticos | B5.5 |
| **D-13** | `engine.py`: el plan lo permite en B5 y `TRACEABILITY` lo asigna a B6 | Mantener `engine.py` fuera de B5; usar `parallel/task.py` para la referencia | B5.2 |

---

## 15. Criterios de aceptación del diseño (B5.1)

| Criterio | Estado |
|---|---|
| Verificación de repositorio y rama sin tocar `main` | Cumplido (§2) |
| Revisión documental B1–B4 y requisitos B5 | Cumplido (§5) con la limitación de que `MASTER_SPEC.md` se leyó en los apartados §56–62, §31 y anexos relevantes, no íntegro línea a línea |
| Diagnóstico con distinción hecho/hipótesis | Cumplido (§4) |
| Arquitectura, alternativas y riesgos | Cumplido (§6–13) |
| Divergencias oficiales documentadas, no resueltas unilateralmente | Cumplido (§3, §14) |
| Sin cambios de código, `MASTER_SPEC.md`, auditorías ni tolerancias | Cumplido |
