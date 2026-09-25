# REMEDIATION_F3_NUMERICAL

# Remediación numérica independiente de la incidencia F-3 (heredada del Bloque 2)

**Rama:** `fix/b2-numerical-f3` · **Baseline:** tag `block3-validated` (commit `4089909`, idéntico a `HEAD` al iniciar) ·
**Fecha:** 2026-09-24 · **Alcance:** solo F-3. No pertenece a la implementación del Bloque 4; sin commit, merge,
push, tag ni PR. Los informes históricos (`AUDIT_BLOCK_2*.md`, `AUDIT_BLOCK_3*.md`, `REMEDIATION_BLOCK_3*.md`) no
se alteran.

`F3_NUMERICAL_REMEDIATION_STATUS = PASS` (ver §12 y el bloque final).

---

## 1. Resumen

F-3 es un defecto numérico real de la frontera `TARGET_RETURN_GRID`: en problemas con una región factible en forma
de **franja casi degenerada**, OSQP declaraba `INFEASIBLE` (certificado espurio), `NUMERICAL_ERROR`,
`MAX_ITERATIONS` u `OPTIMAL_INACCURATE` en puntos que un LP independiente (HiGHS) demuestra factibles. Los puntos
inválidos estaban bien etiquetados (nunca se aceptaron), pero empobrecían la frontera de una composición (hasta 18
de 20 puntos) y, por herencia, la `GLOBAL_CANDIDATE_FRONTIER`.

**Remediación:** (1) el certificado de inviabilidad de OSQP se contrasta con un LP de factibilidad independiente;
(2) los puntos de retorno objetivo no óptimos se reintentan de forma **determinista y acotada** sobre un problema
**exactamente equivalente** con la fila de retorno centrada (con la fila de presupuesto) y escalada; (3) un
reintento solo se acepta si es `OPTIMAL` **y** supera el `SolutionValidator` con el retorno objetivo original; (4) el
estado y todos los intentos quedan registrados. No se relajó ninguna tolerancia, no se cambió el objetivo solicitado
y `OPTIMAL_INACCURATE` no se promueve nunca.

**Resultado (evidencia en §8-§10):**

| Medida | Antes | Después |
|---|---|---|
| 7 instancias contractuales × GROSS/NET/POST_COST_GROSS | 10 de 21 combinaciones con puntos inválidos (77 puntos únicos; `POST_COST_GROSS` repite los de `GROSS`) | 0 puntos inválidos |
| Barrido determinista `n = 2…5`, semillas 0-1399, GROSS y NET, `TARGET_RETURN_GRID` (11 200 fronteras, 224 000 puntos) | 17 fronteras con puntos inválidos, **212** puntos | **0** |
| Barrido adicional, semillas 1400-2999 (solo código nuevo) | — | 12 800 fronteras, 255 982 puntos: **0** puntos inválidos |
| Fronteras sin defecto previo (11 183) | — | **idénticas**: mismo número de iteraciones en las 11 183; huella B2/B3 (54 configuraciones) idéntica bit a bit a `block3-validated` |
| Suite completa | 1039 passed | **1148 passed** (1039 + 109 nuevos), 0 failed, 0 skipped |
| `mypy --strict` / `ruff check .` / `ruff format --check .` | limpios | limpios (126 ficheros / 259 ficheros) |

---

## 2. Precheck y línea base

```text
git branch --show-current   →  fix/b2-numerical-f3
git status                  →  clean (árbol limpio al iniciar)
git tag --list block3-validated  →  block3-validated   (^{commit} = 4089909 = HEAD; git diff block3-validated HEAD vacío)
```

Suite completa en el baseline (entorno `.venv`, Python 3.13, `osqp 1.1.3`, `scipy 1.18.1`, `numpy 2.5.3`,
`hypothesis 6.168.1`): **1039 passed en 101,02 s**. `tests/property/test_invariants.py` pasó en esa ejecución: el
fallo es esporádico (Hypothesis genera 25 ejemplos aleatorios por ejecución) y **no** se ocultó con reejecuciones
selectivas; se reprodujo de forma determinista con las instancias de §3. No apareció ninguna regresión nueva: todos
los fallos observados en el baseline pertenecen a la familia F-3.

Nota de entorno: el intérprete global no tiene `hypothesis`; todas las ejecuciones usan `.venv/Scripts/python.exe`.

---

## 3. Casos contractuales F-3 (reproducción original)

Las siete instancias `(n, semilla)` de `AUDIT_BLOCK_3_FINAL_CLOSURE.md` §14 se reprodujeron con
`tests/fixtures/near_degenerate.py::instance` (mismo generador que el test de propiedades) × `GROSS`, `NET` y
`POST_COST_GROSS` (este último hereda los pesos de `GROSS`) con `TARGET_RETURN_GRID`, con `numerical_recovery =
false` (comportamiento idéntico al baseline, comprobado con `test_without_recovery_the_baseline_statuses_are_reproduced`
y con la huella de §9). Resultados idénticos a los del cierre de B3:

| Instancia | Tratamiento | Inválidos / 20 | Estado OSQP | Estado nativo | Residual primal / dual (1.er punto inválido) | Iteraciones (1.er punto) | Oráculo LP | Margen objetivo↔máximo |
|---|---|---|---|---|---|---|---|---|
| (2, 84) | GROSS, POST_COST_GROSS | 18 | `INFEASIBLE` | primal infeasible | 1,29e-7 / 2,34e-13 | 25 | factible (18/18) | 1,3e-7 … 2,3e-6 |
| (2, 184) | GROSS, POST_COST_GROSS | 18 | `INFEASIBLE` | primal infeasible | 1,13e-6 / 6,59e-12 | 25 | factible (18/18) | 1,1e-6 … 2,0e-5 |
| (2, 193) | GROSS, POST_COST_GROSS | 18 | `INFEASIBLE` | primal infeasible | 2,78e-7 / 2,58e-12 | 25 | factible (18/18) | 2,8e-7 … 5,0e-6 |
| (2, 89) | NET | 18 | `INFEASIBLE` | primal infeasible | 6,60e-6 / 6,50e-7 | 100 | factible (18/18) | 3,8e-6 … 6,9e-5 |
| (3, 67) | NET | 3 | `NUMERICAL_ERROR` | primal infeasible inaccurate | 6,43e-7 / 6,35e-9 | 250 000 | factible (3/3) | 1,6e-5 … 4,8e-5 |
| (2, 159) | NET | 1 | `MAX_ITERATIONS` | maximum iterations reached | 6,52e-10 / 4,37e-11 | 250 000 | factible (1/1) | 1,2e-4 |
| (2, 19) | NET | 1 | `OPTIMAL_INACCURATE` | solved inaccurate | 1,96e-9 / 1,23e-11 | 250 000 | factible (1/1) | 2,6e-4 |

