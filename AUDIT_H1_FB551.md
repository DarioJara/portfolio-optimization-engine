# AUDIT_H1_FB551 — Auditoría independiente de la remediación numérica H-1 (B4) y F-B55-1 (B3)

Fecha: 2026-10-22. Auditado: PR #10, rama `fix/h1-fb551-numerical-remediation`, SHA `d5e1a57be8ece01096eb753b3dc58f25fc3a1984` (base `8ceaf3a` = `main`).
No se ha modificado código de producción, ni `main`, ni B5.5; sin commit, push ni merge. Sin benchmarks masivos y sin acceso a Arsys/Oracle/SQL Server.
Las copias de trabajo salieron de `git archive` (`8ceaf3a` y `d5e1a57`) en el *scratchpad*; los scripts de evidencia están en `evidence/audit_h1_fb551/` (sin seguimiento git).

## NUMERICAL_REMEDIATION_AUDIT_STATUS = PASS_WITH_CHANGES

**¿Es seguro integrar el PR #10 en `main`? Sí desde el punto de vista matemático y de regresión, condicionado a 2 cambios documentales y 1 decisión explícita del propietario (M-1, M-2).**
No hay BLOCKER ni HIGH. Las dos correcciones son matemáticamente correctas, no relajan ninguna tolerancia, no promueven estados y no producen regresiones observables en B1–B5.4.
Lo que impide un `PASS` limpio es que el informe del PR **subestima el cambio observable de B3**: los empates no son un caso raro y `rank_nodes` altera el conjunto de composiciones candidatas de `main` en ~la mitad de los problemas aleatorios probados (M-1).

| Gravedad | Nº | IDs |
|---|---|---|
| BLOCKER | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 2 | M-1, M-2 |
| LOW | 4 | L-1 … L-4 |
| INFO | 5 | I-1 … I-5 |

## 1. Entorno de la auditoría y límites

| | Valor |
|---|---|
| Máquina | Windows 11, i7-13620H (núcleo OpenBLAS `Haswell`), Python 3.13.6 |
| Versiones | numpy **2.2.6**, scipy 1.16.1, clarabel 0.11.1, osqp 1.0.5, cvxpy 1.7.3, OpenBLAS 0.3.29 (`scipy-openblas`) |
| Diferencia con el lock | El lock exige numpy 2.5.3 / scipy 1.18.1 / osqp 1.1.3 / OpenBLAS 0.3.34; la CI Linux del PR usa numpy 2.4.6 / scipy 1.17.1. **Esta auditoría añade una tercera combinación de versiones.** |
| No disponibles aquí | `mypy`, `ruff`, `hypothesis`, `PySCIPOpt` (no instalados; no se descargó nada sin permiso). `tests/property` excluido; los fallos por SCIP son de entorno (§9). |

Consecuencia importante: en este entorno **la base reproduce de forma determinista el fallo original de H-1** (el entorno del autor, numpy 2.5.3/OpenBLAS 0.3.34, no lo reproducía en Windows). Es una confirmación independiente y fortalece la evidencia.

## 2. Reproducción de los dos tests originales de H-1 (puntos 2 y 13)

`tests/unit/scenarios/test_multi_scenario.py::{test_single_solutions_satisfy_the_constraints_of_every_scenario, test_worst_case_maximizes_the_minimum_scenario_utility}`, `OPENBLAS_NUM_THREADS=1`, 2 tests por celda:

| `OPENBLAS_CORETYPE` | Base `8ceaf3a` | PR `d5e1a57` |
|---|---|---|
| (sin forzar, `Haswell`) | **1 failed**, 1 passed | 2 passed |
| `Haswell` | 1 failed, 1 passed | 2 passed |
| `Sandybridge` | 1 failed, 1 passed | 2 passed |
| `Nehalem` | 1 failed, 1 passed | 2 passed |
| `Zen` | 1 failed, 1 passed | 2 passed |
| `Core2` | 2 passed | 2 passed |

