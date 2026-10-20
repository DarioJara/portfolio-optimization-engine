# BLOCK_5_IMPLEMENTATION_PLAN — Plan de implementación incremental del Bloque 5

Fecha: 2026-10-19. Rama: `block5-hpc-architecture`. Documento de **diseño**: no autoriza ninguna implementación.
Complementa `BLOCK_5_HPC_ARCHITECTURE.md` (decisiones D-xx, riesgos R-xx, divergencias X-x) y
`BLOCK_5_BENCHMARK_PLAN.md` (experimentos E-x, clases W0–W5, pruebas de equivalencia).

Regla de proceso (`CLAUDE.md`): cada entrega empieza declarando bloque, `RequirementID`, módulos permitidos y
fuera de alcance; ejecuta la suite previa antes de tocar nada validado; termina con `TRACEABILITY.md` y
`CHANGELOG.md` actualizados y **se detiene** esperando instrucción expresa.

---

## 1. Comparación con la planificación oficial

| Aspecto | Planificación oficial (`IMPLEMENTATION_PLAN.md` / `IMPLEMENTATION_PROMPTS.md`) | Estructura propuesta (petición) | Diferencia / tratamiento |
|---|---|---|---|
| Granularidad | Un Bloque 5 (salida `BLOCK_5_STATUS = PASS | FAIL`) | B5.1 … B5.5 | Subdivisión compatible. `BLOCK_5_STATUS` se emite al cerrar B5.5; cada subfase emite su propio informe de fase |
| Escala de validación | 10, 100, 1.200 carteras «si los recursos lo permiten»; ~20 activos, ~700 universo | 1, 100, 1.000, 5.000, 22.000; universo hasta 500 | La Definition of Done oficial sigue siendo 10/100/1.200. Escalas mayores se tratan como **capacidad medida** hasta que usted enmiende el plan (D-03) |
| Alcance de recuperación | `staging`, persistencia, «Error Recovery» y su inyección de fallos pertenecen al B6 | B5.4 «lotes, fallos y recuperación» (checkpoints/reanudación) | B5.4 se limita a **recuperación de ejecución en disco local** (diario). La persistencia duradera/SQL queda en B6 (D-04) |
| Memoria compartida y caché | B5, un solo bloque | B5.3 | Igual |
| Orquestador `engine.py` | Plan: `engine.py` permitido en B5 («integración de ejecución paralela y caché»); trazabilidad: orquestador en B6 | — | No se crea `engine.py` en B5; la referencia secuencial vive en `parallel/task.py` (D-13) |
| Benchmarks/auditoría | BEN-004/005/006/007, TST-005 dentro del B5 | B5.5 | Igual; auditoría independiente tras B5.5 |
| Plataforma | Windows (`spawn`) | Linux (Ubuntu 22.04) en producción | El código debe funcionar en ambas; la matriz de pruebas incluye `spawn` y `forkserver` |

No se reemplaza la planificación oficial. Las diferencias se proponen para aprobación y, si se aprueban, se
reflejarán en `IMPLEMENTATION_PLAN.md`/`TRACEABILITY.md` por instrucción expresa (no en esta fase).

---

## 2. Requisitos: oficiales y propuestos

### 2.1 Oficiales (de `IMPLEMENTATION_PLAN.md` Bloque 5)

CFG-011, CFG-012 (completa), PAR-001, PAR-002, PAR-003, PAR-004, PAR-005, PAR-007, PAR-008, PAR-010 (completa),
PAR-011, PAR-012, PAR-013, CCH-001, CCH-002, CCH-003, CCH-004, CCH-005, BEN-001, BEN-002 (completos), BEN-004,
BEN-005, BEN-006, BEN-007, TST-005, GOV-012. (PAR-006 y PAR-009 ya `VALIDATED` en B3 y deben preservarse.)

### 2.2 Requisitos propuestos P-01…P-08 (D-05: aprobado condicionalmente)

Estado de todos: **`PROPOSED`** (no son `RequirementID` oficiales, no figuran en `TRACEABILITY.md`, no se
modifica `MASTER_SPEC.md`). Solo podrán registrarse y, tras pruebas aprobadas, pasar a `VALIDATED` por
instrucción expresa. «Fuente» indica de dónde se derivan; ninguna es un requisito nuevo del usuario salvo lo
indicado.