(250 000 = 50 000 iteraciones + reintento en frío de 200 000.) `GROSS`/`POST_COST_GROSS` de (2,89), (3,67), (2,159) y
(2,19) y `NET` de (2,84), (2,184), (2,193) no tienen puntos inválidos. Los datos de entrada completos (`μ`, `Σ`, `w0`,
costes, restricciones, tolerancias, retorno objetivo, solución tras la remediación y resultado del validador) están
en el **Apéndice A**.

El barrido determinista de la remediación (mismo generador, `n = 2…5`, semillas 0-1399) halló **10 instancias
adicionales** con el mismo defecto (11 con estado `INFEASIBLE` en total con las conocidas; 3 `OPTIMAL_INACCURATE`,
1 `MAX_ITERATIONS`, 1 `NUMERICAL_ERROR` y 1 mixta): `(2,329)`, `(2,627)`, `(2,655)`, `(2,845)`, `(2,1342)` en `GROSS` y
`(2,685)`, `(2,878)`, `(2,1115)`, `(2,1192)`, `(2,1229)` en `NET`. Se incorporaron como tests
(`SWEEP_INSTANCES`). Entre ambos grupos: 17 fronteras con puntos inválidos y 212 puntos inválidos de 224 000 (0,095 %).

---

## 4. Oráculo independiente

Se distinguen cinco categorías; ninguna clasificación usa OSQP como única fuente:

| Categoría | Cómo se decide | Casos F-3 |
|---|---|---|
| A. Verdaderamente infactible | LP de HiGHS con las mismas filas: `INFEASIBLE` | **Ninguno** (77/77 puntos de las 7 instancias son factibles; el mayor objetivo de cada malla es < máximo alcanzable) |
| B. Factible declarado numéricamente infactible | oráculo `FEASIBLE` y OSQP `primal infeasible` | (2,84), (2,184), (2,193) GROSS; (2,89) NET; y 7 del barrido |
| C. Factible que no converge | oráculo `FEASIBLE` y `MAX_ITERATIONS` / `primal infeasible inaccurate` | (3,67) NET (`NUMERICAL_ERROR`), (2,159) NET (`MAX_ITERATIONS`) |
| D. Aproximada que incumple tolerancias | `solved inaccurate` con `accept_inaccurate_solutions = false` | (2,19) NET (el validador la halla válida, exceso 1,2e-9, pero no se acepta) |
| E. Válida y suficientemente precisa | `OPTIMAL` y `SolutionValidator` válido | el resto de puntos y todos los recuperados |

Instrumentos (todos sin OSQP): `optimizers/feasibility_oracle.py::lp_feasibility` (LP de factibilidad con HiGHS,
mismas filas económicas); en los tests, `tests/fixtures/near_degenerate.py`: `lp_max_return` (LP de HiGHS del retorno
máximo, bruto y neto con costes), `two_asset_reference` (solución **analítica exacta** para dos activos, por regiones
de compra/venta y argmin cuadrático recortado) y `orthant_reference` (SLSQP por región lineal de compra/venta,
cualquier `n`). El oráculo LP se valida a sí mismo (`test_the_lp_oracle_separates_feasible_from_infeasible_targets`,
`..._is_inconclusive_when_highs_reaches_a_limit`).

---

## 5. Diagnóstico de causa raíz

Experimentos sobre los **77 puntos inválidos** de las siete instancias (workspace nuevo por punto; los mismos fallos
que en la frontera, de modo que **no** son contaminación por arranque en caliente ni reutilización de workspace):

| Experimento | Resultado (puntos `solved` de 77) | Conclusión |
|---|---|---|
| Ajustes de OSQP por sí solos: `rho ∈ {1e-3, 1e-2, 1, 10}`, `scaling ∈ {0, 50}`, `sigma = 1e-8`, `alpha = 1`, sin `adaptive_rho`, `polish_refine_iter = 10` | 0 (`rho = 1`: 2; sin `adaptive_rho` con `rho = 1`: 1) | La configuración del solver **no** explica el defecto |
| `eps_prim_inf = eps_dual_inf ∈ {1e-8, 1e-10}` | 0: todos pasan a `MAX_ITERATIONS` (50 000 it.) | El certificado `primal infeasible` es espurio (umbral 1e-4 frente a márgenes de 1e-7…1e-5), pero **además** el problema no converge |
| Centrar la fila de retorno con la de presupuesto (sin escalar) | NET (2,19), (3,67), (2,159): 5/5 `solved`; GROSS y NET (2,89): 0 | La casi-paralelismo con `Σw = 1` es una causa (familia NET con μ dispersos también) |
| Centrar y escalar (máx. coef. de peso = 1) | GROSS (84, 184, 193): 54/54; NET (2,89): 8 `solved` + 10 `solved inaccurate` | Escalar tras centrar resuelve la familia de retornos casi idénticos |
| Centrar y escalar con máx. coef. = 1 / **10** / 100 / 1000 | 67 / **77** / 61 / 69 | La escala importa; 10 resuelve los 77 con el presupuesto de 50 000 it. |
| Presupuesto de iteraciones: (2,685) y (2,878) NET (barrido), escala 10 | `MAX_ITERATIONS` a 50 000; `solved` a 115 875 y 118 500 it. | Con `max_iterations × retry_iteration_multiplier` (200 000) convergen |

Causa raíz por familia (todas comparten el mismo mecanismo: ADMM sobre una fila de retorno mal condicionada):

* **Familia A — retornos casi idénticos (GROSS):** (2,84), (2,184), (2,193) y las cinco del barrido (dispersión de
  retornos 3,6e-6…1,5e-4 frente a un nivel de 0,03-0,08). La fila `μᵀw ≥ R` es casi paralela a `Σw = 1` (en (2,84) la
  fila normalizada es `[1, 1,00006]`) y toda la información útil está en 1e-6…1e-4. OSQP declara inviabilidad primal
  aunque el margen objetivo↔máximo sea 1e-7…2e-5; el certificado desaparece al endurecer `eps_prim_inf` (los puntos
  pasan a `MAX_ITERATIONS`), lo que sitúa el umbral por defecto (1e-4) como detonante y la falta de convergencia como
  causa de fondo.
