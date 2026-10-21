# REPORT_BLOCK_5_5 — Benchmarks reproducibles y preparación de la auditoría final del Bloque 5

Fecha: 2026-10-21. Rama: `block5-benchmarks-final-audit` (base `main` `8ceaf3a`, B5.4 integrado). Autor de la ejecución: Claude (Sonnet 5.5).
**Estado final: `FINAL_STATUS = READY_FOR_INDEPENDENT_AUDIT`** (justificación en §12). Sin merge, sin despliegue, sin acceso a Arsys/Oracle/SQL Server,
sin datos reales. **No se ejecutó ninguna carga de ≥ 1.000 carteras.**

> Todas las cifras de este informe proceden de ejecuciones reales cuyos JSON están versionados en `benchmarks/results/` con commit
> (árbol limpio), versiones, huella del host, comando y semilla (BEN-006; `tests/unit/benchmark/test_result_metadata.py` lo comprueba); las
> cifras de **Linux** proceden de las anotaciones públicas de la CI de GitHub (los artefactos y logs no son accesibles sin autenticación).
> Son mediciones **locales, de una sola máquina de desarrollo con la memoria saturada** (§3), con datos **sintéticos**. No son rendimiento
> de producción y no se extrapolan sin declararlo.

## 1. Alcance de la sesión (CLAUDE.md «Control de alcance»)

| Campo | Contenido |
|---|---|
| Bloque | 5.5 — benchmarks, regresión de rendimiento y preparación de la auditoría final del Bloque 5 |
| `RequirementID` afectados | CFG-012, BEN-001, BEN-002, BEN-004, BEN-005, BEN-006, BEN-007, TST-005, GOV-012 (+ evidencia sobre PAR-004/013, CCH-001…005, P-01…P-08) |
| Módulos permitidos | `benchmark/` (nuevos `regression.py`, `scaling.py`), `config/` (nuevo `scaling_config.py` y `default_benchmark.toml`, solo configuración de medida), `benchmarks/`, `tests/performance/`, `tests/integration/`, `tests/unit/benchmark/`, documentación y CI |
| Fuera de alcance (no tocado) | Solvers, algoritmos, formulaciones, tolerancias y tests existentes de B1–B4/B5.2–B5.4; `MASTER_SPEC.md`; SQL Server/Arsys/Oracle; cualquier carga ≥ 1.000 carteras; merge y despliegue |
| Excepción de `tests/unit/test_architecture_rules.py` | Una única entrada nueva en la lista de constantes con nombre (`SECONDS_PER_HOUR`, conversión de unidades), igual que hicieron B5.3/B5.4; no se relaja ninguna regla |

`git diff 8ceaf3a -- portfolio_engine/` solo añade `benchmark/regression.py`, `benchmark/scaling.py`, `config/scaling_config.py` y exportaciones en
dos `__init__.py`: **ningún módulo de B1–B4 ni de `parallel/`/`cache/` cambia**.

## 2. Baseline completo (paso 1) — antes de modificar nada

| Comprobación | Resultado | Evidencia |
|---|---|---|
| `pytest` (Windows 11, Python 3.13.6, worktree limpio de `8ceaf3a`) | **1946 passed, 10 skipped, 0 failed** en 1240 s (20 min 40 s) | salida de la ejecución; los 10 *skipped* son específicos de Linux/POSIX (`test_forkserver_linux`, `test_recovery_linux`, permisos POSIX, `/dev/shm`) |
| `mypy --strict portfolio_engine` | 0 errores (176 ficheros) | — |
| `ruff check .` / `ruff format --check` | limpios | — |
| CI Linux de `main` (`8ceaf3a`) | **success** (run `39486481589`, push a `main`) | API pública de Actions |

Incidencia del baseline (registrada, no ocultada): un primer intento de baseline con `-x` **falló** en
`test_killing_the_coordinator_mid_run_and_resuming_equals_an_uninterrupted_run` (espera de 240 s agotada) porque se ejecutó mientras yo
lanzaba sondas de CPU en paralelo (162 pruebas tardaron 707 s). Aislada, la prueba pasa en 29 s; el baseline definitivo se ejecutó solo, sin
`-x`, en un *worktree* limpio y sin carga concurrente.

## 3. Condiciones de medida (limitaciones que condicionan toda cifra)

| Aspecto | Valor |
|---|---|
| Host | Windows 11 Home 10.0.26200, Intel Core i7-13620H (10 núcleos físicos / 16 lógicos, SMT activo, híbrido P+E), 16,9 GB de RAM |
| Python y librerías | Python 3.13.6; numpy 2.5.3, scipy 1.18.1, osqp 1.1.3, clarabel 0.11.1, pyscipopt 6.2.1, threadpoolctl 3.7.0, psutil 7.2.2 |
| Hilos BLAS | 1 por worker (línea base, PAR-007); `OMP/OPENBLAS/MKL_NUM_THREADS` sin definir en el coordinador |
| **Presión de memoria** | **6,7–8,8 GB de swap en uso y 0,4–1,3 GB de RAM disponible al iniciar cada medición**, con 15–35 % de CPU de fondo (navegador y otras aplicaciones del usuario). Registrado en `metadata.host` de cada JSON |
| Variabilidad observada | El **mismo trabajo** (688.707 iteraciones de solver, 6.404 llamadas, mismo `snapshot_key`) tardó **29,8 s** en una campaña y **17,8 s** en otra (×1,67); el arranque de un pool `spawn` con 4 workers osciló entre 6,3 s y 30,5 s |
| Consecuencia | Los tiempos absolutos están inflados y son ruidosos; se informan **mínimo y mediana**, **contadores deterministas** (llamadas al solver, iteraciones, fronteras) y la comparación entre variantes **dentro de una misma campaña**. Las proyecciones llevan un factor ×1,67 explícito |
| No disponible | Linux local (WSL sin distribución; `forkserver` no existe en Windows): la evidencia de `forkserver` y de Linux procede de la CI de GitHub (§10). No se midió en Arsys (prohibido) |

## 4. Entregables

