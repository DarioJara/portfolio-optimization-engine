# BLOCK_5_BENCHMARK_PLAN — Plan de benchmarks y pruebas de compatibilidad/regresión del Bloque 5

Fecha: 2026-10-19. Rama: `block5-hpc-architecture`. Documento de **diseño**: no se ha ejecutado ningún
benchmark masivo, no se ha accedido a datos confidenciales ni a SQL Server, y **no se inventa ninguna cifra**.
Las únicas cifras citadas proceden de resultados ya versionados en `benchmarks/results/` o de las mediciones
exploratorias marcadas [M] en `BLOCK_5_HPC_ARCHITECTURE.md` §4.2.

Complementa `BLOCK_5_HPC_ARCHITECTURE.md` (arquitectura, decisiones D-xx) y
`BLOCK_5_IMPLEMENTATION_PLAN.md` (entregas B5.2–B5.5).

Requisitos que este plan materializa: BEN-001, BEN-002, BEN-004, BEN-005, BEN-006, BEN-007, TST-005, GOV-012,
CFG-012, y las pruebas de aceptación de PAR-001…013 y CCH-001…005.

---

## 1. Principios

1. **Datos sintéticos reproducibles** (semilla explícita, generador determinista, sin datos reales). Se reutiliza
   y amplía `tests/fixtures/candidates.py::universe_problem` (modelo factorial de rango bajo) y
   `tests/fixtures/problems.py`.
2. **Sin extrapolación implícita.** Una proyección a 22.000 se presenta siempre como aritmética sobre una
   medición concreta, con su incertidumbre; no sustituye a la ejecución.
3. **Contadores deterministas junto a tiempos.** Dado que la máquina de desarrollo tiene tiempos bimodales
   (registrado en `MEMORY.md` y visible en `candidate_engine_20260924T124637Z.json`, donde el mismo trabajo de 1.200
   evaluaciones tardó 7,2 s y 4,1 s), toda medición incluye llamadas al solver, iteraciones y evaluaciones de
   candidatos (invariantes de la carga) y se resume con **mínimo y mediana de N repeticiones**, no solo la media.
4. **Misma carga, mismo código, mismo entorno** entre variantes; solo cambia el factor bajo estudio.
5. **Metadatos obligatorios en cada resultado (BEN-006):** commit y estado *dirty*, `ConfigHash`, `SnapshotKey` y
   hash del bundle, semilla, versiones (Python, numpy, scipy, osqp, clarabel, pyscipopt, threadpoolctl, psutil),
   `mp_start_method`, `workers`, `batch_size`, hilos BLAS, sistema operativo, modelo de CPU, nº de núcleos físicos y
   lógicos, estado de SMT, gobernador de frecuencia (Linux), carga del sistema previa (incluida CPU de SQL Server
   en el servidor, medida por `psutil`, sin conectarse a la base de datos), fecha/hora UTC.
6. **No se ejecutan benchmarks masivos en Arsys, ni ninguna carga de ≥ 1.000 carteras, sin aprobación específica previa** (D-12, vigente). Las cargas locales < 1.000 de B5.2 no la requieren.
7. **Cumplimiento de `CLAUDE.md`:** «No inventar resultados de benchmarks» y «no afirmar que los tests han pasado
   si no se ejecutaron». Cada informe indicará qué se ejecutó y qué no.

---

## 2. Cargas de trabajo W0–W5 y mix de referencia

### 2.1 Principio (D-01)

Una cartera ejecuta el `WorkloadSpec` que se le configure (una estrategia individual o un pipeline compuesto de
operaciones existentes; ver arquitectura §14.3). **No se asume que las 22.000 carteras ejecuten todas las
estrategias.** Las clases W0–W5 son categorías de *coste y de tipo de problema* para medir y planificar, no una
partición obligatoria de las carteras: una cartera puede combinar operaciones de varias clases (su coste ≈ la
suma de los de sus operaciones, **salvo reutilización intra-tarea que debe medirse**, no suponerse).

### 2.2 Definición formal (a partir de operaciones reales del repositorio)

«Carga convexa» abarca W0–W4 (todas se formulan como LP/QP/SOCP convexos, B2/B4); W5 es entera.

