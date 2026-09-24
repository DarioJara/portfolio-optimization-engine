# AUDIT_BLOCK_3_CLOSURE — Auditoría independiente de cierre del Bloque 3

**Rama:** `block3-candidate-engine` · **Baseline:** tag `block2-validated` (`6af836c`) · **Fecha:** 2026-09-24
**Declaración auditada:** `BLOCK_3_REMEDIATION_STATUS = PASS` (`REMEDIATION_BLOCK_3.md`).
**Restricciones cumplidas:** no se modificó código ni documentación; único fichero creado en el repositorio: este. Sin commit, merge, push, tag ni PR; sin avance al Bloque 4. Todos los experimentos (adversariales, mutantes sobre una **copia** del árbol, comparación con el baseline extraído con `git archive`) se ejecutaron desde el scratchpad de la sesión. Las ejecuciones de `pytest` pueden haber regenerado cachés ignoradas (`__pycache__`, `.hypothesis`), no seguidas por git.
**Método:** lectura de los documentos de gobierno y de los diffs (`compiler`, `constraint_set`, `feasibility`, `solution_validator`, `continuous_frontier`, `liquidity`, `candidate_engine`, config); ejecución propia de las cuatro herramientas; escenario adversarial propio (5 activos, `w_current = 0,15`, `MaxWeight = 0,5`, `μ_A000 = 0,40`, distinto del del implementador); 16 mutantes propios; comparación bit a bit de la frontera continua frente a `block2-validated`; Pareto recalculado con bucles explícitos; reproducción de los casos numéricos con un LP independiente.

---

## 1. Resumen ejecutivo

La remediación es técnicamente sólida y las evidencias del implementador se reproducen: H-1 está cerrado en todas las rutas probadas, E-10 y E-11 se comportan como se decidió (incluido el caso adversarial `w = 0,10`, capacidad `0,20`, no elegible ⇒ máx. `0,10`), la frontera continua del B2 es **idéntica bit a bit** al baseline, los 16 mutantes se detectan y la trazabilidad cuadra (316 / 183 / 39 / 94). **No se puede dar un PASS limpio** por dos brechas de contrato de datos en E-11 que el propio diseño deja abiertas y que afectan a que `CON-012`/`FEA-006` se declaren `VALIDATED`:

* **F-1 (HIGH):** el contrato no define qué representa `ADV` (importe monetario o número de títulos) y el código lo usa directamente como importe; no hay validación ni conversión de unidades.
* **F-2 (HIGH):** si `ADVCurrency` y `NAVCurrency` faltan **ambas**, se asume que coinciden; no existe ningún contrato aguas arriba que garantice esa normalización (reproducido incluso con activos cotizados en otra divisa).

Además, la incidencia numérica heredada de B2 (F-3) es real, reproducible y más amplia de lo que sugiere «un punto»; debe abrirse una remediación independiente antes del Bloque 4.

`AUDIT_BLOCK_3_CLOSURE_STATUS = PASS_WITH_CHANGES` (ver §14).

### Comprobaciones ejecutadas de verdad

| Comando / experimento | Resultado |
|---|---|
| `pytest -q -p no:cacheprovider` | **1003 passed in 118,85 s** (0 failed, 0 skipped) |
| `mypy --strict portfolio_engine` | `Success: no issues found in 124 source files` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `250 files already formatted` (solo `--check`) |
| Escenario adversarial H-1 propio (4 causas × frontera GROSS/NET × `PROJECTED_WEIGHTS`/`QP_UTILITY` × frontera global × validador) | máximo de `A000` = **0,15** en todas las rutas (= `w_current`); validador rechaza 0,25 con la cota compilada abierta |
| 16 mutantes propios sobre una copia | **16/16 detectados** (§11) |
| Frontera continua B2 vs `block2-validated` (6 tratamiento×método, 6 activos, costes) | estados, pesos (hexadecimal), retorno neto, turnover y coste **idénticos**; solo cambia `ConstraintHash` (F-5) |
| Pareto global recalculado con bucles explícitos (`two_region_problem`, 3 tratamientos) | coincide con las banderas en los 3; 11 composiciones candidatas, 6 `CompositionID` en la envolvente |
| Casos numéricos B2 (7 instancias) | reproducidos; ningún punto es verdaderamente infactible (F-3) |
| `AUDIT_BLOCK_3.md` | intacto (mismo contenido que en mi primera lectura; `md5 0bb1460e…` antes y después) |

---

