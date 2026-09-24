# AUDIT_BLOCK_2_CLOSURE — Auditoría independiente de cierre del Bloque 2

**Rama:** `block2-continuous-frontier` · **Baseline:** tag `block1-validated` · **Fecha:** 2026-09-23
**Alcance:** verificar que los hallazgos de `AUDIT_BLOCK_2.md` (`AUDIT_STATUS = PASS_WITH_CHANGES`) que impedían cerrar el Bloque 2 quedaron realmente resueltos tras la remediación (`BLOCK_2_REMEDIATION_STATUS = PASS`).
**Restricciones cumplidas:** ningún fichero del repositorio fue modificado; único fichero creado: este. Sin commit, merge, push, tag ni PR; sin avance al Bloque 3. `git status --short` idéntico antes y después (46 entradas + este fichero). Los experimentos se ejecutaron desde el scratchpad de la sesión, importando el repositorio; no se cambiaron semillas, configuración, dimensiones ni tolerancias.
**Método:** lectura directa del código (`highs_backend.py`, `session.py`, `qp_builder.py`, `compiler.py`, `feasibility.py`, `solution_validator.py`, `transaction_cost_model.py`, `adaptive.py`, `continuous_frontier.py`, `router.py`, `status.py`, `solver_config.py`, `default_engine.toml`), ejecución real de las herramientas de calidad, **oráculos independientes escritos en esta auditoría** (`scipy.optimize.linprog`, SLSQP, fuerza bruta en malla; datos regenerados con la misma secuencia RNG, sin pasar por el modelo de costes del motor) y **mutación** de la implementación para comprobar que los tests detectan las regresiones.

---

## H1_REPRODUCTION

Mismas semillas y condiciones documentadas (`N ∈ {5,10,20,40}` × semillas 0..5 × `{GROSS, NET}` × `{RISK_AVERSION_GRID, TARGET_RETURN_GRID}`, configuración por defecto). Ejecutado con un script propio (criterio de la auditoría original: `degradada = len(valid_points) < frontier_points or notas`) **y** con `benchmarks/scripts/frontier_robustness.py`; ambos coinciden:

```text
Total:        96
Healthy:      96
Degraded:     0
No frontier:  0
Notas de degradación observadas: ninguna · máx. iteraciones por frontera: 21 267 · 4,3 s (antes: 250 000 it., 1,9 s por frontera a N=40)
```

**Equivalencia del generador.** El generador ya no vive en `benchmarks/scripts/solver_reuse.py` sino en `tests/fixtures/problems.py::synthetic_problem` (no hay versión histórica versionada con la que compararlo: todo es untracked). Evidencia indirecta de que reproduce los problemas originales: resolviendo el LP de la etapa 1 **con OSQP** (el backend antiguo) sobre `(N=20, seed=0, NET)` y `(N=40, seed=2, NET)` —los dos casos «sin frontera» de la auditoría— se obtiene `MAX_ITERATIONS` en ambos, y el valor óptimo NET de `(20, 0)`, `0.10027698`, coincide con el citado en `AUDIT_BLOCK_2.md` (0,10027697853…). Con HiGHS los dos casos se resuelven.

**Resultado H-1: RESUELTO.**

---

## MAXIMUM_RETURN_STAGE1_VERDICT

**PASS.** `HiGHSLPBackend` (`optimizers/highs_backend.py`) sobre `scipy.optimize.linprog`:

| Aspecto | Comprobación | Resultado |
|---|---|---|
| Signo del objetivo | `q = [−μ; c_b/H; c_s/H]`, `linprog` minimiza ⇒ maximiza `μᵀw − TC(w)` (NET) o `μᵀw` (GROSS). Verificado: `x` de un LP de juguete `max x₁+2x₂` = (0,3; 0,7), `obj = −1,7` | OK |
| Bounds / igualdades / desigualdades | `bounds=(None,None)`; las cotas de variable son filas de `A`; `lower==upper` → `A_eq`; `A x ≤ upper` y `−A x ≤ −lower` → `A_ub`; filas libres (`−inf/+inf`, fila de retorno) se omiten. Multiplicadores: `y>0` cota superior/igualdad, `y<0` cota inferior (probado: `y=[1,0,1]`) | OK |
| Variables auxiliares, turnover, costes, restringidos | Mismo `A`/`lower`/`upper` que el QP (`w−b+s=w₀`, `b,s≥0`, `½(1ᵀb+1ᵀs) ≤ T−exit_turnover`, políticas de restringidos vía cotas de `w`) | OK |
| **NET maximiza realmente el retorno neto** | Mi LP propio (variables `w,b,s`, costes regenerados desde el RNG): `|R*_motor − R*_propio| ≤ 8,8e-13` en 24 problemas (N=5,10,20; 4 semillas; GROSS y NET). Además, en 6 semillas N=20 el retorno neto de los pesos del argmax NET es ≥ el de los pesos del argmax GROSS (dif. hasta +6,4e-4; 4e-15 cuando coinciden): no es «GROSS con costes calculados después» | OK |
| Estados | `OPTIMAL`, `INFEASIBLE` (`x₁+x₂=1, x≤0,4`), `UNBOUNDED`, `MAX_ITERATIONS` (con `lp_max_iterations=1`; el reintento `highs-ds` también termina `MAX_ITERATIONS`, sin promoverlo). Código 4 de `linprog` → `NUMERICAL_ERROR`, nunca `INFEASIBLE`. Sin `x` cuando el estado no es utilizable | OK |
| Confinamiento de backends | `SolverRouter`: `QP → OSQPBackend`, `LP → HiGHSLPBackend` (comprobado); `HiGHSLPBackend.supports` solo `LP` y `setup` rechaza `P ≠ 0`; `scipy.optimize` confinado a `highs_backend.py` (test de arquitectura); `warm_start` lanza `SolverError` en vez de ignorarse | OK |

**OSQP sigue siendo el backend QP; HiGHS solo se usa en LP autorizados.**

---

## MAXIMUM_RETURN_STAGE2_VERDICT

**PASS.** Formulación (`FrontierSession._solve_on_optimal_face`): con un dual óptimo `y` del LP se fijan como igualdades las filas con `|y_i| > lp_feasibility_tolerance` (a su cota activa: superior si `y>0`, inferior si `y<0`), se resuelve `min wᵀΣw` (workspace OSQP propio) y se exige `retorno ≥ R* − tol`.

**Análisis matemático.** Por complementariedad, para *cualquier* solución dual óptima `y`, toda primal óptima deja activas las filas con `y_i ≠ 0`; recíprocamente, toda `x` factible con esas filas activas cumple `cᵀx = yᵀ(Ax) = opt`. Por tanto el conjunto «factible con las filas fijadas» es **exactamente la cara óptima**, aunque el dual no sea único. Consecuencias:

- **Degeneración:** filas activas con dual 0 no se fijan → la cara conserva sus grados de libertad legítimos (probado con costes 0, donde `b,s` son libres; ver casos abajo).
- **Duales cercanos a cero:** el umbral es `lp_feasibility_tolerance` (1e-9, configuración). Una fila con multiplicador genuino menor no se fija; el coste en retorno queda acotado por ese multiplicador y `retorno ≥ R* − tol` sigue exigido y validado (limitación declarada en el CHANGELOG).
- **Sobre-restricción:** no aparece: el QP es factible por construcción (contiene la solución del LP). Medido: las 96 fronteras completas y los casos H-1 sin degradación ni notas.
- **Salir de la cara:** la franja `retorno ≥ R* − tol` solo puede perder `tol` (≈1e-8) de retorno; el `SolutionValidator` recibe ese objetivo y lo comprueba con su propia fórmula.
- **Mutación:** con `_solve_on_optimal_face(target, None)` (sin fijar la cara) fallan los tests `test_h1_cases_now_produce_a_complete_healthy_frontier[…]` y `test_net_target_return_grid_meets_every_net_target[20-0]`/`[40-2]`: el mecanismo de duales es necesario y está cubierto.

**Casos pequeños con múltiples soluciones de máximo retorno** (referencia: fuerza bruta en malla 0,001 sobre el símplex, sin solver; `Σ` con correlaciones distintas, `μ` con empates):

