# AUDIT_BLOCK_5_5 — Auditoría independiente de B5.5 (benchmarks, regresión de rendimiento y proyección de capacidad)

Fecha: 2026-10-21. Rama `block5-benchmarks-final-audit`, PR #9 (borrador), SHA auditado `41e426479dae210bc35208276a8f328ae9b3519c` (base `main` `8ceaf3a`).
Auditor: Claude (Sonnet 5.5), sesión independiente de la que ejecutó B5.5. Sin cambios de código de producción, sin commit/push/PR/merge, sin cargas de ≥ 1.000 carteras,
sin acceso a Arsys, Oracle ni SQL Server. El único fichero creado es este informe.

## BLOCK_5_5_AUDIT_STATUS = PASS_WITH_CHANGES

**B5.5 NO está preparado para integración todavía.** El trabajo de ingeniería es sólido y honesto en lo esencial (procedencia, separación medido/estimado, T1, sin
cambios en módulos validados), pero hay tres bloqueos concretos: (1) la CI del propio PR #9 está en **rojo** y el informe afirma lo contrario de lo que esa CI demuestra
sobre H-1; (2) la caracterización de F-B55-1 como divergencia «de plataforma» es incorrecta y el `xfail` no estricto enmascara regresiones; (3) hay cifras y estados
sobredimensionados que deben corregirse o justificarse. El **Bloque 5 no puede declararse cerrado** (condiciones en §11).

## 1. Qué se auditó y cómo (y qué NO)

| Elemento | Resultado |
|---|---|
| Lectura | `MASTER_SPEC.md`-reglas de `CLAUDE.md`, `REPORT_BLOCK_5_5.md`, `BLOCK_5_5_LARGE_SCALE_PLAN.md`, `INVESTIGATION_H1_B4.md`, `TRACEABILITY.md` (filas relevantes y recuento), `ci.yml`, `portfolio_engine/benchmark/{scaling,regression}.py`, `benchmarks/scripts/{scaling,scale_run,_common}.py`, `tests/integration/test_cross_platform_reference.py`, `default_benchmark.toml` |
| Alcance del cambio | `git diff 8ceaf3a HEAD -- portfolio_engine/`: solo `benchmark/{regression,scaling}.py`, `config/scaling_config.py` y dos `__init__.py` (604 inserciones, 2 borrados de exportación). Ningún solver, algoritmo, formulación ni tolerancia cambia. Confirmado. |
| Tests reproducidos (Windows 11, `.venv`, Python 3.13.6, numpy 2.5.3 / scipy 1.18.1 / clarabel 0.11.1 / osqp 1.1.3, los de `requirements-lock.txt`) | `pytest tests/unit/benchmark tests/performance tests/integration/test_benchmark_harness.py tests/integration/test_cross_platform_reference.py tests/unit/test_architecture_rules.py` → **82 passed, 1 skipped** (el skip es la comparación de tiempos opt-in) en 117 s. Incluye T1, harness en pool real, auditor con mutación, referencia multiplataforma (en Windows la cartera W1 divergente **reproduce** la referencia) y regresión de trabajo |
| Controles estáticos (`.venv`) | `mypy --strict portfolio_engine`: 0 errores en 179 ficheros; `ruff check .`: limpio; `ruff format --check` (portfolio_engine, benchmarks, tests, config): 371 ficheros ya formateados |
| Sonda H-1 reproducida (`h1_numerical_probe.py --repetitions 30`, salida fuera del repo) | Validez con `tol` 1e-9: 1,00 / 0,47 / 0,37 / 0,40 / 0,27 / 0,07 para `eps` 0 / 1e-16 / 1e-15 / 1e-14 / 1e-12 / 1e-10; 1,00 en todas con 3e-9 y 1e-8; SLSQP `ftol=1e-15`: 1,00 / 0,70 / 0,63. **Coincide con el informe** |
| Aritmética de proyecciones | Recalculadas a mano desde los JSON de estimación (`wall = arranque + N·c/(w·min(e,1))`): coinciden al redondeo en todas las filas comprobadas (4 y 8 workers; 1.200 y 22.000) |
| Evidencia sumada desde los JSON | 100 celdas paralelas, 208.452 soluciones auditadas, 0 violaciones, 0 diferencias T1, 0 flotantes inexactos, 0 celdas inválidas. **Reproducido exacto** |
| Procedencia | 21 JSON de B5.5 con `commit` presente en el historial, `dirty=false`, host, versiones y comando (BEN-006). Ninguna escala ≥ 1.000 en los resultados (máximo: 100 → 300 tareas) |
| Recuento de requisitos | 316 = 244 `VALIDATED` / 39 `PARTIAL` / 33 `NOT_IMPLEMENTED` / 0 `IMPLEMENTED`. **Verificado** parseando la última columna de las filas de `TRACEABILITY.md` |
| GitHub Actions (API pública de Actions/check-runs) | Ver §8. **Run del PR en `failure`** |
| **No hecho** | Suite completa de ~1.994 tests (≈ 20 min y la máquina está saturada); Linux local; reejecución de campañas de rendimiento. Los números de tiempo del informe **no se han reproducido**, solo su coherencia interna, su aritmética y su procedencia. Nota de transparencia: mi primer lote de pytest se lanzó por error con el Python global (numpy 2.2.6/scipy 1.16.1) y lo aborté; **ningún resultado de esa tanda se usa aquí** |