* **Familia B — franja neta delgada (NET):** (2,89), (3,67), (2,159), (2,19) y las del barrido. La dispersión de
  retornos es normal (0,012-0,031) pero los costes de compra/venta casi anulan la pendiente efectiva del retorno neto
  (en (2,89): `μ₁ − μ₂ − c_b₁ − c_s₂ ≈ 2e-4` frente a coeficientes de ~1e-2), de modo que el rango de retornos netos de
  la malla es solo 6,9e-5 y la región `retorno neto ≥ R` es una franja estrecha alrededor del vértice de máximo
  retorno. El mismo mal condicionamiento se manifiesta como **cuatro estados distintos** según el punto:
  `INFEASIBLE`, `NUMERICAL_ERROR`, `MAX_ITERATIONS` y `OPTIMAL_INACCURATE` (este último, convergencia en el suelo de
  `eps = 1e-9`).

**Descartado como causa:** condición de `Σ` (`cond(Σ) = 1,6…2,9`; los casos no son singulares), tolerancias
solicitadas (solo (2,19) está en el suelo `1e-9`), arranque en caliente y reutilización de workspace (fallos idénticos
con workspace nuevo), diferencias GROSS/NET en la formulación (los dos tratamientos usan el mismo QP con filas
distintas; el defecto aparece en ambos según la geometría), retornos exactamente iguales (frontera degenerada
documentada, sin fallo). No se aplicó ninguna solución global antes de identificar la causa.

---

## 6. Estrategia aplicada y cambios

### 6.1 Diseño (`ARCHITECTURE.md` §3.5, decisiones F3-01…F3-08)

```text
_run_variance(q, lower, target)                       # frontiers/session.py
  result = solve_with_policy(...)                     # camino normal, sin cambios
  si target y result.status ≠ OPTIMAL (y recuperación activa):
      NumericalRecovery.recover(...)                  # frontiers/numerical_recovery.py
        1. INFEASIBLE / NUMERICAL_ERROR / UNKNOWN → lp_feasibility (HiGHS, mismas filas)
             INFEASIBLE → CONFIRMED_INFEASIBLE: no se reintenta nada; estado del solver confirmado
        2. para cada escala de recovery_row_scales (una resolución por escala,
           max_iterations × retry_iteration_multiplier iteraciones, workspace nuevo):
             problema con la fila de retorno normalizada  (BuiltProblem.normalize_return_row)
             aceptar solo si OPTIMAL y SolutionValidator(objetivo original) válido → RECOVERED
        3. sin recuperación: NOT_RECOVERED; INFEASIBLE con LP factible → NUMERICAL_ERROR
```

* **Normalización reversible y exacta.** Con `e` la fila de presupuesto (`eᵀx = presupuesto`, igualdad) y `r` la fila
  de retorno: `r' = s·(r − λe)`, `cota' = s·(cota − λ·presupuesto)`, `λ = rᵀe/eᵀe`, `s = escala/máx|r_w − λe_w|`.
  Es el mismo conjunto factible (`r'x − cota' = s·(rx − cota)` para todo `x` con `eᵀx = presupuesto`), mismas
  variables (los pesos se usan sin deshacer nada), mismo objetivo y demás filas. Retornos idénticos → no hay nada que
  escalar (`None`). Verificado con `test_the_normalized_row_is_an_exact_rescaling_of_the_original_constraint`.
* **El objetivo solicitado no se modifica:** `FrontierPoint.target_return` es el original; el validador comprueba el
  retorno objetivo original con `constraint_tolerance` (no relajada).
* **El validador es el criterio de aceptación de cada reintento.** Hallazgo durante el desarrollo: con una escala
  inservible OSQP declara `OPTIMAL` sobre la fila reescalada y devuelve un punto que **viola** el objetivo original
  (`test_a_retry_that_the_solver_calls_optimal_but_the_validator_rejects_is_not_accepted`); el punto se rechaza, se
  registra (`RecoveryAttempt.rejected_by_validator`) y se prueba la siguiente escala.
* **Estados.** `OPTIMAL_INACCURATE` nunca se promueve. Un `INFEASIBLE` de OSQP que el LP halla factible y que nada
  recupera se reclasifica a `NUMERICAL_ERROR` (`SOL-002`: un fallo numérico no se presenta como inviabilidad
  matemática); un `INFEASIBLE` confirmado por el LP conserva `status_source = SOLVER`. Un punto recuperado tiene
  `status_source = CROSS_CHECK`.
* **Sin bucles ni cálculo inútil:** como máximo un LP y `len(recovery_row_scales)` QP por punto; los puntos
  verdaderamente infactibles terminan tras el LP; los puntos `OPTIMAL` no entran en la recuperación.
* **Trazabilidad:** `SolveResult.recovery = RecoveryTrace(estado y estado nativo del solver inicial, veredicto del LP,
  todos los intentos con solver, estado, iteraciones, residuales primal/dual, escala y rechazo del validador,
  resultado)`; iteraciones y tiempos del resultado suman los de todos los intentos.
* **Configuración** (sin literales en el código): `solver.numerical_recovery = true` y `solver.recovery_row_scales =
  [10.0, 1.0, 100.0]` en `config/default_engine.toml` (valores de ejemplo, justificados por la tabla de §5: 10 resuelve
  los 77 puntos). Las escalas 1 y 100 son una protección: **ninguno de los 212 puntos recuperados del barrido las
  necesitó** (todos se recuperaron con un único intento, escala 10); se ejercitan solo con tests sintéticos
  (rechazo por el validador, agotamiento). Ninguna tolerancia se toca.
* **Sin dependencia nueva:** HiGHS y OSQP ya eran dependencias; no se implementó ningún solver propio.

### 6.2 Ficheros

Modificados: `portfolio_engine/config/solver_config.py`, `config/default_engine.toml`,
`portfolio_engine/frontiers/session.py`, `portfolio_engine/models/enums.py` (`RecoveryOutcome`),
`portfolio_engine/models/solution.py` (`RecoveryAttempt`, `RecoveryTrace`, `SolveResult.recovery`),
`portfolio_engine/optimizers/__init__.py`, `portfolio_engine/optimizers/formulations/__init__.py`,
`portfolio_engine/optimizers/formulations/qp_builder.py` (`NormalizedReturnProblem`,
`BuiltProblem.normalize_return_row`), `tests/unit/frontiers/test_known_solver_status_cases.py` (solo el docstring: nota
de remediación; la lógica no cambia), `ARCHITECTURE.md`, `TRACEABILITY.md`, `CHANGELOG.md`.

