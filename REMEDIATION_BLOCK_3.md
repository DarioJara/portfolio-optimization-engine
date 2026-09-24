# REMEDIATION_BLOCK_3 — Remediación del Bloque 3 tras `AUDIT_BLOCK_3_STATUS = PASS_WITH_CHANGES`

**Rama:** `block3-candidate-engine` · **Baseline:** tag `block2-validated` (commit `6af836c`) · **Fecha:** 2026-09-24
**Alcance:** exclusivamente la remediación del Bloque 3. Sin avance al Bloque 4; sin commit, merge, push, tag ni PR. `AUDIT_BLOCK_3.md` permanece intacto.
**Autoridad:** `MASTER_SPEC.md` (con la enmienda E-10 incorporada por decisión del usuario, D-3).

**Segunda tanda (decisiones funcionales del usuario sobre A-11):** §3 (ADV/NAV, cierre de `FEA-006` y `CON-012`), §8 (casos deterministas del fallo de B2) y §9-§10 actualizados.

Este informe es el detalle de la remediación; el resumen ejecutivo está en la respuesta de la sesión (`BLOCK_3_REMEDIATION_SUMMARY`).

---

## 1. H-1 — posiciones actuales no comprables (E-10)

**Defecto (AUDIT H-1):** una posición actual con `EligibleFlag`/`LiquidityFlag` falsos o fuera del `InvestmentUniverse` podía pasar de 10 % a 100 % y todas las capas la daban por válida.

**Decisión (D-3, E-10 — Existing Non-Buyable Position Policy):** para una posición actual no comprable y no restringida, `0 ≤ w ≤ min(w_current, MaxWeight)`; se puede mantener o reducir (incluso a cero), nunca incrementar; no es una liquidación obligatoria; si no está en cartera no puede entrar (`w = 0`). Conserva la precedencia de `RestrictedExistingPositionPolicy` (E-09): `HOLD_OR_REDUCE` `w ≤ w_current`; `FREEZE_WEIGHT` `w = w_current`; `FORCE_LIQUIDATE` `w = 0`. Registrada en `MASTER_SPEC.md` §12 y Anexo A (fila E-10) y en `ARCHITECTURE.md` §3.4 (filas 12-15).

**Implementación (una sola definición, consumida por todas las capas):**

| Capa | Cambio |
|---|---|
| Predicado | `models/purchasability.py::purchase_block_reasons` (nuevo): `EligibleFlag`, `LiquidityFlag` (falso / desconocido según `unknown_liquidity_policy`: `EXCLUDE` bloquea, `ALLOW` permite, `ERROR` detiene), `InvestmentUniverse`. |
| `ConstraintSet` | Nuevo campo `unknown_liquidity_policy` (entra en el `ConstraintHash`); `build_constraint_set(..., unknown_liquidity_policy)`. Sin mover la clave de configuración (`candidates.unknown_liquidity_policy`). |
| `ConstraintCompiler` | `_bounds` fija `[0, min(w_current, MaxWeight)]` y emite `NonBuyablePositionRule`; los restringidos siguen por `_apply_policy` (E-09) y no generan regla E-10. |
| Factibilidad previa | `PreFeasibilityChecker._non_buyable`: causa `NON_BUYABLE_CAPS_BELOW_BUDGET` (además de `SUM_UPPER_BELOW_BUDGET` / `GROUP_UPPER_BELOW_MIN`) cuando los topes hacen imposible el presupuesto. |
| Frontera continua / candidatos / frontera global | Sin cambios de lógica: consumen los límites compilados (`ContinuousFrontierEngine`, `ProjectedWeightsEvaluator`, `QPCompositionEvaluator`, `GlobalCandidateFrontierEngine`). |
| Screening | `EligibilityResult.weight_cap` + `screen(..., entrant_weight_caps)`: un activo `LIQUIDATE_ONLY` que reentra en una composición se puntúa con peso de entrada `min(1/T, w_current)`. |
| `SolutionValidator` | Comprobación `NON_BUYABLE_POLICY` desde `w_current` (no desde `compiled.upper`): rechaza el 20 % aunque la cota compilada estuviera abierta. |
| Diagnósticos | Nota `E10_NON_BUYABLE_POSITIONS_CAPPED_AT_CURRENT_WEIGHT` en `CandidateDiagnostics.notes`; `eligibility_counts` ya cuenta `LIQUIDATE_ONLY`. |

