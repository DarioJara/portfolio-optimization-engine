# AUDIT_BLOCK_2 — Auditoría técnica independiente del Bloque 2

**Rama:** `block2-continuous-frontier` · **Baseline:** tag `block1-validated` · **Fecha:** 2026-09-23
**Alcance auditado:** diff completo del árbol de trabajo (sin commit) frente a `block1-validated`: 16 ficheros modificados y 27 entradas nuevas (`git status`).
**Restricciones cumplidas:** no se modificó código ni documentación existente, sin commit, merge ni avance al Bloque 3. Único fichero creado: este. `git status --short` es idéntico antes y después de las ejecuciones.
**Método:** lectura directa del código (no solo de los tests), ejecución real de las cuatro herramientas de calidad, y experimentos adversariales de solo lectura ejecutados desde el scratchpad de la sesión (fuera del repositorio; las recetas para reproducirlos están en el Anexo A).

---

## 0. Veredicto

`BLOCK_2_STATUS = PASS` **no está plenamente justificado tal como se declara.** La matemática, la no regresión, el alcance y la higiene del diff son sólidos y se han verificado de forma independiente. El motivo del veredicto condicionado es **una debilidad de robustez no documentada en la etapa MaximumReturn** (hallazgo H-1). No corrompe resultados —el validador rechaza lo inválido y el motor degrada con notas—, pero puede **no producir frontera** en problemas sintéticos plausibles, y ni la trazabilidad, ni el CHANGELOG, ni los tests lo reflejan. Además, la lectura del benchmark que hace el CHANGELOG queda invalidada por ese mismo defecto (§WORKSPACE_AND_WARM_START_ANALYSIS).

| Severidad | Nº | Hallazgos |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 1 | H-1 |
| MEDIUM | 4 | M-1 … M-4 |
| LOW | 8 | L-1 … L-8 |
| INFO | 7 | I-1 … I-7 |

---

## 1. Ejecución real de comprobaciones (sección 18)

Ejecutadas con `.venv` (Python 3.13.6) sobre el árbol de trabajo. El `python` global no tiene las dependencias de desarrollo; el repositorio exige el `.venv` (README).

| Comando | Resultado exacto |
|---|---|
| `pytest -q` | `477 passed in 26.70s` (0 failed, 0 skipped) |
| `mypy --strict portfolio_engine` | `Success: no issues found in 96 source files` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `177 files already formatted` |
| `pytest --collect-only` sobre `unit/{optimizers,constraints,frontiers,validation}` | `174 tests collected` (reconcilia la cifra del CHANGELOG) |

Contadores del CHANGELOG (477, 174, 96 ficheros mypy, 177 ruff) **reconciliados**. Única discrepancia: la cabecera de `TRACEABILITY.md` (línea 7) dice `476 passed`; el resto de documentos dice 477 (L-6).

---

## 2. Trazabilidad (sección 1)

Recuento reconstruido fila a fila desde `TRACEABILITY.md` (316 filas): **139 `VALIDATED` · 38 `PARTIAL` · 0 `IMPLEMENTED` · 139 `NOT_IMPLEMENTED`**, idéntico a la tabla resumen y al CHANGELOG.

Comparación contra `block1-validated` (mismo conjunto de 316 IDs):

| Transición | Nº |
|---|---|
| `NOT_IMPLEMENTED` → `VALIDATED` | 80 |
| `NOT_IMPLEMENTED` → `PARTIAL` | 26 |
| `PARTIAL` → `VALIDATED` (DAT-028) | 1 |
| Regresiones (`VALIDATED` → otro estado) | 0 |
| Requisitos con bloque asignado ≥ 3 que cambian de estado | 0 |
| Filas que pasan a `IMPLEMENTED` | 0 |

- Los 107 cambios son todos de filas con bloque `1` o `2` (los `PARTIAL` mixtos «2 / 3–4» son parciales legítimos con el resto declarado). Ningún requisito de B3–B6 marcado prematuramente.
- **Evidencia de tests:** todas las referencias `ruta::test` de las filas `VALIDATED`/`PARTIAL` del B2 (más DAT-028) existen (0 faltantes; comprobación automática sobre el código).
- **Deriva de metadatos (M-4):** 16 identificadores de la columna «Clase/función prevista» de filas `VALIDATED`/`PARTIAL` del B2 no existen en el código (`check_budget`, `check_bounds`, `check_volatility`, `check_turnover`, `check_groups`, `add_cost_lifting`, `PreFeasibilityChecker.check_bounds`, `map_clarabel_status`, `composition_counts`, `EligibilityFilter`, `Availability`, `SolverVersion`, `PortfolioEngineResult`, …). El propio documento declara que en filas `VALIDATED`/`PARTIAL` esas columnas son «las reales». Además OPT-007/FRN-006 apuntan a `frontiers/explicit_portfolios.py`, que es un pass-through de 26 líneas; la lógica real está en `frontiers/session.py`.
- **Estado dudoso:** OPT-007 y FRN-006 (`VALIDATED`) cubren MaximumReturn; ver H-1. Con el defecto no documentado, `PARTIAL` (o `VALIDATED` con limitación explícita) habría sido lo honesto. FRN-019 (adaptativa) `VALIDATED`, con la salvedad de M-1.
- DAT-028 (`PARTIAL`→`VALIDATED`): el cambio en `universe_validator.py` es coherente y sus tests existen (`test_block2_config.py`, `test_constraint_compiler.py`). Aceptado.

---

## BLOCK_1_TEST_CHANGES

Respecto a `block1-validated` **solo dos ficheros de test cambian** (`git diff --stat -- tests`), pero afectan a **cuatro** tests de B1 (el enunciado hablaba de «dos tests»). Los 250 tests restantes del B1 están byte a byte sin cambios y pasan.

