# IMPLEMENTATION PLAN

# Plan de implementación verificable — Motor de optimización cuantitativa de carteras

> **Fase actual:** PROMPT 0 completado y cerrado formalmente el 2026-09-23 (decisiones A-01 … A-37 aceptadas; solo documentación). **Siguiente fase autorizable:** BLOQUE 1, únicamente con instrucción explícita del usuario.
> **Documentos de referencia:** `MASTER_SPEC.md` (contrato), `ARCHITECTURE.md` (diseño, ambigüedades A-xx), `TRACEABILITY.md` (RequirementIDs y estados), `IMPLEMENTATION_PROMPTS.md` (bloques autorizados), `CLAUDE.md` (reglas).
> Este plan **no** autoriza a avanzar de bloque automáticamente.

---

## 1. Protocolo común a todos los bloques

### 1.1 Inicio de sesión de bloque (CLAUDE.md, "Control de alcance")

Antes de escribir código, cada sesión declara:
1. Bloque actual.
2. RequirementIDs afectados (lista de §3 de este plan, contrastada con `TRACEABILITY.md`).
3. Módulos permitidos.
4. Módulos fuera de alcance.
5. Decisiones A-xx y enmiendas del MASTER_SPEC (Anexo A) que afectan al bloque (todas aceptadas; ver §6).

Orden de lectura obligatorio: `MASTER_SPEC.md` → `ARCHITECTURE.md` → `TRACEABILITY.md` → `IMPLEMENTATION_PLAN.md` → `CHANGELOG.md` → bloque de `IMPLEMENTATION_PROMPTS.md`.

### 1.2 No regresión (MASTER_SPEC §80)

1. Ejecutar la suite completa existente (`pytest`) antes de tocar código.
2. Registrar el baseline (nº tests, pasados, fallidos, duración) en `CHANGELOG.md`.
3. Implementar.
4. Ejecutar la suite completa de nuevo.
5. Comparar; corregir cualquier regresión antes de continuar.
6. Si un bloque previo tiene tests fallando: **no continuar** (IMPLEMENTATION_PROMPTS, Bloques 2–6).

### 1.3 Gate de fin de bloque

1. Ejecutar tests aplicables (y la suite completa).
2. Ejecutar `mypy` y `ruff` sobre `portfolio_engine/` (GOV-003, GOV-009).
3. Resumir archivos modificados.
4. Resumir tests **realmente** ejecutados y resultados (salida real, no estimada).
5. Identificar incidencias y limitaciones.
6. Actualizar `TRACEABILITY.md` (estado por RequirementID + registro de cambios de estado con evidencia).
7. Actualizar `CHANGELOG.md`.
8. Emitir `BLOCK_N_STATUS = PASS | FAIL` y **detenerse**.

### 1.4 Reglas de estado

| Estado | Condición necesaria |
|---|---|
| `NOT_IMPLEMENTED` | No existe código funcional. |
| `PARTIAL` | Existe código funcional pero falta parte del requisito, integración o test, o se usa una aproximación (`PARTIAL_IMPLEMENTATION: <motivo>`). |
| `IMPLEMENTED` | Código funcional completo + integración + test de aceptación escrito. |
| `VALIDATED` | Lo anterior + test de aceptación **ejecutado y en verde** en el gate. |

Un requisito que abarca varios bloques (columna *Bloque* con varios valores) solo puede pasar a `VALIDATED` cuando se cumple su último tramo; en bloques intermedios queda `PARTIAL` con el motivo.

---

## 2. Pre-requisitos antes del Bloque 1

| # | Acción | Responsable | Obligatorio para B1 | Referencia |
|---|---|---|---|---|
| PR-1 | Decisiones A-01 … A-37 | Usuario | — | **Cerrado (2026-09-23):** todas aceptadas, con precisiones en A-01, A-02, A-03, A-06, A-07, A-24, A-25, A-26, A-27 (ARCHITECTURE §12; MASTER_SPEC Anexo A) |
| PR-2 | Inicializar Git en la raíz | Claude (autorizado) | — | **Cerrado:** `git init` ejecutado (rama `master`); baseline de PROMPT 0 registrado en el commit `e49c70e`. Los commits siguientes se harán al cierre de cada bloque validado |
| PR-3 | Dependencias de desarrollo `hypothesis`, `mypy`, `ruff` | Bloque 1 | Sí | **Sin instalación global.** El Bloque 1 las declara en `pyproject.toml` (grupo de desarrollo) y se instalan en un entorno virtual local del proyecto (`.venv`, excluido de Git) |
| PR-4 | Decidir tratamiento de la carpeta `1.-Version Anterior/` (se mantiene como referencia de solo lectura; no se importa) | Usuario | No | ARCHITECTURE §13 |