| ID | Contenido | Fuente | Criterio de aceptación (prueba) | Entrega |
|---|---|---|---|---|
| P-01 | `ExecutionStatus` (`COMPLETED`, `FAILED_INPUT_VALIDATION`, `FAILED_EXCEPTION`, `TIMED_OUT`, `WORKER_CRASHED`, `CANCELLED`, `SKIPPED_BY_RESUME`) separado de `SolverStatus`; el executor nunca reetiqueta estados de solver | `CLAUDE.md` («diferenciar OPTIMAL, OPTIMAL_INACCURATE, INFEASIBLE, errores numéricos y límites»); MASTER_SPEC §45; deuda F-03b | Histograma de `SolverStatus` y `outcome` idéntico secuencial↔paralelo (C-08); ningún estado no óptimo aparece como `OPTIMAL` | B5.2 |
| P-02 | Contrapresión: cola acotada de lotes en vuelo; memoria del coordinador acotada | `ARCHITECTURE.md` §10.6/§11; PAR-011; petición B5.1 (E.6) | Con 5.000 tareas sintéticas el nº de lotes en vuelo nunca supera el límite configurado y el RSS del coordinador no crece con el total de tareas (medido) | B5.2 |
| P-03 | Contabilidad de integridad: cada `TaskID` aparece exactamente una vez; enviadas = Σ estados finales | Petición B5.1 (G: pérdida/duplicación); `CLAUDE.md` (integridad) | C-10, C-11 | B5.4 |
| P-04 | Timeouts por capas (solver, tarea, lote) y cancelación que conserva lo completado | Petición B5.1 (D); límites de tiempo ya existentes en los backends | C-15; mapeo de `TIME_LIMIT` con test (cierra F-04 en lo que afecte) | B5.4 |
| P-05 | Diario local append-only (formato no ejecutable) y reanudación con verificación del manifiesto — **contrato exacto diferido (D-04)** | Petición B5.1 (D, E.8–9); B6 («Error Recovery», idempotencia) | C-12, C-13; la reanudación con config/snapshot/código distintos se rechaza | B5.4 |
| P-06 | Reintentos con cuarentena de tareas venenosas — **supeditado a D-06** | Petición B5.1 (D, E.7) | C-14 | B5.4 |
| P-07 | Interfaces abstractas (`MarketDataProvider`, `PortfolioRequestSource`, `ResultSink`, `RunControl`, `ProgressReporter`) y CLI JSON, sin conexiones externas (D-10) | Petición B5.1 (H); `CLAUDE.md` (no acoplar a DB/agente) | C-25 (test de arquitectura: sin imports de DB/HTTP); CLI estable | B5.4 |
| P-08 | `RunManifest` y trazabilidad por tarea (commit/*dirty*, hashes de config y snapshot, versiones, hilos, host, `TaskID`, `SequenceID`) | BEN-006; petición B5.1 (D, E.10); `RunMetadata` formal es de B6 | Manifiesto completo y estable; reproducible a partir de él | B5.2/B5.4 |
| P-09 | `WorkloadSpec` configurable por cartera y catálogo cerrado de operaciones, con validación de dependencias previa al despacho | **D-01 (decisión del usuario, 2026-10-19)**; GOV-012 | Combinaciones válidas se ejecutan; inválidas ⇒ `FAILED_INPUT_VALIDATION` sin despachar; cada operación del catálogo equivale al motor original (T1) | B5.2 |

---

### 2.3 Decisiones del usuario incorporadas (2026-10-19)

Resumen; el registro completo está en `BLOCK_5_HPC_ARCHITECTURE.md` §14.

* **Aprobadas:** D-01 (workload configurable → P-09), D-02, D-13 (`parallel/task.py`; `engine.py` para B6),
  D-07 con ajustes (criterio T1 con tolerancias existentes; T0 solo diagnóstico; diferencias de estado se
  investigan), D-09 (entorno aislado Python ≥ 3.11, lock reproducible), D-05 condicional (P-xx = `PROPOSED`).
* **Diferidas:** D-03 (se mantiene 10/100/1.200; 5.000/22.000 = capacidad adicional), D-04 (diario mínimo, contrato
  por definir), D-06, D-08, D-10, D-11, D-12 (**sin benchmarks masivos en Arsys sin aprobación específica antes de
  cualquier carga ≥ 1.000 carteras**).
* Consecuencia para los criterios de B5.2: donde este plan decía «T0», rige **T1** (equivalencia dentro de las
  tolerancias existentes, estados idénticos salvo investigación documentada); T0 se reporta como diagnóstico.

## 3. Entregas

Convención de módulos (todos dentro de los «módulos permitidos» oficiales: `config/parallel_config.py`,
`config/benchmark_config.py`, `parallel/`, `cache/`, `benchmark/`, `benchmarks/`, `tests/performance/`,
`tests/integration/`; se añaden `tests/unit/parallel/` y `tests/unit/cache/` siguiendo el patrón del repositorio).
**Fuera de alcance en todas:** SQL Server, staging, coordinador de persistencia (B6); formulaciones matemáticas;
`MASTER_SPEC.md`; módulos de B1–B4 salvo error demostrado, que se reporta y detiene el trabajo.

### B5.1 — Auditoría y diseño HPC (esta entrega)

| Campo | Contenido |
|---|---|
| Alcance | Los tres documentos de diseño. Sin código |
| Módulos | Ninguno de producción |
| Dependencias | B1–B4 integrados en `origin/main` (`271eaeb`) |
| Riesgos | Decisiones tomadas con mediciones de otra máquina (R-09, R-13) |
| Pruebas | N/A (no se ejecutaron suites; solo mediciones exploratorias de lectura) |
| Aceptación | Estado `NEEDS_DECISIONS` hasta resolver D-01…D-13 relevantes; revisión por el usuario |
| Rollback | Eliminar los tres `.md` de la rama (`git rm`); no hay cambios que revertir en código |

### B5.2 — Ejecución paralela

| Campo | Contenido |
|---|---|
| Objetivo | Ejecutar lotes de carteras en un pool de procesos con resultados equivalentes al secuencial |
| RequirementID | CFG-011 (workers, batch size/AUTO, modo de datos, hilos), PAR-001, PAR-002, PAR-003, PAR-007, PAR-008, PAR-010 (orden por `SequenceID`), PAR-011, PAR-012, PAR-013, BEN-001/002 (timers por tarea, IPC); P-01, P-02, P-08 |
| Pasos | 0) Re-ejecutar la suite completa y registrar baseline (pytest, mypy `--strict`, ruff); crear el entorno aislado Python ≥ 3.11 (D-09, sin tocar el Python del sistema), justificar `threadpoolctl`/`psutil` en `pyproject.toml` y regenerar `requirements-lock.txt`. 1) **Perfilar** una cartera (`cProfile`) para fijar el reparto real del tiempo (confirma/refuta §4.4 del documento de arquitectura). 2) `config/parallel_config.py` (sin defaults de negocio en código; valores en `config/default_engine.toml`; `workers` explícito, error si falta). 3) `parallel/task.py`: `PortfolioRequest`, `TaskResult`, `run_portfolio` secuencial de referencia (composición de motores existentes). 4) `parallel/batching.py` (`PortfolioBatch`, `SequenceID`, `resolve_batch_size`, ordenación LPT). 5) `parallel/threading_control.py` (`threadpoolctl` + variables de entorno antes de importar numpy). 6) `parallel/worker.py` (`WorkerInitializer`, `WorkerContext`: datos de mercado pasados por el initializer; estado por tarea fresco). 7) `parallel/executor.py` (`BatchExecutor`: `ProcessPoolExecutor`, `forkserver`/`spawn`, contrapresión, planificación dinámica, orden canónico). 8) Equivalencia secuencial↔paralelo (T0) y permutación |
| Módulos afectados | **Nuevos:** `config/parallel_config.py`, `parallel/{task,batching,threading_control,worker,executor}.py`, `config/default_engine.toml` (nueva sección `[parallel]`), tests. **Tocados:** `config/engine_config.py` (campo opcional `parallel`), `parallel/__init__.py`, `pyproject.toml`/`requirements-lock.txt` (`threadpoolctl`, `psutil` declarados) |
| Dependencias | B1–B4 en verde; decisiones D-01, D-02, D-07, D-09, D-13 |
| Riesgos | R-02, R-03, R-08, R-09, R-11, R-12, R-16 |
| Pruebas | Unitarias: batching (AUTO, límites), hilos (`threadpool_info` ⇒ 1 en cada worker; nº de hilos del SO), config (sin `cpu_count` implícito; valor ausente ⇒ error), orden por `SequenceID`, `ExecutionStatus`. Integración: 1 vs N workers y varios batch sizes ⇒ T0 (misma máquina, sin límites de pared); permutación de envío y de composición de lotes; tamaño de payload por tarea acotado (PAR-005); `spawn` y `forkserver`. Regresión: suite completa sin cambios (1.482 + nuevas) |
| Criterios de aceptación | (i) Todas las pruebas de equivalencia pasan bajo **T1** (tolerancias existentes; D-07); la igualdad bit a bit se reporta como diagnóstico, no se exige; (ii) estados de solver idénticos en todas las carteras de prueba (cualquier diferencia se investiga y documenta, no se acepta automáticamente); (iii) sin cambios en módulos B1–B4; (iv) `mypy --strict`, `ruff check`, `ruff format --check` limpios; (v) PAR-001/002/003/007/008/010/011/012/013 ⇒ `VALIDATED` solo si tienen test de aceptación pasado |
| Rollback | `parallel.enabled=false` (por defecto) ⇒ ruta secuencial intacta; `git revert` del conjunto de commits de B5.2; ningún módulo previo modificado salvo el campo opcional `EngineConfig.parallel` y el TOML |

### B5.3 — Memoria compartida y caché

| Campo | Contenido |
|---|---|
| Objetivo | Elegir con datos el mecanismo de datos compartidos y entregar una caché de resultados correcta |
| RequirementID | PAR-004, PAR-005, CCH-001, CCH-002, CCH-003, CCH-004, CCH-005, BEN-004 (parte memoria compartida), CFG-011 (modo de memoria) |
| Pasos | 1) `parallel/shared_data.py`: `MarketSnapshot` inmutable direccionado por hash; backends: pickle-initializer (A), ficheros `np.load` (B), memmap (C), `SharedMemory` (D) tras una interfaz común, con ciclo de vida garantizado. 2) Benchmark E4 para elegir modo por defecto. 3) `cache/keys.py` (`CacheKey` con los 10 componentes, `CurrentPortfolioStateHash` siempre). 4) `cache/result_cache.py` (`ResultCache(max_entries/bytes)`, `get_or_compute`, métricas de aciertos/fallos). 5) Pruebas de sensibilidad por componente y de «hit ⇒ 0 llamadas a `solve()`» |
| Módulos afectados | **Nuevos:** `parallel/shared_data.py`, `cache/{__init__,keys,result_cache}.py`, tests. **Tocados:** `parallel/worker.py`, `parallel/executor.py` (integración), `config/parallel_config.py` (modo, caché) |
| Dependencias | B5.2 validado; decisión del modo de datos por medición |
| Riesgos | R-05, R-10, R-14; el beneficio de la memoria compartida puede ser nulo mientras los modelos copien (`copy=True`): se **reporta**, sin cambiar B1–B4 |
| Pruebas | Arrays `writeable=False` y hash verificado; sin segmentos/ficheros residuales tras éxito, excepción y `kill -9`; payload por tarea pequeño; cambiar cualquiera de los 10 componentes ⇒ *miss*; `CompositionHash` igual con distinta cartera actual ⇒ *miss*; caché on/off ⇒ resultados idénticos bit a bit; caché acotada (expulsión); aciertos eliminan llamadas al solver (contador = 0); caché **desactivada por defecto** |
| Criterios de aceptación | CCH-001…005 y PAR-004/005 con tests aprobados; modo por defecto justificado con resultados reales de E4 (guardados en `benchmarks/results/`); ninguna fuga tras 100 iteraciones de crear/destruir el contexto |
| Rollback | `cache.enabled=false` y modo de datos «pickle-initializer»; eliminar `cache/` y `parallel/shared_data.py` no afecta a B5.2 |

### B5.4 — Gestión de lotes, fallos y recuperación

| Campo | Contenido |
|---|---|
| Objetivo | Aislar errores individuales, tolerar caídas, cancelar y reanudar sin pérdida ni duplicados |
| RequirementID | (oficiales) PAR-011 (completo), BEN-001 (etapas Staging/Database N/A hasta B6); (propuestos, tras D-05) P-03, P-04, P-05, P-06, P-07 |
| Pasos | 1) Captura de excepciones por tarea en el worker (`FAILED_*`, trazas acotadas). 2) Reintentos, reconstrucción del pool ante `BrokenProcessPool`, cuarentena. 3) Timeouts por capas y cancelación. 4) `parallel/journal.py`: diario por lotes en disco local (Parquet/JSON/npz, **no pickle**), índice atómico, `RunManifest`, reanudación con verificación de hashes. 5) Contabilidad de integridad. 6) `parallel/protocols.py` (`MarketDataProvider`, `PortfolioRequestSource`, `ResultSink`, `RunControl`, `ProgressReporter`) con implementaciones locales y CLI JSON; test de arquitectura que prohíbe imports de DB/HTTP en `portfolio_engine` |
| Módulos afectados | **Nuevos:** `parallel/{journal,protocols,supervisor}.py`, CLI en `benchmarks/scripts/` o `parallel/cli.py`, tests. **Tocados:** `parallel/executor.py`, `parallel/worker.py`, `tests/unit/test_architecture_rules.py` (nuevas reglas, no relaja las existentes) |
| Dependencias | B5.2 y B5.3 validados; D-04, D-05, D-06, D-10 |
| Riesgos | R-05, R-06, R-07, R-08, R-14, R-17, R-19 |
| Pruebas | Inyección de fallos: excepción en tarea; `os._exit` / `kill -9` de un worker; tarea que cuelga hasta plazo; solver que devuelve cada estado no óptimo (se conserva el estado); cartera inválida; corrupción/truncamiento de un fichero del diario (escritura parcial); caída del coordinador a mitad y reanudación (resultado final = ejecución ininterrumpida, T0); reanudación con config/snapshot/código distintos ⇒ rechazo; cancelación conserva lo completado; ninguna pérdida/duplicado (invariante de conteo); dos ejecuciones simultáneas sin colisión; salidas del CLI JSON estables |
| Criterios de aceptación | Todas las pruebas de fallo pasan; invariante de integridad en el 100 % de las ejecuciones de prueba; el diario nunca contiene `pickle`; tiempos de recuperación medidos y reportados (sin umbral inventado) |
| Rollback | Modo «sin diario» (`journal.enabled=false`); `git revert` de la entrega; B5.2/B5.3 siguen operativos |

### B5.5 — Benchmarks, pruebas de regresión y auditoría independiente

| Campo | Contenido |
|---|---|
| Objetivo | Medir de verdad, fijar baseline, detectar deterioros y auditar |
| RequirementID | CFG-012 (completo), BEN-001/002 (completos), BEN-004, BEN-005, BEN-006, BEN-007, TST-005, GOV-012 |
| Pasos | Ejecutar el `BLOCK_5_BENCHMARK_PLAN.md`: harness (`benchmark/suite.py::scaling_benchmark`, `benchmark/regression.py::compare_to_baseline`, `benchmarks/scripts/scaling.py`, `benchmarks/scripts/scale_run.py`), generador sintético determinista, resultados con metadatos en `benchmarks/results/`, tests `tests/performance/` con marcador `performance`; informe de la fase; auditoría independiente (otro agente/equipo, sin reutilizar mis oráculos); emisión de `BLOCK_5_STATUS` |
| Módulos afectados | `benchmark/`, `benchmarks/`, `config/benchmark_config.py`, `tests/performance/`, `tests/integration/` |
| Dependencias | B5.2–B5.4 validados; D-01, D-03, D-11, D-12 |
| Riesgos | R-01, R-04, R-09, R-13 |
| Pruebas | Todas las del plan de benchmarks (equivalencia, aislamiento, reanudación, regresión de rendimiento) y la suite completa |
| Criterios de aceptación | Ver §4; sin cifras inventadas; los resultados quedan en `benchmarks/results/` con commit, hashes y versiones; los requisitos solo pasan a `VALIDATED` con su test de aceptación pasado |
| Rollback | Retirar scripts/resultados no afecta a la funcionalidad; el baseline anterior se conserva versionado |

---

## 4. Criterios de cierre del Bloque 5 (propuestos)

1. Suite completa verde (B1–B4 sin regresión) más las pruebas nuevas; `mypy --strict`, `ruff check`,
   `ruff format --check` limpios (sin ejecutar `ruff format .` en la raíz: reescribe bloques de código de los
   `.md` de auditoría — véase memoria del proyecto).
2. Equivalencia secuencial↔paralelo (T0 en misma máquina; T1 entre máquinas) en todas las clases W0–W5 probadas.
3. Pruebas de fallos y reanudación aprobadas; integridad de conteo al 100 %.
4. Validación real a 10, 100 y 1.200 carteras (DoD oficial). Escalas 1.000/5.000/22.000: medidas y reportadas;
   las no ejecutadas se declaran **no ejecutadas** y los requisitos asociados quedan `PARTIAL`.
5. `TRACEABILITY.md` y `CHANGELOG.md` actualizados; estados solo `NOT_IMPLEMENTED/PARTIAL/IMPLEMENTED/VALIDATED`.
6. Auditoría independiente sin hallazgos bloqueantes.

---

## 5. Orden y dependencias

```
B5.1 (diseño) ──► [decisiones D-01…D-13] ──► B5.2 ──► B5.3 ──► B5.4 ──► B5.5 ──► auditoría independiente
                                               │         └─ puede solaparse parcialmente con B5.4 solo en diseño de pruebas
                                               └─ baseline de perfilado compartido con B5.5
```

Cada flecha es una puerta de fase: no se avanza sin instrucción expresa del usuario.

---

## 6. Deuda técnica conservada (no se aborda en B5)

F-03b, F-04, F-05, F-06, F-07, F-08, F-09, F-11…F-13 de `AUDIT_BLOCK_4_CLOSURE.md`/`AUDIT_BLOCK_4.md` siguen
abiertas. Las que interactúan con B5 están listadas en el §5 del documento de arquitectura (F-03b, F-04, F-07,
F-09 y la nota de rendimiento de Clarabel). Ninguna impide el desarrollo del B5.

Mejoras detectadas que pertenecen a otros bloques o requieren cambiar código de B1–B4 y **no** se implementan
en B5 sin instrucción expresa: copia obligatoria de arrays en los modelos (`readonly_float_array`,
que impide compartir memoria física real); aceleración de `candidate_generation` (si el perfilado la justifica);
orquestador `engine.py` (B6); persistencia SQL y `RunMetadata` formal (B6).

---

## 7. Preparación de B5.2 (evaluación tras las decisiones del 2026-10-19)

| Condición | Estado |
|---|---|
| Decisiones que bloqueaban B5.2 (D-01, D-02, D-13, D-07, D-09, D-05) | Resueltas (ver arquitectura §14.1) |
| Decisiones diferidas | Ninguna bloquea B5.2 (arquitectura §14.2) |
| Alcance de B5.2 definido (módulos, requisitos, pruebas, aceptación, rollback) | Sí (§3) |
| Contrato de workload (`WorkloadSpec`, catálogo de operaciones con los motores reales) | Definido a nivel de diseño; su forma final es el primer paso de B5.2 |
| Definiciones W0–W5 y mix de referencia | En `BLOCK_5_BENCHMARK_PLAN.md` §2 (supuesto de ingeniería, configurable) |
| Benchmarks de B5.2 | Solo locales y de escala < 1.000 carteras; cualquier carga ≥ 1.000 (o cualquier carga en Arsys) exige aprobación específica (D-12) |
| Baseline de la suite (1.482 pruebas) en esta rama | **No re-ejecutado todavía** (solo diseño); es el paso 0 de B5.2 |
| Aprobación expresa para iniciar | **Pendiente: B5.2 no se inicia sin ella** |

Conclusión: el diseño está en condiciones de iniciar B5.2 (`BLOCK_5_DESIGN_STATUS = READY`), condicionado a su
aprobación expresa y a las condiciones de entrada de arriba. Riesgos que persisten y se vigilan en B5.2: R-02,
R-03, R-08, R-09, R-11, R-12 (arquitectura §13).


---

## 8. Resultado de B5.2 (2026-10-19) y estado de los requisitos propuestos

Implementado en la rama `block5-hpc-architecture` sin commit (véanse `CHANGELOG.md`, `ARCHITECTURE.md` §3.7,
`TRACEABILITY.md`). Diferencias respecto al plan de §3 (B5.2), justificadas en `ARCHITECTURE.md` §3.7:

* `ParallelConfig` vive en `config/default_parallel.toml` con cargador propio (no es campo de `EngineConfig`).
* El snapshot llega al worker por un fichero de arranque hash-verificado (hallazgo medido E-8), no por `initargs`.
* El catálogo de operaciones integra la búsqueda de candidatos en `GLOBAL_FRONTIER` y la construcción de escenarios en
  `MULTI_SCENARIO`; `STRATEGY_ROBUST` no admite `mu_set` explícito.
* No se añadió `psutil` (no hizo falta); `threadpoolctl` pasó a dependencia directa.
* Criterio de aceptación T1 (D-07); la igualdad bit a bit es diagnóstico (104.734 floats comparados, 0 inexactos).

Estado de los requisitos propuestos (no oficiales; D-05):

| ID | Estado tras B5.2 | Evidencia / pendiente |
|---|---|---|
| P-01 | PARTIAL | `ExecutionStatus` separado de `SolverStatus` y sin reetiquetado (`test_solver_states_are_not_execution_failures`, estados idénticos secuencial↔paralelo); faltan `TIMED_OUT`, `CANCELLED`, `SKIPPED_BY_RESUME` (B5.4) |
| P-02 | PARTIAL | Cola acotada probada (`test_scheduling_is_dynamic_and_the_queue_is_bounded`); RSS del coordinador no medido (sin `psutil`) |
| P-03 | PARTIAL | «Exactamente una vez» comprobado en cada ejecución (`test_the_integrity_check_detects_lost_duplicated_and_swapped_results`, caída de worker); contabilidad completa y diario en B5.4 |
| P-04 | NO INICIADO | B5.4 |
| P-05 | NO INICIADO | B5.4 (contrato D-04 pendiente) |
| P-06 | NO INICIADO | B5.4: hoy **todos los lotes en vuelo** quedan `WORKER_CRASHED` sin reintento ni cuarentena (semántica fijada por `test_a_crash_mid_task_marks_every_in_flight_batch_as_worker_crashed`; con detección tardía posible del último worker creado, véase `ARCHITECTURE.md` §3.7) |
| P-07 | NO INICIADO | B5.4 (D-10) |
| P-08 | PARTIAL | `RunManifest` mínimo (hashes, versiones, plataforma, parámetros); sin commit de Git (la biblioteca no invoca `git`; lo registran los benchmarks) |
| P-09 | CUMPLIDO con limitación | `WorkloadSpec` (`test_workload.py`) y equivalencia T1 de las 13 variantes; sin `mu_set` explícito |

Hallazgo de rendimiento que condiciona B5.3–B5.5: el arranque de cada worker (≈5 s de `import` en `spawn`) domina a
tamaños pequeños; el reparto del tiempo de CPU entre fases no se ha perfilado todavía (paso 1 de B5.2 del plan:
pendiente, no se ha ejecutado `cProfile`).

---

## 9. Resultado de B5.3 (2026-10-20) y estado de los requisitos propuestos

Rama `block5-shared-memory-cache`, pendiente de auditoría independiente (`AUDIT_REQUEST_BLOCK_5_3.md`). Detalle, cifras y
límites en `CHANGELOG.md` (Bloque 5.3) y `ARCHITECTURE.md` §3.8.

* Datos compartidos: `BUNDLE_FILE` (defecto, B5.2), `FILE_MMAP`, `SHARED_MEMORY`; referencia de tamaño constante; arrays de
  solo lectura sin copia; limpieza e inventario de huérfanos. Sin ventaja de arranque; ahorro de memoria privada ≈ tamaño de los datos.
* Caché por worker a nivel de operación, clave completa, límites y métricas; desactivada por defecto; sin aciertos entre carteras distintas.
* Equivalencia T1 comprobada para los tres modos y con caché; ningún solver, tolerancia ni estado modificado.

| ID | Estado tras B5.3 | Evidencia / pendiente |
|---|---|---|
| P-02 | PARTIAL | Memoria por worker medida con `psutil` (benchmarks); RSS del coordinador y presupuesto global siguen sin cerrarse (B5.4/B5.5) |
| P-09 | CUMPLIDO con limitación | `STRATEGY_ROBUST` admite `mu_half_width` (`BOX`); `ELLIPSOIDAL` sigue sin expresarse (M-2 parcial) |
| resto | Sin cambio | B5.4 abierto: M-1, D-DET, L-1, L-2, L-4, reintentos, plazos, diario |

Remediación tras `AUDIT_BLOCK_5_3.md` (`PASS_WITH_CHANGES`): M-1…M-4 y L-2…L-7 corregidos (`CHANGELOG.md`, «Remediación tras
AUDIT_BLOCK_5_3»); H-1 (fragilidad numérica B4 dependiente del runner) queda abierta fuera del alcance de B5.3.