## 2. Hallazgos (por severidad)

| ID | Sev. | Hallazgo | ¿Bloquea merge? |
|---|---|---|---|
| A-01 | **Alta** | La CI del PR #9 (run `39613590671`, SHA auditado) **falla** en un runner AMD EPYC 7763: `test_single_solutions_satisfy_the_constraints_of_every_scenario` y `test_worst_case_maximizes_the_minimum_scenario_utility` (H-1). El informe dice que el fallo original «no se ha vuelto a observar» | **Sí** |
| A-02 | **Alta** | F-B55-1 es **dependiente de la CPU, no de la plataforma/SO**; el informe afirma lo contrario en puntos concretos y el `xfail` no estricto da `XPASS` silencioso en EPYC 7763 | **Sí** (corrección de afirmaciones y del test) |
| A-03 | Media | El «validador independiente» es parcial y su puerta de validez no cuenta soluciones rechazadas por estado (clase H-1); las «208.452 soluciones» son re-auditorías repetidas de ≤ 59 lotes distintos | Sí (matizar cifras y añadir contador) |
| A-04 | Media | Proyecciones de capacidad: rangos falsamente estrechos, eficiencia de 8 workers con **una** medición, memoria constante en N, clases excluidas que sesgan a la baja; presentadas con tablas de apariencia precisa | Sí (rotulado y rangos), no el cálculo |
| A-05 | Media | Estados `VALIDATED` discutibles: TST-005/BEN-005 (la comparación de tiempos es opt-in y no corre en CI), BEN-004 (el módulo `scaling_benchmark` de la especificación no existe), PAR-003 (una sola mezcla sintética) | Justificar o degradar |
| A-06 | Media | La huella de C-28 omite el estado de solver de W2/W3/W4 (solo estados de puntos de frontera) | No (mejora de la prueba) |
| A-07 | Baja | Inexactitudes menores de documentación (swap hasta 11,1 GB frente a «6,7–8,8»; metadatos antiguos de B5.3; contexto de «hardware lottery» en CI) | No |
| A-08 | Info | Confundidor de diseño: campañas no intercaladas → no se separan «carteras distintas» de «fase de la máquina» (×1,67) | No |

## 3. A-01 — CI roja del PR #9 y H-1 (Alta)

**Evidencia (API pública).** Run `39613590671` (evento `pull_request`, SHA `41e4264`), job «Ubuntu / Python 3.11», runner **AMD EPYC 7763**, conclusión `failure` en el paso «Full test suite»:
`2 failed, 2002 passed, 3 skipped, 1 xpassed` en 319 s. Los dos fallos son exactamente los de H-1 (`AUDIT_BLOCK_5_3`). Los pasos de diagnóstico (que corren con `if: always()`) dan:

* `b55-h1-unperturbed`: con la tolerancia configurada y **sin perturbar**, `estados={'OPTIMAL_INACCURATE/CROSS_CHECK': 60}`, 22 iteraciones (en esta máquina: `OPTIMAL`, 10 iteraciones).
* Validez con `tol` 1e-9: **0,00** / 0,52 / 0,40 / 0,42 / 0,43 / 0,07 para `eps` 0 / 1e-16 / … / 1e-10; con 3e-9 y 1e-8: 1,00 en todo.
* SLSQP `ftol=1e-15`: **0,00** sin perturbar, 0,60 / 0,75 con perturbación; con `ftol ≥ 1e-12`: 1,00.

