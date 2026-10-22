# REMEDIATION_BLOCK_5_5 — Cierre de B5.5 tras `AUDIT_BLOCK_5_5.md` (`PASS_WITH_CHANGES`)

Fecha: 2026-10-22. Rama `block5-benchmarks-final-audit`, PR #9. Base de la integración: `main` `75d8bb5` (PR #10: remediación numérica de H-1 y F-B55-1,
`REMEDIATION_H1_FB551.md`). Sin merge, sin cambios directos en `main`, sin cargas de ≥ 1.000 carteras, sin Arsys/Oracle/SQL Server, sin datos reales.
**`BLOCK_5_5_STATUS = READY_FOR_FINAL_AUDIT`** (justificación en §9).

## 1. Qué se hizo, en orden

| Paso | Resultado |
|---|---|
| Integrar `main` | `git merge origin/main` (no *rebase*: se conserva el historial publicado del PR). Conflictos solo en `CHANGELOG.md` y `TRACEABILITY.md` (ambos lados añadían entradas al final): se conservan las dos; la entrada de B5.5 se reañade tras las de `main`. Los ficheros sin versionar del propietario coincidentes con los de `main` (`AUDIT_H1_FB551.md`, `evidence/audit_h1_fb551/`) se apartaron antes de fusionar y quedan los versionados de `main`. Cero conflictos de código |
| `conic.retry_equilibrate = false` | Ya viene en `config/default_engine.toml` de `main` y la carga es estricta (clave obligatoria); todos los benchmarks y tests de B5.5 leen esa configuración (`tests/fixtures/problems.py::base_config`). No existe otro TOML de motor en B5.5. `config/default_benchmark.toml` es configuración de **medida**, fuera del `config_hash` |
| `config_hash` del motor | `5d3cdc5e…3630` (B5.5 antes de integrar) → **`86af211e…d775`** (solo por la clave nueva: cargar la configuración antigua con `retry_equilibrate = false` da exactamente el hash nuevo). Los resultados anteriores conservan su hash como registro de la configuración con la que se midieron |
| Regeneración | Referencia multiplataforma, baselines de rendimiento (trabajo y tiempos), sonda H-1 y lote `ENG-MIX-BASE` 10/100 regenerados **sobre árbol limpio** con el hash nuevo (`benchmarks/results/*postmerge*`, `…/baselines/*`, `h1_numerical_probe_20261022T*`) |
| Cambios numéricos y de composiciones | **Ninguno en esta CPU** (§2). El cambio de F-B55-1 solo existe en las CPU con núcleo OpenBLAS `SkylakeX` (§3) |
| `xfail` de F-B55-1 | **Retirado.** Prueba por cartera sin marcas + prueba de subproceso que fuerza cada núcleo (§3) |
| A-03, A-04, A-05, A-06, A-07 | Corregidos (§5–§8) |
| A-01, A-02 | Revisados con la rama integrada (§3, §4) |
| Requisitos | Revisados todos los `PARTIAL` y `VALIDATED` afectados (§8) |
| Verificación | Suite completa de Windows, `mypy --strict`, Ruff y CI de Linux sobre el PR (§9) |

## 2. Efecto numérico de la integración (medido)

| Comprobación | Resultado |
|---|---|
| Huella de referencia (10 carteras, 565 soluciones) antes y después | **Bit a bit idéntica** en las 10 carteras (pesos, estados, nº de soluciones y de composiciones: W1 = 11 composiciones/240 soluciones) |
| Contadores de trabajo `ENG-MIX-BASE` (10 y 100 carteras), mismo `snapshot_key` | **Idénticos**: 72.728 / 688.707 iteraciones, 652 / 6.404 llamadas al solver, 28 / 292 fronteras |
| Contadores de las 7 celdas de referencia de rendimiento | Idénticos a los de Windows previos (W1: 484 llamadas, 46.934 iteraciones) |
| Sonda H-1 (`h1_numerical_probe.py`, 100 resoluciones por celda, tolerancia cónica **configurada 1e-9**) | Validez **1,00 en todas las perturbaciones** (antes de la integración: 1,00 / 0,47 / 0,35 / 0,35 / 0,37 / 0,05 para `eps` 0 / 1e-16 / 1e-15 / 1e-14 / 1e-12 / 1e-10). Con perturbación, 47–95 % de las resoluciones terminan `OPTIMAL` por la ruta del reintento (`status_source = CROSS_CHECK`) con 18–19 iteraciones, en vez de `OPTIMAL_INACCURATE` |
| Estados no óptimos aceptados | Ninguno: el reintento conserva sus propias tolerancias (las configuradas) y su estado; no se promueve nada |

