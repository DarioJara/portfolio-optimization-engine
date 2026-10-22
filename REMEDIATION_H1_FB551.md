# REMEDIATION_H1_FB551 — Remediación numérica de H-1 (B4) y F-B55-1 (B3)

Fecha: 2026-10-21. Rama: `fix/h1-fb551-numerical-remediation` (desde `main` = `8ceaf3a`; **no** toca `block5-benchmarks-final-audit` ni `main`).
Procede de `INVESTIGATION_H1_B4.md` y `AUDIT_BLOCK_5_5.md` (PR #9, SHA auditado `41e426479dae210bc35208276a8f328ae9b3519c`; ambos documentos viven en esa
rama y aquí se **contrastan** con el código y la evidencia, no se asumen).

Alcance de esta fase: investigar y remediar de forma independiente dos defectos numéricos; sin merge, sin cambios en B5, sin Arsys/Oracle/SQL Server, sin
benchmarks de ≥ 1.000 carteras. **Fuera de alcance:** cualquier bloque posterior.

## FINAL_STATUS = READY_FOR_INDEPENDENT_AUDIT (informe original; el estado tras la auditoría está en §10.5)

La evidencia justifica la implementación y no hay una decisión matemática pendiente que impida auditarla. **No resuelto** (§8): el efecto sobre B5.5 requiere rebasar el PR #9 (no se ha tocado esa rama);
quedan hipótesis abiertas sobre *qué* operación numérica introduce el ulp; y hay decisiones del propietario (valor de `retry_equilibrate`, invariancia de conjunto del desempate de B3).

## 1. Resumen

| | H-1 (B4) | F-B55-1 (B3) |
|---|---|---|
| Síntoma | `OPTIMAL_INACCURATE` ⇒ solución con pesos válidos rechazada; `SLSQP` del test con `success=False` | W1 devuelve 11 o 12 composiciones (240/260 soluciones; 484/506 llamadas al solver) según la CPU |
| **Causa confirmada** | Instancia degenerada en el borde de `tol = 1e-9`: el residuo primal se estanca en 4·10⁻⁹…10⁻⁸ > `tol_feas` una iteración después de cumplir la brecha ⇒ `AlmostSolved`; el reintento en frío repetía **el mismo método determinista** y caía igual | `ranking_key` desempata por hash solo con mejoras idénticas **bit a bit**; composiciones con la misma utilidad matemática (entrante con peso cero, activos idénticos) difieren en el último ulp ⇒ el ruido decide qué finalistas sobreviven |
| Qué lo dispara entre CPU | Cualquier diferencia de 1 ulp en `b`/`q`. En CI el sentido lo marca el **núcleo de OpenBLAS**: con `Haswell` (EPYC 7763 y una VM EPYC 9V74 sin AVX-512) falla sin perturbar; con `SkylakeX` no; forzando `OPENBLAS_CORETYPE=Haswell` en CPU `SkylakeX` el fallo aparece (§3.2) | El **núcleo de OpenBLAS**, en sentido contrario: `SkylakeX` diverge (12 composiciones), `Haswell` no; forzando `Haswell` en esas CPU la divergencia desaparece (§4.2) |
| Corrección | El reintento en frío tras un estancamiento usa otra numérica (`conic.retry_equilibrate`) con las **mismas** tolerancias; oráculo SLSQP con `ftol = 1e-12` | `rank_nodes`: mejoras a menos de `candidates.improvement_tolerance` (ya existente) del mejor del grupo son un empate y se desempatan por hash |
| Tolerancias / algoritmos | **No se relaja ninguna tolerancia; no se cambia de solver ni de algoritmo; no se promueve ningún estado** | Sin parámetro nuevo; misma búsqueda (Beam + Local), mismo criterio de parada |

## 2. Método y entorno

* Sin acceso a las CPU que fallan: la evidencia por CPU procede de **12 runners de GitHub Actions** (matriz `remediation-diagnostics.yml`, temporal) y de esta máquina
  (Windows 11, i7-13620H, Python 3.13.6, numpy 2.5.3 / scipy 1.18.1 / clarabel 0.11.1 — el `requirements-lock.txt`).
* CI de Linux: `ubuntu-22.04`, Python 3.11.17, **numpy 2.4.6 / scipy 1.17.1** / clarabel 0.11.1 / osqp 1.1.3 (la CI **no instala el lock**; deriva de versiones posible).
* Tres runs de la matriz (12 trabajos cada uno, la CPU se sortea): `5cf463a`, `ab42ca7` y **`3b1cc5c`** (con cada carga etiquetada con el núcleo de OpenBLAS activo; es la referencia
  para H-1). En `3b1cc5c`: 5 × AMD EPYC 7763 y 1 × EPYC 9V74 sin AVX-512 expuesto (núcleos OpenBLAS `Haswell`), 3 × EPYC 9V45, 2 × EPYC 9V74 y 1 × Xeon Platinum 8370C (AVX-512, núcleos `SkylakeX`);
  en `5cf463a` además un Xeon 8573C. Las anotaciones son públicas; copia en `evidence/remediation_h1_fb551/ci_annotations_run_*.json`.
* El workflow temporal de la matriz (12 trabajos) y el disparador de `ci.yml` se retiraron al cerrar la fase; están en el historial: `git show 3b1cc5c:.github/workflows/remediation-diagnostics.yml`.
* Script: `benchmarks/scripts/remediation_diagnostics.py` (`env`, `h1`, `fb551`); no modifica ningún algoritmo: perturba de forma determinista los datos con ruido de ulp.

## 3. H-1 (B4)

