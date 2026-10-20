# AUDIT_BLOCK_5_4 — Auditoría independiente del Bloque 5.4

Fecha: 2026-10-20 · Rama `block5-recovery-journal` · Commit auditado `436a7eb5322a5cf202848d1eac646e45a5e1369e` (= cabeza del PR #8, verificado por la API pública de GitHub).
Entorno de reproducción: Windows 11, Python 3.13.6, `.venv` del proyecto. No se modificó código de producción, ni se hizo commit/push/merge. Sin Arsys/Oracle/SQL Server. B5.5 no iniciado.
Único fichero creado en el repositorio: este informe. Las sondas viven fuera del repo (scratchpad de la sesión).

## 0. Resultado

**`BLOCK_5_4_AUDIT_STATUS = PASS_WITH_CHANGES`**

Ningún BLOCKER ni HIGH. Las garantías centrales (una sola contabilización por `TaskID`, ausencia de pérdida/duplicación/intercambio, recuperación de caídas, tarea venenosa aislada, cotas sin bucle infinito, rechazo de reanudación incompatible sin tocar el diario, equivalencia T1) se reprodujeron. Hay 1 MEDIUM (los plazos agotan el presupuesto de reconstrucciones y dejan carteras sanas `ABORTED`) y varios LOW que conviene corregir o aceptar por escrito.

**¿B5.4 está preparado para integrarse en `main`?** **Todavía no «tal cual»**: puede integrarse cuando M-1 se corrija o se acepte explícitamente como limitación documentada (en `TRACEABILITY.md`/`REPORT_BLOCK_5_4.md`) y los LOW queden registrados. No hay regresiones de B5.3 ni de B1–B4. La decisión de merge es del usuario.

## 1. Pruebas reproducidas vs. evidencia reportada

| Origen | Evidencia |
|---|---|
| **Reproducido por esta auditoría** | `pytest` completo: **1925 passed, 3 skipped, 0 failed** (19 min 35 s) — coincide con lo reportado. `mypy --strict portfolio_engine`: sin errores (176 ficheros). `ruff check .`: limpio. `ruff format --check portfolio_engine tests benchmarks`: 350 ficheros ya formateados. Sondas propias de §2–§7. |
| **Reportado por el autor, no reproducido** | Baseline 1775 passed/2 skipped; tiempos de recuperación; que el diff no toca B1–B4 (verificado por `git diff --stat`, ver §8). |
| **Reportado por GitHub Actions (solo metadatos)** | Run 39450470100 (`Portfolio Engine CI`, evento `pull_request`, head 436a7eb): `completed / success`; job «Ubuntu / Python 3.11» (ubuntu-22.04) con todos los pasos en éxito: *Static checks*, *Linux forkserver smoke test*, *Runner CPU (diagnostic)*, *Full test suite* (≈3 min 44 s). **No se pudieron obtener los logs** (la descarga exige autenticación; `gh` no está instalado en este equipo), por lo que no se verificó el recuento de tests de Linux. |

Límite de la verificación en Linux: la evidencia de `forkserver`, `/proc`, `fcntl.flock` y permisos 0700 es únicamente «CI en verde»; esta auditoría no pudo ejecutarla.

## 2. Recuperación de workers (puntos 1, 2, 5)

Sondas propias (`probe_proc.py`, oráculo propio: multiconjunto de `PortfolioID`/`TaskID`, orden sin intercambios y comparación con la ejecución secuencial a **tolerancia 0.0**, más estricta que T1). Inyección de fallos con `tests/fixtures/faults.py` (`os._exit` dentro del worker) y con *kill* externo (`TerminateProcess` desde el coordinador).

| Sonda | Resultado |
|---|---|
| R1 — 2 tareas matan su worker una vez, workers = 1/2/3, lote 3 | 8/8 `COMPLETED`, una vez cada una, sin intercambios, **bit a bit iguales** a la ejecución secuencial; reconstrucciones 2/2/1 |
| R2 — tarea venenosa, lote 4, workers = 1/2/3 | solo la venenosa `WORKER_CRASHED`; 7 sanas `COMPLETED` e idénticas; contabilidad equilibrada |
| R3 — todas las tareas venenosas | 2 `WORKER_CRASHED` + 4 `ABORTED`, `aborted=True`, 5 reconstrucciones, 34 s: **termina, sin bucle infinito** |
| R3b — *initializer* siempre fallido (hash de snapshot manipulado) | 6 × `WORKER_INIT_FAILED`, 2 reconstrucciones |
| R3c — *initializer* que muere sin registrarse | 6 × `ABORTED`, 2 reconstrucciones |
| R5 — *kill* externo a mitad de tarea (worker elegido por su marca), workers 1/2/3 | 8/8 `COMPLETED`, exactas, 1 reconstrucción en cada caso (la detección de caída funcionó con workers creados bajo demanda) |

Lectura del código: el presupuesto de «sin progreso» cuenta solo caídas sin atribuir y venenosas consecutivas; las atribuidas están acotadas por `max_task_attempts` y `max_total_rebuilds`. La corrección F-1 del autor es coherente con lo observado. La detección tardía (D-DET) se cubre con `_check_workers` (PID registrado sin salida limpia); ver L-2 para su riesgo.

## 3. Timeouts y cancelación (punto 3)

* R6 con `max_total_rebuilds=50`, 4 tareas colgadas + 6 sanas, `task_timeout=1.5 s`: 4 × `TIMED_OUT`, 6 × `COMPLETED`.
* **R6 con `max_total_rebuilds=3`: 3 × `TIMED_OUT` y 7 × `ABORTED`, de las cuales 6 son carteras sanas.** Véase **M-1**.
* R7 — cancelación a los 7 s con diario: 2 `COMPLETED` conservadas, 8 `CANCELLED`, equilibrado; la **reanudación** restauró 2, ejecutó 8, resultado final 10/10 exacto a tolerancia 0.
* Semántica documentada y coherente con el brief: no se promete *kill* individual; se termina el proceso del worker y los lotes vecinos se recalculan (trabajo repetido, no resultados perdidos).

## 4. Diario: corrupción, truncamiento, recuperación, compatibilidad (punto 4)

Sondas propias (`probe_journal.py`, API pública de `RunJournal`):

| Caso | Resultado |
|---|---|
| Ida y vuelta de 5 resultados | exacta a tolerancia 0.0 |
| Shard truncado a 0, 10, ½ y N−1 bytes | detectado, apartado como `.corrupt`, 4/5 tareas conservadas, la 5.ª se reejecuta |
| Un byte alterado | ídem |
| Manifiesto truncado / alterado / vacío | `JournalError` (no se acepta) |
| Reanudar con distinto `request_set_hash`, `config_hash`, `snapshot_key`, `code_hash`, `n_tasks`, `python_version`, `format_version` o versiones de librería | `JournalIncompatibleError` en los 8 casos; **hash del árbol de ficheros idéntico antes/después** |
| Shard con el resultado de B bajo el `task_id` de A (suma válida) | rechazado (`task_id` del resultado ≠ registro) |
| Tarea duplicada en dos shards | se conserva la primera; `duplicate_tasks=1` |
| Segunda apertura simultánea | `JournalLockedError` |
| Crear sobre un diario existente | `JournalError` |
| Temporales huérfanos | eliminados al abrir |
| Último evento truncado | `inspect_journal` lo cuenta como inválido sin fallar |
| Contenido | no aparecen `current_weights` ni `password` en el diario (solo resultados y `PortfolioID`) |

Hallazgos del códec/diario con **checksum válido pero contenido hostil o inválido**: ver L-1.

## 5. Permisos, seguridad de temporales, archivos y recursos compartidos (punto 6)

* `pickle`: la prueba de arquitectura nueva prohíbe `pickle.load` fuera de los dos módulos preexistentes; el diario y el códec no lo importan. El códec resuelve tipos solo dentro de `portfolio_engine` y solo dataclasses/enums; sondeé que **ninguna dataclass ajena** (stdlib) es alcanzable por el espacio de nombres del paquete (0 casos).
* Escritura atómica con `O_EXCL`, `fsync` y `os.replace`; modo 0700/0600 en POSIX; en Windows se heredan las ACL del padre (documentado). No se verificó 0700 en Linux (solo CI).
* El *scratch* de ejecución lleva `owner.json` y se barre como huérfano; R9/L-2 muestra un riesgo de las marcas.
* Eventos del diario y mensajes sintéticos acotados por `max_message_chars`; los eventos no llevan datos de cartera.

## 6. Equivalencia T1 y estados de solver (punto 7)

* Todas las sondas con workers reales comparan con la ejecución secuencial a **tolerancia 0.0** y pasan. La suite de equivalencia existente (`test_parallel_equivalence`, `test_determinism`, `test_shared_data_equivalence`, regresión dorada) pasa sin cambios.
* `git diff 6498f0e HEAD --stat` no toca motores, solvers ni tolerancias de B1–B4. `ExecutionStatus` queda separado de `SolverStatus`; la prueba `test_a_solver_time_limit_is_a_solver_status_not_an_execution_failure` pasa.

## 7. Regresiones B5.3 y fallos intermitentes B4 (punto 10)

* Suite completa verde, incluida toda la suite de B5.3 (caché por worker, memoria compartida): **0 regresiones**.
* Cinco pruebas de B5.2 se reescribieron por el cambio de semántica (F-4 del autor: ya no «todos los lotes en vuelo → `WORKER_CRASHED`»). Es un cambio de contrato intencionado y coherente con el brief, pero debe constar en la revisión humana del PR.
* **Fallo numérico intermitente de B4 (H-1, `test_multi_scenario`, dependiente del CPU del runner): no se manifestó** en ninguna de las dos ejecuciones (local ni CI). Sigue abierto y es independiente de B5.4.

## 8. Hallazgos

| ID | Sev. | Hallazgo | Evidencia | Remediación propuesta |
|---|---|---|---|---|
| **M-1** | **MEDIUM** | Cada plazo vencido (tarea/lote) termina el pool y consume una reconstrucción de `max_total_rebuilds` (`_apply_limits`: `rebuilds >= max_total_rebuilds` con pendientes). Con N tareas lentas legítimas se agota el presupuesto y **carteras sanas pasan a `ABORTED`** (incluso una tarea que habría acabado `TIMED_OUT`). Contradice el espíritu de «no atribuir culpa a carteras sanas» (aunque `ABORTED` se documenta como reintentable) y cada plazo cuesta ≈ un respawn completo del pool (≈ 5 s por worker en Windows). | R6: `max_total_rebuilds=3` → 3 `TIMED_OUT` + 7 `ABORTED` (6 sanas); con 50 → 4 `TIMED_OUT` + 6 `COMPLETED`. | No contar las reconstrucciones intencionadas (`_intentional`) contra `max_total_rebuilds` (o darles presupuesto propio acotado por nº de tareas); añadir prueba con más plazos que el presupuesto. Alternativa mínima: documentar el comportamiento y el valor por defecto como riesgo en `TRACEABILITY.md`. |
| L-1 | LOW | `_read_shard` solo captura `OSError/ValueError/KeyError/TypeError/CodecError`. Un shard con suma válida pero (a) anidamiento profundo → `RecursionError`, o (b) una dataclass cuyo `__post_init__` lanza `ConfigError` (`PortfolioEngineError`), **hace fallar toda la reanudación** en lugar de apartarse como `.corrupt`, y vuelve a fallar en cada intento hasta intervención manual. El docstring afirma rechazo de documentos hostiles; es parcial. Requiere un diario modificado por quien recalcule la suma (fuera del modelo de amenaza documentado) o un bug de codificación. | `probe_journal.py` J4 (profundidad 1100/5000 → `RecursionError`) y J5 (`ConfigError`); `probe_codec.py` A2/A3. | Capturar `PortfolioEngineError` y `RecursionError` en `_read_shard`/`decode` (o limitar profundidad) y tratarlos como shard corrupto; test de regresión. |
| L-2 | LOW | `_terminate_pool` mata todos los PID de marcas `w.<pid>` / `t.*.<pid>` sin verificar que sigan siendo workers del pool. Si un worker murió y su PID fue reutilizado por un proceso ajeno antes de la recuperación (Windows recicla PID con rapidez), el supervisor terminaría un proceso ajeno. Ventana corta, pero el efecto es grave si ocurre. | R9: un proceso ajeno con marca `w.<pid>` fue terminado (exit 15). | Limitar la terminación a los hijos reales del coordinador (p. ej. `psutil.Process().children()` o comparar hora de creación guardada en la marca) y no terminar PID cuya marca sea de un proceso ya desaparecido. |
| L-3 | LOW | Evidencia Linux solo vía CI (metadatos); sin logs ni recuento de tests; `forkserver`, `/proc` zombi, `flock`, 0700 no ejecutados en esta auditoría. | §1. | Adjuntar el log del job al cierre, o ejecutar la suite en Linux/WSL; mantener el requisito `PARTIAL` hasta entonces (el autor ya lo hace). |
| L-4 | LOW | `RecoveryConfig` es campo obligatorio: cualquier TOML de ejecución existente sin `[parallel.recovery]` deja de cargar (ruptura de configuración, documentada en el informe §7). | Diff de `parallel_config.py`. | Anotar en `CHANGELOG.md` como cambio incompatible, o aportar valores por defecto. |
| INFO-1 | INFO | La identidad del diario incluye el hash de todo `portfolio_engine`: cualquier cambio de código invalida reanudaciones (por diseño; muy estricto, sin riesgo). | `journal.code_hash`. | — |
| INFO-2 | INFO | Condición de carrera «tarea que termina justo al vencer el plazo» (puede constar `TIMED_OUT`) y resolución = `supervision_poll_seconds`; documentadas por el autor. | Docstring del supervisor. | — |
| INFO-3 | INFO | Unidad de entrega = lote: un worker terminado descarta lo calculado en su lote (se recalcula). Documentado. | R6/R7. | — |

## 9. Estado de requisitos (opinión de auditoría)

Coincido con los estados del autor: `PAR-011`, `P-01`, `P-03`, `P-04`, `P-06`, `P-07`, `P-08` quedan sustentados por pruebas reproducidas en Windows; `P-05` debe mantenerse `PARTIAL` (contrato D-04 no aprobado; L-1 abierto). Ninguno debería pasar a `VALIDATED` en Linux sin los logs de L-3. Conviene que `TRACEABILITY.md` recoja M-1 y L-1/L-2.

## 10. Reproducción

```bash
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --no-header -rf
.venv/Scripts/python.exe -m mypy --strict portfolio_engine
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check portfolio_engine tests benchmarks
# sondas (fuera del repo; requieren PYTHONPATH=. en la raíz del proyecto):
#   probe_codec.py, probe_journal.py  -> A1–A5, J0–J13
#   probe_proc.py R1 R2 R3 R5 R6 R7 R9 -> pools reales (≈ 8 min)
```

Nota de proceso: al relanzar la suite sin `-x` se terminaron todos los `python.exe` del equipo (solo había mi `pytest` anterior); no afectó al repositorio.

**BLOCK_5_4_AUDIT_STATUS = PASS_WITH_CHANGES**
