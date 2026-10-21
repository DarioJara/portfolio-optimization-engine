# REMEDIATION_H1_FB551 — Remediación numérica de H-1 (B4) y F-B55-1 (B3)

Fecha: 2026-10-21. Rama: `fix/h1-fb551-numerical-remediation` (desde `main` = `8ceaf3a`; **no** toca `block5-benchmarks-final-audit` ni `main`).
Procede de `INVESTIGATION_H1_B4.md` y `AUDIT_BLOCK_5_5.md` (PR #9, SHA auditado `41e426479dae210bc35208276a8f328ae9b3519c`; ambos documentos viven en esa
rama y aquí se **contrastan** con el código y la evidencia, no se asumen).

Alcance de esta fase: investigar y remediar de forma independiente dos defectos numéricos; sin merge, sin cambios en B5, sin Arsys/Oracle/SQL Server, sin
benchmarks de ≥ 1.000 carteras. **Fuera de alcance:** cualquier bloque posterior.

## FINAL_STATUS = READY_FOR_INDEPENDENT_AUDIT

(Condicionado a la sección 8: lo que sigue **no** está resuelto —el efecto sobre B5.5 requiere rebasar PR #9, y hay dos hipótesis abiertas—, pero la evidencia
justifica la implementación y no hay una decisión matemática pendiente que impida auditarla. Las decisiones que sí le corresponden al propietario están en §7.)

## 1. Resumen

| | H-1 (B4) | F-B55-1 (B3) |
|---|---|---|
| Síntoma | `OPTIMAL_INACCURATE` ⇒ solución con pesos válidos rechazada; `SLSQP` del test con `success=False` | W1 devuelve 11 o 12 composiciones (240/260 soluciones; 484/506 llamadas al solver) según la CPU |
| **Causa confirmada** | Instancia degenerada en el borde de `tol = 1e-9`: el residuo primal se estanca en 4·10⁻⁹…10⁻⁸ > `tol_feas` una iteración después de cumplir la brecha ⇒ `AlmostSolved`; el reintento en frío repetía **el mismo método determinista** y caía igual | `ranking_key` desempata por hash solo con mejoras idénticas **bit a bit**; composiciones con la misma utilidad matemática (entrante con peso cero, activos idénticos) difieren en el último ulp ⇒ el ruido decide qué finalistas sobreviven |
| Qué lo dispara entre CPU | Cualquier diferencia de 1 ulp en `b`/`q` (**no** es específico de EPYC 7763: ver §3.2) | El **núcleo de OpenBLAS** que se despacha (`SkylakeX` en CPU AVX-512 frente a `Haswell`): forzar `OPENBLAS_CORETYPE=Haswell` en esas CPU elimina la divergencia (§4.2) |
| Corrección | El reintento en frío tras un estancamiento usa otra numérica (`conic.retry_equilibrate`) con las **mismas** tolerancias; oráculo SLSQP con `ftol = 1e-12` | `rank_nodes`: mejoras a menos de `candidates.improvement_tolerance` (ya existente) del mejor del grupo son un empate y se desempatan por hash |
| Tolerancias / algoritmos | **No se relaja ninguna tolerancia; no se cambia de solver ni de algoritmo; no se promueve ningún estado** | Sin parámetro nuevo; misma búsqueda (Beam + Local), mismo criterio de parada |

## 2. Método y entorno

* Sin acceso a las CPU que fallan: la evidencia por CPU procede de **12 runners de GitHub Actions** (matriz `remediation-diagnostics.yml`, temporal) y de esta máquina
  (Windows 11, i7-13620H, Python 3.13.6, numpy 2.5.3 / scipy 1.18.1 / clarabel 0.11.1 — el `requirements-lock.txt`).
* CI de Linux: `ubuntu-22.04`, Python 3.11.17, **numpy 2.4.6 / scipy 1.17.1** / clarabel 0.11.1 / osqp 1.1.3 (la CI **no instala el lock**; deriva de versiones posible).
* Las CPU muestreadas en el primer run (`5cf463a`): 7 × AMD EPYC 7763 (núcleos OpenBLAS `Haswell`), 1 × EPYC 9V45, 3 × EPYC 9V74 y 1 × Xeon Platinum 8573C (los cinco con AVX-512 y núcleos
  OpenBLAS `SkylakeX`). Anotaciones públicas del run; los datos crudos de este equipo están en `evidence/remediation_h1_fb551/`.