Creados: `portfolio_engine/frontiers/numerical_recovery.py`, `portfolio_engine/optimizers/feasibility_oracle.py`,
`tests/fixtures/near_degenerate.py`, `tests/unit/frontiers/test_numerical_recovery.py`,
`tests/unit/optimizers/test_return_row_normalization.py`, `tests/unit/config/test_solver_recovery_config.py`,
`REMEDIATION_F3_NUMERICAL.md`.

Sin cambios: backends (`osqp_backend.py`, `highs_backend.py`), `router.py`, `status.py`, `SolutionValidator`,
`ConstraintCompiler`, `TransactionCostModel`, `CandidateEngine`, `global_frontier.py`, `pareto.py`, `outputs/`.

---

## 7. Tests añadidos (109, todos deterministas)

* `tests/unit/frontiers/test_numerical_recovery.py`: las 7 instancias × GROSS/NET/POST_COST_GROSS y las 10 del barrido
  con **todos** los puntos `OPTIMAL` y válidos; optimalidad de cada punto interior frente a la referencia exacta
  (analítica para `n = 2`, SLSQP por regiones para `n = 3` NET, tolerancia de varianza 1e-6); ningún objetivo de la
  malla verdaderamente infactible (LP); POST_COST_GROSS hereda los pesos recuperados; traza completa de un punto
  recuperado (por qué, solver inicial y final, ambos intentos, iteraciones, `y` no expuesto); reproducibilidad bit a
  bit; estados originales reproducidos con `numerical_recovery = false` (`INFEASIBLE`, `NUMERICAL_ERROR`,
  `MAX_ITERATIONS`, `OPTIMAL_INACCURATE`); un objetivo por encima del máximo sigue siendo `INFEASIBLE`, confirmado por
  el LP y sin reintentos; objetivos a 1e-6/1e-7 del máximo se resuelven; un reintento `OPTIMAL` rechazado por el
  validador no se acepta y reclasifica a `NUMERICAL_ERROR`; con pocas iteraciones ningún reintento se promueve y no hay
  más intentos que escalas; la malla de `theta` queda fuera de la recuperación; fronteras sanas **idénticas bit a bit**
  con y sin recuperación; retornos casi idénticos (`n = 2, 3, 4`, dispersión 1e-6…1e-8), `Σ` singular y casi singular
  (rango 1, jitter 0 / 1e-10 / 1e-8) y retornos exactamente iguales (frontera degenerada).
* `tests/unit/optimizers/test_return_row_normalization.py`: equivalencia exacta de la fila normalizada, escala pedida,
  fila centrada, retornos idénticos → `None`, oráculo LP (factible/infactible/inconcluso por límites) y no
  modificación del problema.
* `tests/unit/config/test_solver_recovery_config.py`: valores por defecto, validación y desactivación.
* `tests/fixtures/near_degenerate.py`: instancias y referencias independientes (no usan el motor).

Los tests históricos `test_known_solver_status_cases.py` (9) y `test_known_inaccurate_point.py` (2) se conservan sin
cambios de lógica y siguen pasando.

---

## 8. Tabla comparativa antes / después (instancias contractuales)

«Antes» = `numerical_recovery = false` (idéntico al baseline). Puntos válidos de la frontera (`TARGET_RETURN_GRID`,
20 puntos), iteraciones totales de OSQP de la frontera (recuperación incluida) y tiempo (mínimo de 3 ejecuciones).

| Instancia | Tratamiento | Válidos antes → después | Estados no óptimos antes → después | Iteraciones antes → después | Tiempo (s) antes → después |
|---|---|---|---|---|---|
| (2, 84) | GROSS | 2 → 20 de 20 | INFEASIBLE ×18 → — | 1 200 → 2 550 | 0,018 → 0,194 |
| (2, 84) | NET | 20 → 20 de 20 | — → — | 4 775 → 4 775 | 0,029 → 0,029 |
| (2, 84) | POST_COST_GROSS | 2 → 20 de 20 | INFEASIBLE ×18 → — | 1 200 → 2 550 | 0,020 → 0,204 |
| (2, 184) | GROSS | 2 → 20 de 20 | INFEASIBLE ×18 → — | 1 175 → 2 425 | 0,020 → 0,202 |
| (2, 184) | NET | 20 → 20 de 20 | — → — | 3 125 → 3 125 | 0,025 → 0,026 |
| (2, 184) | POST_COST_GROSS | 2 → 20 de 20 | INFEASIBLE ×18 → — | 1 175 → 2 425 | 0,018 → 0,190 |
| (2, 193) | GROSS | 2 → 20 de 20 | INFEASIBLE ×18 → — | 1 250 → 2 600 | 0,019 → 0,183 |
| (2, 193) | NET | 20 → 20 de 20 | — → — | 2 175 → 2 175 | 0,025 → 0,029 |
| (2, 193) | POST_COST_GROSS | 2 → 20 de 20 | INFEASIBLE ×18 → — | 1 250 → 2 600 | 0,017 → 0,177 |
| (2, 89) | GROSS | 20 → 20 de 20 | — → — | 8 350 → 8 350 | 0,025 → 0,025 |
| (2, 89) | NET | 2 → 20 de 20 | INFEASIBLE ×18 → — | 502 025 → 1 121 675 | 0,242 → 0,667 |
| (2, 89) | POST_COST_GROSS | 20 → 20 de 20 | — → — | 8 350 → 8 350 | 0,027 → 0,029 |
| (3, 67) | GROSS | 20 → 20 de 20 | — → — | 9 650 → 9 650 | 0,024 → 0,029 |
| (3, 67) | NET | 17 → 20 de 20 | NUMERICAL_ERROR ×3 → — | 994 025 → 1 045 475 | 0,487 → 0,584 |
| (3, 67) | POST_COST_GROSS | 20 → 20 de 20 | — → — | 9 650 → 9 650 | 0,031 → 0,029 |
| (2, 159) | GROSS | 20 → 20 de 20 | — → — | 16 650 → 16 650 | 0,028 → 0,030 |
| (2, 159) | NET | 19 → 20 de 20 | MAX_ITERATIONS ×1 → — | 904 725 → 913 075 | 0,396 → 0,403 |
| (2, 159) | POST_COST_GROSS | 20 → 20 de 20 | — → — | 16 650 → 16 650 | 0,027 → 0,028 |
| (2, 19) | GROSS | 20 → 20 de 20 | — → — | 3 325 → 3 325 | 0,024 → 0,023 |
| (2, 19) | NET | 19 → 20 de 20 | OPTIMAL_INACCURATE ×1 → — | 2 680 225 → 2 694 825 | 1,102 → 1,081 |
| (2, 19) | POST_COST_GROSS | 20 → 20 de 20 | — → — | 3 325 → 3 325 | 0,026 → 0,023 |

