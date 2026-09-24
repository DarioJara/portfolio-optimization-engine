# AUDIT_BLOCK_3_FINAL_CLOSURE — Auditoría independiente de cierre definitivo del Bloque 3

**Rama:** `block3-candidate-engine` · **Baseline:** tag `block2-validated` (`6af836c`) · **Fecha:** 2026-09-24
**Declaración auditada:** `BLOCK_3_FINAL_REMEDIATION_STATUS = PASS` (`REMEDIATION_BLOCK_3_CLOSURE.md`).
**Restricciones cumplidas:** sin avance al Bloque 4; sin commit, merge, push, tag ni PR; no se modificó código productivo, tests ni documentación existente; único fichero creado en el repositorio: este informe. Todos los experimentos (escenarios adversariales, mutantes, comparación con el baseline) se ejecutaron desde el scratchpad de la sesión, sobre **copias** del árbol (`copy/`) y una extracción `git archive block2-validated` (`base/`). Las ejecuciones de `pytest` pueden haber regenerado cachés ignoradas por git (`__pycache__`, `.hypothesis`).

**Método.** Precheck de rama/estado/tag; lectura de los documentos de gobierno y de los cuatro informes previos del Bloque 3; diff completo frente al baseline **incluyendo los 74 ficheros sin seguimiento**; ejecución propia de las cuatro herramientas; **scripts adversariales propios** (escenario distinto del de los tests: 5 activos, `w_current = 0,15`, `MaxWeight = 0,5`, `μ_A000 = 0,40`), Pareto recalculado con bucles explícitos, 7 mutantes en copia aislada, comparación bit a bit contra el baseline y reproducción de F-3 en ambos árboles.

---

## 1. Executive Summary

Las remediaciones del implementador se **reproducen de forma independiente**. H-1/E-10 está cerrado en todas las rutas (compilador, factibilidad, frontera continua GROSS/NET × 2 métodos, `CandidateEngine`, `PROJECTED_WEIGHTS`, `QP_UTILITY`, frontera global, `SolutionValidator`). F-1 (unidad de `ADV`), F-2 (divisas/FX) y F-4 (restringidos) están cerrados con rechazo explícito y sin ninguna conversión ni inferencia implícita; `FEA-006` y `CON-012` se sostienen como `VALIDATED`. Sin regresión económica: 480 puntos de frontera (4 políticas × 3 tratamientos × 2 métodos) son **idénticos bit a bit** al baseline; los 51 ficheros de test históricos pasan (560). El motor sigue generando múltiples composiciones (11) y la Global Candidate Frontier contiene 6 `CompositionID` no dominados, con Pareto recalculado de forma independiente coincidente.

F-3 (numérica, heredada de B2) sigue **abierta**, es **idéntica en `block2-validated`**, no fue agravada por B3, ningún punto no óptimo se presenta como válido y existen casos deterministas para su remediación. No bloquea la integración de B3, pero debe remediarse (o asignarse expresamente) **antes de comenzar B4**.

No hay hallazgos abiertos bloqueantes del Bloque 3. Se registran 5 observaciones no bloqueantes (§17).

| Comprobación | Resultado propio |
|---|---|
| `pytest -q -p no:cacheprovider` | **1039 passed in 123,77 s** (0 failed, 0 skipped; exit 0) |
| `mypy --strict portfolio_engine` | `Success: no issues found in 124 source files` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `252 files already formatted` (el informe del implementador decía 251; diferencia de un fichero, sin consecuencia: todos conformes) |
| 51 ficheros de test de `block2-validated` sobre el código actual | **560 passed** |
| Adversarial H-1/E-10 (4 causas × 8 rutas + validador) | máximo de `A000` = **0,15** en todas |
| Mutantes (copia aislada) | **7/7 detectados** (§12; uno tras corregir un mutante mío mal construido) |
| Frontera continua B2 vs baseline (480 puntos) | SHA-256 idéntico; estados `OPTIMAL`, 480 válidos en ambos |
| F-3 en baseline vs actual | mismas 10 combinaciones/estados en ambos árboles |

Precheck: rama `block3-candidate-engine` ✔; tag `block2-validated` presente ✔; 37 ficheros modificados + 74 sin seguimiento (81 entradas en `git status --short`).

---

## 2. H-1 / E-10 Verdict — **CERRADO / CONFORME**

Caso pedido: `CurrentWeight = 0,15`, `MaxWeight = 0,50`. Escenario propio con `μ_A000 = 0,40` (frente a 0,03–0,09; sin tope el optimizador lo subiría muy por encima de 0,15).

