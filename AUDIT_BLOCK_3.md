# AUDIT_BLOCK_3 — Auditoría técnica independiente del Bloque 3

**Rama:** `block3-candidate-engine` · **Baseline:** tag `block2-validated` (commit `6af836c`) · **Fecha:** 2026-09-24
**Alcance auditado:** el árbol de trabajo **sin commit** frente a `block2-validated`: 21 ficheros modificados y 25 entradas nuevas (`git status`; 46 líneas antes de escribir este informe; 47 con él). Nada del Bloque 3 está commiteado.
**Restricciones cumplidas:** no se modificó código ni documentación existente; sin commit, merge, push, tag ni PR; sin avance al Bloque 4. Único fichero creado en el repositorio: este. Los experimentos (adversariales, mutaciones, perfilado) se ejecutaron desde el scratchpad de la sesión (fuera del repositorio; los mutantes sobre una **copia** del árbol).
**Método:** lectura directa del código de `candidates/`, `frontiers/global_frontier.py`, `constraints/{integer,compiler}.py`, `validation/composition_validator.py`, `models/universe_index.py` y de los tests; ejecución real de las cuatro herramientas de calidad; 9 experimentos adversariales independientes; 16 mutantes; perfilado con `cProfile`.
**Limitación de lectura declarada:** de `MASTER_SPEC.md` (2115 líneas) leí completas las secciones que gobiernan el Bloque 3 (§12 con E-09, §13, §23-25, §26-33, §59, §61, §71, Anexo A); no releí el resto. `AUDIT_BLOCK_1.md`, `AUDIT_BLOCK_2.md` y `AUDIT_BLOCK_2_CLOSURE.md` se leyeron en cabecera, resumen y transiciones (no línea a línea).

---

## AUDIT_SUMMARY

`BLOCK_3_STATUS = PASS` **no está plenamente justificado tal como se declara.** La ingeniería es sólida y se ha verificado de forma independiente: el `CandidateEngine` devuelve varias composiciones reales desde la cartera actual, el haz es un haz real, el Pareto global coincide con un cálculo independiente, el caso contractual (11 composiciones válidas, 6 `CompositionID` en la envolvente) se reproduce, la liquidación de activos retirados es correcta al céntimo, el mapeo de índices es correcto con índices globales no consecutivos, y 15 de 16 mutantes fueron detectados. El motivo del veredicto no es la calidad general, sino **un hallazgo HIGH que es una violación material del contrato de elegibilidad** (H-1): el motor continuo, las estimaciones del `CandidateEngine` y el `SolutionValidator` aceptan **subir** el peso de un activo mantenido pero no elegible (10 % → 100 % en mi reproducción). La propia implementación lo reconoce como «limitación conocida», pero:

* contradice la política que ella misma documenta (`ARCHITECTURE.md` §3.4 fila 13: «puede conservarse o venderse pero **no recomprarse**»);
* deja soluciones que compran un activo no elegible dentro de la frontera global **marcadas como válidas**;
* mantiene `CAN-013` en `VALIDATED` con esa brecha abierta;
* no está fijada por ningún test (ni `xfail`).

Es de corrección localizada (una máscara de «comprable» hacia el compilador y una comprobación en el validador) pero **requiere cambios en `constraints/compiler.py` y `validation/solution_validator.py` (módulos B2)**, por lo que no puede darse por buena sin remediación explícita y decisión del usuario sobre el contrato (D-3).

| Severidad | Nº | Hallazgos |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 1 | H-1 |
| MEDIUM | 2 | M-1, M-2 |
| LOW | 7 | L-1 … L-7 |
| INFO | 7 | I-1 … I-7 |

Decisiones pendientes para el usuario (no las resuelvo yo): **D-1** (BEN-009), **D-2** (FEA-006), **D-3** (contrato de un activo mantenido no elegible).

### Comprobaciones ejecutadas de verdad

| Comando | Resultado exacto |
|---|---|
| `.venv\Scripts\python -m pytest -q -p no:cacheprovider --durations=15` | `796 passed in 98.31s` (0 failed, 0 skipped) |
| `python -m mypy --strict portfolio_engine` | `Success: no issues found in 122 source files` |
| `python -m ruff check .` | `All checks passed!` |
| `python -m ruff format --check .` | `233 files already formatted` (solo `--check`; nunca `ruff format .`, ver memoria del proyecto: reescribe bloques de código de `.md`) |
| Ficheros de test que existían en `block2-validated` (51) ejecutados sobre el **código actual** | `560 passed in 35.91s` (= 558 del baseline + 2 tests nuevos de `test_architecture_rules.py`) |
| Baseline `block2-validated` extraído con `git archive` a scratchpad y ejecutado sobre su propio código | `557 passed, 1 failed` en la primera ejecución (ver I-1: test de propiedades con hypothesis, preexistente, intermitente); 15 ejecuciones posteriores de ese fichero: todas en verde |

Aviso metodológico: el `python` global del sistema no tiene `hypothesis`, `mypy` ni `ruff`; hay que usar `.venv` (el primer intento con el `python` global produjo 3 errores de colección por `ModuleNotFoundError: hypothesis`, no atribuibles al código).

---

## REQUIREMENTS_AND_TRACEABILITY

### Reconciliación 316 → 317

Recuento reconstruido fila a fila desde `TRACEABILITY.md` (317 filas, 317 IDs únicos): **182 `VALIDATED` · 40 `PARTIAL` · 0 `IMPLEMENTED` · 95 `NOT_IMPLEMENTED`**, idéntico a la tabla resumen y al `CHANGELOG.md` (139→182, 39→40, 138→95).

| Transición frente a `block2-validated` | Nº |
|---|---|
| `NOT_IMPLEMENTED` → `VALIDATED` | 36 |
| `NOT_IMPLEMENTED` → `PARTIAL` | 7 |
| `PARTIAL` → `VALIDATED` (`DAT-013`, `CON-013`, `CON-022`, `TC-003`, `TC-011`, `FRN-021`) | 6 |
| ID nuevo (`BEN-009`, `VALIDATED`) | 1 |
| Degradaciones `VALIDATED` → otro estado | 0 |
| IDs eliminados | 0 |

Aritmética: 139 + 36 + 6 + 1 = 182 ✓; 39 − 6 + 7 = 40 ✓; 138 − 43 = 95 ✓. Las 49 filas con cambio de estado y ninguna otra fila de bloques 4-6 cambió de estado.

### Requisitos exclusivos y compartidos del Bloque 3

* **Exclusivos B3 (validados en B3):** `CAN-001…013`, `CAN-015…022`, `FRN-002`, `FRN-003`, `FRN-017`, `PAR-006`, `PAR-009`, `VAL-010`, `OUT-004`, `OUT-009`, `TST-012`, `TST-014`, `TST-015`, `TST-016`, `VIS-002`, `FEA-002`, `CFG-009`.
* **Compartidos con B2 (cierre de la parte B3):** `DAT-013`, `CON-013`, `CON-022`, `TC-003`, `TC-011`, `FRN-021`.
* **Compartidos con B4/B5 (quedan `PARTIAL`, correcto):** `CON-010`, `CON-011`, `CON-019` (heurístico vs MIQP), `CON-012` (solo `LiquidityFlag`), `PAR-010` (orden estable de workers, B5), `OPT-002`, `REP-003`.
* **Sin implementar, honestamente declarados:** `CAN-014` (tabu, opcional, §30), `FEA-006` (liquidez en factibilidad previa).

### Auditoría de los requisitos señalados

