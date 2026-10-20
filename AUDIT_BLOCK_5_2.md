# AUDIT_BLOCK_5_2 — Auditoría independiente del Bloque 5.2

Fecha: 2026-10-20. Rama `block5-hpc-architecture` (HEAD `271eaeb`, árbol de trabajo **sin commit** del implementador).
Auditor: revisión independiente; no se modificó código de producción, `MASTER_SPEC.md`, tests ni documentos existentes
(único fichero creado: este informe; las sondas están en el directorio temporal de la sesión, fuera del repositorio).
No se hizo commit/push/PR/merge/tag, no se ejecutaron benchmarks masivos, no se accedió a SQL Server/Oracle/Arsys, no se inició B5.3.

## 0. Acceso al árbol real

`git status` muestra exactamente los ficheros modificados y sin seguimiento descritos (`portfolio_engine/parallel/{task,executor,worker,batching,workload,threading_control}.py`,
`config/parallel_config.py`, `config/default_parallel.toml`, `tests/unit/parallel/`, `tests/integration/test_{determinism,parallel_equivalence}.py`,
`tests/fixtures/parallel.py`, benchmark y 3 JSON). Se auditó ese árbol, no `origin/main`. **No BLOCKED.**

## 1. Pruebas reproducidas (ejecutadas realmente)

| Comprobación | Resultado |
|---|---|
| `pytest` suite completa (incluido el test añadido tras el gate) | 1665 tests recogidos; ejecución completa `EXIT=0`, 1665 puntos, sin `F/E/s` (1664 + el test de integridad) |
| Test de integridad añadido (`test_the_integrity_check_detects_lost_duplicated_and_swapped_results`) | 1 passed (también aislado) |
| `mypy` (strict, 165 ficheros) | Success: no issues |
| `ruff check` / `ruff format --check` (portfolio_engine, tests, benchmarks) | limpio / 323 ficheros formateados (no se ejecutó `ruff format .` en la raíz) |
| Equivalencia T1 W0–W5 | Cubierta por `test_parallel_equivalence.py` (41) y `test_determinism.py` (7), todos en verde dentro de la suite. Tolerancia 1e-6 absoluta = la de la regresión dorada; estados de solver por igualdad exacta; comparador recorre todos los campos salvo relojes/PID/traceback (con test de que detecta diferencias reales). Los JSON de benchmark registran `t1_differences_vs_sequential = 0` |

Nota: el recuento de la suite se ha verificado por conteo de resultados y `--collect-only`, no por la línea final de pytest (ejecutada con `-q -q`).

## 2. Pruebas ejecutadas vs. comprobaciones estáticas

- **Ejecutado (Windows 11, Python 3.13.6, `spawn`)**: suite, mypy, ruff, tres sondas propias (abajo), verificación de solo-lectura de arrays tras el *bundle*, ACL del directorio temporal.
- **Solo estático**: Linux `forkserver` (no hay Linux utilizable: la única distro WSL es la de Docker Desktop, parada), reintentos/plazos (no existen), permisos POSIX 0700 (se confía en `tempfile.mkdtemp`).

## 3. Hallazgos