Verificación adversarial: se extrajeron las versiones **originales** de ambos ficheros desde el tag y se ejecutaron contra el código actual (desde el scratchpad): `4 failed, 12 passed`. Los cuatro fallos son exactamente los esperables por cambio de alcance y ninguno otro:

| # | Test original (B1) | Fallo con el código B2 | Modificación | Clasificación |
|---|---|---|---|---|
| 1 | `test_config_hashing.py::test_snapshot_is_complete_canonical_json` | El snapshot incluye `frontier`, `solver`, `benchmark` | +3 claves en el conjunto esperado. La aserción sigue siendo **igualdad exacta** de conjuntos (no se relajó a subconjunto); el resto del test es idéntico | **ACCEPT** |
| 2 | `test_architecture_rules.py::test_layered_dependencies` | Paquetes nuevos sin entrada en el grafo | +8 entradas nuevas (`costs`, `metrics`, `constraints`, `optimizers`, `validation`, `frontiers`, `outputs`, `benchmark`). Las entradas de `data`/`returns`/`risk` **no cambian**; `validation` no puede depender de `optimizers` | **ACCEPT** |
| 3 | `…::test_no_later_block_packages_exist` | 8 nombres ahora existen | Se retiran de la lista los paquetes del B2 y se añaden 13 rutas concretas de B3–B6. `candidates`, `scenarios`, `parallel`, `staging`, `persistence`, `cache`, `engine.py` siguen prohibidos. **Efecto colateral:** dentro de paquetes ya permitidos (`frontiers`, `optimizers`, `constraints`, `metrics`) la protección pasa de «paquete completo» a lista negra de nombres | **ACCEPT_WITH_CHANGES** (L-3) |
| 4 | `…::test_no_forbidden_imports` | `osqp` ahora se importa | `osqp` sale de `FORBIDDEN_IMPORTS` y se sustituye por `test_osqp_confined_to_its_backend` (solo `optimizers/osqp_backend.py`), más estricto para OSQP. `clarabel`, `cvxpy`, `pyscipopt`, `multiprocessing`… siguen prohibidos | **ACCEPT** |

Además se añaden 4 tests (`osqp` confinado, sin CVXPY en el camino de producción, validador independiente de solvers, política de restringidos fuera de backends/frontiers). `NEUTRAL_LITERALS` y `ALLOWED_NAMED_CONSTANTS` **no se ampliaron**: `test_no_business_numeric_literals` sigue siendo tan estricto como en B1 y pasa con todo el código del B2.

Otros cambios de código B1: `ConstraintConfig` gana dos campos obligatorios (`global_max_turnover`, `group_limits`) sin romper tests B1 (se construye vía loader); `universe_validator.py` solo cambia de comportamiento si hay `group_limits` configurados (vacío ⇒ idéntico a B1); `loader.py` añade la conversión de listas de tablas sin tocar el resto.

**Conclusión:** no hay evidencia de aserciones debilitadas ni cobertura eliminada para hacer pasar código nuevo. Reservado: L-3.

---

## MATHEMATICAL_VALIDATION

Auditado directamente en `optimizers/formulations/qp_builder.py`, `costs/`, `metrics/`, `validation/` y `constraints/`, y **verificado numéricamente de forma independiente** (no con los tests del repositorio):

| Comprobación | Resultado |
|---|---|
| `P = 2Σ` (triángulo superior, convención OSQP `½xᵀPx + qᵀx`) | Correcto; bloques `b, s` de `P` nulos; `P` y `A` constantes en toda la malla |
| `q(θ)[:n] = −θμ` sin costes | Correcto (verificado numéricamente) |
| Net: `q(θ) = θ·[−μ; c_b/H; c_s/H]` — **el coste lleva θ** | Correcto. Identidad comprobada: `½xᵀPx + qᵀx = wᵀΣw − θμᵀw + θ·TC(w)` con error ~2e-18 |
| Factor 2, signos, unidades | Correctos; `H` solo divide el coste (μ anualizado); sin escalados ocultos |
| Fila de retorno neta `μᵀw − (c_bᵀb + c_sᵀs)/H ≥ R` | Correcta; el conjunto factible en `w` coincide con el de `μᵀw − TC(w) ≥ R` porque los costes son ≥ 0 |
| Linealización `w − b + s = w₀` | Correcta; sin complementariedad `b·s = 0` forzada, pero no altera `w` (con costes > 0 se cumple en el óptimo; con costes 0 solo hay libertad en variables auxiliares) |
| Tolerancias | Todas proceden de `SolverConfig`/`FrontierConfig`; no hay literales de negocio en el código B2 |

**Caso pequeño donde `NET ≠ POST_COST_GROSS` con verificación independiente** (2 activos; `μ = (5 %, 10 %)`, σ = (20 %, 30 %), ρ = 0,2; actual (0,7; 0,3); compra 100/150 bps, venta 300/450 bps; `H = 1`). Referencia: **fuerza bruta sobre 2 000 001 puntos** `w = (t, 1−t)` (sin solver):

| θ | NET brute-force | NET motor | GROSS brute-force | GROSS motor | Utilidad neta NET vs post-coste |
|---|---|---|---|---|---|
| 0,3 | t = 0,70000 | 0,70000 | 0,66509 | 0,66509 | 0,013240 < 0,013582 |
| 1,0 | 0,70000 | 0,70000 | 0,50000 | 0,50000 | −0,032260 < −0,027500 |
| 3,0 | 0,66509 | 0,66509 | 0,02830 | 0,02830 | −0,162389 < −0,119406 |