Los tratamientos sin defecto conservan exactamente las mismas iteraciones (la recuperación no interviene). El
intento de recuperación resuelve en hasta 125 iteraciones (familia A) o hasta 47 450 (familia B) sobre la fila
normalizada; en las 17 fronteras defectuosas, **los 212 puntos** se recuperaron con **un único intento** (escala 10)
tras el LP de factibilidad. Optimalidad frente a las referencias independientes en los puntos
interiores de las fronteras recuperadas: error de varianza máximo 3,5e-17 (GROSS, `n = 2`, exacto), 5,3e-15 (NET
(2,89)), 8,4e-10 (NET (3,67)), 8,9e-10 (NET (2,19)) y 1,3e-7 (NET (2,159), dentro de la tolerancia de restricción del
validador 1e-7 en retorno).

---

## 9. No regresión B1 / B2 / B3

* **Suite completa:** `pytest -q` → **1148 passed** (1039 del baseline + 109 nuevos), 0 failed, 0 skipped, 131,78 s.
  Incluye las suites de B1 (config, datos, retornos, covarianza, costes), B2 (restricciones, factibilidad, backends,
  fronteras, validador, benchmark, propiedades) y B3 (candidatos, frontera global, E-09/E-10/E-11).
* **Huella comparada con `block3-validated`** (árbol extraído con `git archive` y ejecutado con el mismo script):
  8 problemas × 3 tratamientos × 2 métodos de la frontera continua + la `GLOBAL_CANDIDATE_FRONTIER` (`two_region_problem`)
  × 3 tratamientos × 2 métodos = **54 configuraciones**; para cada punto: SHA-256 de los pesos, retornos bruto y neto,
  volatilidad, coste de transacción, turnover, banderas de eficiencia (por composición y globales), iteraciones y
  estado. **Diferencias: 0.** Costes de compra/venta, liquidación completa, turnover, E-09/E-10/E-11,
  `CandidateEngine`, Pareto global y `SolutionValidator` no se modifican.
* **Barrido de 11 200 fronteras:** las 11 183 sin defecto previo tienen el **mismo número de iteraciones** (diferencia
  máxima 0) antes y después; solo cambian las 17 defectuosas.
* **Diferencias numéricas observadas y documentadas:** (a) en los casos defectuosos, los puntos pasan de inválidos a
  válidos (el objetivo); (b) el `ConfigHash` cambia respecto a `block3-validated` porque el snapshot de configuración
  incorpora `solver.numerical_recovery` y `solver.recovery_row_scales` (mismo criterio que F-5); ningún resultado
  económico depende del hash; los tests de hash de configuración pasan.
* B1: solo se toca `SolverConfig` (dos campos con validación); el resto de módulos de B1 no cambia y sus tests pasan.

---

## 10. Rendimiento

Recuento de llamadas (fiable) y tiempo (orientativo: esta máquina tiene tiempos bimodales, memoria del proyecto):

| Medida (barrido de 11 200 fronteras) | Antes | Después |
|---|---|---|
| Iteraciones OSQP totales | 149 087 500 | 153 274 125 (**+2,8 %**) |
| Iteraciones en las 17 fronteras defectuosas | 18 992 425 | 23 179 050 |
| Tiempo acumulado (una ejecución por frontera) | 357,1 s | 363,5 s (+1,8 %, dentro del ruido) |
| Tiempo acumulado de las 17 fronteras defectuosas | 7,47 s | 11,97 s |

Coste por punto recuperado: un LP de HiGHS (≈ 10 ms; domina en las fronteras de `n = 2` con 18 puntos
`INFEASIBLE`: 0,02 s → ≈ 0,2 s) y, en la familia B, hasta ≈ 47 000 iteraciones de OSQP (≈ 0,02 s). La frontera más
cara del barrido (2,1115 NET) pasa de 1,8 s a 2,9 s. Las fronteras sin defecto no pagan nada. No se regeneró el
benchmark de B3 (pendiente ya registrada en `AUDIT_BLOCK_3_FINAL_CLOSURE.md`).

---

## 11. Limitaciones residuales, riesgos y pruebas pendientes

* **La escalera de escalas es empírica** (`[10, 1, 100]`): resuelve todos los casos conocidos y las 24 000
  fronteras de los barridos con un único intento (escala 10); los peldaños 1 y 100 no se han necesitado con datos
  reales y no hay garantía general de que otras geometrías no requieran más. Un punto que ninguna escala recupere queda **inválido y correctamente
  etiquetado** (`NUMERICAL_ERROR` si OSQP había declarado `INFEASIBLE` y el LP lo halla factible; el estado original
  en otro caso), nunca aceptado.
* **Convergencia lenta de ADMM:** algunas fronteras NET de `n = 2` necesitan más de 1 M de iteraciones acumuladas
  (≈ 1 s). Un método de punto interior o un segundo solver QP (Clarabel, previsto en el Bloque 4) sería la solución
  estructural; entonces conviene reevaluar el papel de esta escalera y del oráculo LP.
* **Alcance de la recuperación:** solo puntos con retorno objetivo. No cubre la malla de `theta`, MinVariance ni la
  etapa 2 de MaximumReturn (que usa su propia cara óptima, `R2-02`); el barrido de F-3 solo ejerció
  `TARGET_RETURN_GRID` (el test de propiedades ejerce `RISK_AVERSION_GRID` con ejemplos aleatorios y no mostró fallos).
* **Tolerancia del oráculo:** el LP usa `lp_feasibility_tolerance = 1e-9`; un objetivo por encima del máximo en menos de
  1e-9 puede considerarse factible y terminar como `NUMERICAL_ERROR` inválido en lugar de `INFEASIBLE`. Sin efecto en
  los casos conocidos (márgenes ≥ 1,3e-7).