| Caso | Puntos de la cara | Var. mínima (fuerza bruta) | Var. motor | Peor var. en la cara | Pesos motor |
|---|---|---|---|---|---|
| GROSS, 2 activos con `μ` empatado, cap 0,6 | 201 | 0,037440000 | 0,037440000 | 0,047440000 | (0,6; 0,4; 0) |
| GROSS, empate + `MaxTurnover=0,15` activo | 151 | 0,035111250 | 0,035111250 | 0,045596250 | (0,35; 0,3; 0,35) |
| NET, costes 0 (`b,s` degenerados), empate | 201 | 0,037440000 | 0,037440000 (Δ=1,2e-12) | 0,047440000 | (0,6; 0,4; 0) |
| NET, empate de `μ` y costes simétricos 20 bps | 101 | 0,037440000 | 0,037440000 | 0,041500000 | (0,6; 0,4; 0) |
| GROSS, 3 activos con `μ` idéntico (cara 2-D) | 260 901 | 0,026800000 | 0,026800000 | 0,064000000 | (0,6; 0; 0,4) |

En todos el motor elige el mínimo-riesgo de la cara (no un vértice cualquiera). Con datos aleatorios la cara es un vértice y el QP devuelve el vértice del LP (`var_motor − var_vértice ≤ 2e-13`); la referencia SLSQP sobre la franja `R*−1e-9` da varianzas marginalmente menores (1e-9…2e-8) solo por explotar esa franja de 1e-9 (y no converge en 3 de 24), por lo que no se usa como criterio de exactitud.

---

## TOLERANCIA DE ETAPA 2

**PASS.**

- Política: `tol = max(max_return_tie_abs_tolerance, max_return_tie_rel_tolerance·|R*|)` en `SolverConfig.max_return_tie_tolerance` — **única fuente**; único consumidor: `session.py:200`.
- Unidades: retorno anualizado (bruto o neto según el tratamiento), igual que `R*`. Valores en `config/default_engine.toml`: `abs = 1e-8`, `rel = 1e-7`.
- Validación de configuración: no negativos; ambos a 0 se rechaza (conjunto degenerado).
- `max_return_tie_epsilon` / `tie_epsilon`: **ausentes** del código y del TOML; solo aparecen en tests que afirman su ausencia (`test_block2_config.py:207-208`) y en documentos históricos. Búsqueda de `1e-9` en `portfolio_engine/`: **0** apariciones. `lp_feasibility_tolerance = 1e-9` vive en el TOML.
- Test de arquitectura (`test_architecture_rules.py:355`) restringe el uso de `max_return_tie` a los módulos permitidos. Tests: `test_max_return_tie_tolerance_is_absolute_or_relative_in_return_units` (signo, dominio de cada término, casos solo-abs y solo-rel), `test_stage_two_target_is_the_configured_tolerance_below_the_lp_optimum` (GROSS y NET: el objetivo de la etapa 2 es `R* − tol`).

---

## REMOVED_ASSETS_VERDICT

**PASS.** Escenario propio (distinto del de los tests): actual `A,B,C,D = 0,4/0,3/0,2/0,1`; composición fija `A,B,E,F` (`A000,A001,A004,A005`); `μ=(5,6,4,3,11,8)%`, compras 25-75 bps, ventas 90-190 bps, `MaxWeight=0,6`, `H=1`. `C` y `D` se liquidan por completo. Oráculo: malla 0,01 sobre los 4 pesos (176 k puntos) con fórmulas escritas aquí.

| Magnitud | Manual | Motor |
|---|---|---|
| `exit_turnover` | `0,5·(0,2+0,1) = 0,15` | `0,15` (`CompiledConstraints.exit_turnover`; precheck lo cita) |
| `K_E` (`exit_cost_one_off`) | `0,2·130e-4 + 0,1·150e-4 = 0,0041` | coincide (el retorno neto publicado y el objetivo del test de mutación lo exigen) |
| MaximumReturn NET (sin límite) | `R* = 0,0801` en `(0;0;0,6;0,4)` | `NetReturn = 0,0801000000`, pesos idénticos; `Turnover = 1,000000`; `TC_one_off = 0,01790000`; `TC = 0,01790000` (manual = métrica) |
| MaximumReturn NET, `MaxTurnover=0,35` | `R* = 0,067175` en `(0,35;0,3;0,35;0)` | `0,0671750000`, mismos pesos; turnover incluyendo salidas `0,350000 ≤ 0,35` |
| Objetivo NET (malla de 20 objetivos) | retorno neto manual `≥ target` y varianza `≤` la del oráculo en rejilla | 0 violaciones en 20 puntos; p. ej. `target=0,064039`, neto manual `0,064039`, var. motor `0,01438982` ≤ rejilla `0,01439620` |
| Precheck de factibilidad | `MaxTurnover=0,14 < 0,15` ⇒ inviable solo por las salidas; `0,29 < 0,30` (turnover mínimo forzado); `0,30` factible | `REMOVED_ASSETS_TURNOVER_ABOVE_MAX`, `TURNOVER_FORCED_ABOVE_MAX`, y factible; en los dos primeros `solve_count = 0` (el solver no se invocó) |
| `SolutionValidator` | `w=(0,4;0,2;0,2;0,2)`: parte de composición `0,25 ≤ 0,35` pero con salidas `0,40 > 0,35` | `TURNOVER:max` violado. Objetivo NET `0,0625` con neto real `0,0620` (sin `K_E` sería `0,0661`): `RETURN_TARGET:net` violado |