| Entregable | Fichero(s) |
|---|---|
| Configuración de benchmarks de escala (CFG-012) | `config/default_benchmark.toml`, `portfolio_engine/config/scaling_config.py` (`ScalingBenchmarkConfig`, mezclas `ENG-MIX-*`, repeticiones, tope D-12, umbral `k × MAD`) |
| Detección de deterioros (BEN-005) | `portfolio_engine/benchmark/regression.py` (`compare_to_baseline`, `k × MAD` derivado del baseline, guarda de host y de contador de trabajo, estadístico mín/mediana, baseline JSON versionado) |
| Aritmética de escalado y proyección (BEN-004/007) | `portfolio_engine/benchmark/scaling.py` (speedup, eficiencia, Karp–Flatt, modelo de coste del mix, `project_capacity` con rango y factor de extrapolación) |
| Generador sintético determinista | `benchmarks/scripts/synthetic_portfolios.py` (mayor resto + semilla; diversidad; carteras degeneradas) |
| Benchmark oficial de escalado (BEN-004) | `benchmarks/scripts/scaling.py` (secuencial / `spawn` / `forkserver` × workers × lote × hilos BLAS × modo de datos; T1, integridad y auditoría independiente de restricciones como puerta de validez) |
| Escalas y estimación (BEN-007, GOV-012) | `benchmarks/scripts/scale_run.py` (`run` con guarda D-12; `estimate` sin ejecutar) |
| Recuperación (E9/E16) | `benchmarks/scripts/recovery_bench.py` |
| Datos compartidos y caché (E4/E8) | `benchmarks/scripts/shared_data_cache.py` (B5.3; reejecutado sobre árbol limpio) |
| Perfilado (E1) | `benchmarks/scripts/profile_class.py` |
| Investigación H-1 | `benchmarks/scripts/h1_numerical_probe.py`, `INVESTIGATION_H1_B4.md` |
| Baselines y regresión (TST-005) | `benchmarks/scripts/{baseline,perf_reference}.py`, `benchmarks/results/baselines/`, `tests/performance/test_performance_regression.py` |
| Equivalencia entre plataformas (C-28) | `benchmarks/scripts/cross_platform_reference.py`, `…/baselines/cross_platform_reference.json`, `tests/integration/test_cross_platform_reference.py` |
| Pruebas | `tests/unit/benchmark/{test_regression_and_scaling,test_result_metadata}.py`, `tests/integration/test_benchmark_harness.py` |
| CI | `.github/workflows/ci.yml`: pasos «B5.5 cross-platform diagnostic», «B5.5 Linux benchmark evidence» y «B5.5 H-1 numerical probe» (siempre se ejecutan, anotaciones públicas); instala el extra `bench` (`psutil`) |
| Estimación de gran escala y decisiones | `BLOCK_5_5_LARGE_SCALE_PLAN.md` |

## 5. Correctitud: equivalencia T1, restricciones e integridad (condición de validez de toda medición)

Cada celda paralela de `scaling.py` se compara con la ejecución secuencial **antes** de aceptar su tiempo; una celda con diferencias o
violaciones no es válida y el script termina con error.

| Comprobación | Resultado en las 100 celdas paralelas medidas |
|---|---|
| Diferencias T1 frente a la secuencial (`\|Δ\| ≤ 1e-6`, estados de ejecución y de solver idénticos) | **0** |
| Diagnóstico T0 (igualdad exacta de cada `float` comparado, todas las repeticiones) | **0 flotantes distintos; `\|Δ\|` máx. = 0,0**: los resultados paralelos son idénticos bit a bit a los secuenciales en esta máquina |
| Auditoría independiente de restricciones (presupuesto, largo-solo, `MaxWeight`, coherencia `is_valid_solution`/`validation`) | **0 violaciones** en 208.452 soluciones revalidadas |
| Integridad (cada `TaskID` exactamente una vez; enviadas = Σ estados finales) | cumplida en todas las celdas (y en todos los escenarios de recuperación, §8) |
| Estados de solver | histograma idéntico secuencial↔paralelo (prueba `test_a_mixed_batch_in_a_real_pool_equals_the_sequential_run_under_t1`, C-08) |
| Mutación del auditor | pesos corrompidos a propósito (presupuesto, `MaxWeight`, negativos) son detectados (`test_the_independent_constraint_audit_detects_violations_in_mutated_results`) |
| Carteras degeneradas (C-27) | rutas `INFEASIBLE` (solver) y `FAILED_INPUT_VALIDATION` ejercitadas sin romper el lote |
| Regresión B1–B4 (C-24) | suite completa idéntica antes/después: §2 y §11 |
| Equivalencia Windows ↔ Linux (C-28) | referencia versionada (10 carteras, 565 soluciones) y prueba por cartera que la reproduce bajo T1: **9 de 10 carteras coinciden en Linux**; **1 cartera W1 diverge (hallazgo F-B55-1, abajo)** |

### 5.1 Hallazgo F-B55-1 — la búsqueda de candidatos de W1 no es idéntica entre plataformas (abierto, Medio)

**Qué se observó.** El lote de referencia (`ENG-MIX-BASE`, 10 carteras, semilla 7) se reprodujo en Linux (Ubuntu 22.04, Python 3.11.17, GitHub Actions; Xeon Platinum 8573C y
Xeon 6973P-C). 9 de las 10 carteras (W0, W2, W3, W4 y una de las dos W1) coinciden con Windows bajo T1 (estados y número de soluciones idénticos). La cartera
`W1-GLOBAL-NET-000005-0000` no: en Linux la búsqueda de candidatos devuelve **12 composiciones frente a 11** (260 frente a 240 soluciones), todas `OPTIMAL`. En las 11 composiciones
comunes el número de soluciones es el mismo y la diferencia máxima de pesos es **3,5·10⁻¹²** (≪ 1e-6): Linux es un **superconjunto** de Windows. A nivel de lote W1 de dos carteras, 506 llamadas al
solver (Linux, los dos Xeon) frente a 484 (Windows) y 49.012 frente a 46.934 iteraciones.

**Qué se sabe y qué no.** Es un cambio de *qué candidatos entran* (B3, `CandidateEngine` / `GlobalCandidateFrontierEngine`), no de la matemática de cada frontera ni del ejecutor
paralelo de B5 (en cada plataforma, paralelo ≡ secuencial con T1 = 0). Es compatible con una decisión de umbral/orden sensible al redondeo (empates en la puntuación del haz, presupuesto de
evaluaciones o deduplicación), pero **la causa no se ha determinado** y no se ha tocado ningún algoritmo ni tolerancia. No se ha podido comprobar en un runner EPYC (en los runs con pruebas ejecutadas los runners fueron Xeon).

**Tratamiento.** La prueba `test_cross_platform_reference.py` es por cartera y marca esa cartera `xfail` (no estricto) **solo fuera de Windows**, con la causa visible en el informe de pytest;
el baseline de trabajo (`perf_reference_work.json`) conserva ambas variantes observadas (484 y 506) y falla ante cualquier otra. C-28 queda **PARTIAL**. La remediación (decidir si el conjunto de
candidatos debe ser invariante a la plataforma y, si sí, estabilizar el criterio) es una fase B3 independiente.

## 6. Resultados de rendimiento

### 6.1 Clases W0–W5 puras — 10 carteras (secuencial, `spawn` con 1/2/4 workers)