* **Tolerancia de validación absoluta:** `constraint_tolerance = 1e-7` en retorno no es discriminante cuando la
  dispersión de retornos es ≲ 1e-7; en los casos probados las soluciones recuperadas cumplen el objetivo con holgura
  ≤ 1e-16 y coinciden con la referencia exacta, pero el contrato del validador no lo garantiza para dispersiones
  menores (no se relajó ni se endureció).
* **Pruebas pendientes (no ejecutadas):** barridos con `n > 5`, con límites de grupo, turnover máximo y
  `MinWeight`/`min_holding_weight`, con composiciones que excluyen activos actuales (fila de retorno NET con
  `return_offset`) y con la frontera adaptativa; el mecanismo (`normalize_return_row`) es exacto para cualquier fila
  y solo se verificó numéricamente sobre problemas de presupuesto y cotas; `RISK_AVERSION_GRID` con barrido masivo;
  evaluación de rendimiento con el benchmark del proyecto.
* **Riesgo:** el `SolverConfig` gana dos campos obligatorios: cualquier TOML propio debe declararlos (`ConfigError`
  si faltan, como el resto de la sección).

---

## 12. Validación final

```text
pytest -q                     →  1148 passed in 131.78s (0 failed, 0 skipped)
mypy --strict portfolio_engine →  Success: no issues found in 126 source files
ruff check .                  →  All checks passed!
ruff format --check .         →  259 files already formatted
```

Reproducción de los casos F-3 tras la remediación (`REMEDIATION_F3_NUMERICAL.md` §8 y Apéndice A): 0 puntos
inválidos en las 7 instancias contractuales (21 combinaciones instancia × tratamiento) y en las 10 del barrido;
puntos recuperados óptimos frente a referencias independientes; certificado de inviabilidad verdadero (objetivo
por encima del máximo) confirmado y conservado. La incidencia mejora de forma real y sostenida por evidencia
independiente (LP de HiGHS, soluciones analíticas y SLSQP por regiones), no solo por el resultado de `pytest`.
Evidencia complementaria (no sustituye a los barridos deterministas): seis ejecuciones de
`tests/property/test_invariants.py` con `--hypothesis-seed` 1…6, `2 passed` en todas.

---

## Apéndice A — Datos completos de las siete instancias

Las tablas de §3 y §8 resumen; aquí consta, por instancia, la entrada completa, las restricciones, las tolerancias, el
primer punto inválido original (estado, residuales, iteraciones) y la solución tras la remediación con el resultado
del validador independiente. Generado con el motor real (`numerical_recovery = false` para «antes»).

### (2, 84)

- **Entrada** (`np.random.default_rng(84)`, generador de `tests/property/test_invariants.py::frontier_problems`): `μ = [0.05677079088, 0.05677436384]`; `Σ = [[0.06468787, 0.03286406],  [0.03286406, 0.10288222]]`; pesos actuales `w0 = [0.7686434774, 0.2313565226]`; costes de compra/venta (bps) `[77.30813647, 83.74696234]` / `[62.19273952, 71.51611772]`; `cond(Σ) = 2.66`; dispersión de retornos `max μ − min μ = 3.57e-06`.
- **Restricciones**: `Σw = 1`, `long_only`, `0 ≤ w ≤ 1` (`MaxWeight = 1`), sin límites de grupo, turnover ni liquidez; composición = los 2 activos actuales (sin activos que salgan); horizonte `H = 1.0` año.
- **Tolerancias solicitadas**: OSQP `eps_abs = 1e-09`, `eps_rel = 1e-09`, `max_iterations = 50000` (reintento en frío ×4), `eps_prim_inf`/`eps_dual_inf` = valores por defecto de OSQP (1e-4), pulido activo; validador `constraint_tolerance = 1e-07`, `bound_tolerance = 1e-07`, `budget_tolerance = 1e-07`.
- **GROSS** (idéntico en `POST_COST_GROSS`, que hereda sus pesos) — 18 puntos inválidos de 20. Primer punto inválido: retorno objetivo `0.0567720366549`; OSQP: estado `INFEASIBLE` (nativo «primal infeasible»), 25 iteraciones, residual primal `1.29e-07`, residual dual `2.34e-13`; sin solución (`x` no expuesto).
  Tras la remediación: `OPTIMAL`, válido = `True`, `w = [0.6513325705, 0.3486674295]`, retorno bruto de los pesos `0.0567720366549` (≥ objetivo), validador independiente: `is_valid = True`, `max_violation = 1.11e-16`; traza: `RECOVERED`, intentos [('ORIGINAL', 'INFEASIBLE', 25), ('LP_FEASIBILITY_ORACLE', 'OPTIMAL', 0), ('NORMALIZED_RETURN_ROW', 'OPTIMAL', 50)].

### (2, 184)

- **Entrada** (`np.random.default_rng(184)`, generador de `tests/property/test_invariants.py::frontier_problems`): `μ = [0.07089770361, 0.07097186704]`; `Σ = [[ 0.05571917, -0.00359168],  [-0.00359168,  0.02046572]]`; pesos actuales `w0 = [0.273372412, 0.726627588]`; costes de compra/venta (bps) `[131.9719919, 124.8538578]` / `[2.864487053, 40.93459825]`; `cond(Σ) = 2.79`; dispersión de retornos `max μ − min μ = 7.42e-05`.
- **Restricciones**: `Σw = 1`, `long_only`, `0 ≤ w ≤ 1` (`MaxWeight = 1`), sin límites de grupo, turnover ni liquidez; composición = los 2 activos actuales (sin activos que salgan); horizonte `H = 1.0` año.
- **Tolerancias solicitadas**: OSQP `eps_abs = 1e-09`, `eps_rel = 1e-09`, `max_iterations = 50000` (reintento en frío ×4), `eps_prim_inf`/`eps_dual_inf` = valores por defecto de OSQP (1e-4), pulido activo; validador `constraint_tolerance = 1e-07`, `bound_tolerance = 1e-07`, `budget_tolerance = 1e-07`.
- **GROSS** (idéntico en `POST_COST_GROSS`, que hereda sus pesos) — 18 puntos inválidos de 20. Primer punto inválido: retorno objetivo `0.0709515922378`; OSQP: estado `INFEASIBLE` (nativo «primal infeasible»), 25 iteraciones, residual primal `1.13e-06`, residual dual `6.59e-12`; sin solución (`x` no expuesto).
  Tras la remediación: `OPTIMAL`, válido = `True`, `w = [0.2733800734, 0.7266199266]`, retorno bruto de los pesos `0.0709515922378` (≥ objetivo), validador independiente: `is_valid = True`, `max_violation = 0`; traza: `RECOVERED`, intentos [('ORIGINAL', 'INFEASIBLE', 25), ('LP_FEASIBILITY_ORACLE', 'OPTIMAL', 0), ('NORMALIZED_RETURN_ROW', 'OPTIMAL', 75)].