| Causa | Cota compilada A000 | Continua GROSS/NET × RISK_AVERSION/TARGET_RETURN | `PROJECTED_WEIGHTS` (candidatos / puntos globales) | `QP_UTILITY` (candidatos / puntos globales) | Validador (cota abierta a 1,0, `w = 0,25`) |
|---|---|---|---|---|---|
| `EligibleFlag = False` | [0; 0,15] | 0,15 (4/4) | 0,15 / 0,15 | 0,15 (+4·10⁻¹⁰ de tolerancia OSQP) / 0,15 | **rechaza** `NON_BUYABLE_POLICY:A000:no_increase` |
| `LiquidityFlag = False` | [0; 0,15] | 0,15 (4/4) | 0,15 / 0,15 | ídem | rechaza |
| `LiquidityFlag` desconocido, política `EXCLUDE` | [0; 0,15] | 0,15 (4/4) | 0,15 / 0,15 | ídem | rechaza |
| Fuera del `InvestmentUniverse` | [0; 0,15] | 0,15 (4/4) | 0,15 / 0,15 | ídem | rechaza |

* **Independencia del validador:** el contrato se evalúa desde `rule.current_weight` (dato de estado), no desde `compiled.upper`; con `upper` abierto a 1,0 el validador sigue rechazando el aumento. Reserva (igual que E-09, aceptada): la **existencia** de la regla la decide el compilador con el mismo predicado `purchase_block_reasons`.
* **E-09 conserva su precedencia** (`w_current = 0,15`, `RestrictedAssetFlag` y `EligibleFlag = False`, liquidez activa): `HOLD_OR_REDUCE` [0; 0,15], `FREEZE_WEIGHT` [0,15; 0,15], `FORCE_LIQUIDATE` [0; 0]; 0 reglas E-10 duplicadas y 1 regla E-09.
* **Caso adversarial E-10/E-11:** `w_current = 0,10`, capacidad 0,20, `EligibleFlag = False` ⇒ `upper = 0,10` (la capacidad 0,20 queda registrada sin efecto).
* Activo nuevo no elegible en composición explícita: peso máximo ≈ 0 (cubierto por `test_non_buyable_pipelines.py`); el `CandidateEngine` no lo introduce.

Ninguna ruta permite aumentar una posición no comprable.

## 3. E-11 / ADV-NAV Verdict — **CONFORME**

* Fórmula `Capacity = Participation × ADVNotionalPerDay × LiquidationDays / NAV` (`constraints/liquidity.py`), única implementación consumida por compilador y `CandidateEngine`; comprobación dimensional documentada en el módulo: `[1]·[divisa/día]·[día]/[divisa] = adimensional`. Verificada a mano: `2·10⁷ · 0,10 · 5 / 10⁸ = 0,10`.
* Posición nueva `w ≤ capacidad`; existente `w ≤ max(w_current, capacidad)` (protegida: no fuerza venta, no permite crecer). Solo limita tamaño de posición; no garantiza ejecutabilidad de una venta (declarado en `MASTER_SPEC` E-11, `ARCHITECTURE`, docstring).
* `enabled = false` por defecto; con `enabled = true` participación y días obligatorios; NAV `> 0` y finito.

## 4. F-1 Verdict — **CERRADO**

Reproducción propia (compilación directa sobre `AssetMetadata`, sin loader):

| Caso | Resultado |
|---|---|
| `NOTIONAL_PER_DAY`, ADV 2·10⁷ | admitido, capacidad **0,10** |
| `SHARES_PER_DAY` | rechazado: «no es un importe monetario y no se convierte implícitamente…» |
| `CONTRACTS_PER_DAY` | rechazado (ídem) |
| unidad ausente (`None`) | rechazado: «sin unidad de ADV (ADVUnit); debe ser NOTIONAL_PER_DAY» |
| unidad desconocida (`"FOO"`) | rechazado en la propia construcción de `AssetMetadata` (`DataValidationError`); el cargador la rechaza con `INVALID_VALUE` (`ADVUnit` fuera de `AdvUnit.__members__`) |
| ADV `-1`, `NaN`, `inf`, `None` | rechazado |
| `ADVSource` ausente | rechazado; con valor `"X"` se conserva en `LiquidityCapRule.adv_source` |

Enum `AdvUnit` (`NOTIONAL_PER_DAY`, `SHARES_PER_DAY`, `CONTRACTS_PER_DAY`) en `models/enums.py`. No existe conversión de títulos/contratos a importe (no hay precio ni política de valoración aprobados). **No depende exclusivamente del loader:** las llamadas directas a `ContinuousFrontierEngine`, `CandidateEngine` y `GlobalCandidateFrontierEngine` con unidad en títulos o divisas ausentes rechazan (tests `test_the_*_rejects_a_bad_contract`), y `AssetMetadata.__post_init__` impide construir un `adv_unit` que no sea `AdvUnit`. Mutante «sin validación de unidad»: detectado (§12).

## 5. F-2 Verdict — **CERRADO**