| Clase | seq mín (s) | s/cartera | llam. solver | spawn w=1 (s) | w=2 (s) | w=4 (s) | speedup w=4 | efic. w=4 | p50 / p95 lat. (s) | RSS worker (MB) | dif. T1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| W0-GROSS-RISK | 0.536 | 0.054 | 220 | 7.59 | 7.15 | 8.44 | 0.06 | 0.02 | 0.049 / 0.058 | 165 | 0 |
| W0-NET-TARGET | 0.554 | 0.055 | 220 | 7.83 | 7.34 | 8.46 | 0.07 | 0.02 | 0.058 / 0.065 | 165 | 0 |
| W1-GLOBAL-NET | 12.253 | 1.225 | 2420 | 20.68 | 15.05 | 12.55 | 0.98 | 0.24 | 1.211 / 1.293 | 168 | 0 |
| W2-INDEPENDENT | 2.144 | 0.214 | 710 | 9.36 | 8.61 | 8.97 | 0.24 | 0.06 | 0.208 / 0.234 | 167 | 0 |
| W2-EXPECTED | 0.199 | 0.020 | 10 | 7.07 | 6.89 | 8.15 | 0.02 | 0.01 | 0.018 / 0.021 | 163 | 0 |
| W2-WORST-CASE | 0.239 | 0.024 | 10 | 7.43 | 7.30 | 8.29 | 0.03 | 0.01 | 0.021 / 0.024 | 163 | 0 |
| W2-STRESS | 0.182 | 0.018 | 10 | 7.42 | 7.33 | 7.97 | 0.02 | 0.01 | 0.016 / 0.017 | 164 | 0 |
| W3-MIN-CVAR | 0.287 | 0.029 | 20 | 7.63 | 6.99 | 8.30 | 0.03 | 0.01 | 0.028 / 0.033 | 166 | 0 |
| W4-ROBUST | 0.141 | 0.014 | 10 | 7.21 | 7.13 | 8.28 | 0.02 | 0.00 | 0.010 / 0.012 | 163 | 0 |
| W4-ROBUST-BOX | 0.143 | 0.014 | 10 | 7.36 | 7.60 | 8.05 | 0.02 | 0.00 | 0.012 / 0.013 | 163 | 0 |
| W4-MAX-SHARPE | 0.279 | 0.028 | 30 | 7.45 | 7.31 | 8.36 | 0.03 | 0.01 | 0.025 / 0.027 | 165 | 0 |
| W4-VOL-TARGET | 0.206 | 0.021 | 20 | 7.23 | 7.40 | 7.92 | 0.03 | 0.01 | 0.017 / 0.018 | 163 | 0 |
| W5-EXACT-MIP | 15.108 | 1.511 | 2540 | 22.97 | 16.98 | 14.03 | 1.08 | 0.27 | 1.501 / 1.571 | 184 | 0 |
| PIPELINE | 12.199 | 1.220 | 2470 | 20.28 | 15.23 | 13.00 | 0.94 | 0.23 | 1.268 / 1.342 | 170 | 0 |

A 10 carteras el **arranque del pool (≈ 7–8 s de `import` por `spawn`)** domina: solo W1, W5 y el pipeline compuesto (≥ 1,2 s por cartera) se
acercan al punto de equilibrio. Las clases baratas (W0, W3, W4: 0,01–0,06 s por cartera) son 16–60× más lentas en paralelo a esta escala. Esto
no es un defecto del ejecutor: es la sobrecarga fija del arranque que se amortiza con la carga (§6.3 y `BLOCK_5_5_LARGE_SCALE_PLAN.md`).

### 6.2 Clases W0–W5 puras — 100 carteras (secuencial y `spawn` con 4 workers)

| Clase | seq mín (s) | s/cartera | spawn w=4 mín (s) | speedup | eficiencia | inicio pool (s) | p50 / p95 / p99 latencia (s) | RSS worker máx (MB) | válida |
|---|---|---|---|---|---|---|---|---|---|
| W0-GROSS-RISK | 5.03 | 0.050 | 10.93 | 0.46 | 0.11 | 9.5 | 0.074 / 0.090 / 0.094 | 166 | True |
| W0-NET-TARGET | 6.27 | 0.063 | 11.71 | 0.53 | 0.13 | 8.9 | 0.078 / 0.116 / 0.124 | 167 | True |
| W1-GLOBAL-NET | 182.05 | 1.820 | 83.43 | 2.18 | 0.55 | 24.3 | 5.268 / 6.742 / 7.398 | 181 | True |
| W2-INDEPENDENT | 47.84 | 0.478 | 46.45 | 1.03 | 0.26 | 21.2 | 1.007 / 1.196 / 1.449 | 170 | True |
| W2-EXPECTED | 3.85 | 0.038 | 23.57 | 0.16 | 0.04 | 30.5 | 0.083 / 0.109 / 0.116 | 163 | True |
| W2-WORST-CASE | 4.99 | 0.050 | 24.27 | 0.21 | 0.05 | 21.3 | 0.089 / 0.123 / 0.129 | 163 | True |
| W2-STRESS | 3.44 | 0.034 | 23.48 | 0.15 | 0.04 | 21.4 | 0.054 / 0.086 / 0.090 | 164 | True |
| W3-MIN-CVAR | 4.61 | 0.046 | 8.33 | 0.55 | 0.14 | 8.6 | 0.014 / 0.020 / 0.021 | 167 | True |
| W4-ROBUST | 0.71 | 0.007 | 7.67 | 0.09 | 0.02 | 7.2 | 0.008 / 0.011 / 0.014 | 163 | True |
| W4-ROBUST-BOX | 0.76 | 0.008 | 7.48 | 0.10 | 0.03 | 7.2 | 0.007 / 0.011 / 0.012 | 163 | True |
| W4-MAX-SHARPE | 1.65 | 0.016 | 7.77 | 0.21 | 0.05 | 7.7 | 0.015 / 0.026 / 0.035 | 166 | True |
| W4-VOL-TARGET | 1.36 | 0.014 | 8.05 | 0.17 | 0.04 | 7.4 | 0.014 / 0.021 / 0.024 | 164 | True |
| W5-EXACT-MIP | 85.22 | 0.852 | 31.58 | 2.70 | 0.67 | 6.3 | 0.859 / 1.023 / 1.204 | 195 | True |
| PIPELINE | 63.80 | 0.638 | 32.43 | 1.97 | 0.49 | 7.7 | 0.740 / 0.901 / 0.994 | 181 | True |

Con 100 carteras W1 (2,18×) y W5 (2,70×) ya escalan; las demás siguen dominadas por el arranque. Los tiempos por cartera de esta tabla difieren
de los de 10 carteras (p. ej. W1: 1,82 frente a 1,23 s) por dos motivos medidos: las 100 carteras son otras (la mezcla de posiciones cambia con el
índice) y la campaña de 100 cayó en una fase lenta de la máquina (§3). Por eso las proyecciones usan rangos.

### 6.3 Mezcla de referencia `ENG-MIX-BASE` — 10 y 100 carteras, secuencial y `spawn`

| Carteras | Modo | Workers | mín (s) | mediana (s) | carteras/s (mín) | speedup (mín) | eficiencia | inicio pool (s) | p50 / p95 / p99 latencia (s) | RSS coord. / worker máx (MB) | USS worker (MB) | dif. T1 | viol. restricciones |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | sequential | 1 | 2.99 | 3.03 | 3.34 | 1.00 | – | – | 0.060 / 1.238 / 1.281 | 194 / – | – | – | – |
| 10 | spawn | 1 | 10.54 | 10.63 | 0.95 | 0.28 | 0.28 | 7.69 | 0.065 / 1.368 / 1.402 | 194 / 171 | 119 | 0 | 0 |
| 10 | spawn | 2 | 9.94 | 10.78 | 1.01 | 0.30 | 0.15 | 7.40 | 0.077 / 1.373 / 1.395 | 189 / 169 | 118 | 0 | 0 |
| 10 | spawn | 4 | 9.73 | 9.90 | 1.03 | 0.31 | 0.08 | 8.44 | 0.077 / 1.422 / 1.434 | 189 / 168 | 118 | 0 | 0 |
| 10 | forkserver | – | NO DISPONIBLE en Windows (start method no disponible en win32: ['spawn']) | | | | | | | | | | |
| 100 | sequential | 1 | 29.79 | 30.28 | 3.36 | 1.00 | – | – | 0.050 / 1.263 / 1.328 | 283 / – | – | – | – |
| 100 | spawn | 1 | 38.94 | 39.60 | 2.57 | 0.77 | 0.77 | 8.11 | 0.054 / 1.304 / 1.343 | 277 / 198 | 135 | 0 | 0 |
| 100 | spawn | 2 | 24.86 | 25.69 | 4.02 | 1.20 | 0.60 | 8.47 | 0.057 / 1.568 / 1.686 | 277 / 195 | 133 | 0 | 0 |
| 100 | spawn | 4 | 20.39 | 21.13 | 4.90 | 1.46 | 0.37 | 8.84 | 0.072 / 1.659 / 1.704 | 205 / 187 | 126 | 0 | 0 |
| 100 | forkserver | – | NO DISPONIBLE en Windows (start method no disponible en win32: ['spawn']) | | | | | | | | | | |