En θ = 1 el motor NET mantiene la cartera actual (nudo del coste: turnover 0) mientras el GROSS post-coste rota un 20 % y gana 0,001 de retorno neto a cambio de +1,5 p.p. de volatilidad: son fronteras distintas, y el NET domina en la utilidad neta. Con θ = 3 el óptimo NET coincide con el GROSS de θ = 0,3, lo que confirma que el coste se escala con θ. **Target return neto** `R = 0,066`: brute-force t = 0,50000, motor t = 0,50000, retorno neto 0,066000.

**Turnover (sección 5).** `0,5·Σ|w − w_actual|` sobre la unión current ∪ composición (`costs/turnover.py`); las ventas totales cuentan en `TransactionCostModel` y en las métricas; sin cartera actual `turnover`, coste y retorno neto son `None` con motivo (no 0,5 ni 1); `MaxTurnover` linealizado como `½(1ᵀb + 1ᵀs) ≤ T`; el validador lo recalcula desde `w`. FORCE_LIQUIDATE / FREEZE_WEIGHT / HOLD_OR_REDUCE se traducen en `constraints/compiler.py` y el validador los **re-deriva de la política** (no de los límites compilados), con test de mutación asociado. La factibilidad previa usa `max(F⁺, F⁻+r) − r/2`, coherente con el caso `Σw₀ ≠ 1`.

**Target return (sección 6).** Neto y bruto fijan solo `lower` de la última fila. Verificado contra brute-force en neto (arriba) y por los tests SLSQP en bruto. Un objetivo infactible da `INFEASIBLE` con certificado de OSQP y la sesión sigue siendo utilizable (comprobado: tras un objetivo infactible, la resolución siguiente coincide con la de un workspace fresco, `max|Δw| = 0`).

**MaxReturn LP + QP de desempate (sección 6): el contrato se preserva cuando converge, pero no es robusto → H-1.**

---

## 3. Restricciones (sección 7)

`ConstraintCompiler` produce presupuesto `Σw = 1`, cotas efectivas con precedencia override > global > universo, `LongOnly`, `min_holding_weight` como cota continua, filas de grupo (sector, país, clase, divisa), `MaxTurnover` y la política de restringidos. Índices coherentes (composición ordenada por `AssetID`, comprobado). **No hay** cardinalidad simulada, recorte, redondeo ni renormalización posterior al solver (búsqueda de `clip`/`round`/umbrales sobre pesos en `frontiers/optimizers/constraints/validation`: solo `np.clip` sobre un coseno en `adaptive.py`). `zero_weight_tolerance` solo alimenta el recuento de activos en métricas. Sin heurísticas discretas: aceptado.

`FREEZE_WEIGHT` fija `w = w_actual` ignorando `MaxWeight`; el conflicto se detecta antes del solver (`FREEZE_WEIGHT_CONFLICT`). Correcto y testeado.

---

## 4. Backend OSQP (sección 8)

- **Construcción:** `P` triangular superior CSC, `A` CSC, `lower`/`upper` con `±inf`; `CanonicalProblem` valida finitud, dimensiones y `lower ≤ upper`.
- **`update()`:** valida (dimensión, NaN, `lower ≤ upper` fusionado) **antes** de tocar el workspace y solo pasa `q`, `l`, `u`. `P` y `A` no se reconstruyen: `_new_solver` solo lo invocan `setup()` y `cold_retry()`.
- **Mapeo de estados** (`optimizers/status.py`): `solved→OPTIMAL`, `solved inaccurate→OPTIMAL_INACCURATE`, `primal infeasible→INFEASIBLE`, `dual infeasible→UNBOUNDED`, `maximum iterations reached→MAX_ITERATIONS`, `run time limit reached→TIME_LIMIT`, `problem non convex`/certificados `*_inaccurate→NUMERICAL_ERROR`, resto→`UNKNOWN`. No se colapsan estados; un certificado de inviabilidad «inaccurate» **no** se presenta como `INFEASIBLE` (decisión A-33, coherente con «no confundir fallo numérico con inviabilidad»). `x` solo se expone en estados utilizables y finitos.
- **Cold retry realmente frío:** crea un `osqp.OSQP()` nuevo con iterado inicial cero y `max_iterations × multiplicador`; no reutiliza ni el iterado ni el `rho` del workspace original.
- **Warm start:** con `warm_start = false` se fuerza `x = y = 0` en cada resolución tras la primera; con `true` se usa el iterado previo. `polishing` se pasa según config; no se inspecciona `status_polish` (L-5: el validador cubre el riesgo).
- `adaptive_rho = True` y `verbose = False` están fijos en el backend (I-3; son decisiones del solver, no financieras).

---

## WORKSPACE_AND_WARM_START_ANALYSIS

El benchmark real (`solver_reuse_20assets_20260923T152123Z.json`) muestra reutilización sin warm start más lenta que cold en 3/4 fronteras y warm start peor en GROSS/target. El CHANGELOG lo deja «sin investigar (hipótesis: `rho`)». Resultado de la investigación:

**Respuestas a A–E**

- **A) ¿Error de implementación?** No. Los tres modos dan los mismos pesos (`max|Δw| = 0,0` verificado por mí en las cuatro fronteras y en 24 problemas adicionales: no es una comparación vacía); `updated_fields` solo contiene `q`/`lower`/`upper`; `P` y `A` no se recalculan.
- **B) ¿Reconstrucción parcial que anule el beneficio?** No. Único artefacto: en modo `COLD_SETUP` cada punto hace `setup` con `q = 0` y luego `update(q, lower)` (por eso `update_count = 19`), un paso extra irrelevante (L-4).
- **C) ¿`update()` bien usado?** Sí (solo vectores cambiados, validados).
- **D) ¿Coste de setup irrelevante a N = 20?** **No.** Medido: ~3–8 ms por `setup` frente a ~0,1–0,5 ms de `solve` en puntos bien condicionados. El setup domina; el beneficio del reuse es grande.
- **E) ¿Benchmark demasiado pequeño?** No es cuestión de tamaño sino de **confusión**: el tiempo total de la frontera está dominado por la etapa MaximumReturn (H-1), que en el benchmark consume 0,3 s (GROSS/risk: la etapa 2 termina `OPTIMAL_INACCURATE` tras 250 000 iteraciones y se descarta) o 26 750–76 750 iteraciones de un único QP (NET), frente a 75–125 iteraciones por punto de malla. Además `_iterations()` del benchmark **excluye** el LP de la etapa 1 (no está en `result.points`), de modo que iteraciones y tiempo no son comparables.