| Caso | Resultado |
|---|---|
| ambas divisas ausentes | rechazado («no se supone que coincidan») |
| solo `NAVCurrency` ausente / solo `ADVCurrency` ausente | rechazado (ambos) |
| ambas iguales (EUR/EUR) | admitido, sin FX, capacidad 0,10 |
| distintas (USD → EUR) con FX explícito 0,90 | `ADV = 10⁸ USD ⇒ 9·10⁷ EUR`; capacidad **0,45** (= `0,10·9·10⁷·5/10⁸`); orientación *unidades de NAVCurrency por unidad de ADVCurrency* |
| FX ausente | rechazado (pide el par explícito `USD->EUR`) |
| par inverso (`EUR->USD = 1/0,9`) | **rechazado**, no se invierte automáticamente |
| FX `0`, `-1`, `NaN`, `inf` | rechazado en el constructor de `FxRate` (`ConfigError`) |

No se infiere igualdad por ausencia; no se inventa ningún tipo de cambio; no se mezclan divisas incompatibles (comparación exacta de etiquetas). `PortfolioSpec.nav_currency` valida texto no vacío.

## 6. F-4 Verdict — **CERRADO** (con una excepción documentada, ver §17 O-2)

Activo `A000` restringido con `w_current = 0,15`, liquidez activa, bajo las **tres políticas** E-09 × tres defectos de datos (`ADV=None`, `ADVUnit=None`, `ADVCurrency=None`): **9/9 rechazados** con diagnóstico explícito tanto en el compilador como en `ContinuousFrontierEngine`; `CandidateEngine` lo rechaza al iniciar. Ya no existe omisión silenciosa: el bloque de liquidez del compilador se aplica a todo activo de la composición (`compiler.py`, `if constraint_set.liquidity.enabled:` fuera de la rama restringida). Mutante «omitir ADV en restringidos»: detectado.

Interacción E-09/E-10/E-11: `w=0,10`, capacidad 0,20, no elegible ⇒ máximo 0,10 (§2); topes de E-09/E-10 ya son `≤ max(w_current, capacidad)`, así que la semántica de E-09 no cambia.

## 7. F-6 Verdict — FEA-006 y CON-012 — **CERRADO; pueden mantenerse `VALIDATED`**

Frontera continua con causas reproducidas antes del solver (`pre_check_feasible = False`, sin llamar al solver):

* `LIQUIDITY_CAPS_BELOW_BUDGET`: «Σ upper = 0.2 < presupuesto 1.0 con topes ADV/NAV vinculantes: **A000 (tope 0.1), A001 (tope 0.1)**».
* `LIQUIDITY_CAP_BELOW_MIN_WEIGHT`: «**A000**: peso mínimo 0.3 > max(w_current 0.0, capacidad ADV/NAV 0.1)».

El diagnóstico identifica los activos; error de datos, infactibilidad y no convergencia son categorías distintas. Se revisaron las rutas programáticas que podrían evitar los controles: compilador, `CandidateEngine._apply_liquidity`, frontera continua y global, validador (que además re-comprueba el contrato de datos de la regla: unidad, divisas, FX, capacidad finita). El único otro uso de `ADV` (`candidates/screening.py`, `universe_data.py`) es una señal heurística de ranking, no una restricción (O-3). Con ello, la salvedad de F-6 de `AUDIT_BLOCK_3_CLOSURE.md` queda resuelta; el estado `VALIDATED` es sostenible.

## 8. F-5 / F-7 / F-8 Review

| ID | Estado | Verificación |
|---|---|---|
| **F-4** (LOW) | **CLOSED** | §6 |
| **F-5** (LOW) | **CLOSED** (documentado) | El `ConstraintHash` cambia respecto al baseline por una variación real del contrato (payload con política de banderas desconocidas + configuración ADV/NAV + cotas E-10/E-11). Documentado en `ARCHITECTURE.md` §3.4 fila 16 con justificación y en `CHANGELOG.md`. Los resultados económicos son idénticos (§13). |
| **F-7** (INFO) | **ACCEPTED_LIMITATION** | E-10 fija `lower = 0` por encima de `MinWeight`/`min_holding_weight` (A-08), como `HOLD_OR_REDUCE`; documentado en la enmienda E-10 (`MASTER_SPEC.md`) y `ARCHITECTURE.md` fila 17. Decisión aprobada. |
| **F-8** (INFO) | **CLOSED** | `feasibility.py` ya formatea con `float(...)!r` (`BOUNDS_CROSSED: A000: lower 0.3 > upper 0.1`, comprobado en la reproducción de §7). |

## 9. CandidateEngine Regression — **CONFORME**