Módulos B2 tocados (autorizado por la brecha transversal): `constraints/{compiler,constraint_set,feasibility}.py`, `validation/solution_validator.py`, `frontiers/continuous_frontier.py` (una línea: pasar la política). Regla de no regresión: baseline ejecutado antes (796 passed) y después.

**Tests (valores esperados = constantes del escenario: `w_current = 0,10`, `μ_A000 = 0,30` frente a `0,04-0,09`; nunca salen de las funciones bajo prueba):**

* `tests/unit/constraints/test_non_buyable_positions.py` (24): cota `[0, 0,10]` para las cuatro causas (`EligibleFlag`, `LiquidityFlag`, `LiquidityFlag` desconocido con `EXCLUDE`, fuera del `InvestmentUniverse`); `min(0,10, MaxWeight)`; `MinWeight` no fuerza crecer; entrada nueva imposible; política `ALLOW`/`ERROR`; el hash cambia con la política; el validador rechaza 0,20 y 0,11 y acepta 0,10/0,05/0; el validador **no** depende de `compiled.upper` (cota manipulada); precedencia E-09 para `HOLD_OR_REDUCE`/`FREEZE_WEIGHT`/`FORCE_LIQUIDATE`; conflictos (presupuesto imposible, mínimo de grupo, caso factible sin causa); acuerdo compilador ↔ `EligibilityFilter` sobre el escenario de 12 activos (oráculo escrito a mano `{A001, A003, A005, A006, A008}`).
* `tests/integration/test_non_buyable_pipelines.py` (44): para cada causa: frontera continua GROSS y NET × `RISK_AVERSION_GRID`/`TARGET_RETURN_GRID` (máximo = 0,10, todos los puntos válidos), reducción hasta 0 posible, entrada nueva = 0 en una composición explícita, estimaciones de **todos** los candidatos (`PROJECTED_WEIGHTS` y `QP_UTILITY`), frontera global GROSS/NET; control sin bloqueo (el óptimo pasa de 0,5); políticas de restringidos sobre un activo además no elegible.
* `tests/unit/candidates/test_non_buyable_screening.py` (10): `weight_cap`, peso de entrada del screening y cableado del expansor.
* **Control de mutación (ejecutado sobre los tests finales, código restaurado después de cada mutante):** compilador sin tope (`upper = MaxWeight`) → 52 de 76 tests fallan; validador sin la comprobación E-10 → 6 fallan; screening sin `weight_cap` → 2 fallan (el primer intento de este mutante sobrevivió y reveló que el cableado del expansor no estaba probado: se añadió `test_the_neighborhood_expander_screens_with_the_cap`); vectorización de cotas del validador que ignora `upper` → 20 de 20 fallan. Los 4 mutantes se detectan.

`CAN-013` conserva `VALIDATED` porque H-1 está corregido y probado.

**Nota sobre `EligibleFlag` desconocido:** el cargador exige `EligibleFlag` booleano (`universe_validator.py`), por lo que no puede estar «desconocido»; el caso de bandera desconocida que existe es `LiquidityFlag` (cubierto). El restringido desconocido de un activo mantenido ya se trataba en B2.

---

## 2. BEN-009

`BEN-009` se creó de forma unilateral en el Bloque 3 (no está en `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md` ni `IMPLEMENTATION_PLAN.md`). **Retirado como `RequirementID`.** Se conservan benchmark, código (`benchmark/candidate_suite.py`, `benchmarks/scripts/candidate_engine.py`), tests (`tests/unit/benchmark/test_candidate_benchmark.py`), JSON (`benchmarks/results/candidate_engine_20260924T100129Z.json`, sin tocar) y resultados como **evidencia** de `BEN-001`, `BEN-002` y `BEN-006` (filas actualizadas en `TRACEABILITY.md`). El script emite ahora `evidence_for` en lugar de `requirement`.

**Total contractual: 316 `RequirementID`** (reconciliado por script sobre `TRACEABILITY.md`: 316 IDs únicos; 181 `VALIDATED`, 41 `PARTIAL`, 0 `IMPLEMENTED`, 94 `NOT_IMPLEMENTED`; las 26 filas del resumen por dominio coinciden con el recuento de filas).

---

## 3. FEA-006 y CON-012 — restricción ADV/NAV (A-11, aclaración E-11)