**Consecuencias para el informe.**

1. `REPORT_BLOCK_5_5.md` §10 («el fallo original de H-1 (CPU EPYC 7763) no se ha vuelto a observar ni se ha podido descartar») e `INVESTIGATION_H1_B4.md` §6 quedan **desmentidos**: el fallo original se reproduce en la CPU original, con el mecanismo descrito (`OPTIMAL_INACCURATE` por la política de estado, con `status_source = CROSS_CHECK` tras el reintento en frío). La incertidumbre declarada en `INVESTIGATION_H1_B4.md` §4 («no demostrado que el estado sea `AlmostSolved`») queda cerrada por esta evidencia.
2. En EPYC 7763 el fallo no es «intermitente»: es **determinista sin perturbar**. Lo que parecía azar era la lotería de runners de GitHub (Xeon vs EPYC 7763). Por tanto el verde de CI de `main` (`8ceaf3a`) y de los commits `933c0cc`/`ed3eab4` **no es evidencia de robustez**, solo de en qué CPU cayó el job.
3. El estado `READY_FOR_INDEPENDENT_AUDIT` y la fila «success» de §10 describen otro SHA y otra CPU; el SHA de la cabeza del PR tiene CI roja.

**Esto no lo introduce B5.5** (es preexistente en B4 y B5 no toca esos módulos), pero B5.5 lo investigó, lo documentó mal y lo deja integrar con un check rojo.

**Corrección obligatoria.** Actualizar `REPORT_BLOCK_5_5.md` §10/§12, `INVESTIGATION_H1_B4.md` §4/§6, `CHANGELOG.md` y `TRACEABILITY.md` con el run `39613590671`. Y una decisión del propietario, **no tomada aquí**: (a) remediación B4 de H-1 **antes** de este merge; o (b) aceptar explícitamente un check rojo conocido, preexistente y atado a una CPU, con esa decisión registrada. No se debe re-ejecutar la CI hasta que caiga en un Xeon: eso enmascara el defecto (ya lo prohíbe `AUDIT_BLOCK_5_3`).

## 4. A-02 — F-B55-1: ¿es justificable el `xfail`? ¿qué impide la equivalencia multiplataforma completa?

**Datos reunidos (informe + run del PR).** Cartera `W1-GLOBAL-NET-000005-0000`; contador de trabajo `W1` del lote de referencia (484 llamadas al solver / 46.934 iteraciones = variante «11 composiciones», 506 / 49.012 = variante «12»):

| Host | SO / Python | Variante | Fuente |
|---|---|---|---|
| Intel i7-13620H (Raptor Lake) | Windows 11 / 3.13.6 | 484 (11) | referencia versionada, reproducida en esta auditoría |
| AMD EPYC 7763 (Zen 3) | Ubuntu 22.04 / 3.11.17 | **484 (11)** («sin divergencias», `b55-work: W1 … 484`; `1 xpassed`) | run `39613590671` |
| Xeon Platinum 8573C (Emerald Rapids) | idem | 506 (12) | informe §10 |
| Xeon 6973P-C (Granite Rapids) | idem | 506 (12) | informe §10 |
| AMD EPYC 9V45 (Zen 5) | idem | 506 (12) | informe §10 |

**Lectura.** Con el **mismo** SO, el mismo Python y la misma resolución de dependencias, una CPU Linux (EPYC 7763) da el resultado de Windows y otras tres dan el otro. Luego la causa **no es el SO, ni el compilador de las ruedas, ni la versión de Python** (el informe §5.1 listaba esos factores como no distinguibles y concluía «no varía con el fabricante»: eso era un artefacto de que las tres CPU observadas coincidían en otra cosa). La partición observada coincide exactamente con **ISA vectorial**: los tres que dan 12 son CPU con **AVX-512** (Emerald Rapids, Granite Rapids, Zen 5), los dos que dan 11 solo tienen **AVX2** (Raptor Lake de portátil, Zen 3). Es la hipótesis más económica (despacho de núcleos SIMD de OpenBLAS/NumPy con orden de suma/FMA distinto), **pero no está probada**: la cardinalidad es 5 CPU y esa coincidencia es una inferencia mía a partir de la microarquitectura, no un dato medido. Test decisivo (no ejecutado aquí, requeriría CI): en un runner AVX-512 forzar `OPENBLAS_CORETYPE=Haswell` y `NPY_DISABLE_CPU_FEATURES="AVX512F AVX512CD AVX512_SKX …"` y comprobar si pasa a 484; y registrar `numpy.show_config()` de SIMD y las versiones de numpy/scipy/clarabel en cada anotación de CI. Hoy la CI **no instala el lock** (`pip install -e '.[dev,exact-mip,bench]'` resuelve rangos de `pyproject.toml`) ni anota las versiones resueltas, así que tampoco puede descartarse formalmente deriva de versiones entre runs separados en el tiempo.