`forkserver` **no existe en Windows**; se midió en Linux (CI, §10).

**Escalado con más workers y tasas (BEN-002), 100 carteras `ENG-MIX-BASE`, campaña de rendimiento con contadores:**

| Modo | Workers | mín (s) | mediana (s) | carteras/s | fronteras/s | llamadas solver/s | speedup | eficiencia | fracción serie (Karp–Flatt) | inicio pool (s) | ocupación CPU | RSS coord. (MB) | RSS worker máx (MB) | RSS total pico (MB) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sequential | 1 | 17.80 | 17.91 | 5.62 | 16.4 | 360 | 1.00 | – | – | – | – | 260 | – | 260 |
| spawn | 1 | 27.16 | 27.40 | 3.68 | 10.7 | 236 | 0.66 | 0.66 | – | 7.4 | 0.73 | 259 | 198 | 455 |
| spawn | 2 | 15.91 | 16.78 | 6.29 | 18.4 | 403 | 1.12 | 0.56 | 0.79 | 7.0 | 0.56 | 260 | 191 | 634 |
| spawn | 4 | 12.06 | 12.39 | 8.29 | 24.2 | 531 | 1.48 | 0.37 | 0.57 | 7.1 | 0.41 | 173 | 187 | 880 |
| spawn | 8 | 10.61 | 10.87 | 9.43 | 27.5 | 604 | 1.68 | 0.21 | 0.54 | 6.9 | 0.22 | 171 | 183 | 1545 |

Contadores deterministas del lote: `{'frontier_solver_iterations': 688707, 'frontier_results': 292, 'solver_calls': 6404}`

Lectura: (a) el speedup con 4 workers es 1,48× y con 8 workers 1,68× (eficiencia 0,37 y 0,21): el límite no son los núcleos sino (i) el arranque
(≈ 7 s, constante), (ii) la **cola larga**: W1 supone 20 de 100 carteras pero ≈ 82 % del cómputo y cada tarea W1 dura ≈ 1,2 s, y (iii) la
planificación del coordinador; la fracción serie efectiva de Karp–Flatt baja de 0,79 (2 workers) a 0,54 (8) porque el arranque pesa menos.
(b) Descontando el arranque, la eficiencia en régimen estacionario con 4 workers es **0,64** (primera campaña) a **0,90** (campaña de tasas) y con 8 workers 0,59 (una medición); es la que usa la proyección, con ese rango.
(c) Con 8 workers el pico agregado de RSS es 1,5 GB: en una máquina con 0,4–1,3 GB libres cada worker extra empeora el swap.

### 6.4 Modelo de coste del mix y sensibilidad (E17)

El modelo `T_seq = N · Σ sᵢ · cᵢ` del plan (§2.4), con `cᵢ` medido en las clases puras a 10 carteras, **predice la ejecución secuencial real de
las cuatro mezclas con un error de −1,3 % a +1,3 %** (misma campaña, mismas fases de la máquina):

| Mezcla | N | T_seq predicho (s) | T_seq medido, mín (s) | error relativo |
|---|---|---|---|---|
| ENG-MIX-BASE | 10 | 2.95 | 2.99 | -1.3 % |
| ENG-MIX-BASE | 100 | 30.06 | 29.79 | +0.9 % |
| ENG-MIX-CONIC | 100 | 16.50 | 16.29 | +1.3 % |
| ENG-MIX-HEAVY | 100 | 66.11 | 66.59 | -0.7 % |
| ENG-MIX-LIGHT | 100 | 12.28 | 12.32 | -0.3 % |

Contribución de cada clase al tiempo secuencial de ENG-MIX-BASE a 100 carteras (cᵢ medidos a 10 carteras):

| Clase | carteras | s/cartera | contribución |
|---|---|---|---|
| W1-GLOBAL-NET | 20 | 1.225 | 81.5 % |
| W5-EXACT-MIP | 1 | 1.511 | 5.0 % |
| W0-NET-TARGET | 20 | 0.055 | 3.7 % |
| W0-GROSS-RISK | 20 | 0.054 | 3.6 % |
| W2-INDEPENDENT | 5 | 0.214 | 3.6 % |
| W3-MIN-CVAR | 10 | 0.029 | 1.0 % |
| W4-MAX-SHARPE | 5 | 0.028 | 0.5 % |
| W2-WORST-CASE | 4 | 0.024 | 0.3 % |
| W4-VOL-TARGET | 4 | 0.021 | 0.3 % |
| W2-EXPECTED | 4 | 0.020 | 0.3 % |
| W4-ROBUST | 5 | 0.014 | 0.2 % |
| W2-STRESS | 2 | 0.018 | 0.1 % |

Conclusión de sensibilidad: **W1 domina el coste** (82 % del tiempo de `ENG-MIX-BASE` con el 20 % de las carteras); `ENG-MIX-HEAVY` (50 % W1) cuesta
5,4× más que `ENG-MIX-LIGHT` con la misma N. Cualquier plan de capacidad debe empezar por **qué fracción de carteras ejecuta W1/W5** (D-01), no por
el número total. Perfilado (E1, `profile_class.py`, tiempo propio por origen; el perfilador añade sobrecoste, solo reparto relativo):

| Clase | motor (portfolio_engine) | scipy | numpy | solver nativo / bibliotecas | intérprete (builtins) | resto (stdlib, pandas, otros) |
|---|---|---|---|---|---|---|
| W0-NET-TARGET | 19 % | 30 % | 5 % | 8 % | 26 % | 13 % |
| W1-GLOBAL-NET | 30 % | 42 % | 7 % | 3 % | 14 % | 4 % |
| W3-MIN-CVAR | 7 % | 47 % | 4 % | 0 % | 28 % | 14 % |
| W4-MAX-SHARPE | 8 % | 50 % | 7 % | 0 % | 26 % | 10 % |
| W5-EXACT-MIP | 34 % | 39 % | 6 % | 2 % | 14 % | 5 % |

La hipótesis de `BLOCK_5_HPC_ARCHITECTURE.md` §4.4 («82–88 % en Python» en W1) **no se confirma con esta definición de origen**: el código propio del
motor es el 19–34 % del tiempo propio en W0/W1/W5 y el resto es SciPy (matrices dispersas, `linprog`, álgebra: 30–50 %) y llamadas nativas
(*builtins*, entre ellas los solvers: 14–28 %). Se informa tal cual; no se ha optimizado nada.

### 6.5 Tamaño de lote (E3/E13) e hilos BLAS (E6) — 100 carteras `ENG-MIX-BASE`, 4 workers