**Definición literal de `FEA-006`** (fuentes): `TRACEABILITY.md` («Liquidez», `check_liquidity`, `test_liquidity_rules`, bloque 3); `IMPLEMENTATION_PLAN.md:171` (B3) y línea 315 (`A-11 … B3`); `MASTER_SPEC.md` §13 («comprobar incompatibilidades entre … liquidez» antes del solver, con la causa registrada). `IMPLEMENTATION_PROMPTS.md` no lo mencionaba (contradicción que la decisión del usuario resuelve: se implementa en B3).

**Decisiones del usuario (registradas en `MASTER_SPEC.md` §12 como E-11, Anexo A, y en A-11 de `ARCHITECTURE.md`):**

1. `LiquidityCapacity_i = max_adv_participation · ADV_i · liquidation_days / NAV`. Posición **nueva**: `w ≤ capacidad`. Posición **existente**: `w ≤ max(w_current, capacidad)`: no se obliga a liquidar una posición que ya supera el límite y no puede aumentar por encima de su peso actual. Precedencia de E-09 y E-10 intacta. Es un límite de tamaño de posición: **no** garantiza que una venta pueda ejecutarse y es distinto de una futura restricción de volumen negociable por operación (consta en código, especificación, arquitectura y README).
2. Configuración `[constraints.liquidity]`: `enabled`, `max_adv_participation` (`0 < p ≤ 1`), `liquidation_days` (`≥ 1`), más `fx_rates`. **Sin valores productivos por defecto** (`config/default_engine.toml`: `enabled = false`, parámetros comentados; los valores explícitos solo están en fixtures y tests). Con `enabled = true` los parámetros son obligatorios; `NAV > 0`, `ADV ≥ 0`, todo finito; datos ausentes o inválidos ⇒ error (`ConfigError` / `ConstraintCompilationError` / `DataValidationError`), nunca se desactiva en silencio.
3. `ADV` y `NAV` en la misma divisa. Con divisas distintas se exige un tipo de cambio explícito (`ADVCurrency → NAVCurrency`, par exacto; no se infiere ni se invierte) y el cálculo se rechaza si falta. Si solo una de las dos divisas está declarada, se rechaza; si ninguna, se asume la misma divisa de valoración (documentado). El tipo usado queda en `LiquidityCapRule.fx_rate` junto al `ADV` original (trazabilidad).

**Implementación (una sola fórmula, `constraints/liquidity.py::liquidity_capacity`; el resto la consume):**

| Capa | Cambio |
|---|---|
| Modelos de datos | `AssetMetadata.adv_currency`, `PortfolioSpec.nav_currency` (opcionales; columnas `ADVCurrency`/`NAVCurrency`). |
| Configuración | `LiquidityConfig` y `FxRate` (`config/constraint_config.py`) con todas las validaciones; `[constraints.liquidity]` en el TOML; entra en `ConfigHash` y `ConstraintHash`. |
| Validación de inputs | Cargadores de universo (`ADVCurrency`) y de carteras (`NAVCurrency`); `ADV < 0` y `NAV ≤ 0`/no finito ya se rechazaban; `NAV`/`ADV` ausentes con la restricción activa ⇒ error. |
| Compilador | `_bounds`: `high = min(high, max(w_current, capacidad))` para activos no restringidos (tras E-10) y `LiquidityCapRule` con capacidad, `ADV`, FX y si el tope es vinculante. |
| Factibilidad previa | `PreFeasibilityChecker.check_liquidity` (`FEA-006`): `LIQUIDITY_CAP_BELOW_MIN_WEIGHT` y `LIQUIDITY_CAPS_BELOW_BUDGET` con los activos, además de los genéricos. |
| Optimizador continuo / frontera global | Consumen los límites compilados (sin lógica nueva). |
| `CandidateEngine` | Valida los datos al iniciar (un dato faltante detiene la generación; no descarta composiciones en silencio); acota el peso de entrada del screening y los máximos de cardinalidad (FEA-002); estimaciones `PROJECTED_WEIGHTS` y `QP_UTILITY` vía restricciones compiladas; nota `A11_ADV_NAV_LIQUIDITY_CAPS_ACTIVE` con las posiciones protegidas por encima de la capacidad. |
| `SolutionValidator` | `LIQUIDITY_CAP` desde la capacidad y `w_current` de la regla, no desde `compiled.upper` (test con cota manipulada). |