| Clase | Operación(es) real(es) [H] | Tipo de problema y solver típico | Qué varía su coste | Caso tipo / parámetros de configuración |
|---|---|---|---|---|
| **W0 — Frontera convexa de composición fija** | `ContinuousFrontierEngine.solve` (extremos MinVar/MaxRet + malla `RISK_AVERSION_GRID` o `TARGET_RETURN_GRID`; tratamiento GROSS / NET / POST_COST_GROSS) | QP y LP; OSQP (QP), HiGHS vía `linprog` (LP de MaxReturn) | nº de activos de la composición, nº de puntos de la malla, tratamiento NET, reutilización de workspace | Medido: ≈ 0,05–0,18 s por frontera de 20 puntos y 20 activos [M]. Malla y tratamiento: config |
| **W1 — Búsqueda de candidatos + frontera global** | `CandidateEngine.search` + `GlobalCandidateFrontierEngine.solve` (FAST_PRODUCTION) | Heurística discreta (screening, beam, local search) + QP/LP por finalista | `n_held`, universo, presupuesto de búsqueda (`CandidateConfig`: beam, niveles, `max_evaluations`, `max_candidates`) | Medido: ≈ 6–7 s con 20 activos, universo 50–700, 12 composiciones [M]; 82–88 % en Python |
| **W2 — Multiescenario** | `ScenarioEngine.build` + una de: `MultiScenarioOptimizer.solve_independent` (W0/W1 por escenario), `solve_expected_utility`, `solve_worst_case`, `solve_base_with_stress` | QP (independiente), QP/SOCP (utilidad esperada, peor caso, estrés); OSQP / Clarabel | nº de escenarios S, modo, composición fija o candidatos | Subvariantes **W2-IND, W2-EXP, W2-WC, W2-STRESS**; S en config. `solve_independent` ≈ S × (W0 o W1) |
| **W3 — CVaR** | `StrategyOptimizer.cvar` (`MIN_CVAR`, `CVAR_LIMITED`) | LP (HiGHS) o SOCP con mandato de volatilidad vinculante (Clarabel) | nº de observaciones de retorno, con/sin mandato | Subvariantes **W3-LP, W3-MANDATE**. Medido solo a 10 activos [M]: decenas de ms |
| **W4 — Robusta y estrategias cónicas de un solo punto** | `StrategyOptimizer.robust`; `max_sharpe` (Charnes–Cooper); `volatility_target` | SOCP; Clarabel | nº de activos, tipo de incertidumbre (caja / Σ escalada), mandato | Subvariantes **W4-ROBUST, W4-SHARPE, W4-VOLTARGET**. Coste de Clarabel con mandato: **no medido** (nota de B4) |
| **W5 — Validación entera exacta** | `ExactMIPValidator.validate_heuristic` | MIQP; SCIP (`threads=1`) | tamaño del universo (`max_universe_size`), cardinalidad, límite de tiempo y gap | Solo modo validación; universos pequeños; carril aparte; cola larga acotada por el límite de tiempo |

Combinaciones de ejemplo de `WorkloadSpec` (no distribuciones reales): *solo W0*; *W1 completo*;
*W1 + W3 + W4-ROBUST sobre la composición ganadora*; *W2-WC sobre candidatos*. Las combinaciones válidas y sus
dependencias las fija el catálogo de operaciones de B5.2.

### 2.3 Mix sintético de referencia — SUPUESTO DE INGENIERÍA

> **Aviso.** Los mixes siguientes son **supuestos de ingeniería** elegidos para ejercitar el sistema y para el
> análisis de sensibilidad. **No representan la distribución real de cargas de AAA-A ni de ningún cliente, no
> proceden de datos reales y no deben usarse para predecir tiempos de producción ni sustituir datos reales.**
> Se modifican por configuración (`BenchmarkConfig.workload_mix`, fichero versionado cuyo hash consta en los
> metadatos de cada resultado). Cuando existan cargas reales (anonimizadas, previa autorización), las
> sustituirán.