**Causa del reuse-sin-warm-start lento (verificada, ya no es hipótesis):** en el QP degenerado de la etapa 2 de MaxReturn (NET), el workspace reutilizado arrastra el `rho` adaptado durante los puntos anteriores: 76 750 iteraciones. Al fijar `rho = 0,1` justo antes de esa resolución baja a 26 750 (= valor cold). No es un bug; es el estado de `rho` de OSQP sobre un problema casi degenerado.

**Medición limpia (solo la malla, sin extremos; mediana de 7 repeticiones; el motor real):**

| Caso | COLD | REUSE | WARM |
|---|---|---|---|
| N=20 s7 GROSS risk | 61,0 ms / 1425 it | 10,8 ms / 1250 it | 8,6 ms / 975 it |
| N=20 s7 GROSS target | 64,9 ms | 11,1 ms | 8,9 ms |
| N=20 s7 NET risk | 64,9 ms | 14,1 ms | 12,5 ms |
| N=20 s7 NET target | 67,8 ms | 15,6 ms | 14,4 ms |
| N=40 s3 NET target | 83,1 ms | 27,4 ms | 28,5 ms |

El reuse aporta **≈ 3–6×** frente a cold (N=20: 4,3–5,6×; N=40: ~3×); el warm start añade poco y, en target return, a veces empeora (un cambio de `lower` desplaza el iterado previo fuera de la región factible; N=20 s1 NET target: 16,9 ms REUSE vs 21,2 ms WARM). **Conclusión: el diseño es CORRECTO y efectivo; no exigir que el warm start sea siempre más rápido.** Lo que hay que corregir es la lectura del benchmark y el defecto de MaxReturn (M-2, H-1). No se propone ninguna optimización de rendimiento nueva.

---

## 5. Hallazgo H-1 (HIGH) — MaximumReturn no es robusto y el fallo es silencioso

`FrontierSession.solve_maximum_return` resuelve un LP con OSQP (`P = 0`) y luego un QP con `μᵀw ≥ R* − ε`, con `ε = max_return_tie_epsilon = 1e-9` — **igual que `eps_abs = eps_rel = 1e-9` de OSQP**. Experimento sobre 24 problemas sintéticos (N ∈ {5, 10, 20, 40} × 6 semillas, configuración por defecto) × {GROSS, NET} × {risk aversion, target return} = 96 fronteras (Anexo A-2):

- **24/96 (25 %) degradadas** (nota `MAX_RETURN_STAGE_2_FAILED_STAGE_1_SOLUTION_RETURNED` o peor): GROSS 8/48, NET 16/48.
- **4/96 sin frontera**: en NET, N=20 semilla 0 y N=40 semilla 2, el **LP de la etapa 1** termina `MAX_ITERATIONS` (incluso tras el reintento en frío ×4) y el motor devuelve solo 2 puntos con `MAX_RETURN_NOT_SOLVED_GRID_SKIPPED`: no hay malla.
- **Coste:** hasta 250 000 iteraciones y 1,9 s por frontera a N = 40, sin beneficio (con retornos aleatorios el óptimo del LP es único y el desempate no aporta nada).
- **Causa en el LP:** OSQP no converge en esos LP con `P = 0`. Con `eps = 1e-7` converge en un caso (N=20 s0, 30 800 it.) y **no converge ni con `1e-6`** en el otro (N=40 s2). HiGHS (SciPy, ya dependencia de runtime) resuelve los mismos LP en 4–33 ms y coincide con OSQP allí donde este converge (objetivo 0,10027697853625296 vs …98).
- **Causa en la etapa 2:** el conjunto factible `{μᵀw ≥ R* − 1e-9}` es prácticamente un punto; con la solución del LP dentro de la tolerancia de OSQP aparecen `INFEASIBLE` espurios (certificados sobre un problema con punto factible conocido), `MAX_ITERATIONS` y `NUMERICAL_ERROR`.
- **Seguridad:** los fallos se degradan de forma segura (solo se aceptan soluciones `OPTIMAL` validadas). No hay resultado incorrecto.
- **Lo que falta:** ningún test ejercita los tres caminos de degradación (`grep` de las constantes `NOTE_*` en `tests/` → 0 apariciones); el CHANGELOG (Limitaciones conocidas) y `TRACEABILITY.md` no lo mencionan; OPT-007/FRN-006 figuran `VALIDATED`. Los tests del B2 usan problemas de 2–4 activos bien condicionados, por lo que no lo detectan.

**Acción exigida antes del Bloque 3 (sin implementarla aquí):** (1) documentar la limitación y degradar OPT-007/FRN-006 a `PARTIAL` hasta corregirla; (2) añadir tests con problemas de N ≥ 20 y los tres caminos de degradación; (3) decidir el tratamiento del LP: tolerancia/`max_iter` específicos, o un backend LP fiable, o `ε` relativo a la precisión del solver y omitir la etapa 2 cuando el LP es único. Cualquiera de ellas es una decisión de diseño del usuario (posible enmienda a A-14 / §46).

---

## 6. Hallazgos MEDIUM

