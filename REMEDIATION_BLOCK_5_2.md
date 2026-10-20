# REMEDIATION_BLOCK_5_2 — Remediación limitada tras `AUDIT_BLOCK_5_2.md`

Fecha: 2026-10-20. Rama `block5-hpc-architecture` (HEAD `271eaeb`, **sin commit**). Alcance autorizado: condiciones de
integración de B5.2 (documentación, pruebas de fallo, estados de trazabilidad). No se inició B5.3; no se modificó
`MASTER_SPEC.md`, ni algoritmos o tolerancias de B1–B4, ni la lógica de producción de `parallel/` (solo docstrings). No se
ejecutaron benchmarks masivos ni se accedió a Arsys/Oracle/SQL Server; sin commit/push/PR/merge/tag.

## 1. Hallazgos y tratamiento

| Hallazgo | Tratamiento | Estado |
|---|---|---|
| H-1 (HIGH) `WORKER_CRASHED` afecta a todos los lotes en vuelo | `CHANGELOG.md`, `ARCHITECTURE.md` §3.7, docstring de `executor.py`, `README.md` y `BLOCK_5_IMPLEMENTATION_PLAN.md` (P-06) corregidos. Semántica fijada por pruebas (§2) | Remediado |
| M-1 (MEDIUM) fallo determinista del *initializer* sin corte; `submit` sin proteger | Sin cambio de lógica (alcance limitado); deuda trazable en `ARCHITECTURE.md` §3.7 | Pendiente B5.4 |
| M-2 (MEDIUM) `STRATEGY_ROBUST` sin `mu_set` explícito | Documentado como capacidad pendiente del `WorkloadSpec` (docstring de `workload.py`, `ARCHITECTURE.md`, nota en `GOV-012`); motor robusto intacto | Documentado; B5.3/B5.4 |
| M-3 (MEDIUM) `FORKSERVER` sin prueba | Rotulado **NO VALIDADO** frente a `SPAWN` probado solo en Windows (TOML de ejemplo, docstring de `ProcessStartMethod`, `README.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `TRACEABILITY.md` CFG-011/PAR-013). Sin declaración de compatibilidad Linux | Documentado; CI Linux pendiente |
| M-4 (MEDIUM) PAR-013 `VALIDATED` optimista | **PAR-013 → `PARTIAL`** (dependencia PAR-004 sin implementar, `FORKSERVER` sin validar, M-1). Recuentos recalculados desde las filas: 230 `VALIDATED`, 44 `PARTIAL`, 42 `NOT_IMPLEMENTED`, 0 `IMPLEMENTED` (316) | Remediado |
| L-1…L-3 | Deuda trazable en `ARCHITECTURE.md` §3.7 (B5.3/B5.4) | Pendiente |
| L-4 | Documentado: un `ParallelExecutor.run` a la vez por proceso | Documentado |
| L-5 | Docstring de `parallel/__init__.py` actualizado; README con la convención de rutas Windows/Linux, `threadpoolctl` y comando de benchmark independiente de plataforma | Remediado |

## 2. Pruebas de caída (`tests/unit/parallel/test_executor.py`)

* `test_a_crash_mid_task_marks_every_in_flight_batch_as_worker_crashed` (2 casos: lotes de 1 y de 2): 2 workers, una cartera
  mata su worker mientras otra cartera sana corre en el otro (sincronización por ficheros-bandera con plazo; sin esperas por
  tiempo). Verifica que ambas quedan `WORKER_CRASHED` sin operaciones, que las no enviadas se completan en el pool
  reconstruido con resultados idénticos a la referencia secuencial (T1) y que no quedan procesos vivos.
* `test_a_crash_without_warm_up_keeps_exactly_once_and_bounded_damage`: solo invariantes (una salida por cartera en
  orden canónico, culpable perdida, daño acotado por los lotes en vuelo, `COMPLETED` ≡ referencia).
* **Hallazgo durante la remediación.** La versión previa de la primera prueba **fallaba de forma reproducible** (4 de 4
  ejecuciones, ~135 s cada una): con `ProcessPoolExecutor` en Windows / CPython 3.13.6 la caída del último worker creado
  bajo demanda puede detectarse tarde (el hilo gestor fija su lista de *sentinels* antes de que ese worker exista); mientras
  tanto el vecino sano completa con normalidad y se pierde un lote enviado después. Sondas con pool estándar e instrumentado
  mostraron resultados distintos entre ejecuciones idénticas. Corrección **solo en la prueba**: la primera prueba crea todos
  los workers y espera un resultado de cada uno antes de enviar trabajo (`warm_up`), lo que hace la detección inmediata y el
  resultado determinista; la segunda prueba, sin calentamiento, fija los invariantes. Estabilidad: las 3 pruebas de caída
  pasaron 5 de 5 ejecuciones consecutivas (~50 s cada una) y en la suite completa final.
* Semántica documentada: «los lotes en vuelo **en el momento en que el pool detecta la caída**». El ejecutor de producción no
  calienta el pool: deuda D-DET para B5.4 (calentar el pool o vigilar los procesos, con prueba).

## 3. Archivos modificados en esta remediación

`CHANGELOG.md`, `ARCHITECTURE.md`, `README.md`, `TRACEABILITY.md`, `BLOCK_5_IMPLEMENTATION_PLAN.md`,
`config/default_parallel.toml` (comentario), `portfolio_engine/config/parallel_config.py` (docstring),
`portfolio_engine/parallel/{__init__,executor,workload}.py` (solo docstrings), `tests/unit/parallel/test_executor.py`
(prueba de caída con calentamiento y prueba de invariantes) y este informe. `AUDIT_BLOCK_5_2.md` no se altera.

## 4. Verificación (ejecutada)

`pytest -q` completo: **1668 passed**, 0 failed, 0 omitidos (654 s). `mypy --strict portfolio_engine`: sin errores (165
ficheros). `ruff check .`: limpio. `ruff format --check .`: 342 ficheros formateados. `git diff --check`: sin errores de
espacios (avisos LF/CRLF). Una ejecución completa intermedia, anterior a la corrección de la prueba de caída, dio
2 fallos (las dos variantes de la prueba de caída) y 1665 aciertos; se corrigió la prueba y se repitió el gate completo.

## 5. Pendiente para integrar y para B5.3/B5.4

Sin cambios de código obligatorios. Antes de apoyarse en `FORKSERVER` o en cifras de rendimiento: ejecutar la suite en
Ubuntu 22.04 + Python ≥ 3.11 y amortizar el arranque del pool. B5.4: reintento/cuarentena (P-06), corte de reconstrucciones
sin progreso (M-1), detección inmediata de caídas (D-DET), truncado de mensajes (L-2). B5.3: huella ampliada (L-1), tipo
serializable de incertidumbre de `μ` (M-2).