| Requisito | Estado declarado | Veredicto independiente |
|---|---|---|
| `CAN-001` contrato `list[CandidateComposition]` | VALIDATED | **Confirmado.** 11–12 composiciones reales en mis ejecuciones; nunca una sola (§CANDIDATE_ENGINE_VERDICT). |
| `CAN-002` parte de la composición actual | VALIDATED | **Confirmado.** Raíz = cartera actual (`_root_positions`); cada candidato alcanzable por su `SwapHistory` (test + lectura). |
| `CAN-003/004/005` 1/2/3-swap | VALIDATED | **Confirmado.** Experimento: con `swap_orders=(3,)` aparecen composiciones a distancia 3; el vecindario 2-swap está acotado por lista corta (A-18), documentado. |
| `CAN-006` LocalSearch | VALIDATED | **Confirmado** (oráculo SLSQP + enumeración exhaustiva en los tests). |
| `CAN-007` BeamSearch | VALIDATED | **Confirmado** (§BEAM_SEARCH_VERDICT). |
| `CAN-008/009` exploración/diversificación | VALIDATED | Confirmado (mezcla configurable, semilla derivada). |
| `CAN-010/011` screening multiseñal | VALIDATED | **Confirmado con reservas de diseño** (M-2: señales muy correlacionadas). Signos y construcción verificados contra construcción explícita de carteras y con mutantes. |
| `CAN-012` screening vectorizado | VALIDATED | Confirmado para el screening (un bucle sobre 9 señales). `EligibilityFilter._status/_reasons` sí hacen bucles Python por activo (una vez por cartera; irrelevante, L-6). |
| `CAN-013` EligibilityFilter | VALIDATED | **Sobrevalorado → debe ser `PARTIAL` hasta remediar H-1.** El filtro impide *entrar*, no *aumentar*. |
| `CAN-014` tabu | NOT_IMPLEMENTED | Correcto (opcional en §30; el prompt B3 no lo lista). INFO. |
| `CAN-015` CompositionHash | VALIDATED | **Confirmado**, incluido cross-process con `PYTHONHASHSEED` distintos y mutante detectado. |
| `CAN-016/017` salida y diagnósticos | VALIDATED | Confirmado; las estimaciones se etiquetan como estimaciones. |
| `CAN-018/019/020/021/022` | VALIDATED | Confirmado (límites respetados: reproducido; ADD/DROP; cold start; evaluación; referencia incluida y mutante detectado). |
| `TC-011` coste `K_E` de retirados | VALIDATED | **Confirmado** por reproducción independiente (§REMOVED_ASSETS_VERDICT). |
| `FEA-006` liquidez en pre-factibilidad | NOT_IMPLEMENTED | Estado honesto, pero `IMPLEMENTATION_PLAN.md:171` lo asigna al B3 (L-2, D-2). |
| `CON-010/011/019` | PARTIAL | **Correcto** (heurístico ≠ MIQP; §CARDINALITY_VERDICT). |
| `CON-012` | PARTIAL | Correcto (solo `LiquidityFlag`, sin participación ADV/NAV). |
| `CON-013` restringidos no incorporables | VALIDATED | Confirmado en su definición literal (restringido no en cartera → nunca entra). |
| `CON-022` política E-09 | VALIDATED | Confirmado para **activos restringidos** (`HOLD_OR_REDUCE` acota a `w_current`: experimento de contraste, máx. 0,10). No cubre activos no elegibles (H-1). |
| `DAT-013` índices 3 niveles | VALIDATED | **Confirmado** con índices no consecutivos (§INDEX_MAPPING_VERDICT). |
| `PAR-006` sin copia de Σ 700×700 | VALIDATED | Confirmado (`tracemalloc`, snapshot comparte memoria con el modelo de riesgo). |
| `PAR-009` semillas deterministas | VALIDATED | Confirmado (sin `hash()`; test de arquitectura lo prohíbe; test cross-process). |
| `PAR-010` SequenceID + desempate | PARTIAL | Correcto (orden de workers es B5). |
| `FRN-002/003/017/021` | VALIDATED | **Confirmado** (§GLOBAL_FRONTIER/PARETO). |

### BEN-009 — análisis de gobernanza

* **¿Estaba previsto en MASTER_SPEC?** No. `MASTER_SPEC.md` **no contiene ningún identificador `BEN-*`**: los `BEN-001…008` son construcciones de `TRACEABILITY.md` derivadas de §71 en la Fase 0. Tampoco figura en `IMPLEMENTATION_PROMPTS.md` (el bloque 3 no pide benchmark) ni en `IMPLEMENTATION_PLAN.md` (el B3 no lista `BEN-*`).
* **¿Creado unilateralmente?** Sí, por el implementador en este bloque; **se declaró abiertamente** (cabecera de `TRACEABILITY.md`, `CHANGELOG.md`), no hay ocultación.
* **¿Requisito funcional nuevo o prueba adicional?** Es **evidencia/herramienta de medida**, no un requisito funcional: §71 exige medir `CandidateSelectionTime` (cubierto por `BEN-001`, `PARTIAL`) y reportar estadísticos (`BEN-002`, `PARTIAL`). `BEN-009` no añade ninguna obligación del contrato; su «aceptación» es que el script y sus 2 tests funcionan y que existe un JSON con metadatos. Además figura como `VALIDATED` de forma auto-referencial.
* **Recomendación:** documentarlo como **evidencia de `BEN-001`/`BEN-002`** (subconjunto B3) y de `BEN-006` (política de no inventar benchmarks), manteniendo el total en 316. Si el usuario prefiere conservarlo como requisito, debe aprobarse expresamente (y quedar reflejado como enmienda en el Anexo A, como se hizo con E-01…E-09), y su estado debería ser `PARTIAL` (herramienta descriptiva de un solo proceso; sin memoria, sin repeticiones suficientes, ejecución sobre árbol `+dirty`).
* **Severidad:** LOW (L-1). **Decisión pendiente D-1.**

---

## ELIGIBILITY_VERDICT

**Veredicto: NO CONFORME — HIGH (H-1).** Contrato violado: un activo mantenido pero no comprable puede ver aumentado su peso.

### Taxonomía y quién impone qué

| Categoría | Cómo se trata | ¿Hay control de incremento? |
|---|---|---|
| Elegible para nuevas compras (`ELIGIBLE_NEW`) | entra en composiciones | n/a (activo nuevo; su cota es `[MinWeight, MaxWeight]`) |
| Mantenido y comprable (`HELD`) | puede mantenerse, reducirse o comprarse más | n/a |
| **Mantenido pero no comprable** (`LIQUIDATE_ONLY`: `EligibleFlag=False`, `LiquidityFlag` falso o desconocido con política `EXCLUDE`, fuera de `InvestmentUniverse`; reproducido con `EligibleFlag` y `LiquidityFlag`, los otros dos casos por lectura del código) | «puede conservarse o venderse, no comprarse» (`eligibility.py` cabecera; `ARCHITECTURE.md` fila 13) | **NO.** `ConstraintCompiler._bounds` no recibe elegibilidad; la cota superior es `MaxWeight` (`compiler.py:213-250`). |
| Restringido mantenido `HOLD_OR_REDUCE` | `0 ≤ w ≤ min(w_current, MaxWeight)` | **Sí** (E-09, `_apply_policy`) |
| Restringido `FREEZE_WEIGHT` | `w = w_current`; no puede salir de la composición | Sí |
| Restringido `FORCE_LIQUIDATE` | `w = 0`; sale de todas las alternativas | Sí |
| Excluido (`EXCLUDED`) | ni entra ni está en cartera | n/a |