* Script: `benchmarks/scripts/remediation_diagnostics.py` (`env`, `h1`, `fb551`); no modifica ningún algoritmo: perturba de forma determinista los datos con ruido de ulp.

## 3. H-1 (B4)

### 3.1 Reproducción (punto 3 del encargo)

Los dos tests de `tests/unit/scenarios/test_multi_scenario.py` **pasan** en esta máquina (Intel/Windows) y **fallan** donde el redondeo cae del lado malo.
Estados, residuos y chequeos del primer test, en la CPU/entorno donde falla (EPYC 7763; idéntico en las otras 11 muestras de CI):

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
| El mecanismo es `Solved → AlmostSolved` por la tolerancia 1e-9 y se dispara con diferencias de ~1 ulp (INVESTIGATION §2) | **Confirmado** en 12 runners reales: es exactamente el patrón de arriba |
| «No demostrado que el estado sea `AlmostSolved`» (INVESTIGATION §4) | **Cerrado**: `Terminated with status = AlmostSolved`, 11 + 11 iteraciones, anotado en cada runner |
| Fallo del primer test «intermitente» / «solo EPYC 7763» (INVESTIGATION §1) | **Matizado**: no es intermitente ni propio de EPYC 7763. En el entorno de CI de este run (numpy 2.4.6) **las 12 muestras** —EPYC 7763, 9V45, 9V74 y Xeon 8573C, con núcleos `Haswell` y `SkylakeX`— terminan `OPTIMAL_INACCURATE` sin perturbar (0/3 válidas). En B5.5 un Xeon 8573C terminó `Solved` (9 iteraciones): lo que cambia el resultado es **cualquier** diferencia de 1 ulp en los datos de entrada (CPU, núcleo BLAS y versión de numpy/OpenBLAS), no una CPU concreta. «Funcionó en el runner Xeon» **no** es evidencia de robustez |
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
| **Núcleo de OpenBLAS** (despacho `SkylakeX` frente a `Haswell`) como **disparador** del ruido entre CPU | En el B5.5 sin corregir, las 5 CPU con AVX-512 y núcleos `SkylakeX` (EPYC 9V45, 3 × 9V74, Xeon 8573C) dan 260/12; las 7 EPYC 7763 (`Haswell`) dan 240/11; **forzando `OPENBLAS_CORETYPE=Haswell` en las 5 CPU AVX-512 la divergencia desaparece**; mismo resultado idéntico en las 12 muestras | **Confirmada** (12/12 runners) |
| **Despacho SIMD de NumPy** (bucles propios, no BLAS) | `NPY_DISABLE_CPU_FEATURES` con las extensiones AVX-512 no elimina la divergencia (§9: la variable surte efecto) | **Descartada como causa principal** |
| Criterios de factibilidad / tolerancias | Todos los estados `OPTIMAL`, mismas composiciones comunes con |Δpeso| ≤ 3,5·10⁻¹² entre variantes | No intervienen |
| Orden de sumas/FMA dentro del solver (OSQP/QDLDL) | No aislado | **Hipótesis pendiente**: no se necesita para la corrección; no se ha medido por separado |
| SO / Python / compilador | EPYC 7763 y Windows dan el mismo resultado pese a SO y Python distintos | Descartada (ya señalado por AUDIT_BLOCK_5_5 A-02) |

Corrección de `AUDIT_BLOCK_5_5` A-02: coincide en que la divergencia es **dependiente de CPU/núcleo BLAS, no de la plataforma**; la partición observada no es «AVX-512 sí/no» en abstracto sino **el núcleo de OpenBLAS elegido**
(medido con `threadpoolctl`: `SkylakeX` frente a `Haswell`), verificado por intervención (`OPENBLAS_CORETYPE`).

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

### 5.2 F-B55-1 — el desempate debe ser continuo (banda de empate)

*Problema.* La función «orden de los nodos» es discontinua ante ruido de 1 ulp en las mejoras de utilidad empatadas matemáticamente.

*Propuesta.* `rank_nodes(nodos, τ)`: se ordena como antes; se agrupan las mejoras que distan **menos de τ de la mejor del grupo** (ancla, sin encadenar: un grupo no puede crecer por deriva) y dentro del grupo se ordena
por hash; los grupos se ordenan por mejora decreciente; las estimaciones válidas siguen antes que las inválidas. `τ = candidates.improvement_tolerance` (= 10⁻⁹): el motor ya declara que
una diferencia de utilidad menor es «no una mejora» (parada del haz, ascenso local). **No se añade ningún parámetro.** Con `τ = 0` equivale al orden anterior.