## 2. Cierre de H-1 y veredicto E-10

**Veredicto: H-1 CERRADO. E-10: CONFORME.**

Reproducción independiente (escenario propio; `w_current = 0,15`, `MaxWeight = 0,5`, `μ_A000 = 0,40` frente a 0,03-0,09):

| Causa | Cota compilada | Factibilidad previa | Frontera continua GROSS / NET | `PROJECTED_WEIGHTS` (estim. / puntos globales) | `QP_UTILITY` | Validador (cota abierta, `w = 0,25`) |
|---|---|---|---|---|---|---|
| `EligibleFlag = False` | 0,15 | factible | 0,15 / 0,15 | 0,15 / 0,15 | 0,15 / 0,15 | **rechaza** (`NON_BUYABLE_POLICY`) |
| `LiquidityFlag = False` | 0,15 | factible | 0,15 / 0,15 | 0,15 / 0,15 | 0,15 / 0,15 | rechaza |
| `LiquidityFlag` desconocido (`EXCLUDE`) | 0,15 | factible | 0,15 / 0,15 | 0,15 / 0,15 | 0,15 / 0,15 | rechaza |
| Fuera del `InvestmentUniverse` | 0,15 | factible | 0,15 / 0,15 | 0,15 / 0,15 | 0,15 / 0,15 | rechaza |

* **Activo nuevo no elegible** (no en cartera, en composición explícita): peso máximo `6e-22` ≈ 0; el `CandidateEngine` no genera ninguna composición con él (0 de 6).
* **Independencia del validador:** `SolutionValidator._non_buyable` toma `rule.current_weight` (dato de estado) y no `compiled.upper`; con `upper` sustituido por 1 sigue rechazando. Reserva legítima: la **existencia** de la regla la decide el compilador (mismo predicado `purchase_block_reasons`); si el compilador no emitiera la regla, el validador no la vería. Es el mismo patrón que E-09 (`restricted_rules`) y está cubierto por el test de acuerdo compilador ↔ `EligibilityFilter`; no lo considero hallazgo.
* **Precedencia de E-09** con activo restringido: `HOLD_OR_REDUCE` `[0; w_current]`, `FREEZE_WEIGHT` `[w; w]`, `FORCE_LIQUIDATE` `[0; 0]`, sin regla E-10 duplicada.
* **Ninguna ruta** permite incrementar una posición no comprable en lo probado (compilador, factibilidad, continua, candidatos en ambos modos, frontera global, validador, screening con `weight_cap`).

## 3. Veredicto E-11 (ADV/NAV)

**Veredicto: CONFORME en su lógica financiera; NO conforme en el contrato de datos (F-1, F-2).**

* Fórmula `p·ADV·días/NAV` verificada a mano (`ADV = 2e7`, `p = 0,1`, `días = 5`, `NAV = 1e8` ⇒ 0,10; con FX `4e7 USD × 0,5 = 2e7 EUR` ⇒ 0,10).
* Posición nueva `w ≤ capacidad`; existente `w ≤ max(w_current, capacidad)`. Con `w_current = 0,20` y capacidad 0,10 el tope es 0,20: **no fuerza la venta** (límite inferior 0). No permite crecer por encima de 0,20 (validador y frontera).
* **Adversarial pedido:** `w_current = 0,10`, capacidad 0,20 (`ADV = 4e7`), `EligibleFlag = False` ⇒ `upper = 0,10` (no 0,20): E-10 prevalece (`rule.capacity = 0,20` queda registrada, sin efecto).
* `FREEZE_WEIGHT` (`[0,15; 0,15]`) y `FORCE_LIQUIDATE` (`[0; 0]`) mantienen su semántica con la liquidez activa (activo restringido con capacidad 0,10 y `w_current = 0,15`).
* No confunde el límite de posición con la ejecutabilidad de una orden: la especificación (E-11), `ARCHITECTURE.md`, README y el docstring lo declaran expresamente.

## 4. Unidades y divisas — revisión prioritaria

### F-1 — HIGH — El significado de `ADV` no está definido y la fórmula supone importe monetario sin comprobarlo