---

## 3. Plan por bloque

**Requisitos transversales (aplican en todos los bloques, se revisan en cada gate y se cierran en B6):** GOV-002 (prioridad de corrección matemática), GOV-003 (tipado), GOV-007 (inyección de dependencias / Protocol-ABC), GOV-009 (lint/complejidad), GOV-010 (sin stubs; `PARTIAL_IMPLEMENTATION` declarado), GOV-011 (no regresión), CFG-015 (sin literales de negocio), BEN-006 (sin benchmarks inventados).

**Requisitos diferidos condicionales (E-25):** NCV-003, NCV-004, NCV-005 — solo se implementarán si el usuario aporta un caso financiero no convexo validado.

**Requisitos opcionales fuera de bloque:** RET-004, RET-005, RET-006, RET-007 (métodos internos "futuros" de expected returns, §8). Solo se define la interfaz `ExpectedReturnProvider` (RET-001) que los admite; permanecen `NOT_IMPLEMENTED` documentados salvo instrucción expresa del usuario.

### BLOQUE 1 — Foundation: configuración, datos, retornos y riesgo

**Objetivo:** cimientos inmutables, validados y deterministas sobre los que se construirá la optimización.

**RequirementIDs (objetivo `VALIDATED` en este bloque salvo indicación):**
- Gobierno: GOV-001, GOV-004, GOV-005, GOV-006, GOV-008; GOV-003, GOV-009 (aplicados desde B1, validados en cada gate); GOV-010, GOV-011 (proceso).
- Configuración: CFG-001, CFG-002, CFG-003, CFG-004, CFG-005 (parte base → `PARTIAL` hasta B4), CFG-006, CFG-014, CFG-015 (test activo desde B1; `PARTIAL` hasta B6 por alcance transversal), CFG-016, CFG-017, CFG-018 (`OptimizationHorizonYears`, E-03), CON-021 (enum y configuración obligatoria de `RestrictedExistingPositionPolicy`, E-09; valor de ejemplo `HOLD_OR_REDUCE`).
- Datos: DAT-001, DAT-002, DAT-003, DAT-004, DAT-005, DAT-006, DAT-009, DAT-010, DAT-011, DAT-012, DAT-013 (nivel global → `PARTIAL` hasta B3), DAT-014, DAT-015 (solo ExternalAlpha → `PARTIAL` hasta B4), DAT-016 (`CurrentPortfolioStateHash`, E-06), DAT-020 … DAT-031.
- Retornos: RET-001, RET-002, RET-003, RET-008, RET-010, RET-011, RET-012.
- Riesgo: RSK-001, RSK-002, RSK-003, RSK-006, RSK-007, RSK-008, RSK-009, RSK-010, RSK-011, RSK-012, RSK-013.
- Costes: TC-005 (modelo de datos + validación de inputs).
- Tests: TST-001 (unit), TST-003 (property, infraestructura), TST-018 (tests obligatorios de B1).

**Módulos permitidos:** `pyproject.toml`, `config/default_engine.toml`, `portfolio_engine/__init__.py`, `portfolio_engine/exceptions.py`, `portfolio_engine/config/` (solo `engine_config`, `data_config`, `return_config`, `risk_config`, `constraint_config` base, `transaction_cost_config`, `loader`, `hashing`), `portfolio_engine/models/` (`enums`, `asset`, `universe_index`, `market_data`, `portfolio`, `risk_model`, `costs`), `portfolio_engine/data/sources/` (DataFrame, CSV, Parquet), `portfolio_engine/data/validation/`, `portfolio_engine/returns/`, `portfolio_engine/risk/` (solo EMPIRICAL y LEDOIT_WOLF; sin `oas.py`, `ewma.py`, E-07), `portfolio_engine/utils/`, `tests/unit/`, `tests/property/`, `tests/fixtures/`, `.gitignore`, `README.md`, `CHANGELOG.md`, `TRACEABILITY.md`.

**Fuera de alcance (no crear ni siquiera como stub):** CandidateEngine, fronteras, backends de solver, ScenarioEngine, multiprocessing, SQL Server, MIQP, NonConvex, Beam Search, OAS/EWMA (diferidos al Bloque 4, E-07; tampoco como valores de enum seleccionables), caché, outputs, persistencia, `FrontierConfig`/`SolverConfig`/`CandidateConfig`/`ScenarioConfig`/`ParallelConfig`/`PersistenceConfig`/`BenchmarkConfig` (se crean en su bloque; `EngineConfig` los tendrá como opcionales ausentes).