**M-1 — La frontera adaptativa puntúa siempre con retorno bruto.** `frontiers/adaptive.py::_best_interval` usa `metrics.expected_return_gross` para huecos y curvatura también en fronteras `NET`. La curva que se grafica y sobre la que se define la eficiencia neta es (volatilidad, retorno **neto**). La adaptatividad sí es real (inserta puntos, respeta el máximo, se detiene por tolerancia; comprobado en código y en `test_adaptive_frontier.py`), pero para NET refina sobre una curva distinta y su calidad no está testeada (el único test NET solo comprueba que termina y no supera el máximo).

**M-2 — El benchmark y su lectura en el CHANGELOG no son atribuibles.** Ver §WORKSPACE_AND_WARM_START_ANALYSIS: iteraciones sin el LP, tiempos dominados por MaxReturn, hipótesis del `rho` ya verificable. BEN-003 puede seguir como herramienta, pero las cifras de la tabla del CHANGELOG no deben citarse como efecto del reuse/warm start.

**M-3 — Limitación «la composición debe contener toda la cartera actual»** (ver sección dedicada): aceptable, pero está repartida en 4 sitios y el optimizador aún no tiene el offset de liquidaciones.

**M-4 — Deriva de la trazabilidad** (16 identificadores previstos en filas validadas/parciales; ruta de módulo de OPT-007/FRN-006; `476` vs `477`). No afecta al código.

---

## ARCHITECTURAL_DEVIATIONS_DECISION

Las 10 desviaciones de `ARCHITECTURE.md` §3.2, evaluadas contra el código:

| # | Diseño original → implementación | Impacto matemático | Impacto arquitectónico / rendimiento | Riesgo B3–B6 | Recomendación |
|---|---|---|---|---|---|
| 1 | Workspace por (composición, escenario, tratamiento, método) → uno por (composición, tratamiento) compartido por ambas mallas y por MinVar/etapa 2 | Ninguno: `P` y `A` fijos (la fila de retorno está siempre, libre en la malla de θ); solo cambian `q` o `lower`; resultados idénticos a cold | Reuse ≈ 3–6× (medido). Acopla el estado `rho` entre resoluciones (efecto medido en la etapa 2 degenerada) | Escenarios (B4) exigirán un workspace por escenario; memoria por sesión acotada al ciclo de vida de la sesión; paralelismo: no se comparte entre procesos | **ACCEPT** |
| 2 | MaxReturn único → LP (workspace propio) + QP de desempate en el compartido | Formulación lexicográfica aceptada (A-14); la exactitud depende de la precisión del LP en OSQP | LP con `P = 0` no comparte workspace; coste elevado cuando falla la etapa 2 | Alto si se generaliza a MaxSharpe/otros; en B3 se resolverá para muchas composiciones ⇒ multiplica la fragilidad | **ACCEPT_WITH_CHANGES** (H-1) |
| 3 | `update(q, l, u, b)` → `update(q, lower, upper)` | Ninguno (la forma canónica no usa `b`) | Renombrado por ruff E741 | Otros backends (B4) podrían necesitar `b`; cambio trivial | **ACCEPT** |
| 4 | `SolveResult`/`ValidationReport`/`FrontierPoint` + `PointMetrics`, `FrontierDiagnostics` | Ninguno | Métricas no disponibles = `None` + motivo (§24) | Bajo | **ACCEPT** |
| 5 | Grafo: `metrics`→`config`; `outputs`→`costs`; `benchmark`→`frontiers`,`optimizers` | Ninguno | Grafo acíclico (test); `validation` no importa `optimizers`/`frontiers`/`osqp` (test) | Bajo; vigilar que `validation` dependa de `constraints` compilado (ver I-4) | **ACCEPT** |
| 6 | `ClarabelBackend` si es requerido → no adoptado; router rechaza SOCP/SDP con `RoutingError` | Ninguno en B2; SOL-005 sigue `NOT_IMPLEMENTED` | Coherente con el prompt («si es requerido por los problemas incluidos») y A-32 | La verificación cruzada real llega en B4; SOL-014 queda `PARTIAL` (honesto) | **ACCEPT** |
| 7 | `EngineConfig` sin secciones futuras → añade `frontier`, `solver`, `benchmark` (obligatorias, sin defaults en código) | Ninguno | Cada campo se consume fuera de `config/` (comprobado); `ConfigHash` las incluye; `default_engine.toml` es la única fuente de valores | Cada bloque añadirá secciones; el snapshot del hash cambiará cada vez (por diseño) | **ACCEPT** |
| 8 | `SolverConfig` con solo parámetros del solver → incluye tolerancias del validador y flags `workspace_reuse`/`warm_start` | Ninguno | Mezcla responsabilidades: tolerancias del validador (VAL-008) y flags de experimento (benchmark) en la config de producción; alteran `ConfigHash` | Bajo; si el validador crece (tracking error, CVaR) conviene un `ValidationConfig` | **ACCEPT_WITH_CHANGES** (L-7; sin urgencia) |
| 9 | Ajuste `polish` → OSQP ≥ 1.1 (`polishing`); `adaptive_rho_interval` fijo | Ninguno; el intervalo fijo da reproducibilidad bit a bit (verificado por test) | El intervalo fijo es una decisión de rendimiento no medida más allá de N ≤ 40; solo probado con osqp 1.1.3 | El cambio de `rho` entre resoluciones (M-2) interactúa con este valor | **ACCEPT_WITH_CHANGES** (L-5, I-5) |
| 10 | `POST_COST_GROSS` como evaluación ex post → re-etiquetado de puntos GROSS (mismos pesos, `point_id` nuevos, flags de Pareto recalculados, sin resolver) | Ninguno: coincide con §39; nunca se presenta como NET (test) | Cero coste de solver | Bajo | **ACCEPT** |