* **Evidencia:** `MASTER_SPEC.md` solo lista la columna `ADV` (sin unidad); E-11 exige «misma divisa» pero no dice que `ADV` sea un importe. `portfolio_engine/candidates/universe_data.py:49` lo documenta como «volumen medio diario» (ambiguo: puede ser número de títulos). `liquidity_capacity` usa `asset.adv` tal cual; no existe campo de unidad, precio ni conversión de títulos a importe (el dataset de precios tiene `Volume` pero no se cruza con `ADV`).
* **Impacto:** si el origen entrega `ADV` en unidades, la capacidad sale con dimensiones erróneas (`títulos·días/NAV` en lugar de fracción de cartera): topes arbitrariamente holgados o restrictivos sin ningún aviso. Es una restricción de riesgo de liquidez potencialmente incorrecta por construcción de datos.
* **Reproducción:** cualquier universo con `ADV = 1e6` (títulos) y `NAV` en euros produce `capacidad = 0,1·1e6·5/NAV` sin ninguna comprobación (basta `liquidity_problem` con `ADV` en unidades).
* **Recomendación:** enmendar E-11/A-11 para fijar que `ADV` es un **importe monetario diario** y añadir un campo/columna de unidad (o un contrato de carga que lo garantice); rechazar `ADV` declarado en títulos salvo conversión validada con precio explícito.

### F-2 — HIGH — Con `ADVCurrency` y `NAVCurrency` ausentes se asume que coinciden

* **Evidencia:** `constraints/liquidity.py::_fx_rate`: `if adv_currency is None and nav_currency is None: return None  # se asume la misma divisa`. No existe contrato verificable aguas arriba: los cargadores solo copian `ADVCurrency`/`NAVCurrency` si existen (columnas opcionales, `Text`), y ni `MASTER_SPEC` ni `ARCHITECTURE` garantizan que `ADV` y `NAV` vengan normalizados. La propia columna `Currency` del activo se ignora.
* **Impacto:** igualdad de divisas basada exclusivamente en campos ausentes (lo que el enunciado de esta auditoría prohíbe). Con la restricción activada, un `ADV` en USD frente a un `NAV` en EUR se usa sin conversión y sin aviso.
* **Reproducción:** universo con `Currency = USD` en todos los activos, `ADV = 2e7`, `NAV = 1e8` sin divisas declaradas, `enabled = true` ⇒ «capacity A000 = 0.1, fx None» aplicado en silencio.
* **Recomendación:** con `enabled = true`, exigir **siempre** `NAVCurrency` y `ADVCurrency` declaradas (error si faltan) o una divisa de valoración explícita en la configuración; documentar que sin ellas no se aplica ADV/NAV (con error, no en silencio).

### Auditoría de `fx_rates` (conforme)

* Orientación: `rate = unidades de to_currency por unidad de from_currency`; el par se busca **exacto** `(ADVCurrency, NAVCurrency)`; el par inverso no se acepta (probado; mutante «FX invertido» detectado); sin inversión implícita.
* `rate` finito y `> 0` (rechazados `0`, negativos, `NaN`, `bool`); pares duplicados y `from == to` rechazados.
* Las divisas se comparan como texto exacto: `"eur"` frente a `"EUR"` o `" EUR"` provoca error (seguro, sin normalización que pudiera ocultar un desajuste).
* Errores de conversión/datos se propagan como `ConstraintCompilationError` (compilador) y detienen la generación de candidatos al iniciar (`_apply_liquidity`), sin descartar composiciones en silencio.
* No se inventan tipos de cambio en ningún punto del código.

## 5. Configuración

**Veredicto: CONFORME.**

* `enabled = false` ⇒ ninguna regla (probado; incluso con `NAV` ausente); por defecto `enabled = false`, sin valores productivos en el TOML.
* `enabled = true` ⇒ `max_adv_participation` y `liquidation_days` obligatorios (constructor y cargador TOML), `NAV > 0`, `ADV ≥ 0`, todo finito. Rechazados en mi prueba: participación `True`, `"0.1"`, `0`, `>1`, `NaN`; días `True`, `"5"`, `< 1`, `NaN`; `enabled = 1`; `fx_rates` que no sea tupla de `FxRate`.
* Datos ausentes/inválidos con la restricción activa ⇒ error (`NAV` ausente, `ADV` ausente, spec ausente); no se desactiva en silencio, **salvo** el caso F-4 (activo restringido).

## 6. FEA-006 y CON-012