### H-1 — HIGH — `WORKER_CRASHED` castiga a carteras que no fallaron y la documentación lo subestima
Evidencia (sonda `probe_crash.py`: 48 carteras, 2 workers, `batch_size=4`, un worker muere a mitad de trabajo con `os._exit`):
`{'COMPLETED': 32, 'WORKER_CRASHED': 16}`, 1 reconstrucción. Un solo worker caído implica como máximo 4 carteras culpables, pero se marcaron 16
(= todos los lotes en vuelo, límite `workers × max_in_flight_per_worker × batch_size` = 2×2×4). Hasta 12 carteras sanas quedaron como `WORKER_CRASHED` definitivo,
sin reintento y con `operations=()` (se pierde incluso lo ya calculado en el lote).
`CHANGELOG.md` y `ARCHITECTURE.md` dicen «un worker caído marca **todo el lote**»; la realidad es **todos los lotes en vuelo**.
Impacto: con la configuración de ejemplo y 22.000 carteras, un OOM aislado invalida decenas de carteras sanas y el estado `WORKER_CRASHED` pasa a significar «afectada por una caída», no «causó una caída» (semántica contraria a §6.4 del diseño, que prevé reintento y cuarentena).
Es alcance declarado de B5.4 (reintentos), por lo que no es regresión; sí lo es la **inexactitud documental** y la ausencia de una prueba que fije la semántica real.
Remediación: corregir CHANGELOG/ARCHITECTURE/TRACEABILITY (todos los lotes en vuelo); añadir test con ≥2 workers y caída a mitad de tarea; en B5.4 reintentar los lotes en vuelo (`attempt+1`) y aislar a la tarea venenosa antes de etiquetar `WORKER_CRASHED`.

### M-1 — MEDIUM — Fallo determinista del *initializer*: sin corte, N reconstrucciones y ejecución «con éxito»
Sonda `probe_initfail.py` (hash de *bundle* erróneo): `run()` **devuelve** 24/24 `WORKER_CRASHED`, 3 reconstrucciones, 19 s. Un error de arranque (dependencia ausente en Linux, `bundle` corrupto, `ImportError`) se presenta como 24 «caídas de worker» y cada reconstrucción paga ~5–6 s de `import`; no hay límite de reconstrucciones consecutivas sin progreso ni excepción de nivel de ejecución.
Además, `pool.submit(...)` en `_execute` (executor.py:268) no está protegido: si el pool se rompe entre iteraciones, `BrokenProcessPool` se propaga y se descartan todos los resultados (análisis estático; **no reproducido**).
Remediación: contador de reconstrucciones sin progreso → `ParallelExecutionError`; capturar `BrokenProcessPool` en `submit`.

### M-2 — MEDIUM (limitación de alcance, no regresión) — `STRATEGY_ROBUST` sin `mu_set` explícito
`task.py:430-437` solo pasa `covariance_scale_max`; `StrategyOptimizer.robust` (B4) conserva `mu_set` intacto, así que **la API de B4 no cambia ni se degrada**: no es regresión. Es una capacidad de B4 no expuesta por el nuevo `WorkloadSpec`. Consecuencia concreta (estática, no ejecutada): con `expected_returns.mode` externo y `[robust].mu_uncertainty ≠ NONE`, `_mu_set` lanza `UnsupportedCombinationError` («suministre un MuUncertaintySet explícito»), imposible de suministrar desde el workload ⇒ `FAILED_EXCEPTION` para todo mandato con alpha externo. Está documentada (E-5, CHANGELOG, plan P-09 «CUMPLIDO con limitación»). Conclusión: **limitación de alcance, correctamente rotulada PARTIAL en la documentación de diseño**, pero `OperationKind.STRATEGY_ROBUST` no figura como PARTIAL en TRACEABILITY.
Remediación: decidir en B5.3/B5.4 un `MuUncertaintySpec` serializable (tipo, half-width/ω/radio) dentro de `OperationSpec`, o declarar explícitamente la exclusión de alpha externo.

### M-3 — MEDIUM — `FORKSERVER` ofrecido y sin ninguna prueba; riesgo de entorno
`ProcessStartMethod.FORKSERVER` es valor válido de configuración (y objetivo de producción Ubuntu), pero no se ejecutó nunca (solo un test monkeypatch de «método no disponible»). Riesgo estático: el servidor *forkserver* se lanza una vez por proceso coordinador con el `os.environ` de ese instante; las variables de `worker_thread_environment` solo llegan si el servidor arranca dentro del bloque, y no se refrescan en ejecuciones posteriores con otro `blas_threads`. `threadpoolctl` en el *initializer* mitiga BLAS/OpenMP ya cargados, pero no HiGHS/otros hilos nativos. Tampoco hay `set_forkserver_preload`. El CHANGELOG ya admite «no probado»; falta reflejarlo en TRACEABILITY (CFG-011/PAR-013 figuran sin esta salvedad).
Remediación: CI Linux (Ubuntu 22.04 + Python ≥3.11) con la suite paralela en `forkserver`; test de hilos por worker en ese modo.

