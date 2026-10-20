# B5.4 — Recovery & Journal, trabajo paralelo aislado

**Estado:** preparado, no implementado. Rama `block5-recovery-journal` derivada de `main` en el commit `539d4b7e37384921dfbfe2a51a3c52d809ba5517`. **B5.3 sigue en paralelo en `block5-shared-memory-cache`.**

## Objetivo

Implementar recuperación controlada de lotes, reintentos, límites de tiempo, cancelación y diario local verificable, preservando resultados de B1–B5.2. NO añadir integraciones SQL, red, orquestación remota ni persistencia empresarial (reservadas para B6).

## Base y autoridad

Leer `MASTER_SPEC.md`, `BLOCK_5_IMPLEMENTATION_PLAN.md` (§3 B5.4), `BLOCK_5_BENCHMARK_PLAN.md` (C-10 a C-16, C-25 y E9) y `AUDIT_BLOCK_5_2.md` + `REMEDIATION_BLOCK_5_2.md`. La suite Linux de B5.2 aprobó 1.669 tests antes de este trabajo.

## Reglas estrictas para paralelismo entre equipos

- Trabajar en esta rama y su propio worktree/carpeta; nunca usar el mismo working tree que el agente que implementa B5.3. No mezclar cambios sin registrar.
- Las interfaces compartidas `parallel/executor.py`, `parallel/worker.py`, `parallel/task.py`, `config/parallel_config.py` pueden cambiar en B5.3. Minimizar modificaciones a estos archivos; primero construir módulos aislados y pruebas. Documentar conflictos previstos.
- No fusionar en `main` hasta integrar B5.3 y ejecutar de nuevo pruebas completas tras rebase/cherry-pick controlado. No resolver conflictos de caché/memoria/estado por eliminación de código.
- Sin merge, PR de integración ni deploy automático; publicar commits solo a esta rama cuando estén probados, con reporte de cambios.

## Tareas técnicas

1. **Baseline**: checkout y git status, Python >=3.11, pytest/mypy/Ruff; no tocar producción.
2. **Contrato de errores**: distinguir fallo de tarea, fallo de initializer, pool roto, cancelación, timeout y `SolverStatus`. Mantener `ExecutionStatus` independiente del estado matemático del solver.
3. **Supervisor y reconstrucción**: aislar lotes en vuelo al detectar `BrokenProcessPool`, atrapar fallos tanto en `submit` como en `result`, poner tope configurable de reconstrucciones consecutivas sin progreso; implementar reintentos idempotentes, cuarentena/reducción de lote ante tarea venenosa; evitar reintentos sin límite y no atribuir culpa a carteras sanas.
4. **D-DET**: probar la detección tardía de caída de un worker creado bajo demanda; asegurar cierre/contabilidad sin perder una tarea pendiente.
5. **Timeout y cancelación**: especificar semántica rigurosa para timeout de solver vs tarea vs lote. No prometer kill individual que ProcessPoolExecutor no puede garantizar sin mecanismo supervisado; estudiar procesos dedicados si lo requiere la prueba. Preservar resultados completados.
6. **Diario local**: `parallel/journal.py` con formato NO ejecutable (JSON/JSONL con checksums, blobs numéricos seguros cuando corresponda), escrituras atómicas, hashes de entrada/versión/config/snapshot y `RunManifest`; recuperación y rechazo de reanudaciones incompatibles. No deserializar pickle de fuente externa.
7. **Interfaces desacopladas**: `parallel/protocols.py` con contratos `MarketDataProvider`, `PortfolioRequestSource`, `ResultSink`, `RunControl`, `ProgressReporter`; CLI JSON local si encaja sin crear `engine.py` (B6). Sin conexiones externas.
8. **Observabilidad segura**: mensajes y trazas limitados, sin exposición de datos de carteras; limpieza de temporales y comportamiento ante muerte del coordinador.
9. **Pruebas adversariales**: workers 1/2/3, kill a mitad de tarea, initializer siempre fallido, pool roto durante submit, vecino sano, tarea venenosa, truncado de journal, reanudación incompatible, repetición/cancelación, datos sintéticos, tolerancias T1.
10. **Gate final**: suite completa, mypy strict, Ruff y tests de arquitectura; benchmarks únicamente pequeños, locales, sintéticos. Registrar evidencia e incidencias con criticidad.

## Criterios de aceptación

- Cada `TaskID` se contabiliza una sola vez; no hay carteras perdidas ni duplicadas.
- Caída de un worker no convierte permanentemente en fallidas carteras sanas sin posibilidad de reintento documentada.
- No hay loop infinito si el initializer falla consistentemente.
- Reanudar con una fuente incompatible es rechazado sin corrupción.
- Las respuestas matemáticas conservan equivalencia T1 y estados exactos.
- El diario no almacena secretos ni cargas de clientes sin controles explícitos.
- Riesgos no demostrados quedan como PARTIAL, no VALIDATED.

## Restricciones y salida

No cambiar `MASTER_SPEC.md`; no tocar ramas `main` ni B5.3; sin Arsys, Oracle, SQL Server, datos reales, cargas >=1.000 ni credenciales.

Entregar: commits/branch SHA, arquitectura realizada, pruebas, riesgos, archivos que se solapan con B5.3, instrucciones concretas de integración posterior y estado `B5_4_STATUS = READY_FOR_INDEPENDENT_AUDIT / PASS_WITH_CHANGES / BLOCKED`.

**No realizar merge ni empezar B5.5**.