### 3.1 Reproducción (punto 3 del encargo)

Los dos tests de `tests/unit/scenarios/test_multi_scenario.py` **pasan** en esta máquina (Intel/Windows, 10 iteraciones, `OPTIMAL`) y, **sobre la base sin corregir (`8ceaf3a`) en CI, fallan los dos en los 6 de 12 runners con núcleos `Haswell` (5 × EPYC 7763 y la VM EPYC 9V74) y pasan en los 6 con núcleos `SkylakeX`** (run `3b1cc5c`).
Estados, residuos y chequeos del primer test, en un runner donde falla (EPYC 7763; idéntico en los 6 `Haswell`):

| Dato | Valor |
|---|---|
| Estado del solver / fuente | `OPTIMAL_INACCURATE` / `CROSS_CHECK` (tras el reintento en frío) |
| Iteraciones | 22 = 11 + 11 (Windows: 10, `OPTIMAL`) |
| `validation.violations` | vacío: **los pesos cumplen todas las restricciones** (`report.is_valid`); `is_valid_solution = False` solo por la política de estado |
| Brecha `|worst_case_utility − solver_t|` | ≈ 5·10⁻¹⁵ (pesos numéricamente correctos) |
| Residuo primal / dual de Clarabel | 9,5·10⁻⁹ / 8·10⁻¹⁶ (tol 10⁻⁹): **el primal está por encima de la tolerancia, el dual y la brecha mucho por debajo** |

Últimas iteraciones de Clarabel en el runner (tabla nativa, columnas `gap`, `pres`, `dres`):

```
 8  +9.2609e-02  +9.2609e-02  1.34e-09  1.40e-10  8.67e-11   <- pres < 1e-9 pero gap 1.34e-9 > 1e-9: aún no termina
 9  +9.2609e-02  +9.2609e-02  1.40e-11  3.83e-09  9.07e-13   <- gap cumple; pres SUBE a 3.8e-9
10  +9.2609e-02  +9.2609e-02  1.40e-13  3.55e-09  9.08e-15
11  +9.2609e-02  +9.2609e-02  1.32e-14  9.54e-09  8.16e-16   Terminated with status = AlmostSolved
```

**Mecanismo confirmado** (medido, no supuesto): el criterio de brecha se incumple por un factor 1,34 en la iteración 8; en la 9 el residuo primal queda por encima de
`tol_feas` por el suelo numérico de la regularización estática (ε₁ = 10⁻⁸) y de la factorización con filas degeneradas, y ya no baja (el residuo se estanca en 4·10⁻⁹…10⁻⁸); Clarabel detecta la falta
de progreso y devuelve `AlmostSolved` (se cumplen las tolerancias *reducidas*, 5·10⁻⁵). En esta máquina el residuo vuelve a 1,5·10⁻¹⁰ por azar de redondeo y termina `Solved`.

### 3.2 Contraste con `INVESTIGATION_H1_B4.md` y `AUDIT_BLOCK_5_5.md`

| Afirmación | Veredicto con la evidencia |
|---|---|
| El mecanismo es `Solved → AlmostSolved` por la tolerancia 1e-9 y se dispara con diferencias de ~1 ulp (INVESTIGATION §2) | **Confirmado** en los runners con núcleos `Haswell` (y en `SkylakeX` forzados a `Haswell`): es exactamente el patrón de arriba |
| «No demostrado que el estado sea `AlmostSolved`» (INVESTIGATION §4) | **Cerrado**: `Terminated with status = AlmostSolved`, 11 + 11 iteraciones, anotado en cada runner |
| Fallo del primer test «intermitente» / «solo EPYC 7763» (INVESTIGATION §1) | **Matizado.** No es intermitente en un entorno dado ni propio de EPYC 7763: en CI **falla determinista** (22 = 11 + 11 iteraciones, 0/3 válidas, sin perturbar) en **todas** las CPU con núcleos OpenBLAS `Haswell` (incluida una VM EPYC 9V74) y no falla en las de núcleos `SkylakeX`. **Intervención:** con `OPENBLAS_CORETYPE=Haswell` las CPU `SkylakeX` (EPYC 9V45/9V74, Xeon 8370C) reproducen el fallo (0/3, 22 iteraciones). El núcleo BLAS decide en qué lado cae el ulp; el sentido contrario al de F-B55-1. El Windows local usa núcleos `Haswell` con OpenBLAS 0.3.34 y **no** falla (10 iteraciones): la versión de numpy/OpenBLAS también cuenta, no solo el núcleo. «Funcionó en un runner Xeon» **no** es evidencia de robustez (AUDIT_BLOCK_5_5 A-01 lo anticipó) |
| Mismo defecto en los dos tests (AUDIT §3) | **Dos mecanismos distintos** (motor Clarabel; criterio de éxito del oráculo SLSQP) con una raíz común: precisión pedida ≈ resolución de coma flotante |
| El segundo test falla por el criterio del oráculo, no por el motor (INVESTIGATION §3) | **Confirmado**: `ftol = 1e-15` ≈ 70 ulp del óptimo (|x₄| ≈ 0,09, ulp ≈ 1,4·10⁻¹⁷); con `ftol = 1e-12` el éxito es 100 % en todas las celdas de la sonda y la dispersión del óptimo (≤ 5·10⁻¹³) es muy inferior a las tolerancias del test |

### 3.3 Qué ocurre si se toca cada palanca (barrido local, 40 resoluciones por celda, perturbación de 1 ulp en `b` y `q`)