* El test que falla en la base es el primero, con **exactamente los mismos números de la anotación de CI** del PR #9: `worst_case_utility = -0.09260875000001824`, `solver_t = -0.09260875000001369`.
* El PR con hilos por defecto (16): 85 tests de los módulos afectados (`test_multi_scenario`, `test_h1_clarabel_numerics`, `test_tie_stability`, `test_block4_config`) pasan.
* El segundo test (oráculo SLSQP) no falló en la base en este entorno; su análisis es independiente (§5).

## 3. Barrido determinista de H-1 (puntos 3, 4, 5; 360 resoluciones)

Instancia exacta del primer test; perturbación determinista de `b` y `q` de Clarabel (relativa `eps` o **±1 ulp con `np.nextafter`**), 30 semillas por celda. Script: `h1_sweep.py`. Se instrumentan `solve`, `cold_retry` y `DefaultSolver` (ajustes).

| Celda | Base: válidas / `OPTIMAL` / `OPTIMAL_INACCURATE` / sin pesos | PR: válidas / `OPTIMAL` / `OPTIMAL_INACCURATE` / sin pesos |
|---|---|---|
| `eps` = 0 | 0 / 0 / 30 / 0 | **30** / 30 / 0 / 0 |
| `eps` = 1e-16 | 14 / 14 / 16 / 0 | **30** / 30 / 0 / 0 |
| `eps` = 1e-14 | 13 / 13 / 17 / 0 | **30** / 30 / 0 / 0 |
| `eps` = 1e-12 | 11 / 11 / 19 / 0 | **30** / 30 / 0 / 0 |
| `eps` = 1e-10 (estrés) | 1 / 1 / 27 / **2** | **30** / 30 / 0 / 0 |
| **±1 ulp (`nextafter`)** | 18 / 18 / 12 / 0 | **30** / 30 / 0 / 0 |

Hallazgos:

1. **Conservación de tolerancias y restricciones (punto 3).** En las 180 resoluciones del PR hay **una única tupla** `(tol_gap_abs, tol_gap_rel, tol_feas, tol_infeas_abs, tol_infeas_rel) = (1e-9)×5`; el reintento usa `max_iter = 800` (= 200 × `retry_iteration_multiplier`) y `equilibrate_enable = False`. `validation.violations` vacío en las 180. La política de estado (`accept_inaccurate_solutions = false`) no cambia.
2. **El reintento de la base era inútil (confirma el diagnóstico):** en las 121 resoluciones con reintento `OPTIMAL_INACCURATE → OPTIMAL_INACCURATE`, `max|Δx| = 0` y `|Δobj| = 0` exactos (mismo método determinista). En 2 casos de la base el reintento termina `NUMERICAL_ERROR` **sin pesos** (eps = 1e-10).
3. **Con la corrección:** los 123 reintentos acaban `OPTIMAL` (121 desde `OPTIMAL_INACCURATE`, 2 desde `NUMERICAL_ERROR`), con pesos que se mueven `max|Δx| = 9,1·10⁻¹⁰` y `|Δobj| = 1,6·10⁻¹⁰` respecto al primer intento, es decir, dentro de la tolerancia de 10⁻⁹. Iteraciones medias del reintento: 8,0 frente a 10,8.
4. **El primer intento no cambia:** en los 57 casos en que ni la base ni el PR necesitan reintento, pesos y estado son **idénticos bit a bit** (57/57).
5. **Sin promoción artificial de estados (punto 4):** `solve_with_policy` sustituye el resultado por el del reintento con **su propio** estado nativo; el estado `OPTIMAL` de los 123 reintentos viene de un `Solved` genuino de Clarabel (`Terminated with status = Solved`, comprobado además en el test espía `test_the_retry_changes_the_numerics_after_a_stall…`). El mapa `CLARABEL_STATUS_MAP` no se ha tocado (`almostsolved → OPTIMAL_INACCURATE`). No existe ningún camino de código que convierta `AlmostSolved` en `OPTIMAL`. La validación independiente de pesos (`report.is_valid`) sigue siendo condición adicional.

### 3.1 Evidencia matemática de que `Solved` sin equilibrado cumple lo mismo (`kkt_check.py`)