La identidad `Turnover = 0,5·(Σ_composición|wᵢ−currentᵢ| + Σ_retirados|currentⱼ|)` se cumple en compilador, constructor QP (`T − exit_turnover`), precheck, validador y métricas. **Mutación:** con `exit_turnover ≡ 0` fallan 4 tests de `test_removed_assets.py`; con `exit_cost_one_off ≡ 0` fallan `test_net_target_return_accounts_for_the_liquidation_cost` y `test_compiled_exit_data_is_consistent_with_the_cost_model` (`K_E` es aditivo constante en el argmin del MaximumReturn, por eso solo lo detecta la fila de retorno del objetivo NET, como cabe esperar).

Ninguna capa omite la parte constante de los activos retirados. `TC-011` queda `PARTIAL` con justificación (integración con generación de composiciones en B3).

---

## RESTRICTED_POSITIONS_VERDICT

**PASS.** Activo restringido en cartera (`w₀ = 0,3`) dentro de la composición, fronteras de 20 puntos, GROSS y NET:

- `HOLD_OR_REDUCE`: rango `[0,1934; 0,3000]`, nunca por encima de `w₀` (exceso máx. 2,9e-10 en NET, ruido del solver dentro de `bound_tolerance`). Un restringido en cartera que sale de la composición es compatible (precheck factible; 20 puntos válidos).
- `FORCE_LIQUIDATE`: `w = 0`. Que salga de la composición equivale a la liquidación (factible, 20 puntos válidos).
- `FREEZE_WEIGHT`: `w = w₀` en toda la frontera. Un activo con `CurrentWeight > 0` **no puede salir**: rechazo previo al solver con `FREEZE_WEIGHT_EXITED` (`solve_count`/puntos = 0). Conflicto con los límites de configuración (`w₀ = 0,7 > MaxWeight = 0,6`) → `FREEZE_WEIGHT_CONFLICT`, también con `solve_count = 0`.

**Independencia semántica:** el compilador traduce la política a cotas; el validador re-deriva la política desde `RestrictedExistingPositionPolicy` y `w₀` (incluidos los retirados con `FREEZE_WEIGHT`), no desde las cotas compiladas; `test_policy_consistency.py` comprueba que aceptan exactamente los mismos pesos para las tres políticas. Se probó el validador con: subida de un restringido (`RESTRICTED_POLICY:A001:no_increase` + `BOUNDS`), etc. (ver SOLUTION_VALIDATOR_VERDICT).

---

## ADAPTIVE_NET_VERDICT

**PASS.** `frontiers/adaptive.py::scoring_return`: `GROSS → expected_return_gross`; `NET → expected_return_net` (neto con liquidaciones); `POST_COST_GROSS → expected_return_net` de los pesos `GROSS` (la frontera resuelta es la GROSS y la curva publicada, (volatilidad, retorno tras costes), es la que se refina; `post_cost_evaluation` re-etiqueta los puntos sin resolver nada nuevo y nunca los presenta como NET). Un retorno neto no disponible lanza `FrontierError`, no degrada en silencio.

**Test que falla si NET vuelve a bruto** (`test_net_adaptive_frontier_is_scored_with_the_net_return`, con costes de 200 bps para que ambas curvas difieran > 1e-3): ejecutado y en verde; además se **mutó** `continuous_frontier.scoring_return` para devolver siempre el retorno bruto y el resultado fue `3 failed, 2 passed` (fallan las dos variantes NET y la de POST_COST_GROSS; el test GROSS sigue verde, como debe). Baseline sin mutación: `12 passed` en el fichero.

---

## SOLUTION_VALIDATOR_VERDICT