| Nombre | W0 | W1 | W2 (reparto interno) | W3 | W4 | W5 | Intención |
|---|---|---|---|---|---|---|---|
| `ENG-MIX-BASE` | 40 % | 20 % | 15 % (IND 5, EXP 4, WC 4, STRESS 2) | 10 % | 14 % | 1 % | Mezcla equilibrada con predominio de fronteras sencillas |
| `ENG-MIX-LIGHT` | 80 % | 5 % | 5 % | 4 % | 5 % | 1 % | Cota inferior de coste (casi solo frontera de composición fija) |
| `ENG-MIX-HEAVY` | 10 % | 50 % | 25 % | 5 % | 9 % | 1 % | Cota superior (búsqueda de candidatos y escenarios) |
| `ENG-MIX-CONIC` | 20 % | 10 % | 15 % | 25 % | 29 % | 1 % | Sesgo hacia Clarabel (CVaR/robusta/Sharpe) |

Los porcentajes son proporciones del **número de carteras**; cada cartera ejecuta la(s) operación(es) de su
clase. W5 se mantiene bajo y en carril propio por su coste y variabilidad. La asignación de clase a cada cartera
es determinista (`derive_seed(semilla, "mix", índice)`).

### 2.4 Análisis de sensibilidad por tipo de carga

1. **Medir primero el coste unitario por clase** `c_i` (E1; escalas de 1 y 100 carteras por clase; mínimo y
   mediana de N repeticiones, más contadores deterministas: llamadas al solver, iteraciones, evaluaciones).
2. **Modelo de coste del mix:** `T_seq(mix) = N · Σ_i s_i · c_i`, con `s_i` la proporción de la clase `i`.
   Al trasvasar peso de `j` a `i`, `∂T/∂s_i = N·(c_i − c_j)`. El modelo se **verifica** comparando su predicción
   con la ejecución real del mix (el error se informa); no sustituye a la ejecución.
3. **Barridos (E17):** (a) un factor a la vez: variar `s_i` en un paso configurable manteniendo las proporciones
   relativas del resto; (b) mixes extremos (`LIGHT`/`HEAVY`/`CONIC`) y clases puras; (c) parámetros internos de
   cada clase (malla de frontera, presupuesto de búsqueda, S, observaciones de CVaR, tamaño de universo).
4. **A informar por clase y por mix:** coste unitario (mín./mediana/p95), carteras/s con 1 y p workers, speedup y
   eficiencia, pico de memoria por worker, tasa de errores y estados de solver, y **contribución de cada clase al
   tiempo total**.
5. **Cola larga:** efecto de W1 y W5 sobre la latencia p95/p99 y sobre el equilibrio de carga según su proporción.
6. **Límite honesto:** la sensibilidad vale para *este* generador sintético y *esta* máquina; no se extrapola.

### 2.5 Diversidad sintética de carteras

Determinista por `(semilla, índice)`: nº de posiciones (p. ej. 10–30), tamaño de universo (50/200/500/700),
mandatos (pesos máx/mín, turnover, grupos), activos restringidos y no comprables, costes, cardinalidad objetivo,
activos nuevos máximos, y un porcentaje configurable de carteras **intencionalmente degeneradas** (inviables, sin
cartera actual, volatilidad objetivo inferior a σ_min) para ejercitar rutas de error. Todo parámetro del
generador sale de `BenchmarkConfig`, no del código.

---

## 3. Escalas

| Escala | Propósito | Clases | Condición de ejecución |
|---|---|---|---|
| **1 cartera** | Referencia individual: distribución de etapas, perfilado, conteo de llamadas | Todas | Local, repeticiones ≥ N |
| **100 carteras** | Prueba funcional y de equivalencia | Todas (W5 reducida) | Local y servidor |
| **1.000 carteras** | Carga intermedia, primera proyección | W0, W1, Mixta (W2–W4 con muestra) | Servidor |
| **5.000 carteras** | Escalabilidad (fugas, deriva, journal) | W0, W1, Mixta | Servidor, ventana acordada (D-12) |
| **22.000 carteras** | Capacidad objetivo | **Condicionada** (ver abajo) | Solo con autorización explícita |

Notas de escala:
* La Definition of Done oficial del Bloque 5 son **10, 100 y 1.200** carteras (X-1/D-03); 1.000 y 5.000 las
  complementan; 22.000 es de **capacidad**, no de cierre, salvo enmienda del plan.