* **Factibilidad previa reproducida:** con `LIQUIDITY_CAPS_BELOW_BUDGET` (dos activos nuevos de capacidad 0,10) y `LIQUIDITY_CAP_BELOW_MIN_WEIGHT` (mínimo 0,30 > 0,10) la frontera continua devuelve `pre_check_feasible = False`, **`solve_count = 0`** (el solver no se invoca) y las causas identifican los activos (`A000 (tope 0.1), A003 (tope 0.1)`; `A000: peso mínimo 0.3 > max(w_current 0.0, capacidad 0.1)`). Los mutantes que apagan `check_liquidity` o la causa de mínimo se detectan.
* **Evidencia frente al estado declarado:** la funcionalidad y los tests justifican `FEA-006` y `CON-012` en lo que la especificación **actual** dice. Pero con F-1/F-2 abiertos, la restricción puede aplicarse con datos de unidad/divisa no verificados; recomiendo que ambas filas conserven `VALIDATED` solo con esa salvedad explícita en `TRACEABILITY.md` o vuelvan a `PARTIAL` hasta cerrar F-1/F-2 (F-6).
* No se confunde el límite de posición con la garantía de ejecución de una venta (conforme).

## 7. Regresión de Bloques 1 y 2

**Veredicto: CONFORME (sin regresión económica).**

* **Tests:** los 51 ficheros del baseline pasan sobre el código actual (dentro de los 1003). Diff de tests preexistentes: 7 ficheros, 111 inserciones y 22 borrados; el único `assert` borrado es una reformulación de `build_constraint_set(...)` con el nuevo argumento; ninguna aserción debilitada, ninguna tolerancia tocada (`test_architecture_rules.py` amplía el grafo como ya auditó `AUDIT_BLOCK_3.md`).
* **Semántica económica del motor continuo:** comparación directa con `block2-validated` (6 combinaciones, 6 activos, costes de compra/venta): estados del solver, `is_valid_solution`, pesos (hex), retorno neto, turnover y coste de transacción **idénticos**. Retornos brutos/netos, turnover, liquidaciones completas y estados del solver no cambian. `CompositionID` idéntico.
* **Módulos tocados:** `compiler.py` (reglas E-10/E-11 solo en la rama de activos no restringidos; la rama restringida y `_apply_policy` intactas), `constraint_set.py` (dos campos nuevos), `feasibility.py` (checks nuevos; las reglas de B2 no se modifican), `solution_validator.py` (dos checks nuevos y `_bounds` vectorizado con equivalencia probada contra el recorrido escalar), `continuous_frontier.py` (+1 línea).
* **F-5 (LOW):** `ConstraintHash` **cambia** respecto a B2 (el payload de `ConstraintSet` incorpora `unknown_liquidity_policy` y `liquidity`) aunque el problema sea el mismo. No hay caché aún (B5), pero el cambio de valores no está listado como tal en `CHANGELOG.md`/`TRACEABILITY.md`.

## 8. CandidateEngine

**Veredicto: CONFORME.** Comprobado por ejecución de la suite y del caso contractual: múltiples composiciones reales (11 en `two_region_problem`, referencia incluida), 1-swap/2-swap y `BeamSearch` (tests de haz y mutantes de auditoría anteriores siguen en verde), deduplicación (mutante `dedup_off` detectado también por mi copia), índices global/local, costes de retirados (`test_liquidation`) y estimaciones etiquetadas como estimaciones. E-10/E-11 se propagan al screening (`weight_cap`), a la cardinalidad (FEA-002) y a las estimaciones vía restricciones compiladas.

## 9. Global Candidate Frontier

**Veredicto: CONFORME.** Caso contractual reproducido: 11 composiciones candidatas y 6 `CompositionID` distintos en la envolvente para GROSS, NET y POST_COST_GROSS. Pareto **recalculado de forma independiente** (dominancia con tolerancia, solo puntos válidos no duplicados): coincide con las banderas de eficiencia en los 3 casos; la frontera continua de la composición actual conserva `scope = CONTINUOUS_FRONTIER` (pipelines separados). Con E-10/E-11 activos, ningún punto global de una composición que contiene el activo protegido supera su tope (§2, §3).

## 10. Calidad de los tests

* **Valores esperados independientes:** constantes escritas a mano (`w_current`, `ADV = 2e7 ⇒ 0,10`, `4e7 USD × 0,5`), oráculo de acuerdo compilador ↔ filtro con conjunto escrito a mano, oráculo escalar para la vectorización de cotas, LP de HiGHS para el caso numérico. No dependen de las funciones bajo prueba.
* **Cobertura de rutas:** los tests de pipeline recorren continua GROSS/NET × 2 métodos, candidatos `PROJECTED_WEIGHTS`/`QP_UTILITY` y frontera global; el test del expansor cubre el cableado del screening (descubierto por un mutante superviviente del propio implementador).
* **Debilidades menores (no bloquean):** los mutantes se ejecutan con `-x` (el recuento «1 failed» no mide cuántos tests matan cada uno); ningún test cubre el caso F-4 (restringido sin `ADV`) ni F-1/F-2 porque el contrato no los define.

