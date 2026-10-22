# HARD_CONSTRAINTS_DESIGN — Restricciones obligatorias de las carteras finales

> Rama `feature/hard-constraints-final-portfolios` (creada desde `origin/main` `75d8bb5`). No se modifica
> `MASTER_SPEC.md`: las enmiendas metodológicas que requieren aprobación están en §12 y las decisiones
> abiertas en §13. Complementa `AUDIT_PORTFOLIO_HARD_CONSTRAINTS.md` (qué existía y qué faltaba) y
> `HARD_CONSTRAINTS_IMPLEMENTATION_REPORT.md` (qué se implementó y con qué resultados).

## 1. Principios de diseño

1. **Prioridad absoluta de lo obligatorio.** Una propuesta solo es comparable (por retorno, riesgo o
   diversificación) si antes cumple *todos* los límites obligatorios. La diversificación es un objetivo
   secundario *blando* que solo ordena propuestas ya admisibles (§6.3).
2. **Nada se relaja en silencio.** Un límite incumplido produce un rechazo con todas sus causas; un
   override que relaja un límite sin autorización explícita es un `ConfigError`; si no hay solución
   admisible el veredicto es `INFEASIBLE` (demostrado) o `NO_FEASIBLE_SOLUTION` (buscado y no hallado).
3. **Los pesos del solver no se tocan.** No hay recortes, renormalizaciones ni «limpieza» de pesos
   pequeños después de optimizar. La cardinalidad se garantiza en la *generación discreta* y con un
   peso mínimo estrictamente positivo dentro del propio optimizador, y se *verifica* contando posiciones.
4. **Una única fuente de verdad.** `EffectiveHardConstraints` (por cartera) integra los campos que ya
   existían en el motor y los nuevos, con su procedencia, las autorizaciones aplicadas y un hash.
5. **Sin regresión.** Sin la sección `[hard_constraints]` el motor, su `ConfigHash` (`86af211e` para la
   configuración de ejemplo) y todos sus resultados son idénticos a los de `main`.

## 2. Parámetros y unidades

Unidades: pesos como fracción del NAV (`0.2` = 20 %); volatilidad y retorno **anualizados** en tanto por
uno (`0.15` = 15 % anual), las mismas de `RiskModel` (`ARCHITECTURE.md` §5.2). La covarianza «oficial» es
`RiskModel.covariance.matrix` (anualizada, PSD validada); la validación final extrae la submatriz por
`AssetID`, nunca desde estado del solver.

| Parámetro | Semántica | Origen previo |
|---|---|---|
| `cardinality_policy` | `FIXED` (defecto) · `INCREASE` · `DECREASE` | nuevo |
| `target_size`, `min_size`, `max_size`, `max_size_increase`, `max_size_decrease` | tamaño exacto / intervalo absoluto / variación máxima | `PortfolioSpec.target_portfolio_size` (se integra) + nuevos |
| `max_added_assets` | altas `a` | `candidates.max_new_assets` (se integra, mismo significado) |
| `max_removed_assets` | bajas `r` | nuevo |
| `max_total_changed_assets` | `a + r` | nuevo |
| `max_replacements` | sustituciones uno a uno `min(a, r)` | nuevo |
| `max_pure_additions` / `max_pure_removals` | `a − min(a, r)` / `r − min(a, r)` | nuevos |
| (`max_swaps`) | `max(a, r)` | `candidates.max_swaps` (sin cambios) |
| `min_volatility`, `max_volatility` | banda `σ_min <= σ <= σ_max` (`volatility_band_enforcement = HARD`, único modo) | `PortfolioSpec.volatility_limit` (se integra como `max_volatility`) |
| `min_active_weight`, `max_active_weight` | peso mínimo/máximo **por posición** | `constraints.global_min/max_weight`, `frontier.min_holding_weight` (se integran) |
| `max_concentration_hhi`, `min_effective_number_of_positions` | `Σ w² <= H`, `1/Σ w² >= N` | nuevos |
| `diversification_penalty_weight` | objetivo **blando** secundario | nuevo |
| `min_expected_return`, `preserve_original_expected_return`, `expected_return_treatment` | `μᵀw >= max(suelo, μᵀw0)` bruto o neto | nuevos |
| `max_transaction_cost` | coste único de la transición (fracción del NAV) | nuevo |
| `position_weight_threshold` | **único** umbral de «peso positivo» (defecto `frontier.zero_weight_tolerance`) | integra el existente |
| `weight/budget/volatility/hhi/return_tolerance` | tolerancias de la validación final, **cada una `<= 1e-6`** | nuevas (defecto: tolerancias del solver) |
| `band_max_starts`, `band_max_iterations`, `band_convergence_tolerance` | estrategia de la banda no convexa (obligatorios con `min_volatility`) | nuevos |

