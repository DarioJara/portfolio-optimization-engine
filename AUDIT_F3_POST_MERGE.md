# AUDIT_F3_POST_MERGE

Auditoría cuantitativa independiente y focalizada de las dos correcciones P2 posteriores al merge del PR #3
(remediación F-3). Rama `fix/f3-oracle-iteration-accounting`, baseline `main` (`b59e446`).
Auditoría de solo lectura: no se ha modificado código, tests ni documentación existente; no hay commit, merge,
push, tag ni PR; no se avanza al Bloque 4. Único fichero creado: este informe.

Entorno de las mediciones: `.venv` del proyecto (Python 3.13). Las referencias de `main` se obtuvieron con
`git archive main` extraído en un directorio temporal fuera del repositorio (sin `git worktree`, sin tocar `.git`).
Los scripts de auditoría están en el directorio temporal de la sesión, no en el repositorio.

---

## 1. Executive Summary

Las dos correcciones son **correctas, mínimas y no alteran resultados financieros**.

* **P2-01** se reproduce en `main` (`normalize_return_row` → `None` con retornos idénticos y costes asimétricos en
  NET) y queda corregido en la rama. La equivalencia algebraica se verifica de forma independiente (error relativo
  máx. 4·10⁻¹³ con 2 400 vectores aleatorios).
* **P2-02** se reproduce (el oráculo de HiGHS se excluía de `iterations` pero no de `solve_time`) y queda
  corregido: cada intento se cuenta exactamente una vez; el desglose `iterations_by_solver` es coherente en
  `SolveResult`, `FrontierSession` y `FrontierDiagnostics`.
* Regresión económica: 0 diferencias de estado, validez ni pesos (diferencia máxima **0**, bit a bit) entre `main` y
  la rama en 31 + 480 + 700 fronteras (≈ 24 600 puntos). El único cambio observable son las iteraciones del oráculo
  (+214 en total sobre las fronteras recuperadas, coincide con lo declarado).
* Calidad: 1187 tests OK, `mypy --strict` OK, `ruff check` OK, `ruff format --check` OK.
* Hay **0 hallazgos bloqueantes** y 5 no bloqueantes. El más relevante técnicamente (RF-01): la regla adaptativa deja
  sin arreglar una banda intermedia de retornos casi idénticos en NET donde la escala sobre pesos infla los
  coeficientes auxiliares (hasta 10⁹) y la recuperación tarda 22 000–192 000 iteraciones en lugar de ~100. Sigue
  recuperando, pero 192 475 está al 96 % del presupuesto de reintento (200 000). Coincide con lo que la
  implementación admite parcialmente en sus limitaciones; aquí se cuantifica.
* No he podido reproducir íntegramente el barrido de 224 000 puntos (ver §5); lo sustituyo por muestras
  independientes, con la limitación indicada.

Decisión: **PASS_WITH_CHANGES** (cambios menores de documentación; seguimiento recomendado de RF-01).

---

## 2. P2-01 Verdict — escalado de la fila NET

**Confirmado y corregido.**

Reproducción contra `main` (2 activos, μ = [0.07, 0.07], Σ = diag(0.02, 0.04), cartera actual [0.7, 0.3], costes
de compra 127.8/54.7 bps y de venta 9.2/4.3 bps; fila NET original
`[0.07, 0.07, −1.278e-2, −5.469e-3, −9.154e-4, −4.289e-4]`):

| spread de μ | GROSS `main` | NET `main` | GROSS rama | NET rama |
|---|---|---|---|---|
| 0 | `None` | **`None`** | `None` | escala 782.7, máx.\|fila'\| = 10, bloque de pesos 0 |
| 1e-16 | 1.8e17 | 1.8e17 (máx.\|fila'\| 2.3e15) | idéntico | 782.7 (máx.\|fila'\| = 10) |
| 1e-13 | 2e14 | 2e14 (2.6e12) | idéntico | 782.7 |
| 1e-10 | 2e11 | 2e11 (2.6e9) | idéntico | 782.7 |
| ≥ 1e-8 | — | escala sobre pesos | idéntico a `main` | idéntico a `main` |

Comprobaciones de robustez de la nueva condición:

* Sin división por cero: la primera guarda (`overall <= dim·eps·máx|r|`) devuelve `None` para fila nula
  (probado con fila de ceros y con retornos idénticos sin costes); `largest` solo se sustituye por `overall`, que
  es estrictamente positivo tras esa guarda.
* Fila solo con coeficientes auxiliares (pesos exactamente 0): escala 1000 con `weight_scale = 10`, finita.
* NaN / ±inf en la fila: no alcanzan la función (la construcción del problema lo rechaza con `SolverError`).
  Una fila con todos los coeficientes ~10⁻³¹⁰ desborda la escala y falla en la construcción del problema
  normalizado con `SolverError` (caso extremo inalcanzable con datos válidos; lo registro solo como nota).
* Determinismo: 3 ejecuciones idénticas.
* Signos y unidades: la fila centrada conserva el signo de la original (`λ` es la proyección sobre la fila de
  presupuesto); la escala es un factor positivo.
* Umbral `√eps ≈ 1.5·10⁻⁸` (relativo al máximo de toda la fila) y `dim·eps`: son guardas estructurales de
  redondeo, no parámetros financieros; el ratio pesos/auxiliares en las instancias reales F-3 queda muy por
  encima del umbral (test `test_the_weight_dominated_scale_is_unchanged_for_ordinary_instances` y mis 31 fronteras
  contractuales, pesos idénticos bit a bit).
* Comportamiento cerca del umbral: **discontinuo** (ver RF-01). A un lado la escala es ~10³ y al otro ~10⁹–10¹⁰.

## 3. Mathematical Equivalence

Sea `A` la matriz de restricciones, fila 0 = `e` (presupuesto, igualdad `eᵀx = B`), fila `ρ` = `r` (retorno) con
cota `ℓ_r` (`rᵀx ≥ ℓ_r`; en NET `ℓ_r = objetivo + K_E/H`). La implementación calcula:

1. `λ = rᵀe / eᵀe`, `c = r − λ e`.
2. `s = weight_scale / L` con `L > 0` (`L = máx|c[:n]]` o `máx|c|`).
3. Nueva fila `r' = s·c`, nueva cota `ℓ' = s·(ℓ_r − λ B)`.

Para todo `x` factible respecto de la fila de presupuesto (`eᵀx = B`):

`r'ᵀx − ℓ' = s(rᵀx − λ eᵀx) − s(ℓ_r − λ B) = s(rᵀx − ℓ_r) − sλ(eᵀx − B) = s(rᵀx − ℓ_r)`.

Como `s > 0`, `r'ᵀx ≥ ℓ'  ⇔  rᵀx ≥ ℓ_r` sobre el conjunto que ya impone `eᵀx = B`. Las variables, `P`, `q`, las
demás filas, `upper` y las tolerancias no cambian, por lo que el conjunto factible y el óptimo son idénticos. La
elección de `L` (pesos o toda la fila) solo altera `s`, no la equivalencia; la demostración es independiente de
ella.

Verificación numérica independiente (mi script, no el del implementador): 3 configuraciones de μ
([0.07, 0.07], [0.07, 0.07 + 1e-11], [0.03, 0.11]) × 3 objetivos × 200 vectores `x` con `1ᵀw = 1` y variables
auxiliares libres: `|(r'x − ℓ') − s(rx − ℓ_r)|` con error relativo máximo **3.9·10⁻¹³**. El aval del
`SolutionValidator` (retorno objetivo original) y del oráculo LP (ver §4) completa la comprobación.
Comprobado por inspección del diff: no se modifican variables, objetivo, restricciones distintas de `ρ`, target
original (`FrontierPoint.target_return`), costes, tolerancias ni criterio de aceptación (`git diff main` sobre
`session.py` solo toca iteraciones).

## 4. NET Degenerate Case

**Comparativa «escalar siempre sobre toda la fila» frente a escalado adaptativo** (mi propia
reproducción, motor real, `TARGET_RETURN_GRID`, NET; total de iteraciones de la frontera):