### (2, 193)

- **Entrada** (`np.random.default_rng(193)`, generador de `tests/property/test_invariants.py::frontier_problems`): `μ = [0.08284899344, 0.0828292457]`; `Σ = [[ 0.01278857, -0.00080159],  [-0.00080159,  0.03641868]]`; pesos actuales `w0 = [0.4359495087, 0.5640504913]`; costes de compra/venta (bps) `[177.6941082, 150.2682569]` / `[29.72486472, 115.3521455]`; `cond(Σ) = 2.86`; dispersión de retornos `max μ − min μ = 1.97e-05`.
- **Restricciones**: `Σw = 1`, `long_only`, `0 ≤ w ≤ 1` (`MaxWeight = 1`), sin límites de grupo, turnover ni liquidez; composición = los 2 activos actuales (sin activos que salgan); horizonte `H = 1.0` año.
- **Tolerancias solicitadas**: OSQP `eps_abs = 1e-09`, `eps_rel = 1e-09`, `max_iterations = 50000` (reintento en frío ×4), `eps_prim_inf`/`eps_dual_inf` = valores por defecto de OSQP (1e-4), pulido activo; validador `constraint_tolerance = 1e-07`, `bound_tolerance = 1e-07`, `budget_tolerance = 1e-07`.
- **GROSS** (idéntico en `POST_COST_GROSS`, que hereda sus pesos) — 18 puntos inválidos de 20. Primer punto inválido: retorno objetivo `0.082843989548`; OSQP: estado `INFEASIBLE` (nativo «primal infeasible»), 25 iteraciones, residual primal `2.78e-07`, residual dual `2.58e-12`; sin solución (`x` no expuesto).
  Tras la remediación: `OPTIMAL`, válido = `True`, `w = [0.7466093688, 0.2533906312]`, retorno bruto de los pesos `0.082843989548` (≥ objetivo), validador independiente: `is_valid = True`, `max_violation = 1.11e-16`; traza: `RECOVERED`, intentos [('ORIGINAL', 'INFEASIBLE', 25), ('LP_FEASIBILITY_ORACLE', 'OPTIMAL', 0), ('NORMALIZED_RETURN_ROW', 'OPTIMAL', 75)].

### (2, 89)

- **Entrada** (`np.random.default_rng(89)`, generador de `tests/property/test_invariants.py::frontier_problems`): `μ = [0.121170518, 0.1059384138]`; `Σ = [[ 0.03497367, -0.00631973],  [-0.00631973,  0.05849135]]`; pesos actuales `w0 = [0.60247509, 0.39752491]`; costes de compra/venta (bps) `[99.46657044, 189.4535369]` / `[178.6131551, 50.98764545]`; `cond(Σ) = 1.8`; dispersión de retornos `max μ − min μ = 0.0152`.
- **Restricciones**: `Σw = 1`, `long_only`, `0 ≤ w ≤ 1` (`MaxWeight = 1`), sin límites de grupo, turnover ni liquidez; composición = los 2 activos actuales (sin activos que salgan); horizonte `H = 1.0` año.
- **Tolerancias solicitadas**: OSQP `eps_abs = 1e-09`, `eps_rel = 1e-09`, `max_iterations = 50000` (reintento en frío ×4), `eps_prim_inf`/`eps_dual_inf` = valores por defecto de OSQP (1e-4), pulido activo; validador `constraint_tolerance = 1e-07`, `bound_tolerance = 1e-07`, `budget_tolerance = 1e-07`.
- **NET** — 18 puntos inválidos de 20. Primer punto inválido: retorno objetivo `0.115120759407`; OSQP: estado `INFEASIBLE` (nativo «primal infeasible»), 100 iteraciones, residual primal `6.6e-06`, residual dual `6.5e-07`; sin solución (`x` no expuesto).
  Tras la remediación: `OPTIMAL`, válido = `True`, `w = [0.6313062031, 0.3686937969]`, retorno neto de los pesos `0.115120759407` (≥ objetivo), validador independiente: `is_valid = True`, `max_violation = 3.33e-16`; traza: `RECOVERED`, intentos [('ORIGINAL', 'INFEASIBLE', 100), ('LP_FEASIBILITY_ORACLE', 'OPTIMAL', 3), ('NORMALIZED_RETURN_ROW', 'OPTIMAL', 27500)].

### (3, 67)

- **Entrada** (`np.random.default_rng(67)`, generador de `tests/property/test_invariants.py::frontier_problems`): `μ = [0.1262424966, 0.1309439927, 0.1458974959]`; `Σ = [[ 0.04990717,  0.00148764, -0.00158432],  [ 0.00148764,  0.0480441 , -0.00191921],  [-0.00158432, -0.00191921,  0.02959804]]`; pesos actuales `w0 = [0.4844332009, 0.245594001, 0.2699727981]`; costes de compra/venta (bps) `[46.34308081, 67.8890128, 142.0370098]` / `[58.09810814, 61.66595549, 127.5421633]`; `cond(Σ) = 1.74`; dispersión de retornos `max μ − min μ = 0.0197`.
- **Restricciones**: `Σw = 1`, `long_only`, `0 ≤ w ≤ 1` (`MaxWeight = 1`), sin límites de grupo, turnover ni liquidez; composición = los 3 activos actuales (sin activos que salgan); horizonte `H = 1.0` año.
- **Tolerancias solicitadas**: OSQP `eps_abs = 1e-09`, `eps_rel = 1e-09`, `max_iterations = 50000` (reintento en frío ×4), `eps_prim_inf`/`eps_dual_inf` = valores por defecto de OSQP (1e-4), pulido activo; validador `constraint_tolerance = 1e-07`, `bound_tolerance = 1e-07`, `budget_tolerance = 1e-07`.
- **NET** — 3 puntos inválidos de 20. Primer punto inválido: retorno objetivo `0.132655093249`; OSQP: estado `NUMERICAL_ERROR` (nativo «primal infeasible inaccurate»), 250000 iteraciones, residual primal `6.43e-07`, residual dual `6.35e-09`; sin solución (`x` no expuesto).
  Tras la remediación: `OPTIMAL`, válido = `True`, `w = [0.3494930176, 0.245594001, 0.4049129814]`, retorno neto de los pesos `0.132655093249` (≥ objetivo), validador independiente: `is_valid = True`, `max_violation = 0`; traza: `RECOVERED`, intentos [('ORIGINAL', 'NUMERICAL_ERROR', 250000), ('LP_FEASIBILITY_ORACLE', 'OPTIMAL', 8), ('NORMALIZED_RETURN_ROW', 'OPTIMAL', 15500)].