Interpretación: en esta CPU (núcleo `Haswell`) el primer intento ya terminaba `OPTIMAL` sin perturbar, así que la corrección no cambia ningún resultado; solo actúa cuando el primer
intento se estanca, y entonces el resultado válido deja de depender del ulp. Esto es lo que debía comprobarse al regenerar los baselines: **ningún baseline de B5.5 cambia de valor**; lo único que
se actualiza es el registro del hash y de la procedencia.

## 3. F-B55-1: de «dependiente de la plataforma» a «dependiente del núcleo BLAS», y cierre

`AUDIT_BLOCK_5_5.md` A-02 desmintió la atribución a la plataforma (el EPYC 7763 daba el resultado de Windows) y `REMEDIATION_H1_FB551.md` §4 demostró por intervención que el factor es el **núcleo de OpenBLAS**
(`SkylakeX` → 12 composiciones; `Haswell` → 11), no el SO ni el fabricante, y que la causa es el empate sensible a ulps de `rank_nodes`, corregido en `main`. Este PR retira lo que dependía de la lectura errónea.

| Elemento | Antes | Ahora |
|---|---|---|
| `xfail` no estricto «solo fuera de Windows» | Absorbía regresiones y daba `XPASS` silencioso | **Eliminado**. `test_each_portfolio_matches_the_committed_fingerprint[…]` falla ante cualquier divergencia de las 10 carteras (T1, estados de puntos y de estrategias, nº de soluciones y de activos) y muestra el núcleo cargado |
| Equivalencia entre CPU | Dependía del sorteo del runner | `test_forcing_each_openblas_kernel_gives_the_same_fingerprint[Haswell|SkylakeX]` ejecuta la huella en un subproceso con `OPENBLAS_CORETYPE` forzado y comprueba que el núcleo cargado es el pedido; `SkylakeX` solo se puede forzar con AVX-512 (si no, se omite y **no cuenta como validación**) |
| Composiciones de la cartera W1 | 11 o 12 | `test_the_w1_candidate_set_is_the_same_composition_count_as_the_reference`: 11 siempre |
| Baseline de trabajo | Dos variantes (484 / 506) | Una (484); el formato de variantes se conserva por si aparece una nueva, que haría fallar la prueba |
| Paso de CI «B5.5 OpenBLAS kernel matrix» | — | En cada ejecución: huella + tests de H-1, de desempate y de multiescenario con el núcleo nativo, `Haswell` y, si hay AVX-512, `SkylakeX`; falla el paso si algo falla |

Evidencia real (CI del PR, run `39774545136`, `0be043a`, Intel Xeon Platinum 8573C, núcleos `SkylakeX`, Python 3.11.17):

| Núcleo | Huella de referencia (Windows) | H-1 + desempate + multiescenario |
|---|---|---|
| nativo = `SkylakeX` | **0 divergencias** | 33 passed |
| `Haswell` forzado | **0 divergencias** | 33 passed |
| `SkylakeX` forzado | **0 divergencias** | 33 passed |

y contador de trabajo W1 de Linux **484 llamadas / 47.009 iteraciones** (Windows 484 / 46.934: +0,16 %, dentro de la tolerancia configurada del 1 %; la variante de 506 llamadas ha desaparecido).
El resultado es la misma huella en Windows/`Haswell`, Linux/`SkylakeX` y Linux/`Haswell`. Los runners de GitHub se sortean: el run anterior cayó en un Xeon; la cobertura de un runner `Haswell` nativo
(EPYC 7763) la dan el forzado de núcleo y la matriz de 12 runners de `REMEDIATION_H1_FB551.md` §3.4 (fallo H-1 en los 6 `Haswell` antes de la corrección; todos verdes después).

## 4. A-01 y A-02 revisados con las correcciones integradas