Caso contractual `two_region_problem`: **11 composiciones** generadas, 11 conjuntos de `AssetID` distintos y 11 `CompositionHash` distintos (`composition_hash` sobre `frozenset`, insensible al orden: la lista no está multiplicada por reordenamientos); incluye la composición actual `{A000, A001}` y tamaño objetivo 2. El mutante «sin deduplicación de vecinos» rompe 4 tests de `test_deduplication.py` (reordenar IDs no crea composición nueva; una composición alcanzada por dos padres se evalúa una vez; un ciclo de swaps no reevalúa). Los tests de 1-swap/2-swap, `BeamSearch`, índices global/eligible/local, costes de retirados (`test_liquidation.py`), turnover y estimaciones (`EstimatedUtilityGain`, `EstimatedTransactionCost`) están dentro de los 1039 y pasan. En el escenario H-1 propio, el `CandidateEngine` generó 5 composiciones y respetó E-10/E-11.

## 10. Global Frontier Regression — **CONFORME**

Pipeline `CurrentPortfolio → CandidateEngine → composiciones → Continuous Frontier por composición → unión de puntos válidos → Pareto global` reproducido sobre `two_region_problem`:

| Tratamiento | Candidatas | Puntos válidos (138; 46 duplicados marcados) | Pareto propio (bucles, tolerancia `pareto_tolerance`) | Banderas del motor (válidos no duplicados) | `CompositionID` en la envolvente |
|---|---|---|---|---|---|
| GROSS | 11 | 138 | 64 | 64 — **idénticos** | **6** |
| NET | 11 | 138 | 64 | 64 — **idénticos** | **6** |
| POST_COST_GROSS | 11 | 138 | 64 | 64 — **idénticos** | **6** |

* Cada magnitud se usa por separado (GROSS: retorno bruto; NET/POST_COST: retorno neto); no se mezclan.
* Los duplicados heredan la bandera de su representante (88 banderas en total = 64 + 24 duplicados); es la semántica documentada de `global_frontier.py` y no es un defecto.
* Varias composiciones están realmente no dominadas (6), sin forzarlo; `scope` = `GLOBAL_CANDIDATE_FRONTIER` en los puntos globales y `CONTINUOUS_FRONTIER` en la continua (pipelines separados); `composition_id` coincide con el hash de `asset_ids` en todos los puntos.
* En el escenario H-1 propio los puntos globales con `A000` no superan 0,15 en GROSS/NET-`PROJECTED_WEIGHTS` ni `QP_UTILITY`.

## 11. Test Evidence

* Suite completa: **1039 passed, 0 failed, 0 skipped** (123,77 s). Coincide con lo declarado. La ejecución inicial fue correcta a la primera; no hubo fallo de `tests/property/test_invariants.py`.
* 51 ficheros históricos de B1/B2 (`git ls-tree block2-validated`): **560 passed**.
* Subconjunto usado para mutantes (constraints, candidates, validation, global Pareto, integration, config): **585 passed** sobre la copia sin mutar (control base).
* Diff de tests preexistentes: 7 ficheros, 111 inserciones y 22 borrados. Los borrados son el cambio de firma de `build_constraint_set(..., None)` → nuevo argumento, y la reestructuración de `test_architecture_rules.py` (grafo de capas ampliado con `candidates` y `parallel`; se retiran de la lista de módulos futuros solo los que implementa B3 — `candidates`, `frontiers/global_frontier.py`, `constraints/integer.py`, `parallel/determinismo` — y **siguen prohibidos** `scenarios`, `staging`, `persistence`, `cache`, `engine.py`, `constraints/conic.py`, `parallel/{batching,shared_data,worker,executor,threading_control}.py`, `metrics/cvar_metric.py`, backends MIQP/Clarabel). Ninguna aserción debilitada, ninguna tolerancia tocada. `constraints/integer.py` y `parallel/determinism.py` están expresamente permitidos en el bloque 3 por `IMPLEMENTATION_PLAN.md` (§B3), con alcance limitado.
* Los valores esperados de los tests específicos son constantes escritas a mano (0,10; 0,45; 90 EUR; 0,15), no calculadas con el código bajo prueba; los tests de pipeline usan oráculos independientes (LP de HiGHS en `test_known_solver_status_cases.py`, bucles explícitos para Pareto).

## 12. Mutation Evidence — **7/7 detectados** (copia aislada; restaurada tras cada mutante; base 585 passed)

| # | Mutante | Resultado | Tests que lo matan |
|---|---|---|---|
| M1 | Eliminar validación de `AdvUnit` (`check_adv_unit` devuelve siempre `NOTIONAL_PER_DAY`) | **KILLED** | 7 (`SHARES_PER_DAY`, `CONTRACTS_PER_DAY`, unidad ausente, frontera continua/candidatos/global con unidad en títulos) |
| M2 | Aceptar divisas ausentes (ambas `None` ⇒ se admite) | **KILLED** | 5 (`test_both_currencies_absent…`, continua/candidatos/global) |
| M3a | Quitar el control `LIQUIDITY_CAP` del `SolutionValidator` | **KILLED** | 5 |
| M3b | Quitar el control `NON_BUYABLE_POLICY` del `SolutionValidator` | **KILLED** | 6 (las 4 causas + 2) |
| M3c | Quitar la re-comprobación independiente del contrato de datos del validador | **KILLED** (1 test: `test_the_validator_detects_a_rule_whose_data_contract_is_violated`) | 1 |
| M4 | Omitir la validación ADV de activos restringidos (F-4) | **KILLED** | 6 (3 políticas E-09 + precedencia) |
| M5 | Desactivar la deduplicación de vecinos (`if digest in visited` → `if False`) | **KILLED** | 4 (`test_deduplication.py`) |