Recalculo independiente (desde `x, s, z`, sin fiarme de Clarabel) en 150 instancias SOCP de cartera con escalado heterogéneo, `tol = 1e-9`:

| Reintento | `Solved` | máx. residuo primal | máx. residuo dual | máx. brecha relativa |
|---|---|---|---|---|
| con equilibrado (comportamiento base) | 127 | 2,8·10⁻⁹ | 3,8·10⁻¹¹ | 9,8·10⁻¹⁰ |
| **sin equilibrado (PR)** | 146 | 3,5·10⁻⁹ | 6,5·10⁻¹¹ | 9,9·10⁻¹⁰ |

La normalización propia no coincide con la interna de Clarabel (ambos superan 10⁻⁹ en residuo primal con mi normalización), así que **no se puede afirmar igualdad exacta de la condición de parada**; sí que la calidad es del mismo orden y que el equilibrado no relaja la garantía de forma apreciable. El `Solved` sigue siendo la afirmación del solver, respaldada por la validación independiente de pesos.

### 3.2 Casos en que el segundo intento empeora o cambia la solución (punto 5; `retry_stress.py`, `retry_stress_wide.py`)

Estrés directo sobre Clarabel: SOCP de cartera (5–39 activos), 3 familias (`plain`, `scaled` con columnas 10^U(−3,3) y 10^U(−6,6), `lowrank`), `tol` ∈ {1e-9, 1e-11, 1e-12}, 200 instancias por celda; se compara el reintento de la base (con equilibrado) con el del PR (sin él) sólo cuando el primer intento no es `Solved`.

* **Reintento del PR peor que el de la base: 0 casos** en ambas ejecuciones (rangos de escala 10³ y 10⁶). Mejor: 143 y 112 casos.
* A la tolerancia de producción (1e-9): sólo la familia `scaled` falla el primer intento; el reintento del PR lo rescata en **19/19** (escala 10³) y **85/91** (escala 10⁶); en los 6 restantes queda `AlmostSolved` → `OPTIMAL_INACCURATE` correctamente distinguido y rechazado. El reintento de la base no rescata ninguno.
* **Cambio de solución:** entre dos resultados utilizables, `max|Δx| > 10⁻⁶` aparece siempre en pares donde al menos uno es `AlmostSolved`. Por tolerancia: a 1e-11/1e-12 (fuera de producción) 233 casos; **a la tolerancia de producción 1e-9 hay 10 casos (todos en la familia `scaled`), con `max|Δx| = 2,4·10⁻⁴` y `|Δobj| ≤ 1,4·10⁻⁹`**. Es decir, el reintento sin equilibrado puede devolver un punto que difiere en pesos hasta ~2·10⁻⁴ del que daría el reintento equilibrado (que nunca converge a `Solved` en esos casos), con el mismo valor objetivo a ~10⁻⁹: la tolerancia 10⁻⁹ fija el objetivo, no los pesos, en direcciones planas/mal escaladas. En la instancia de H-1 el desplazamiento es ≤ 9·10⁻¹⁰ (§3). No es un defecto (el punto pasa la validación independiente de restricciones), pero conviene saberlo (I-1).
* **Limitación:** no se encontró un caso en que el reintento sin equilibrado devuelva un fallo duro (`NumericalError`/`InsufficientProgress`) sobre un primer intento `AlmostSolved` utilizable, pero **el diseño no lo impide** (L-2).

## 4. Oráculo SLSQP y `ftol = 1e-12` (punto 6; `slsqp_oracle.py`)

Mismo problema que el segundo test; 200 arranques por celda con el punto inicial perturbado en 10⁻¹²; referencia = solución del motor (`worst_case_utility = −0,01771815284692995`):

