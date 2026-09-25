# F3_POST_MERGE_REVIEW

Revisión de dos hallazgos P2 de GitHub posteriores al merge del PR #3 (remediación F-3).
Rama `fix/f3-oracle-iteration-accounting`, baseline `main` (`b59e446`). Sin commit, merge, push, tag ni PR. No se avanza al Bloque 4.

## P2-01 — escalado de la fila NET

**P2-01 confirmed:** SÍ. Caso sintético NET: 2 activos, μ = [0.07, 0.07], costes asimétricos no nulos. Fila de retorno original `[0.07, 0.07, −1.28e-2, −5.5e-3, −9.2e-4, −4.3e-4]`; `normalize_return_row(10.0)` en `main` devolvía `None` (comprobado con script y con los tests nuevos ejecutados contra el `qp_builder.py` de `main`: 17 fallan).

**P2-01 root cause:** `largest = max|centered[:n_weights]|`. Con μ idénticos el centrado anula el bloque de pesos, pero la fila NET conserva `−c_b/H` y `−c_s/H` (la fila de presupuesto tiene ceros en b y s), de modo que la restricción seguía siendo informativa y aun así `largest = 0 → None` abortaba la escalera de reintentos.

**P2-01 correction:** `BuiltProblem.normalize_return_row` (`qp_builder.py`):
* fila nula (todos los coeficientes centrados `≤ dim·eps·max|r|`, ruido de redondeo) → `None`;
* bloque de pesos centrado `≤ √eps` del máximo de toda la fila → escala sobre **toda** la fila (pesos + variables de compra/venta);
* en otro caso se conserva la escala sobre los pesos.

Desviación consciente respecto a «escalar siempre sobre todos los coeficientes»: lo probé y **empeoraba** los puntos NET recuperados ya validados (p. ej. (2, 685) NET 1,35 M → 3,83 M iteraciones, un intento más; pesos hasta 2·10⁻⁸ distintos), porque en esas instancias los coeficientes auxiliares dominan a los de pesos y la escala calibrada en F-3 (máximo de pesos = 10) deja de aplicarse. La regla condicional deja todos los pesos idénticos a `main` (ver regresión). El umbral `√eps` y `dim·eps` son guardas estructurales de redondeo (sin literales de negocio; `test_no_business_numeric_literals` pasa), no tolerancias financieras. Tolerancias aprobadas, formulación económica, validador y estados no se tocan.

**Mathematical equivalence:** se mantiene `fila' = s·(fila − λ·e)`, `cota' = s·(cota − λ·presupuesto)`; test con 50 vectores aleatorios (variables auxiliares libres, `1ᵀw = 1`) para GROSS y NET con μ idénticos: `fila'·x − cota' = s·(fila·x − cota)`; las demás filas, `upper`, `P`, `q` idénticos. Oráculo independiente: `nd.lp_max_return` (linprog sobre variables originales) frente al LP de HiGHS sobre la fila original y sobre la transformada, con targets factibles (−1e-4, −1e-3) e infactible (+1e-6): coinciden. Recuperación forzada con `INFEASIBLE` inicial fingido: oráculo `FEASIBLE` → reintento `OPTIMAL` aceptado por el validador, varianza = referencia analítica de dos activos (1e-6); target infactible → `CONFIRMED_INFEASIBLE`.

## P2-02 — contabilización de iteraciones

**P2-02 confirmed:** SÍ. `_merge` sumaba `attempts` excluyendo `STRATEGY_ORACLE`, mientras `solve_time` sí incluía el oráculo (inconsistencia). `FrontierSession.total_iterations` y `FrontierDiagnostics.total_iterations` heredaban la omisión.

**Iteration accounting before/after:** contrato elegido: `SolveResult.iterations` = total de todos los solvers que intervinieron (original + oráculo + reintentos, cada intento una vez). Ejemplo determinista caso C: antes 35, ahora 39 (10 OSQP + 4 HiGHS + 25 OSQP). Efecto real en instancias contractuales/barrido: +24…+54 iteraciones **por frontera** con recuperación por oráculo (+2…+8 **por punto** recuperado, 71 puntos); total de +214 iteraciones sobre las 224 000 fronteras del barrido (las de los 212 puntos recuperados; sin oráculo, sin cambio).