| instancia | adaptativo (rama) | siempre toda la fila | puntos inválidos (ambas) | dif. máx. de pesos |
|---|---|---|---|---|
| (2, 685) | **1 347 131** | **3 834 256** | 0 / 0 | 2.3e-8 |
| (2, 878) | 1 384 081 | 1 580 056 | 0 / 0 | 4e-13 |
| (2, 1115) | 5 228 930 | 5 750 680 | 0 / 0 | 4e-13 |
| (2, 1192) | 3 823 625 | 3 854 225 | 0 / 0 | 2e-15 |
| (2, 1229) | 3 025 825 | 3 025 850 | 0 / 0 | 9e-15 |
| (2, 89) | 1 121 729 | 2 038 679 | 0 / 0 | 2e-12 |
| (3, 67) | 1 045 503 | 1 058 753 | 0 / 0 | 3e-15 |
| (2, 84), (2, 184), (2, 193) | 4 776 / 3 126 / 2 176 | idéntico | 0 / 0 | 0 |

Se reproduce la cifra declarada de (2, 685): ≈ 1,35 M frente a ≈ 3,83 M. La opción «siempre toda la fila» nunca es
mejor en el conjunto medido y es **hasta 2,8× peor** (y con desviaciones de pesos de 2·10⁻⁸ en (2, 685)).
La decisión de conservar la escala de pesos cuando son informativos está por tanto justificada empíricamente.

Puntos ya recuperados: las 31 fronteras contractuales y del barrido conservadas (266 puntos recuperados, los mismos
en `main` y rama; los 77 puntos únicos de las 7 instancias contractuales incluidos), 0 inválidos, pesos idénticos.

**Oráculo independiente** (`nd.lp_max_return`, `scipy.linprog` sobre las variables originales) frente al LP de HiGHS
de la fila original y de la transformada: coinciden para objetivos factibles (−1e-4, −1e-3 respecto de mantener la
cartera) e infactible (+1e-6). Con μ idénticos NET, la recuperación forzada llega a OPTIMAL validado; con objetivo
infactible se confirma `CONFIRMED_INFEASIBLE`. Verificado ejecutando el módulo real de tests y mis scripts.

**Limitación registrada (fallo espontáneo no reproducible).** Los tests de P2-01 en NET (`test_net_recovery_of_
identical_returns_reaches_the_independent_optimum` y los relacionados) usan un `INFEASIBLE` inicial **fingido**.
No he podido reproducir espontáneamente que OSQP falle con retornos idénticos en NET: barrido propio de 450
fronteras (150 instancias aleatorias × 3 spreads de μ ∈ {0, 1e-12, 1e-9}, n = 2…4, costes y Σ aleatorios; 9 000 puntos) → **9 000
OPTIMAL válidos, 0 recuperaciones activadas, tanto en `main` como en la rama**. El defecto es real como
propiedad de la función (`None` donde la restricción es informativa) pero **latente** en el flujo completo: solo
se manifestaría si OSQP fallara primero en esa geometría.

**Banda intermedia (RF-01).** Recuperación forzada en NET con μ = [0.07, 0.07 + spread], objetivo = mantener la
cartera − 1e-4:

| spread | rama (adaptativo) | siempre toda la fila |
|---|---|---|
| 0, 1e-10 | 1 intento, ~175 it. | ~100 it. |
| **1e-9** | escala 2·10¹⁰; intentos OSQP: 25 475 it. | 100 it. (escala 782.7) |
| **2e-9** | escala 1·10¹⁰; **192 475 it.** | 100 it. |
| **5e-9** | escala 4·10⁹; 22 525 it. | 100 it. |
| ≥ 1e-8 | 176 it. | ~100 it. |

Para spread entre ≈ 1e-9 y 5e-9 (bloque de pesos > √eps del máximo de toda la fila) la regla vuelve a la escala de
pesos, que infla los coeficientes auxiliares a 10⁹–10¹⁰; OSQP tarda 10²–10³ veces más, y en un caso (2e-9) consume
192 475 de las 200 000 iteraciones de reintento (`max_iterations 50 000 × retry_iteration_multiplier 4`). Sigue
recuperando y validando, pero el margen es mínimo. No hay instancia natural (el barrido no la produjo) y la
implementación ya lo anticipa en sus «Known limitations», pero no está cubierto por ningún test.

## 5. P2-02 Verdict — iteraciones del oráculo

**Confirmado y corregido.** `_merge` sumaba `attempts` excluyendo `STRATEGY_ORACLE` mientras `solve_time` sí
incluía el oráculo (`main`); la rama suma todos los intentos.