* **A-01 (CI roja en EPYC 7763).** El run `39613590671` (SHA `41e4264`, anterior a la integración) falló por H-1 de forma determinista; el informe de B5.5 lo ignoraba y afirmaba que el fallo «no se
  ha vuelto a observar». **Retirado y sustituido** (`REPORT_BLOCK_5_5.md` §10, `INVESTIGATION_H1_B4.md` §6): el fallo era real, determinista sin perturbar en núcleos `Haswell`, y estaba en `main`, no en B5.5.
  La remediación B4 que el auditor dejaba como decisión del propietario **ya está integrada** (PR #10): el reintento en frío usa otra numérica con las mismas tolerancias y la sonda da 1,00 en todas las celdas.
  No se re-ejecutó ninguna CI «hasta caer en un Xeon»: la decisión se apoya en el forzado de núcleo y en la matriz de `main`. Falta, como nueva evidencia pasiva, un run nativo en EPYC 7763 (§9).
* **A-02 (F-B55-1 dependiente de CPU y `xfail`).** Reescrito como dependiente del núcleo OpenBLAS (§3); `xfail` eliminado; pruebas estructurales por núcleo. La hipótesis «ISA vectorial» del auditor
  queda **refinada**: el factor causal demostrado es el núcleo de OpenBLAS que se carga (la ISA solo decide cuál), probado por intervención con `OPENBLAS_CORETYPE`.

## 5. A-03 — validador y cifras

* `_common.audit_constraints` cuenta ahora `valid_weights_but_rejected` (`is_valid_solution` falso con informe de validación válido: el modo de fallo de H-1) y **lo incluye en `ConstraintAudit.clean`** y por tanto
  en `valid_measurement`: una celda con pesos correctos rechazados por estado deja de ser una medición válida. Prueba de mutación: `test_valid_weights_rejected_by_status_invalidate_the_audit`. No se toca ninguna tolerancia.
* Descripción exacta de lo que revalida: **presupuesto, largo-solo y `MaxWeight` por activo**, más coherencia `is_valid_solution`/`validation` y el contador anterior. No revisa grupos, rotación, cardinalidad,
  costes ni riesgo (solo el `SolutionValidator` interno), y reutiliza las tolerancias del `EngineConfig`.
* Las «208.452 soluciones» son **re-auditorías** (suma de `solutions_checked` de 100 celdas que revalidan los mismos lotes; según la auditoría independiente ≈ 59 lotes distintos y ≈ 127.000 soluciones). Se presentan así en el informe.
* Los 100 resultados de B5.5 anteriores a este contador no lo traen; el histograma de estados de todos ellos es solo `OPTIMAL`/`point:OPTIMAL` y todos los estados de ejecución `COMPLETED`, por lo que su valor habría sido 0.

## 6. A-04 — proyecciones de capacidad

Rotuladas como **orden de magnitud, no intervalo de confianza** (`BLOCK_5_5_LARGE_SCALE_PLAN.md` y `REPORT_BLOCK_5_5.md`), sin cambiar los números: el rango de cada fila son repeticiones de las mismas
carteras; la eficiencia con 8 workers procede de una sola medición (intervalo degenerado) y con 4 de dos; la memoria es una **cota inferior** (el coordinador retiene los resultados y no se midió por encima de 300 tareas);
las clases sin medir (W2, W5) están excluidas y renormalizadas, lo que sesga a la baja (6–26 % de las carteras); el factor ×1,67 es una variación de fase observada una vez; el equipo de medida (10 núcleos P+E, memoria
saturada) no es el destino (6 núcleos compartidos con SQL Server).

## 7. A-05 y revisión de requisitos

Recuento tras la revisión: **316 = 241 `VALIDATED` / 42 `PARTIAL` / 33 `NOT_IMPLEMENTED` / 0 `IMPLEMENTED`** (B5.5 había llegado a 244 / 39 / 33; verificado contando las filas de `TRACEABILITY.md`).

| Requisito | Estado final | Razón |
|---|---|---|
| CFG-012 | VALIDATED | configuración estricta con pruebas; ajustes de medida fuera del `config_hash` |
| BEN-002 | VALIDATED | estadísticas calculadas y comprobadas con oráculo manual (percentiles, tasas, contadores) |
| BEN-004 | VALIDATED (criterio justificado) | el requisito exige medir lote {1, 5, 10, 20, AUTO}, workers {1, 2, 4, 8} y modo de datos compartidos: los tres barridos se ejecutaron con T1 = 0; la fila de trazabilidad nombra ahora los módulos reales (script + funciones puras) en vez de `benchmark/suite.py::scaling_benchmark`. Límites declarados: máquina local y runners de 4 vCPU, 8 workers una sola configuración, no el destino (eso es BEN-007/GOV-012) |
| BEN-005 | **PARTIAL** (degradado) | detector y trabajo determinista validados y siempre activos; la regresión de **tiempo** es opt-in y no corre en CI |
| TST-005 | **PARTIAL** (degradado) | ídem: los tests no miden rendimiento en la suite por defecto |
| PAR-003 | **PARTIAL** (degradado) | AUTO calibrado en una sola mezcla sintética; sin contraste con una distribución real |
| BEN-001, BEN-006 | PARTIAL | sin cambio: faltan etapas de B6 y `RunMetadata` formal |
| BEN-007 | PARTIAL | 10 y 100 ejecutadas; **1.200 sin ejecutar** (sin autorización) |
| GOV-012 | PARTIAL | escala objetivo proyectada, no ejecutada; W2 y W5 sin medir a dimensión realista |
| PAR-013 | PARTIAL | sin cambio (re-auditoría de B5.4 pendiente; `main` añadió evidencia sobre el cuelgue de `_terminate_pool`, sin cambiar el estado) |
| SOL-002, SOL-005, SOL-014, SCN-006, CAN-007 | sin cambio | su evidencia ampliada (PR #10) ya figura en `main`; este PR no modifica esos módulos |
| P-02, P-05, P-07, P-08 | PARTIAL | sin cambio (ver `BLOCK_5_IMPLEMENTATION_PLAN.md` §10–§11) |
| C-28 | **cumplida (T1) en la parte medida** (10 carteras, 565 soluciones; Windows `Haswell` + Linux `SkylakeX`/`Haswell` forzados) | queda fuera: otras mezclas (HEAVY/CONIC), W5 y dimensión realista (A-02 §4 puntos 3 y 5); C-28 no es un `RequirementID` oficial |

## 8. A-06, A-07, A-08

* **A-06.** La huella incluye `strategy_statuses` (estado de solver de cada `StrategyResult`, también dentro de los multiescenario) y la comparación lo exige igual; un `OPTIMAL_INACCURATE` en W2/W3/W4 con pesos coincidentes ya no pasaría.
* **A-07.** Swap al iniciar cada medición: **6,7–11,1 GB** y RAM disponible **0,3–2,3 GB** (23 resultados); corregido en el informe. Los JSON de B5.3 conservan su esquema de metadatos reducido (BEN-006 sigue `PARTIAL`).
* **A-08.** Sin cambio de datos: las campañas no intercaladas no separan «carteras distintas» de «fase de la máquina»; se mantiene declarado como limitación y no se interpretan diferencias de ×1,5 como efecto de carga.

## 9. Verificación y estado

| Comprobación | Resultado |
|---|---|
| Suite completa Windows 11 / Python 3.13.6 (*worktree* limpio de `0be043a`, una sola ejecución, sin carga concurrente) | **2016 passed, 12 skipped, 0 failed** (16 min 30 s). Los 12 *skipped*: 10 específicos de Linux/POSIX, la regresión de tiempo opt-in y `SkylakeX` forzado (sin AVX-512 en esta CPU) |
| Pruebas nuevas del cierre | huella por cartera (10), núcleo forzado `Haswell` (pasa) y `SkylakeX` (se omite aquí; pasa en CI), conjunto de composiciones de W1, estados de estrategia (A-06), contador de pesos válidos rechazados (A-03) |
| `mypy --strict portfolio_engine` / `ruff check .` / `ruff format --check .` | 0 errores (179 ficheros) / limpios / limpios |
| CI Linux del PR #9, `0be043a` (run `39774545136`, Xeon 8573C) | **success, 2028 passed, 3 skipped**; matriz de núcleos: huella 0 divergencias con nativo (`SkylakeX`), `Haswell` y `SkylakeX` forzados; 33 pruebas de H-1/desempate/multiescenario pasadas en cada uno |
| CI Linux del PR #9, `389d897` (cabeza de documentación; run `39776822484`, **AMD EPYC 9V45**, núcleo `SkylakeX`) | **success, 2028 passed, 3 skipped** (5 min 00 s); huella 0 divergencias con nativo/`Haswell`/`SkylakeX` forzados; 33 pruebas de H-1/desempate/multiescenario por núcleo; W1 484 llamadas / 47.009 iteraciones; sonda H-1 1,00 en todas las perturbaciones. Segundo modelo de CPU distinto (tras el Xeon 8573C) |
| Ejecuciones completas duplicadas | Ninguna: una suite completa en Windows y una CI completa por commit; los diagnósticos de núcleos son focalizados (3 módulos de test y la huella) y llevan `timeout` y `timeout-minutes` |

**Estado.** No queda ningún defecto bloqueante de B5.5 conocido: la CI está en verde con `main` integrado, F-B55-1 está cerrado, H-1 remediado, las cifras y los estados corregidos. Siguen abiertos, sin bloquear la auditoría final de B5.5, los pendientes de §10 (sobre todo BEN-007 a 1.200 carteras, que requiere autorización expresa del propietario). **El Bloque 5 completo no puede cerrarse sin BEN-007.**

## 10. Hallazgos pendientes

| ID | Estado |
|---|---|
| BEN-007 (1.200 carteras, DoD oficial) | **Pendiente de autorización expresa del propietario**; guarda D-12 y topes `--max-wall`/`--max-rss-mb` listos |
| C-28 ampliado (HEAVY/CONIC, W5, dimensión realista) y W2/W5 a dimensión realista | Pendiente (D-I del plan) |
| Regresión de rendimiento de **tiempo** en el destino | Pendiente; requiere baseline en el host de destino (no disponible: Arsys prohibido) |
| Run nativo en EPYC 7763 / núcleo `Haswell` real | Evidencia pasiva: aparecerá si un run futuro cae en esa CPU; la cobertura actual es por forzado de núcleo y por la matriz de `main` |
| Re-auditoría de B5.4 (PAR-013) | Ajena a B5.5 |
| Mejoras no bloqueantes | CI con el lock instalado (hoy numpy 2.4.6 en CI frente a 2.5.3 local); intercalar medidas secuenciales/paralelas (A-08) |