## 11. Mutantes (ejecución propia sobre una copia del árbol)

Todos restaurados; 16 de 16 detectados:

| Mutante | Resultado |
|---|---|
| E-10: compilador sin tope | KILLED |
| E-10: validador sin comprobación | KILLED |
| E-10: ignora `InvestmentUniverse` | KILLED |
| E-10: liquidez desconocida permitida | KILLED |
| E-10: `EligibleFlag` ignorado | KILLED |
| E-11: tope duro (`capacidad` en vez de `max(w_current, capacidad)`) | KILLED |
| E-11: compilador sin tope ADV/NAV | KILLED |
| E-11: validador sin comprobación | KILLED |
| E-11: FX ignorado | KILLED |
| E-11: FX invertido (`ADV / fx`) | KILLED |
| E-11: sin `liquidation_days` | KILLED |
| E-11: sin `max_adv_participation` | KILLED |
| E-11: comprobación de datos en `CandidateEngine` apagada | KILLED |
| E-11: `check_liquidity` apagado | KILLED |
| E-11: causa de mínimo apagada | KILLED |
| Deduplicación de vecinos (`if digest in visited` → `if False`) | KILLED |

Los cuatro mutantes ADV/NAV declarados por el implementador (sin tope, tope duro, validador, FX) están incluidos y se detectan.

## 12. Incidencia numérica histórica heredada de B2

### F-3 — MEDIUM — Fronteras `TARGET_RETURN_GRID` casi degeneradas o en el suelo de precisión de OSQP (abierta; heredada de B2)

* **Evidencia:** `tests/property/test_invariants.py::test_every_frontier_point_satisfies_the_financial_invariants` exige `is_valid_solution` en cada punto; `tests/unit/frontiers/test_known_solver_status_cases.py` (9 tests) y `test_known_inaccurate_point.py` (2) fijan 7 instancias `(n, semilla)`. Reproducidas (mismas estadísticas que el implementador):

| Instancia (tratamiento) | Puntos no válidos | Estado | Clasificación (oráculo LP de HiGHS) |
|---|---|---|---|
| (2,84), (2,184), (2,193) — GROSS y POST_COST_GROSS | 18 de 20 cada una | `INFEASIBLE` (solver) | **factible** (objetivo < máximo alcanzable, márgenes 1e-7…2e-5): infactibilidad **numérica incorrectamente declarada** |
| (2,89) NET | 18 de 20 | `INFEASIBLE` (solver y cross-check) | factible, mismo diagnóstico |
| (3,67) NET | 3 | `NUMERICAL_ERROR` | factible que no converge |
| (2,159) NET | 1 | `MAX_ITERATIONS` | factible que no converge |
| (2,19) NET | 1 | `OPTIMAL_INACCURATE` | convergencia en el suelo de `eps = 1e-9`; validación independiente válida (exceso 1,2e-9) |

  Márgenes negativos (objetivo por encima del máximo, es decir, verdadera infactibilidad): **0**.
* **Impacto:** (i) la suite puede fallar de forma esporádica (≈ 0,21 % por ejemplo según la exploración del implementador; el test usa 25 ejemplos; sin semilla ni base de ejemplos fijas); (ii) más relevante que la suite: en las instancias casi degeneradas **18 de los 20 puntos** de una frontera quedan sin solución válida (bien etiquetados, nunca aceptados), lo que empobrece la frontera de una composición y, por herencia, la `GLOBAL_CANDIDATE_FRONTIER`. No hay corrupción financiera: ningún punto inválido cuenta como válido. Confirmado por comparación con `block2-validated`: idéntico en el baseline (no es regresión de B3).
* **Reproducción:** generador de `frontier_problems` con `(n, seed)` de la tabla; `ContinuousFrontierEngine(config).solve(problem, tratamiento, TARGET_RETURN_GRID)`.
* **Recomendación:** **abrir una remediación independiente** (B2/solver: criterio de infactibilidad de OSQP en rangos de retorno mínimos, escalado, reintento con otro backend o tolerancia justificada) **antes de avanzar al Bloque 4**, o incluirla explícitamente como primer entregable de B4 (estados y robustez de solvers). No se han tocado tolerancias ni tests en esta auditoría y **no se declara resuelta**.

