# REMEDIATION_BLOCK_5_4 — Remediación tras `AUDIT_BLOCK_5_4.md` (`PASS_WITH_CHANGES`)

Fecha: 2026-10-20 · Rama `block5-recovery-journal` · Commit auditado: `436a7eb5322a5cf202848d1eac646e45a5e1369e`.
Cabeza de la remediación: ver `git log` de la rama (el último commit solo añade documentación y evidencia).
Estado: **`FINAL_STATUS = READY_FOR_REAUDIT`** (todos los hallazgos tratados; límites en §4).

Restricciones respetadas: sin cambios en metodología matemática, solvers, tolerancias ni `MASTER_SPEC.md`; sin merge a `main`; B5.5 no
iniciado; sin Oracle, Arsys, producción, HERMES ni Windmill; sin datos reales.

## 1. Hallazgos y resolución

| ID | Sev. | Resolución | Pruebas de regresión |
|---|---|---|---|
| **M-1** | MEDIUM | Presupuestos **separados**. `max_total_rebuilds` cuenta solo reconstrucciones **por fallo** de workers. Las terminaciones intencionadas por plazo tienen su propia cota finita: `DEADLINE_REBUILDS_PER_TASK = 2` por tarea (cada una finaliza una tarea como `TIMED_OUT` o descompone un lote en unitarios, así que no puede haber más), con aborto limpio si se superara. Nuevo contador `RecoveryReport.deadline_rebuilds` | Unitarias (`test_supervisor.py`): `test_many_deadlines_do_not_consume_the_failure_budget_nor_abort_healthy_tasks` (4 plazos con `max_total_rebuilds=2` ⇒ 4 `TIMED_OUT`, resto `COMPLETED`, 0 `ABORTED`), `test_the_deadline_budget_is_finite_even_if_every_task_hangs`, `test_the_deadline_budget_aborts_cleanly_if_it_were_ever_exceeded`. Procesos reales (`test_recovery.py`): `test_more_deadlines_than_the_failure_budget_still_let_healthy_tasks_finish` (3 plazos, `max_total_rebuilds=1`) |
| **L-2** | LOW | El supervisor **solo termina procesos que son hijos vivos del coordinador** (`multiprocessing.active_children()`) **y** cuya hora de creación coincide con la registrada por el worker en su marca `w.<pid>.<inicio>` (Windows: `GetProcessTimes`; Linux: `starttime` de `/proc/<pid>/stat`). La vigilancia de caídas (D-DET) también compara esa identidad (PID reutilizado ⇒ «desaparecido», nunca «vivo») | `test_markers.py`: `test_a_foreign_process_is_never_terminated_even_with_a_matching_token`, `test_an_owned_child_is_terminated_only_when_identity_matches`, `test_start_tokens_identify_a_process_and_workers_register_theirs`, `test_scan_reads_tokens_and_accepts_marks_without_one`; `test_supervisor.py::test_a_reused_pid_never_gets_a_foreign_process_terminated` (marcas apuntando a un proceso ajeno **real** vivo: el supervisor lo deja vivo y la ejecución completa); Linux: `test_start_token_matches_proc_and_distinguishes_processes` |
| **L-1** | LOW | Un *shard* con suma válida pero contenido inválido se **aparta como `.corrupt`** y sus tareas se re-ejecutan; ya no bloquea la reanudación. `_read_shard` convierte cualquier fallo de lectura/decodificación en `JournalError`; el códec rechaza documentos de más de `MAX_DEPTH = 200` niveles con un recorrido **no recursivo** antes de decodificar y traduce `RecursionError`. Los resultados reales llegan a ≤ MAX_DEPTH/2 (comprobado) | `test_journal.py::test_a_shard_with_valid_checksum_but_invalid_content_is_set_aside_not_fatal` ×5 (recursión del parser JSON a 5000 niveles, profundidad 300, `ConfigError` en `__post_init__`, tipo ajeno, etiqueta desconocida); `test_codec.py`: profundidad (201 / 5000 / 50000 niveles), límite exacto aceptado, resultados reales poco profundos, dataclass inválida ⇒ error de la librería |
| **L-4** | LOW | **Documentado y con mensaje accionable** (sin valores por defecto en código: política del proyecto). `load_parallel_config` sin `[parallel.recovery]` lanza `ConfigError` que cita la sección, `config/default_parallel.toml` y «Bloque 5.4». Registrado como **cambio incompatible** en `CHANGELOG.md` y `ARCHITECTURE.md` §3.9 | `test_parallel_config.py::test_a_pre_b54_configuration_without_recovery_fails_with_an_actionable_message` |
| **L-3** | LOW | Evidencia Linux ejecutada y conservada: ver §2 | `tests/integration/test_recovery_linux.py` (7 pruebas) + paso de CI «B5.4 Linux recovery evidence» |

### Hallazgo adicional descubierto por la evidencia Linux (corregido)

| ID | Sev. | Hallazgo | Resolución |
|---|---|---|---|
| **R-1** | LOW | En Linux `events.jsonl` se creaba con `open(..., "ab")` ⇒ modo `0644` (legible por grupo y otros), contra la promesa de permisos `0600` del diario. La prueba POSIX de B5.4 solo comprobaba `*.json`, y en Windows no se ejecuta | `os.open(..., 0o600)`; la prueba POSIX ahora recorre **todos** los ficheros; la prueba Linux `test_journal_and_scratch_permissions_are_private` verificó el arreglo en el runner (falló antes, pasó después) |