## 6. Iteration Accounting

Inspección de `numerical_recovery.py::_merge` y `models/solution.py`:

* `iterations = sum(a.iterations for a in attempts)` con `attempts = [ORIGINAL, (ORACLE), *NORMALIZED]`: cada
  intento entra exactamente una vez (el resultado del oráculo se añade una sola vez; los reintentos, uno por
  escala).
* `SolveResult.iterations_by_solver`: sin recuperación → `((solver_name, iterations),)`; con recuperación →
  `trace.iterations_by_solver` (suma por nombre de solver desde los intentos). Orden alfabético.
* `FrontierSession.iterations_by_solver` suma sobre `_results`; `FrontierDiagnostics.iterations_by_solver` la
  recibe; `total_iterations` = suma de sus valores (test y mi comprobación).
* `setup_time`/`solve_time`: las líneas de tiempo del `_merge` no cambian respecto de `main` (`first + extra`,
  cada intento una vez). Verificado **solo por inspección**, no por test (RF-04).

Escenarios reproducidos independientemente (con los tests del implementador, ejecutados, y con mis propias
ejecuciones reales):

| caso | resultado esperado | verificado |
|---|---|---|
| A. OPTIMAL inicial sin recuperación | `recovery is None`, `(("OSQP", it),)` | sí (test real, `(2,84)` objetivo holgado) |
| B. Oráculo confirma INFEASIBLE | 10 + 4 = 14 (antes 10), HiGHS 4 / OSQP 10 | sí |
| C. Oráculo FEASIBLE + recuperación | 10 + 4 + 25 = 39 (antes 35) | sí |
| D. Oráculo INCONCLUSIVE | 10 + 6 + 25 = 41, semántica `INCONCLUSIVE` conservada | sí |
| E. Recuperación fallida | 10 + 4 + 5·escalas, estado reclasificado, iteraciones intactas | sí |
| F. Múltiples reintentos | 10 + 30 + 40 + 8 = 88, solo OSQP | sí |
| Real (OSQP + HiGHS) `(2,84)` GROSS | oráculo 1 vez, `HiGHS` en el desglose, sesión = punto | sí |

Los casos B–F usan un oráculo y reintentos **guionizados** (deterministas) contrastados contra constantes
codificadas a mano, no contra la función bajo prueba; el caso «real» cubre el flujo con solvers reales. Efecto real
medido con mi barrido de las 31 fronteras (GROSS/NET, 17 con recuperación): **+214 iteraciones en total**
(54 + 24 + 54 + 54 + 28), **coincide exactamente con lo declarado**. El aumento por punto es de 2 a 8 iteraciones
(71 puntos con cambio); las cifras «24…54» son **por frontera**, no por punto (RF-02).

Documentación de la semántica: `SolveResult`, `FrontierSession`, `FrontierDiagnostics` y `ARCHITECTURE.md`
(F3-06) describen la suma como métrica agregada de actividad, con el desglose por solver como métrica comparable.
Nota (RF-03): `outputs/builders.py` (`iterations`, `solver_iterations` por punto) exporta `SolveResult.iterations`
que ahora incluye HiGHS **sin desglose**; `iterations_by_solver` no llega a `outputs/` ni a los esquemas.

## 7. Regression B1/B2/B3

Comparación `main` vs rama (mismo motor real, `.venv`, `TARGET_RETURN_GRID`):

| conjunto | fronteras | puntos | inválidos rama | dif. estado/validez | dif. máx. pesos | recuperados |
|---|---|---|---|---|---|---|
| Contractual F-3: 7 instancias × GROSS/NET/POST_COST_GROSS + 10 del barrido | 31 | 620 | 0 | 0 | **0** | 266 (77 únicos de las 7 instancias + 135 de las 10 adicionales, POST_COST_GROSS repite los de GROSS) |
| Muestra independiente, n = 2…5, semillas **1400–1459** (fuera del rango declarado), GROSS y NET | 480 | 9 600 | 0 | 0 | 0 | 0 (ningún punto requirió recuperación) |
| Barrido parcial: n = 2 semillas 0–199, n = 3 0–69, n = 4/5 0–39, GROSS y NET | 700 | 14 000 | 0 | 0 | 0 | 77 |