El `EligibilityFilter` (`candidates/eligibility.py`) sí distingue `LIQUIDATE_ONLY`; pero ese estado **solo se consume para decidir qué entra en una composición** (`ENTERABLE_STATUSES` lo incluye) y **nunca se traduce en cotas de peso**. El compilador (B2) y el `SolutionValidator` (B2) no conocen la elegibilidad. Además, `NeighborhoodExpander` calcula `entrants = enterable − composición`, de modo que un activo `LIQUIDATE_ONLY` que se sacó en un nivel puede **reentrar** como «entrante» en el siguiente (es coherente a nivel de conjunto —sigue siendo un activo mantenido— pero refuerza que el peso no está acotado).

### Reproducción independiente del caso pedido (CurrentWeight = 10 %, EligibleFlag = False, el optimizador quiere 20 % o más)

```text
universo de 4 activos, sigma = vol 10 % con correlación 0,1, mu = [0.30, 0.05, 0.05, 0.05]
cartera actual: A000 = 10 % (EligibleFlag=False), A001 = 90 %; MaxWeight = 1
Resultados (frontera continua sobre la composición actual {A000, A001}, 20 puntos):
  GROSS: w_A000 máx = 1.0000, todos los puntos is_valid_solution = True
  NET  : w_A000 máx = 1.0000, todos los puntos is_valid_solution = True
  GLOBAL_CANDIDATE_FRONTIER (GROSS): w_A000 máx en puntos válidos = 1.0
  Estimaciones del CandidateEngine para {A000, A001}: w_A000 = 1.0000 (lambda 1 y 4), 0.9319 (lambda 16); satisfies_constraints = True
  SolutionValidator sobre el punto con w_A000 = 1.000: is_valid = True, violaciones = ()
Contraste con el MISMO activo RESTRINGIDO (RestrictedAssetFlag=True, HOLD_OR_REDUCE):
  w_A000 máx = 0.1000  (correctamente acotado)
Mismo activo con LiquidityFlag=False (mantenido): w_A000 máx = 1.0  (también sin control)
```

Es decir: el activo pasa de 10 % a **100 %** y **todas las capas lo validan**. El caso literal del prompt (10 % → 20 %) es un subconjunto de este resultado.

### ¿Debería rechazarse o restringirse?

Según el contrato aprobado en la propia arquitectura («un activo mantenido no elegible puede conservarse o venderse pero no recomprarse»), **debería restringirse** a `0 ≤ w ≤ min(w_current, MaxWeight)` (equivalente a `HOLD_OR_REDUCE`), y el `SolutionValidator` debería rechazar cualquier solución que lo supere. Además:

* **Incoherencia interna entre políticas.** El activo restringido (E-09) tiene límite de incremento en compilador y validador; el activo no elegible/ilíquido no. Los dos casos tienen la misma razón de negocio («no comprar»). `EligibilityFilter`, compilador y `SolutionValidator` **no son coherentes** entre sí.
* **El argumento de la implementación** («limitar el incremento exigiría cambiar el compilador validado del B2») es un argumento de coste, no de contrato: CLAUDE.md permite modificar un módulo validado con baseline + tests + comparación (regla de no regresión).
* **El MASTER_SPEC no define** una política para el activo mantenido no elegible (solo lista `EligibleFlag` como campo, §5/§13, y E-09 solo cubre restringidos). Por eso la interpretación correcta es una **decisión del usuario (D-3)**; mi recomendación es aplicar la misma semántica que `HOLD_OR_REDUCE` y documentarlo como enmienda.
* **No hay test que fije el comportamiento** (ni `xfail` ni test de «limitación conocida»): `grep -ri "incremento|increase|limitación" tests/` → 0 coincidencias. La limitación solo existe en prosa (`eligibility.py`, `ARCHITECTURE.md`, `README.md:164`, `CHANGELOG.md`).

**Clasificación: HIGH.** No CRITICAL porque (a) está documentada abiertamente, (b) el contrato del MASTER_SPEC es silencioso, (c) la corrección es acotada. Pero es una violación material del contrato de elegibilidad y de la coherencia validador/compilador, y **impide declarar PASS**.

---

## CANDIDATE_ENGINE_VERDICT

**Veredicto: CONFORME.**

* **Múltiples composiciones reales.** `two_region_problem`: 11 candidatos (la referencia + 10 alternativas); `universe_problem(50, 20)`: 12. Todos conjuntos de `AssetID` distintos: la deduplicación es por `CompositionHash` de IDs ordenados (`visited`, `pool` como `dict` por hash, `select_survivors` con distancia mínima `swap_count`) y la lista devuelta pasa una validación independiente (`validate_candidate_composition`, que no usa el `EligibilityFilter`). Los tests comprueban unicidad de hashes; el reordenamiento no crea composiciones (mutante `hash_order_dependent` detectado).
* **Parte de la composición actual.** `_root_positions` usa la cartera actual (ajustada si hay `FORCE_LIQUIDATE`); la composición actual se incluye siempre como referencia (`_reference_candidate`, mutante `reference_not_included` detectado).
* **Cold start** (`COLD_START_SEED`): semilla por utilidad individual `μ_a − λσ_aa` sobre activos entrables; exige `TargetPortfolioSize`; turnover/costes `None` con motivo (`NO_CURRENT_PORTFOLIO`), no inventados.
* **`CandidateScore`, `EstimatedUtilityGain`, `EstimatedTurnover`, `EstimatedTransactionCost`, `CandidateDiagnostics`:** presentes y con semántica separada: `candidate_score` es el prior heurístico acumulado; `estimated_*` proceden del evaluador (cota inferior en `PROJECTED_WEIGHTS`) y se etiquetan «ESTIMATES_ARE_NOT_OPTIMIZED_RESULTS». No se presenta un score heurístico como solución de optimización.
* **Sin lista multiplicada por reordenamiento:** comprobado por lectura (los vecinos son `frozenset[int]`) y por test.

Reservas menores: L-3 (semántica del presupuesto de evaluaciones), L-5 (`beam_width` acoplado al número de finalistas por perfil), L-4 (la deduplicación por `visited` no está protegida por tests).

---

## BEAM_SEARCH_VERDICT

**Veredicto: CONFORME — es un haz real, no un greedy disfrazado.**

* `BeamSearch.run` expande **todos** los nodos del haz en cada nivel (`for node in beam`), ordena a los hijos y conserva `beam_width` supervivientes distintos (`select_survivors`), con `beam = survivors`. Los criterios de parada (`MAX_LEVELS`, `NO_NEIGHBORS`, `STAGNATION`, `BUDGET_EXHAUSTED`) se registran.
* **Mutantes:** `beam = survivors[:1]` y `beam_width → 1` fueron **detectados** por `test_a_wider_beam_finds_compositions_the_greedy_path_misses[3]`.
* **Semillas 3, 18 y 19 reproducidas** con la configuración del test (`swap_orders=(1,)`, 2 niveles) y contrastadas con **enumeración exhaustiva** de las 210 composiciones de tamaño 4 (mismo evaluador):

| Semilla | Mejor con B=1 (1 alternativa) | Mejor con B=3 (3 alternativas) | Óptimo exhaustivo (210 factibles) |
|---|---|---|---|
| 3 | 0,054442 | **0,056059** | 0,062943 |
| 18 | 0,049199 | **0,051302** | 0,061045 |
| 19 | 0,032075 | **0,032948** | 0,039757 |

  B=3 > B=1 en las tres semillas (la afirmación del test es cierta), y con B=1 el algoritmo devuelve **una** alternativa frente a tres.
* **Calidad de la búsqueda con la configuración por defecto** (4 niveles, swaps 1-2, 3 perfiles λ) en 5 universos de 10 activos: en las 5 semillas el mejor candidato **coincide con el óptimo exhaustivo** (con ~190 de 210 composiciones evaluadas; es evidencia débil porque casi se enumera el espacio, **no** demuestra calidad a escala).
* **Debilidad del test:** compara utilidades *estimadas* (cotas inferiores de 15 iteraciones), no una utilidad exacta; y no cubre el caso multi-nivel con `local_search_starts > 0`. Cubierto por mi experimento exhaustivo. (I-5.)
* **`MaximumSwaps` / `MaximumNewAssets` se aplican efectivamente** (experimento independiente sobre 14 activos, 5 mantenidos):