* *Puerta de proyección antes de 22.000*: con los datos de 1.000 (y 5.000), se calcula el tiempo proyectado por
  clase y el pico de memoria; el usuario autoriza o no la ejecución. Con el pipeline W1 completo la aritmética
  sobre las mediciones existentes (≈6–7 s por cartera, [M]) apunta a decenas de horas en un único proceso;
  por tanto la ejecución de 22.000 puede limitarse a W0/Mixta ligera o a una fracción acordada (D-01).
* Cada escala se ejecuta con **un límite de tiempo de pared global** (`--max-wall`) y un `--max-rss` por worker
  para abortar de forma limpia; una ejecución abortada se informa como tal y no cuenta como PASS.

---

## 4. Métricas

| Métrica | Definición / cómo se mide | Notas |
|---|---|---|
| Tiempo total (T) | Reloj monotónico de la ejecución completa (`perf_counter`), de envío a último resultado ordenado | También por etapa del coordinador |
| Carteras/s | `N_completadas / T` | Se informa con y sin carteras fallidas |
| Latencia por cartera | `PortfolioTotal` medido **dentro del worker**; p50, p95, p99, máximo, media | Percentiles del config existente (`BenchmarkConfig.percentiles`) |
| Espera en cola | tiempo entre `submit` y `inicio de cómputo` | Detecta desequilibrio de carga |
| Sobrecarga de IPC/serialización | `(recepción − envío) − cómputo` por lote; bytes de entrada/salida (`len(pickle.dumps)`), tiempo de `dumps/loads` | BEN-001 `IPC` |
| Utilización de CPU | `psutil.cpu_times`/`cpu_percent` del sistema y por proceso (coordinador y workers); ocupación efectiva = Σ tiempo de CPU de workers / (`workers` × T) | Registrar CPU de SQL Server como contexto |
| Memoria máxima | RSS y, en Linux, PSS/USS por proceso (`psutil.memory_full_info`); pico del coordinador; pico agregado; crecimiento de RSS por worker vs nº de tareas | Permite decidir `max_tasks_per_child` |
| Speedup | `S(p) = T_seq / T_p` (mismo código, `workers=1` en ruta secuencial pura como T_seq) | Se informa también `T(workers=1, pool)` para aislar la sobrecarga del pool |
| Eficiencia paralela | `E(p) = S(p)/p` | — |
| Fracción serie efectiva | Karp–Flatt: `e = (1/S − 1/p)/(1 − 1/p)` | Orienta si el límite es el coordinador/IO |
| Tasa de errores | por taxonomía: `FAILED_INPUT_VALIDATION`, `FAILED_EXCEPTION`, `TIMED_OUT`, `WORKER_CRASHED`, y por **estado de solver** (`OPTIMAL`, `OPTIMAL_INACCURATE`, `INFEASIBLE`, límites, errores numéricos) | Ambos ejes por separado |
| Llamadas al solver/s | contador de `solve()` por solver ÷ T | BEN-002 |
| Reproducibilidad numérica | Repetir la misma ejecución k veces: nº de campos con diferencia ≠ 0 y máx. diferencia absoluta (clase T0/T1) | §7 |
| Diferencia frente al secuencial | Idem entre ruta secuencial y paralela | §7 |
| Tiempo de recuperación | Reanudación tras caída: tiempo hasta reanudar y tareas rehechas | B5.4 |

Estadística: mínimo, mediana, media, p95, máximo y desviación absoluta mediana (MAD) de N repeticiones
(N fijado en `BenchmarkConfig`; recomendación inicial ≥ 5 para escalas ≤ 100 y ≥ 3 para escalas mayores, por coste).
La detección de deterioro (BEN-005) usa un umbral **derivado de la variabilidad medida** (p. ej. k × MAD del
baseline, con k en configuración), no un porcentaje fijo inventado.

---

## 5. Matriz de experimentos