Ejecución del problema del primer test; «válidas» = `is_valid_solution`. `eps` = perturbación relativa; 1e-10 supera lo que cambia entre CPU y *altera* el problema (las filas redundantes dejan de ser consistentes): se muestra solo como estrés.

| Variante (solo en el experimento) | eps 0 | 1e-16 | 1e-14 | 1e-12 | 1e-10 |
|---|---|---|---|---|---|
| Línea base (código previo) | 1,00 | **0,50** | 0,40 | 0,35 | 0,05 |
| `presolve` apagado | 1,00 | 0,50 | 0,40 | 0,35 | 0,05 |
| regularización dinámica apagada | 1,00 | 0,50 | 0,40 | 0,35 | 0,05 |
| `direct_solve_method = qdldl` | 1,00 | 0,50 | 0,40 | 0,35 | 0,05 |
| refinamiento iterativo apagado | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 |
| refinamiento con más iteraciones | 0,00 | 0,53 | 0,23 | 0,35 | 0,03 |
| regularización estática 10⁻¹⁰ | 1,00 | 1,00 | 1,00 | 0,97 | 0,07 |
| regularización estática 10⁻¹² | 1,00 | 1,00 | 1,00 | 0,88 | 0,05 |
| regularización estática apagada | 1,00 | 1,00 | 1,00 | 1,00 | 0,05 |
| `max_step_fraction = 0,95` | 1,00 | 1,00 | 1,00 | 1,00 | 0,35 |
| **equilibrado apagado** | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 |
| Tolerancia 3·10⁻⁹ o 10⁻⁸ (sonda de `INVESTIGATION_H1_B4.md`, reproducida por `AUDIT_BLOCK_5_5.md`; no repetida aquí) | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 |

Lectura: el estancamiento es **sensible a la numérica** (regularización, equilibrado, paso), no a la matemática del problema. Relajar la tolerancia lo oculta (3·10⁻⁹ ≈ 3× el suelo del residuo primal,
sin margen para otros problemas degenerados) pero **cambia la garantía** de todas las formulaciones cónicas; cambiar la numérica del *primer* intento cambia resultados validados.

### 3.4 Resultado de la corrección en CI (run `3b1cc5c`, cada carga etiquetada con el núcleo de OpenBLAS)

Instancia del primer test **sin perturbar** (3 resoluciones) y base sin corregir frente a rama corregida:

| Núcleo OpenBLAS (CPU) | Base: tests originales de H-1 | Motor sin corregir (reintento idéntico) | Motor corregido |
|---|---|---|---|
| `Haswell` nativo (5 × EPYC 7763, 1 × EPYC 9V74 VM) | **FALLAN los 2** | `OPTIMAL_INACCURATE/CROSS_CHECK`, 22 it., 0/3 válidas | `OPTIMAL/CROSS_CHECK`, 19 it., 3/3 |
| `SkylakeX` nativo (3 × EPYC 9V45, 2 × EPYC 9V74, Xeon 8370C) | pasan | `OPTIMAL/SOLVER`, 9 it., 3/3 válidas | `OPTIMAL/SOLVER`, 9 it., 3/3 (idéntico) |
| `SkylakeX` con `OPENBLAS_CORETYPE=Haswell` (mismas 6 CPU) | — | `OPTIMAL_INACCURATE/CROSS_CHECK`, 22 it., 0/3 | `OPTIMAL/CROSS_CHECK`, 19 it., 3/3 |

Con perturbación de 1 ulp (`eps` = 10⁻¹⁶…10⁻¹², 20 resoluciones por celda; run `5cf463a`, mismas conclusiones en `3b1cc5c`), el motor sin corregir da 7/20 a 11/20 soluciones válidas según la celda y la CPU
(p. ej. 7/20 con `eps` = 10⁻¹⁶ en EPYC 7763 y 9/20 en `SkylakeX`) y el corregido **20/20 en todas las celdas de todos los runners**; la suite de los módulos afectados (926 tests) pasa en los 12 runners (§9).

## 4. F-B55-1 (B3)

### 4.1 Reproducción y causa

* `W1-GLOBAL-NET-000005-0000` (lote de referencia de B5.5: 10 carteras de `ENG-MIX-BASE`, semilla 7): 240 soluciones/11 composiciones (referencia Windows) frente a 260/12 en otras CPU
  (484 frente a 506 llamadas al solver del contador de trabajo).
* **Medido en esta máquina (Windows/Intel, una sola CPU):** perturbar `μ`, `Σ` y los costes con ruido relativo de 10⁻¹⁶ cambia el resultado entre 11 y 12 composiciones
  (16 semillas: 12 × 11 y 4 × 12; con 10⁻¹⁴ y 10⁻¹²: 4 y 6 × 12). **La búsqueda es discontinua ante ruido de ulp**: no hace falta otra CPU para ver las dos variantes.
* Traza de las decisiones del `CandidateEngine` (variante 11 frente a variante 12, `eps = 10⁻¹⁶`): en el perfil λ = 1 hay tres composiciones con la **misma mejora**
  (`0,051082416342949855`) en la variante 11 y `…855`/`…855`/`…84` en la variante 12. `SearchNode.ranking_key = (válida, −mejora, hash)` solo desempata por hash si las mejoras son bit a bit iguales;
  con 1 ulp de diferencia el orden lo decide el ruido, `select_survivors` conserva *otros* finalistas y la unión de finalistas distintos de los tres perfiles (con el reparto por rondas) pasa de 10 a 11 (+ la referencia = 11 o 12).
  La causa de los empates exactos: un entrante que recibe peso cero en el óptimo da la **misma utilidad** que la composición padre; es degeneración matemática, no un defecto de datos.