| Configuración | Candidatos | Máx. nuevos | Máx. swaps | Rechazos por causa |
|---|---|---|---|---|
| `max_new=1` | 9 | 1 | 1 | `MAX_NEW_ASSETS: 1259` |
| `max_swaps=1` | 9 | 1 | 1 | `MAX_SWAPS: 1259` |
| `max_new=2, max_swaps=2` | 10 | 2 | 2 | 879 + 879 |
| `max_new=0` | 1 (solo la referencia) | 0 | 0 | 480 |

  Los mutantes que anulan cada límite fueron detectados. Nota de eficiencia: los vecinos que violan el límite se **generan** y luego se rechazan (1259 en el primer caso); barato, pero un vecindario acotado por diseño sería más eficiente (I-6).

---

## SCREENING_VERDICT

**Veredicto: CONFORME con reservas de diseño (M-2).** Es un **screening heurístico**, no una optimización continua; así se declara y así se usa (preselecciona; la selección final es por utilidad evaluada).

* **Señales y signos** (nueve, todas «mayor es mejor» tras aplicar dirección): `+μ_a`; `−ΔVar`; `−ρ(a,r)`; `−cov(a,r)`; `+ΔU`; `+(μ_a−r_f)/σ_a`; `+log ADV`; entrante `−BuyCost` / mantenido `+SellCost`; `1−exposición sectorial`. Verificadas contra la **construcción explícita de carteras** (`test_signals_equal_the_explicit_portfolio_construction`, oráculo independiente) y con mutantes: invertir el signo de covarianza, diversificación o coste fue **detectado**.
* **Normalización:** por rango con empates promediados (por defecto) o z-score, **dentro** del conjunto (entrantes / mantenidos). Con `RANK` los *outliers* no pesan; con `ZSCORE` un valor extremo comprime al resto y **no hay test de robustez a outliers** (L-7).
* **Unidades:** las señales tienen unidades distintas (retorno, varianza, correlación, log-ADV, bps, fracción) y solo se combinan tras normalizar; correcto.
* **Pesos configurables** (`[candidates.screening_weights]`); una señal de peso 0 no interviene; sin literales de negocio (grep de literales en `candidates/`: 0).
* **Datos ausentes:** `MissingSignalPolicy` `EXCLUDE`/`NEUTRAL`/`ERROR` con registro (`SignalTable.missing/imputed`); tests para las tres políticas.
* **Posible doble contabilización (M-2), medida:** correlación de rango entre señales normalizadas de los entrantes (universo de 200, cartera de 20, λ = 4):

```text
                      alpha  marg.risk  divers.  cov    ΔU    risk-adj
expected_alpha         1.00     0.07     0.11    0.09   0.78    0.82
marginal_risk          0.07     1.00     0.92    0.96   0.66    0.23
diversification        0.11     0.92     1.00    0.96   0.63    0.11
covariance             0.09     0.96     0.96    1.00   0.65    0.12
expected_utility_gain  0.78     0.66     0.63    0.65   1.00    0.76
```

  Tres señales de riesgo (`marginal_risk`, `diversification`, `covariance`) se comportan casi como **una** con peso efectivo ≈ 2,5/9,5; `expected_utility_gain` (peso 2) ya incorpora α y ΔVar (0,78 con α, 0,65 con riesgo); `risk_adjusted_return` correlaciona 0,82 con α. Los pesos «configurables» no equivalen a exposiciones independientes. No es un error (los pesos son de ejemplo y son configurables), pero conviene documentarlo o seleccionar un subconjunto ortogonal antes de calibrar en producción.
* **Caso adversarial α vs riesgo/correlación/costes:** cubierto por tres tests (`test_alpha_only_ranking_would_pick_the_concentrating_asset_but_the_screening_does_not`, `test_covariance_beats_individual_alpha_in_the_generated_candidates`, `test_transaction_cost_beats_individual_alpha_in_the_generated_candidates`; estos dos con óptimo exacto SLSQP): por alpha individual saldría X (colineal con la cartera / caro), el motor selecciona Y. Los tres pasan y no dependen de reproducir el algoritmo bajo prueba.

---

## INDEX_MAPPING_VERDICT

**Veredicto: CONFORME.**

* **Determinismo del hash:** `composition_hash = SHA-256(canonical_json({"Composition": sorted(ids)}))`; misma composición en distinto orden → mismo identificador (test, propiedad `test_composition_hash_is_invariant_to_order`, test cross-process con `PYTHONHASHSEED` distintos, y mutante que quita el `sorted` **detectado**). La búsqueda no usa `hash()` nativo ni `random` global (test de arquitectura `test_candidate_pipeline_never_uses_python_hash_or_global_random_state`).
* **Índices no consecutivos:** los tests usan `ELIGIBLE = [1, 3, 4, 8]` sobre 10 activos, con el activo actual `A000` no elegible (centinela `-1`). **Experimento independiente:** universo de 12 activos con elegibles `{2, 5, 6, 9, 11}`, cartera actual `{A005, A009}`; para las 10 combinaciones de tamaño 2, `prepared.mu == mu[comb]` y `prepared.sigma == Σ[ix_(comb, comb)]` → **0 discrepancias** (orden local idéntico para `mu` y `Σ`); las 8 composiciones generadas contienen solo activos elegibles; `global_indices` del candidato 0 = `[5 9]`.
* **Mutante** que sustituye el índice global por `arange` local en `extract_vector`: **detectado** por `test_local_submatrix_and_vector_come_from_the_global_arrays_by_asset_identity`.
* La cartera se mapea por `AssetID`, nunca por `CurrentPortfolioState.global_indices` (índice de universo ≠ índice del modelo de riesgo); decisión correcta y documentada.

---

## GLOBAL_FRONTIER_VERDICT

**Veredicto: CONFORME.**

Pipeline verificado por lectura (`GlobalCandidateFrontierEngine.solve`): `CandidateEngine.search` → **una frontera continua por cada** composición candidata (no solo la de mayor `CandidateScore`) → unión de puntos → `global_pareto`. La frontera de la composición actual se resuelve una sola vez y se **reetiqueta** (`relabel_scope`) como referencia global (misma resolución, `diagnostics is`), sin recomputar ni confundir con `CONTINUOUS_FRONTIER`. El mutante «solo la primera composición» (`search.compositions[:1]`) fue **detectado** por el test contractual.

**Caso contractual reproducido** (`two_region_problem`; 6 activos, tamaño 2, 6 combinaciones tratamiento × método):

| Tratamiento | Método | Candidatas | Composiciones con puntos válidos | `CompositionID` en la envolvente | Puntos (válidos / duplicados) | Envolvente |
|---|---|---|---|---|---|---|
| GROSS | RISK_AVERSION_GRID | 11 | 11 | **6** | 184 / 46 | 64 |
| GROSS | TARGET_RETURN_GRID | 11 | 11 | **6** | 184 / 10 | 62 |
| NET | RISK_AVERSION_GRID | 11 | 11 | **6** | 184 / 46 | 64 |
| NET | TARGET_RETURN_GRID | 11 | 11 | **6** | 220 / 46 | 63 |
| POST_COST_GROSS | RISK_AVERSION_GRID | 11 | 11 | **6** | 184 / 46 | 64 |
| POST_COST_GROSS | TARGET_RETURN_GRID | 11 | 11 | **6** | 184 / 10 | 62 |