**PASS.** No importa `optimizers`, `frontiers`, `osqp` ni `scipy` (búsqueda de imports + test de arquitectura); recibe solo pesos y restricciones compiladas. Rechazos comprobados directamente sobre pesos (cartera `0,4/0,3/0,2/0,1`, `MaxTurnover=0,2`, `A001` restringido `HOLD_OR_REDUCE`):

| Entrada | Resultado |
|---|---|
| `w₀` | válida |
| `Σw ≠ 1` | `BUDGET:sum` |
| `NaN`, `Inf` | `FINITE:weights` (exceso `inf`) |
| `w > MaxWeight` | `BOUNDS:A000:upper` (+ `TURNOVER:max`) |
| `w < 0` | `BOUNDS:…:lower` + `LONG_ONLY:…` |
| restringido que sube | `BOUNDS` + `RESTRICTED_POLICY:A001:no_increase` |
| turnover > máximo | `TURNOVER:max` |
| activo retirado no contado en el turnover / `K_E` no contado en el objetivo NET | `TURNOVER:max` / `RETURN_TARGET:net` |
| objetivo bruto/neto inalcanzable | `RETURN_TARGET:gross` / `RETURN_TARGET:net` |
| retirado con `FREEZE_WEIGHT` (test) | `RESTRICTED_POLICY:…:frozen_exited` |

`test_solver_optimal_but_invalid_rejected` (backend manipulado que devuelve `OPTIMAL` con pesos inválidos) pasa: todos los puntos siguen con estado `OPTIMAL` pero `is_valid_solution = False`, `status_source = VALIDATOR`, y quedan fuera de Pareto. Los costes de transacción se validan a través del objetivo NET (fórmula por tramos sobre la unión, distinta del lifting); no existe una comprobación independiente de «coste ≤ X» porque el contrato no define ese límite.

Reserva heredada (I-4 de `AUDIT_BLOCK_2`): comparte con el compilador el objeto `CompiledConstraints` (incluidos `current_weights` y `exited`); un error de compilación de esas listas se propagaría de forma coherente. Compensado por los tests del compilador y por mi comprobación manual de `exit_turnover`/`K_E`.

---

## TRACEABILITY_VERDICT

**PASS.** Reconstruido fila a fila desde `TRACEABILITY.md` (316 IDs, mismo conjunto que en `block1-validated`):

| Estado | Filas | Tabla resumen | CHANGELOG (remediación) |
|---|---|---|---|
| `VALIDATED` | **139** | 139 | 139 |
| `PARTIAL` | **39** | 39 | 39 |
| `IMPLEMENTED` | 0 | 0 | 0 |
| `NOT_IMPLEMENTED` | **138** | 138 | 138 |
| Total | **316** | 316 | — |

- Transiciones vs `block1-validated`: `NI→VALIDATED` 80, `NI→PARTIAL` 27, `PARTIAL→VALIDATED` 1 (DAT-028), sin regresiones ni filas `IMPLEMENTED`. Antes de la remediación eran 38 `PARTIAL`/139 `NI`: la diferencia es `TC-011`.
- **OPT-007** y **FRN-006**: `VALIDATED`, con la evidencia de la remediación (robustez N=10-40, cara óptima, degradación, tolerancia, reproducción 96/96/0/0). Tras mi reproducción independiente (H1_REPRODUCTION) y los oráculos anteriores, el estado está justificado. Las rutas de módulo ya son las reales (`frontiers/session.py`, `optimizers/highs_backend.py`).
- **TC-011**: `NOT_IMPLEMENTED → PARTIAL` (bloque «3»). Es el único requisito con bloque asignado ≥ 3 que cambia de estado. Aceptado: lo implementado son las constantes `K_E`/`exit_turnover` dentro de los módulos del B2 (optimizador de composición fija, sin `CandidateEngine`), exigido por la remediación; el resto (generación de composiciones, TST-014) sigue declarado pendiente en el propio estado. Ningún otro requisito de B3–B6 avanzó (0 con bloque 3–6 fuera de `NOT_IMPLEMENTED`, salvo `TC-011`).
- Las 404 referencias `ruta::test` de las 178 filas `VALIDATED`/`PARTIAL` existen (0 faltantes). La cabecera dice `558 passed` (deriva `476` corregida).

---

## BLOCK1_REGRESSION_VERDICT

**PASS_WITH_NOTE** (no equivale a «los 252 tests originales pasan sin tocar»; se documenta con exactitud).