Los pesos por activo (`weight_bound_overrides` de `PortfolioSpec`, `AssetMetadata.min/max_weight`) siguen
siendo los de B1/B2; el mandato los **restringe** pero no los sustituye.

## 3. Precedencia, autorización y trazabilidad

```
nivel 1  global      [hard_constraints]  +  candidates.max_new_assets / max_swaps,
                      constraints.global_min/max_weight, frontier.min_holding_weight
nivel 2  perfil      [hard_constraints.profiles.<perfil>]            (mandato/perfil de riesgo)
nivel 3  cartera     [hard_constraints.portfolios.<id>]  +  PortfolioSpec
                      (volatility_limit, target_portfolio_size, weight_bound_overrides)
```

* **Regla de endurecimiento.** Un nivel posterior puede *endurecer* un límite (bajar un máximo, subir un
  mínimo, fijar uno que no existía). Relajarlo —o contradecirlo con un override por activo más ancho que
  `max_active_weight`— exige una `RelaxationAuthorization(field, authorized_by, reason, reference)` del
  campo, **en el mismo nivel**, con los tres textos no vacíos. Sin ella: `ConfigError
  MANDATE_RELAXATION_NOT_AUTHORIZED` que nombra el campo, los valores y su procedencia.
* `FIXED` cuenta como valor global aunque nadie lo escriba: un perfil o una cartera no puede pasar a
  `INCREASE`/`DECREASE` sin autorización.
* Tolerancias y definiciones comunes (`*_tolerance`, `volatility_band_enforcement`, parámetros de la
  banda) solo pueden fijarse en el nivel global.
* **Trazabilidad.** `EffectiveHardConstraints` guarda cada valor efectivo, su procedencia
  (`GLOBAL`, `ENGINE_CONFIG:<clave>`, `PROFILE:<x>`, `PORTFOLIO:<id>`, `PORTFOLIO_SPEC:<campo>`), las
  autorizaciones aplicadas, el `ConfigHash` del motor y `effective_hash = SHA-256(payload canónico)`.
  `EngineConfig.hard_constraints` entra en el `ConfigHash` **solo si está definido** (la tabla de
  `config_to_dict` omite el campo cuando es `None`): cachés, diarios y tareas distinguen mandatos distintos.
* **Derivación al motor.** `derive_engine_config` alinea con el mandato efectivo los campos que leen
  B1–B4 (`frontier.min_holding_weight`, `constraints.global_min/max_weight`,
  `candidates.max_new_assets/max_swaps`). Así compilador, `CandidateEngine` y validadores trabajan con la
  misma fuente sin tocar código validado. Es idempotente.

## 4. Cardinalidad

**Definición.** Una *posición* es un activo con `w_i > τ`, `τ = position_weight_threshold`. Es el único
criterio del módulo (búsqueda, validación y métricas coinciden en él; `τ` por defecto es
`frontier.zero_weight_tolerance`, el de `PointMetrics.number_assets`). `n0` = posiciones de la cartera
original con el mismo `τ`.

**Intervalo admisible** (`allowed_sizes`):

| Política | Intervalo antes de `min_size`/`max_size`/`target_size` |
|---|---|
| `FIXED` | `[n0, n0]` |
| `INCREASE` | `[n0, n0 + max_size_increase]` (exige `max_size_increase` o `max_size`) |
| `DECREASE` | `[max(n0 − max_size_decrease, 1), n0]` (exige `max_size_decrease` o `min_size`) |

`min_size`/`max_size` intersecan; un `target_size` fuera del intervalo de la política es una
inviabilidad declarada (`HC_CARDINALITY_TARGET_OUTSIDE_POLICY`), no un cambio silencioso de política.
Sin cartera original (`n0 = 0`) y sin `target_size` la cardinalidad no está definida
(`HC_CARDINALITY_UNDEFINED`).