**Tests (valores esperados a mano: `p = 0,10`, `días = 5`, `NAV = 1e8`, `ADV = 2e7` ⇒ 0,10):** `tests/unit/constraints/test_liquidity_capacity.py` (50) cubre los 18 casos pedidos: 1 nueva bajo el límite, 2 nueva sobre el límite, 3 actual bajo el límite, 4 actual sobre el límite (no se fuerza), 5 intento de aumento (rechazado), 6 mantener, 7 reducir, 8 `ADV = 0`, 9 `NAV` inválido (`0`, negativo, `NaN`, `inf`, ausente), 10 participación inválida, 11 días inválidos, 12 divisas distintas con FX explícito (4e7 USD × 0,5 = 2e7 EUR), 13 FX ausente (el par inverso no se acepta), 14 configuración activada incompleta (constructor y cargador TOML), 15-17 `FREEZE_WEIGHT`/`FORCE_LIQUIDATE`/`HOLD_OR_REDUCE`, 18 `MaxTurnover` (turnover mínimo forzado 0 a mano); más `test_liquidity_rules` (FEA-006). `tests/integration/test_liquidity_pipelines.py` (15): frontera continua GROSS/NET × 2 métodos (máximo exactamente 0,10 o 0,20 según el caso; todos los puntos válidos), reducción a 0, `MaxTurnover` con turnover recalculado a mano, `CandidateEngine` y frontera global con `PROJECTED_WEIGHTS` y `QP_UTILITY`, diagnósticos, error de datos, control sin restricción (el óptimo pasa de 0,5) y restricción desactivada.

**Control de mutación:** sin tope en el compilador → 17 de 65 tests fallan; tope duro `capacidad` en lugar de `max(w_current, capacidad)` → 9; validador sin comprobación → 4; conversión FX ignorada → 1. Los 4 mutantes se detectan.

**Estados:** `CON-012` **VALIDATED** (ADV/NAV y `LiquidityFlag` implementados y probados; el límite de volumen negociable por operación queda fuera y así se declara) y `FEA-006` **VALIDATED**. Total contractual 316.

**Regresión E-09/E-10:** los tests de E-10 (24 + 44 + 10) y los de E-09 de B2 siguen en verde (§9); los casos 15-17 y `test_e10_stays_stricter_than_the_liquidity_cap_for_a_non_buyable_position` verifican la precedencia con la liquidez activa.

**Limitaciones declaradas:** sin `ADVCurrency`/`NAVCurrency` (ninguna declarada) se asume la misma divisa; no hay conversión FX automática ni inversión de pares; no se modela el volumen negociable por operación.

---

## 4. Rendimiento del `CandidateEngine`

### 4.1 Por qué ≈ 1.200 evaluaciones

`utility_risk_aversions = [1, 4, 16]` (3 perfiles λ) × 2 fases por perfil (haz y pulido con búsqueda local) × `max_evaluations = 200`. Las 6 fases agotan su presupuesto (200 cada una, medido con `CandidateDiagnostics`): 1.296 vecinos generados, 2 duplicados omitidos, 1.200 evaluados (94 no evaluados por presupuesto). El vecindario por nodo está acotado por las listas cortas (`shortlist_in = 8`, `shortlist_out = 6`, `max_neighbors_per_order = 60`), por eso el número de evaluaciones **no crece con el universo** (50 → 700 activos: 1.200 en ambos): la búsqueda es de presupuesto fijo y el benchmark no mide escalado con el universo.

### 4.2 Perfil por etapas (`benchmarks/scripts/candidate_profile.py`, universo 50, cartera 20, semilla 7)

Tiempo **acumulado** por etapa, como porcentaje del tiempo total con `cProfile` (la sobrecarga del perfilador está incluida; sirve para el reparto, no para tiempos absolutos):

| Etapa | Antes (árbol con E-10, sin optimizar) | Después |
|---|---|---|
| Screening (señales + score) | < 1 % | 0,8 % |
| Listas cortas (selección/exploración: «scoring» de candidatos) | < 1 % | 0,1 % |
| Generación de vecinos | < 1 % | 0,5 % |
| Deduplicación (`CompositionHash` de vecinos) | 5,3 % | 3,4 % |
| Preparación (restricciones B2 + factibilidad) | 32,6 % | 25,5 % |
| Evaluación de composiciones (`PROJECTED_WEIGHTS`; no hay QP en este modo) | 60,2 % | 68,6 % |
| Selección de finalistas | < 1 % | 0,2 % |
| Hashing (`composition_hash` + `constraint_hash`; `canonical_json` es un subconjunto: 11,8 %) | ≈ 15 % (`constraint_hash` 8,4 % + `composition_hash` 6,9 %) | 1,7 % (`composition_hash`; `constraint_hash` ya no se calcula en la búsqueda) |