*Equivalencia.* Dos composiciones con mejoras a menos de 10⁻⁹ son indistinguibles para el criterio del propio motor; elegir entre ellas por hash es **tan arbitrario como la elección previa** (ruido de ulp) pero **determinista
y reproducible entre CPU**. No cambia qué composiciones se evalúan ni sus pesos; cambia solo qué empates sobreviven.

*Efectos previstos.* (a) Resultado idéntico entre CPU. (b) En entradas sin empates (todas las fixtures validadas) el orden es idéntico al anterior. (c) En entradas **con** empates exactos el resultado puede diferir del anterior *en la CPU que
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
* **Resultados:** primer intento y búsqueda sin empates, idénticos bit a bit (926 tests de los módulos afectados frente a 910 de la base: +16 nuevos, 0 regresiones). Solo cambian (a) las resoluciones cónicas que antes
  terminaban `OPTIMAL_INACCURATE` tras el reintento y (b) la selección entre composiciones con mejora empatada.
* **B5.5 (PR #9):** sus baselines de trabajo (`perf_reference_work.json`) admitían dos variantes (484/506) por F-B55-1; con esta corrección la variante única es **484/11 composiciones**. Al rebasar B5.5 sobre esta rama hay que
  (1) retirar el `xfail` de `test_cross_platform_reference.py`, (2) sustituir las dos variantes por una, (3) regenerar `config_hash` de los baselines de rendimiento (los tiempos por host ya exigen reejecución) y
  (4) el criterio M-2 de la auditoría («conjunto de una variante superconjunto de la otra») deja de ser necesario. **No se ha hecho aquí** (la rama B5.5 no se altera).
* **Decisión pendiente del propietario (§8):** ninguna impide la auditoría; sí se necesitan para el cierre de B5.5/B5.

## 8. Causas confirmadas, hipótesis pendientes y límites

**Confirmadas (con evidencia):** mecanismo `Solved → AlmostSolved` de H-1 y su suelo de residuo primal; reintento idéntico inútil; ausencia de relación con una CPU concreta (12/12 runners con el mismo entorno); criterio del oráculo SLSQP;
causa de F-B55-1 (empates de ulp en `ranking_key`); su disparador entre CPU (núcleo OpenBLAS `SkylakeX` frente a `Haswell`, por intervención `OPENBLAS_CORETYPE`); eficacia de ambas correcciones en 12 CPU/entornos de CI y en Windows.

**Hipótesis pendientes (no se presentan como causas):** (1) qué cálculo numérico previo a Clarabel produce el ulp que lo desplaza (la factorización de Σ por autovalores `eigh`, productos de matrices…): se sabe que depende del entorno BLAS/numpy, no cuál es la operación;
(2) en F-B55-1, que el orden de sumas **dentro de OSQP/QDLDL** no intervenga (no se aisló); (3) la deriva de numpy/OpenBLAS entre el run de B5.5 y este (el B5.5 Xeon 8573C daba `Solved`, este run no): no se registraron versiones en B5.5, así que no se puede atribuir.

**Límites:** la CI **no instala el lock**; la evidencia de Linux es con numpy 2.4.6/scipy 1.17.1, la de Windows con numpy 2.5.3/scipy 1.18.1; no se probó ARM ni macOS; solo un lote de referencia (10 carteras, 2 W1) y un universo sintético con clones para F-B55-1;
H-1 se ha estudiado en **una** instancia (la del test; existe un riesgo análogo en otras instancias degeneradas, ahora cubierto por el reintento con otra numérica salvo que esa también se estanque: en ese caso el estado seguirá siendo `OPTIMAL_INACCURATE`, correctamente distinguido).

**Pendiente de decisión (propietario):** (a) fijar `retry_equilibrate = false` como valor de producción (el de ejemplo del repositorio) o elegir otra palanca del §3.3; (b) si el criterio de empate de B3 debe ser **invariante de conjunto** entre CPU (lo que implementa `rank_nodes`) o basta T1 sobre los pesos; (c) cuándo rebasar B5.5.

## 9. Estado de GitHub Actions

Ver la sección final (se rellena con los runs publicados de la rama).