**Por qué no se simula.** Eliminar pesos pequeños después del solver cambia el vector óptimo y rompe la
suma, los límites y la volatilidad. Aquí:

1. el `CandidateEngine` (B3) genera composiciones de **un tamaño `k` por ejecución**
   (`CandidateEngine.search_with_mandate`: una búsqueda por `k` admisible, fusionadas sin duplicados con
   la referencia primero);
2. el compilador B2 exige a todo miembro de la composición `w_i >= min_active_weight > 0`, de modo que el
   optimizador **no puede** dejar un miembro a cero (por eso `min_active_weight` —o
   `frontier.min_holding_weight`/`constraints.global_min_weight`— es obligatorio con mandato; y
   `τ < min_active_weight`);
3. la validación final cuenta posiciones reales y vigila la masa de pesos positivos por debajo de `τ`
   (`DUST_MASS`) para que no se esconda cardinalidad en pesos diminutos.

La cardinalidad es, por tanto, exacta *por construcción* (selección discreta + cotas inferiores
positivas) y *verificada*, no emulada.

**Excepciones legítimas de B2/B3.** Un activo restringido con `HOLD_OR_REDUCE` (E-09) o no comprable
que se mantiene (E-10) puede reducirse hasta cero por mandato del propio motor; si el optimizador lo
llega a cero, esa propuesta pierde una posición y la validación final la rechaza (`CARDINALITY`) o la
cuenta como baja. `FREEZE_WEIGHT` mantiene el peso (y la posición); `FORCE_LIQUIDATE` es una baja forzosa
que consume presupuesto de sustituciones (§5, §8). Una formulación MIQP con binarias queda reservada a
`EXACT_MIP` (validación, nunca el bucle interno; MIP-005).

## 5. Cambios de componentes

Con `C0` las posiciones originales y `C` las finales, `a = |C ∖ C0|`, `r = |C0 ∖ C|`:

```
total = a + r      sustituciones uno a uno = min(a, r)      altas independientes = a − min(a, r)
swaps = max(a, r)  bajas independientes   = r − min(a, r)   |C| − |C0| = a − r
```

Ejemplo (`C0 = {a,b,c,d}`): `{a,b,c,x}` → `a=r=1`, 1 sustitución; `{a,b,c,d,x}` → `a=1,r=0`, 0
sustituciones y 1 alta independiente; `{a,x}` → `a=1,r=3`, 1 sustitución y 2 bajas independientes. Con
`FIXED` (`a = r`) todos los límites coinciden. Los límites se aplican (i) como poda durante la
búsqueda (`CompositionLimits.move_violations`), (ii) en la validación independiente de cada composición
(`validate_candidate_composition`) y (iii) sobre los pesos finales (§9), siempre respecto a la **cartera
original**. Las salidas forzosas (`FORCE_LIQUIDATE`, activos con cota superior 0) cuentan como bajas.

## 6. Pesos y concentración

1. **Impuestos dentro del optimizador (B2).** `max_active_weight` → `constraints.global_max_weight`
   (con `weight_bound_overrides` acotado por la regla de §3); `min_active_weight` → `min_holding_weight`.
   Son cotas lineales: se cumplen por construcción.
2. **Impuestos en la validación final.** `Σ w² <= H` (`max_concentration_hhi`) y
   `N_eff = 1/Σ w² >= N` son restricciones cuadráticas convexas (equivalen a `‖w‖₂ <= √H` con
   `H = min(max_hhi, 1/N)`): la frontera QP (OSQP) no las admite y el módulo **no modifica los solvers**.
   Los puntos que las violan se rechazan con causa; en la estrategia de banda (§7) entran como un cono
   (`ModelBuilder.add_cone`), de modo que ahí se imponen dentro del optimizador. Como `Σ w² >= 1/k`
   (Cauchy-Schwarz), `1/k <= H` es necesario (§8).
3. **Objetivo blando.** `diversification_penalty_weight` *no* es una restricción: ordena la envolvente
   aceptada por `retorno − penalización·Σ w²` (`ranked_point_ids`). No entra en la función objetivo de
   los solvers (cambiaría la formulación de B2; decisión D-4 de §13).

## 7. Volatilidad mínima y máxima