**¿Es justificable el `xfail`?** Como **marca temporal documentada**, sí: la divergencia es real, está caracterizada, no se «arregla» tocando B3 desde B5.5, y la referencia de trabajo conserva ambas variantes. Pero tal como está **no es aceptable**:

1. Es `strict=False` y condicionado a `sys.platform != "win32"`: en EPYC 7763 el test **pasa** (`XPASS`) sin que nadie lo vea; en las CPU AVX-512 cualquier fallo de la cartera —por ejemplo un cambio real de pesos en las 11 composiciones comunes o un estado no `OPTIMAL`— queda **absorbido como xfail**. La prueba deja de proteger exactamente la cartera que más lo necesita.
2. La condición correcta no es `win32`, sino la variante de CPU/ISA; el informe y el docstring dicen «solo fuera de Windows»/«entre plataformas», lo cual es erróneo.

**Corrección obligatoria.** Sustituir el `xfail` ciego por una aserción estructurada para esa cartera: «las composiciones comunes coinciden bajo T1; el conjunto de una variante es superconjunto de la otra; el número de composiciones ∈ {11, 12}», y que **falle** en cualquier otro caso. Reescribir F-B55-1 como dependiente de CPU (hipótesis ISA, con el test decisivo).

**Qué impide declarar equivalencia multiplataforma completa** (C-28 debe seguir `PARTIAL`, de acuerdo con el informe):

1. Existe una divergencia abierta de qué candidatos entran (B3, `CandidateEngine`/`GlobalCandidateFrontierEngine`); causa raíz sin determinar (probablemente decisión de umbral/empate sensible a ulps, pero no demostrada).
2. No se ha aislado el factor (CPU/ISA) ni se registran las versiones de librerías resueltas en CI.
3. La evidencia es **un** lote de 10 carteras (2 W1), semilla 7; nada sobre mezclas HEAVY/CONIC, W5 ni dimensión realista.
4. La huella no incluye el estado de solver de W2/W3/W4 (A-06): un `OPTIMAL_INACCURATE` en esas clases pasaría C-28 si los pesos coinciden.
5. Windows y Linux usan Python 3.13 y 3.11 respectivamente; mientras la CI no use el lock, «Linux» no es una configuración congelada.
6. El criterio T1 (`1e-6`) acepta la variante de pesos pero **no** la de conjunto de soluciones; hace falta decidir si el conjunto de candidatos debe ser invariante (decisión B3, D-H del plan).

## 5. A-03 — Validador de restricciones y las 208.452 soluciones

* **Lo que es** `_common.audit_constraints`: revalidación de presupuesto (`|Σw−1| ≤ budget_tolerance`), largo-solo (`w ≥ −bound_tolerance`) y `MaxWeight` por activo (desde `snapshot.universe`, no desde el motor), sobre los pesos de los resultados. Es independiente **del solver y del `SolutionValidator`** en esas tres familias; la mutación (pesos corrompidos) está probada.
* **Lo que no es.** (a) No revisa grupos/sectores, rotación, cardinalidad (W5), costes, objetivos ni restricciones de riesgo; esas siguen cubiertas solo por el validador **interno** del motor. «0 violaciones» significa «0 violaciones de presupuesto/largo-solo/`MaxWeight`», no «solución correcta». (b) Reutiliza las tolerancias del propio `EngineConfig`, de modo que un aflojamiento de tolerancia ampliaría ambos validadores a la vez. (c) La comprobación de coherencia solo detecta «marcada válida pero informe inválido»; la inversa («pesos correctos pero `is_valid_solution=False`», que es **exactamente** el modo de fallo de H-1) no se cuenta ni invalida la celda. Si H-1 ocurriera en un benchmark, `valid_measurement` seguiría siendo `True` (solo quedaría reflejado en el histograma de estados, que no es una puerta). En los datos locales no ocurrió: el histograma agregado es solo `OPTIMAL` (1.744) y `point:OPTIMAL` (190.780), y todos los estados de ejecución son `COMPLETED` (4.313).
* **Cifra.** Los 208.452 son la suma de `solutions_checked` sobre 100 celdas, pero cada celda revalida **el mismo lote** (misma semilla) y el lote de `ENG-MIX-BASE`/100 aparece en 5 campañas. Contando una vez por lote distinto (clave mezcla/N/semilla/universo/posiciones) hay **59 lotes** y ≈ **127.000** soluciones, y aun así varios lotes puros solapan con las mezclas. La cifra es correcta como «auditorías realizadas», **no** como «soluciones distintas validadas». Debe presentarse así.

