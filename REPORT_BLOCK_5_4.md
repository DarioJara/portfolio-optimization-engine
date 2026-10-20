# REPORT_BLOCK_5_4 — Recuperación, reintentos, plazos, cancelación, diario y reanudación

Fecha: 2026-10-20 · Rama: `block5-recovery-journal` · Base: `main` `bf74f974` (B5.3 integrado) ·
Estado: **`B5_4_STATUS = READY_FOR_INDEPENDENT_AUDIT`** (con las limitaciones de §6; Linux no ejecutado).

## 1. Alcance

* Bloque: **B5.4** (`BLOCK_5_IMPLEMENTATION_PLAN.md` §3, `BLOCK_5_4_EXECUTION_BRIEF.md`).
* Requisitos: oficiales `PAR-011` (completo), `PAR-013`, `BEN-001` (sin cambio de estado); propuestos `P-01`, `P-03`…`P-08`.
* Módulos permitidos: `parallel/{supervisor,markers,journal,codec,protocols,cli}.py` (nuevos), `parallel/{executor,worker,task,shared_data}.py`,
  `config/parallel_config.py`, `config/default_parallel.toml`, tests y documentación.
* Fuera de alcance (no tocado): `MASTER_SPEC.md`, motores/solvers/tolerancias de B1–B4, caché y mecanismos de memoria compartida de B5.3,
  SQL/red/orquestación (B6), `engine.py`, benchmarks masivos y auditoría (B5.5). Sin Arsys, sin datos reales, sin cargas ≥ 1.000.

## 2. Qué se hizo

1. Estado Git verificado (árbol limpio; la rama local no existía, sí `origin/block5-recovery-journal` con solo `BLOCK_5_4_EXECUTION_BRIEF.md`).
   Rama local creada desde el remoto e `origin/main` (`bf74f97`) integrado con un **merge sin conflictos** (`6498f0e`); nada descartado.
2. Baseline antes de tocar código: **1775 passed, 2 skipped**.
3. Implementación (arquitectura en `ARCHITECTURE.md` §3.9):

| Pieza | Contenido |
|---|---|
| Contrato de errores | `ExecutionStatus` + 5 estados; independiente de `SolverStatus` |
| Supervisor | cuarentena de la tarea sospechosa (reintento aislado), reenvío intacto de las sanas, captura en `submit`, cotas, plazos tarea/lote, cancelación con gracia, vigilancia de PID |
| Marcas de progreso | ficheros vacíos `w.<pid>` / `t.<lote>.<pos>.<pid>`; sin API privada del pool |
| Diario | JSON no ejecutable + códec con lista blanca, escritura atómica, sumas SHA-256, manifiesto/identidad, bloqueo del SO, eventos |
| Interfaces | 5 `Protocol` + versiones locales; CLI `journal-info` |
| Observabilidad | mensajes/trazas acotados; eventos sin datos de cartera; marcas bajo el barrido de huérfanos |

## 3. Evidencia (ejecutada realmente; Windows 11, Python 3.13.6, `.venv`)

| Comprobación | Resultado |
|---|---|
| Baseline pre-cambios | 1775 passed, 2 skipped (13 min 20 s) |
| Suite completa tras B5.4 | **1925 passed, 3 skipped** (19 min 20 s); 0 regresiones; +150 pruebas |
| Equivalencia matemática T1 | suite existente (`test_parallel_equivalence`, `test_determinism`, `test_shared_data_equivalence`, regresión dorada) sin cambios y verde; cada prueba de recuperación compara contra la referencia secuencial bajo T1; códec: 0 floats distintos en las 14 clases W0–W5 (tolerancia 0) |
| `mypy --strict portfolio_engine` | sin errores (176 ficheros) |
| `ruff check .` · `ruff format --check portfolio_engine tests benchmarks` | limpios |
| Reglas de arquitectura | nuevas: sin `pickle.load` fuera de `cache/result_cache.py` y `parallel/shared_data.py` (bytes propios / fichero propio con hash); el diario sin `eval`/`exec`; sin imports DB/HTTP en `parallel/` (ya existente) |

Pruebas de fallos con procesos reales (`tests/integration/test_recovery.py`, 20 casos): worker muerto a mitad de tarea con 1/2/3 workers
(resultado final ≡ ejecución sin fallos), tarea venenosa con lotes de 4, *initializer* que lanza / muere / se registra y muere,
worker reciclado (`max_tasks_per_child=1`) sin falsos positivos, tarea colgada → `TIMED_OUT`, lote lento → descomposición, cancelación,
reanudación completa / parcial / tras corregir la causa, reanudación incompatible (snapshot, solicitudes, menos solicitudes) rechazada sin
tocar el diario, diario opt-in, ausencia de restos de directorios, **coordinador real terminado a mitad y reanudado**, **dos coordinadores
simultáneos** con diarios distintos, y `TIME_LIMIT` del solver conservado como `SolverStatus`.

Tiempos de recuperación (medidos, sin umbral inventado): `RecoveryReport.recovery_seconds` por ejecución; dominados por el arranque `spawn`
(≈ 5 s por worker). No se ejecutó ningún benchmark de recuperación; esa medición es de B5.5.

## 4. Hallazgos durante la implementación (corregidos antes de entregar)