11 composiciones con puntos válidos y 6 `CompositionID` distintos en la envolvente, en **las seis** combinaciones (el contrato «`len(unique(CompositionID)) > 1`» se cumple con margen). Los extremos están repartidos: la cartera actual domina el extremo de bajo riesgo y una alternativa con `A002` domina el de alto retorno (`> 0,15` frente a un máximo de `< 0,06` de la actual), como diseña el dataset.

Nota de honestidad sobre el dataset: es **sintético y diseñado** para que sobrevivan varias composiciones (lo pedía la auditoría); demuestra que el pipeline *puede* producir una envolvente multicomposición, no que en datos reales lo haga.

---

## PARETO_VERDICT

**Veredicto: CONFORME.**

* **Contraste con cálculo independiente:** reimplementé el Pareto con bucles explícitos (dominancia con tolerancia `pareto_tolerance`, solo puntos válidos no duplicados) y lo comparé con las banderas de `global_pareto` en las 6 combinaciones: **`indep == flags` en las 6** (`True`). El test del repositorio hace lo mismo (`_brute_force_envelope`) y hay un test de fuerza bruta aleatoria.
* **Dominancia / empates / tolerancias:** `pareto_mask` usa `no_worse & strictly_better & valid` con tolerancia en ambas magnitudes (heredado de B2, validado). Mutante «dominancia sin condición estricta» → **detectado** (`test_a_point_dominated_by_another_composition_is_flagged_but_kept`).
* **Deduplicación entre composiciones:** por tolerancias de configuración en volatilidad, retorno bruto y **pesos sobre la unión de activos** (0 donde falta el activo); el duplicado hereda la bandera del original y conserva `duplicate_of` (trazabilidad); los dominados **no se eliminan** (FRN-016). Los inválidos no participan.
* **Composición de origen y sin mezcla bruto/neto:** cada `GlobalFrontierPoint` conserva `composition_id`, `asset_ids` y el `FrontierPoint` original con su `SolveResult` y `ValidationReport`. `is_global_gross_efficient` usa **solo** `expected_return_gross`; `is_global_net_efficient` usa **solo** `expected_return_net` (mutante que usaba bruto para la bandera neta → **detectado**, `test_gross_and_net_efficiency_use_a_single_magnitude_each`). La bandera neta es `None` si algún punto válido no tiene neto (p. ej. cold start).
* **El Pareto global puede diferir entre GROSS y NET:** en el resultado NET, |eficientes brutos| = 65 y |eficientes netos| = 64, con **1** punto en la diferencia simétrica: la diferencia existe y es pequeña porque el dataset tiene costes bajos (5-40 bps). Además `net ≤ gross` en todos los puntos válidos.
* **`POST_COST_GROSS`** conserva la semántica B2: pesos de la frontera GROSS con retorno neto; la envolvente publicada usa la magnitud neta.

Duplicación menor: la equivalencia de puntos entre composiciones (`global_frontier._weights_close/_find_duplicates`) es una segunda implementación distinta de la de B2 (`frontiers/dedup.is_equivalent`) (L-6).

---

## REMOVED_ASSETS_VERDICT

**Veredicto: CONFORME — la lógica validada del Bloque 2 no se ha deteriorado.**

Reproducción independiente del caso contractual: actual `A` = 10 %, `B` = 90 %; composición `{B, C}`; nueva cartera `B = 90 %`, `C = 10 %` (fijada con `MinWeight = MaxWeight`). Costes: `SellCost_A = 13 bps`, `BuyCost_C = 37 bps`, horizonte `H = 1` año:

```text
tratamiento       pesos      turnover   coste único    TC/H         neto        neto esperado
GROSS             [0.9 0.1]  0.1        0.0005         0.0005       0.0715      0.0715
NET               [0.9 0.1]  0.1000     0.0005         0.0005       0.07149...  0.07149...
POST_COST_GROSS   [0.9 0.1]  0.1        0.0005         0.0005       0.0715      0.0715
esperado: turnover = 0.5·(0.10 + 0.10) = 0.10; coste = 0.10·(13 + 37)/10⁴ = 0.0005 ✓
número de activos nuevos = 1, retirados = 1 ✓
MaxTurnover = 0.09 → pre_check_feasible = False (0 puntos)      ← infactible ANTES del solver ✓
MaxTurnover = 0.10 → factible, 2 puntos válidos                 ← el turnover forzado exacto ✓
MaxTurnover = 0.11 → factible
```

Se confirma: venta completa de A, compra de C, `turnover = 0,10`, `coste = 0,10 × (SellCost_A + BuyCost_C)`, `NetReturn = Gross − coste/H`, `MaxTurnover` incluye la liquidación (constante `exit_turnover`) y el `SolutionValidator` valida el punto. `exit_cost_one_off` a cero (mutante) fue **detectado** por `test_net_target_return_accounts_for_the_liquidation_cost`. La propiedad `test_a_removed_asset_always_has_a_sale_and_a_cost_when_costs_are_positive` (hypothesis) cubre casos aleatorios.

Regresión B2: los 51 ficheros de test del baseline pasan **sobre el código actual** (560 passed).

---

## CARDINALITY_VERDICT

**Veredicto: CONFORME en lo que declara; correctamente clasificado como heurístico (PARTIAL).**

Distinción explícita, y bien mantenida en código y documentación:

* **A. Cumplimiento heurístico mediante generación discreta (B3):** `MaximumNewAssets`, `MaximumSwaps` y `TargetPortfolioSize` se garantizan **por construcción de vecindarios** (`SwapGenerator` con movimientos `SWAP`/`ADD`/`DROP`) y por rechazo con causa (`move_violations`, `limit_violations`); las posiciones congeladas (`FREEZE_WEIGHT`) no pueden salir (`mandatory`), la liquidez y la elegibilidad restringen *la entrada*, y las cotas de peso/grupo/turnover las aplican el compilador y la factibilidad previa **por composición**. Cada candidato devuelto pasa `validate_candidate_composition`.
* **B. Formulación MIQP exacta (B4, `MIP-001`):** **no existe**. `CON-010/011/019` están en `PARTIAL` con esa justificación, `candidate_engine.py` lo dice en su docstring («no equivale a una formulación MIQP exacta … ni se simula eliminando pesos tras el solver»), y no hay backend MIP (`test_no_later_block_packages_exist`). No se presenta la heurística como MIQP: ✓.

Comprobado: tamaño objetivo constante en todos los candidatos (`sizes {5}`), `max_new_assets=0` deja solo la referencia, cardinalidad infactible devuelve solo la referencia con causa (`FEA-002`). Limitaciones que siguen abiertas: el óptimo global de cardinalidad **no se garantiza** (haz + búsqueda local), no hay participación ADV/NAV (`CON-012`, `FEA-006`), y H-1 (no elegible mantenido).

---

## PERFORMANCE_VERDICT

**Veredicto: sin error de diseño; oportunidad de optimización importante antes del Bloque 5 (M-1). El benchmark NO demuestra escalabilidad a 1.200 carteras.**

### Lo que dice el JSON (`benchmarks/results/candidate_engine_20260924T100129Z.json`)

Universos de 50, 200 y 700 activos, cartera de 20, 3 repeticiones + 1 calentamiento, un proceso, sin paralelismo. En los seis `runs`: `compositions = 12`, **`compositions_evaluated = 1200`**, `neighbors_generated = 1296`, `frontier_points = 240`. `candidate_generation` medio: 9,28 / 8,42 / 8,66 / 9,09 / 8,21 / 9,19 s; `frontier_evaluation` ≈ 0,83–1,28 s; `screening` ≈ 0,07–0,12 s; `pareto` ≈ 0,01 s; total 9,05–10,38 s. Metadatos correctos (commit, `config_hash`, semilla, versiones) pero **`git_commit = 6af836c…+dirty`** (árbol sin commit; no reproducible desde un commit; L-1). No incluye **memoria**.