**Correcciones.** Redactar «soluciones revalidadas (con repeticiones)» y las tres familias comprobadas; añadir un contador `valid_weights_but_rejected` (is_valid_solution falso con `validation.violations` vacío) y reportarlo/gate-arlo en `valid_measurement` sin tocar ninguna tolerancia.

## 6. H-1 y la validez de los benchmarks (sin tocar algoritmos ni tolerancias)

Riesgos concretos para lo que B5.5 afirma:

1. **Validez por CPU.** Todas las cifras de rendimiento y los 0 fallos proceden de un i7-13620H donde la sonda sin perturbar da `OPTIMAL`. En un EPYC 7763 las clases con conos (W2-WORST-CASE, y toda cartera con restricciones degeneradas tipo rotación+peso máximo+grupo activos) devolverían `OPTIMAL_INACCURATE` y se rechazarían con pesos correctos. Los benchmarks no lo notarían (A-03c). Una ejecución masiva en el servidor de destino con esa CPU podría perder la fracción de carteras W2-WORST-CASE (4 % de `ENG-MIX-BASE`) sin aviso.
2. **Contadores de trabajo.** `COLD_RETRY` añade llamadas al solver; `perf_reference_work.json` fija llamadas «exactas» con dos variantes (484/506, por F-B55-1) pero el efecto de H-1 en EPYC 7763 sobre otras celdas no está en el baseline (la CI no comparó contra él porque esa prueba pasó, pero tampoco hay constancia de qué celdas alcanzan el camino de reintento allí).
3. **Tiempos.** La comparación de tiempos es por host (fingerprint) y opt-in: no hay protección frente a un cambio de CPU del servidor; es correcto que devuelva `HOST_MISMATCH`, pero entonces no hay baseline de tiempos en CI en absoluto.
4. **Comparabilidad de campañas.** Los fallos de H-1 y de F-B55-1 muestran que el mismo código produce resultados distintos según la CPU: las proyecciones de §9 son válidas, como mucho, para esta CPU.

Recomendación (no aplicada): puerta de validez ampliada (A-03), anotar en cada JSON de benchmark el ISA/familia de CPU y el recuento de estados `OPTIMAL_INACCURATE`, y condicionar toda ejecución masiva a que la sonda H-1 dé 1,00 en el host de destino.

## 7. Resultados experimentales frente a estimaciones (punto 3)

**Bien resuelto.** Las estimaciones viven en `capacity_estimate_*.json` con `metadata.executed = false` y una declaración explícita; el informe usa tablas separadas («medido» §6.1–6.9 y «proyección» en `BLOCK_5_5_LARGE_SCALE_PLAN.md`); el factor de extrapolación (×10 … ×7.333) y el aviso «no sustituye a la ejecución» están en cada fila; `scale_run.py run` rechaza ≥ 1.000 sin `--authorized-by`; no se asignan costes a clases sin medir; el dinero requiere una tarifa del usuario. El modelo `T_seq = N·Σ sᵢcᵢ` se contrasta con medidas (−1,3 % … +1,3 %) y se etiqueta como «predicho» frente a «medido». Las cifras de Linux se atribuyen a anotaciones públicas de CI.