**Tests obligatorios (IMPLEMENTATION_PROMPTS, Bloque 1):**

| Test obligatorio | RequirementID | Fichero previsto |
|---|---|---|
| returns correctos | RET-010 | `tests/unit/returns/test_returns_engine.py` |
| annualization | RET-011 | `tests/unit/returns/test_annualization.py` |
| missing data | DAT-023, DAT-024 | `tests/unit/data/test_validation_missing.py` |
| duplicados | DAT-020 | `tests/unit/data/test_validation_duplicates.py` |
| PSD | RSK-008, RSK-009 | `tests/unit/risk/test_psd_diagnostics.py` |
| near singular matrix | RSK-008 | `tests/unit/risk/test_psd_diagnostics.py::test_near_singular` |
| singular matrix | RSK-008 | `tests/unit/risk/test_psd_diagnostics.py::test_singular` |
| PSD repair | RSK-010, RSK-011, RSK-012 | `tests/unit/risk/test_psd_repair.py` |
| config immutability | CFG-014 | `tests/unit/config/test_config_immutability.py` |
| transaction-cost input validation | TC-005 | `tests/unit/costs/test_transaction_cost_inputs.py` |

Tests adicionales del bloque: todos los listados en `TRACEABILITY.md` para los RequirementIDs anteriores (stale, outliers, metadatos, pesos, límites, correction log, Ledoit-Wolf vs referencia, hash de config, grafo de imports, literales de negocio, estado actual de cartera).

**Definition of Done:** todos los tests del bloque en verde; ningún test fallando; `TRACEABILITY.md` actualizado con `IMPLEMENTED`/`VALIDATED`/`PARTIAL` reales; `CHANGELOG.md` creado. Salida: `BLOCK_1_STATUS = PASS | FAIL`.

**Riesgos específicos:** ambigüedad de unidades de coste (A-04); criterios de outliers/stale deben ser configurables sin defaults ocultos; Ledoit-Wolf propio vs sklearn (se implementa la fórmula y se contrasta con sklearn solo en test).

---

### BLOQUE 2 — Optimizador continuo y frontera eficiente (composición fija)

**Precondición:** suite del Bloque 1 en verde. Horizonte resuelto (A-03/E-03): los costes se expresan como `TransactionCostOneOff / OptimizationHorizonYears`.

**RequirementIDs:**
- Config: CFG-007, CFG-008, CFG-012 (subset micro-benchmark → `PARTIAL` hasta B5), CFG-005 (extensión).
- Restricciones: CON-001, CON-002, CON-003, CON-005, CON-006, CON-007, CON-008, CON-009, CON-013 (composición fija; elegibilidad en B3), CON-014, CON-018, CON-020, CON-022 (semántica de la política en frontera continua → `PARTIAL` hasta B3).
- Factibilidad: FEA-001, FEA-003, FEA-004, FEA-007.
- Optimización: OPT-001 (familia FAST → `PARTIAL`), OPT-003, OPT-004, OPT-005, OPT-006, OPT-007, OPT-008, OPT-013 (clases QP → `PARTIAL`), OPT-014 (Current/MinVar/MaxRet → `PARTIAL`).
- Costes: TC-001, TC-002, TC-004, TC-006, TC-007, TC-008, TC-009, TC-010, TC-012; TC-003 (general; test de liquidación completo en B3).
- Fronteras: FRN-001, FRN-004, FRN-005, FRN-006, FRN-007, FRN-008, FRN-009, FRN-010, FRN-011, FRN-012, FRN-013, FRN-014, FRN-015, FRN-016, FRN-018, FRN-019, FRN-020, FRN-021, FRN-022, FRN-023.
- Validación: VAL-001, VAL-002, VAL-003 (métrica), VAL-004, VAL-005, VAL-007 (lineales), VAL-008, VAL-009.
- Solvers: SOL-001, SOL-002 (OSQP), SOL-003, SOL-004, SOL-005 (solo si se adopta A-32), SOL-008 (QP), SOL-009, SOL-010, SOL-012, SOL-013, SOL-014.
- Métricas: MET-001, MET-002, MET-003, MET-005, MET-006.
- Outputs: OUT-001 (campos disponibles en B2 → `PARTIAL`), OUT-002, OUT-003, OUT-005, OUT-006, OUT-007, OUT-008.
- Reproducibilidad/benchmark: REP-004, BEN-001 (subset), BEN-002 (subset), BEN-003.
- Tests: TST-002, TST-004, TST-006, TST-007, TST-008, TST-009, TST-010, TST-011, TST-013, TST-017 (QP→OSQP), TST-022 (consistencia de horizonte).
- VIS-001 (`PARTIAL`).