| # | Sev. | Hallazgo | Resolución |
|---|---|---|---|
| F-1 | Alta | Diseño inicial: las caídas *atribuidas* a una sospechosa consumían el presupuesto «sin progreso», de modo que 1 caída compartida + 2 intentos aislados de una venenosa abortaban la ejecución y dejaban `ABORTED` a carteras sanas (detectado por `test_a_poison_task_does_not_fail_its_healthy_batch_neighbours`) | El presupuesto cuenta solo caídas **sin atribuir** y venenosas consecutivas sin resultado en medio; las atribuidas quedan acotadas por `max_task_attempts` y `max_total_rebuilds` (+ prueba unitaria del caso «todas matan su proceso») |
| F-2 | Media | Códec: un `StrEnum` es también `str` y se codificaba como cadena (perdía el tipo; detectado por la prueba de ida y vuelta) | Comprobar `Enum` antes que `str` |
| F-3 | Media | Un directorio de diario con solo `.lock` (coordinador muerto antes del manifiesto) se rechazaba como «no vacío» | `_is_blank`: el bloqueo y un `shards/` vacío no cuentan |
| F-4 | Media | Cinco pruebas de B5.2 fijaban la semántica antigua («todos los lotes en vuelo → `WORKER_CRASHED`») | Reescritas (su docstring lo preveía) con la nueva semántica; las inyecciones de fallo existentes se conservan |
| F-5 | Baja | `msvcrt`/`fcntl`, `/proc`: código específico de plataforma | Rama por `sys.platform` (mypy limpio en ambas); Linux no ejecutado (ver §6) |

## 5. Archivos que se solapan con B5.3 (ya integrado en `main`)

B5.3 está en `main`, por lo que ya no hay solape *pendiente*; estos son los archivos de B5.3 que B5.4 modifica y lo que cambia:

* `parallel/executor.py`: `_execute`/`_collect`/`_failed`/`_crash_error` sustituidos por la delegación en `BatchSupervisor`; `run()` gana
  `journal/control/progress/sink`; `RunResult` gana campos con valor por defecto. La publicación de datos compartidos (`publish_snapshot`) y la
  métrica de caché se conservan sin cambios.
* `parallel/worker.py`: `run_batch(batch, progress_dir=None)` (compatible), `initialize_worker(…, max_message_chars=None)` (compatible),
  `initialize_worker_supervised`, `snapshot_fingerprint` ampliada, `bound_errors`. La caché por worker y los tres modos de adjunción no se tocan.
* `parallel/shared_data.py`: **solo se añade** `scratch_directory`.
* `config/parallel_config.py` / `default_parallel.toml`: nuevo campo obligatorio `recovery` (`RecoveryConfig`); cualquier TOML de ejecución
  existente debe añadir `[parallel.recovery]`. `ParallelConfig` y los modos de datos/caché no cambian.
* `parallel/task.py`: solo `ExecutionStatus`.

## 6. Limitaciones y riesgos (los requisitos afectados quedan `PARTIAL`)

| Sev. | Limitación |
|---|---|
| **Media** | **Linux no ejecutado.** `forkserver`, detección de zombis por `/proc`, `fcntl.flock` y permisos 0700 están escritos y comprobados estáticamente (mypy) pero no corridos. `ci.yml` solo se dispara en PR/push a `main`; para validarlo basta abrir el PR (o `workflow_dispatch` sobre la rama — no se ha lanzado) |
| Media | H-1 de B4 (fragilidad numérica dependiente del CPU del runner) sigue abierto: el job Linux puede salir rojo con independencia de B5.4 |
| Media | `P-05` sigue `PARTIAL`: contrato D-04 del diario no aprobado; solo `ParallelExecutor`; las sumas protegen de corrupción accidental, no de un atacante con acceso de escritura |
| Baja | La unidad de entrega es el lote: un worker terminado (plazo, cancelación, caída) obliga a recalcular o descarta lo calculado en su lote |
| Baja | Un *kill* externo repetido `max_task_attempts` veces sobre la misma tarea queda `WORKER_CRASHED` (indistinguible de una venenosa) |
| Baja | Plazos medidos con resolución `supervision_poll_seconds` desde que el coordinador observa el inicio |
| Baja | L-4 abierta (`os.environ`: un `run()` a la vez por proceso; varios procesos coordinadores a la vez sí funcionan) y L-1 parcial |
| Info | La identidad del diario incluye el hash de todo `portfolio_engine` y las versiones de librerías: cualquier cambio de código o de versión invalida una reanudación (por diseño) |
| Info | La suite crece ≈ 6 min por las pruebas con `spawn` reales |

## 7. Instrucciones para integrar

1. Auditoría independiente de la rama (sin reutilizar los oráculos de las pruebas; ver §8).
2. Abrir un PR `block5-recovery-journal → main` **por el usuario** (no se ha hecho merge ni PR): el merge de `main` ya está incorporado (`6498f0e`),
   no se esperan conflictos.
3. Dejar correr `ci.yml` (Ubuntu 22.04 / Python 3.11): `mypy --strict`, Ruff y suite completa. Si falla solo
   `test_multi_scenario` en un runner EPYC 7763, es H-1 (preexistente); reintentar el job. Cualquier otro fallo (en especial
   `test_markers`, `test_journal`, `test_recovery`) sería un hallazgo real de B5.4 en Linux.
4. Cualquier TOML de ejecución propio debe añadir `[parallel.recovery]` (copiar de `config/default_parallel.toml`); `journal_enabled` sigue en `false`.

## 8. Puntos que debería comprobar la auditoría

* Que ninguna ruta pueda dejar una tarea sin resultado final o con dos (`_verify_exactly_once`, `RunAccounting`, cancelación y aborto).
* La condición de carrera «tarea que termina justo al vencer el plazo» (puede constar `TIMED_OUT`; documentada).
* El códec: lista blanca de tipos, ida y vuelta exacta, rechazo de documentos hostiles.
* Equivalencia `Comparison(tolerance=0.0)` del diario frente a la ejecución original en otras clases de workload y universos.
* Falsos positivos de la vigilancia de PID en Linux (`max_tasks_per_child`, zombis).
* Que ningún cambio de B5.4 altere resultados numéricos: el diff no toca B1–B4; la suite de equivalencia T1 es la evidencia.