Especial atención: (1) workspace compartido — **correcto y efectivo**; (2) MaxReturn LP+QP — correcto en formulación, **frágil en ejecución**; (7) secciones de `EngineConfig` — **correctas**, sin parámetros ignorados; (9) OSQP ≥ 1.1 y polishing — aceptados, con la nota de que solo 1.1.3 está probado.

---

## CURRENT_PORTFOLIO_COMPOSITION_LIMITATION

Declaración: «la composición debe contener todos los activos actuales» (`ConstraintCompiler._check_composition`, `FrontierProblem`).

- **¿Requisito explícito del MASTER_SPEC?** No lo es en el sentido de una regla permanente. El **prompt del Bloque 2** exige «mantener exactamente los mismos activos» y el test `set(CurrentAssets) == set(FrontierAssets)`, y el CandidateEngine del B3 es el que retira activos. `MASTER_SPEC` §23 pide que los activos que salen cuenten como venta completa.
- **¿Limitación temporal legítima del B2?** Sí. Es coherente con el alcance («composición fija») y `TC-011` (`K_E`) figura honestamente como `NOT_IMPLEMENTED` (B3).
- **¿Entra en conflicto con B3?** No es un conflicto de contrato, pero **sí obliga a tocar código del B2**. El modelo de costes (`TransactionCostModel`) y las métricas ya son generales sobre la unión (venta completa testeada: `test_exited_assets_included`, `test_cost_is_not_computed_only_on_new_composition`), pero el **optimizador no**:
  1. `qp_builder._composition_costs` recorta `buy/sell` a la composición: el coste constante `K_E` de los activos que salen no entra ni en el objetivo neto ni en la fila de retorno neta;
  2. `CompiledConstraints.current_weights` contiene solo la composición: la fila `MaxTurnover` y el turnover del validador no incluyen `½Σ w₀` de los activos que salen;
  3. `feasibility.minimum_forced_turnover` idem (aunque ya admite `Σw₀ ≠ 1`, lo que es un buen punto de partida);
  4. el validador de `RETURN_TARGET` neto sí usa `cost_model.cost(w)` sobre la unión (correcto), por lo que detectaría el desajuste en lugar de ocultarlo.
- **¿Impide contabilizar correctamente las ventas completas?** Con la limitación, dentro del B2 **no** (no hay activos que salgan). En el B3 la contabilidad *ex post* es correcta hoy; la *optimizada* requiere los offsets de los puntos 1–3.
- **Encapsulación:** la restricción está impuesta en **un único guard** (`_check_composition`) y documentada; no es un supuesto estructural profundo. Pero el supuesto «`current_weights` vive solo sobre la composición» está replicado en los 3 puntos anteriores.

**Clasificación: ACCEPT_WITH_CHANGES.** Antes de empezar el B3, registrar en `ARCHITECTURE.md` la lista de los tres puntos a extender (offset de coste en la fila de retorno y en el objetivo; offset de turnover en la fila `MaxTurnover`, en el validador y en la factibilidad) y decidir si `CompiledConstraints` debe llevar ya `exit_cost_offset` y `exit_turnover_offset`. No se ha implementado nada de B3.

---

## 7. Solution Validator (sección 10)

Independiente del solver: no importa `optimizers`, `frontiers` ni `osqp` (test de arquitectura) y recibe solo pesos. Recalcula presupuesto, cotas, `LongOnly`, grupos, turnover (`0,5·Σ|w − w₀|` desde los pesos, no desde `b + s`), política de restringidos (desde la política), retorno objetivo bruto/neto (con `TransactionCostModel.cost`, fórmula por tramos distinta del lifting), varianza no negativa y finitud (NaN/Inf ⇒ violación con exceso infinito). `test_solver_optimal_but_invalid_rejected` demuestra que rechaza una solución que el solver marca como resuelta.

Independencia parcial (I-4): comparte con el solver los **límites compilados** (`CompiledConstraints`) y el modelo de costes; un error de compilación de cotas no lo detectaría el validador (los tests del compilador lo cubren; la política de restringidos sí se re-deriva por separado). No hay lógica circular.

## 8. Frontier Engine (sección 11)

Gross, Net y Post-Cost Gross son pipelines distintos y `CONTINUOUS_FRONTIER` no se mezcla con un futuro `GLOBAL_CANDIDATE_FRONTIER`. Malla de θ calibrada desde los extremos (`AUTO`, multiplicadores de configuración) o `EXPLICIT`; malla de retorno objetivo lineal entre `R_MV` y `R_max` (neto usa retornos netos). `InitialFrontierPoints < FrontierPoints` solo se admite con `adaptive = true` y la configuración rechaza parámetros ignorados. Deduplicación por pesos/retorno/volatilidad (marca, no elimina) y Pareto bruto/neto con duplicados heredando la eficiencia. Los puntos de una composición se resuelven **secuencialmente** en una sola sesión (sin `multiprocessing`/`concurrent`, prohibido por test). Definición de hecho del prompt: `frontier_dataset` produce `Volatility`, `ExpectedReturnGross`, `ExpectedReturnNet`. Reservas: M-1 y H-1.

## 9. Tests (sección 14)

No se acepta «477 passed» como evidencia; se auditó calidad.

- **Fortalezas:** oráculos **independientes del motor** en `tests/fixtures/reference.py` (KKT cerrado, greedy de caja, SLSQP, HiGHS `linprog`, análisis por tramos con nudo de coste para 2 activos con θ escalando el coste, LP de turnover mínimo). Test específico de que la formulación **sin** escalar por θ da soluciones distintas (`test_unscaled_cost_formulation_gives_different_solutions`) y de que NET ≠ POST_COST. Control de mutaciones de 18 mutantes (con un superviviente detectado y cerrado). Fixtures no triviales para el turnover/grupos/restringidos.
- **Debilidades:** (1) problemas de 2–4 activos ⇒ no detectan H-1 (fixtures favorables); (2) camino de degradación de MaxReturn sin test; (3) adaptativa en NET sin test de calidad (M-1); (4) `numerical_regression` usa el propio motor como referencia (detector de cambios, no prueba de corrección; declarado); (5) el control de mutaciones es un «script temporal no versionado» ⇒ no reproducible (L-8); (6) parametrizaciones (`method`, `treatment`, `policy`) son genuinas, no inflan cobertura.
- Conteo: 174 tests en solver/frontier/constraints/validation (reconciliado).