### 4.2 ¿BLAS, orden de operaciones, factibilidad, tolerancias o búsqueda? (punto 6)

| Hipótesis | Evidencia | Estado |
|---|---|---|
| **Algoritmo de búsqueda / criterio de orden** (empates sensibles a ulp) | Traza anterior; ruido de 10⁻¹⁶ reproduce 11/12 en una sola CPU; `rank_nodes` elimina la variación (§6) | **Confirmada como causa** de la discontinuidad |
| **Núcleo de OpenBLAS** (despacho `SkylakeX` frente a `Haswell`) como **disparador** del ruido entre CPU | En el B5.5 sin corregir (`41e4264`, lote de referencia), **todas** las CPU con núcleos `SkylakeX` (run `3b1cc5c`: 3 × EPYC 9V45, 2 × 9V74, Xeon 8370C; run `5cf463a`: además Xeon 8573C) dan 260/12 y **todas** las de núcleos `Haswell` (EPYC 7763 y la VM EPYC 9V74 sin AVX-512) dan 240/11, como Windows; **forzando `OPENBLAS_CORETYPE=Haswell` en las CPU `SkylakeX` la divergencia desaparece** (6/6 en `3b1cc5c`, 5/5 en `5cf463a`); el mismo modelo EPYC 9V74 se comporta según el núcleo que expone | **Confirmada** (intervención) |
| **Despacho SIMD de NumPy** (bucles propios, no BLAS) | `NPY_DISABLE_CPU_FEATURES` con extensiones AVX-512 **no surtió efecto** (la lista de características habilitadas de NumPy 2.4.6 seguía incluyendo AVX512F/SKX/CLX/CNL con la variable puesta), y la divergencia persistió. La prueba **no es concluyente** | **Hipótesis pendiente** (no descartada ni confirmada) |
| Criterios de factibilidad / tolerancias | Todos los estados `OPTIMAL`, mismas composiciones comunes con |Δpeso| ≤ 3,5·10⁻¹² entre variantes | No intervienen |
| Orden de sumas/FMA dentro del solver (OSQP/QDLDL) | No aislado | **Hipótesis pendiente**: no se necesita para la corrección; no se ha medido por separado |
| SO / Python / compilador | EPYC 7763 y Windows dan el mismo resultado pese a SO y Python distintos | Descartada (ya señalado por AUDIT_BLOCK_5_5 A-02) |

Corrección de `AUDIT_BLOCK_5_5` A-02: coincide en que la divergencia es **dependiente de CPU/núcleo BLAS, no de la plataforma**; la partición observada no es «AVX-512 sí/no» en abstracto sino **el núcleo de OpenBLAS elegido**
(medido con `threadpoolctl`: `SkylakeX` frente a `Haswell`), verificado por intervención (`OPENBLAS_CORETYPE`). La hipótesis ISA de la auditoría («AVX-512») queda refinada: lo que importa es qué núcleo carga OpenBLAS, no el conjunto de instrucciones por sí mismo (la VM EPYC 9V74 sin AVX-512 expuesto carga `Haswell`).

## 5. Propuesta matemática (documentada antes de aplicarla)

### 5.1 H-1 — el reintento en frío debe cambiar de numérica, no de problema

*Problema.* `solve_with_policy` + `COLD_RETRY` reintenta «desde cero con más iteraciones», pero Clarabel es **determinista**: con los mismos datos y ajustes el reintento reproduce el mismo estancamiento
(medido: `iteraciones = 22 = 11 + 11` y, por tanto, `OPTIMAL_INACCURATE/CROSS_CHECK` otra vez). El reintento solo es útil si cambia la numérica.

*Propuesta.* Tras un estancamiento (`AlmostSolved`, `NumericalError`, `InsufficientProgress`) el reintento resuelve **el mismo problema con las mismas tolerancias** pero con otra configuración de equilibrado
(`conic.retry_equilibrate`, valor de ejemplo `false`). Tras `MaxIterations` conserva el equilibrado primario (el límite era el nº de iteraciones). Elección entre las palancas del §3.3: es la única que da 1,00 en todo el rango de ruido
realista (10⁻¹⁶…10⁻¹²) **y** en el de estrés (10⁻¹⁰), y la menos invasiva: no toca el primer intento.

*Equivalencia matemática.* Clarabel resuelve el mismo SOCP; un `Solved` del reintento satisface las mismas condiciones (brecha, residuos primal y dual ≤ las `tol_*` configuradas); el equilibrado solo reescala
las filas/columnas del sistema interno y no cambia el óptimo. El estado no se promueve: el del reintento es el suyo (si vuelve a ser `AlmostSolved`, el resultado es `OPTIMAL_INACCURATE` y se rechaza como antes).
Los pesos de la solución siguen pasando la validación independiente.

*Efectos previstos.* (a) Nada cambia donde el primer intento ya es `Solved` (sin regresión; verificado: 926 tests, §7). (b) Los casos que antes terminaban `OPTIMAL_INACCURATE` tras el reintento pasan a `OPTIMAL` si el reintento converge
(en el problema de H-1: 100 % en 800 resoluciones locales perturbadas —5 niveles de ruido, 100 y 60 por celda— y en las 12 muestras de CI). (c) Coste: una segunda resolución en frío solo en esos casos (≈ el que ya pagaba el reintento idéntico). (d) `config_hash` cambia (clave obligatoria nueva).