| Lote | efectivo | nº de lotes | mín (s) | mediana (s) | speedup | p95 latencia (s) | ocupación CPU |
|---|---|---|---|---|---|---|---|
| 1 | 1 | 100 | 20.09 | 20.14 | 1.47 | 1.697 | 0.49 |
| 5 | 5 | 20 | 20.08 | 20.09 | 1.47 | 1.605 | 0.48 |
| 10 | 10 | 10 | 24.43 | 24.54 | 1.21 | 1.559 | 0.37 |
| 20 | 20 | 5 | 34.73 | 35.04 | 0.85 | 1.296 | 0.23 |
| AUTO | 7 | 15 | 20.34 | 20.45 | 1.45 | 1.685 | 0.48 |

Con una mezcla con cola larga, lotes grandes perjudican (lote 20 ⇒ +72 % de tiempo, 5 lotes para 4 workers); lotes de 1–5 y el modo AUTO
(efectivo 7) son equivalentes dentro de ±1,5 %. **AUTO es aceptable para esta mezcla** pero no está calibrado frente a una distribución de
costes real: la recomendación se limita a *no superar el tamaño que deje menos de ~4 lotes por worker* hasta medir con cargas reales.

| Hilos BLAS | mín (s) | mediana (s) | carteras/s | RSS worker máx (MB) |
|---|---|---|---|---|
| 1 (línea base) | 20.39 | 21.13 | 4.90 | 187 |
| 2 | 20.68 | 20.97 | 4.84 | 188 |

2 hilos BLAS por worker **no aportan** (4,90 → 4,84 carteras/s, dentro del ruido): se mantiene 1 (PAR-007).

### 6.6 Memoria y crecimiento con el número de tareas (E10 parcial)

Memoria por proceso (tablas 6.1–6.3): worker **RSS 163–198 MB (USS 119–135 MB)**, coordinador **RSS 173–283 MB**, pico agregado **455 MB (1 worker) →
880 MB (4) → 1.545 MB (8)**. Crecimiento con el número de tareas (1 worker, 100 → 300 tareas por clase):

| Clase | Tareas | s/cartera (secuencial) | p50 / p95 / p99 latencia (s) | RSS worker máx (MB) | USS worker máx (MB) | RSS coordinador (MB) |
|---|---|---|---|---|---|---|
| W0-NET-TARGET | 100 | 0.0377 | 0.0368 / 0.0579 / 0.0808 | 171 | 121 | 199 |
| W0-NET-TARGET | 300 | 0.0393 | 0.0381 / 0.0594 / 0.0810 | 175 | 125 | 160 |
| W3-MIN-CVAR | 100 | 0.0181 | 0.0174 / 0.0228 / 0.0252 | 169 | 119 | 162 |
| W3-MIN-CVAR | 300 | 0.0184 | 0.0185 / 0.0239 / 0.0269 | 170 | 120 | 168 |

El coste por cartera no deriva (±4 %) y el RSS del worker crece 1–4 MB al triplicar las tareas: **sin señal de fuga a esta escala**. Es evidencia
**insuficiente** para el criterio de P-02/E10 (1.000 → 5.000 tareas, RSS del coordinador independiente del total), que exige autorización (D-12).

### 6.7 Datos compartidos (E4) y caché (E8)

| Universo | Modo | Workers | Pool listo (s) mín – mediana – máx | Publicar (ms) | Adjuntar máx (ms) | Handle (B) | RSS worker (MB) | USS worker (MB) |
|---|---|---|---|---|---|---|---|---|
| 50 | BUNDLE_FILE | 1 | 6.6 – 6.7 – 6.9 | 7 | 48 | 228 | 162 | 113.3 |
| 50 | FILE_MMAP | 1 | 6.6 – 6.6 – 7.0 | 16 | 80 | 559 | 162 | 113.7 |
| 50 | SHARED_MEMORY | 1 | 6.8 – 6.9 – 6.9 | 14 | 67 | 504 | 162 | 113.5 |
| 50 | BUNDLE_FILE | 2 | 6.4 – 7.6 – 8.0 | 7 | 46 | 228 | 161 | 113.3 |
| 50 | FILE_MMAP | 2 | 7.0 – 7.0 – 7.3 | 16 | 78 | 559 | 162 | 113.6 |
| 50 | SHARED_MEMORY | 2 | 6.4 – 6.6 – 6.8 | 13 | 56 | 504 | 162 | 113.3 |
| 50 | BUNDLE_FILE | 4 | 7.8 – 7.9 – 7.9 | 8 | 43 | 228 | 162 | 113.3 |
| 50 | FILE_MMAP | 4 | 7.7 – 7.7 – 8.0 | 18 | 81 | 559 | 162 | 113.3 |
| 50 | SHARED_MEMORY | 4 | 7.7 – 7.8 – 8.0 | 15 | 59 | 504 | 162 | 113.3 |
| 500 | BUNDLE_FILE | 1 | 2.1 – 3.4 – 3.4 | 8 | 21 | 228 | 165 | 116.9 |
| 500 | FILE_MMAP | 1 | 4.7 – 7.7 – 7.7 | 46 | 100 | 559 | 165 | 113.5 |
| 500 | SHARED_MEMORY | 1 | 1.8 – 3.4 – 5.9 | 8 | 27 | 504 | 166 | 113.9 |
| 500 | BUNDLE_FILE | 2 | 3.5 – 7.1 – 7.6 | 27 | 61 | 228 | 166 | 117.2 |
| 500 | FILE_MMAP | 2 | 1.8 – 4.9 – 5.0 | 12 | 33 | 559 | 165 | 113.9 |
| 500 | SHARED_MEMORY | 2 | 3.7 – 4.2 – 7.0 | 30 | 77 | 504 | 165 | 113.8 |
| 500 | BUNDLE_FILE | 4 | 8.0 – 8.4 – 8.9 | 37 | 62 | 228 | 165 | 117.1 |
| 500 | FILE_MMAP | 4 | 2.7 – 5.7 – 10.2 | 55 | 110 | 559 | 165 | 113.8 |
| 500 | SHARED_MEMORY | 4 | 2.2 – 3.9 – 7.6 | 10 | 29 | 504 | 165 | 113.7 |

`BUNDLE_FILE`, `FILE_MMAP` y `SHARED_MEMORY` dan resultados idénticos (T1 = 0, sin residuos en las 18 celdas). Adjuntar cuesta 20–110 ms por worker; el
ahorro de memoria privada es del orden del tamaño de los datos (≈ 3 MB con N = 500); no hay ventaja de arranque medible (el tiempo hasta pool listo
va de 1,8 s a 10,2 s por la variabilidad del arranque, no por el modo). Se mantiene `BUNDLE_FILE` por defecto, como justificó B5.3.

| Repetidas k | Duplicadas | Llamadas solver (off → on) | Aciertos / fallos | mín off (s) | mín on (s) | speedup | dif. T1 |
|---|---|---|---|---|---|---|---|
| 1 | 0 % | 264 → 264 | 0 / 12 | 0.70 | 0.77 | 0.92 | 0 |
| 2 | 50 % | 528 → 264 | 12 / 12 | 1.45 | 0.78 | 1.85 | 0 |
| 4 | 75 % | 1056 → 264 | 36 / 12 | 2.75 | 0.88 | 3.13 | 0 |

La caché **no ayuda sin duplicados** (k = 1: 0 aciertos y +9 % de tiempo, 0,92×) y elimina exactamente las llamadas duplicadas con ellos (264 y 792 llamadas
evitadas; 1,85× y 3,13×): sigue **desactivada por defecto**, coherente con CCH-001.