### M-4 — MEDIUM — Cobertura de pruebas de fallo y estados `VALIDATED` optimistas
El único test de caída (`test_a_worker_crash_is_reported_and_the_run_continues`) mata el worker **en el initializer** con 1 worker; no ejerce caída a mitad de tarea, ni con vecinos sanos, ni el fallo determinista del initializer. Se cita como evidencia de PAR-013 (`VALIDATED`), que además declara dependencia de PAR-004 (`NOT_IMPLEMENTED`). Recomendación: PAR-013 → `PARTIAL` hasta B5.3, o documentar por qué su dependencia no condiciona el estado.

### L-1 — LOW — Detección de contaminación acotada a `mu`/`Σ`
`snapshot_fingerprint` cubre solo `mu` y `sigma`; `universe`, `costs` y `return_scenarios` no se vigilan. Se comprobó (`probe_ro.py`) que tras `pickle` los arrays siguen `writeable=False` y la escritura falla, por lo que el riesgo real es bajo.

### L-2 — LOW — Mensajes y trazas sin truncar
`TaskError.message = str(error)` y la traza completa viajan en el resultado; el diseño (§6.8) exige truncado/escape para no volcar datos de cartera en logs. Remediar al introducir el diario (B5.4).

### L-3 — LOW — Ciclo de vida del fichero de arranque
Contiene `mu`, `Σ`, universo y costes en claro en `%TEMP%` mientras dura la ejecución; se borra en `finally` (probado, incluido fallo previo) pero queda tras muerte brusca del coordinador (admitido en el CHANGELOG) y no hay barrido de directorios `portfolio_engine_run_*` huérfanos. Permisos: no se fijan explícitamente; se confía en `mkdtemp` (Windows: ACL heredada SYSTEM/Administradores/usuario, verificada; POSIX 0700, no verificado) y no hay test de permisos. Integridad correcta: lectura única → hash → `pickle.loads` sobre los mismos bytes (sin TOCTOU); el hash viaja por canal distinto del fichero; manipulación rechazada antes de deserializar (test).

### L-4 — LOW — `os.environ` del coordinador mutado temporalmente
`worker_thread_environment` modifica el entorno global del proceso; no es seguro con varios hilos del coordinador ejecutando `run()` a la vez (restauración cruzada). Documentar «un `ParallelExecutor.run` a la vez por proceso».

### L-5 — LOW — Higiene documental
`parallel/__init__.py` conserva el docstring de B3 («solo existen las utilidades de determinismo…»); README usa `.venv/Scripts/python` (solo Windows).

### I-1 — INFO — Contratos y semántica correctos
- `WorkloadSpec`: catálogo cerrado, parámetros obligatorios/prohibidos validados antes de ejecutar, hash canónico con `schema_version`.
- `TaskResult`: estados de ejecución separados de los de solver (nunca se reetiquetan; test `solver_states_are_not_execution_failures`). `COMPLETED` solo significa «sin excepción»: los consumidores deben leer `is_valid_solution/outcome` (deuda F-03b de B4).
- `ParallelExecutor`: `fork` excluido; cola acotada; orden canónico por `SequenceID`; `TaskID` independiente del calendario; pérdidas/duplicados/identidades cruzadas detectados y fail-closed (se aborta con `ParallelExecutionError`, sin resultados parciales). El chequeo de intercambio comprueba `portfolio_id` por `SequenceID`, no `task_id` (suficiente hoy).
- Aislamiento: motores nuevos por tarea; test «sola vs. en lote grande» da resultados equivalentes. `PortfolioID` duplicado rechazado. `workers` sin valor por defecto ni `cpu_count` (regla arquitectónica comprobada por AST).
- Dependencias de capas: grafo acíclico verificado por los tests de arquitectura (reglas ampliadas correctamente y sin relajar prohibiciones ajenas).
- Sobresuscripción: dentro de cada worker spawn todas las librerías detectadas por `threadpoolctl` quedan en 1 hilo (test con proceso real). No se midió CPU total del sistema ni hilos de HiGHS/Clarabel (`psutil` ausente; admitido).
- Reproducibilidad: 1/2/3 workers, lotes 1/2/AUTO/único, envío barajado y repetición dan T1 sin diferencias; T0 (bit a bit) coincide en esta máquina, solo diagnóstico.