Los 212 puntos recuperados declarados = 209 (n = 2) + 3 (n = 3) = **77 originales + 135 adicionales** (no
77 + 212: los 212 incluyen a los 77; en mis datos 74 + 3 = 77 en el barrido parcial y 135 en las 10 fronteras
del barrido). Todos coinciden en `main` y rama, 0 inválidos.

**Limitación de la auditoría:** no he reproducido íntegramente el barrido declarado (n = 2…5, semillas 0–1399,
224 000 puntos). Intenté ejecutarlo completo, pero los procesos concurrentes fueron estrangulados por el sistema
(uso de memoria/CPU de la máquina, 1,2 GB libres) y los abandoné. La cobertura es la de las muestras de la tabla
(≈ 24 600 puntos, incluidas las 17 fronteras con recuperación del barrido declarado y 480 fronteras fuera de
rango). Lo no comprobado por mí: las semillas n = 3…5 entre 70/40 y 1399 y las semillas n = 2 entre 200 y 1399
salvo las 10 conocidas. Dado que el cambio no toca ninguna ruta salvo la recuperación y el contador de
iteraciones, y que la ruta OPTIMAL queda intacta, el riesgo residual es bajo.

Suite completa (B1–B3, CandidateEngine, Global Frontier, Pareto, E-09/10/11): sin regresiones (§8). El diff no
modifica ningún módulo de candidatos, Pareto ni frontera global.

## 8. Test Evidence

Ejecutado por mí en el `.venv` (la primera ejecución con el Python del sistema falló por dependencias ausentes —
hypothesis, mypy, ruff— y fue descartada):

| comando | resultado |
|---|---|
| `pytest -q` | **1187 passed** (353 s), 0 fallidos |
| `mypy --strict portfolio_engine` | Success: no issues in 126 source files |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 262 files already formatted (el informe declara 261; diferencia irrelevante) |

Los 1187 se corresponden con 1151 previos + 36 nuevos (`test_f3_post_merge_review.py`).

**Los tests detectan los defectos originales** (probado sobre copias temporales de la rama con un fichero de
`main` restaurado):

* `qp_builder.py` de `main` → **17 fallos**, 19 pasan. Fallan por la razón esperada (`normalize_return_row`
  devuelve `None`; equivalencia algebraica y oráculo LP sobre la fila degenerada).
* `numerical_recovery.py` de `main` (oráculo excluido) → **4 fallos** (casos B, C, D, E), 32 pasan.
* Ambas cifras coinciden con lo declarado.

Calidad de los tests: hay asserts contra constantes independientes (sumas de iteraciones codificadas a mano,
`lp_max_return`/`two_asset_reference` del fixture, comparación con LP HiGHS en el problema original y el
transformado). `_check_sums` compara `iterations` con la suma de los intentos del propio `trace` (contrastes
internos), pero los totales absolutos de cada caso son independientes. Lagunas: ningún test cubre la banda de
RF-01, ni `setup_time`/`solve_time` (RF-04), ni un fallo espontáneo de OSQP con μ idénticos en NET.

**Protecciones de F-3 conservadas** (inspección del diff + suite): la rama no toca `RECOVERABLE_STATUSES`, la
lógica de aceptación, `SolutionValidator`, el oráculo ni la reclasificación:

* `OPTIMAL_INACCURATE` nunca se promociona (los reintentos solo se aceptan si son `OPTIMAL` y pasan `accept`).
* `INCONCLUSIVE` conserva semántica (caso D).
* El validador usa el retorno objetivo original (`accept=session._passes_validation(r, target)`).
* Un punto verdaderamente infactible no se acepta (`CONFIRMED_INFEASIBLE`, verificado con objetivo +1e-6).

## 9. Financial Invariants

Comparación `main` vs rama sobre todos los puntos de las tres tablas de §7: pesos idénticos bit a bit
(diferencia máxima 0), mismo estado y validez, mismos intentos de recuperación y mismas iteraciones salvo las del
oráculo. Dado que retornos bruto y neto, volatilidad, turnover y costes se calculan a partir de los pesos
(`SolutionValidator`/métricas, independientes del solver), no pueden diferir. No he recalculado columna a columna
retorno/volatilidad/turnover/costes ni el Pareto global; la afirmación se apoya en pesos idénticos + suite verde
(incluye B3 y Pareto). Los cambios de diagnóstico (iteraciones, `iterations_by_solver`) están claramente separados
de los de resultados financieros.