*Alternativas descartadas.* Relajar `tol_*` a 3·10⁻⁹/10⁻⁸ (cambia la garantía de toda formulación cónica; el suelo del residuo es 4·10⁻⁹…10⁻⁸, sin margen); `accept_inaccurate_solutions = true` (acepta *todo*
`OPTIMAL_INACCURATE` de todos los backends, incl. OSQP, y exige una nueva política de validación); apagar el equilibrado en el primer intento (cambia resultados validados y puede empeorar problemas mal escalados);
apagar la regularización estática (riesgo de KKT singular).

*Oráculo del segundo test.* `ftol = 1e-12` (100 % de éxito en toda celda de la sonda); las aserciones del test (`atol = 1e-4`, `abs = 1e-7`) no cambian: se exige exactamente lo mismo, con un oráculo cuyo
criterio de éxito queda por encima de la resolución de coma flotante.

### 5.2 F-B55-1 — desempate estable mediante banda de empate

*Problema.* La función «orden de los nodos» es discontinua ante ruido de 1 ulp en las mejoras de utilidad empatadas matemáticamente. La corrección la hace **estable casi seguro, no continua** (§10, L-1): sigue discontinua en el borde `gap = τ`.

*Propuesta.* `rank_nodes(nodos, τ)`: se ordena como antes; se agrupan las mejoras que distan **menos de τ de la mejor del grupo** (ancla, sin encadenar: un grupo no puede crecer por deriva) y dentro del grupo se ordena
por hash; los grupos se ordenan por mejora decreciente; las estimaciones válidas siguen antes que las inválidas. `τ = candidates.improvement_tolerance` (= 10⁻⁹): el motor ya declara que
una diferencia de utilidad menor es «no una mejora» (parada del haz, ascenso local). **No se añade ningún parámetro.** Con `τ = 0` equivale al orden anterior.

*Equivalencia.* Dos composiciones con mejoras a menos de 10⁻⁹ son indistinguibles para el criterio del propio motor; elegir entre ellas por hash es **tan arbitrario como la elección previa** (ruido de ulp) pero **determinista
y reproducible entre CPU**. No cambia qué composiciones se evalúan ni sus pesos; cambia solo qué empates sobreviven.

*Efectos previstos (corregido tras `AUDIT_H1_FB551.md` M-1; ver §10).* (a) Resultado idéntico entre CPU. (b) **Los empates no son un caso marginal**: en problemas aleatorios sin activos clonados, **12 de 24 casos devuelven un conjunto de composiciones distinto al de `main`** (4 con una composición más o menos; 8 con sustituciones de igual tamaño y **igual mejora**), con empates exactos en 14/14 problemas instrumentados y decenas a centenares de pares con 10⁻¹⁴ < gap ≤ 10⁻⁹ que antes se ordenaban por su diferencia real y ahora por hash. La mejor mejora no empeora en ningún caso. Solo las fixtures validadas existentes (sus tests) no cambian. (c) En el universo con clones la referencia pasa de 10 a 9 composiciones; en el lote de referencia de B5.5 el resultado de Windows no cambia.
se tomó como referencia* (p. ej. el universo con clones de los tests pasa de 10 a 9 composiciones en esta máquina); en el lote de referencia de B5.5 el resultado de Windows **no cambia** (`cross_platform_reference.py explain` ⇒ «sin divergencias»).

*Alternativas descartadas.* Redondear las mejoras (discontinuidad en el borde de la rejilla); ordenar solo por hash (rompe la prioridad de utilidad); un parámetro de banda nuevo (innecesario).

## 6. Implementación y pruebas

Commits separados (B4 y B3 no se mezclan):

| Commit | Contenido |
|---|---|
| `eca9582` (B4) | `conic.retry_equilibrate` (`config/conic_config.py`, `config/default_engine.toml`), `ClarabelBackend.cold_retry` / `_new_solver`; oráculo SLSQP `ftol = 1e-12`; `tests/unit/scenarios/test_h1_clarabel_numerics.py` (+8), `test_block4_config.py` |
| `992d45f` (B3) | `candidates/expansion.py::rank_nodes`, `beam_search.select_survivors`, `local_search`, `candidate_engine`; `tests/unit/candidates/test_tie_stability.py` (+8), adaptación de `test_beam_search.py` |
| posteriores | `benchmarks/scripts/remediation_diagnostics.py`, workflows temporales de CI y evidencia local |

Pruebas de regresión **independientes de la CPU** (perturbación determinista, no se espera un hardware concreto), verificadas rojas sin la corrección y verdes con ella:

* `test_one_ulp_perturbations_never_invalidate_the_degenerate_worst_case[0, 1e-16, 1e-14, 1e-12]`: todas las soluciones `OPTIMAL` y válidas (sin la corrección: 4 de 4 fallan salvo `eps = 0`).
* `test_the_retry_changes_the_numerics_after_a_stall_but_not_the_tolerances` / `…after_an_iteration_limit_keeps_the_primary_numerics`: ajustes de Clarabel espiados; las 5 tolerancias del reintento son las configuradas.
* `test_tied_gains_are_ordered_by_hash_whatever_the_last_ulp`, `test_survivor_selection_is_invariant…`, `test_the_candidate_set_does_not_depend_on_ulp_noise_with_tied_compositions`
  (universo con activos clonados; 12 semillas de ruido): la última falla sin la corrección.
* `test_the_exact_float_order_is_not_stable_under_ulp_noise` documenta el defecto (orden por `ranking_key` exacto inestable).
* **Sin `xfail` ni `skip` nuevos.**

## 7. Impacto en resultados y compatibilidad