**Convexidad.** Con `Σ = L Lᵀ`: `σ <= σ_max` ⇔ `‖Lᵀw‖₂ <= σ_max` es un cono de segundo orden
(convexo; ya en B4). `σ >= σ_min` ⇔ `wᵀΣw >= σ_min²` es el *complemento* de un elipsoide convexo:
**reverse-convex**, no convexo. Maximizar una forma cuadrática convexa sobre un politopo es NP-difícil;
no existe un reformulado convexo exacto. Por tanto:

* una validación posterior garantiza **admisibilidad** de lo devuelto, no **completitud** de la búsqueda
  ni **optimalidad global**;
* la estrategia debe separar lo que se puede certificar de lo que no.

**Estrategia (`frontiers/volatility_band.py`), por composición, objetivo «máximo retorno»:**

*Lema 1 (relajación).* Sea `F` el conjunto factible sin `σ_min` (convexo) y `F_b ⊆ F` el de la banda.
`r_A = max_F r(w)` es una cota superior de `max_{F_b} r(w)`. Si el óptimo `w_A` de la relajación cumple
`σ(w_A) >= σ_min`, entonces `w_A ∈ F_b` y es el **óptimo global** (`OPTIMAL_CERTIFIED`). Si `F = ∅`
(`INFEASIBLE` firme del solver) entonces `F_b = ∅` (`INFEASIBLE_PROVEN`).

*Lema 2 (ascenso de varianza).* Para `f(w) = wᵀΣw` convexa y `v ∈ F`, sea `w⁺ = argmax_F (Σv)ᵀw`.
Como `v ∈ F`, `(Σv)ᵀ(w⁺ − v) >= 0`; por convexidad
`f(w⁺) >= f(v) + 2(Σv)ᵀ(w⁺ − v) >= f(v)`: la varianza no decrece. Se usa para hallar un punto con
`σ >= σ_min` desde la relajación y desde un arranque concentrado en cada activo (orden determinista: `Σ_ii`
decreciente y `AssetID`).

*Lema 3 (corte tangente = aproximación interior).* Para cualquier `v`,
`wᵀΣw − 2vᵀΣw + vᵀΣv = (w − v)ᵀΣ(w − v) >= 0`, luego
`{ w : 2(Σv)ᵀw >= σ_min² + vᵀΣv } ⊆ { w : wᵀΣw >= σ_min² }`, y `v` (con `f(v) >= σ_min²`) pertenece al
primer conjunto. El subproblema convexo «máximo retorno sobre `F` ∩ corte» tiene, por tanto, una solución
**admisible** con `r(w⁺) >= r(v)`: la sucesión de iterados es admisible y monótona en retorno
(procedimiento convexo-cóncavo / DC) y converge a un punto estacionario del problema original. No se
afirma optimalidad global.

*Veredictos* (`BandOutcome`, nunca se relaja `σ_min` ni `σ_max`):

| Resultado | Significado | Garantía |
|---|---|---|
| `OPTIMAL_CERTIFIED` | relajación admisible, o el valor alcanza la cota `r_A` (brecha `<=` tolerancia) | óptimo global del problema con banda |
| `FEASIBLE_LOCAL` | punto admisible por DC | admisible; la brecha `r_A − r` acota la pérdida |
| `NO_FEASIBLE_SOLUTION_FOUND` | ningún arranque cruzó `σ_min` | **no** prueba inviabilidad |
| `INFEASIBLE_PROVEN` | relajación inviable o factibilidad previa | inviabilidad demostrada |
| `SOLVER_FAILURE` | estado no concluyente del solver | no confundir con inviabilidad (§45) |

**Cotas deterministas** (factibilidad previa): `max_volatility` por debajo de
`volatility_lower_bound` (B4) es inviable; con `long_only` y presupuesto 1, `σ(w) <= √(max_i Σ_ii)` y
`μᵀw <= max_i μ_i` (máximo de una función convexa/lineal en un vértice del símplex), de modo que
`min_volatility` o `min_expected_return` por encima son inalcanzables.

**Frontera global.** Los puntos de la malla se validan contra la banda (`MIN_VOLATILITY` /
`MAX_VOLATILITY`); además, para cada composición candidata se añade la *propuesta de banda* anterior
(`BandProposal`), validada con la misma validación final. La malla por sí sola puede no tocar una banda
estrecha: la propuesta de banda es lo que acerca la completitud para el criterio «máximo retorno».