## 10. Traceability

* `TRACEABILITY.md`: una fila nueva de historial (SOL-002, OPT-005, FRN-008 con «evidencia ampliada»); ningún
  cambio de estado, total contractual **316** intacto (183 VALIDATED / 39 PARTIAL / 94 NOT_IMPLEMENTED según la
  fila anterior). Cero líneas eliminadas.
* `CHANGELOG.md`: entrada nueva, 26 líneas añadidas, ninguna eliminada; identifica los hallazgos como posteriores
  al merge del PR #3.
* `REMEDIATION_F3_NUMERICAL.md`: nota final «Nota posterior al merge del PR #3» (21 líneas añadidas, 0
  eliminadas); la evidencia histórica no se reescribe.
* `ARCHITECTURE.md`: las filas F3-02 y F3-06 se reescriben (2 líneas modificadas); es un documento vivo y el cambio
  refleja el comportamiento nuevo con referencia a la revisión post-merge.
* Informes históricos `AUDIT_*.md`, `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`: sin modificación.
* No hay avance de estados sin evidencia. Incidencia RF-02 en la redacción (ver abajo).

## 11. Residual Findings

Ninguno bloqueante.

| ID | Severidad | Evidencia | Impacto | Acción pendiente |
|---|---|---|---|---|
| RF-01 | P3 (no bloqueante) | Recuperación forzada NET, μ = [0.07, 0.07 + 1e-9…5e-9]: 22 525–192 475 iteraciones frente a ~100 con escala sobre toda la fila; umbral `√eps` discontinuo (escala ~10³ a un lado, ~10⁹–10¹⁰ al otro); 192 475 ≈ 96 % del presupuesto de reintento de 200 000. En las 9 000 soluciones de mi barrido con μ casi idénticos no se activó nunca la recuperación. | Riesgo de que un caso real de esa banda agote el presupuesto y quede `NOT_RECOVERED` (fallo numérico reclasificado, no invalidez financiera). Latente: no reproducido espontáneamente. | Añadir test/instancia de la banda; valorar una regla continua (p. ej. escala por el máximo de toda la fila cuando aquella sea comparable o menor que la de pesos, o probar ambas escalas en la escalera de reintentos) validándola contra (2, 685), (2, 89) y el barrido. Requiere decisión del usuario; no se propone aquí implementar. |
| RF-02 | P3 (documentación) | `F3_POST_MERGE_REVIEW.md` dice «+24…+54 por punto recuperado con oráculo» y `CHANGELOG.md` «(24-54 en las instancias…)». Medido: +2…+8 por punto (71 puntos), +24…+54 **por frontera**, +214 total. | Descripción imprecisa del efecto; sin impacto en resultados. | Corregir la redacción («por frontera», y añadir el rango por punto). |
| RF-03 | P3 | `outputs/builders.py` exporta `iterations`/`solver_iterations` por punto con el nuevo total (oráculo incluido) sin `iterations_by_solver`; `outputs/schemas.py` sin campo de desglose. La suma solo está documentada en modelos/ARCHITECTURE. | Consumidores de las exportaciones pueden interpretar `iterations` como homogéneo. | Documentar en el esquema de salida o exponer el desglose en un bloque posterior autorizado (fuera de esta corrección). |
| RF-04 | P3 | `setup_time`/`solve_time` no tienen test de no duplicación; verificado solo por inspección (líneas no modificadas respecto de `main`). | Bajo: el diff no las toca. | Añadir un test de aditividad de tiempos por intento cuando convenga. |
| RF-05 | P3 (limitación de la evidencia) | Tests P2-01 NET con fallo inicial fingido; el fallo espontáneo no se reproduce ni en `main` ni en la rama (9 000 puntos OPTIMAL). | El defecto es latente: la corrección es preventiva. | Mantener registrado; no se puede promover a «reproducido en flujo real». |
| AUD-01 | Limitación de auditoría | Barrido completo de 224 000 puntos no reproducido (procesos concurrentes estrangulados por el sistema); cubierto con 31 + 480 + 700 fronteras. | Cobertura parcial de mi verificación, no del proyecto. | Opcional: ejecutar el barrido completo en máquina descargada. |