Nota de método: mi primera versión de M3c solo mutaba un argumento de `record(...)` (el valor) y sobrevivió porque el exceso `inf` independiente seguía marcando la violación (mutante equivalente, no debilidad del test). Se rehízo eliminando el bloque completo de la comprobación y quedó detectado. La cobertura de M3c depende de un único test; suficiente pero estrecha (O-5).

## 13. Baseline Regression (B1/B2) — **SIN REGRESIÓN**

* Comparación directa `block2-validated` (extracción `git archive`) frente al código actual: 4 configuraciones (sin política y `HOLD_OR_REDUCE`/`FREEZE_WEIGHT`/`FORCE_LIQUIDATE` con activo restringido) × 3 tratamientos de coste × 2 métodos de frontera × 20 puntos = **480 puntos**, con costes de compra/venta y un activo que sale de la composición: estado del solver, `is_valid_solution`, pesos (hexadecimal), retorno bruto, retorno neto, turnover, coste de transacción y volatilidad — hash SHA-256 **idéntico** (`f71aa2d4…c714`); 480 `OPTIMAL`, 480 válidos en ambos.
* Módulos tocados del motor continuo: `compiler.py` (reglas E-10/E-11 añadidas; `_apply_policy` y la rama restringida intactas), `constraint_set.py`, `feasibility.py`, `solution_validator.py` (dos checks nuevos; `_bounds` vectorizado), `continuous_frontier.py` (+1 línea). E-10/E-11 justifican los cambios de restricciones y `ConstraintHash`; no aparece ninguna regresión económica no documentada.

## 14. F-3 Inherited Numerical Issue — **ABIERTA (heredada de B2, incidencia independiente)**

Reproducción en **ambos árboles** (`block2-validated` extraído y rama actual), 7 instancias `(n, semilla)` de `tests/property/test_invariants.py::frontier_problems` × 3 tratamientos × 2 métodos (solo `TARGET_RETURN_GRID` falla):

| Instancia | Tratamiento | Puntos no válidos | Estado del solver | Clasificación |
|---|---|---|---|---|
| (2,84), (2,184), (2,193) | GROSS y POST_COST_GROSS | 18/20 | `INFEASIBLE` | infactibilidad **numérica incorrectamente declarada** (el oráculo LP de `test_known_solver_status_cases.py` demuestra objetivo < máximo alcanzable) |
| (2,89) | NET | 18/20 | `INFEASIBLE` | ídem |
| (3,67) | NET | 3/20 | `NUMERICAL_ERROR` | factible que no converge |
| (2,159) | NET | 1/20 | `MAX_ITERATIONS` | factible que no converge |
| (2,19) | NET | 1/20 | `OPTIMAL_INACCURATE` | convergencia en el suelo de tolerancia; no se cuenta como válido |

Resultados **idénticos** en `block2-validated` y en la rama actual (mismas 10 filas, mismos estados y recuentos). En todas, ningún punto no óptimo se cuenta como solución válida (`is_valid_solution = False` y sin `weights`/`metrics` válidos); en la frontera global solo participan puntos válidos. No se relajó ninguna tolerancia, no se cambió ningún estado y no se usaron reruns selectivos. Los tests `test_known_solver_status_cases.py` (9) y `test_known_inaccurate_point.py` (2) fijan los casos y pasan; el test de propiedades pasó en mi ejecución inicial (el fallo es esporádico).

* **A. ¿Existía en `block2-validated`?** **Sí**, con exactamente los mismos estados.
* **B. ¿Lo agravó B3?** **No.** Diferencia nula; la frontera global hereda la calidad de cada frontera de composición (puntos inválidos etiquetados, nunca aceptados).
* **C. ¿Puede integrarse B3 manteniendo F-3 como incidencia independiente?** **Sí**, porque se cumplen las cuatro condiciones: preexistente, no agravada, sus puntos no óptimos no se presentan como válidos y hay casos deterministas para remediarla.
* **D. ¿Es obligatorio remediar F-3 antes de B4?** **Sí (recomendado como precondición de B4).** Es una incidencia de robustez del solver del B2 (criterio de infactibilidad de OSQP en rangos de retorno mínimos, escalado/reintento/backend alternativo) y B4 amplía formulaciones y router de solvers; empezar sin resolverla la propagaría a nuevas formulaciones. Puede alternativamente asignarse como primer entregable de B4 con decisión explícita del usuario. **No se declara resuelta.**