### 4.3 Mejoras aplicadas (sin cambiar la búsqueda)

1. `CompiledConstraints.composition_id` y `constraint_hash` **bajo demanda** (`cached_property`): la búsqueda compila ≈ 1.100 composiciones y publica 12; mismos valores que antes.
2. `composition_hash`: serialización directa de los AssetID (mismos bytes que `canonical_json`; test de equivalencia con 5 conjuntos incluidos Unicode/comillas/barras).
3. `SolutionValidator._bounds` sin bucle de Python por activo (mismo informe: violaciones, orden y `max_violation`).
4. `MemoizedEvaluator`: memoria **local a la generación** de `(CompositionHash, λ, utilidad de referencia)`; elimina la reevaluación de la composición de referencia en el ensamblado (una por perfil) y de las finalistas en perfiles donde ya se habían evaluado (`CandidateDiagnostics.evaluation_cache_hits`; 3 aciertos en el caso medido). No es la caché del Bloque 5.
5. No se han introducido multiprocessing, `SharedMemory`, `ProcessPoolExecutor` ni nada del B5.

**Resultado (deterministas):** llamadas a funciones por búsqueda **2.296.734 → 1.261.180 (−45 %)**; `canonical_json` 3.298 → ≈ 1.100 llamadas; 1.200 evaluaciones y 12 composiciones **iguales**. **Equivalencia bit a bit** de la salida antes/después en 4 escenarios (`universe_problem(50, 20, 7)`, `random_problem` ×2, `two_region_problem`): `CompositionID`, utilidades, turnover, costes y pesos estimados (comparados en hexadecimal) idénticos.

**Tiempo (con la salvedad siguiente):** tiempo de CPU mínimo de 5 repeticiones, ejecutadas de forma alterna antes/después: 1,17 s y 1,23 s → 1,03 s, 1,08 s y 1,08 s (**−12 % a −16 %**).

**Salvedad medida — la máquina tiene dos estados de rendimiento.** Ejecuciones idénticas dan ≈ 1,0 s o ≈ 5-6 s de CPU (5×) según un estado de la máquina ajeno al código; es la explicación probable de la discrepancia que la auditoría no pudo atribuir (5,6-6,8 s en su perfilado frente a 8-9 s en el JSON). Por eso: (i) se comparan solo ejecuciones alternas y mínimos; (ii) las cifras absolutas de los JSON no son comparables entre sí. El nuevo `benchmarks/results/candidate_engine_20260924T124637Z.json` (árbol `+dirty`, tiempos de generación 3,8-6,2 s frente a 8,2-9,3 s del JSON anterior) se ejecutó en un estado distinto y **no** se interpreta como mejora por sí mismo; el JSON anterior se conserva.

**No aplicado (oportunidad identificada):** evaluar en lote (vectorizar el gradiente proyectado entre los vecinos de un nodo) reduciría la etapa dominante (69 %) pero cambia el orden de sumas de punto flotante; requiere revalidar resultados y se propone para la preparación del B5. Tampoco se ha tocado el bucle por activo de `ConstraintCompiler._bounds`/`weight_of` (25 % en preparación).

---

## 5. Correlación entre señales del screening (M-2)

Medido con `benchmarks/scripts/screening_correlation.py` (5 semillas, universo 200, cartera 20, λ = 4; también 700). **No se ha cambiado ninguna ponderación ni eliminado ninguna señal.**

Correlación de rango (Pearson sobre percentiles) media, señales de los entrantes:

| | alpha | riesgo marg. | diversif. | covar. | ΔU | ajust. riesgo |
|---|---|---|---|---|---|---|
| alpha | 1,00 | 0,03 | 0,04 | 0,02 | 0,79 | 0,88 |
| riesgo marginal | 0,03 | 1,00 | **0,93** | **0,95** | 0,60 | 0,12 |
| diversificación | 0,04 | 0,93 | 1,00 | **0,97** | 0,56 | 0,01 |
| covarianza | 0,02 | 0,95 | 0,97 | 1,00 | 0,56 | 0,00 |
| `expected_utility_gain` | 0,79 | 0,60 | 0,56 | 0,56 | 1,00 | 0,76 |