## 12. Git Hygiene

* Rama actual `fix/f3-oracle-iteration-accounting`, HEAD `b59e446` (sin commits nuevos). Estado igual al inicial:
  9 ficheros modificados (`ARCHITECTURE.md`, `CHANGELOG.md`, `REMEDIATION_F3_NUMERICAL.md`, `TRACEABILITY.md`,
  `numerical_recovery.py`, `session.py`, `models/frontier.py`, `models/solution.py`, `qp_builder.py`) y 2 no
  seguidos (`F3_POST_MERGE_REVIEW.md`, `tests/unit/frontiers/test_f3_post_merge_review.py`), más este informe
  (`AUDIT_F3_POST_MERGE.md`, nuevo).
* Sin commit, merge, push, tag ni PR. No se modificó código productivo, tests ni documentación existente.
  Todas las copias y scripts de auditoría viven en el directorio temporal de la sesión.
* Aviso de git por normalización de finales de línea (LF→CRLF) en `CHANGELOG.md`,
  `REMEDIATION_F3_NUMERICAL.md` y `qp_builder.py`: hay que revisarlo antes del commit (no lo he modificado).

## 13. Final Decision

Las dos correcciones P2 son correctas y no cambian resultados financieros; los datos que declara el implementador
se reproducen (1187 tests, 17 y 4 tests que detectan los defectos, +214 iteraciones, 212 puntos recuperados,
1,35 M frente a 3,83 M en (2, 685)). Hay que corregir la redacción de RF-02 antes del commit; RF-01 queda como
seguimiento recomendado. Ningún hallazgo bloquea el merge.

---

F3_POST_MERGE_AUDIT_SUMMARY

P2-01:
Confirmado en `main` (`normalize_return_row` → `None` con μ idénticos y costes NET asimétricos) y corregido en la
rama (escala 782.7, fila finita); fallo espontáneo en el flujo completo no reproducible (0 de 9 000 puntos): defecto
latente.

P2-02:
Confirmado y corregido: `SolveResult.iterations` suma todos los intentos una vez cada uno (oráculo incluido);
`iterations_by_solver` coherente en `SolveResult`, `FrontierSession` y `FrontierDiagnostics`.

Mathematical equivalence:
`r'x − ℓ' = s(rx − ℓ_r)` para todo `x` con presupuesto; error numérico máx. 3.9e-13; variables, objetivo, demás
filas, target, costes y tolerancias sin cambios.

Iteration totals:
+214 iteraciones sobre 17 fronteras con recuperación (54, 24, 54, 54, 28; +2…+8 por punto, 71 puntos); coincide
con lo declarado; solo el oráculo cambia el total.

Recovered points:
212 = 209 (n = 2) + 3 (n = 3) = 77 originales + 135 adicionales; 266 puntos recuperados en las 31 fronteras
contractuales, iguales en `main` y rama, 0 inválidos.

Economic regression:
0 diferencias de estado/validez/pesos (dif. máx. 0) en 31 + 480 + 700 fronteras (≈ 24 600 puntos); barrido completo
de 224 000 puntos no reproducido (limitación de la auditoría).

Tests passed:
1187 (pytest); `mypy --strict` 126 ficheros OK; `ruff check` OK; `ruff format --check` 262 ficheros OK.
Con `qp_builder.py` de `main` fallan 17 tests nuevos; con `numerical_recovery.py` de `main` fallan 4.

Tests failed:
0

Open blocking findings:
Ninguno.

Open non-blocking findings:
RF-01 (banda de escala intermedia NET, P3), RF-02 (redacción «por punto» vs «por frontera», P3), RF-03 (outputs
sin desglose, P3), RF-04 (sin test de aditividad de tiempos, P3), RF-05 (P2-01 latente, cubierto con fallo
fingido, P3), AUD-01 (barrido completo no reproducido).

Git status:
Rama `fix/f3-oracle-iteration-accounting`, HEAD `b59e446`; 9 ficheros modificados + 2 no seguidos (test e informe
de la implementación) + este informe; sin commit, merge, push, tag ni PR.

AUDIT_F3_POST_MERGE_STATUS = PASS_WITH_CHANGES