| `ftol` | éxitos | máx. `|x − x_motor|` | máx. `|f − f_motor|` | máx. violación |
|---|---|---|---|---|
| 1e-15 (original) | **153/200** | 1,66·10⁻⁷ | 2,4·10⁻¹² | 3,9·10⁻¹⁵ |
| 1e-13 | 191/200 | 1,71·10⁻⁷ | 2,8·10⁻¹² | 5,5·10⁻¹³ |
| **1e-12 (PR)** | **200/200** | 1,72·10⁻⁷ | 2,8·10⁻¹² | 5,6·10⁻¹³ |
| 1e-10 | 200/200 | 1,71·10⁻⁷ | 2,8·10⁻¹² | 5,6·10⁻¹³ |
| 1e-8 | 200/200 | 1,42·10⁻⁶ | 2,1·10⁻¹⁰ | 2,1·10⁻¹⁰ |

Justificación: `ftol` en SLSQP es un criterio de parada sobre `|Δf|` y sobre la violación de restricciones, no una cota de error; con 10⁻¹⁵ ≈ 70 ulp del óptimo (|f| ≈ 0,09, ulp ≈ 1,4·10⁻¹⁷) la búsqueda lineal falla («Positive directional derivative») en ~23 % de los arranques. Con 10⁻¹² el éxito es 100 %, y el error medido (1,7·10⁻⁷ en pesos; 2,8·10⁻¹² en valor) deja un margen de ×580 sobre `atol = 1e-4` y de ×3·10⁴ sobre `abs = 1e-7` del test. **Las aserciones del test no cambian y el cambio de `ftol` no debilita el test** (incluso 1e-8 seguiría dentro de las tolerancias). Matiz (L-4): el oráculo no tiene referencia independiente de ambos; el test compara motor contra SLSQP.

## 5. F-B55-1 (B3) — perturbaciones de 1 ulp (puntos 7 y 8; `fb_sweep.py`)

Universo con dos pares de activos clonados (empates exactos), el del test del PR; ruido determinista en `μ` y `Σ` (simétrica), 40 semillas por celda, conjunto de `composition_id` devueltos:

| Perturbación | Base: conjuntos distintos / tamaños / iguales a su referencia | PR: conjuntos distintos / tamaños / iguales a su referencia |
|---|---|---|
| **±1 ulp (`nextafter`)** | **13** / {10} / 4 de 40 | **1** / {9} / 40 de 40 |
| relativa 1e-16 | 13 / {10} / 8 de 40 | 1 / {9} / 40 de 40 |
| relativa 1e-14 | 13 / {10} / 1 de 40 | 1 / {9} / 40 de 40 |
| relativa 1e-12 | 13 / {10} / 0 de 40 | 1 / {9} / 40 de 40 |
| relativa 1e-11, 1e-10, 1e-9 (30 semillas) | — | 1 / {9} (los tres) |
| relativa 1e-8 (30 semillas) | — | **6** / {8, 9} |

* Con `rank_nodes` el conjunto es **invariante** hasta ruido relativo de 10⁻⁹ (= `improvement_tolerance`, margen ≈ 10⁷ sobre el ruido de 1 ulp) y deja de serlo en 10⁻⁸, como cabe esperar: ahí el ruido supera la tolerancia y las diferencias dejan de ser empates.
* Tamaño de la referencia: la base da 10 y el PR 9 composiciones (cambio observable documentado por el propio informe).
* **No fusiona candidatos materialmente distintos:** `rank_nodes` sólo reordena; no elimina ni agrupa composiciones. Sólo cambia cuál de dos mejoras a menos de 10⁻⁹ se prefiere por hash; en los casos con conjunto distinto las composiciones que salen y las que entran tienen la **misma mejora** (p. ej. 0,0618103/0,0618103), la mejor mejora global no empeora y en un caso (`rand|14|2`) el PR incluso añade una candidata mejor (0,0601 frente a 0,0570).

### 5.1 La función no es continua en el borde de la banda (L-1; `band_edge.py`)

`ranking_key` pasa de discontinuo en *todos* los empates a discontinuo sólo en el borde `gap = τ`: con dos mejoras separadas exactamente `τ = 1e-9`, desplazar una de ellas ±3 ulp **cambia el orden** (`('z','a')` ↔ `('a','z')`). Lejos del borde, 0 cambios en 20.000 perturbaciones de 1 ulp. La probabilidad por par de caer en el borde es ≈ ulp/τ ≈ 10⁻⁸. Además el agrupamiento por ancla no es transitivo (con pasos de 0,6 τ el tercer nodo queda fuera del grupo del primero aunque esté a 0,6 τ del segundo), comportamiento intencionado ("sin encadenar") pero que hace que «desempate continuo» (REMEDIATION §5.2) sea inexacto: es **estable casi seguro**, no continuo.