| ID | Factor | Valores | Clases | Objetivo | Requisito |
|---|---|---|---|---|---|
| E1 | Línea base secuencial | `run_portfolio` sin pool | todas | Referencia T_seq, perfilado (`cProfile`) de W1 | BEN-001/002 |
| E2 | Nº de workers | 1, 2, 3, 4, 5, 6, 8, 12 (tope por D-11; sin asumir `cpu_count`) | W0, W1, Mixta | Curva de speedup/eficiencia, saturación | BEN-004, PAR-012 |
| E3 | `PortfolioBatchSize` | 1, 5, 10, 20, AUTO | W0, W1 | Sobrecarga de planificación vs equilibrio | BEN-004, PAR-003 |
| E4 | Modo de datos compartidos | pickle-initializer, ficheros `np.load`, `memmap`, `SharedMemory` | W0, W1 (universo 500/700 y S escenarios) | Elegir modo por medición; memoria/PSS por worker, tiempo de arranque | PAR-004, BEN-004 |
| E5 | Método de arranque | `spawn`, `forkserver` (con/sin preload), `fork` (solo informativo) | W0, W1 | Coste de arranque (`import` ≈ 5 s [M]) y estabilidad | R-03/R-05 |
| E6 | Hilos BLAS por worker | 1 (base), 2 | W1 | Confirmar que 1 es lo mejor con N workers | PAR-007 |
| E7 | Hilos de solver | HiGHS, Clarabel, SCIP en valor por defecto vs 1 | W3, W4, W5 | Medir sobresuscripción real; sustentar D-08 | PAR-007 |
| E8 | Caché | desactivada / activada con 0 %, 10 %, 50 % de solicitudes duplicadas | W0, W1 | Ganancia real y tasa de aciertos; confirmar que sin duplicados ≈ 0 aciertos | CCH-003/005 |
| E9 | Fallos inyectados | excepción, `os._exit`, `kill -9`, cuelgue, estado de solver adverso, entrada corrupta | W0, W1 | Aislamiento y recuperación | P-03…P-06 |
| E10 | Crecimiento con nº de tareas | 100 → 1.000 → 5.000 | W0, W1 | Fugas de memoria/segmentos, deriva de latencia | R-05 |
| E11 | SMT | 6 vs 12 hilos lógicos (afinidad) | W1 | Rendimiento real de núcleos lógicos | D-11 |
| E12 | Coexistencia con otra carga | carga sintética de CPU/RAM en el servidor (sin tocar la base de datos) | W1 | Degradación y estabilidad bajo contención | R-04 |
| E13 | Lote tamaño objetivo AUTO | tiempos objetivo por lote en configuración | W0, W1, Mixta | Calibrar el parámetro de AUTO | PAR-003 |
| E14 | Escenarios | S = 1, 3, 5, 10 | W2 | Coste ∝ S, memoria de `Σ_s` | R-01 |
| E15 | Universo | 50, 200, 500, 700 | W1 | Escalado con N (recordando que medidas previas apuntan a poca sensibilidad en `candidate_generation`) | GOV-012 |
| E16 | Persistencia/diario | con y sin diario; formatos de shard | W0 | Coste del journal y de la reanudación | P-05 |
| E17 | Sensibilidad del mix | `ENG-MIX-*`, un factor a la vez, clases puras (§2.4) | todas | Qué clase domina el tiempo; validar `N·Σ s_i·c_i` | D-01 |

Reglas: un factor a la vez salvo experimentos factoriales explícitos; orden de ejecución aleatorizado y
registrado; *warm-up* descartado (1 ejecución mínima) pero informado; los experimentos de rendimiento se ejecutan
en ventana sin otras cargas conocidas (o con la carga medida y registrada).

---

## 6. Procedimiento de ejecución

1. Preparar entorno limpio con `requirements-lock.txt` (+ `threadpoolctl`, `psutil` si se aprueba D-09);
   registrar versiones.
2. Generar el lote sintético (semilla y `ConfigHash` registrados; el fichero de entrada se guarda con su hash).
3. Ejecutar E1 (secuencial) y almacenar los resultados **de referencia** (pesos, métricas, estados, contadores).
4. Ejecutar la variante paralela; comparar con la referencia (§7) antes de interpretar tiempos: **un
   resultado erróneo invalida su medición de rendimiento**.