**OSQP/HiGHS diagnostics:** nuevos `iterations_by_solver` en `RecoveryTrace`, `SolveResult`, `FrontierSession` y `FrontierDiagnostics` (tupla `(solver, iteraciones)` ordenada; suma = total). Campos existentes y sus firmas se conservan (campo nuevo con valor por defecto). Documentado: sumar ADMM (OSQP) y símplex/IPM (HiGHS) es una métrica agregada de actividad, no de esfuerzo homogéneo. Los tiempos no se usan como valores esperados.

## Resultados

**Contractual F-3 cases:** 7 instancias × GROSS/NET/POST_COST_GROSS (21 fronteras) + 10 del barrido, comparadas con `main`: estados y validez idénticos, **pesos idénticos bit a bit (diferencia máx. 0)**, mismos intentos; la única diferencia son las iteraciones del oráculo. Los 77 puntos contractuales siguen 0 inválidos.

**Regression B1/B2/B3:** barrido determinista n = 2…5, semillas 0-1399, GROSS y NET (11 200 fronteras, 224 000 puntos) en `main` y en la rama: 0 puntos inválidos, 212 puntos recuperados (209 n=2 + 3 n=3), 0 diferencias de estado/validez, diferencia máx. de pesos 0. Suite completa (incluye B1–B3, CandidateEngine, Global Frontier, Pareto, E-09/10/11): sin regresiones.

**Tests passed:** baseline previo `pytest -q`: 1151 passed. Final: **1187 passed** (36 nuevos en `tests/unit/frontiers/test_f3_post_merge_review.py`: P2-01 retornos idénticos/casi idénticos, costes asimétricos, fila nula, GROSS/NET/POST_COST_GROSS, target factible/infactible, equivalencia algebraica y con oráculo; P2-02 casos A–F más ruta real). `mypy --strict portfolio_engine`: sin errores (126 ficheros). `ruff check .`: OK. `ruff format --check .`: 261 ficheros OK. Los tests nuevos detectan los defectos: contra el `qp_builder.py` de `main` fallan 17; con la exclusión del oráculo restaurada fallan 4.

**Tests failed:** ninguno en la ejecución final. (Una ejecución intermedia falló `test_no_business_numeric_literals` por un literal `16.0` mío; corregido.)

**Files modified:** `portfolio_engine/optimizers/formulations/qp_builder.py`, `portfolio_engine/frontiers/numerical_recovery.py`, `portfolio_engine/frontiers/session.py`, `portfolio_engine/models/solution.py`, `portfolio_engine/models/frontier.py`; docs `ARCHITECTURE.md` (F3-02, F3-06), `TRACEABILITY.md` (fila de historial), `CHANGELOG.md`, `REMEDIATION_F3_NUMERICAL.md` (nota posterior, sin reescribir evidencia); nuevo `tests/unit/frontiers/test_f3_post_merge_review.py`; este informe. Informes históricos de auditoría intactos. Hallazgos registrados como procedentes de una revisión posterior al merge del PR #3.

**Known limitations:**
* El caso «weights informativos pero minúsculos frente a los auxiliares» sigue usando la escala de pesos (calibrada); no hay instancia real que lo exija.
* El caso NET de μ idénticos se prueba con fallo inicial forzado (fingido); en el barrido n = 2…5 no apareció espontáneamente.
* Sin benchmarks de rendimiento nuevos; barridos con n > 5 no repetidos.
* `iterations` sigue siendo una métrica mixta de solvers (documentado).
* Cierre de la auditoría (`AUDIT_F3_POST_MERGE.md`), limitaciones residuales, **no defectos financieros resueltos** (sin cambio de código productivo, de tolerancias ni de estados):
  * RF-01: NET casi degenerado (diferencia de retorno ≈ 1e-9…5e-9) con escala sobre pesos; la recuperación es correcta pero puede consumir una proporción elevada del presupuesto de iteraciones (medido hasta 192 475 de 200 000). Cubierto por `tests/unit/frontiers/test_f3_near_identical_net_budget.py` (sin umbral de tiempo ni de iteraciones; la regla de normalización no cambia).
  * RF-03: `iterations_by_solver` está en los diagnósticos agregados (`SolveResult`, `FrontierSession`, `FrontierDiagnostics`), no en todas las salidas por punto (`outputs/`).
  * RF-04: no hay test específico de aditividad de `setup_time`/`solve_time`.
  * RF-05: la ruta degenerada de P2-01 se verifica con fallo inicial inducido; no se reprodujo una activación espontánea en el barrido.

**Git status:** rama `fix/f3-oracle-iteration-accounting`; cambios sin commit (9 ficheros modificados + 2 nuevos: test e informe).

F3_POST_MERGE_REVIEW_STATUS = PASS