## 6. Cambios observables en B3 respecto a `main` (punto 13; `fb_why.py`) — M-1

REMEDIATION §5.2/§7 afirma que, en entradas sin empates, el orden es idéntico, y trata los empates como un caso particular. Medido en problemas **aleatorios** (`random_problem`, 10 y 14 activos, 12 semillas, 24 casos, sin clones):

* **12 de 24 casos devuelven un conjunto de composiciones distinto al de `main`** (4 con una composición más o menos —10→11, 9→8, 11→12, 11→10—, 8 con sustituciones de igual tamaño y misma mejora).
* En los 14 problemas instrumentados (7 semillas × 2 tamaños) el orden de `rank_nodes` difiere del de `ranking_key` en 4–8 de 12–13 llamadas por problema: los empates exactos (entrantes con peso cero) son **la norma**, con 16–215 pares de mejora exactamente igual por problema, y además decenas a centenares de pares con 10⁻¹⁴ < gap ≤ 10⁻⁹ (p. ej. ≈50 y ≈340) que antes se ordenaban por su diferencia real (diminuta) y ahora por hash.
* Calidad: mejor mejora no empeora en ningún caso; los sustituidos tienen la misma mejora.

Esto **no es un defecto** (el criterio es matemáticamente defendible y todos los tests existentes de B3 siguen pasando), pero es un cambio de comportamiento de un bloque `VALIDATED` que el informe presenta como acotado. Requiere (a) corregir la redacción, (b) cuantificar el cambio sobre los baselines de B3/B5 y (c) aceptación explícita del propietario (invariancia de conjunto frente a «sólo T1 sobre los pesos»).

## 7. Compatibilidad: `retry_equilibrate` obligatorio y `config_hash` (punto 10; `cfg_compat.py`)

| Comprobación | Resultado |
|---|---|
| TOML sin `retry_equilibrate` | `ConfigError: Clave obligatoria ausente: conic.retry_equilibrate` (cambio incompatible, deliberado) |
| Valor no booleano | rechazado por `ConicSolverConfig.__post_init__` y cubierto por `test_block4_config.py` |
| `config_hash` de `config/default_engine.toml` | `5d3cdc5e…` (base) → `86af211e…` (PR); también cambia al alternar sólo `retry_equilibrate` |
| Config con `retry_equilibrate == equilibrate` | aceptada sin aviso (reintento idéntico al primer intento, el defecto original) — L-3 |
| Hashes guardados | `benchmarks/results/*.json` y `evidence/b5_4_remediation/*.json` contienen `config_hash` antiguos: no coincidirán con el nuevo (comportamiento esperado de B5.3/B5.4; deben regenerarse al rebasar) |
| `.github/workflows/ci.yml` | idéntico a `main` (el disparador temporal se retiró) |

## 8. Evidencia de CI Windows/Linux y 12 runners (punto 11)

Evidencia `ci_annotations_run_3b1cc5c.json` (revisada localmente, no consultada en GitHub: `gh` no disponible):

* 12 trabajos «CPU sample»: **6 con núcleo `Haswell`** (5 × EPYC 7763 + 1 × EPYC 9V74 VM) donde la **base falla los 2 tests (`2 failed`) y el PR pasa**; **6 con `SkylakeX`** (3 × EPYC 9V45, 2 × EPYC 9V74, 1 × Xeon 8370C) donde ambos pasan. **926 passed en los 12** (módulos afectados). Coherente con lo que reproduzco localmente (§2).
* Suite completa sólo en **un** runner (EPYC 7763): 1973 passed, 2 skipped.
* Los 12 runners son **4 modelos de CPU y 2 núcleos de OpenBLAS**, todos x86-64 Linux, Ubuntu 22.04, Python 3.11.17, numpy 2.4.6. No hay ARM, macOS ni otras versiones de OpenBLAS. La CI **no instala el lock** (numpy 2.4.6 vs 2.5.3).
* El resultado de mypy/ruff en CI se infiere de la conclusión `success` del trabajo (los pasos `mypy --strict portfolio_engine`, `ruff check`, `ruff format --check` están en `ci.yml`); las anotaciones no los recogen.
* Windows: sólo la ejecución local del autor (1962 passed/10 skipped) y la mía (§9).