Los 252 tests de `block1-validated` se extrajeron con `git archive` a un directorio aparte y se ejecutaron **contra el código actual**: `248 passed, 4 failed`. Los 4 fallos son exactamente los tests cuyo contrato se amplió de forma deliberada y documentada en `AUDIT_BLOCK_2.md` (BLOCK_1_TEST_CHANGES, aceptados): `test_snapshot_is_complete_canonical_json` (nuevas secciones `frontier/solver/benchmark` del `ConfigHash`), `test_layered_dependencies`, `test_no_later_block_packages_exist` y `test_no_forbidden_imports` (paquetes de B2 y `osqp`). Sus versiones modificadas (más estrictas o equivalentes; `git diff --stat -- tests` = solo 2 ficheros de test modificados, +117/−11) pasan en la suite actual. Los otros 248 pasan sin cambios. Además, en el árbol actual pasan íntegros los 558 tests.

---

## AUDIT_BLOCK_2_SHA256

Fichero **no modificado** durante esta auditoría (SHA calculado antes y después con `sha256sum`; `Get-FileHash` coincide):

```text
SHA-256:  3d9940c040ad070f00f23e768d3254ead151a1447c9d5df280604500d3b736a4
Líneas:   344 (wc -l, terminadores LF; 0 caracteres CR)
Bytes:    39 799
Veredicto original: AUDIT_STATUS = PASS_WITH_CHANGES (última línea del fichero)
```

Este SHA-256 es la **referencia de integridad futura**. No se afirma que coincida byte a byte con la versión inicial: el CHANGELOG indica que el formatter lo alteró una vez y que se «restauró la línea original», pero no existe evidencia histórica (el fichero es untracked) que permita demostrar la identidad byte a byte.

---

## TOOLING_FORMAT_RECOMMENDATION

Ejecutado con el `.venv` (Python 3.13.6, ruff 0.16.8), sin cambiar configuración:

- `ruff format --check .` → **`1 file would be reformatted, 183 files already formatted`** (exit ≠ 0). El único fichero es `AUDIT_BLOCK_2.md` (bloque de código Python de la línea 325: el formatter de Markdown reescribiría `cfg = base_config(); eng = …`). Evidencia histórica: no debe tocarse. Todo el código Python está formateado.
- Comprobado sin modificar `pyproject.toml`, solo con override por línea de comandos: `ruff format --check --config 'format.exclude=["AUDIT_BLOCK_*.md"]' .` → **`182 files already formatted`** (excluye `AUDIT_BLOCK_1.md` y `AUDIT_BLOCK_2.md`); `ruff check` con el mismo override: `All checks passed!`.
- **Recomendación** (para decidir e implementar fuera de esta auditoría): añadir en `pyproject.toml`, dentro de `[tool.ruff.format]`, `exclude = ["AUDIT_BLOCK_*.md"]` (mejor que `extend-exclude` global: mantiene el lint sobre esos ficheros y solo protege del formatter). Alternativa menos general: `--exclude` en el comando de CI. Complementar la advertencia que ya hay en el README («nunca `ruff format .` en la raíz») y la memoria del proyecto. Mientras tanto, `ruff format --check .` en la raíz seguirá fallando solo por ese fichero. Los informes de auditoría nuevos (`AUDIT_BLOCK_2_CLOSURE.md` incluido) evitan bloques ```python``` para no introducir más ficheros afectados.

---

## ARCHITECTURAL_DECISIONS

Decisiones R2-01…R2-05 de `ARCHITECTURE.md` §3.3 (más el párrafo «Diagnósticos (M-2)», que en el documento no lleva identificador `R2-xx`; `R2-05` es la centralización de la política de restringidos):