### 6.8 Recuperación ante fallos (E9/E16), 12 carteras W0, 2 workers, procesos reales

| Escenario | mín (s) | mediana (s) | sobrecoste vs. limpia (s) | crashes / reintentos aislados / venenosas / plazos | estados finales | comprobaciones |
|---|---|---|---|---|---|---|
| clean | 8.31 | 8.89 | +0.00 | 0 / 0 / 0 / 0 | {'COMPLETED': 12} | válidas |
| clean_journal | 8.43 | 8.55 | +0.12 | 0 / 0 / 0 / 0 | {'COMPLETED': 12} | válidas |
| worker_killed_once | 21.94 | 22.99 | +13.63 | 1 / 2 / 0 / 0 | {'COMPLETED': 12} | válidas |
| poison_task | 29.62 | 30.40 | +21.31 | 3 / 3 / 1 / 0 | {'COMPLETED': 11, 'WORKER_CRASHED': 1} | válidas |
| hanging_task | 10.13 | 10.41 | +1.82 | 0 / 0 / 0 / 1 | {'COMPLETED': 11, 'TIMED_OUT': 1} | válidas |
| cancel_then_resume | 8.03 | 8.43 | -0.28 | 0 / 0 / 0 / 0 | {'COMPLETED': 8, 'SKIPPED_BY_RESUME': 4} | válidas |
| ↳ cancel_then_resume | cancelación: 0.60 s; 1.ª ejecución 8.48 s; reanudación 8.03 s | | | | | tareas rehechas: 8 |
| corrupt_shard_then_resume | 8.01 | 8.09 | -0.30 | 0 / 0 / 0 / 0 | {'COMPLETED': 10, 'SKIPPED_BY_RESUME': 2} | válidas |
| ↳ corrupt_shard_then_resume | cancelación: 0.61 s; 1.ª ejecución 8.42 s; reanudación 8.01 s | | | | | tareas rehechas: 10 |

Lectura: el diario cuesta **+0,12 s** sobre 12 carteras (≈ 1 %). Una muerte de worker cuesta ≈ **+13,6 s** (un pool nuevo ≈ 7–8 s más los reintentos aislados) y una
tarea venenosa ≈ **+21 s** (3 reconstrucciones); un cuelgue con plazo de 3 s se resuelve con **+1,8 s** y no reconstruye el pool; la cancelación responde en
**0,6 s**; la reanudación rehízo exactamente las tareas no persistidas (8 de 12; 10 de 12 con un shard dañado, que contenía 2 tareas) y el resultado
final coincidió con la ejecución ininterrumpida bajo T1. Todas las comprobaciones de integridad pasaron en las 3 repeticiones de cada escenario.

### 6.9 Dimensión realista (E15): 20 posiciones por cartera, universo 50 / 200 / 700

| Clase | s/cartera U=50 | U=200 | U=700 | llamadas solver/cartera | RSS worker máx U=700 (MB) | T1 y restricciones |
|---|---|---|---|---|---|---|
| W0-GROSS-RISK | 0.036 | 0.035 | 0.032 | 22 | 175 | 0 dif. / 0 viol. |
| W0-NET-TARGET | 0.068 | 0.073 | 0.059 | 22 | 175 | 0 dif. / 0 viol. |
| W1-GLOBAL-NET | 2.678 | 2.975 | 3.266 | 264 | 183 | 0 dif. / 0 viol. |
| W3-MIN-CVAR | 0.029 | 0.033 | 0.032 | 2 | 177 | 0 dif. / 0 viol. |
| W4-ROBUST | 0.016 | 0.014 | 0.013 | 1 | 170 | 0 dif. / 0 viol. |
| W4-MAX-SHARPE | 0.021 | 0.021 | 0.021 | 3 | 177 | 0 dif. / 0 viol. |
| W4-VOL-TARGET | 0.021 | 0.017 | 0.020 | 2 | 171 | 0 dif. / 0 viol. |

Con 20 posiciones, **W1 cuesta 2,7–3,3 s por cartera** y sube solo un 22 % al pasar de 50 a 700 activos del universo; el resto de clases cuesta
0,013–0,075 s. Es el dato que sustenta las proyecciones realistas. Límites: solo 3 carteras por clase (2 repeticiones), solo las clases W0/W1/W3/W4
(los escenarios de W2 y el MIP de W5 de los fixtures están ligados a 8 activos), y cada W1 medido es una única composición de 20 posiciones: **el
intervalo real será más ancho que el mostrado**. La medición exploratoria de B5.1 (≈ 6–7 s por W1) es ≈ 2× mayor que la actual, dentro del orden de la
variación de fase observada (§3).

## 7. H-1 — fragilidad numérica de B4 (investigada, no modificada)

Ver `INVESTIGATION_H1_B4.md`. Resumen: el mecanismo reproducible es que la tolerancia cónica configurada (1e-9) está en el borde de lo alcanzable en el
problema degenerado del primer test; una perturbación de **1 ulp** hace que solo el 47 % de las resoluciones terminen `OPTIMAL` (el resto `AlmostSolved` ⇒
`OPTIMAL_INACCURATE` ⇒ rechazadas por `accept_inaccurate_solutions = false`, con pesos correctos); con 3e-9 o 1e-8 el 100 % (0 de 1.200 degradadas). El segundo
test falla por el criterio de éxito de su oráculo SLSQP (`ftol = 1e-15`: 67–76 % de éxito con puntos iniciales perturbados; 100 % con `ftol ≥ 1e-12`; mismo
mensaje que CI). **Ningún algoritmo, tolerancia ni test se cambió**; la remediación es una fase B4 independiente (propuesta en el documento). Observaciones de
la CI de Linux: §10.

## 8. Regresión de rendimiento (BEN-005, TST-005)

* `benchmarks/results/baselines/perf_reference_work.json` fija el **trabajo determinista** (llamadas al solver e iteraciones) de 7 celdas de referencia;
  `perf_reference_<huella>.json` fija los tiempos de **este host** (mínimo de 7 repeticiones tras calentamiento).
* `tests/performance/test_performance_regression.py` (en la suite por defecto): el trabajo de cada celda coincide con el baseline (llamadas exactas;
  iteraciones con la tolerancia relativa **configurada**), el baseline cubre las celdas y declara su procedencia, y la detección sobre el baseline real
  distingue un tiempo ×3 (`SLOWER`), el mismo tiempo (`WITHIN_NOISE`) y un cambio de contador (`WORK_CHANGED`, no un juicio de velocidad).
* La comparación de **tiempos** es opt-in (`PE_RUN_TIMING_REGRESSION=1`, mínimo de repeticiones frente a `k × MAD` del baseline, confirmación en hasta 3 rondas
  antes de fallar) porque solo vale en el mismo host y la máquina es bimodal. **Se ejecutó una vez en este host: pasó.** Si el host no coincide, la prueba se
  omite y esa omisión **no cuenta como validación** (queda dicho en su docstring).

## 9. Estado de los requisitos (solo estados verificables)

Recuento contractual tras B5.5: **316 `RequirementID` = 244 `VALIDATED` / 39 `PARTIAL` / 33 `NOT_IMPLEMENTED` / 0 `IMPLEMENTED`** (antes 238 / 42 / 36 / 0; verificado
contando las filas de `TRACEABILITY.md`). Ningún requisito pasa a `VALIDATED` sin una prueba de aceptación que pasa de verdad.