**Reparos.** (i) El ±1,3 % valida solo la **aditividad secuencial** (no hay interacción entre tareas), no el modelo de capacidad paralela, y se obtuvo con costes por clase y mezclas de campañas con fases distintas de máquina; es un buen resultado, pero no demuestra que el coste unitario sea estable (A-08). (ii) En §6.2, W1 cuesta 1,82 s/cartera con 100 carteras frente a 1,23 s con 10 y 1,2 s dentro de la mezcla: ×1,5 entre conjuntos de carteras o fases de máquina, **mayor que cualquier rango de las proyecciones**. (iii) La cifra «1,4–3,8 h para 22.000 `BASE`» es una cifra de **una máquina sin dedicación**, con 6,7–11,1 GB de swap, y se cita en un resumen («Cómo leerlo») sin ese cualificador en la misma frase.

## 8. A-05 — Estados de requisito (punto 9, parte de gobernanza)

| Requisito | Estado declarado | Valoración |
|---|---|---|
| CFG-012, BEN-002 | VALIDATED | Aceptable: configuración y estadísticos con oráculo manual |
| BEN-005 / TST-005 | VALIDATED | **Discutible.** La detección de deterioros de **tiempo** es opt-in (`PE_RUN_TIMING_REGRESSION=1`, ejecutada una vez, solo en este host) y su omisión «no cuenta como validación» (docstring propio). Lo que corre siempre detecta cambios de **trabajo**, no de rendimiento. Un test de regresión de rendimiento que no mide rendimiento en la suite por defecto ni en CI debería ser `PARTIAL`, o la enmienda debe documentar que el criterio es «trabajo determinista + detector probado» |
| BEN-004 | VALIDATED | **Discutible.** La fila de trazabilidad sigue indicando el módulo `benchmark/suite.py::scaling_benchmark`, que no existe (el informe lo reconoce: «script + funciones puras»). Medido solo en este host y en runners de 4 vCPU con 10 carteras; 8 workers en una sola configuración |
| PAR-003 | VALIDATED | **Discutible.** Calibración de AUTO sobre una sola mezcla sintética con cola larga; el propio informe dice que no está calibrado frente a una distribución real |
| BEN-007 / GOV-012 | PARTIAL | Correcto |
| BEN-001, BEN-006 | PARTIAL | Correcto |
| C-28 | PARTIAL | Correcto (ver §4) |
| PAR-013 | PARTIAL | Correcto (sigue ligado a la re-auditoría de B5.4: `AUDIT_BLOCK_5_4_CLOSURE.md` está **sin versionar** en el árbol; no forma parte del PR) |

`CLAUDE.md` exige no declarar `VALIDATED` sin implementación **y** test de aceptación que pasan; en los tres casos discutibles el test de aceptación existe pero verifica una versión más débil del requisito. Acción: o degradar a `PARTIAL`, o justificar por escrito la enmienda del criterio. Si se degradan: 241 `VALIDATED` / 42 `PARTIAL` / 33 `NOT_IMPLEMENTED` (cifra mía, hipotética).

## 9. Modelo de coste, calibración e incertidumbre de las proyecciones a 1.200 y 22.000 carteras (punto 9)

**Qué se verificó.** La aritmética (`project_capacity`) y su aplicación (`scale_run.py estimate`) son correctas y reproducibles; coste, eficiencia, arranque y memoria se derivan de mediciones citadas; el rango óptimo/central/pesimista combina coste (mín./mediana/máx. de repeticiones) y eficiencia (mín./mediana/máx. de muestras), con factor de extrapolación declarado.

**Problemas de incertidumbre (la proyección es más incierta de lo que sugieren sus tablas):**