## 13. Trazabilidad y gobernanza

* **316** `RequirementID` únicos; **183 `VALIDATED`, 39 `PARTIAL`, 0 `IMPLEMENTED`, 94 `NOT_IMPLEMENTED`** (recontado por script; el resumen por dominio coincide fila a fila). `BEN-009` no existe como fila; el benchmark y su JSON se conservan como evidencia de `BEN-001`, `BEN-002`, `BEN-006`.
* Sin avance de B4–B6. `CON-012` y `FEA-006` en `VALIDATED` (ver F-6).
* **E-10 y E-11** son enmiendas localizadas: `MASTER_SPEC.md` gana solo esos bloques y dos filas del Anexo A (0 líneas borradas frente al baseline); `IMPLEMENTATION_PLAN.md` e `IMPLEMENTATION_PROMPTS.md` sin cambios; ningún contrato no relacionado modificado.
* `AUDIT_BLOCK_3.md` intacto.

---

## 14. Hallazgos residuales

| ID | Severidad | Resumen | Bloquea PASS |
|---|---|---|---|
| **F-1** | HIGH | `ADV` sin unidad definida; se usa como importe monetario sin validar ni convertir | **Sí** |
| **F-2** | HIGH | `ADVCurrency`/`NAVCurrency` ausentes ⇒ se asume misma divisa, sin contrato aguas arriba | **Sí** |
| **F-3** | MEDIUM | Fronteras `TARGET_RETURN_GRID` casi degeneradas: infactibilidad numérica declarada, no convergencia, `OPTIMAL_INACCURATE`; suite con fallo esporádico; heredada de B2 | Requiere remediación independiente antes de B4 |
| **F-6** | MEDIUM | `CON-012` y `FEA-006` `VALIDATED` sin salvedad mientras F-1/F-2 estén abiertos (sobrevaloración de estado) | Sí (se resuelve con la salvedad o con `PARTIAL`) |
| **F-4** | LOW | Con la restricción activa, un activo **restringido** (E-09) sin `ADV` no genera error (se omite su regla porque E-09 prevalece); el dato faltante no se detecta | No |
| **F-5** | LOW | `ConstraintHash` cambia respecto a B2 para el mismo problema (payload ampliado); no registrado como cambio de valores | No |
| **F-7** | INFO | E-10 fija el límite inferior en 0 y prevalece sobre `MinWeight` y `min_holding_weight` (A-08), como `HOLD_OR_REDUCE`; documentado en la enmienda | No |
| **F-8** | INFO | Mensajes de error con `np.float64(...)` (`BOUNDS_CROSSED: lower np.float64(0.3)`); cosmético | No |

Detalle de F-4: **Evidencia:** en `ConstraintCompiler._bounds` el bloque de liquidez está en el `else` de la rama `restricted`. **Reproducción:** política `HOLD_OR_REDUCE`, `A000` restringido con `ADV = None`, `enabled = true` ⇒ compila sin error (`upper = 0,15`). **Impacto:** bajo (no altera el resultado, E-09 es más estricto o igual), pero contradice «datos faltantes ⇒ error» para el conjunto completo de activos.
Detalle de F-5: **Evidencia:** `constraint_hash` de la frontera continua distinto de `block2-validated` con pesos y estados idénticos. **Impacto:** claves de caché del B5 futuras deben partir de esta versión; documentar el cambio.

## 15. Limitaciones y decisiones pendientes

* **Decisión D-A (usuario):** definir que `ADV` es un importe monetario diario y cómo se acredita (campo de unidad o contrato de carga) — F-1.
* **Decisión D-B (usuario):** exigir divisa declarada de `ADV` y `NAV` (o una divisa de valoración explícita en configuración) cuando la restricción está activa — F-2.
* **Decisión D-C (usuario):** abrir remediación independiente de la incidencia de B2 antes del B4, o asignarla al B4 — F-3.
* `CON-012`/`FEA-006`: mantener `VALIDATED` con salvedad o volver a `PARTIAL` hasta cerrar F-1/F-2 — F-6.
* Sin límite de volumen negociable por operación (declarado, fuera de alcance); benchmark de B3 generado sobre árbol sin commit (regenerar tras el commit); validado solo con Python 3.13 / Windows 11 / `osqp 1.1.3` / `scipy 1.18.1`.

---

AUDIT_BLOCK_3_CLOSURE_STATUS = PASS_WITH_CHANGES