| Decisión | Veredicto | Justificación |
|---|---|---|
| **R2-01** LP de MaximumReturn con HiGHS (`linprog`), OSQP sigue en QP | **ACCEPT** | Resuelve la causa raíz medida (OSQP no converge en LP con `P=0`); HiGHS es dependencia ya existente; sin dependencia nueva; router explícito, confinamiento por test, estados sin colapsar, `warm_start` no soportado y declarado. Verificado en 24 problemas contra un LP propio (≤ 8,8e-13). Reserva menor: sin warm start, un LP por frontera (aceptable) |
| **R2-02** Etapa 2 sobre la cara óptima por duales + `R* − tol` con `tol` de configuración | **ACCEPT** | Matemáticamente exacta (complementariedad), verificada con 5 casos degenerados por fuerza bruta y mutación; tolerancia única y configurable. Reserva menor: umbral de dual = `lp_feasibility_tolerance` (documentado) |
| **R2-03** Activos actuales fuera de la composición: liquidación completa, `K_E`, `exit_turnover`, precheck, validador | **ACCEPT** | Cubre las tres capas señaladas en `AUDIT_BLOCK_2` (objetivo/fila neta, `MaxTurnover`, validador/precheck); comprobado manualmente (tabla de REMOVED_ASSETS_VERDICT) y por mutación. `TC-011` `PARTIAL` es honesto |
| **R2-04** Adaptativa puntúa con el retorno del tratamiento | **ACCEPT** | Cierra M-1; el test falla realmente si NET vuelve a bruto (mutación verificada) |
| **R2-05** Precedencia de la política de restringidos en `models/portfolio.py::resolve_restricted_policy` (dedup) preservando la independencia compilador/validador | **ACCEPT** | Cierra L-1 sin sacrificar la independencia del validador; test de consistencia y de implementación única |
| **Diagnósticos por fase** (`min_variance_time`, `max_return_time`, `grid_time`, `total_iterations`, `endpoint_iterations`) | **ACCEPT_WITH_CHANGES** | Cierra M-2: el benchmark separa realmente MinVariance, MaxReturn (LP + etapa 2) y malla, e incluye las iteraciones del LP. Cambio menor recomendado: darle un identificador (`R2-06`) o incorporarlo a la tabla para que la trazabilidad de decisiones sea completa; no hay «endpoint discovery» como fase propia más allá de `min_variance`+`max_return` (la calibración de la malla queda dentro de `grid`, coste despreciable) |

---

## Benchmark (revisión pedida en §12)

`benchmarks/results/solver_reuse_20assets_20260923T172754Z.json` (N=20, 20 puntos, semilla 7, 5 repeticiones + 1 de calentamiento, osqp 1.1.3, scipy 1.18.1). Fases realmente separadas: `setup`, `update`, `solve`, `frontier_total`, `min_variance`, `max_return`, `grid`; iteraciones `endpoint_solver_iterations` (incluye el LP) y `grid_solver_iterations`. Recalculado por mí desde el JSON (media, ms):

| Caso | grid cold → reuse → warm | cold/reuse (malla) | reuse/warm | frontera total cold/reuse |
|---|---|---|---|---|
| GROSS / aversión | 126,3 → 20,9 → 17,2 | **6,04×** | 1,21× | 2,95× |
| GROSS / objetivo | 131,9 → 30,5 → 32,2 | **4,33×** | 0,95× | 2,58× |
| NET / aversión | 138,0 → 29,5 → 29,2 | **4,68×** | 1,01× | 2,75× |
| NET / objetivo | 147,8 → 51,8 → 47,8 | **2,86×** | 1,08× | 2,05× |

- **Workspace reuse: la evidencia soporta ≈ 2,9×–6,0× en la malla** (rango ~2,8×–6× del CHANGELOG; en la frontera total, 2,05×–2,95×, porque los extremos, ≈ 28–34 ms, no dependen del modo). Los tres modos dan pesos idénticos (`max|Δw| = 0`).
- **Warm start: no mejora en todos los casos.** Solo reduce iteraciones/tiempo apreciablemente en GROSS/aversión (925 vs 1275 iteraciones); en GROSS/objetivo es peor que reuse (0,95×; iteraciones 4875 → 5150) y en los otros dos queda dentro de ±8 %. La afirmación del CHANGELOG («no se afirma que el warm start siempre acelere») es correcta.
- Las cifras antiguas (`…152123Z`, 853,6 ms, etc.) siguen en el repositorio como histórico; el CHANGELOG las declara no atribuibles. No se extrapola N=20 a producción: un solo tamaño, una semilla, una máquina (Windows 11), y el JSON registra `git_commit = 763b1fd…+dirty` (árbol sin commit, por lo que la ejecución no es reproducible por commit).

---

## Git diff frente a `block1-validated` (§14)