**Tolerancia.** `volatility_tolerance <= 1e-6` (techo de seguridad `TOLERANCE_CEILING`) y, si la banda
está acotada por ambos lados, `tol_efectiva = min(tol, 1 % · (σ_max − σ_min))`: la tolerancia numérica no
puede cubrir una violación material.

## 8. Factibilidad previa (`hard_constraints/preflight.py`)

Condiciones **necesarias** evaluadas antes de tocar ningún solver (MASTER_SPEC §13); cada fallo es una
prueba de inviabilidad y queda en `HardConstraintAudit.preflight_causes`. Para cada `k` admisible, con
`f` salidas forzosas, `r = max(f, n0 − k)` y `a = k − n0 + r` (el par que minimiza simultáneamente `a`,
`r`, `a + r`, `max(a, r)`, `min(a, r)`, las altas y las bajas independientes):

| Código | Regla |
|---|---|
| `HC_CARDINALITY_UNDEFINED` / `_TARGET_OUTSIDE_POLICY` | intervalo vacío, objetivo fuera de la política, sin `n0` ni objetivo |
| `HC_SIZE_EXCEEDS_AVAILABLE_ASSETS`, `HC_MANDATORY_EXCEEDS_SIZE` | `k > n0 + elegibles − salidas`; posiciones obligatorias `> k` |
| `HC_CHANGE_BUDGET_INSUFFICIENT` | `a`, `r`, `a + r`, `min(a, r)`, altas/bajas independientes o swaps mínimos superan su límite; faltan activos incorporables |
| `HC_WEIGHT_BOUNDS_VS_CARDINALITY` | `k·min_active > 1` o `k·max_active < 1` |
| `HC_HHI_VS_CARDINALITY` | `1/k > cota_HHI` (`N_eff <= k`) |
| `HC_ACTIVE_WEIGHT_RANGE_EMPTY`, `HC_VOLATILITY_BAND_EMPTY` | `min > max` |
| `HC_VOLATILITY_MAX_BELOW_DETERMINISTIC_BOUND` | `σ_max <` cota inferior de B4 |
| `HC_VOLATILITY_MIN_ABOVE_ATTAINABLE`, `HC_RETURN_FLOOR_UNATTAINABLE` | cotas del símplex (solo `long_only`) |
| `HC_ALL_SIZES_INFEASIBLE` | ningún tamaño es alcanzable (con el motivo de cada `k`) |

Si fallan para todos los tamaños, el `CandidateEngine` devuelve cero composiciones, la frontera global no
llama a ningún solver (ni siquiera a la continua de la cartera actual) y la auditoría es `INFEASIBLE`.

## 9. Validación final obligatoria (`hard_constraints/validator.py`)

Se ejecuta sobre cada punto de la frontera y sobre cada propuesta de banda, **solo desde los pesos
finales** y los datos oficiales. Comprueba, con su exceso, límite y tolerancia: estado del solver,
finitud, presupuesto, no negatividad, cardinalidad real, masa en pesos sub-umbral, altas/bajas/total/
sustituciones/altas y bajas independientes/swaps, peso mínimo y máximo por posición (con excepciones
autorizadas), `Σ w²` y `N_eff`, volatilidad mínima y máxima con la `Σ` oficial, retorno mínimo
(absoluto y/o `μᵀw0`, bruto o neto), turnover (con liquidaciones completas) y coste único, y la
elegibilidad/mandato de la composición desde datos crudos. Un punto se acepta solo si **además** el
solver lo dio por válido (estado admisible y validación independiente B1–B4). Se registran *todas* las
causas (`HC_REJECTED:<CHECK>`); los resultados originales (`GlobalFrontierResult.points`) se conservan y
`accepted_points` / `accepted_envelope` son vistas sobre ellos. La envolvente Pareto se recalcula **solo
entre aceptados**.

## 10. Flujo y capas

```
EngineConfig.hard_constraints ──resolve_hard_constraints──► EffectiveHardConstraints (hash)
        │                                  │
        │ derive_engine_config             ├─ CandidateEngine.search_with_mandate  (una búsqueda por k)
        ▼                                  │     └ preflight por k · CompositionLimits ampliados
 motor B1–B4 (compilador, fronteras) ──────┤
                                           ├─ ContinuousFrontierEngine por composición
                                           ├─ HardConstraintGate.audit (FinalProposalValidator por punto)
                                           └─ VolatilityBandSolver → BandProposal (si hay banda)
```