## 10. Hard-coding y configuración (sección 15)

Búsqueda de `252`, `20`, `30`, `0.02`, `0.15`, `1e-*`, defaults de θ, tolerancias, tamaños de frontera, límites de turnover y costes en `costs/ constraints/ optimizers/ frontiers/ metrics/ validation/ outputs/ benchmark/`: **ningún literal de negocio**; `test_no_business_numeric_literals` (sin ampliar) pasa. Constantes matemáticas legítimas: `2.0` (de `P = 2Σ`), `0.5` (turnover), `1.0`. Fuente única de verdad: cada valor vive solo en `config/default_engine.toml` (20 puntos, θ multiplicadores, `eps`, `max_iterations`, tolerancias, etc.) y se consume desde `FrontierConfig`/`SolverConfig`. Excepción menor I-3 (`adaptive_rho = True`, `verbose = False` en el backend).

## 11. Arquitectura y mantenibilidad (sección 16)

Grafo acíclico verificado; dominio no depende de OSQP fuera del backend (test); `validation` no depende de `optimizers`. El constructor QP (lógica financiera del lifting) reside en `optimizers/formulations`, permitido por `ARCHITECTURE`. Riesgos menores: `frontiers/explicit_portfolios.py` es un pass-through de 26 líneas, `RiskAversionGrid`/`TargetReturnGrid` son envoltorios finos sobre la sesión (L-2); `OptimizationBackend` (ABC) tiene una sola implementación pero lo exige SOL-003; `BackendCapabilities` declara flags de bloques futuros (I-6).

**Duplicación de `RestrictedExistingPositionPolicy`:** `build_constraint_set` reimplementa en 4 líneas la precedencia `spec → config` que ya existe en `data/validation/portfolio_validator.py::effective_restricted_policy`. El CHANGELOG la declara. La duplicación es **semántica** (la regla de precedencia, una de las decisiones más delicadas de E-09), no accidental; `constraints` no puede importar `data` (regla de capas). El resto de usos de la política (compilador ↔ validador) es duplicación **deliberada** (independencia del validador). **Clasificación: ACCEPT_WITH_CHANGES (L-1):** mover `effective_restricted_policy` a `models`/`config` y que ambos la reutilicen; hacerlo en el primer bloque que toque estas capas.

## 12. Dependencias (sección 17)

`pyproject.toml`: runtime = `numpy>=1.26,<3`, `scipy>=1.11,<2`, `pandas>=2.1,<4`, `pyarrow>=14`, **`osqp>=1.1,<2`** (nuevo, necesario: el código usa `polishing` y `solve(raise_error=…)`). Dev sin cambios (`pytest`, `hypothesis`, `mypy`, `ruff`, `scikit-learn` solo en tests). No hay dependencias innecesarias (`scipy` se usa en runtime por `scipy.sparse`; `linprog`/`minimize` solo en tests). `requirements-lock.txt` añade `osqp==1.1.3` y sus dependencias transitivas (`Jinja2`, `MarkupSafe`, `setuptools`). `requires-python >= 3.11`: el código usa `StrEnum` y `datetime.UTC` (3.11+), pero **solo se ha validado en 3.13.6/Windows 11** (el CHANGELOG lo declara; no se afirma lo contrario). Los límites inferiores de numpy/scipy/pandas/osqp no están probados (I-5).

## 13. Higiene del diff (sección 19)

- `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`, `IMPLEMENTATION_PLAN.md`, `CLAUDE.md`, `AUDIT_BLOCK_1.md`: **sin modificar** (`git diff --name-only` → 0).
- Nada de `1.-Version Anterior/` (está en `.gitignore`; ninguna referencia en código/config/tests).
- Sin secretos (búsqueda de `api_key|secret|password|token|BEGIN … KEY`: solo los `_TRUE_TOKENS` de parseo del B1), sin binarios, sin `__pycache__` ni `egg-info` versionables (`.gitignore`). Los únicos artefactos no-`.py` nuevos son `tests/numerical_regression/golden/frontiers.json` y `benchmarks/results/*.json` (evidencia declarada; I-7).
- Sin código de B3–B6: no hay `candidates`, `scenarios`, `parallel`, `staging`, `persistence`, `cache`, `engine.py`, Beam, Global Frontier, MIQP ni Clarabel (test + búsqueda).
- Todo el trabajo del B2 está **sin commit**; el diff se auditó sobre el árbol de trabajo.

---

## 14. Lista de hallazgos

**CRITICAL** — ninguno.

**HIGH**
- **H-1** MaximumReturn (LP en OSQP con `P = 0` y QP de desempate con `ε = 1e-9`) no converge en 25 % de las fronteras sintéticas y no produce frontera en el 4 %; sin documentar ni testear; OPT-007/FRN-006 `VALIDATED`. (§5)

**MEDIUM**
- **M-1** Adaptativa puntúa con retorno bruto también en NET; calidad NET sin test. (`frontiers/adaptive.py::_best_interval`)
- **M-2** Benchmark: iteraciones sin el LP, tiempos dominados por MaxReturn, hipótesis de `rho` ya verificable; la tabla del CHANGELOG no debe citarse como efecto de reuse/warm start.
- **M-3** Limitación de composición: `K_E` y offsets de turnover ausentes en optimizador/validador/factibilidad (aceptable en B2; obliga a tocar B2 en B3).
- **M-4** Trazabilidad: 16 identificadores inexistentes en filas validadas/parciales, ruta de módulo de OPT-007/FRN-006, `476` vs `477`.