## 15. Requirement Reconciliation — **RECONCILIADO**

Recuento propio por script sobre `TRACEABILITY.md` (filas con `RequirementID`, un único estado por fila, sin duplicados):

| Total | VALIDATED | PARTIAL | IMPLEMENTED | NOT_IMPLEMENTED |
|---|---|---|---|---|
| **316** | **183** | **39** | 0 | **94** |

* Coincide con lo declarado. `BEN-009` **no existe** como fila (solo se menciona como retirado); el benchmark y su JSON se conservan como evidencia de `BEN-001`, `BEN-002`, `BEN-006` (los JSON conservan el campo histórico `requirement: BEN-009`, declarado en `BEN-006`).
* `CON-012` y `FEA-006` `VALIDATED` (§7); `CAN-013` `VALIDATED`; `CAN-014` `NOT_IMPLEMENTED` (tabú opcional); `PAR-010`, `CON-010`, `CON-011`, `CON-019`, `REP-003`, `OPT-002` `PARTIAL` (compartidos con B4–B6). Sin avance artificial de B4–B6 (§16).
* E-10 y E-11 registrados como **enmiendas localizadas**: `MASTER_SPEC.md` +29 líneas, **0 borradas** frente al baseline (bloques E-10, E-11 y dos filas del Anexo A); `IMPLEMENTATION_PLAN.md`, `IMPLEMENTATION_PROMPTS.md`, `AUDIT_BLOCK_1.md`, `AUDIT_BLOCK_2.md`, `AUDIT_BLOCK_2_CLOSURE.md`: sin diferencias frente al baseline. `AUDIT_BLOCK_3.md` intacto (md5 `0bb1460e…`, idéntico al registrado en `AUDIT_BLOCK_3_CLOSURE.md`).
* Esta auditoría **no marca ningún requisito** como `VALIDATED` ni modifica estado alguno.

## 16. Git Hygiene

* `git branch --show-current`: `block3-candidate-engine` ✔; `git tag --list block2-validated`: presente ✔.
* `git diff --check`: sin errores de espacios; solo los avisos informativos «LF will be replaced by CRLF» en `CHANGELOG.md` y `portfolio_engine/validation/__init__.py` (no son defectos de contenido).
* `git diff --stat block2-validated`: **37 ficheros modificados, 1719 inserciones, 179 borrados**; `--name-status`: 37 × `M` (ninguno borrado ni renombrado). Sin commit alguno posterior al baseline (los 5 commits del log son los históricos).
* Sin seguimiento: **74 ficheros** (`git ls-files --others --exclude-standard`): 4 informes `.md`, 3 scripts de benchmark, 2 JSON de resultados de benchmark (`candidate_engine_*.json`, evidencia declarada), módulos de B3 (`candidates/`, `parallel/`, `constraints/{integer,liquidity}.py`, `frontiers/{candidate_evaluator,global_frontier}.py`, `models/{composition,purchasability}.py`, `outputs/candidate_*`, `validation/composition_validator.py`, `config/candidate_config.py`, `benchmark/candidate_suite.py`) y tests/fixtures. Sin binarios no previstos (los únicos no `.py`/`.md` son los 2 JSON), sin ficheros temporales (`.tmp`, `.log`, `.bak`, etc.), sin secretos (búsqueda de `api_key`/`secret`/`password`/claves privadas en `.py/.toml/.json`: sin coincidencias).
* Sin código prematuro B4–B6: `portfolio_engine/` contiene solo `candidates`, `parallel/determinism.py` (semillas y tie-break; el paralelismo real es B5), `constraints/integer.py` (representación para la heurística, sin MIP; MIQP es B4) y `frontiers/global_frontier.py`, todos permitidos por `IMPLEMENTATION_PLAN.md` para B3; no existen `scenarios/`, `staging/`, `persistence/`, `cache/`, `engine.py`, `conic.py`, `mixed_integer_backend.py`, `clarabel_backend.py`; el test de arquitectura lo verifica y pasa.
* Informes históricos intactos (§15). El repositorio principal no se modificó en esta auditoría salvo la creación de este informe (mis mutantes se aplicaron solo a la copia del scratchpad).

## 17. Residual Limitations

Ningún hallazgo del Bloque 3 queda **abierto y bloqueante**. Clasificación de F-1…F-8 de `AUDIT_BLOCK_3_CLOSURE.md`:

| ID | Sev. previa | Clasificación final |
|---|---|---|
| F-1 | HIGH | **CLOSED** (§4) |
| F-2 | HIGH | **CLOSED** (§5) |
| F-3 | MEDIUM | **OPEN_NON_BLOCKING** para la integración de B3 (heredada de B2; obligatoria antes de B4, §14) |
| F-4 | LOW | **CLOSED** (§6; excepción O-2) |
| F-5 | LOW | **CLOSED** (documentado, §8) |
| F-6 | MEDIUM | **CLOSED** (§7) |
| F-7 | INFO | **ACCEPTED_LIMITATION** (§8) |
| F-8 | INFO | **CLOSED** (§8) |

**Hallazgo abierto: F-3** — Severidad MEDIUM. *Evidencia:* §14 (tabla y `tests/unit/frontiers/test_known_solver_status_cases.py`, `test_known_inaccurate_point.py`, `tests/property/test_invariants.py`). *Reproducción:* generador `(n, semilla)` de `frontier_problems` con `ContinuousFrontierEngine(config).solve(problema, tratamiento, TARGET_RETURN_GRID)`; mismos resultados en `block2-validated`. *Impacto:* fallo esporádico de la suite de propiedades y, en instancias casi degeneradas, hasta 18 de 20 puntos de una frontera de composición sin solución válida (bien etiquetados; ninguno aceptado), lo que empobrece la frontera de esa composición y, por herencia, la global. Sin corrupción financiera. *Decisión pendiente (usuario):* remediación numérica independiente (recomendada) antes de B4, o asignarla expresamente como primer entregable de B4.

**Observaciones nuevas no bloqueantes (no numeradas en informes previos):**

* **O-1 (INFO, documentación).** F-3 solo consta como pendiente en `CHANGELOG.md` (línea 936) y en los informes de remediación/auditoría; no figura en `TRACEABILITY.md` ni `ARCHITECTURE.md`. Conviene añadir una nota de estado (p. ej. en `SOL-002`/`VAL-001`) para que no se pierda antes de B4. *Decisión pendiente:* si se desea registrarlo.
* **O-2 (LOW, ACCEPTED_LIMITATION).** El compilador no exige `ADV` a una posición actual que **sale** de la composición (venta completa; §"Excepción documentada" de `REMEDIATION_BLOCK_3_CLOSURE.md`). Reproducido: `A000` (restringido o no) con `ADV = None` fuera de la composición compila (`upper = [1, 1]`). El `CandidateEngine` sí valida todas las posiciones actuales al iniciar. Aceptable (no hay tope que aplicar); una composición explícita pasada directamente a la frontera continua no valida el `ADV` de lo que sale.
* **O-3 (INFO).** `candidates/screening.py` usa `snapshot.adv` (crudo, sin comprobación de unidad) como señal heurística de ranking incluso con la restricción ADV/NAV desactivada; no genera ninguna restricción ni validez, solo orden de exploración, y su peso es configurable.
* **O-4 (INFO).** Como en E-09, la existencia de las reglas `non_buyable`/`liquidity` la decide el compilador; el validador las comprueba de forma independiente desde los datos de la regla pero no puede detectar una regla que el compilador no hubiera emitido (cubierto por el test de acuerdo compilador ↔ `EligibilityFilter`).
* **O-5 (INFO).** La re-comprobación independiente del contrato de datos del validador (M3c) está cubierta por un solo test. Suficiente, pero estrecho.

Limitaciones ya declaradas y que se mantienen: sin límite de volumen negociable por operación (E-11); benchmark de B3 generado sobre árbol sin commit (regenerar tras el commit); validación solo con Python 3.13 / Windows 11 / `osqp` y `scipy` fijados; `ruff format --check` cuenta 252 ficheros frente a los 251 del informe del implementador (todos conformes; sin consecuencia).

## 18. Final Closure Decision

**PASS.** Criterios de §16 del encargo:

| Criterio | Cumplido |
|---|---|
| H-1/E-10 cerrado (todas las rutas, 4 causas, `PROJECTED_WEIGHTS` y `QP_UTILITY`, validador independiente) | ✔ |
| F-1 cerrado (unidad; sin conversión implícita; llamadas directas) | ✔ |
| F-2 cerrado (divisas obligatorias; FX explícito, orientación fija, sin inversión ni inferencia) | ✔ |
| F-4 cerrado (restringidos validan datos ADV; sin omisión silenciosa) | ✔ |
| F-6 cerrado (FEA-006/CON-012 `VALIDATED` sostenible; sin rutas que eviten controles) | ✔ |
| Sin regresiones materiales de B1/B2 (480 puntos bit a bit; 560 tests históricos) | ✔ |
| `CandidateEngine` multicomposición (11, deduplicadas, sin reordenamientos) | ✔ |
| Global Candidate Frontier correcta (6 `CompositionID` no dominados; Pareto independiente coincide) | ✔ |
| Trazabilidad reconciliada (316 / 183 / 39 / 94; BEN-009 ausente; E-10/E-11 localizadas) | ✔ |
| Tests y mutantes críticos con evidencia suficiente (1039 passed; 7/7 mutantes) | ✔ |
| Sin hallazgos abiertos bloqueantes del Bloque 3 | ✔ |
| F-3 como incidencia heredada independiente: preexistente, no agravada, puntos no óptimos no válidos, casos deterministas, pendiente antes de B4 | ✔ |