5. Guardar JSON con metadatos en `benchmarks/results/` (nombre `<experimento>_<escala>_<timestamp>.json`) y un
   resumen legible. No se sobreescriben resultados previos.
6. Regla de ruido: si dos repeticiones del mismo caso difieren más de lo que el MAD del baseline permite, se
   repiten y se informa de la inestabilidad; los contadores deterministas se usan para decidir cuando el tiempo
   es dudoso.

---

## 7. Compatibilidad y regresión: pruebas que deben existir

La arquitectura debe conservar los contratos matemáticos y funcionales de B1–B4. Cada fila indica qué prueba
detecta el riesgo, su oráculo y la tolerancia. Los estados de solver se comparan **siempre** por igualdad exacta.

### 7.1 Tolerancias y su justificación

| Clase | Aplica a | Criterio | Justificación (fuente) |
|---|---|---|---|
| **T0 (diagnóstico, D-07)** | Misma máquina, mismo entorno, 1 hilo BLAS, sin límites de tiempo de pared | Se **mide y reporta** la igualdad bit a bit de pesos, métricas y estados; **no es criterio de aceptación**. Un incumplimiento se investiga pero no falla la fase si T1 se cumple | Pipeline presumiblemente determinista (semillas con `derive_seed`; `adaptive_rho_interval` fijo) [H]; hipótesis a verificar en B5.2 |
| **T1 (criterio de aceptación, D-07)** | Siempre: secuencial vs paralelo, distintos workers/lotes/orden, entre máquinas | `|Δpeso| ≤ 1e-6` y `|Δmétrica| ≤ 1e-6` absolutos; estados de solver idénticos; `CompositionHash`, `ConstraintHash`, `CurrentPortfolioStateHash` idénticos | Reutiliza `TOLERANCE = 1e-6` de `tests/numerical_regression/test_frontier_golden.py`; las tolerancias de validación (`1e-7`) y de deduplicación (`1e-6` pesos, `1e-8` retorno/volatilidad) ya existen en `config/default_engine.toml`. No se introduce ninguna tolerancia nueva (D-07) |
| **Restricciones** | Todas las soluciones | Revalidación independiente con `SolutionValidator` con las tolerancias de `SolverConfig` (`budget/bound/constraint = 1e-7`, `variance = 1e-12`) | Contrato de B2 (VAL-008) |
| **T2** | Rendimiento | Estadística (MAD, k configurable) | §4 |

Las ejecuciones con límite de tiempo de pared (`time_limit_seconds`) pueden dar estados distintos según la
carga; para la equivalencia se ejecuta **sin** ese límite (o con límites de iteración) y los casos con límite se
verifican aparte comprobando que el estado se conserva (nunca `OPTIMAL` por defecto).

### 7.2 Catálogo de pruebas