* **Compatibilidad de configuración (cambio incompatible):** `[conic] retry_equilibrate` es **obligatoria** (el proyecto no admite valores por defecto implícitos); cualquier TOML propio sin ella falla con «Clave obligatoria ausente».
  `config_hash` cambia ⇒ las claves de caché y los diarios de reanudación creados antes no coinciden (comportamiento intencionado de B5.3/B5.4).
* **Resultados:** primer intento idéntico bit a bit cuando no hay reintento (57/57 en la auditoría); en B3 cambia el conjunto de composiciones en ~la mitad de los problemas aleatorios (M-1, §10.1) con igual calidad; se aceptan estos cambios y los baselines/golden de B3/B5 que dependan del conjunto exacto deben regenerarse (decisión D-2, §10.2).
  terminaban `OPTIMAL_INACCURATE` tras el reintento y (b) la selección entre composiciones con mejora empatada.
* **B5.5 (PR #9):** sus baselines de trabajo (`perf_reference_work.json`) admitían dos variantes (484/506) por F-B55-1; con esta corrección la variante única es **484/11 composiciones**. Al rebasar B5.5 sobre esta rama hay que
  (1) retirar el `xfail` de `test_cross_platform_reference.py`, (2) sustituir las dos variantes por una, (3) regenerar `config_hash` de los baselines de rendimiento (los tiempos por host ya exigen reejecución) y
  (4) el criterio M-2 de la auditoría («conjunto de una variante superconjunto de la otra») deja de ser necesario. **No se ha hecho aquí** (la rama B5.5 no se altera).
* **Decisiones del propietario:** formalizadas en §10.2 (D-1…D-5).

## 8. Causas confirmadas, hipótesis pendientes y límites

**Confirmadas (con evidencia reproducible):**

1. H-1: mecanismo `Solved → AlmostSolved` (el residuo primal sube a 4·10⁻⁹…10⁻⁸ la iteración siguiente a cumplir la brecha) y su carácter determinista por entorno; el reintento en frío idéntico no puede cambiarlo.
2. H-1: el sentido lo marca el **núcleo de OpenBLAS** en el entorno de CI (`Haswell` falla, `SkylakeX` no; intervención con `OPENBLAS_CORETYPE`), no una CPU concreta.
3. Criterio del oráculo SLSQP (`ftol = 1e-15` ≈ 70 ulp del óptimo).
4. F-B55-1: causa en la búsqueda (empates matemáticos exactos desordenados por 1 ulp en `ranking_key`), reproducida con ruido de 10⁻¹⁶ **en una sola CPU**; su disparador entre CPU es, de nuevo, el núcleo de OpenBLAS (sentido contrario: `SkylakeX` diverge), por intervención.
5. Eficacia: tras las correcciones, 0 divergencias de F-B55-1 y 0 soluciones inválidas de H-1 en **12/12** runners de CI y en Windows, con perturbaciones de ulp, y sin regresiones (926 tests de los módulos afectados en los 12 runners; suite completa 1962 passed/10 skipped en Windows y 1973 passed/2 skipped en CI).

**Hipótesis pendientes (no se presentan como causas):**

1. Qué cálculo previo produce el ulp que desplaza a Clarabel/`CandidateEngine` (factorización de Σ por autovalores, productos matriz-vector…): se sabe que cambia con el núcleo BLAS, no cuál es la operación.
2. Despacho SIMD de NumPy (bucles propios): la prueba con `NPY_DISABLE_CPU_FEATURES` fue **ineficaz** y no es concluyente.
3. Orden de sumas dentro de OSQP/QDLDL en F-B55-1: no aislado.
4. Deriva de versiones: el Xeon 8573C de B5.5 daba `Solved` y la misma CPU en este run con núcleos `SkylakeX` también (consistente), pero B5.5 no registró versiones de numpy/OpenBLAS; no puede atribuirse. La versión de OpenBLAS cuenta: Windows (`Haswell`, OpenBLAS 0.3.34) no falla.

**Límites:** la CI **no instala el lock** (numpy 2.4.6/scipy 1.17.1 frente a 2.5.3/1.18.1 en Windows); no se probó ARM, macOS ni otras versiones de OpenBLAS; H-1 se estudió en **una** instancia (el riesgo análogo en otras instancias degeneradas está cubierto por el reintento
con otra numérica salvo que esa también se estanque, caso en el que el estado seguirá siendo `OPTIMAL_INACCURATE`, correctamente distinguido y rechazado); F-B55-1 sobre un lote de referencia (10 carteras, 2 W1) y un universo sintético con clones. La remediación **no** demuestra que no existan otros
puntos de decisión discontinuos en el motor de candidatos (p. ej. `argsort` estable sobre puntuaciones de screening empatadas): no se observaron en las 96 perturbaciones del lote de referencia (48 sobre `W1-GLOBAL-NET-000005`, 48 sobre las dos W1).

**Decisiones del propietario (no tomadas aquí; no impiden auditar):** (a) confirmar `retry_equilibrate = false` como valor de ejemplo de producción o elegir otra palanca del §3.3; (b) confirmar que el desempate de B3 debe ser **invariante de conjunto** entre CPU (lo que implementa `rank_nodes`) en lugar de aceptar solo T1 sobre los pesos;
(c) cuándo rebasar B5.5 (PR #9) sobre esta rama y qué hacer con su `xfail` y sus baselines (§7).

## 9. Estado de GitHub Actions

Evidencia pública (anotaciones de check-runs de la API de GitHub; sin logs). Rama `fix/h1-fb551-numerical-remediation`, repositorio `DarioJara/portfolio-optimization-engine`.

| Run | SHA | Workflow | Resultado | Contenido |
|---|---|---|---|---|
| `39672838576` | `3b1cc5c` | Portfolio Engine CI (job `Ubuntu / Python 3.11`, runner EPYC 7763) | **success** | mypy `--strict`, Ruff check/format, forkserver y evidencia B5.4, **suite completa: 1973 passed, 2 skipped** (302 s) |
| `39672838602` | `3b1cc5c` | Remediation diagnostics (temporal, 12 runners) | **success** (12/12) | CPU, H-1 antes/después, F-B55-1 antes/después, base sin corregir, suite de los módulos afectados: **926 passed en los 12** |
| `39666799848` / `39666799963` | `ab42ca7` | CI / diagnóstico | success / success | CI en EPYC 9V45: **1973 passed, 2 skipped**; mismos resultados por CPU |
| `39663855062` / `39663855280` | `5cf463a` | CI / diagnóstico | success / success | CI en EPYC 7763: 1973 passed, 2 skipped (la CPU donde H-1 falló en el PR #9) |
| `39665164224` | `0e710b9` | Diagnóstico | failure | Error mío de YAML (línea rota) en el workflow temporal, corregido en `76beb31`; sin relación con el código |
| `39665206755` | `76beb31` | CI | cancelled | Cancelado (causa no investigada; la publicación siguiente llegó minutos después); no es un fallo de pruebas |

Los 2 tests omitidos de CI son los mismos de la base. Los workflows temporales y el disparador de `ci.yml` se retiran en el último commit; **ese commit solo toca documentación y workflows** (verificado con `git diff`), así que la evidencia de código es la de `3b1cc5c`.

## 10. Cierre tras `AUDIT_H1_FB551.md` (PASS_WITH_CHANGES: M-1, M-2, L-1…L-4, I-1…I-5)

El informe de auditoría y sus scripts reproducibles se incorporan al repositorio: [`AUDIT_H1_FB551.md`](AUDIT_H1_FB551.md) y `evidence/audit_h1_fb551/` (`h1_sweep.py`, `retry_stress*.py`, `kkt_check.py`,
`slsqp_oracle.py`, `fb_sweep*.py`, `fb_why.py`, `band_edge.py`, `cfg_compat.py`; comandos en su §12). Se conservan tal cual: están excluidos de Ruff (`pyproject.toml`, solo herramientas).
Esta fase **no cambia código de producción, tolerancias, solvers ni algoritmos**.

### 10.1 M-1 — cambio observable de B3 respecto a `main` (cuantificado)

Medido por el auditor (`fb_why.py`; `random_problem`, 10 y 14 activos, 12 semillas, 24 casos, sin clones; numpy 2.2.6, OpenBLAS 0.3.29 `Haswell`):

| Medida | Resultado |
|---|---|
| Casos con conjunto de composiciones distinto al de `main` | **12 de 24** |
| — con una composición más o menos (10→11, 9→8, 11→12, 11→10) | 4 |
| — con sustituciones de igual tamaño y **misma mejora** | 8 |
| Casos en que la mejor mejora **empeora** | **0** (en `rand|14|2` el PR añade una candidata mejor: 0,0601 frente a 0,0570) |
| Empates exactos de mejora (entrantes con peso cero) | en 14/14 problemas instrumentados: 16–215 pares por problema |
| Pares con 10⁻¹⁴ < gap ≤ 10⁻⁹ (antes ordenados por su diferencia diminuta, ahora por hash) | decenas a centenares por problema (≈ 50 y ≈ 340 en los ejemplos) |
| `rank_nodes` frente a `ranking_key` | el orden difiere en 4–8 de 12–13 llamadas por problema |
| Invariancia ante ruido de ulp (universo con clones, 40 perturbaciones) | base: 13 conjuntos distintos; PR: **1** (40/40 iguales a su referencia) hasta ruido relativo 10⁻⁹; 6 conjuntos a 10⁻⁸ (el ruido supera τ y deja de ser un empate) |

Lectura: `rank_nodes` **solo reordena**; no elimina ni agrupa composiciones. Cambia cuál de dos mejoras a menos de 10⁻⁹ se prefiere, y los candidatos que entran o salen tienen la misma mejora
(indistinguibles para el criterio del propio motor). No es un defecto, pero **es un cambio de comportamiento de un bloque `VALIDATED`** que el texto original presentaba como acotado; queda corregido en §5.2 y aceptado en D-2.
Consecuencia: los baselines/golden de B3 y B5 que dependan del conjunto exacto de composiciones deben regenerarse al rebasar B5.5 (D-5); los tests existentes de B3 no cambian (926 passed en los módulos afectados).

### 10.2 M-2 — registro formal de decisiones metodológicas

| ID | Decisión | Fundamento (evidencia) | Consecuencias aceptadas | Estado |
|---|---|---|---|---|
| **D-1** | `conic.retry_equilibrate = false` como configuración del reintento (`config/default_engine.toml`) | 0 reintentos peores que el de la base en 3.600 instancias de estrés; rescate 19/19 (escala 10³) y 85/91 (10⁶) a tol 10⁻⁹ (base: 0); 123/123 reintentos de H-1 acaban `Solved`; 12/12 runners de CI (`Haswell` y `SkylakeX`) | Clave obligatoria nueva (cambio incompatible de configuración); `config_hash` cambia; el reintento puede mover los pesos hasta ~2·10⁻⁴ en problemas mal escalados con igual objetivo a ~10⁻⁹ (I-1) | **Adoptada** |
| **D-2** | Desempate determinista de B3 mediante `improvement_tolerance` (`rank_nodes`): **invariancia de conjunto** entre CPU en lugar de «solo T1 sobre pesos» | F-B55-1 reproducida con ruido de 10⁻¹⁶ en una sola CPU; con la corrección 40/40 conjuntos iguales (auditor) y 12/12 runners (CI) | El conjunto de composiciones de `main` cambia en ~12/24 problemas aleatorios, con igual mejora (§10.1); baselines/golden de B3/B5 a regenerar | **Adoptada** |
| **D-3** | `τ = improvement_tolerance = 1e-9` **absoluto** en esta versión | Es la tolerancia con la que el propio motor declara «no una mejora»; margen ≈ 10⁷ sobre el ruido de 1 ulp; invariante hasta ruido relativo 10⁻⁹ | Limitaciones (L-1): no es relativo a la escala de la utilidad (un cambio de unidades/magnitud la haría material o inmaterial); estable casi seguro, no continuo (borde `gap = τ`, probabilidad ≈ 10⁻⁸ por par; agrupación por ancla no transitiva). Revisar si cambia la escala de la utilidad | **Adoptada** (con limitaciones) |
| **D-4** | **Conservar `OPTIMAL_INACCURATE`** cuando el reintento no converge; **no relajar tolerancias**; `accept_inaccurate_solutions = false` | Relajar `tol_*` cambia la garantía de toda formulación cónica y el suelo del residuo es 4·10⁻⁹…10⁻⁸; en 6/91 casos extremos (escala 10⁶) el reintento también se estanca | Esos casos siguen rechazados como `OPTIMAL_INACCURATE` (correctamente distinguidos). Escalonar tolerancias queda como mejora posible, **no implementada** | **Adoptada** |
| **D-5** | **Integrar el PR #10 antes de actualizar B5.5 (PR #9)**; después, rebasar B5.5: retirar el `xfail` de F-B55-1, una sola variante de baseline de trabajo (484/11 composiciones), regenerar `config_hash` y baselines; el criterio «superconjunto» de AUDIT_BLOCK_5_5 M-2 deja de ser necesario | Los baselines de B5.5 dependen del `config_hash` y del conjunto de composiciones, que este PR cambia | PR #9 queda **pendiente de rebase** hasta el merge del PR #10; no se toca aquí | **Adoptada** |

### 10.3 Hallazgos LOW e INFO pendientes (documentados, no corregidos en esta fase)

| ID | Hallazgo | Estado y acción futura |
|---|---|---|
| **L-1** | Desempate «continuo» inexacto: discontinuidad en el borde `gap = τ` (con dos mejoras separadas exactamente τ, ±3 ulp cambian el orden; 0 cambios en 20.000 perturbaciones lejos del borde); agrupación por ancla no transitiva; τ absoluto no validado frente a la escala | **Abierto, aceptado (D-3).** Terminología corregida a «estable casi seguro». Mejora futura: τ relativo a la escala de la utilidad |
| **L-2** | `solve_with_policy` sustituye siempre el primer resultado por el reintento sin comparar calidad (diseño previo de B2); `_last_native_status` no se reinicia en `setup()/update()` y se compara con la cadena exacta `"MaxIterations"` en lugar de `map_clarabel_status(native) is SolverStatus.MAX_ITERATIONS` (un cambio del `repr` de Clarabel degradaría silenciosamente a «cambiar numérica» tras un límite de iteraciones) | **Abierto.** No se corrige aquí (sin cambios de algoritmo adicionales); no observado en 3.600 instancias de estrés. Corrección sugerida: normalizar con `map_clarabel_status` y reiniciar el estado en `setup`/`update` |
| **L-3** | `retry_equilibrate == equilibrate` se acepta sin aviso y reproduce el defecto original (reintento idéntico) | **Abierto.** Solo nota en el docstring de `ConicSolverConfig`. Sugerencia: aviso o rechazo explícito en la validación |
| **L-4** | El oráculo SLSQP no tiene referencia independiente de motor y SLSQP; la justificación «70 ulp» es heurística | **Abierto, sin impacto en la corrección del test** (márgenes ×580 en pesos y ×3·10⁴ en valor; éxito 200/200 con `ftol = 1e-12`) |
| I-1 | H-1 medida sobre una instancia del repositorio más estrés sintético; 6/91 casos extremos siguen `OPTIMAL_INACCURATE`; pesos hasta ~2·10⁻⁴ de diferencia con objetivo igual a ~10⁻⁹ en problemas mal escalados | Informativo (D-1, D-4) |
| I-2 | El disparador `Haswell`/`SkylakeX` se confirma indirectamente (el auditor reproduce la base con `Haswell`, `Sandybridge`, `Nehalem` y `Zen`, no con `Core2`); no pudo forzar `SkylakeX` | Informativo |
| I-3 | F-B55-1 sobre el lote W1 de B5.5 no reproducido por el auditor (requiere rebasar B5.5) | Se verificará al rebasar (D-5) |
| I-4 | mypy/ruff no ejecutados por el auditor; 2 omitidos de CI y 40 locales = los de la base | Ejecutados en esta fase (CHANGELOG, «Verificación») |
| I-5 | Estados de requisitos coherentes con CLAUDE.md | Sin cambio |

### 10.4 Verificación de esta fase

Ver la entrada «Cierre tras AUDIT_H1_FB551» de `CHANGELOG.md` (configuración, regresión de H-1 y F-B55-1, módulos afectados, mypy `--strict`, Ruff).

### 10.5 Estado

**FINAL_STATUS (cierre) = READY_FOR_MERGE**, a falta de la confirmación del propietario de D-1…D-5 (propuestas por él mismo en el encargo de cierre y registradas aquí). Sin merge realizado.