| Requisito | Antes | Ahora | Evidencia | Por qué no más |
|---|---|---|---|---|
| CFG-012 | PARTIAL | **VALIDATED** | `ScalingBenchmarkConfig` con carga estricta y validación; tres pruebas de configuración | — |
| BEN-002 | PARTIAL | **VALIDATED** | media, p50/p95/p99, máx., mín./mediana, carteras/s, fronteras/s y llamadas al solver/s medidos (`…_rates_*.json`); prueba de las tasas y de los percentiles con oráculo manual | — |
| BEN-004 | PARTIAL | **VALIDATED** | workers {1, 2, 4, 8}; lote {1, 5, 10, 20, AUTO}; modos secuencial/`spawn`/`forkserver` (Linux en CI); hilos BLAS {1, 2}; modos de datos compartidos; 100 celdas paralelas con T1 = 0 y 0 violaciones | Medido en una máquina local y en runners de CI; **no en Arsys** (prohibido). El módulo `scaling_benchmark` previsto se materializó como script + funciones puras |
| BEN-005 | NOT_IMPLEMENTED | **VALIDATED** | `benchmark/regression.py` + pruebas unitarias + `tests/performance/test_performance_regression.py` | La comparación de **tiempos** es opt-in (ejecutada una vez: pasó); la de trabajo corre siempre |
| TST-005 | NOT_IMPLEMENTED | **VALIDATED** | `tests/performance/` (trabajo determinista frente a baseline versionado con variantes de plataforma; detección sobre el baseline real) | idem |
| PAR-003 | PARTIAL | **VALIDATED** | barrido de lote: AUTO (efectivo 7) dentro de ±1,5 % del mejor en `ENG-MIX-BASE`; lotes 10 y 20 pierden +21 % y +72 % | Calibración solo para esa mezcla sintética |
| BEN-001 | PARTIAL | PARTIAL | + arranque del pool, IPC (tamaños y ida-vuelta de serialización), `PortfolioTotal` por tarea/operación y perfilado por origen | Faltan `DataLoad`/`RiskModel` dentro del harness y `Staging`/`Database` (B6) |
| BEN-006 | PARTIAL | PARTIAL | metadatos completos en cada JSON de B5.5, comprobados por `test_result_metadata.py` | `RunMetadata` formal es de B6; los resultados históricos de B2/B3 conservan su subconjunto |
| BEN-007 | NOT_IMPLEMENTED | **PARTIAL** | 10 y 100 carteras ejecutadas y validadas; guarda D-12 probada; estimación de 1.000/1.200/5.000/22.000 | **1.200 carteras (DoD oficial) no ejecutada**: requiere autorización expresa |
| GOV-012 | PARTIAL | PARTIAL | costes por clase a 8 activos y a 20 posiciones con universo 50/200/700; modelo de coste del mix (±1,3 %); proyección con rango | Escala objetivo proyectada, no ejecutada; W2 y W5 sin medir a dimensión realista |
| PAR-013, PAR-004, CCH-001…005, CFG-011 | sin cambio | sin cambio | Reejecutados en Linux (CI) y en Windows sin regresión (§11) | PAR-013 sigue `PARTIAL` (su cierre depende de la re-auditoría de B5.4, ajena a B5.5) |

Requisitos propuestos P-xx (no oficiales, D-05): **P-02 PARTIAL** (cola acotada probada; RSS del coordinador medido solo hasta 300 tareas, el criterio de 5.000 no se ejecutó),
**P-08 PARTIAL** (los benchmarks registran commit y `dirty`; la biblioteca no invoca `git`), el resto sin cambio respecto a `BLOCK_5_IMPLEMENTATION_PLAN.md` §10.

Pruebas del catálogo C-xx de `BLOCK_5_BENCHMARK_PLAN.md` §7.2 con evidencia nueva en B5.5: C-01/C-08 (mezcla en pool real), C-07 (auditor + mutación), C-16
(crecimiento 100→300 tareas), C-26 (W5 en el lote), C-27 (degeneradas), C-12/C-13/C-14/C-15 (tiempos de recuperación) y **C-28 (PARTIAL: F-B55-1)**.

## 10. CI en Linux

No hay `gh` ni PR de B5.5: la CI (`ci.yml`) solo se dispara con PR o push a `main`, así que se añadió **temporalmente** `block5-benchmarks-final-audit` a `push.branches`
(precedente: `b53-branch-ci.yml`); el disparador se retira al cerrar la fase. Los logs de Actions no son públicos sin autenticación; las **anotaciones sí** (API de *check-runs*), y los
pasos de B5.5 publican en ellas lo esencial.

| Commit | Run | Resultado | Runner | Detalle |
|---|---|---|---|---|
| `8ceaf3a` (`main`) | `39486481589` | **success** | — | baseline de CI (merge de B5.4) |
| `f650607` | `39525414018` | **failure** | EPYC 7763 | 3 errores de **colección** (0 pruebas ejecutadas): `psutil` está en el extra opcional `bench` y la CI instalaba `[dev,exact-mip]`. Defecto mío, corregido añadiendo `bench` a la instalación |
| `6a8e79b` | `39525647162` | failure | Xeon 8573C | 1989 passed, **2 failed**: las dos comprobaciones nuevas de C-28 (§5.1) |
| `0e05505` | `39526528068` | failure | Xeon 6973P-C | idéntico; añade diagnósticos de divergencia y de contadores de trabajo |
| `933c0cc` | `39527318745` | **success** | Xeon 8573C (4 vCPU, SMT) | **2004 passed, 3 skipped, 1 xfailed** en 4 min 33 s; el *xfailed* es F-B55-1 |

Evidencia de Linux de B5.5 (run `39527318745`, Python 3.11.17):

* **Benchmark de escala 10 (`ENG-MIX-BASE`)**: secuencial 0,66 s; `spawn` 1 worker 2,04 s (pool listo en 1,34 s) y 2 workers 1,97 s; **`forkserver` 1,78 s (1,12 s) y 1,72 s**.
  Todas las celdas `valida=True`, T1 = 0, restricciones limpias. En Linux el arranque es 5–6× más rápido que en esta Windows (7–8 s) y `forkserver` gana un 13–16 % a `spawn`.
  Siguen valiendo las cautelas: 10 carteras, runner compartido de 4 vCPU.
* **Pruebas de B5.4 en Linux** (`forkserver`, `flock`, permisos, zombis, limpieza): 56 passed.
* **Sonda de H-1 en el Xeon 8573C** (§7): con la tolerancia cónica configurada, validez 1,00 / 0,47 / 0,45 / 0,37 / 0,27 / 0,02 para perturbaciones 0 / 1e-16 / 1e-15 / 1e-14 / 1e-12 / 1e-10; con 3e-9 y 1e-8,
  1,00 en todas; SLSQP `ftol=1e-15`: 0,73–0,80 con puntos iniciales perturbados. **El mecanismo de H-1 se reproduce en Linux/Intel**, no solo en Windows. En los runs en que se ejecutaron
  pruebas los runners fueron Xeon (8573C ×2, 6973P-C); el único EPYC 7763 sorteado (`f650607`) falló en la colección sin ejecutar nada. **Por tanto el fallo original de H-1 (CPU EPYC 7763) no se ha vuelto a observar** ni se ha podido descartar en esa CPU.
