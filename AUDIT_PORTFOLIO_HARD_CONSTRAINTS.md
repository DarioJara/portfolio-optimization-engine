# AUDIT_PORTFOLIO_HARD_CONSTRAINTS — Auditoría de las restricciones sobre carteras finales

> Alcance: ¿impide el motor, **en `main` `75d8bb5`**, que se generen carteras finales con cardinalidad no
> deseada, demasiadas sustituciones, volatilidad fuera de límites o concentración excesiva? Rama de
> trabajo: `feature/hard-constraints-final-portfolios` (desde `origin/main`; no se toca el PR #9 de B5.5).
> Método: lectura del código (`MASTER_SPEC.md` §12, §13, §21, §26, §44; `portfolio_engine/`), ejecución de
> los tests existentes como baseline y una medición reproducible sobre el motor sin modificar.
> Diseño: `HARD_CONSTRAINTS_DESIGN.md`. Implementación y resultados: `HARD_CONSTRAINTS_IMPLEMENTATION_REPORT.md`.

## 1. Veredicto

**El motor NO impide hoy esas carteras.** Los límites de B3 (`max_new_assets`, `max_swaps`,
`target_portfolio_size`) restringen la *composición candidata* (el conjunto de activos), no los *pesos
finales*, y ninguna validación posterior cuenta posiciones reales, sustituciones respecto a la cartera
original, concentración ni volatilidad mínima. Medición (§3) sobre una cartera de 11 posiciones: el
motor sin modificar publica como `is_valid_solution = True` puntos con entre 2 y 10 posiciones
y con hasta 5 sustituciones.

## 2. Inventario de mecanismos existentes (baseline `main`)

| Mecanismo | Dónde | Qué restringe | Qué **no** garantiza |
|---|---|---|---|
| `candidates.max_new_assets` | `config/candidate_config.py`; `constraints/integer.py` (`CompositionLimits`) | altas `a` de una **composición** respecto a la cartera actual (poda de la búsqueda + `validate_candidate_composition`) | pesos finales; bajas; sustituciones uno a uno |
| `candidates.max_swaps` | ídem | `max(a, r)` de la composición | ídem; no distingue sustitución de alta/baja independientes |
| `PortfolioSpec.target_portfolio_size` | `models/portfolio.py`; `CandidateEngine._target_size` | tamaño **de la composición**; si falta, `len(cartera actual)` | número de posiciones con peso `> 0`: el optimizador puede dejar miembros a cero |
| `CompositionLimits` | `constraints/integer.py` | `target_size`, `max_new_assets`, `max_swaps`, `mandatory` | sin retirados, total, sustituciones, intervalo de tamaño |
| `constraints.global_min/max_weight`, `weight_bound_overrides` | `models/portfolio.py::resolve_effective_weight_bounds`; compilador | cotas lineales por activo (precedencia override > global > universo) | un override puede **ensanchar** el máximo global sin rastro ni autorización |
| `frontier.min_holding_weight` | `frontier_config.py`; `compiler.py:338` | peso mínimo estricto de todo miembro (A-08) | es opcional; sin él, miembros a cero |
| `SolutionValidator` | `validation/solution_validator.py` | presupuesto, cotas, grupos, turnover, restringidos, no comprables, ADV/NAV, retorno objetivo; de la varianza solo `w'Σw >= 0` | cardinalidad, sustituciones, volatilidad, concentración |
| `AdvancedSolutionValidator` | `validation/advanced_validator.py` | `VOLATILITY_LIMIT` (**máximo**), CVaR, Sharpe, escenarios, cardinalidad `EXACT_MIP` | solo se invoca en `StrategyOptimizer`/multiescenario, no en la frontera global |
| `PortfolioSpec.volatility_limit` | `models/portfolio.py`; `strategy_optimizer.py` | `σ <= σ_max` como SOCP en las **estrategias** | la frontera QP lo **rechaza** (`ContinuousFrontierEngine.reject_unenforced_constraints`); no existe `σ_min` |
| `check_cardinality` (FEA-002), `check_volatility` (FEA-005) | `constraints/feasibility.py` | factibilidad previa de cardinalidad frente a pesos y de `σ_max` frente a la cota determinista | no consideran presupuestos de cambio, política de tamaño, HHI ni `σ_min` |
| `ConfigHash` | `config/hashing.py` | hash del motor completo | sin parámetros efectivos por cartera ni procedencia |

## 3. Hallazgos

Medición (script reproducible en `HARD_CONSTRAINTS_IMPLEMENTATION_REPORT.md` §6): universo de 16 activos
(`tests.fixtures.candidates.random_problem(16, held=[0..10], seed=11)`), cartera original de 11
posiciones iguales, configuración de ejemplo del repositorio, `GlobalCandidateFrontierEngine.solve`
(GROSS, malla de aversión al riesgo). Posición = `w_i > 1e-8`.

| Resultado del motor **sin modificar** | Valor |
|---|---|
| puntos publicados / marcados `is_valid_solution` | 240 / **240** |
| composiciones candidatas (todas de tamaño 11) | 12 |
| puntos válidos con **11** posiciones | 45 |
| puntos válidos con **menos de 11** posiciones (de 2 a 10) | **195** (81 %) |
| sustituciones uno a uno por punto (`min(a, r)`) | 0: 20 · 2: 21 · 3: 68 · **4: 113 · 5: 18** |
| puntos con más de 3 sustituciones | **131** (55 %) |
| rango de volatilidad de los puntos válidos | 0,0187 – 0,1523 (ninguna banda declarable) |

| ID | Hallazgo | Gravedad | Evidencia |
|---|---|---|---|
| **G-1** | La cardinalidad se impone a la *composición*, no a los *pesos*. Sin `min_holding_weight` el QP deja miembros a cero y el punto se publica como válido con menos posiciones que el mandato. | Alta | tabla anterior (195/240); `compiler.py:338` solo aplica el mínimo si está configurado |
| **G-2** | No hay límites de bajas, cambios totales, sustituciones uno a uno ni altas/bajas independientes; `max_swaps = max(a, r)` no los sustituye. | Alta | `CompositionLimits` solo tiene 3 límites; 131 puntos con > 3 sustituciones |
| **G-3** | Cardinalidad fija a la original: no existe política `INCREASE`/`DECREASE` ni intervalo `min_size`/`max_size`. | Media | `CandidateEngine._target_size` |
| **G-4** | No existe volatilidad mínima; la máxima solo se impone en estrategias, y la frontera global **rechaza** una cartera con `VolatilityLimit` en lugar de aplicarlo. | Alta | `reject_unenforced_constraints`; `SolutionValidator._variance` solo comprueba `>= 0` |
| **G-5** | La concentración existe solo como *métrica descriptiva* (`PointMetrics.herfindahl_index`), nunca como restricción; tampoco hay `N_eff` ni peso máximo/mínimo *por posición* distinto de las cotas por activo. | Media | `models/frontier.py::PointMetrics`; ninguna validación lo consulta |
| **G-6** | Sin precedencia documentada ni autorización de relajamiento: un override de cartera puede ensanchar un límite global; no hay hash de parámetros efectivos por cartera. | Media | `resolve_effective_weight_bounds` (override > global) |
| **G-7** | Sin validación final de propuesta: la aceptación depende de `is_valid_solution` (B2), que no conoce el mandato; no se registran causas de rechazo de mandato. | Alta | `FrontierPoint.is_valid_solution`; `GlobalFrontierResult.envelope` |
| **G-8** | Sin suelo de retorno esperado (`μᵀw >= μᵀw0`). | Media | solo `RETURN_TARGET` interno de la frontera objetivo |
| **G-9** | Tolerancias de validación heredadas del solver (`1e-7`) sin techo de materialidad para una banda estrecha. | Baja | `ValidationTolerances` |
| **G-10** | Sin factibilidad previa que combine cardinalidad, activos obligatorios/elegibles y presupuestos de sustitución. | Media | `FEA-002` solo mira pesos |

## 4. Cobertura de cada punto del encargo

Clasificación: **existía** (reutilizado tal cual), **se amplió** (existía y se extendió) o **desde cero**.

| Punto del encargo | Mecanismo | Clasificación |
|---|---|---|
| 1. `candidates.max_new_assets` / `max_swaps` / `target_portfolio_size` / `CompositionLimits` | integrados en el mandato (`max_added_assets`, `max_swaps`, `target_size`) | **se amplió** (`CompositionLimits` + 7 campos) |
| 1. `max_removed_assets`, `max_total_changed_assets`, `max_replacements` (+ altas/bajas independientes) | `CompositionLimits`, `counts.py`, validación final | **desde cero** |
| 1. Comprobar respecto a la cartera original y el resultado final | poda en búsqueda, validación de composición, validación de pesos | **desde cero** (los dos últimos niveles) |
| 2. Política `FIXED`/`INCREASE`/`DECREASE`, `target_size`, `min_size`/`max_size` | `resolver.py`, `candidate_engine.search_with_mandate`, `merge.py` | **desde cero** |
| 2. Incompatibilidades antes de optimizar | `preflight.py` | **desde cero** (amplía FEA-002) |
| 2. Cardinalidad = posiciones reales, sin recortar pesos | umbral `τ` único, `min_active_weight > 0` obligatorio, conteo en validación | **desde cero** |
| 3. `min_volatility`, `max_volatility`, `HARD`, sobrescritura por perfil y cartera | `MandateSettings`, resolvedor, gate, `volatility_band.py` | `max`: **se amplió** (`PortfolioSpec.volatility_limit`); `min` y banda: **desde cero** |
| 3. Recalcular con la `Σ` oficial; tolerancia no material | `validator.py` (`official_moments`, `volatility_tolerance`) | **desde cero** |
| 3. No convexidad de `σ_min` | `volatility_band.py` + `HARD_CONSTRAINTS_DESIGN.md` §7 | **desde cero** |
| 3. `INFEASIBLE` / `NO_FEASIBLE_SOLUTION` | `AuditStatus`, `BandOutcome` | **desde cero** |
| 4. `global_min/max_weight`, `min_holding_weight`, `weight_bound_overrides` | se integran como nivel global/portafolio | **existían** (+ regla de endurecimiento) |
| 4. `min/max_active_weight`, `max_concentration_hhi`, `min_effective_number_of_positions` | resolvedor, validación final, cono en la banda | **desde cero** |
| 4. `diversification_penalty_weight` (objetivo secundario) | `ranked_point_ids` | **desde cero**, `PARTIAL` (no entra en el objetivo del solver) |
| 5. Precedencia global > perfil > cartera, autorización, hash | `resolver.py`, `RelaxationAuthorization`, `effective_hash` | **desde cero** |
| 6. Validación final obligatoria y causas de rechazo | `FinalProposalValidator`, `HardConstraintGate` | **desde cero** (reutiliza `validate_candidate_composition` y el estado/validez B2) |
| 7. Tests de aceptación 1–13 | `HARD_CONSTRAINTS_TEST_MATRIX.md` | **desde cero** |

## 5. Riesgos y limitaciones detectadas durante la auditoría

* **R-1.** `HOLD_OR_REDUCE` (E-09) y los activos no comprables (E-10) pueden llegar a cero por diseño; el
  mandato no los fuerza (la validación final rechaza el punto si rompe la cardinalidad).
* **R-2.** `Σ w²` y `N_eff` no se pueden imponer en la frontera QP sin cambiar la clase del problema
  (QP → SOCP); se validan, y se imponen solo en la estrategia de banda.
* **R-3.** `σ >= σ_min` es no convexa: no hay certificado global general (NP-difícil); véase el diseño.
* **R-4.** La búsqueda de composiciones sigue siendo heurística (B3): un mandato puede ser factible y no
  encontrarse (`NO_FEASIBLE_SOLUTION` no es una prueba de inviabilidad).
* **R-5.** Las operaciones distintas de `GLOBAL_FRONTIER` no pasan por la validación final (se rechazan
  con mandato; decisión D-2).

## 6. Baseline de no regresión

Antes de modificar módulos validados se ejecutaron los tests existentes del área afectada
(`tests/unit/{constraints,validation,config,candidates}`): **556 passed** (143 s). Tras la implementación
véase `HARD_CONSTRAINTS_IMPLEMENTATION_REPORT.md` §4 (suite completa). El `ConfigHash` de la
configuración de ejemplo se conserva (`86af211e`).