Paquetes: `config/hard_constraints_config.py` y `models/hard_constraints.py` (datos),
`hard_constraints/{resolver,preflight,validator,counts}.py` (lógica pura, sin `optimizers`/`frontiers`),
`candidates/merge.py`, `frontiers/{hard_constraint_gate,volatility_band}.py`. El grafo de capas de
`tests/unit/test_architecture_rules.py` incorpora `hard_constraints`. `parallel/task.py` rechaza antes de
ejecutar nada cualquier operación distinta de `GLOBAL_FRONTIER` cuando hay mandato (§12, D-2).

## 11. Compatibilidad

* Sin `[hard_constraints]`: `config_to_dict` no añade el campo, `ConfigHash`, caché, diario y resultados
  son los de `main` (`CandidateEngine` equivalente: ver test de equivalencia FIXED).
* Con mandato: el `ConfigHash` incluye el mandato; reanudar un diario con otro mandato se rechaza
  (`JournalIncompatibleError`) sin tocar el diario; la auditoría se serializa/restaura con el códec JSON
  del diario sin pérdida.
* Secuencial ≡ paralelo bajo T1 (incluida la auditoría); el algoritmo de banda es determinista.

## 12. Enmiendas metodológicas propuestas (requieren aprobación; `MASTER_SPEC.md` no se ha modificado)

| ID | Secciones | Propuesta |
|---|---|---|
| E-HC-01 | §12, §13 | Incorporar a «Restricciones básicas» las del mandato (componentes, cardinalidad por política, banda de volatilidad, `Σ w²`, retorno mínimo) con las definiciones de §2–§5 y la factibilidad previa de §8. |
| E-HC-02 | §21, §50 | Definir el tratamiento de `σ >= σ_min` como problema no convexo y adoptar la estrategia de §7 (relajación certificada + DC local) con los veredictos `OPTIMAL_CERTIFIED`/`FEASIBLE_LOCAL`/`NO_FEASIBLE_SOLUTION_FOUND`; confirmar que NONCONVEX_RESEARCH (E-25) no se usa para esto. |
| E-HC-03 | §44, §79 | Elevar la validación final de mandato a requisito de aceptación: ninguna propuesta es «solución válida» sin ella; `NO_FEASIBLE_SOLUTION` ≠ `INFEASIBLE`. |
| E-HC-04 | §4, §31 | `ConfigHash` incluye `hard_constraints` solo si está definido; `effective_hash` por cartera. |
| E-HC-05 | §12 | Precedencia global < perfil < cartera con autorizaciones de relajamiento trazables. |
| E-HC-06 | §26 | Con política `INCREASE`/`DECREASE` el `CandidateEngine` ejecuta una búsqueda por tamaño admisible. |
| E-HC-07 | §12 | `min_active_weight` estrictamente positivo obligatorio con mandato (cardinalidad real). |

Los requisitos nuevos se registran como **propuestos `HC-001…HC-014`, fuera de los 316 `RequirementID`**
(igual que `P-01…P-08` de B5); ningún estado oficial cambia.

## 13. Decisiones abiertas para el usuario

* **D-1.** ¿Se acepta la estrategia DC (resultado `FEASIBLE_LOCAL` con brecha) para `min_volatility`, o se
  exige certificado global (p. ej. extender `ExactMIPValidator` con SCIP, opcional y no instalado aquí)?
* **D-2.** El mandato solo se impone en `GLOBAL_FRONTIER`; las demás operaciones (`FRONTIER_FIXED_COMPOSITION`,
  estrategias, multiescenario) se **rechazan** con mandato en lugar de ignorarlo. ¿Se extiende la
  validación final a ellas (es una extensión mecánica pero amplía el alcance)?
* **D-3.** `max_concentration_hhi`/`min_effective_number_of_positions` se validan (no se imponen) en la
  frontera QP. ¿Se admite un cono en la frontera continua (cambia la clase del problema de QP a SOCP)?
* **D-4.** `diversification_penalty_weight` ordena propuestas admisibles; ¿se incorpora al objetivo de B2?
* **D-5.** El perfil de riesgo se declara en `[hard_constraints.portfolios.<id>].profile`; ¿debe leerse
  de las tablas de entrada de carteras (`PortfolioValidator`)?
