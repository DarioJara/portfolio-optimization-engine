# Auditoría independiente — Bloque 5.3 (datos compartidos y caché)

Rama `block5-shared-memory-cache`, commit `ff835d052715a524a70535d5de5f21d4e79c3726` (= `d3ecd53` + solo documentación).
Base `539d4b7`. Auditor: revisión independiente asistida (código leído completo: `shared_data.py`, `operation_cache.py`,
`cache/*`, diffs de `worker/executor/task/workload/parallel_config`). No se modificó código de producción, no hay merge,
no se inició B5.4, el workflow temporal **no** se ha borrado. Los scripts de sonda viven fuera del repositorio.

**BLOCK_5_3_AUDIT_STATUS = PASS_WITH_CHANGES**

## 1. Pruebas reproducidas vs. reportadas

### Reproducidas por el auditor (Windows 11, Python 3.13.6, numpy 2.5.3, scipy 1.18.1, `.venv` del repo)

| Prueba | Resultado |
|---|---|
| `pytest -q` (suite completa) | **1757 passed, 2 skipped** (845 s). Skips: forkserver y `/dev/shm` (solo Linux). Coincide con lo reportado |
| Conjunto B5.3 (equivalencia, shared_data, cache, operation_cache) | 73 passed, 1 skipped |
| `mypy --strict portfolio_engine` / `ruff check .` / `ruff format --check .` | limpios (170 / – / 358 ficheros) |
| Diff frente a `539d4b7` | solo `parallel/`, `cache/`, `config/` (+`pyproject`, lock, benchmarks, tests, docs). `MASTER_SPEC.md`, solvers, `engine_config`, `config/hashing` intactos |
| Benchmark `shared_data_cache.py --universe 50 500 --workers 1 2 4 --repetitions 2` | 18 celdas, **T1 = 0 en todas**, 160 puntos válidos/celda, referencia 228/559/504 B; E8 k=4: 1056→264 llamadas, 36 aciertos (JSON en el scratchpad de la sesión; no se añadió al repo) |
| Sonda: 100 ciclos publicar/adjuntar/destruir × 3 modos (mitad con excepción) | 0 residuos |
| Sonda: matar (`kill`) un coordinador publicado, ×3 modos | inventario lo marca huérfano; `remove_orphans` lo elimina; 0 residuos |
| Sonda: cabecera/manifiesto/datos truncados o alterados (FILE_MMAP, SHARED_MEMORY) | rechazados antes de deserializar (fichero de datos vacío da `ValueError`, no `SharedDataError`: cosmético) |
| Sonda: arrays de los 3 modos | `writeable=False`, `setflags(write=True)` y escritura fallan |
| Sonda: referencia con N = 50/500/2000 | 240/593/526 B máx., constante, < 2 KB |
| Sonda: W2 (multiescenario, no incluida en la suite de equivalencia) × 3 modos × caché on/off | 24 combinaciones, 0 diferencias T1, estados iguales, 0 residuos |
| Sonda: claves de caché, un ulp en Σ / costes compra / costes venta / retornos, `eps_abs`, `nav`, `target_portfolio_size`, `investment_universe`, `max_turnover`, `volatility_limit`, `weight_bound_overrides` | cada cambio altera la clave (componentes esperados) |
| Sonda: hit = objeto nuevo, bitwise igual (pickle) al original, sin memoria compartida; el comparador T1 detecta una perturbación de 1e-3 | OK |

### Reportadas, **no reproducidas** (Linux)
Docker Desktop (autorizado por el usuario) no arrancó (error del backend), y no hay distro WSL. Por tanto **forkserver, `/dev/shm`,
Python 3.11 y los 2 tests B4 en Linux no se han reproducido localmente.** Se contrastaron de forma independiente las anotaciones públicas
de la API de GitHub Actions (no el resumen del autor):

| Run | Commit | Job | CPU del runner | Resultado |
|---|---|---|---|---|
| 39407952385 / 39408612070 | dfc9c69 / a600ae0 | suite | EPYC 7763 | 2 fallos B4 |
| 39409385018 | 7d4632a | suite | EPYC 9V45 | pasa |
| ídem | 539d4b7 (main) / rama | sonda ×12 | EPYC 9V74 / Xeon 6973P | **0/12** / 12/12 |
| 39414610396 | d3ecd53 | suite | EPYC 9V45 | 1762 passed |
| ídem | main / rama | sonda ×12 | EPYC 7763 / Xeon 8573C | **0/12** / 12/12 |
| **39415376791** | **ff835d0 (auditado)** | **suite** | **EPYC 7763** | **2 failed, 1760 passed** |
| ídem | main / rama | sonda ×12 | EPYC 9V74 / EPYC 7763 | **12/12** / **0/12** |
| 39415881644 | ff835d0 | `ci.yml` permanente | no registrada | success |

## 2. Hallazgos B4 intermitentes (punto 5)