**Módulos permitidos:** `config/frontier_config.py`, `config/solver_config.py`, `config/benchmark_config.py`, `constraints/` (sin `conic.py`, sin `integer.py`), `costs/`, `optimizers/base.py`, `optimizers/problem.py`, `optimizers/status.py`, `optimizers/router.py`, `optimizers/formulations/qp_builder.py`, `optimizers/osqp_backend.py`, `optimizers/clarabel_backend.py` (solo si A-32), `validation/`, `metrics/` (sin `cvar_metric.py`), `frontiers/` (sin `global_frontier.py`), `outputs/`, `benchmark/timers.py`, `benchmark/stats.py`, `benchmark/suite.py`, `benchmarks/scripts/solver_reuse.py`, tests.

**Fuera de alcance:** CandidateEngine, Global Candidate Frontier, Beam Search, paralelización, MIQP, SQL Server, Max Sharpe y Volatility Control (solo "arquitectura preparada": `ProblemClass.SOCP` y el router conocen la clase, sin formulación), escenarios, caché.

**Tests contractuales (IMPLEMENTATION_PROMPTS, Bloque 2):**

| Test contractual | RequirementID |
|---|---|
| Minimum Variance | OPT-006 |
| Maximum Return | OPT-007 |
| Risk Aversion | FRN-005, OPT-004 |
| Target Return | OPT-008, FRN-008 |
| Gross Frontier | FRN-013 |
| Net Frontier | FRN-010, FRN-011 |
| Transaction-cost scaling | TST-013 |
| Consistencia de horizonte (E-03) | TST-022 |
| CurrentWeight = OptimizedWeight ⇒ Turnover = 0, TC = 0 | TST-010 |
| ExpectedReturnNet ≤ ExpectedReturnGross con costes positivos | TST-009 |
| Composición fija `set(CurrentAssets) == set(FrontierAssets)` | TST-011 |
| Solver statuses | SOL-002 |
| Infeasible problem | SOL-013, FEA-007 |

**Benchmark (real, registrado):** setup, update, solve, frontier total; cold setup vs workspace reuse vs warm start (BEN-003).

**Definition of Done:** dataset (Volatility, ExpectedReturnGross, ExpectedReturnNet) graficable para una cartera (FRN-022). Salida: `BLOCK_2_STATUS = PASS | FAIL`.

**Riesgos:** precisión de OSQP en LP (Max Return) y en detección de inviabilidad (A-33) → verificación cruzada y tests con solución cerrada; calibración de θ (A-16); corrección de `K_E` cuando no hay activos que salen (en B2 siempre `E = ∅` en la frontera continua salvo política A-09).

---

### BLOQUE 3 — Candidate Engine, sustituciones y Global Frontier

**Precondición:** suites B1–B2 en verde. Decisiones A-09, A-11, A-18, A-19 aceptadas (ver ARCHITECTURE §12).

**RequirementIDs:**
- Config: CFG-009.
- Restricciones/factibilidad: CON-010 (heurístico → `PARTIAL` hasta B4), CON-011 (idem), CON-012, CON-013 (elegibilidad), CON-019 (heurístico → `PARTIAL` hasta B4), CON-022 (traducción de la política en `EligibilityFilter` para composiciones candidatas), FEA-002, FEA-006.
- Optimización: OPT-002.
- Costes: TC-003, TC-011.
- Candidatos: CAN-001 … CAN-022.
- Fronteras: FRN-002, FRN-003, FRN-017.
- Validación: VAL-010.
- Datos/índices: DAT-013 (tres niveles).
- Rendimiento/determinismo: PAR-006, PAR-009, PAR-010 (tie-break → `PARTIAL` hasta B5), REP-003.
- Outputs: OUT-004, OUT-009.
- Tests: TST-012, TST-014, TST-015, TST-016.
- VIS-002.