* **Divergencia W1** (F-B55-1): 12 composiciones frente a 11, `|Δpeso|` ≤ 3,5·10⁻¹² en las comunes; 506 frente a 484 llamadas al solver.

El paso final retira el disparador temporal; el SHA que queda como cabeza de la rama difiere del último SHA probado solo en ese cambio de `ci.yml` y en documentación.

## 11. Gate final

| Comprobación | Resultado |
|---|---|
| `pytest` Windows 11 / Python 3.13.6, `933c0cc` (worktree limpio, sin carga concurrente). Los commits posteriores solo tocan el estimador `scale_run.py`, documentación y CI; los ficheros de pruebas nuevos se reejecutaron sobre la cabeza final (239 passed, 1 skipped en `tests/unit/benchmark`, `tests/performance`, el harness, la referencia multiplataforma, las reglas de arquitectura y la configuración) | **1994 passed, 11 skipped, 0 failed** (16 min 09 s) |
| `pytest` baseline (`8ceaf3a`) | 1946 passed, 10 skipped |
| Diferencia frente al baseline | solo pruebas **nuevas** (+metadatos, +regresión de rendimiento, +harness, +plataformas, +unitarias de `benchmark/`) y +1 *skipped* (comparación de tiempos opt-in); **ninguna prueba previa cambió de resultado** |
| `pytest` Linux (CI `39527318745`, `933c0cc`, Ubuntu 22.04 / Python 3.11.17 / Xeon 8573C) | **2004 passed, 3 skipped, 1 xfailed** (4 min 33 s); xfail = F-B55-1 |
| `mypy --strict portfolio_engine` | 0 errores (179 ficheros); Linux: paso «Static checks» ✔ |
| `ruff check .` y `ruff format --check .` | limpios en Windows y en Linux |
| Reglas de arquitectura (`test_architecture_rules.py`) | pasan; una entrada nueva en la lista de constantes con nombre (`SECONDS_PER_HOUR`) |
| Módulos de B1–B5.4 modificados | **ninguno** (`git diff 8ceaf3a -- portfolio_engine/` solo añade `benchmark/{regression,scaling}.py`, `config/scaling_config.py` y exportaciones) |
| Tests existentes desactivados o relajados | **ninguno**; tolerancias y solvers sin cambios |

Archivos modificados o añadidos (resumen): configuración de medida (`config/default_benchmark.toml`, `config/scaling_config.py`); biblioteca (`benchmark/regression.py`, `benchmark/scaling.py`, exportaciones);
`benchmarks/scripts/` (11 scripts nuevos); `tests/` (harness, regresión de rendimiento, metadatos, plataformas, fixtures); `benchmarks/results/` (21 resultados y 3 baselines); `.github/workflows/ci.yml`,
`pyproject.toml` (comentario del extra `bench`); documentación (`REPORT_BLOCK_5_5.md`, `BLOCK_5_5_LARGE_SCALE_PLAN.md`, `INVESTIGATION_H1_B4.md`, `TRACEABILITY.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, `BLOCK_5_IMPLEMENTATION_PLAN.md`).

## 12. Estado final, pendientes y decisiones

### 12.1 Lo que NO se ha hecho (declarado, no omitido)

| Elemento | Motivo |
|---|---|
| Cargas de 1.000 / 1.200 / 5.000 / 22.000 carteras | Prohibidas sin autorización expresa (D-12); estimación y guardas listas (`BLOCK_5_5_LARGE_SCALE_PLAN.md`) |
| Cualquier medición en Arsys, Oracle o SQL Server; datos reales | Prohibido por la instrucción |
| E5 `fork`, E7 hilos de solver, E11 SMT/afinidad, E12 coexistencia con carga ajena, E14 barrido de nº de escenarios | Fuera de las mediciones pedidas o dependientes del servidor; no se inventa ninguna cifra |
| E10 hasta 1.000 → 5.000 tareas (fugas, RSS del coordinador) | Cargas ≥ 1.000: requiere autorización; solo 100 → 300 tareas |
| W2 y W5 a 20 posiciones y universo 700 | Los fixtures de escenarios y el MIP están ligados a 8 activos; adaptarlos excede el alcance (D-I del plan) |
| `forkserver` en Windows | No existe en Windows; medido en Linux por CI (§10) |
| Remediaciones de H-1 (B4) y de F-B55-1 (B3) | Prohibido cambiar algoritmos o tolerancias sin una remediación independiente |
| Auditoría independiente | Es el paso siguiente; este informe y sus oráculos son míos |

### 12.2 Hallazgos nuevos y pendientes

| ID | Severidad | Descripción | Estado |
|---|---|---|---|
| F-B55-1 | Medio | La búsqueda de candidatos de W1 devuelve una composición más en Linux que en Windows en una de las dos carteras W1 de la referencia (§5.1) | Abierto; documentado, probado con `xfail` no estricto fuera de Windows; remediación B3 independiente |
| H-1 | Alto (preexistente, B4) | Tolerancia cónica 1e-9 en el borde de lo alcanzable + oráculo SLSQP `ftol=1e-15` (`INVESTIGATION_H1_B4.md`) | Mecanismo reproducido en Windows y Linux; **no remediado** |
| F-B55-2 | Informativo | El arranque `spawn` en Windows (7–30 s por pool) domina cargas de ≤ 100 carteras baratas; en Linux 1,1–1,4 s | Sin acción en B5; conviene `forkserver` en el servidor Linux |
| F-B55-3 | Informativo | El speedup está limitado por la cola larga de W1/W5 (4 workers: 1,5×; 8: 1,7× a 100 carteras); el orden por coste (LPT) previsto en el plan no puede aplicarse sin coste previo por cartera | Sin acción; relevante para dimensionar workers |
| Entorno | Limitación | Medido con 6,7–8,8 GB de swap en uso: tiempos absolutos inflados (×1,67 observado) | Repetir en una máquina dedicada antes de fijar objetivos de rendimiento |

### 12.3 Decisiones necesarias (detalle y recomendaciones en `BLOCK_5_5_LARGE_SCALE_PLAN.md` §6)

1. **D-A**: autorizar 1.000 y 1.200 carteras (`--authorized-by`); recomendado juntas, local, 4 workers, `--max-wall 1800 --max-rss-mb 400`.
2. **D-B**: dónde ejecutar 5.000/22.000 (equipo dedicado o Arsys en ventana acordada); la máquina actual no sirve para dimensionar.
3. **D-C**: omitir la referencia secuencial completa en 5.000/22.000 (submuestra).
4. **D-D/D-E**: mezcla de carga real (D-01) y workers/reserva para SQL Server (D-11).
5. **D-G**: mantener 10/100/1.200 como DoD y 5.000/22.000 como capacidad (D-03).
6. **D-H**: autorizar una fase B4 de remediación de H-1 antes de una ejecución masiva con W2-WORST-CASE; y una fase B3 para F-B55-1.
7. **D-F/D-I**: tarifa €/h-núcleo (opcional) y medir W2/W5 a dimensión realista.

`BLOCK_5_STATUS` **no se emite**: el cierre del Bloque 5 exige la validación a 1.200 carteras (BEN-007) y la auditoría independiente de B5.5.