Tests: `test_single_solutions_satisfy_the_constraints_of_every_scenario` (`is_valid_solution` falso en la solución WORST_CASE) y
`test_worst_case_maximizes_the_minimum_scenario_utility` (falla el oráculo SLSQP del propio test: «Positive directional derivative»).

Evidencia (no se atribuye la causa):
1. **No es regresión de B5.3**: `539d4b7` falla 0/12 en EPYC 7763 y la rama falla 0/12 en la misma CPU. Los módulos que cargan esos tests difieren de la base solo en `config/__init__.py` y `config/parallel_config.py` (alta de `SharedDataMode`/`CacheConfig`); `parallel/` y `cache/` ni se importan.
2. **La CPU no lo explica por sí sola**: `539d4b7` en EPYC 9V74 dio 0/12 en un run y 12/12 en otro. La narrativa del CHANGELOG («main 0/12, rama 12/12») es una coincidencia de runners; el run posterior sobre el commit auditado la invierte.
3. **Matriz local controlada** (mismo equipo, intérprete y dependencias, base vs. rama, 4 repeticiones; kernel OpenBLAS forzado): Haswell (defecto), Sandybridge, Nehalem, Katmai → 4/4 en ambos árboles; SkylakeX → *Illegal instruction* en ambos (la CPU local no tiene AVX-512). **No se reprodujo el fallo** y base y rama se comportan igual.
4. Causa: **indeterminada**. Se sabe que depende del runner y no del código; falta el detalle de `solution.validation.checks` en el runner que falla.

## 3. Hallazgos por severidad

**BLOCKER: ninguno.**

### HIGH (preexistente, fuera del alcance de B5.3; no bloquea su integración)
**H-1. Fragilidad numérica B4 dependiente del hardware** (sección 2). Un solver cónico/validador marca inválida una solución WORST_CASE en algunas CPU; la CI permanente (`ci.yml`, runner sin CPU fijada) pasará o fallará según el sorteo del runner, también para B5.4.
Remediación: (a) añadir en CI un paso de diagnóstico que imprima `validation.checks` fallidos, estado, iteraciones de Clarabel y `lscpu`; (b) en un runner EPYC 7763 repetir con `OPENBLAS_CORETYPE`/`RAYON_NUM_THREADS=1` para aislar BLAS/Clarabel; (c) abrir una remediación B4 independiente (tolerancia de validación relativa o repulido, y oráculo SLSQP robusto, p. ej. `trust-constr`), sin tocar tolerancias dentro de B5.3; (d) hasta entonces, política de CI: un fallo exacto de esos dos tests se re-ejecuta y se registra, nunca se enmascara.

### MEDIUM (cambios obligatorios antes de integrar)
**M-1. `_statuses_final` ignora `GlobalFrontierResult.continuous`** (`operation_cache.py:129-132`). `continuous` no es parte de `composition_results` (verificado por identidad): una frontera continua con un punto `MAX_ITERATIONS` se cachearía, incumpliendo la afirmación 8. Reproducido sustituyendo estados en `continuous`. Remediación: comprobar `result.continuous` (si no es `None`) y añadir el test.
**M-2. `pid_alive` en Windows trata «acceso denegado» como proceso muerto** (`shared_data.py:393-405`). `OpenProcess` falla con error 5 para procesos privilegiados vivos; reproducido: un run dir cuyo propietario es un proceso vivo privilegiado se lista como huérfano y `remove_orphans` lo borraría (relevante con `root` compartido o coordinador elevado). Remediación: `GetLastError()==5` ⇒ vivo; solo `ERROR_INVALID_PARAMETER (87)` ⇒ muerto; test con PID 4.
**M-3. Evidencia documental de Linux incompleta.** CHANGELOG/TRACEABILITY citan el run 39414610396 (d3ecd53) y presentan «main 0/12 vs rama 12/12», pero omiten el run 39415376791 sobre el commit auditado (suite **fallida**, sonda invertida) y el hecho de que la suite pasó solo en runners donde la base también pasa. Remediación: documentar los 3 runs fallidos de la suite, la tabla completa de CPU y retirar la comparación sesgada. `AUDIT_REQUEST` dice «no hay PR»: existe el PR #7 en borrador (sin merge; aceptable, corregir el texto).
**M-4. Faltan dos pruebas de aceptación del plan para PAR-004**: «ninguna fuga tras 100 iteraciones» y «sin residuos tras kill del coordinador». Funcionalmente pasan (sondas del auditor), pero la regla de estado exige test de aceptación en el repo. Remediación: incorporar ambas sondas (≈40 líneas) como tests.