**Módulos permitidos:** `config/candidate_config.py`, `candidates/`, `frontiers/global_frontier.py`, `constraints/integer.py` (solo representación y comprobación para la heurística; sin formulación MIP), `constraints/feasibility.py` (reglas de cardinalidad/liquidez), `optimizers/formulations/qp_builder.py` (offset `K_E`), `models/composition.py`, `models/universe_index.py`, `parallel/determinism.py` (solo semillas y tie-break), `engine.py` (pipeline FAST_PRODUCTION secuencial), `outputs/`, tests.

**Fuera de alcance:** caché (Bloque 5), multiprocessing, escenarios, MIQP, SOCP, SQL Server.

**Tests contractuales:** `len(candidate_compositions) > 1`; `len(unique(global_points.CompositionID)) > 1` (TST-012); liquidación A/B→C/B (TST-014); mapeo de índices global/eligible/local (TST-015); ausencia de copia `Σ` 700×700 por cartera (PAR-006); beam search mantiene B composiciones distintas y no degenera en greedy (CAN-007).

**Definition of Done:** graficar simultáneamente Current Portfolio, Continuous Frontier y Global Candidate Frontier (VIS-002). Salida: `BLOCK_3_STATUS = PASS | FAIL`.

**Riesgos:** explosión combinatoria de 2/3-swap (A-18); calidad del screening sin referencia exacta hasta B4 (MIP-003); coste de evaluar composiciones por QP (mitigado con aproximaciones configurables).

---

### BLOQUE 4 — Escenarios, SOCP, robustez y optimización avanzada

**Precondición:** suites B1–B3 en verde. Decisiones A-07, A-10, A-13, A-22, A-23, A-24, A-25, A-35 aceptadas. Instalación de `pyscipopt` en el entorno del proyecto como dependencia opcional del grupo `exact-mip` (E-24); ningún solver comercial obligatorio.

**RequirementIDs:**
- Config: CFG-010, CFG-005 (completa).
- Riesgo: RSK-004, RSK-005 (según A-07).
- Datos: DAT-015 (completa).
- Restricciones/factibilidad: CON-004, CON-010, CON-011, CON-015, CON-016, CON-017, CON-019 (MIP), FEA-005, FEA-008.
- Optimización: OPT-001 (completa), OPT-009, OPT-010, OPT-011, OPT-012, OPT-013 (completa), OPT-014 (completa).
- Costes: TC-013.
- Solvers: SOL-002 (Clarabel), SOL-005, SOL-006, SOL-007 (arquitectura, `PARTIAL`), SOL-008 (completo), SOL-011.
- MIP: MIP-001 … MIP-007 (SCIP/PySCIPOpt como referencia; comerciales opcionales, E-24).
- No convexo (E-25): NCV-001 (solo arquitectura → máximo `PARTIAL`) y NCV-002 (guarda de convexidad, validable). NCV-003, NCV-004 y NCV-005 **diferidos** (`NOT_IMPLEMENTED`) hasta que exista un caso financiero validado; no se implementa ningún algoritmo no convexo ni multi-start. SOL-007 (`NonConvexBackend`) queda en `PARTIAL`.
- Robustez: ROB-001 … ROB-006.
- Escenarios: SCN-001 … SCN-010.
- Métricas/validación/outputs: MET-004, VAL-003 (límite), VAL-006, VAL-007 (completa), OUT-001 (completo).
- Tests: TST-017 (completo), TST-019.
- VIS-003.

**Módulos permitidos:** `config/scenario_config.py`, `risk/covariance/oas.py`, `risk/covariance/ewma.py`, `scenarios/`, `constraints/conic.py`, `constraints/integer.py` (formulación MIP), `optimizers/formulations/` (sharpe, volatility, cvar, robust, multi_scenario, miqp), `optimizers/clarabel_backend.py`, `optimizers/mixed_integer_backend.py`, `optimizers/nonconvex_backend.py`, `optimizers/router.py`, `returns/expected/` (shrinkage), `metrics/cvar_metric.py`, `frontiers/explicit_portfolios.py`, `engine.py`, `outputs/`, tests.

**Fuera de alcance:** multiprocessing, memoria compartida, caché, SQL Server, staging.

**Tests:** Routing QP→OSQP; SOCP→Clarabel; MIQP no enviado a OSQP; outputs por escenario; Max Sharpe sanity (vs bisección); restricciones de volatilidad; restricciones CVaR; tests de optimización robusta; EXACT_MIP vs enumeración en universo pequeño y gap frente a la heurística.

**Definition of Done:** una misma cartera produce fronteras y soluciones distintas por ScenarioID (SCN-008). Salida: `BLOCK_4_STATUS = PASS | FAIL`.