**Recomendación:** el Bloque 3 puede integrarse en `main` (commit/merge a decisión del usuario, no realizados aquí). Antes de iniciar el Bloque 4 debe decidirse la remediación de F-3 (recomendado: remediar primero, de forma independiente y sin relajar tolerancias) y regenerar el benchmark de B3 sobre el árbol ya comprometido.

---

BLOCK_3_FINAL_AUDIT_SUMMARY

Branch:
block3-candidate-engine (baseline `block2-validated` presente)

H-1 / E-10:
CERRADO. Máximo de A000 = 0,15 = w_current en compilador, factibilidad, frontera continua (GROSS/NET × 2 métodos), CandidateEngine (PROJECTED_WEIGHTS y QP_UTILITY), frontera global y validador independiente; 4 causas (EligibleFlag, LiquidityFlag, liquidez desconocida EXCLUDE, fuera del InvestmentUniverse); E-09 conserva precedencia.

F-1:
CERRADO. Solo NOTIONAL_PER_DAY; SHARES/CONTRACTS, unidad ausente o desconocida y ADV negativo/no finito rechazados; ADVSource conservada; sin conversión implícita; llamadas directas también validan.

F-2:
CERRADO. ADVCurrency y NAVCurrency obligatorias (ausentes/una sola ⇒ error); FX explícito, orientación NAVCurrency por ADVCurrency (100 USD × 0,90 = 90 EUR), par inverso y FX inválido rechazados.

F-4:
CERRADO. Restringidos con ADV incompleto rechazados bajo HOLD_OR_REDUCE, FREEZE_WEIGHT y FORCE_LIQUIDATE (9/9); adversarial 0,10/0,20/no elegible ⇒ 0,10. Excepción documentada: posición que sale de la composición (O-2).

F-6:
CERRADO; sin rutas que eviten los controles.

FEA-006:
VALIDATED sostenible. LIQUIDITY_CAP_BELOW_MIN_WEIGHT y LIQUIDITY_CAPS_BELOW_BUDGET detectados antes del solver, con activos identificados.

CON-012:
VALIDATED sostenible.

CandidateEngine:
CONFORME. 11 composiciones únicas (11 hashes), incluye la actual, deduplicación verificada por mutante.

Global Candidate Frontier:
CONFORME. 6 CompositionID no dominados en GROSS/NET/POST_COST_GROSS; Pareto independiente idéntico a las banderas (64 puntos); pipelines continua/global separados.

Tests passed:
1039 (suite completa); 560 en los 51 ficheros históricos de B1/B2; 585 en el subconjunto de mutantes (control base).

Tests failed:
0. mypy --strict: PASS (124 ficheros). ruff check: PASS. ruff format --check: PASS (252 ficheros).

Mutants detected:
7/7 (AdvUnit, divisas ausentes, validador LIQUIDITY_CAP, validador NON_BUYABLE, contrato de datos del validador, ADV en restringidos, deduplicación de vecinos).

Requirement totals:
316 RequirementID: 183 VALIDATED, 39 PARTIAL, 0 IMPLEMENTED, 94 NOT_IMPLEMENTED (recontado por script). BEN-009 ausente.

Inherited F-3 status:
ABIERTA e idéntica en block2-validated (mismos estados en 10 combinaciones); no agravada por B3; puntos no óptimos nunca válidos; casos deterministas presentes; no resuelta; remediación pendiente antes de B4.

Open blocking findings:
Ninguno.

Open non-blocking findings:
F-3 (MEDIUM, heredada; obligatoria antes de B4); O-1 (F-3 no consta en TRACEABILITY/ARCHITECTURE); O-2 (ADV no exigido a posiciones que salen; ACCEPTED_LIMITATION); O-3 (ADV crudo como señal de ranking); O-4 (existencia de reglas decidida por el compilador); O-5 (M3c cubierto por un solo test); F-7 ACCEPTED_LIMITATION.

Git status:
Rama block3-candidate-engine; 37 ficheros modificados (1719+/179−) y 74 sin seguimiento; sin commit, merge, push, tag ni PR; `git diff --check` sin errores de contenido; sin secretos ni binarios no previstos; sin código B4–B6; informes históricos intactos. Único fichero creado: AUDIT_BLOCK_3_FINAL_CLOSURE.md.

Closure recommendation:
Integrar el Bloque 3 en main; decidir y ejecutar la remediación independiente de F-3 antes de iniciar el Bloque 4; regenerar el benchmark de B3 tras el commit.

AUDIT_BLOCK_3_FINAL_CLOSURE_STATUS = PASS