## 9. Suite completa, mypy y ruff (puntos 12 y 13)

* `pytest` completo (sin `tests/property`, sin `hypothesis`): **PR `d5e1a57`: 2 failed, 1915 passed, 40 skipped (24 min)**. Los 2 fallos: `test_router_block4.py::test_the_four_backend_families_are_routed_by_mathematical_structure` y `test_codec.py::test_all_workload_classes_round_trip_exactly` → ambos por `RoutingError: PySCIPOpt no está instalado (E-24)`, ajenos al PR. Base `8ceaf3a`: ver línea siguiente.
* **Base `8ceaf3a`, mismo entorno: 3 failed, 1898 passed, 40 skipped (24 min)**: los mismos 2 fallos de SCIP **más** `test_multi_scenario.py::test_single_solutions_satisfy_the_constraints_of_every_scenario` (H-1). Diferencia PR − base: −1 fallo (H-1 corregido), **+17 tests nuevos pasan** (1915 − 1898), 0 regresiones, los mismos 40 omitidos. Ejecuciones secuenciales sin otra carga propia; había procesos `python` huérfanos de sesiones anteriores en la máquina (tiempos no comparables con la CI).
* `mypy --strict` y `ruff check/format`: **NO EJECUTADOS** aquí (no instalados). Revisión estática del diff: tipos explícitos (`rank_nodes`, `_new_solver(…, equilibrate: bool)`), sin `Any` nuevo salvo el ya existente `Any` de Clarabel.
* Regresiones B1–B5.4: ninguna observada. Los cambios observables medidos son los de §3 (conic `OPTIMAL_INACCURATE`→`OPTIMAL`) y §6 (selección entre empates en B3).

## 10. Hallazgos

### MEDIUM

**M-1 — El cambio observable de B3 está subestimado.** Ver §6. *Evidencia:* 12/24 conjuntos distintos a `main`; empates exactos en 14/14 problemas. *Impacto:* los baselines/golden de B3 y B5 que dependan del conjunto exacto de composiciones deben regenerarse; el texto del PR («sin empates idéntico»; «el universo con clones pasa de 10 a 9») induce a creer que es un caso marginal. *Acción:* reescribir REMEDIATION §5.2(b), §7 con estas cifras; confirmar por escrito la decisión del propietario (b) de §8 del informe del PR.