### I-2 — INFO — Benchmarks (honestos; separar overhead, cómputo y total)
Verificados contra los JSON (`valid_measurement=true`, T1=0 en cada fila). Cada repetición **incluye el arranque del pool** (~6–7 s, `import` por worker en `spawn`):
- 24 carteras ligeras: secuencial 2,73 s; paralelo 7,4–9,3 s (speedup 0,29–0,37); `compute_occupancy` ≈ 0,09, `overhead_estimate` ≈ 7,2 s. El paralelo **pierde** por completo.
- 20 carteras (12 W1): secuencial 11,94 s; 4 workers 10,95 s (1,09×) / AUTO 11,85 s (1,01×). Suma de cómputo por tarea 11,9 s (secuencial) → 14,96 s (4 workers, +25 %): contención/SMT en un host de 16 CPU lógicas.
- Los tiempos son mínimo de 3 repeticiones en una máquina documentada como bimodal (~5×); el CHANGELOG evita proyectar a 22.000 carteras y rotula la mezcla como supuesto. La cifra «camino crítico 2,9×» es derivada (no tiempo de pared) y así se declara. Conclusión correcta: B5.2 **no demuestra aceleración**; el valor del bloque es corrección, determinismo y base para B5.3–B5.5. El arranque del pool es coste fijo que habrá que amortizar (preload `forkserver`, pool persistente).
- `parallel_scaling_24portfolios_20261019T205808Z.json` (pool serializado) se conserva como evidencia de la causa raíz E-8, no como resultado vigente.

## 4. Trazabilidad y coherencia documental

Recuentos coherentes: 231 VALIDATED + 43 PARTIAL + 42 NOT_IMPLEMENTED = 316; tabla PAR (1 NOT / 2 PARTIAL / 10 VALIDATED) coincide con las filas. 0 `IMPLEMENTED` (correcto). Cifra 1664 passed coherente con 1665 recogidos tras el test añadido (documentado). Correcciones requeridas: H-1 (alcance de la caída), M-2 (ROBUST parcial), M-3 (forkserver sin probar), M-4 (PAR-013), L-5.

## 5. Veredicto

**BLOCK_5_2_AUDIT_STATUS = PASS_WITH_CHANGES**

- No hay BLOCKER. La corrección numérica (T1), el aislamiento, la integridad de resultados y los controles de calidad se reprodujeron.
- **¿B5.2 preparado para integración?** Sí, **condicionado** a corregir, antes del commit, la documentación (H-1, M-2, M-3, M-4, L-5) y, recomendable, añadir el test de caída a mitad de tarea con ≥2 workers (H-1/M-4). No exige cambios de lógica de producción obligatorios; M-1 puede resolverse en B5.4.
- **¿Puede iniciarse B5.3?** Sí, una vez aplicadas esas correcciones documentales y con autorización explícita del usuario. Antes de apoyarse en el modo `FORKSERVER` o en cifras de rendimiento hay que ejecutar la suite en Linux y amortizar el arranque del pool.

Detenido; a la espera de instrucciones.