### LOW
- **L-1** Integridad solo en el momento de adjuntar: el fichero `FILE_MMAP` sigue siendo escribible por el mismo usuario; reproducido que una escritura posterior altera los retornos y que solo `μ/Σ` se detectan (fingerprint, L-1 ya abierto para B5.4); en POSIX un truncamiento posterior puede dar SIGBUS. Mitigar ampliando la huella o marcándolo solo-lectura; documentar el límite de confianza (mismo usuario).
- **L-2** Si falla la publicación tras crear el segmento (`_publish_out_of_band`), `segment` no llega a `publish_snapshot` y no se hace `unlink`. En Windows se libera al recolectar (verificado); en Linux persiste hasta el fin del proceso (por lectura de código, no reproducido). Envolver con `try/except` + `unlink`.
- **L-3** `_remove_tree` devuelve `False` si no consigue borrar y el resultado se ignora: fuga silenciosa. Registrar/advertir y exponerlo en `RunResult`.
- **L-4** `SHARED_MEMORY` sin comprobar capacidad de `/dev/shm` (64 MB por defecto en Docker): riesgo de SIGBUS (plausible, no reproducido). Pre-chequeo y degradación a `FILE_MMAP`.
- **L-5** `inventory_orphans` en Linux filtra `pe_<pid>_…` en `/dev/shm`: prefijo genérico y espacios de PID de contenedores; riesgo de borrar segmentos ajenos con `remove_orphans` (acción explícita). Prefijo más específico + `owner.json` también para segmentos.
- **L-6** La suite de equivalencia por modo excluye W2; añadir (las sondas ya pasan). Constantes operativas (`REMOVE_RETRIES`, `REMOVE_DELAY_SECONDS`) hardcodeadas: llevarlas a configuración o documentarlas como infraestructura.
- **L-7** El JSON de benchmark del repo fue generado con `e00762e+dirty`, no con un commit reproducible; regenerar con árbol limpio.
- **L-8** `OPTIMAL_INACCURATE` se considera definitivo y se cachea (determinista; decisión a documentar).

## 4. Respuesta a los puntos de la solicitud

1. **Implementación**: BUNDLE_FILE, FILE_MMAP y SHARED_MEMORY verificadas en Windows (spawn) con T1 = 0.
2. **Integridad/aislamiento/limpieza/corrupción**: cadena hash handle→cabecera/manifiesto→buffers correcta; directorio con ACL restringida en Windows (SYSTEM/Administradores/propietario); POSIX (0700/0600) por comportamiento estándar de CPython, no reproducido. Limpieza correcta en éxito, excepción, caída de worker y kill del coordinador. Hallazgos M-2, L-1…L-5.
3. **CacheKey**: los 10 componentes oficiales presentes (+`portfolio_id`, `operation_hash`, `snapshot_key`); `CurrentPortfolioStateHash` siempre; sin reutilización entre carteras. Desviación documentada: `ConstraintHash` = hash de **entradas** (ARCHITECTURE E-14, no enmienda de `MASTER_SPEC`); recomendable formalizarla como enmienda.
4. **Equivalencia T1/caché/memoria/regresión**: reproducida (secciones 1). Hit = 0 llamadas al solver (tests + E8).
6. **Windows vs Linux**: ver tablas; Linux no reproducido.
7. **Benchmarks**: coinciden con el CHANGELOG. Ahorro real de memoria pequeño: ≈ 3 MB de ≈ 116 MB por worker con N = 500 (≈ 3 %), ruido con N = 50; USS excluye páginas compartidas, así que el ahorro agregado es ≈ (W−1)×tamaño de los datos. Sin ventaja de arranque (≈ 6–9 s dominado por `import`); adjuntar cuesta +10–60 ms por la verificación hash. Mantener `BUNDLE_FILE` por defecto está justificado. Sin extrapolación a producción; Σ_s múltiples y 22.000 carteras sin medir.
8. **Clasificación**: PAR-004, PAR-005, CCH-001…005, CFG-011 `VALIDATED` aceptable **condicionado a M-1 y M-4** (CCH-001/003/005 por M-1 en el alcance global; PAR-004 por M-4). PAR-013 y BEN-004 `PARTIAL` correctos. Recuento 316 = 238/42/36 verificado.

## 5. Correcciones

**Obligatorias antes de integrar**: M-1, M-2, M-3, M-4; y **eliminar `.github/workflows/b53-branch-ci.yml`** una vez archivada su evidencia (ya verificada aquí).
**Recomendadas**: L-1…L-8; abrir remediación B4 por H-1; reproducir en Linux real (forkserver, `/dev/shm`, Python 3.13 `track=False`) cuando haya entorno.

## 6. Veredicto de integración

B5.3 **puede integrarse en `main` tras aplicar M-1…M-4** y re-ejecutar suite, mypy y ruff. No introduce regresión demostrable; el fallo de CI en Linux es preexistente y dependiente del runner (incertidumbre documentada, causa no determinada). Los logs y anotaciones consultados están en la API pública de Actions (runs listados arriba).

BLOCK_5_3_AUDIT_STATUS = **PASS_WITH_CHANGES**