## 2. L-3 — evidencia verificable en Linux

* Entorno: GitHub Actions `ubuntu-22.04`, kernel Linux 6.8.0-1070-azure, Python 3.11.17, usuario no root (`uid=1001`), Intel Xeon Platinum 8573C.
  *(Docker Desktop no arrancó en la máquina local —el servicio exige privilegios—, por lo que no se usó un contenedor local.)*
* Run **`39466030525`** (evento `pull_request`, cabeza `a2992ec…`, PR #8): **success**. Pasos: estáticos (mypy `--strict`, Ruff check y
  format) ✔; smoke de `forkserver` ✔; **B5.4 Linux recovery evidence** ✔ (**56 passed in 19,54 s**); **suite completa ✔ — `1957 passed, 2 skipped`** (4 min 10 s).
* Registro conservado en `evidence/b5_4_remediation/ci_run_39466030525.json` (metadatos de run, job, pasos y todas las anotaciones, extraídos
  de la API pública de GitHub sin autenticación; incluye la lista de pruebas pasadas). Verificable en
  `https://github.com/DarioJara/portfolio-optimization-engine/actions/runs/39466030525`.
* Cubre: `forkserver` con worker muerto a mitad de tarea + tarea venenosa (resultado ≡ secuencial T1, `WORKER_CRASHED` solo la venenosa), plazos de
  tarea bajo `forkserver` (worker terminado de verdad), reanudación de diario bajo `forkserver`; **`fcntl.flock`** entre procesos (un segundo
  coordinador recibe `JournalLockedError`; el bloqueo se libera si el titular muere); **permisos** `0700/0600` de diario y *scratch*;
  **zombis** (`kill(pid, 0)` los da por vivos; la vigilancia los trata como caídos); identidad por `starttime`; **limpieza**: sin procesos hijo
  residuales en `/proc` tras caída y plazo, aparte del servidor *forkserver* y el *resource tracker* de `multiprocessing`.
* Historia honesta de la evidencia: el primer run con el paso nuevo (`2baab54`) falló 3 pruebas (las anotaciones de ese run se truncaron a 4096 caracteres y no
  nombran las fallidas; por la lista de pasadas y por el run siguiente corresponden a los permisos de `events.jsonl` = R-1 y a dos pruebas de
  limpieza que contaban el *resource tracker* de `multiprocessing` como proceso residual: defecto de la propia prueba); el segundo (`5fc5d0b`) dejó
  2 por lo último, con la causa visible en las anotaciones (`assert [2207] == []`). Ambos runs fallidos, con sus anotaciones, siguen en la pestaña *Actions* del PR #8. Un run anterior (`26e04c2`) falló sin jobs por un
  error de YAML en el paso nuevo (corregido en `2baab54`).
* H-1 (fragilidad numérica de B4 por CPU del runner) **no se manifestó** en este run; sigue abierto.

## 3. Verificaciones locales (Windows 11, Python 3.13.6)

| Comprobación | Resultado |
|---|---|
| Suite completa en la cabeza de la remediación (`a2992ec`) | **1946 passed, 10 skipped** (22 min 07 s); 0 fallos. Los 10 skips son pruebas solo-Linux/POSIX (7 de `test_recovery_linux.py`, `test_forkserver_linux`, `/dev/shm`, permisos POSIX) |
| `mypy --strict portfolio_engine` | sin errores (176 ficheros) |
| `ruff check .` · `ruff format --check portfolio_engine tests benchmarks` | limpios |
| Equivalencia T1 | suite de equivalencia/determinismo/regresión dorada sin cambios y verde; las pruebas de recuperación comparan contra la referencia secuencial |
| Archivos de B1–B4, solvers, tolerancias, `MASTER_SPEC.md` | sin cambios (`git diff 436a7eb..HEAD --stat` solo toca `parallel/{markers,supervisor,codec,journal}.py`, `config/parallel_config.py`, tests, CI y documentación) |

## 4. Límites que permanecen (sin ocultar)

* `P-05` sigue `PARTIAL` (contrato D-04 no aprobado; solo `ParallelExecutor`; integridad contra corrupción accidental). `PAR-013` sigue `PARTIAL`
  hasta la re-auditoría. Ningún estado oficial cambia (316 `RequirementID`: 238 `VALIDATED` / 42 `PARTIAL` / 36 `NOT_IMPLEMENTED`).
* La identidad por hora de creación depende de la plataforma (Windows/Linux). En otras (macOS) solo rige la pertenencia al coordinador.
* Con L-2, un worker que **no** es hijo vivo del coordinador no se termina nunca: si un lote queda colgado en un proceso que ya no es nuestro
  hijo, el plazo no lo mata (se recoge igualmente cuando el pool se cierra). No se observó en las pruebas.
* La CI de Linux sigue sujeta a H-1 (B4) según el CPU del runner; no se relajó ninguna tolerancia ni se desactivó ninguna prueba.
* Los tiempos de recuperación siguen sin umbral ni benchmark (B5.5).

## 5. Reproducción

```bash
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider          # suite completa
.venv/Scripts/python.exe -m mypy --strict portfolio_engine
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check portfolio_engine tests benchmarks
# Linux: CI «Portfolio Engine CI» (paso «B5.4 Linux recovery evidence»); o, en Linux/WSL con Python ≥ 3.11:
python -m pytest -v -rA tests/integration/test_recovery_linux.py tests/unit/parallel/test_markers.py tests/unit/parallel/test_journal.py
```