(`liquidity`: correlación no definida en los datos sintéticos porque `ADV` es constante; `transaction_cost` y `sector_fit` ≈ 0 con todo.) Con 700 activos: 0,96-0,98 entre las tres de riesgo.

* **Doble contabilización:** las tres señales de riesgo se comportan como una sola (nominal 33,3 % del peso; aportación real a la varianza del score 34,6 % con 200 activos, 36,6 % con 700); `expected_utility_gain` (nominal 26,7 %) aporta el **37,8 %** porque ya contiene alpha (0,79) y riesgo (0,60); `risk_adjusted_return` va con alpha (0,88). Los pesos configurables **no** son influencias independientes: «un 25 % a riesgo» son en realidad las tres filas. La aportación real de `liquidity` (3,3 % nominal → 0 %), `transaction_cost` (6,7 % → 1,2 %) y `sector_fit` (3,3 % → 0,2 %) depende de la dispersión de esas señales en los datos: con datos sintéticos casi constantes no pesan.
* **Sensibilidad del `CandidateScore`:** cambiar **un** peso ±50 % apenas mueve la lista corta (Spearman ≥ 0,996; 7,0-8,0 de 8 activos comunes); quitar **el grupo** de riesgo o usar el conjunto ortogonal (alpha, ΔU, liquidez, coste, sector) sí la cambia (Spearman 0,89-0,93; 3,0-4,8 de 8 comunes). Conclusión: el ranking es estable frente a ajustes individuales y sensible al bloque de riesgo en conjunto, como cabe esperar de tres señales casi idénticas.
* **Tests** (`tests/unit/candidates/test_screening_correlation.py`, 22): fijan la correlación (> 0,85 entre las tres), el solapamiento de ΔU con alpha y riesgo, el score como media ponderada exacta de las señales normalizadas (invariante a escalar los pesos), la estabilidad frente a un peso y el cambio al quitar el grupo. Son tests de caracterización: si cambia la definición de una señal deben revisarse junto con esta sección.
* Recomendación (no aplicada): documentar en la configuración que los pesos de riesgo son un grupo, y valorar un conjunto ortogonal o una decorrelación antes de calibrar en producción. Queda fuera de B3 decidir ponderaciones.

---

## 6. Deduplicación (L-4)

`tests/unit/candidates/test_deduplication.py` (5 tests) con un evaluador contador por `(CompositionHash, λ)`: composición alcanzada desde **dos padres distintos**, con **el orden de AssetID alterado** (todas las permutaciones dan el mismo hash; `visited` con el hash calculado al revés), tras un **ciclo de swaps** (la raíz no se reevalúa) y en una **búsqueda completa** (ninguna pareja `(composición, λ)` se evalúa dos veces; evaluaciones del contador ≥ `total_evaluated` + raíces; `duplicates_skipped > 0`). **El mutante `dedup_off` (`if digest in visited:` → `if False:`) ahora es detectado por los 4 tests de comportamiento.** Además la prueba encontró duplicados reales (la referencia y las finalistas reevaluadas en el ensamblado), resueltos con `MemoizedEvaluator` (§4.3).

---

## 7. Semántica de `max_evaluations` (L-3)

Los documentos de gobierno (`MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`) **no definen** este parámetro. El único contrato escrito era el docstring de `CandidateConfig` («por perfil de aversión al riesgo y por fase») y el `CHANGELOG.md` del B3 (cada fase tiene su presupuesto porque el haz agotaba el presupuesto único y la búsqueda local nunca se ejecutaba). Los docstrings de `expansion.py`/`beam_search.py` decían «de un perfil» y eran los incorrectos. **Contrato adoptado (el implementado, sin cambiar su significado): presupuesto por perfil λ y por fase; tope total `len(utility_risk_aversions) × 2 × max_evaluations` más la raíz de cada perfil (no consume presupuesto).** Alineados: docstrings (`EvaluationBudget`, `beam_search`, `CandidateConfig`), comentario de `config/default_engine.toml`, `ARCHITECTURE.md` fila 14 y el test nuevo `test_max_evaluations_is_a_budget_per_risk_profile_and_per_phase` (cada fase ≤ límite, el haz agota el suyo y el pulido conserva el suyo, total ≤ 3 × 2 × límite). Si se prefiere un presupuesto por perfil, el tope real pasaría de 1.200 a 600 y cambiaría la calidad de búsqueda: sería una decisión distinta.