**Riesgos:** disponibilidad/licencia del solver MIQP (A-24); tiempo de EXACT_MIP con ~700 binarios (solo modo validación, time limit, gap reportado); precisión de Max Sharpe con κ pequeño (A-13); capacidades reales de Clarabel 0.11.1 (A-37).

---

### BLOQUE 5 — HPC, paralelización y performance

**Precondición:** suites B1–B4 en verde. No se optimiza código matemáticamente incorrecto.

**RequirementIDs:** CFG-011, CFG-012 (completa), PAR-001, PAR-002, PAR-003, PAR-004, PAR-005, PAR-007, PAR-008, PAR-010 (completa), PAR-011, PAR-012, PAR-013, CCH-001, CCH-002 (incluye siempre `CurrentPortfolioStateHash`, E-06), CCH-003, CCH-004, CCH-005, BEN-001, BEN-002 (completos), BEN-004, BEN-005, BEN-006, BEN-007, TST-005, GOV-012.

**Módulos permitidos:** `config/parallel_config.py`, `config/benchmark_config.py`, `parallel/`, `cache/`, `benchmark/`, `benchmarks/`, `engine.py` (integración de ejecución paralela y caché), `tests/performance/`, `tests/integration/`.

**Fuera de alcance:** SQL Server, staging, coordinador de persistencia (B6); cambios en formulaciones matemáticas (si se detecta un error, se detiene y se reporta).

**Tests/benchmarks:** determinismo 1 vs N workers y distintos batch sizes (PAR-008); cache hit elimina solver calls (CCH-003); benchmarks BatchSize {1, 5, 10, 20, AUTO}, workers {1, 2, 4, 8, …} sin asumir CPU_COUNT; p50/p95/p99, portfolios/s, solver calls/s; baseline de rendimiento.

**Definition of Done:** validación real con 10, 100 y 1.200 carteras si los recursos lo permiten (si no, se documenta el máximo ejecutado y el requisito queda `PARTIAL`). Salida: `BLOCK_5_STATUS = PASS | FAIL`.

**Riesgos:** semántica `spawn` en Windows (coste de arranque de workers, re-importación); ciclo de vida de `SharedMemory` ante excepciones; variabilidad de tiempos en máquina local (benchmarks con repeticiones y metadatos).

---

### BLOQUE 6 — Persistencia, auditoría e integración de producción

**Precondición:** suites B1–B5 en verde. Instancia SQL Server disponible para validar (A-28); si no, los requisitos PER dependientes quedan `PARTIAL`.

**RequirementIDs:** CFG-013, DAT-007, DAT-008 (opcional), PER-001 … PER-010, REP-001, REP-002, OUT-007 (persistencia), BEN-008, TST-020, TST-021; cierre de CFG-015, GOV-005 en producción.

**Módulos permitidos:** `config/persistence_config.py`, `staging/`, `persistence/`, `data/sources/sqlserver_source.py`, `models/run_metadata.py`, `engine.py`, `utils/logging.py`, `tests/integration/`, `tests/e2e/`, `README.md`, `ARCHITECTURE.md`, `TRACEABILITY.md`, `CHANGELOG.md`, `PRODUCTION_READINESS_REPORT.md`.

**Tests:** end-to-end completo; idempotencia/reintento; inyección de fallos (DB no disponible, escritura parcial, caída de worker, fallo de solver, cartera inválida) sin pérdida del batch; benchmark fast_executemany vs BCP si ambos disponibles.

**Auditoría final:** cada RequirementID revisado; ningún `IMPLEMENTED` sin test; requisitos de producción en `VALIDATED`; opcionales `NOT_IMPLEMENTED` documentados.

**Salida:** `PRODUCTION_READINESS_REPORT.md` y uno de `PRODUCTION_READY` / `PRODUCTION_READY_WITH_LIMITATIONS` / `NOT_PRODUCTION_READY`.

---

## 4. Distribución de requisitos por bloque

Recuento calculado por script a partir de la columna *Bloque* de `TRACEABILITY.md` (inicio = primer bloque indicado; cierre = último bloque indicado, en el que el requisito puede alcanzar `VALIDATED`). Los requisitos de proceso transversal (p. ej. GOV-003, GOV-009, GOV-010, GOV-011, BEN-006, TST-001) se aplican en cada gate y cuentan como cierre en su último bloque.