### Por qué el generador tarda 8–9 s (perfilado propio, `cProfile`, universo 50)

1. **No es el screening.** El screening cuesta 2,4–8,0 ms por llamada de N = 50 a 1.500 (crece ~linealmente y es despreciable: `screen_time_total` ≈ 0,05–0,13 s de un total de 5,6–6,8 s).
2. **Es el número de evaluaciones × el coste por evaluación.** 1200 evaluaciones = 3 perfiles λ × 2 fases (haz + pulido) × `max_evaluations = 200` (cada fase agota su propio presupuesto). Coste medido: **4,7–5,7 ms por composición evaluada** (mi máquina en reposo: búsqueda de 5,6–6,8 s; el JSON refleja 8–9 s; no he podido determinar la causa de la diferencia —posiblemente carga distinta de la máquina o árbol sin commit— y no la afirmo).
3. **Desglose del coste por evaluación** (perfil de 4,3 s): `evaluate` 2,5 s (de los cuales `_refine`, 15 iteraciones de gradiente proyectado con `project_box_budget` —ordenación de 2n puntos de ruptura por iteración—: 1,9 s; 19.648 llamadas) y `prepare` 1,5 s (compilación de restricciones 0,95 s, de ellos **`_constraint_hash` con `canonical_json` ≈ 0,4 s** y `composition_hash` ≈ 0,3 s: hashes de matrices que la búsqueda no necesita).
4. **Consecuencia:** el tiempo es **plano respecto al universo** (50 → 1.500: 5,6 → 6,8 s) porque la búsqueda está **limitada por presupuesto y por listas cortas** (`shortlist_in = 8`), no por el universo. Por tanto el benchmark **no mide el crecimiento con el universo** y no debe leerse como prueba de escalabilidad; sí muestra que el coste dominante por cartera es fijo.
5. **Extrapolación honesta (no medida):** ~6–7 s de búsqueda + ~1 s de fronteras por cartera ≈ 8 s en un proceso; 1.200 carteras serían del orden de **2,5 h en un solo proceso**. Eso justifica el Bloque 5 (paralelismo) pero **no lo demuestra**: no se ha medido con workers ni con las cargas reales; no afirmo escalabilidad.

### Oportunidades (no errores) antes del B5

* Hash de restricciones y de composición **perezosos** (solo cuando se reutilicen o se publiquen), no por cada vecino evaluado.
* `project_box_budget`: O(n²) por iteración con `n = 20` es aceptable; podría amortizarse con una raíz por bisección/Newton y reutilizando el orden entre iteraciones.
* Reevaluar el reparto del presupuesto (200 por fase y por perfil ⇒ 1200) y si los tres perfiles λ comparten trabajo (p. ej., el screening por nodo).
* Añadir al benchmark la memoria (`tracemalloc`) y una serie de universos donde el screening domine.

`total_evaluated`/`total_generated`, los tiempos por etapa y los rechazos están en `CandidateDiagnostics`; por eso el desglose es verificable.

---

## REGRESSION_VERDICT

**Veredicto: CONFORME.** Sin regresiones de B1/B2.

* Los 558 tests del baseline pasan sobre el código B3 (los 51 ficheros de test del baseline: **560 passed**; los +2 son los tests nuevos de `test_architecture_rules.py`). 796 − 560 = 236 tests nuevos en ficheros nuevos; 796 − 558 = 238 declarados ✓.
* **Diff de los dos ficheros de test modificados** (leído íntegro):
  * `tests/unit/config/test_config_hashing.py`: **+1 línea** (`"candidates"` en el conjunto esperado de secciones del snapshot). Amplía el alcance del snapshot de `ConfigHash`; no debilita ninguna aserción.
  * `tests/unit/test_architecture_rules.py`: **amplía** el grafo de dependencias (`parallel`, `candidates`; `frontiers` y `benchmark` pueden depender de `candidates`), **retira de `LATER_BLOCK_PACKAGES`** exactamente lo que el B3 implementa (`candidates`, `parallel`, `frontiers/global_frontier.py`, `constraints/integer.py`) **y mantiene prohibido** el resto (`scenarios`, `parallel/{batching,shared_data,worker,executor,threading_control}.py`, `staging`, `persistence`, `cache`, `engine.py`, `constraints/conic.py`, `metrics/cvar_metric.py`, backends Clarabel/MIP…), y añade **2 tests nuevos** (sin `hash()` ni estado aleatorio global; `candidates` independiente de solvers/frontiers/SciPy/OSQP). No se eliminó ni relajó ninguna aserción existente. Es una ampliación deliberada y documentada, coherente con lo hecho en B2.
* **796 passed no se acepta como prueba suficiente por sí sola** y no lo hice: además de las cuatro herramientas, ejecuté el baseline aparte, 15 mutantes, oráculos independientes de Pareto/costes/índices/beam y perfilado.

---

## ARCHITECTURAL_DEVIATIONS

Revisadas las 13 desviaciones de `ARCHITECTURE.md` §3.4:

| # | Desviación | Juicio |
|---|---|---|
| 1 | `tabu.py` no creado; 4 módulos añadidos (`universe_data`, `prepared`, `evaluation`, `expansion`) | Aceptable. Evitan duplicar el vecindario entre haz y búsqueda local. `candidates/` = 13 módulos: sin sobrefragmentación. |
| 2 | Sin `engine.py` | Aceptable (B6); `OPT-002` `PARTIAL`. |
| 3 | `candidates` no depende de `optimizers`/`frontiers`; `QPCompositionEvaluator` inyectado | **Correcto** y verificado: `test_candidate_engine_is_independent_of_solvers_and_frontiers` + `test_import_graph_is_acyclic`; el modo `QP_UTILITY` sin evaluador inyectado falla con error explícito. |
| 4 | Un perfil λ por región de la frontera | Justificado (una composición óptima para un λ cubre una zona); configurable. |
| 5 | Evaluación `PROJECTED_WEIGHTS` = cota inferior | Aceptable y bien etiquetada; contrastada con SLSQP; ver I-5 (ranking con cotas de distinta tensión). |
| 6 | `candidate_score` ≠ `estimated_utility_gain` | Correcto. |
| 7 | `EngineConfig.candidates` obligatorio, sin defaults en código | Correcto; `test_every_candidate_parameter_is_consumed_by_the_engine_code`. |
| 8 | `outputs/candidate_{schemas,builders}.py` nuevos | Correcto (no toca módulos B2). |
| 9 | `parallel/determinism.py` solo (sin multiprocessing) | Correcto y contenido: el paquete `parallel/` contiene únicamente `__init__.py` y `determinism.py`; el resto sigue prohibido por test. |
| 10 | Índices en tres niveles | Correcto. |
| 11 | `CompositionID` = `CompositionHash` | Correcto. |
| 12 | Solo `LiquidityFlag`; sin ADV/NAV; `FEA-006` NI | Ver L-2 (D-2). |
| 13 | Activo mantenido no elegible sin límite de incremento | **Es H-1.** |

Otras comprobaciones:

* **Dependencias circulares:** ninguna (test de grafo acíclico verde).
* **Hardcoding:** grep de literales numéricos en `candidates/`, `global_frontier.py`, `candidate_evaluator.py`, `integer.py`, `determinism.py`: sin literales de negocio; todos los parámetros vienen de `CandidateConfig` (24 campos, todos consumidos).
* **Configuraciones ignoradas:** no detectadas (test de consumo de parámetros). Sí hay una incoherencia de **documentación** sobre `max_evaluations` (L-3).
* **Stubs / funcionalidad prematura:** ninguno. No hay backends Clarabel/MIP nuevos, ni SQL/HPC, ni `multiprocessing`, ni caché (los resultados de `grep` sobre `portfolio_engine` para `multiprocessing|shared_memory|joblib|pyodbc|sqlalchemy` son cero; `clarabel/cvxpy` solo aparecen en `enums.py` y el router, preexistentes de B2).
* **Duplicación:** la deduplicación global es una segunda implementación (L-6).