---

## 8. Test inestable del Bloque 2

* **Test:** `tests/property/test_invariants.py::test_every_frontier_point_satisfies_the_financial_invariants` (Hypothesis, 25 ejemplos; exige `is_valid_solution` en cada punto).
* **Causa:** reproducible **sin Hypothesis**, con el generador del propio test, y **idéntica sobre el baseline `block2-validated` y sobre el código actual** (extraído con `git archive` y comparado): en fronteras `TARGET_RETURN_GRID` de problemas de 2-3 activos, algún punto no converge y se marca con su estado real. Casos (exploración determinista de `n ∈ 2..5` × semillas 0-199 × 3 tratamientos × 2 métodos = 4.800 casos): **10 fallos (0,21 %)**, todos en `TARGET_RETURN_GRID`, 0 en `RISK_AVERSION_GRID`, 9 con `n = 2` y 1 con `n = 3`; 7 instancias distintas: `(n, semilla) = (2,19) (3,67) (2,84) (2,89) (2,159) (2,184) (2,193)`.
  * `(2,19)` NET: OSQP agota 250.000 iteraciones con residuales primal 2e-9 y dual 1e-11 y declara `solved inaccurate` → `OPTIMAL_INACCURATE` (`accept_inaccurate_solutions = false`). Con `eps = 3e-9` o `1e-8` converge (`OPTIMAL`, mismo objetivo): la tolerancia de ejemplo `1e-9` está en el suelo de precisión de OSQP. El punto está validado por el `SolutionValidator` independiente (`max_violation = 1,2e-9`).
  * `(2,84)`, `(2,184)`, `(2,193)`: los dos activos tienen retornos esperados casi iguales (diferencias 3,6e-6, 7,4e-5, 2,0e-5), la frontera es casi degenerada y OSQP declara `INFEASIBLE` para retornos objetivo alcanzables (limitación de `eps_prim_inf` ya descrita en `ARCHITECTURE.md` R2-02).
  * `(2,89)`, `(2,159)`, `(3,67)`: `INFEASIBLE`, `MAX_ITERATIONS` y `NUMERICAL_ERROR` tras la verificación cruzada de puntos de `TARGET_RETURN_GRID` (mismo patrón de estados no óptimos del solver; no se han analizado una a una).
* **Frecuencia:** 0,21 % por ejemplo ⇒ ≈ 5 % por ejecución si los ejemplos fueran uniformes; observado: 1 fallo en ≈ 46 ejecuciones (1 de la auditoría + 15 + 30 posteriores) con base de ejemplos de Hypothesis vacía.
* **Impacto:** ninguno financiero (los puntos se etiquetan con su estado real y nunca se aceptan en silencio; los válidos cumplen los invariantes); es una limitación de robustez de B2/OSQP en fronteras casi degeneradas que la frontera global hereda. **No se han relajado tolerancias ni modificado el test.**
* **Registro:** `tests/unit/frontiers/test_known_inaccurate_point.py` (2 tests deterministas) fija la regla («un `OPTIMAL_INACCURATE` nunca cuenta como válido y su validación independiente existe») y la causa (tolerancia `1e-9` frente a `1e-8`). **Recomendación:** decidir en B4 (estados/robustez de solvers) si se adapta la tolerancia, el escalado o el tratamiento de fronteras degeneradas; hasta entonces el test de propiedades puede fallar de forma esporádica.

**Segunda tanda — clasificación de los casos (hallazgo separado, NO resuelto):** `tests/unit/frontiers/test_known_solver_status_cases.py` (9 tests) fija las 7 instancias `(n, semilla)` con un oráculo LP independiente (HiGHS: máximo retorno alcanzable, bruto o neto con costes). Los 10 casos (instancia × tratamiento) con puntos no válidos:

| Situación | Casos | Evidencia |
|---|---|---|
| Solución **verdaderamente infactible** (objetivo > máximo alcanzable) | **0** | en todos los puntos no válidos `objetivo < máximo` (márgenes de 1,3e-7 a 1,2e-4) |
| Problema **factible** declarado `INFEASIBLE` (fallo numérico del solver / de su criterio de infactibilidad) | `(2,84)` y `(2,184)` y `(2,193)` en GROSS y POST_COST_GROSS, `(2,89)` NET | retornos esperados casi iguales en 84/184/193 (frontera casi degenerada) |
| Problema **factible que no converge** (`NUMERICAL_ERROR`, `MAX_ITERATIONS`) | `(3,67)` NET, `(2,159)` NET | tras la verificación cruzada |
| Convergencia por debajo de la tolerancia pedida (`OPTIMAL_INACCURATE`; validación independiente válida, exceso 1,2e-9) | `(2,19)` NET | `eps = 1e-9` en el suelo de precisión de OSQP; converge con `3e-9` |
| **Estado reportado correctamente** | todos | ningún punto no óptimo cuenta como válido; los `OPTIMAL_INACCURATE` conservan su validación |

No se relajó ninguna restricción económica ni tolerancia (un test lo verifica). **¿Requiere remediación específica posterior? Sí:** es un hallazgo de B2/solver (estados y robustez de OSQP en fronteras `TARGET_RETURN_GRID` casi degeneradas o en el suelo de precisión), independiente del Bloque 3; propuesta: tratarlo en B4 (estados de solver, verificación cruzada, tolerancias y escalado) o en una remediación específica de B2. Hasta entonces `tests/property/test_invariants.py::test_every_frontier_point_satisfies_the_financial_invariants` puede fallar de forma esporádica (≈ 0,21 % por ejemplo); **no se afirma que esté resuelto**.

---

## 9. Resultados de la verificación

Ejecutado realmente sobre el código final (Windows 11, Python 3.13, `.venv`; nunca `ruff format .` con escritura en la raíz: por el riesgo de reescribir bloques de código de `.md` solo se formatearon `portfolio_engine`, `tests` y `benchmarks`; en la raíz solo `--check`):

| Comando | Resultado exacto |
|---|---|
| `pytest -q` antes de la primera tanda (baseline) | 796 passed |
| `pytest -q` tras la primera tanda (E-10, rendimiento, etc.) | 929 passed |
| `pytest -q -p no:cacheprovider` **final** (tras ADV/NAV y casos de B2) | **1003 passed in 255.47s** (0 failed, 0 skipped) = 929 + 74 nuevos (50 + 15 + 9) |
| Los 51 ficheros de test del baseline `block2-validated` sobre el código final | **560 passed** (558 del baseline + 2 tests de arquitectura del B3) |
| `mypy --strict portfolio_engine` | `Success: no issues found in 124 source files` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `250 files already formatted` |
| Control de mutación | E-10: 4/4; ADV/NAV: 4/4; `dedup_off`: detectado |

Tests nuevos de la segunda tanda: `test_liquidity_capacity` 50, `test_liquidity_pipelines` 15, `test_known_solver_status_cases` 9. Los tests de Bloques 1 y 2 no se debilitaron ni se tocaron tolerancias; los únicos cambios en tests previos son los de la primera tanda (nuevo argumento de `build_constraint_set`). `MASTER_SPEC.md` gana solo E-10 y E-11 (aclaración A-11); `IMPLEMENTATION_PLAN.md` e `IMPLEMENTATION_PROMPTS.md` sin cambios; `AUDIT_BLOCK_3.md` intacto. Contractual: 316 `RequirementID` (183 `VALIDATED`, 39 `PARTIAL`, 0 `IMPLEMENTED`, 94 `NOT_IMPLEMENTED`; el resumen por dominio coincide con el recuento de filas, verificado por script).

---

## 10. Limitaciones residuales

* `FEA-006` y `CON-012` `VALIDATED` con la restricción ADV/NAV (§3); no se modela un límite de volumen negociable por operación ni la ejecutabilidad de ventas.
* Fallo esporádico del test de propiedades de B2 (§8): causa documentada, no corregida (fuera de B3).
* Presupuesto de evaluaciones: la evaluación en lote (§4.3) no se ha aplicado; ≈ 1.200 evaluaciones por cartera siguen costando ≈ 1 s (estado rápido) a ≈ 5 s (estado lento) de CPU.
* El benchmark de B3 se ejecutó sobre un árbol sin commit (`+dirty`); debe regenerarse tras el commit (L-1). Los tiempos absolutos dependen del estado de la máquina.
* La memoria local `MemoizedEvaluator` no sustituye a la caché de resultados del B5 (`CCH-*`).
* Validado solo con Python 3.13, Windows 11, `osqp 1.1.3`, `scipy 1.18.1`.