**M-2 — Decisiones de propietario sin tomar que condicionan el cierre:** valor de producción de `retry_equilibrate` (la evidencia lo respalda: 0 casos peores en 3.600 instancias, 19/19 y 85/91 rescates a 1e-9), invariancia de conjunto (M-1) y orden de rebase de B5.5 (PR #9) con regeneración de `config_hash`/baselines. No son defectos de código; deben quedar registradas antes del merge.

### LOW

**L-1 — Desempate «continuo» inexacto:** discontinuidad en el borde `gap = τ` y agrupación no transitiva (§5.1). Probabilidad ≈ 10⁻⁸ por par; documentar como «estable casi seguro»; `τ` es absoluto (`improvement_tolerance = 1e-9`): si la escala de la utilidad cambia mucho (p. ej. unidades), `τ` dejaría de ser inmaterial; no se valida frente a la escala.

**L-2 — Reintento sin comparación de calidad y estado oculto en el backend.** `solve_with_policy` sustituye siempre el primer resultado por el reintento (diseño previo); con numérica distinta aumenta la superficie de un reintento peor que un `AlmostSolved` utilizable (no observado en el estrés). Además `_last_native_status` no se reinicia en `setup()/update()` y se compara por cadena exacta `"MaxIterations"`, mientras el resto del código normaliza con `map_clarabel_status(...).strip().lower()`; un cambio del `repr` de Clarabel degradaría silenciosamente a «cambiar numérica» incluso tras límite de iteraciones. Sugerencia: usar `map_clarabel_status(native) is SolverStatus.MAX_ITERATIONS`.

**L-3 — `retry_equilibrate == equilibrate` se acepta sin aviso** y reproduce el defecto original (reintento idéntico). Sólo hay una nota en el docstring.

**L-4 — Oráculo SLSQP sin referencia independiente** y justificación de «70 ulp» heurística (el propio `INVESTIGATION_H1_B4.md` la califica de interpretación). No afecta a la corrección del test (márgenes ×580).

### INFO

* **I-1:** la corrección de H-1 se ha medido sobre **una** instancia degenerada del repositorio más estrés sintético; en 6/91 casos extremos (escala 10⁶) el reintento también se estanca y el resultado sigue `OPTIMAL_INACCURATE` (correctamente rechazado). En problemas mal escalados el reintento rescatado puede mover los pesos hasta ~2·10⁻⁴ con igual objetivo a ~10⁻⁹ (§3.2); un consumidor que dependa de la precisión de los pesos (no del objetivo) debe saberlo.
* **I-2:** el disparador entre CPU (núcleo OpenBLAS `Haswell` vs `SkylakeX`) se confirma indirectamente: reproduzco el fallo de la base con `Haswell`, `Sandybridge`, `Nehalem` y `Zen` y no con `Core2` (§2); no se pudo forzar `SkylakeX` (la CPU local no tiene AVX-512).
* **I-3:** F-B55-1 sobre el lote de referencia W1 de B5.5 (`cross_platform_reference.py`) **no se ha reproducido** (requiere rebasar B5.5, fuera del alcance); la verificación equivalente se hizo sobre universo con clones y 24 problemas aleatorios.
* **I-4:** mypy/ruff no ejecutados localmente (§9); los 2 tests omitidos de CI y los 40 omitidos locales son los mismos de la base (SCIP, Linux-only).
* **I-5:** el estado de requisitos (`TRACEABILITY.md`: SOL-002, SOL-005, SOL-014, SCN-006, CAN-007 «sin cambio») es coherente con CLAUDE.md; no se declara nada como `VALIDATED` sin test.

## 11. Decisiones matemáticas pendientes

1. ¿Se acepta que el desempate de B3 sea **invariante de conjunto** (a costa de cambiar el conjunto de `main` en empates, §6) en lugar de sólo T1 sobre pesos? (M-1)
2. Confirmar `retry_equilibrate = false` como valor de producción (la alternativa de relajar `tol_*` queda descartada por los datos: el suelo del residuo es 4·10⁻⁹…10⁻⁸).
3. ¿`τ` absoluto es aceptable o debe hacerse relativo a la escala de la utilidad? (L-1)
4. Qué hacer con los 6/91 casos de escala extrema donde el reintento sigue `AlmostSolved` (escalonar tolerancias, o aceptar el rechazo actual). (I-1)
5. Rebase de B5.5 (PR #9): retirar `xfail`, una sola variante 484/11, regenerar `config_hash`.

## 12. Comandos reproducibles

Desde el *scratchpad* (`base/` y `pr/` = `git archive 8ceaf3a` / `d5e1a57`), con el Python del §1:

```
python h1_sweep.py <arbol> out.json 30            # §3  (base y pr)
python retry_stress.py 0 200 ; python retry_stress_wide.py 1 200   # §3.2
python kkt_check.py                               # §3.1
python slsqp_oracle.py <arbol>                    # §4
python fb_sweep.py <arbol> out.json 40 ; python fb_sweep_hi.py <arbol> out.json 30   # §5
python fb_why.py <arbol> ; python band_edge.py <arbol>                                # §5.1, §6
python cfg_compat.py <arbol>                      # §7
OPENBLAS_NUM_THREADS=1 OPENBLAS_CORETYPE=<tipo> python -m pytest tests/unit/scenarios/test_multi_scenario.py::<test>   # §2
python -m pytest -q --ignore=tests/property        # §9
```