---

## FINDINGS

### H-1 — HIGH — Un activo mantenido y no comprable puede aumentar su peso; todas las capas lo validan

* **Evidencia:** `constraints/compiler.py:213-250` (`_bounds` no recibe elegibilidad; solo aplica E-09 a restringidos); `candidates/eligibility.py` cabecera («Limitación conocida…») y `LIQUIDATE_ONLY ∈ ENTERABLE_STATUSES`; `ARCHITECTURE.md` §3.4 fila 13; `README.md:164`; `validation/composition_validator.py` (solo valida activos **nuevos**). Ningún test fija la conducta.
* **Impacto:** la frontera continua, las estimaciones del `CandidateEngine` y la `GLOBAL_CANDIDATE_FRONTIER` pueden proponer **comprar** un activo no elegible, ilíquido (o de `LiquidityFlag` desconocido con política `EXCLUDE`) o fuera del `InvestmentUniverse` **hasta `MaxWeight`**, y los puntos figuran como `is_valid_solution = True`, con banderas de eficiencia global. Contradice la política documentada (no recomprar) y la coherencia con E-09. Consecuencia operativa: recomendaciones de inversión que violan restricciones de elegibilidad/liquidez.
* **Reproducción:** ver §ELIGIBILITY_VERDICT (10 % → 100 %). Pasos mínimos: `make_problem(mu, Σ, [0.10, 0.90, 0, 0], config, universe_overrides={"EligibleFlag": [False, True, True, True], "MaxWeight": [1.0]*4})` con `mu[0]` alto; `ContinuousFrontierEngine(config).solve(problem, GROSS, RISK_AVERSION_GRID)`; leer `max(point.weights[0])` = 1,0 y `point.validation.is_valid` = `True`.
* **Recomendación:** (1) el usuario decide D-3 (recomendado: misma semántica que `HOLD_OR_REDUCE`, `0 ≤ w ≤ min(w_current, MaxWeight)`, para todo activo mantenido no comprable); (2) el compilador recibe la máscara de «comprable» (o una política equivalente) y fija la cota superior; (3) `SolutionValidator` recalcula la regla **desde los datos** (independiente del compilador) y rechaza el exceso; (4) `EligibilityFilter`, compilador y validador comparten una única definición; (5) tests: 10 % → 20 % rechazado en compilador, validador, estimador de candidatos y frontera; caso ilíquido y fuera de universo; acuerdo compilador/validador (como `test_policy_consistency`); (6) mientras tanto, `CAN-013` pasa a `PARTIAL`, y la limitación se fija con un test/`xfail` visible. Seguir la regla de no regresión de CLAUDE.md al tocar B2 (baseline de tests antes y después).

### M-1 — MEDIUM — El coste de generación de candidatos (≈ 4,7–5,7 ms por composición; 1200 evaluaciones) es alto y no escala con el universo por diseño del presupuesto

* **Evidencia:** JSON de benchmark (`compositions_evaluated = 1200` en los 6 `runs`; `candidate_generation` 8,2–9,3 s), perfilado propio (evaluación 58 %, `prepare` 34 %; hashes canónicos ≈ 16 %), escalado del screening 2,4→8,0 ms para N = 50→1.500.
* **Impacto:** ≈ 8 s por cartera y proceso; sin optimización, 1.200 carteras ≈ 2,5 h de un solo proceso (extrapolación, no medición). Además el benchmark es plano respecto al universo y **no puede sustentar** afirmaciones de escalabilidad.
* **Reproducción:** `tests.fixtures.candidates.universe_problem(N, 20, 7, config)` → `search(config, problem)`; `result.diagnostics.total_evaluated == 1200`; medir `time.perf_counter()`.
* **Recomendación:** antes del B5, hashes perezosos, revisar el reparto del presupuesto entre perfiles/fases y añadir memoria y un barrido donde el screening domine; no fijar un umbral arbitrario (no lo exijo). No hay error de diseño.

### M-2 — MEDIUM — El screening multiseñal contabiliza varias veces la misma información (señales muy correlacionadas)

* **Evidencia:** correlación de rango 0,92–0,96 entre `marginal_risk`, `diversification` y `covariance`; 0,78 entre α y `expected_utility_gain`; 0,82 entre α y `risk_adjusted_return` (`SCREENING_VERDICT`).
* **Impacto:** los pesos configurables no equivalen a influencias independientes; calibrar «un 25 % a riesgo» en realidad da más del doble de peso efectivo. Es heurístico (la selección final es por utilidad evaluada), de ahí MEDIUM y no HIGH.
* **Reproducción:** `CandidateScreening.screen(...)` sobre `universe_problem(200, 20, 7, config)`; `np.corrcoef(result.entrants.normalized)`.
* **Recomendación:** documentar la redundancia y/o ofrecer un conjunto ortogonal (p. ej. α, ΔU, sector, coste, liquidez); test de sensibilidad a la ponderación; test de robustez a outliers con `ZSCORE`.

### L-1 — LOW — BEN-009 creado unilateralmente; benchmark sobre árbol `+dirty`

* **Evidencia:** §BEN-009; `git_commit = …+dirty` en el JSON.
* **Impacto:** el total de requisitos deja de ser el base de reconciliación de 316; el JSON no es reproducible desde un commit.
* **Recomendación:** decisión **D-1** (recomendado: evidencia de `BEN-001/002/006`, total 316); regenerar el JSON tras el commit.

### L-2 — LOW — `FEA-006` (asignado al B3 por `IMPLEMENTATION_PLAN.md:171`) queda `NOT_IMPLEMENTED`

* **Evidencia:** `TRACEABILITY.md` (`FEA-006`, `CON-012`), `ARCHITECTURE.md` fila 12 («fuera del alcance solicitado del B3»).
* **Impacto:** el plan autorizado lo incluía; el prompt B3 no lo pide. Declarado con honestidad (CLAUDE.md), pero es una reducción de alcance frente al plan.
* **Recomendación:** decisión **D-2**: reasignarlo formalmente (B4/B5) en `IMPLEMENTATION_PLAN.md` o implementarlo.

### L-3 — LOW — `max_evaluations` es por fase y perfil, no «por perfil» como documentan los docstrings

* **Evidencia:** `candidate_engine.py` `_run_profile`: `EvaluationBudget(cfg.max_evaluations)` para el haz **y** otro nuevo `polishing_budget` para el pulido; `expansion.py` («presupuesto `max_evaluations` de un perfil»); 1200 = 3 × 2 × 200.
* **Impacto:** el cómputo real es el doble del que sugiere la documentación.
* **Recomendación:** corregir la documentación o el reparto; reflejarlo en la configuración de ejemplo.

### L-4 — LOW — La deduplicación por `visited` no está protegida por ningún test

* **Evidencia:** mutante `dedup_off` (desactivar `if digest in visited: continue` en `NeighborhoodExpander.expand`) **sobrevivió**: 53 tests en verde.
* **Impacto:** una regresión podría reevaluar composiciones ya vistas (gasto de presupuesto, posibles ciclos) sin que ningún test lo detecte, porque `pool` (por hash) y `select_survivors` enmascaran el duplicado.
* **Recomendación:** test que asegure `evaluated == número de composiciones distintas` y `duplicates_skipped > 0` en un caso diseñado.