| ID | Riesgo | Prueba | Oráculo | Entrega |
|---|---|---|---|---|
| C-01 | Diferencias indebidas secuencial↔paralelo | Para cada clase W0–W4: lote de ≥100 carteras; ruta secuencial vs pool (workers = 2, 4, N); comparar todo | T1 | B5.2 |
| C-02 | Dependencia del orden de finalización | Barajar el orden de envío (múltiples semillas) y retardos artificiales aleatorios en workers; resultado ordenado por `SequenceID` idéntico | T1 | B5.2 |
| C-03 | Dependencia del tamaño de lote | Batch size ∈ {1, 5, 10, 20, AUTO} ⇒ resultados idénticos | T1 | B5.2 |
| C-04 | Dependencia del nº de workers | workers ∈ {1, 2, 4, …} ⇒ idénticos | T1 | B5.2 |
| C-05 | Contaminación entre carteras | Secuencia A,B,A en el **mismo** worker (`workers=1`): A idéntica en ambas apariciones; además cartera A sola vs en lote; comprobar que `WorkerContext` no retiene objetos de tarea (inspección de referencias) y que el snapshot sigue con el mismo hash tras N tareas | T1 | B5.2 |
| C-06 | Escritura accidental sobre datos compartidos | Intentar `arr[0] = x` ⇒ `ValueError`; hash del snapshot antes/después de la ejecución | exacto | B5.3 |
| C-07 | Violación de restricciones | Revalidar el 100 % de resultados en pruebas con `SolutionValidator` independiente; inyectar un resultado corrupto en el transporte y comprobar que se detecta (hash de integridad) | exacto | B5.2/B5.4 |
| C-08 | Cambios de estado del solver | Histograma de `SolverStatus` y de `outcome` idéntico secuencial vs paralelo; ningún estado no óptimo se convierte en `OPTIMAL`; estados `TIME_LIMIT`/`MAX_ITER` se conservan | exacto | B5.2 |
| C-09 | No reproducibilidad | Repetir la misma ejecución k=3 veces ⇒ T1 (T0 reportado como diagnóstico) | T1 | B5.2 |
| C-10 | Condiciones de carrera | Estrés con muchas tareas diminutas y workers > núcleos, repetido ≥ 100 veces; sin pérdida/duplicado/resultados cruzados (cada resultado lleva el hash de su entrada y se comprueba que coincide con su `TaskID`) | exacto | B5.2/B5.4 |
| C-11 | Pérdida o duplicación de trabajos | Invariante de conteo: `enviadas = Σ estados finales`; cada `TaskID` exactamente una vez en el diario; todas las modalidades de fallo de E9 | exacto | B5.4 |
| C-12 | Errores de recuperación | Matar un worker en medio de un lote ⇒ reintento y resultado final = ejecución sin fallos; matar el coordinador y reanudar ⇒ idéntico a ejecución ininterrumpida; reanudar con config/snapshot/código distintos ⇒ rechazo explícito | T1 / exacto | B5.4 |
| C-13 | Escritura parcial del diario | Truncar/corromper un shard: se detecta (hash/longitud), esa parte se re-ejecuta, el resto se conserva | exacto | B5.4 |
| C-14 | Tarea venenosa | Tarea que mata el proceso: queda `WORKER_CRASHED`, las vecinas del lote se completan tras la cuarentena | exacto | B5.4 |
| C-15 | Timeout/cancelación | Tarea que excede el plazo ⇒ `TIMED_OUT`; cancelación conserva lo completado y no envía más | exacto | B5.4 |
| C-16 | Fugas de recursos | Tras éxito, excepción y `kill -9`: sin segmentos `SharedMemory` ni ficheros temporales residuales; RSS por worker acotado tras N tareas | umbral configurable (medido) | B5.3/B5.5 |
| C-17 | Sobresuscripción | En cada worker `threadpool_info()` reporta 1 hilo por librería; nº de hilos del SO por worker ≤ límite configurado | exacto | B5.2 |
| C-18 | Caché: clave | Mutar cada uno de los 10 componentes de la clave ⇒ *miss*; mismo `CompositionHash` con otra cartera actual ⇒ *miss*; cambio de `OptimizationHorizonYears` ⇒ *miss* | exacto | B5.3 |
| C-19 | Caché: efectividad | *hit* ⇒ 0 llamadas a `solve()`; el resultado servido es bit a bit el calculado | exacto | B5.3 |
| C-20 | Caché: corrección global | Caché on/off sobre cargas con duplicados ⇒ resultados idénticos | T1 | B5.3 |
| C-21 | Caché: límites | Expulsión al superar `max_entries`/bytes; métricas de aciertos/fallos coherentes | exacto | B5.3 |
| C-22 | Carga útil por tarea | Tamaño de la tarea serializada ≪ tamaño de Σ (PAR-005); no contiene matrices globales | umbral derivado (p. ej. < 1 % de `Σ`) | B5.2 |
| C-23 | No copia completa de Σ por cartera | `tracemalloc` en worker: ninguna asignación O(N²) por tarea (extiende PAR-006) | umbral derivado de N | B5.2 |
| C-24 | Regresión B1–B4 | Suite completa (1.482 pruebas + nuevas) idéntica antes/después; mypy/ruff | exacto | todas |
| C-25 | Arquitectura | Ningún import de DB/HTTP/agentes en `portfolio_engine`; ningún `os.cpu_count()` implícito (PAR-012); ningún `pickle.load` de ficheros externos | análisis estático | B5.4 |
| C-26 | Aislamiento de EXACT_MIP | Carril W5 con `threads=1`; un MIP largo no bloquea W0–W4 (latencia de otros lotes acotada) | medido | B5.4/B5.5 |
| C-27 | Entradas inválidas | Cartera inválida/inviable ⇒ resultado con estado `INFEASIBLE`/`FAILED_INPUT_VALIDATION`, lote intacto | exacto | B5.2 |
| C-28 | Equivalencia entre plataformas | Resultados de Windows/Intel vs Linux/Ryzen sobre las mismas 100 carteras | T1 | B5.5 |