| Bloque | Requisitos que se inician | Requisitos que se cierran |
|---|---|---|
| B1 | 70 | 59 |
| B2 | 107 | 87 |
| B3 | 47 | 46 |
| B4 | 46 | 62 |
| B5 | 21 | 25 |
| B6 | 18 | 30 |
| Diferidos condicionales (NCV-003 … NCV-005, E-25) | 3 | 3 |
| Futuro (opcionales RET-004 … RET-007) | 4 | 4 |
| **Total** | **316** | **316** |

La fuente de verdad es la columna *Bloque* de `TRACEABILITY.md`; este recuento debe recalcularse si cambia.

---

## 5. Estrategia de pruebas

| Tipo | Ubicación | Herramienta | Contenido |
|---|---|---|---|
| Unit | `tests/unit/` | pytest | Cada función/clase con casos manuales de valor exacto. |
| Integration | `tests/integration/` | pytest | Pipelines (frontera continua, global, escenarios, persistencia). |
| Property | `tests/property/` | hypothesis | Invariantes §73 sobre carteras/costes/pesos generados. |
| Numerical regression | `tests/numerical_regression/` | pytest + golden files | Fronteras de referencia con tolerancias de config; cambios de golden solo con justificación en CHANGELOG. |
| Performance regression | `tests/performance/` | pytest (marcador `performance`) | Comparación contra baseline (B5). |
| End-to-end | `tests/e2e/` | pytest | Flujo completo (B6). |

Principios:
- **Fixtures sintéticas deterministas** (`tests/fixtures/`) con semilla explícita; universos pequeños para soluciones exactas por enumeración (validación de heurísticas y MIP) y universos de escala para rendimiento.
- **Soluciones de referencia independientes**: fórmulas cerradas (min-var sin restricciones activas, max-return de caja), enumeración exhaustiva, bisección cuasiconvexa (Sharpe), y un segundo solver como verificación cruzada — nunca el mismo código que se prueba.
- **Tolerancias** siempre desde configuración de tests (no literales dispersos).
- **Marcadores pytest**: `unit`, `integration`, `property`, `numerical`, `performance`, `sqlserver` (se omite con motivo explícito si no hay instancia; un test omitido nunca cuenta como validación).

---

## 6. Decisiones (cerradas en el cierre de PROMPT 0, 2026-09-23)

Todas las decisiones A-01 … A-37 de `ARCHITECTURE.md` §12 están **aceptadas por el usuario**; A-09 cerrada formalmente con `RestrictedExistingPositionPolicy` (E-09). Las que afectan al contrato están incorporadas al `MASTER_SPEC.md` (Anexo A).

| ID | Tema | Decisión final | Bloque |
|---|---|---|---|
| A-01 | `*` → `+` en la fórmula de costes | Corregido en MASTER_SPEC §23 (F-01) | B2 |
| A-02 | Signos corruptos por Markdown | Corregido en MASTER_SPEC §14, §16, §25, §35, §37, §38 (F-02, F-03); revisión global realizada | B2 |
| A-03 | Horizonte de costes | `OptimizationHorizonYears` centralizado en `EngineConfig`, defecto 1.0 en config; `TC = TC_one_off / H`; sin horizonte literal en fórmulas (E-03) | B1 (parámetro), B2 (uso) |
| A-04 | Precedencia y unidades de costes | Buy/Sell → Estimated → spread/2 + comisión; unidad declarada | B1 |
| A-06 | Clave de caché | Unión de claves + `CurrentPortfolioStateHash` (AssetID + CurrentWeight) siempre; invalidación ante cambio de pesos (E-06) | B1 (hash), B5 (caché) |
| A-07 | OAS / EWMA | Diferidos al Bloque 4; B1 solo EMPIRICAL y LEDOIT_WOLF (E-07) | B4 |
| A-08 | Pesos cero en frontera continua | Pertenencia = variables; `min_holding_weight` opcional | B2 |
| A-09 | Activos restringidos ya en cartera | `RestrictedExistingPositionPolicy` ∈ {HOLD_OR_REDUCE, FREEZE_WEIGHT, FORCE_LIQUIDATE}; selección explícita obligatoria en producción; `HOLD_OR_REDUCE` en ejemplos/tests; no hardcodeada en CandidateEngine ni optimizador (E-09) | B1 (config), B2–B3 (semántica) |
| A-10 | Entradas TE/beta/factores | Entradas opcionales; `ReferenceBenchmarkConfig` separado de `BenchmarkConfig` | B4 |
| A-11 | LiquidityConstraint y NAV | Fórmula ADV/NAV con parámetros de config | B3 |
| A-12 | Caja | Activo sintético CASH | B2 |
| A-13 | Max Sharpe | Charnes–Cooper en Clarabel; NOT_APPLICABLE sin exceso positivo | B4 |
| A-18 | Vecindario 2/3-swap | Shortlists de config; exhaustivo bajo umbral | B3 |
| A-19 | ADD/DROP y COLD_START | Incluidos | B3 |
| A-22 | Escenarios | Transformaciones declarativas en config | B4 |
| A-24 | Solver MIQP | SCIP / PySCIPOpt de referencia; Gurobi/CPLEX/MOSEK opcionales; ningún comercial obligatorio (E-24) | B4 |
| A-25 | No convexo | Solo arquitectura; algoritmos concretos y multi-start `NOT_IMPLEMENTED` hasta caso validado; preferir reformulación convexa (E-25) | B4 |
| A-26 | Git | `git init` ejecutado | — |
| A-27 | hypothesis | Dependencia de desarrollo del proyecto (B1), sin instalación global | B1 |
| A-28 | SQL Server | Requerido para `VALIDATED` en PER | B6 |
| A-32 | Clarabel en Bloque 2 | Solo como verificador de estados | B2 |
| A-35 | CVaR | `CVaRConfig` explícita | B4 |