### L-5 — LOW — `beam_width` gobierna a la vez el haz y el número de finalistas por perfil

* **Evidencia:** `_run_profile`: `select_survivors(finals, cfg.beam_width, …)`; `max_candidates` reparte después por rango.
* **Impacto:** ampliar el haz para explorar más cambia también cuántos candidatos por perfil salen; acoplamiento no necesario.
* **Recomendación:** parámetro separado (`finalists_per_profile`) si se quiere desacoplar; no urgente.

### L-6 — LOW — Duplicación de la lógica de equivalencia y bucles Python en elegibilidad

* **Evidencia:** `global_frontier._weights_close/_find_duplicates` frente a `dedup.is_equivalent/deduplicate` (B2); `EligibilityFilter._status/_reasons` con bucles por activo.
* **Impacto:** riesgo de divergencia de criterios; coste despreciable (una vez por cartera).
* **Recomendación:** documentar la diferencia (unión de activos) o factorizar.

### L-7 — LOW — Sin test de robustez a outliers en el screening con `ZSCORE`

* **Evidencia:** `tests/unit/candidates/test_screening.py` (no hay caso de outlier); la normalización por rango (por defecto) es robusta por construcción.
* **Impacto:** con `ZSCORE` un valor extremo comprime al resto y el ranking cambia sin aviso.
* **Recomendación:** test explícito, o advertencia en configuración.

### I-1 — INFO — Test de propiedades preexistente de B2 intermitente

* **Evidencia:** en la extracción limpia de `block2-validated` (sin base de ejemplos de hypothesis) la primera ejecución completa dio `1 failed, 557 passed`: `tests/property/test_invariants.py::test_every_frontier_point_satisfies_the_financial_invariants` con `SolverStatus.INFEASIBLE` en un punto de frontera de un ejemplo generado; 15 ejecuciones posteriores del mismo fichero pasaron, y la suite de B3 pasó (796). El fallo **no** es del Bloque 3 y no se pudo reproducir con semilla fija: 30 ejecuciones adicionales de ese test sobre una copia del árbol B3 con `--hypothesis-seed=1…30` (base de ejemplos vacía) pasaron todas.
* **Impacto:** un solver puede devolver `INFEASIBLE` para un problema generado que el test considera factible: posible caso límite de B2 que la frontera global hereda.
* **Recomendación:** fijar la semilla del ejemplo fallido cuando se reproduzca y decidir si es infactibilidad legítima (test demasiado estricto) o un problema numérico de B2. Fuera del alcance de B3.

### I-2 — INFO — El Bloque 3 no está commiteado

* Todo el trabajo está en el árbol de trabajo; el commit base del JSON de benchmark es el del baseline con `+dirty`. Auditar tras el commit reproducirá los hashes.

### I-3 — INFO — `CAN-014` (tabu) `NOT_IMPLEMENTED`

* Opcional según §30; el prompt del bloque 3 no lo lista. Estado honesto.

### I-4 — INFO — La generación de candidatos usa utilidad neta de costes incluso con tratamiento `GROSS`

* `CandidateEngine` evalúa `μᵀw − λ wᵀΣw − TC(w)` (con costes de liquidación) sea cual sea el tratamiento de la frontera posterior; en `GROSS` la selección de composiciones es cost-aware y la frontera no. Coherente con «partir de la cartera actual», pero conviene documentarlo.

### I-5 — INFO — Las estimaciones `PROJECTED_WEIGHTS` son cotas inferiores de 15 iteraciones

* Ordenan composiciones con cotas de distinta «tensión»; el modo `QP_UTILITY` da el óptimo exacto y está cubierto. Mis experimentos exhaustivos (5 semillas) no mostraron pérdida de calidad a escala pequeña.

### I-6 — INFO — Los vecinos que violan límites se generan y luego se rechazan

* Eficiencia menor (p. ej. 1259 rechazos por `MAX_NEW_ASSETS`), sin impacto de corrección.

### I-7 — INFO — Cobertura y cualidad de los tests nuevos

* **Buenos oráculos independientes:** Pareto por fuerza bruta (test y mi contraste), costes de liquidación calculados a mano, SLSQP como óptimo independiente para evaluación, búsqueda local y screening (α vs riesgo/costes), enumeración exhaustiva de composiciones, acuerdo exhaustivo `EligibilityFilter` ↔ validador independiente (3 políticas × 495 composiciones), hashes entre procesos, propiedades con hypothesis (60 ejemplos).
* **Mutación:** 15 de 16 mutantes detectados (beam greedy, ancho de haz, coste de salida, hash sin orden, `max_new`, `max_swaps`, Pareto sin estricta, solo la primera composición, mezcla bruto/neto, índice local, elegibilidad, tres signos de screening, referencia excluida); sobrevivió `dedup_off` (L-4). Sin oráculos ausentes: la elegibilidad de incremento (H-1).
* **Debilidades:** la comparación B=3 vs B=1 usa utilidades estimadas (cotas inferiores); el benchmark tiene 2 tests que verifican mecánica, no rendimiento; no hay test de outliers ni de reevaluación de duplicados.

---

## Higiene del diff (sección 16)

| Comprobación | Resultado |
|---|---|
| `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`, `IMPLEMENTATION_PLAN.md` | **Sin cambios** (`git diff block2-validated --stat` vacío) |
| `AUDIT_BLOCK_1.md`, `AUDIT_BLOCK_2.md`, `AUDIT_BLOCK_2_CLOSURE.md`, `README_USO.md`, `requirements-lock.txt` | **Sin cambios** |
| Documentos modificados | `ARCHITECTURE.md`, `CHANGELOG.md`, `README.md`, `TRACEABILITY.md` (los permitidos por el flujo) |
| `pyproject.toml` | +1 marcador `performance` (sin dependencias nuevas) |
| Secretos | `grep -i password\|secret\|api_key\|BEGIN PRIVATE` → 0 (solo tokens booleanos `_TRUE_TOKENS` preexistentes) |
| Binarios accidentales | Ninguno (mayor fichero nuevo: 28 KB, código; un JSON de benchmark de 13,7 KB) |
| Versión anterior | `1.-Version Anterior/` e `Instrucciones.txt` siguen ignorados por `.gitignore` y no aparecen en el diff |
| Código HPC/SQL/paralelo prematuro | Ninguno; `parallel/` contiene solo `determinism.py` |
| Estado del repositorio tras la auditoría | `git status --short`: 46 líneas antes de escribir este informe y 47 después (la línea añadida es `?? AUDIT_BLOCK_3.md`); ningún otro fichero cambió |

---

## Decisiones pendientes para el usuario

* **D-1:** ¿`BEN-009` es requisito o evidencia? Recomendación: evidencia de `BEN-001/002/006`; total 316.
* **D-2:** `FEA-006` (asignado al B3 en el plan): ¿implementar ahora o reasignar formalmente a B4/B5?
* **D-3:** contrato de un activo **mantenido y no comprable**: ¿`0 ≤ w ≤ min(w_current, MaxWeight)`? (recomendado) o ¿debe liquidarse? o ¿otra política? Debe quedar como enmienda en el Anexo A.

## Condiciones para pasar a `PASS`

1. Resolver H-1 (D-3 + compilador + validador independiente + tests) y bajar `CAN-013` a `PARTIAL` mientras tanto.
2. Regenerar el benchmark sobre un commit limpio (L-1) y aclarar el presupuesto (L-3).
3. Añadir el test de deduplicación (L-4).
4. Resolver D-1 y D-2 en la trazabilidad.

M-1, M-2 y el resto de LOW/INFO no bloquean el cierre del Bloque 3; M-1 debe tratarse antes del Bloque 5.

AUDIT_BLOCK_3_STATUS = PASS_WITH_CHANGES