**LOW**
- **L-1** Duplicación de la precedencia `spec → config` de la política de restringidos (centralizar en `models`/`config`).
- **L-2** Sobrefragmentación menor: `explicit_portfolios.py` (pass-through), grids como envoltorios finos.
- **L-3** `test_no_later_block_packages_exist` pasa de «paquete completo» a lista negra de nombres en paquetes ya permitidos; preferible una lista blanca de módulos por paquete.
- **L-4** `COLD_SETUP` del benchmark hace `setup` con `q = 0` y luego `update`; la referencia «cold» no es mínima.
- **L-5** No se inspecciona `status_polish` de OSQP (el validador cubre el riesgo).
- **L-6** Cabecera de `TRACEABILITY.md`: `476 passed` frente a `477`.
- **L-7** `SolverConfig` mezcla parámetros de solver, tolerancias del validador y flags de benchmark.
- **L-8** El control de mutaciones (18/18) no está versionado: evidencia no reproducible.

**INFO**
- **I-1** Los tres modos de solver dan pesos idénticos (`max|Δw| = 0`), verificado independientemente.
- **I-2** Tras una resolución `INFEASIBLE` el workspace compartido sigue siendo fiable (verificado).
- **I-3** `adaptive_rho = True`, `verbose = False` fijos en el backend (decisiones de solver, no financieras).
- **I-4** El validador comparte con el solver los límites compilados y el modelo de costes; no hay circularidad.
- **I-5** Solo `osqp 1.1.3` y Python 3.13.6/Windows están probados; los límites inferiores declarados no se han validado.
- **I-6** `BackendCapabilities` declara flags de bloques futuros; todos con valor real (`False`).
- **I-7** `benchmarks/results/*.json` y `golden/frontiers.json` son artefactos generados versionables por decisión del bloque.

---

## 15. Condiciones para cerrar el Bloque 2 (sin implementarlas aquí)

1. Documentar H-1 en el CHANGELOG (Limitaciones conocidas) y en `TRACEABILITY.md`; reclasificar OPT-007/FRN-006 a `PARTIAL` mientras no se resuelva.
2. Añadir tests de N ≥ 20 y de los tres caminos de degradación de MaxReturn; decidir con el usuario el tratamiento del LP (tolerancia/backend/ε relativo).
3. Corregir la lectura del benchmark en el CHANGELOG (M-2) o rehacerlo separando extremos y malla.
4. Decidir M-1 (retorno neto en la puntuación de la adaptativa NET) y sus tests.
5. Corregir la deriva de `TRACEABILITY.md` (M-4, L-6).
6. Registrar en `ARCHITECTURE.md` los tres puntos a extender para `K_E` en el B3 (M-3).

---

## Anexo A — Reproducción de los experimentos

Todos ejecutados desde el scratchpad, importando el repositorio (`sys.path.insert(0, '.')`) y usando `tests.fixtures.problems` y `benchmarks.scripts.solver_reuse._synthetic_problem`. No se modificó ningún fichero del repositorio.

**A-1 (`NET ≠ POST_COST` con fuerza bruta).** `make_problem(mu, S, cur, base_config(), universe_overrides={"BuyCost": [100,150], "SellCost": [300,450], "MaxWeight": [1,1]})`; sesión `open_session(..., NET|GROSS, RISK_AVERSION_GRID).solve_risk_aversion(θ)`; referencia: `t = linspace(0,1,2_000_001)`, `w = (t, 1−t)`, objetivo `wᵀΣw − θμᵀw + θ·TC(w)/H` con `TC` por tramos.

**A-2 (robustez de MaxReturn).**
```python
cfg = base_config(); eng = ContinuousFrontierEngine(cfg)
for n in (5, 10, 20, 40):
    for seed in range(6):
        prob = _synthetic_problem(n, seed, cfg)
        for t in (CostTreatment.GROSS, CostTreatment.NET):
            for m in FrontierMethod:
                r = eng.solve(prob, t, m)
                degraded = len(r.valid_points) < cfg.frontier.frontier_points or bool(r.notes)
```
Casos sin frontera (`MAX_RETURN_NOT_SOLVED_GRID_SKIPPED`): `(n=20, seed=0, NET)` y `(n=40, seed=2, NET)`. LP directo: `build_fixed_composition_problem(session.context.inputs, NET, quadratic=False)` resuelto con `OSQPBackend` a `eps ∈ {1e-9…1e-6}` y con `scipy.optimize.linprog(method="highs")`.

**A-3 (rho).** Sesión NET con `warm_start = false`; tras `solve_minimum_variance` y 4 puntos de θ se llama a `solve_maximum_return()` (76 750 iteraciones en la etapa 2) o, antes, `session.shared_backend._solver.update_settings(rho=0.1)` (26 750).

**A-4 (malla sin extremos).** Por modo (`workspace_reuse`, `warm_start`) ∈ {(F,F),(T,F),(T,T)}: `solve_minimum_variance()` y luego 18 θ (`geomspace(0.02, 2, 18)`) o 18 retornos objetivo entre `R_MV` y 0,09; mediana de 7 repeticiones, todos los puntos válidos.

**A-5 (tests B1 originales).** `git show block1-validated:<fichero>` a `scratchpad/oldtests/` y `pytest --rootdir=<scratchpad> <scratchpad>/oldtests` con `PYTHONPATH=.` → 4 fallos, todos por cambio de alcance.

---

AUDIT_STATUS = PASS_WITH_CHANGES