1. **Rango de coste falsamente estrecho en las filas «U=700».** Se alimenta con 3 carteras por clase y 2 repeticiones; mín/mediana/máx son repeticiones de **las mismas 3 carteras**, no dispersión entre carteras. Resultado: `0,806 / 0,884 / 0,962 s` por cartera (±9 %), mientras en esta misma máquina W1 varió ×1,5 entre conjuntos de carteras/fases. W1 es el 82 % del coste, y su coste real con 20 posiciones depende de la cartera (candidatos, haz).
2. **Sesgo a la baja por exclusión.** En las proyecciones «U=700» se excluyen y renormalizan las clases sin medir (W2×4 y W5): 16 % de `BASE`, 6 % de `LIGHT`, **26 % de `HEAVY`**; W5 cuesta 0,9–1,5 s ya a 8 activos. La renormalización reparte el 100 % del coste sobre las clases baratas medidas. El plan lo cuantifica (+10–20 % por un 1 % de W5), pero las tablas no lo incorporan al rango.
3. **Eficiencia con una sola muestra a 8 workers.** El «rango» es `(0,59, 0,59, 0,59)` (n=1): óptimo/central/pesimista solo reflejan el coste. La fila `22000 / 8 workers / BASE U=700 = 1,04 / 1,14 / 1,24 h` (±9 %) es **intervalo degenerado**, no una incertidumbre. A 4 workers, n=2 (0,64–0,90).
4. **Eficiencia transferida entre configuraciones.** Se mide con `ENG-MIX-BASE` a 8 activos y 3 posiciones (tareas de 0,05–1,2 s) y se aplica a una mezcla cuyas tareas W1 duran ≈ 3,3 s. Con N=1.200 y tareas largas, el efecto de cola es otro (probablemente más favorable que a N=100, pero no medido). La eficiencia en régimen estacionario además resta la mediana de arranques **medidos aparte** (6,3–30,5 s) a la pared de cada ejecución: ruido de 1–2 puntos porcentuales por celda a 100 carteras.
5. **Memoria constante en N.** Tabla: 0,47 GB (1 worker) / 0,95 GB (4) / 1,64 GB (8) igual para 1.000 y 22.000 carteras. El coordinador retiene los `TaskResult` hasta el final (el plan lo reconoce, §3); no se midió por encima de 300 tareas y solo con clases baratas. Debe leerse como **cota inferior**: ≈ 11 KB serializados por cartera ⇒ cientos de MB a 22.000 solo en bytes crudos, antes del factor de objetos Python.
6. **Dos «factores» que no son cotas.** El `×1,67` es la variación de fase observada *una* vez, aplicada a toda la proyección (incluido el arranque); y el rango pesimista solo es un máximo observado entre pocas repeticiones. Ninguno cubre extrapolación ×333–×7.333 ni cambio de hardware.
7. **Transferibilidad al destino.** El host de medida es un i7 híbrido P+E de 10 núcleos/16 hilos con memoria saturada; el destino previsto (Arsys: 6 núcleos/12 hilos compartidos con SQL Server) y la CPU (H-1, F-B55-1) son distintos. Las filas de 8 workers no son representables en un destino de 6 núcleos.

**Veredicto sobre las proyecciones.** Útiles como **orden de magnitud y como plan de pruebas** («1.000 `BASE` realistas: minutos a decenas de minutos; 22.000: horas a decenas de horas según mezcla»), **no** como compromiso de capacidad ni como intervalo estadístico. Para 1.200 carteras (DoD oficial) el factor de extrapolación es ×400 sobre 3 carteras por clase; solo la ejecución P2 lo cierra. Corrección: rotular las tablas con «orden de magnitud, no intervalo de confianza; rango = repeticiones de las mismas carteras» y marcar la memoria como cota inferior; no cambiar los números.

## 10. Otros puntos del encargo

* **Controles estáticos y equivalencia T1** (puntos 4): reproducidos, ver §1. T1 en las 100 celdas sumadas desde los JSON: 0 diferencias y 0 flotantes distintos (T0 exacto en esta máquina); cada celda paralela se compara con la secuencial **antes** de aceptar su tiempo y marca `valid_measurement=false` si no coincide. La equivalencia es en la misma máquina; entre CPU no es exacta (A-02).
* **Estimadores y speedup** (punto 2): `speedup`, `efficiency`, `karp_flatt` correctos. Observación: speedup y eficiencia usan el **mínimo** de cada celda, y secuencial y paralelo se miden en momentos distintos de una máquina bimodal (×1,67); el cociente de mínimos mezcla fases. Es un sesgo conocido y declarado, de tamaño comparable a las diferencias entre 4 y 8 workers. `compute_occupancy` usa latencias de la última repetición con el mínimo de pared (inconsistencia menor).
* **Detección de regresiones** (`regression.py`): umbral `k×max(MAD, suelo·mediana)` con `k=5`, suelo 5 %: razonable y bien guardado (`HOST_MISMATCH`, `WORK_CHANGED`); con 7 repeticiones la MAD es poco fiable y el suelo domina, por lo que el umbral efectivo es ≈ 25 % de la mediana. Es un detector grueso, no uno de «deterioro significativo» fino.
* **Cargas de ≥ 1.000**: ninguna ejecutada, ni Arsys/Oracle/SQL Server, ni datos reales. La guarda D-12 está probada.
* **A-07 (documentación).** §3 del informe declara 6,7–8,8 GB de swap al iniciar; los JSON muestran hasta 11,1 GB (`universe50`) y 9,9 GB (`growth`). Los JSON antiguos de B5.3 (`shared_data_cache_*`) usan un esquema de metadatos reducido (sin `dirty`, versiones ni carga del host), lo que el informe reconoce parcialmente (BEN-006 `PARTIAL`).