### (2, 159)

- **Entrada** (`np.random.default_rng(159)`, generador de `tests/property/test_invariants.py::frontier_problems`): `μ = [0.1499780928, 0.1382046187]`; `Σ = [[ 0.06838752, -0.00201827],  [-0.00201827,  0.03208717]]`; pesos actuales `w0 = [0.3545109062, 0.6454890938]`; costes de compra/venta (bps) `[20.96114596, 18.06194387]` / `[33.0281736, 92.01709035]`; `cond(Σ) = 2.14`; dispersión de retornos `max μ − min μ = 0.0118`.
- **Restricciones**: `Σw = 1`, `long_only`, `0 ≤ w ≤ 1` (`MaxWeight = 1`), sin límites de grupo, turnover ni liquidez; composición = los 2 activos actuales (sin activos que salgan); horizonte `H = 1.0` año.
- **Tolerancias solicitadas**: OSQP `eps_abs = 1e-09`, `eps_rel = 1e-09`, `max_iterations = 50000` (reintento en frío ×4), `eps_prim_inf`/`eps_dual_inf` = valores por defecto de OSQP (1e-4), pulido activo; validador `constraint_tolerance = 1e-07`, `bound_tolerance = 1e-07`, `budget_tolerance = 1e-07`.
- **NET** — 1 puntos inválidos de 20. Primer punto inválido: retorno objetivo `0.142561879685`; OSQP: estado `MAX_ITERATIONS` (nativo «maximum iterations reached»), 250000 iteraciones, residual primal `6.52e-10`, residual dual `4.37e-11`; sin solución (`x` no expuesto).
  Tras la remediación: `OPTIMAL`, válido = `True`, `w = [0.7401639036, 0.2598360964]`, retorno neto de los pesos `0.142561879685` (≥ objetivo), validador independiente: `is_valid = True`, `max_violation = 0`; traza: `RECOVERED`, intentos [('ORIGINAL', 'MAX_ITERATIONS', 250000), ('NORMALIZED_RETURN_ROW', 'OPTIMAL', 8350)].

### (2, 19)

- **Entrada** (`np.random.default_rng(19)`, generador de `tests/property/test_invariants.py::frontier_problems`): `μ = [0.1215255256, 0.09003097869]`; `Σ = [[ 0.03367285, -0.00768381],  [-0.00768381,  0.04427805]]`; pesos actuales `w0 = [0.2732340243, 0.7267659757]`; costes de compra/venta (bps) `[185.6870268, 87.86767417]` / `[82.52882788, 123.0357999]`; `cond(Σ) = 1.63`; dispersión de retornos `max μ − min μ = 0.0315`.
- **Restricciones**: `Σw = 1`, `long_only`, `0 ≤ w ≤ 1` (`MaxWeight = 1`), sin límites de grupo, turnover ni liquidez; composición = los 2 activos actuales (sin activos que salgan); horizonte `H = 1.0` año.
- **Tolerancias solicitadas**: OSQP `eps_abs = 1e-09`, `eps_rel = 1e-09`, `max_iterations = 50000` (reintento en frío ×4), `eps_prim_inf`/`eps_dual_inf` = valores por defecto de OSQP (1e-4), pulido activo; validador `constraint_tolerance = 1e-07`, `bound_tolerance = 1e-07`, `budget_tolerance = 1e-07`.
- **NET** — 1 puntos inválidos de 20. Primer punto inválido: retorno objetivo `0.0988273419267`; OSQP: estado `OPTIMAL_INACCURATE` (nativo «solved inaccurate»), 250000 iteraciones, residual primal `1.96e-09`, residual dual `1.23e-11`; sin solución (`x` no expuesto).
  Tras la remediación: `OPTIMAL`, válido = `True`, `w = [0.5801477327, 0.4198522673]`, retorno neto de los pesos `0.0988273419267` (≥ objetivo), validador independiente: `is_valid = True`, `max_violation = 0`; traza: `RECOVERED`, intentos [('ORIGINAL', 'OPTIMAL_INACCURATE', 250000), ('NORMALIZED_RETURN_ROW', 'OPTIMAL', 14600)].



---

## Nota posterior al merge del PR #3 (2026-09-25)

> Nota añadida después del merge; **no modifica la evidencia histórica anterior**. Detalle en
> `F3_POST_MERGE_REVIEW.md` (rama `fix/f3-oracle-iteration-accounting`).

La revisión de GitHub posterior al merge señaló dos defectos P2, ambos reproducidos:

* **P2-01** — `normalize_return_row` calculaba la escala solo sobre `centered[:n_weights]`. Con retornos
  idénticos en `NET` el bloque de pesos centrado es nulo pero la fila conserva `−c_b/H` y `−c_s/H`; el método
  devolvía `None` y la escalera de reintentos se abortaba con una restricción aún informativa. Corregido: si el
  bloque de pesos centrado es despreciable (`<= √eps` del máximo de toda la fila) la escala se calcula sobre
  toda la fila; en otro caso se conserva la escala de pesos calibrada en este informe (el cambio a «todos los
  coeficientes» sin condición empeoraba los puntos `NET` recuperados de las instancias contractuales, p. ej.
  (2, 685): 1,35 M → 3,83 M iteraciones).
* **P2-02** — `numerical_recovery._merge` excluía del total de iteraciones las del oráculo de HiGHS aunque su
  tiempo sí se sumaba a `solve_time`. Corregido: `SolveResult.iterations` suma todos los intentos; se añade el
  desglose `iterations_by_solver`. Las cifras de iteraciones de las tablas anteriores de este informe son las de
  entonces (sin oráculo) y no se reescriben.