### 7.3 Regresión de rendimiento (BEN-005, TST-005)

* Baseline versionado por `(clase, escala, host)` en `benchmarks/results/baselines/` con metadatos.
* `tests/performance/` (marcador `performance`) compara contra el baseline con umbral basado en la dispersión
  medida (`k × MAD`, `k` en configuración); un resultado fuera de umbral no falla por sí solo si el contador
  determinista (llamadas al solver/evaluaciones) cambió: en ese caso se señala cambio de **trabajo**, no de
  velocidad.
* Los tests de rendimiento no se ejecutan por defecto en CI; se activan por marcador. Por ello cualquier test
  «omitido» no cuenta como validación (regla del plan de pruebas).

---

## 8. Criterios de aceptación

| Criterio | Condición |
|---|---|
| Correctitud | C-01…C-15, C-17…C-27 pasan; equivalencia T1 en todas las comparaciones (T0 solo diagnóstico); diferencias de estado investigadas y documentadas |
| Integridad | Invariante de conteo al 100 %; sin pérdida ni duplicados en ninguna de las ejecuciones de E9/E10 |
| Rendimiento | Se **miden y publican** E1–E16 con metadatos. No se fijan metas de speedup antes de tener la línea base; tras ella se propondrán objetivos con su justificación (D-01, D-11). Un resultado de rendimiento sin equivalencia correcta no cuenta |
| Cobertura de escala | Se ejecutan 10, 100 y 1.200 carteras (DoD oficial) si los recursos lo permiten; 1.000/5.000/22.000 se ejecutan o se declaran explícitamente «no ejecutado» con motivo |
| Reproducibilidad | Cada resultado se puede regenerar con comando, semilla y commit registrados |
| Trazabilidad | `TRACEABILITY.md`/`CHANGELOG.md` actualizados con evidencia (rutas de los JSON) |
| Honestidad | Ninguna cifra sin ejecución real; los límites de las mediciones (una máquina, N repeticiones) constan en el informe |

---

## 9. Estructura de ficheros prevista (B5.5, sujeta a aprobación)

```
benchmark/suite.py            (scaling_benchmark: BatchSize, workers, modo de datos)
benchmark/regression.py       (compare_to_baseline, umbrales por MAD)
benchmarks/scripts/scaling.py (BEN-004)
benchmarks/scripts/scale_run.py (BEN-007 / GOV-012)
benchmarks/scripts/synthetic_portfolios.py (generador determinista)
benchmarks/results/*.json     (resultados con metadatos; baselines en benchmarks/results/baselines/)
tests/performance/test_performance_regression.py (TST-005)
tests/integration/test_determinism.py (PAR-008)
tests/unit/parallel/, tests/unit/cache/
```

---

## 10. Riesgos del propio plan de benchmarks y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Máquina de desarrollo (Windows/Intel) no representa Arsys (Ubuntu/Ryzen 3600, SQL Server compartido) | Medir en el servidor para decisiones de dimensionamiento; local solo para corrección y regresión de estructura |
| Tiempos bimodales | Contadores deterministas, mínimo+mediana, MAD, repeticiones aleatorizadas |
| Coste prohibitivo de 22.000 con W1 | Puerta de proyección (§3) y autorización explícita |
| Generador sintético no refleja carteras reales | Variedad de mandatos y degeneraciones; cuando se pueda (B6/fases posteriores) añadir cargas derivadas de datos reales **anonimizados**, previa autorización |
| Contención con SQL Server en pruebas en servidor | Ventana acordada; medir la carga previa; E12 simula contención sin tocar la base |
| Falsos positivos por ruido | Umbrales por MAD y confirmación con contadores |