## 11. Correcciones obligatorias antes del merge y condiciones para cerrar el Bloque 5

### 11.1 Obligatorias para integrar B5.5 (M-1 … M-5)

| # | Acción | Hallazgo |
|---|---|---|
| M-1 | Registrar en informe, `INVESTIGATION_H1_B4.md`, `CHANGELOG.md` y `TRACEABILITY.md` el run `39613590671` (CI roja en EPYC 7763; H-1 determinista sin perturbar) y retirar las afirmaciones «no se ha vuelto a observar». **El propietario decide** entre remediación B4 previa o integrar con un check rojo conocido (registrada), sin re-ejecutar hasta un runner «afortunado» | A-01 |
| M-2 | Reescribir F-B55-1 como dependiente de CPU/ISA (no «de plataforma»); sustituir el `xfail` no estricto por una aserción estructurada (comunes iguales bajo T1, superconjunto, 11 ó 12 composiciones) que falle en cualquier otro caso; corregir el docstring y la afirmación «no varía con el fabricante» | A-02 |
| M-3 | Presentar las 208.452 como «re-auditorías» (≈ 59 lotes distintos) y declarar las tres familias que revalida el auditor; añadir el contador `valid_weights_but_rejected` a `valid_measurement` (sin tocar tolerancias ni solvers) | A-03 |
| M-4 | Rotular las proyecciones («orden de magnitud, no intervalo»; rango = repeticiones de las mismas carteras; 8 workers con n=1; memoria = cota inferior; clases excluidas = sesgo a la baja) y mantener los números tal cual | A-04 |
| M-5 | Justificar por escrito o degradar BEN-005/TST-005/BEN-004/PAR-003; actualizar los recuentos en consecuencia | A-05 |

### 11.2 Recomendadas (no bloquean)

Añadir el estado de solver de W2–W4 a la huella de C-28 (A-06); anotar en CI el ISA de CPU y las versiones resueltas (o instalar el lock en un job de referencia); corregir el rango de swap; intercalar mediciones secuenciales y paralelas para separar fase de máquina de carga (A-08).

### 11.3 Para declarar el Bloque 5 completamente cerrado (`BLOCK_5_STATUS`)

1. M-1…M-5 cumplidos y CI en verde **de forma determinista** (o excepción documentada y aceptada por el propietario) con la rama final.
2. **BEN-007**: ejecución autorizada de **1.200 carteras** (DoD oficial) con T1, auditor ampliado y sonda H-1 en el host de ejecución; idealmente P1 (1.000) antes, con RSS del coordinador medido.
3. **H-1 resuelto** (remediación B4 independiente) o excluido por decisión expresa de la ejecución masiva de W2-WORST-CASE; **F-B55-1** con causa raíz o criterio B3 de invariancia decidido.
4. Medir W2 y W5 a dimensión realista (D-I) o declarar la proyección «U=700» como parcial en el cierre.
5. Re-auditoría de B5.4 (`AUDIT_BLOCK_5_4_CLOSURE.md` hoy sin versionar) para cerrar PAR-013, y validación en el servidor de destino (B6/Arsys) bajo autorización, no realizable desde esta máquina.

## 12. Respuesta directa

* **¿B5.5 está preparado para integración?** **No, todavía.** Estado `PASS_WITH_CHANGES`. El código añadido es limpio, probado y no toca módulos validados; pero la rama tiene CI roja con un hallazgo que el informe da por no reproducido, una causa de F-B55-1 mal atribuida y un `xfail` que desprotege, y varias cifras deben corregirse. Cumplidas M-1…M-5 (y la decisión sobre H-1), la integración es razonable.
* **¿Bloque 5 cerrado?** **No.** Falta BEN-007 a 1.200 carteras, la decisión/remediación de H-1 y F-B55-1, y la validación en destino (§11.3).