Resto de A-xx (A-05, A-14 … A-17, A-20, A-21, A-23, A-29 … A-31, A-33, A-34, A-36, A-37): aceptadas según la propuesta de ARCHITECTURE §12.

`IMPLEMENTATION_PROMPTS.md` (Bloque 2) corregido tipográficamente (F-04), coherente con MASTER_SPEC §35 y §37; en cualquier conflicto prevalece MASTER_SPEC.

---

## 7. Riesgos técnicos globales

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Fórmulas tipográficamente corruptas (A-01, A-02) | Implementación de un signo erróneo | Corregidas en MASTER_SPEC (F-01 … F-03) e IMPLEMENTATION_PROMPTS (F-04); tests algebraicos TST-013 y TST-022. |
| Precisión de ADMM (OSQP) en LP e inviabilidad | Estados o endpoints incorrectos | Mapeo estricto de estados, validación independiente, verificación cruzada configurable. |
| Complejidad combinatoria del CandidateEngine | Tiempo por cartera | Screening vectorizado, shortlists configurables, beam acotado, benchmarks reales. |
| Windows `spawn` y memoria compartida | Rendimiento y fugas de segmentos | `SharedMemory` gestionada por el coordinador, benchmark shared_memory vs memmap. |
| Instalación de SCIP/PySCIPOpt en Windows | EXACT_MIP no validable | Instalar en el entorno del proyecto en B4 (grupo `exact-mip`); si falla, MIP-* queda `NOT_IMPLEMENTED`/`PARTIAL` documentado. |
| SQL Server no disponible | Persistencia no validable | PER-* `PARTIAL` con motivo; staging Parquet validado igualmente. |
| Commits de bloque omitidos | Pérdida de trazabilidad de versiones (`GitCommit`) | Baseline `e49c70e` registrado; commit por bloque validado (README_USO). |
| Deriva de alcance entre bloques | Violación de CLAUDE.md | Declaración de alcance al inicio de cada sesión; módulos permitidos/fuera de alcance de §3. |

---

## 8. Estado de la fase PROMPT 0

| Entregable | Estado |
|---|---|
| `ARCHITECTURE.md` | Creado |
| `TRACEABILITY.md` | Creado y actualizado en el cierre — 316 RequirementIDs, todos `NOT_IMPLEMENTED`; cobertura de §0–§82 verificada por script |
| `IMPLEMENTATION_PLAN.md` | Creado y actualizado en el cierre |
| `MASTER_SPEC.md` | Fórmulas corregidas (F-01 … F-03) y enmiendas E-03, E-06, E-07, E-09, E-24, E-25 (Anexo A) |
| `IMPLEMENTATION_PROMPTS.md` | Bloque 2 corregido tipográficamente (F-04) |
| Repositorio Git | Inicializado (`git init`); baseline de PROMPT 0 en el commit `e49c70e` |
| Código productivo | Ninguno (conforme a PROMPT 0) |
| Stubs / placeholders | Ninguno |
| Tests | Ninguno (no aplica en PROMPT 0) |
| `CHANGELOG.md` | No creado en PROMPT 0 (el prompt pide exactamente tres documentos); se crea en el Bloque 1 |