- `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`, `IMPLEMENTATION_PLAN.md`, `CLAUDE.md`, `AUDIT_BLOCK_1.md`: **intactos** (`git diff --stat` vacío). 18 ficheros tracked modificados (documentación de estado, configuración, `enums`, `exceptions`, validadores B1 con cambio semántico nulo sin `group_limits`, `pyproject`/lock: `osqp>=1.1,<2`, `osqp==1.1.3`, `Jinja2`, `MarkupSafe`, `setuptools`; `scipy` ya era dependencia).
- Ausentes: `CandidateEngine`, Beam Search, Global Candidate Frontier, MIQP/`pyscipopt`, Clarabel, CVXPY, `multiprocessing`/`SharedMemory`/`concurrent`, SQL/persistencia/caché, `engine.py`, `scenarios`, `parallel`, `staging` (búsqueda en `portfolio_engine/`: solo aparecen menciones en docstrings, el enum `MIQP` de B1 y el router que **rechaza** con `RoutingError`).
- Sin secretos (`api_key|secret|password|BEGIN … KEY`: 0 ficheros). Sin binarios: los 3 ficheros no-`.py`/`.md` nuevos son JSON de texto (`benchmarks/results/*.json` ×2, `tests/numerical_regression/golden/frontiers.json`).
- Todo el trabajo del Bloque 2 sigue **sin commit** (el diff se auditó sobre el árbol de trabajo).

---

## Tests

Todas las cifras proceden de ejecuciones reales de esta auditoría (`.venv`, Python 3.13.6, Windows 11):

| Comando | Resultado |
|---|---|
| `pytest -q` | **558 passed** en 29,6 s (0 failed, 0 skipped) |
| `mypy --strict portfolio_engine` | `Success: no issues found in 97 source files` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `1 file would be reformatted, 183 files already formatted` (único fichero: `AUDIT_BLOCK_2.md`; ver TOOLING_FORMAT_RECOMMENDATION) |
| Tests de B1 originales (extraídos del tag) vs código actual | 248 passed, 4 failed (cambios de alcance documentados) |
| Reproducción H-1 (`frontier_robustness.py` y script propio) | 96 / 96 / 0 / 0 |
| Mutaciones de esta auditoría | `scoring_return→bruto`: 3 tests fallan · `exit_turnover≡0`: 4 fallan · `exit_cost≡0`: 2 fallan · etapa 2 sin duales: los tests H-1 fallan |
| Oráculos independientes | R* vs LP propio (24 problemas): ≤ 8,8e-13 · 5 casos degenerados vs fuerza bruta: coinciden · escenario A,B,C,D→A,B,E,F: coincide con el cálculo manual |

---

## Known residual limitations

Ninguna bloquea el cierre. Se documentan para su decisión:

1. **Todo el Bloque 2 está sin commit** y la rama `block2-continuous-frontier` no contiene ningún commit de B2: el cierre no está anclado a un hash ni a un tag; el benchmark registra `+dirty`.
2. **`ruff format --check .` falla en la raíz** por `AUDIT_BLOCK_2.md`; hay que aplicar la exclusión recomendada (decisión de configuración fuera de esta auditoría).
3. **Integridad histórica de `AUDIT_BLOCK_2.md`**: solo puede fijarse a partir del SHA-256 actual.
4. **Identificación de la cara óptima** con umbral `lp_feasibility_tolerance`: un multiplicador genuino menor no se fija (coste en retorno acotado, `retorno ≥ R* − tol` validado). El LP se resuelve siempre en frío (un LP por frontera).
5. **Generador sintético** movido a `tests/fixtures`; su equivalencia con el original se apoya en evidencia indirecta (mismos casos fallan con OSQP).
6. **Benchmark** de un tamaño (N=20), una semilla, una máquina; no extrapolable a producción. El warm start no es universalmente beneficioso.
7. Solo validado con Python 3.13.6/Windows 11, `osqp 1.1.3`, `scipy 1.18.1`; los límites inferiores de dependencias no están probados.
8. `TC-011` `PARTIAL` (integración con la generación de composiciones y TST-014 en B3); `current_metrics` es `None` con activos retirados si alguno falta en el modelo de riesgo.
9. Hallazgos menores de `AUDIT_BLOCK_2` no abordados y aceptados fuera de alcance: L-2, L-3, L-4, L-5, L-7, L-8, I-1…I-7 (cuatro mutantes de la remediación y los míos tampoco están versionados).
10. Validador y compilador comparten `CompiledConstraints` (independencia parcial, I-4).
11. Las decisiones de diagnósticos por fase no tienen identificador `R2-xx` propio.

---

AUDIT_BLOCK_2_CLOSURE = PASS
