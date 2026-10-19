# AUDIT_BLOCK_4 — Auditoría cuantitativa independiente del Bloque 4

Auditor: revisión adversarial independiente (no implementación). Fecha: 2026-09-26.
Rama: `block4-scenarios-robust-optimization`. Baseline: tag `numerical-f3-validated` (= `HEAD` = `1c079f6`).
Alcance de escritura de esta auditoría: **solo este fichero**. No se modificó código, tests ni documentación
existentes; no hay commit, merge, push, tag ni PR. Todas las copias de trabajo (mutantes, baseline extraído con
`git archive`, scripts de sondeo, un rerun del benchmark) viven fuera del repositorio, en el directorio de
scratchpad de la sesión.

---

## 1. Executive Summary

**Veredicto: `PASS_WITH_CHANGES`.**

La parte matemática del Bloque 4 es sólida y se sostiene bajo contraste independiente: Max Sharpe
(Charnes–Cooper/SOCP), control de volatilidad, CVaR (Rockafellar–Uryasev), robustez (caja/elipsoide/Σ escalada),
los tres modos multiescenario de solución única y el MIQP de cardinalidad coinciden con oráculos que **no** usan
las formulaciones bajo prueba (SLSQP, fórmula cerrada, enumeración exhaustiva, cálculo directo de CVaR) con
diferencias de 1e-10 a 1e-6. Los escenarios transforman realmente los datos. El routing es real (Clarabel, HiGHS,
OSQP y SCIP se ejecutan de verdad). No hay regresión: 240 puntos de frontera B2 son **idénticos bit a bit** al
baseline. 27 de 29 mutantes fueron detectados.

Sin embargo, se encontró **un defecto funcional real de severidad HIGH** y **una declaración de gate falsa**:

| ID | Sev. | Resumen | ¿Bloquea el cierre? |
|----|------|---------|---------------------|
| F-01 | **HIGH** | `PortfolioSpec.volatility_limit` se **ignora en silencio** en `MIN_CVAR`/`CVAR_LIMITED`, `ROBUST`, `WORST_CASE` y `BASE_WITH_STRESS`; el resultado sale `is_valid_solution=True` con volatilidad 1,3×–2,5× el límite | **Sí** |
| F-02 | **MEDIUM** | `ruff format --check .` **falla** (`README.md:223`); la declaración «Ruff format --check: PASS» es falsa. Regresión introducida por B4 (el baseline pasa) | **Sí** (corrección trivial) |
| F-03 | MEDIUM | `SharpeOutcome.OPTIMAL` se asigna con independencia del estado del solver y de la validación; detección de volatilidad cero inconsistente | No (recomendado antes del cierre) |
| F-10 | MEDIUM | Estados de `NCV-001` (VALIDATED) y otros divergen de `IMPLEMENTATION_PLAN.md` | No (decisión documental) |

Reproducido de forma independiente: **1454 tests pasan, 0 fallan** (486,9 s); `mypy --strict portfolio_engine` PASS
(158 ficheros); `ruff check .` PASS; `ruff format --check .` **FAIL** (1 fichero, Markdown). Trazabilidad reconcilia
exactamente: 316 = 224 VALIDATED + 38 PARTIAL + 0 IMPLEMENTED + 54 NOT_IMPLEMENTED.

Limitaciones honestas de esta auditoría (ver §2.3): no leí íntegramente `MASTER_SPEC.md` ni los informes históricos
B2/B3/F-3 (consulté las secciones y requisitos relevantes por búsqueda dirigida); no ejercité de forma
independiente ADV/NAV, FX ni E-09/E-10/E-11 sobre las formulaciones nuevas más allá de lo que ya cubren los tests
existentes (que pasan).

---

## 2. Scope and Baseline

### 2.1 Precheck (ejecutado)

| Comprobación | Resultado |
|---|---|
| `git branch --show-current` | `block4-scenarios-robust-optimization` ✓ |
| `git tag --list numerical-f3-validated` | presente; apunta a `1c079f677b9aa6343f47262b0777085b515c1892` = `HEAD` |
| Commits sobre el baseline | **0**: todo el Bloque 4 está sin commit |
| `git diff --stat numerical-f3-validated` | 33 ficheros modificados, +1362 / −145 |
| Ficheros sin seguimiento | 55 ficheros (≈13 257 líneas) — módulos, tests, benchmark, un JSON de resultados |
| `git diff --check` | sin errores de espacios; solo avisos «LF will be replaced by CRLF» en 4 ficheros |

Ficheros de producción modificados sobre el baseline (extracto relevante): `config/*` (6 secciones nuevas),
`constraints/{feasibility,integer}.py`, `frontiers/{continuous_frontier,global_frontier,candidate_evaluator,
numerical_recovery,session}.py`, `models/{enums,solution}.py`, `optimizers/{router,status,problem,osqp_backend,
highs_backend,__init__}.py`, `exceptions.py`, `metrics/__init__`, `outputs/__init__`, `validation/__init__`.
Cambios en módulos B2/B3/F-3 (`git diff` línea a línea): `SolverRouter(..., inner_loop=True)` en
`ContinuousFrontierEngine` y en `numerical_recovery`; `reject_unenforced_constraints` (rechazo explícito de
`VolatilityLimit` en fronteras QP); reclamos de optimalidad en los backends OSQP/HiGHS; guarda
`type(problem) is not CanonicalProblem` (un cono/entero jamás llega a OSQP/HiGHS). Ningún cambio económico.

`MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`, `IMPLEMENTATION_PLAN.md`, `AUDIT_*`, `REMEDIATION_*`,
`F3_POST_MERGE_REVIEW.md` **no** figuran en `git diff --name-status` (intactos). Modificados: `ARCHITECTURE.md`,
`CHANGELOG.md`, `README.md`, `TRACEABILITY.md` (esperado por CLAUDE.md).

### 2.2 Entorno de verificación

`.venv` del proyecto: Python 3.13.6, numpy 2.5.3, scipy 1.18.1, osqp 1.1.3, clarabel 0.11.1, PySCIPOpt 6.2.1,
pytest 9.1.1, mypy 2.3.1, ruff 0.16.8, hypothesis 6.168.1. Coinciden con `requirements-lock.txt`.
Nota: el `python` del PATH (global) **no** tiene `hypothesis`; con él la recolección falla (3 errores). Se usó `.venv`.

### 2.3 Qué leí y qué no

Leído por completo: `CLAUDE.md`, todos los módulos B4 nuevos relevantes (`conic`, `sharpe`, `volatility`, `cvar`,
`robust`, `multi_scenario` (formulación y orquestador), `miqp`, `scenario_engine`, `scenario_definitions`,
`clarabel_backend`, `scip_backend`, `nonconvex_backend`, `router`, `status`, `advanced_validator`,
`strategy_optimizer`, `exact_mip_validation`, `cvar_metric`, `robust_metric`, `shrinkage`, `models/cvar`,
`cvar_config`), el bloque B4 de `IMPLEMENTATION_PROMPTS.md`, `ARCHITECTURE.md` §3.6, el bloque B4 de
`IMPLEMENTATION_PLAN.md` y la matriz de `TRACEABILITY.md` (parseada). Leído de forma **parcial/dirigida**:
`MASTER_SPEC.md` (enmiendas E-24/E-25, requisitos citados), `CHANGELOG.md`, `README.md`, informes B2/B3/F-3
(búsqueda de las cifras «77 puntos» y de las interfaces). No sostengo haber leído íntegramente esos documentos.

---

## 3. ScenarioEngine Verdict — **PASS**

Ejecutado (`m_scn.py`): los diez `ScenarioType` (`BASE, BULL, BEAR, STRESS, RATE_UP, RATE_DOWN, EQUITY_CRASH,
CREDIT_WIDENING, FX_SHOCK, CUSTOM`) se construyeron con datos declarados y **todos** producen `μ_s`, `Σ_s`
distintos de la base (Δμ de 0,010 a 0,120; ΔΣ de 0,006 a 0,060; ScenarioHash distinto para cada uno).

* **Diseño anti-etiqueta:** un escenario no-BASE/no-CUSTOM sin transformaciones se rechaza (`ConfigError`,
  comprobado). El tipo es solo una etiqueta; ninguna magnitud está en el código (revisado `scenario_definitions.py`
  y `scenario_engine.py`; sin constantes financieras hardcodeadas). Esto satisface la exigencia de que un
  escenario «con nombre distinto pero datos idénticos» no sea funcional: no puede construirse.
* **Contraste analítico independiente** (shock sectorial `μ' = μ·a + b`, escala de volatilidad `Σ' = DΣD`,
  estrés de correlación `R' = (1−ρ)R + ρ·R_obj`): error máximo **0,0** en μ y Σ frente a mi cálculo con numpy.
* **Costes y restricciones:** multiplicador ×3 aplicado a compra y venta (ratio 3,0 exacto); overrides de
  `max_turnover` (0,05) y `global_max_weight` (0,3) presentes en `constraints_s`; costes base intactos.
* **Preservación:** tras `build`, `mu` y `Σ` originales son idénticos (aserción ejecutada); el escenario BASE sin
  modificaciones es el **mismo objeto** que el modelo base.
* **Σ PSD:** autovalor mínimo > 0 en los diez. Un `Σ` personalizado no-PSD (autovalor −1·0,04) **se acepta con
  reparación registrada** (`covariance_repair = EIGENVALUE_FLOOR`, λ_min tras reparar ≈ 1,2e-11): conforme al
  contrato «reparación solo si la configuración lo autoriza y queda registrada». Observación INFO: la lista
  `transformations` del escenario no menciona la reparación (sí lo hace el campo `covariance_repair`).
* Selector sin coincidencia → `ScenarioError` (una transformación que no actúa nunca se ignora).
* Determinismo: hashes idénticos en dos construcciones independientes.
* Mutantes: M17 (shock de volatilidad no aplicado) y M18 (shock de coste no aplicado) **detectados**.

Límite de la evidencia: los shocks se validaron con selector `ALL`/`SECTOR`. No probé `COUNTRY`/`CURRENCY`/
`ASSET_CLASS` por mi cuenta (cubiertos por `test_scenario_engine.py`, que pasa).

---

## 4. Multi-Scenario Verdict — **PASS** (con F-01)

Caso construido (`d_multi.py`): 4 activos; BASE (p=0,7) favorece `A000` (peso óptimo 0,296); STRESS (p=0,3,
`CUSTOM`, μ de `A000` = −10 %, volatilidad ×3) hace que la solución independiente sea `[0,0,0,1]`.

| Modo | Solver | Resultado del motor | Oráculo SLSQP (definición matemática) |
|---|---|---|---|
| ExpectedScenarioUtility | OSQP | `[0, .10351, .07287, .82362]` | `[0, .10351, .07287, .82362]` ✓ |
| WorstCase | Clarabel | `[0, .05551, .03843, .90607]`, t=0,036221 | idéntico; `min_s U_s(w)` = 0,036221 ✓ |
| BaseWithStressConstraints | Clarabel | `[.13144,.13937,.10546,.62373]`, vol_STRESS = 0,120000 | `[.13145,.13936,.10545,.62374]` ✓ |
| ScenarioIndependent (BASE) | — | difiere de las tres soluciones conjuntas | — |

La solución de BaseWithStress optimiza la utilidad de BASE e impone `√(wᵀΣ_STRESS w) ≤ 0,12` (la solución
independiente de BASE tendría 0,178 en STRESS). Las tres soluciones conjuntas difieren de la independiente
(diferencia > 1e-2): no es «varios problemas independientes etiquetados como conjunto».

* **ExpectedScenarioUtility** usa `Σ p_s(μ_sᵀw − λ wᵀΣ_s w) − Σ p_s TC_s`, matemáticamente igual a la utilidad de
  los parámetros ponderados (lineal en los parámetros); no usa la varianza de la mezcla. Mutante M15b (ignorar
  probabilidades en `_aggregate_model`) **detectado**; M19 (no exigir Σp=1) **detectado**; M16 (signo del epígrafe
  del peor caso) **detectado**; M4 (omitir `constraints_s`), M4b, M4c **detectados**.
* Las restricciones de todos los escenarios se **intersectan** (`intersect_constraint_configs`) y se validan por
  escenario (`ScenarioCheck`).
* **Problema (F-01):** estas rutas no aplican `PortfolioSpec.volatility_limit` (ver §12/§19).
* INFO (F-05): `expected_moments` (`formulations/multi_scenario.py:114`) es **código muerto** (nadie lo llama; la
  agregación real es `MultiScenarioOptimizer._aggregate_model`). El mutante M15 sobre esa función sobrevivió por
  ese motivo.

---

## 5. SolverRouter Verdict — **PASS**

* `route()`: `QP → OSQP`, `LP → HiGHS`, `SOCP → Clarabel`, `MIQP/MIQCP/MISOCP → SCIP` **solo** si el problema es
  un `MixedIntegerProblem`; SDP → `RoutingError`; NLP no convexo sin algoritmos → `RoutingError`.
* **Ejecución real, no nominal:** en todos mis sondeos `StrategyResult.solver_names` fue `('CLARABEL',)`,
  `('OSQP',)`, `('HiGHS',)` según correspondía (Sharpe/vol/peor caso/estrés → Clarabel; utilidad esperada y
  robusta de caja → OSQP; CVaR → HiGHS). MIP ejecutado con SCIP (b&b real: 1 493 nodos en el caso de 40 activos).
* Un MIQP nunca llega a OSQP: `_linear` exige `type(problem) is CanonicalProblem`; `_mixed_integer` exige
  `MixedIntegerProblem`; los backends OSQP/HiGHS rechazan tipos derivados (`SolverError`). Mutante M5 (mixto
  tratado como no mixto) **detectado**.
* Un SOCP no se degrada a QP: un `ConicProblem` declarado como QP se rechaza (`_conic_backend`); OSQP rechaza
  `ConicProblem`. Guarda `inner_loop`: `EXACT_MIP` y `NONCONVEX` rechazados con `inner_loop=True` (los motores
  continuo/global/recuperación se construyen con `inner_loop=True`).
* Textos de estado reales de Clarabel 0.11.1 verificados: `Solved`, `PrimalInfeasible`, `DualInfeasible`
  (ejecutados sobre LPs triviales); el mapa `map_clarabel_status` da `OPTIMAL`, `INFEASIBLE`, `UNBOUNDED`,
  `AlmostSolved → OPTIMAL_INACCURATE`. Mutante M9 (promover `AlmostSolved` a `OPTIMAL`) **detectado**.
* `OPTIMAL_INACCURATE` no se promociona: `accept_inaccurate_solutions=false` por defecto; `assemble()` marca
  `is_valid_solution=False` con `OPTIMAL_INACCURATE` (comprobado). `SolveResult` impone además `x` ⇔ estado usable.

---

## 6. Clarabel / SOCP Verdict — **PASS**

**Álgebra de la factorización** (`conic.py`): `Σ = L Lᵀ` por autovalores; el cono usa `‖Lᵀw‖`. Verificado
numéricamente con `Σ` 3×3 no diagonal: `wᵀΣw = 0,022825`, `‖Lᵀw‖² = 0,022825` (error 2e-17), mientras que
`‖Lw‖² = 0,011509` (**incorrecto**, no coincide). El error de transposición sería, por tanto, detectable.
Mutantes: M1 (`transpose` devuelve `L`) y M1b (`volatility_cone` incrusta `L` en lugar de `Lᵀ`) **detectados**.

* Traducción a Clarabel (`to_conic_form`): `A x + s = b`, `s ∈ SOC`, con `A = −[aᵀ; F]`, `b = [c; g]`, lo que
  representa `‖Fx+g‖ ≤ aᵀx+c`. Correcto; contrastado por las coincidencias con SLSQP de §3–§9.
* Cono rotado para `wᵀΣw ≤ h`: `‖(2Lᵀw, h−1)‖ ≤ h+1`, equivalente correcto; mutante M11 (`h−1 → h+1`) **detectado**.
* **Σ singular / casi singular:** el rango se determina por umbral relativo; Σ 3×3 singular (rango 2) → error de
  reconstrucción 1,7e-16. Σ casi singular (rango 1 + 1e-13·I) con `VOL_TARGET`: `OPTIMAL`, válido, volatilidad
  recalculada 0,04000000001. Σ no PSD → `NotPositiveSemidefiniteError` (nunca «arreglada» en silencio).
* **VolatilityLimit** (sondeo `e_edge.py`, `four_asset_problem`, σ_libre = 0,0964):
  límite no vinculante (0,1446) → `VOL_TARGET` activo en el límite (0,14465 ≤ 0,1446), Max Sharpe = solución libre;
  límite vinculante (0,0868) → volatilidad recalculada 0,08679 ≤ 0,0868 en ambos; límite imposible (0,05 <
  cota inferior 0,0861) → `INFEASIBLE` con causa `VOLATILITY_LIMIT_BELOW_DETERMINISTIC_BOUND`, sin invocar el solver.
* Iteraciones, tiempos y residuales primal/dual se propagan en `SolveResult`; `x` solo se expone con estado usable.

---

## 7. Max Sharpe Mathematical Verdict — **PASS** en la matemática; **F-03** en el etiquetado

**Demostración de validez.** Sea `N(w) = (μ−rf)ᵀw − TC(w)` (o sin `TC` en bruto), con `TC` convexa lineal a
trozos: `TC(w) = (c_bᵀb + c_sᵀs + K_E)/H`, `w − b + s = w₀`, `b,s ≥ 0`. Con `y = κw`, `κ > 0`: el problema
`min ‖Lᵀy‖ s.a. N(y,κ) ≥ 1` y todas las restricciones homogeneizadas es convexo y su óptimo `r*` satisface
`Sharpe* = 1/r*` porque `N` y la volatilidad son homogéneas de grado 1 en `(y,κ)` (incluida la constante `K_E`
como `(K_E/H)·κ`, y `b',s'` como `κ·b, κ·s`). Las restricciones **no homogéneas** se conservan íntegramente:

* presupuesto `1ᵀy = Bκ`; cotas `l_iκ ≤ y_i ≤ u_iκ` (cotas efectivas compiladas: E-09, E-10, ADV/NAV incluidos);
* grupos `g_minκ ≤ Gy ≤ g_maxκ`; lifting `y − b' + s' = w₀κ`; turnover `½(1ᵀb'+1ᵀs') ≤ (T_c − exit)κ`;
* volatilidad `‖Lᵀy‖ ≤ σ_maxκ`.

Si faltan cotas finitas el constructor **rechaza** (`UnsupportedCombinationError`); no se transforma un problema
distinto del solicitado.

**Contraste numérico independiente** (`a_sharpe.py`, SLSQP multi-arranque sobre el **problema financiero
original**, con `cost_model.cost(w)` real, no sobre el transformado):

| Caso | Sharpe motor | Sharpe SLSQP | Δ |
|---|---|---|---|
| GROSS, MaxWeight 0,35 (cotas activas) | 0,6056108968 | 0,6056108969 | −1,1e-10 |
| GROSS, MaxWeight 0,35 + turnover 0,08 | 0,5950577903 | 0,5950577904 | −1,1e-10 |
| NET, MaxWeight 0,6 + turnover 0,10 + w₀ asimétrico | 0,5843555642 | 0,5843555644 | −1,8e-10 |
| NET, sin cotas activas | 0,6071333461 | 0,6071333461 | −3e-12 |

Pesos idénticos a 5 decimales; turnover recalculado 0,0799999994 ≤ 0,08. Cartera tangente analítica
(`w ∝ Σ⁻¹(μ−rf)`) reproducida en `test_max_sharpe.py` (pasa). Presupuesto siempre 1,0 (`compiled.budget=1.0`), por
lo que `(μ−rf)ᵀw = μᵀw − rf` es consistente.

**Estados:**

| Situación | Resultado observado |
|---|---|
| exceso de retorno máximo ≤ 0 (μ < rf) | `outcome=NOT_APPLICABLE`, `is_valid=False`, sin pesos ✓ (`MAX_ACHIEVABLE_EXCESS_RETURN=-0.005`) |
| restricciones incompatibles (ΣMaxWeight < 1) | `INFEASIBLE` previo al solver, causa explícita ✓ |
| volatilidad cero con exceso positivo | **ver F-03** |
| Σ casi singular sin núcleo explotable | `OPTIMAL`, válido ✓ |

**Óptimo global:** justificado (problema convexo; `OptimalityClaim.CONVEX_GLOBAL` solo con estado `OPTIMAL`).

Mutantes: M2 (ignorar `w₀κ`), M2b (presupuesto sin `κ`), M2c (offset de coste NET), M14 (omitir precondición
A-13) **detectados**.

---

## 8. CVaR Verdict — **PASS** con observaciones LOW

Formulación: `min α + 1/(1−β) Σ π_t u_t`, `u_t ≥ −r_tᵀw − α`, `u_t ≥ 0`; pérdida `L = −rᵀw`. Correcta.

* **Cálculo manual** sobre una distribución discreta de 10 escenarios equiprobables (pérdidas 0,05; 0,04; 0,03;
  0,02;…): `CVaR₉₀ = 0,05` ✓ (peor átomo); `CVaR₈₀ = 0,04` ✓ (media de 0,05 y 0,03); `CVaR₈₅ =
  (0,10·0,05 + 0,05·0,03)/0,15 = 0,043333` ✓ (átomo frontera fraccionado); `VaR₉₀ = 0,03`, `VaR₈₀ = 0,02` ✓.
  `metrics/cvar_metric.py` no usa Rockafellar–Uryasev ni solver.
* **Minimizar CVaR vs. restringir CVaR ≤ MaxCVaR** son problemas distintos, ambos verificados (`b_cone_cvar.py`,
  2 activos, T=40, `MaxWeight=1`, oráculo por rejilla de 2 000 puntos con CVaR directo):
  * `MIN_CVAR` β=0,90: motor `w=[.7733,.2267]`, CVaR recalculado 0,0330002; rejilla 0,0330015 ✓; β=0,80: 0,0280591 vs 0,0280592 ✓.
  * `MAX_RETURN_WITH_LIMIT` (límite = 1,3×mín): motor retorno 0,065306 con `w=[.4898,.5102]`, CVaR recalculado
    0,0429003 = límite; rejilla `w=[.48985,.51015]`, retorno 0,065305 ✓. Límite 0,5×mín → `INFEASIBLE` ✓.
* `alpha` del solver no es único cuando `(1−β)T` es entero (intervalo de VaR); se informa `var_period` calculado
  aparte (INFO).
* Escalado temporal: por defecto `horizon_scaling="NONE"` (`horizon_periods=1`); `SQRT_TIME` existe **solo si se
  declara** y el docstring lo etiqueta como supuesto de incrementos independientes. No se aplica raíz del tiempo
  automáticamente. INFO: para colas no gaussianas `√h` es una aproximación; recomendable documentarlo en README.
* Mutantes M3 (signo de pérdida), M3b (horizonte), M3c (pesos de observación), M12 (átomo sin fraccionar) **detectados**.
* **F-08 (LOW):** la pérdida del CVaR es bruta (`−rᵀw`) incluso con `NET`; el límite no descuenta los costes
  deterministas (`TC`), aunque el objetivo `MAX_RETURN_WITH_LIMIT` sí es neto.
* **F-01** afecta a este camino (VolatilityLimit del spec ignorado).

---

## 9. EXACT_MIP Verdict — **PASS** (LOW: F-06, F-07)

* Formulación real: `z_i ∈ {0,1}`, `l_i z_i ≤ w_i ≤ u_i z_i`, `Σz = K`, `Σ_{i∉actual} z ≤ MaxNew`, swaps, activos
  obligatorios/prohibidos, presupuesto, grupos, lifting, turnover, costes NET, cono opcional (MISOCP). `l_i,u_i` son
  las cotas **compiladas** (incluyen E-09/E-10/ADV/NAV). Un activo con `z=0` se vende por completo con su coste
  (liquidación entra en objetivo y turnover).
* **Enumeración exhaustiva independiente** (`c_mip.py`; 6 activos, todas las C(6,K) composiciones resueltas con
  SLSQP sobre la utilidad `μᵀw − λwᵀΣw`, `MinWeight>0` para que la cardinalidad sea estricta):

| K | MinW/MaxW | Composición MIP | Composición óptima (enumeración) | Utilidad MIP | Utilidad enumeración |
|---|---|---|---|---|---|
| 3 | 0,10/0,5 | A002,A003,A004 | A002,A003,A004 | 0,05785921 | 0,05785976 |
| 2 | 0,10/0,7 | A002,A003 | A002,A003 | 0,04139037 | 0,04139168 |
| 4 | 0,05/0,4 | A000,A002,A003,A004 | A000,A002,A003,A004 | 0,06359553 | 0,06359596 |

  Misma composición en los tres; `claim=MIP_PROVEN`, `valid=True`, SCIP realmente ejecutado.
* **Estados reales** (`h_mip_limit.py`, 40 activos, K=10): `time_limit=0,05 s` → **`TIME_LIMIT`**, `MIP_INCUMBENT`,
  `valid=False`, con cota dual válida (cota superior 0,11987 > incumbente 0,10576; gap 0,133); `node_limit=3` →
  `MAX_ITERATIONS`, `valid=False`; sin límite → `OPTIMAL`, `MIP_PROVEN` (1 493 nodos, 25 s). Un `TIME_LIMIT` no se
  declara `OPTIMAL`; el gap solo se informa con cota dual válida.
* `max_universe_size`: universo de 70 > 60 → `UnsupportedCombinationError` ✓.
* No está en el bucle interno: test de arquitectura + `inner_loop`; ningún módulo del bucle importa scip/miqp.
* Mutantes M7 (`Σz=K−1`) y M7b (sin cota superior semicontinua) **detectados**.
* **MIP-004 → PARTIAL es correcto:** solo hay `calibration_summary` y comparación de gaps; no hay ajuste
  automático del `CandidateEngine`.
* **F-06 (LOW):** la solución no se «pule»; la utilidad recalculada queda 4e-7…1,3e-6 por debajo del óptimo
  (tolerancia de factibilidad de SCIP sobre la restricción cuadrática epígrafe), y en el caso de 40 activos el
  resultado `MIP_PROVEN`/`gap=0,0` convive con una utilidad recalculada 2,4e-6 (2,2e-5 relativo) bajo la cota dual,
  mayor que `relative_gap_tolerance=1e-6`. La afirmación de optimalidad está en términos del objetivo interno de
  SCIP, no de la utilidad recalculada.
* **F-07 (LOW):** `max_universe_size` solo lo aplica `ExactMIPValidator.validate_heuristic`; `build_cardinality_miqp`
  + router + `SCIPBackend` no lo comprueban.
* Cardinalidad = número de `z=1`; con `MinWeight=0` un miembro puede tener peso 0 (decisión A-08, documentada en el
  docstring). El `AdvancedSolutionValidator` recuenta miembros desde `z`, no desde pesos positivos.

---

## 10. Robust Optimization Verdict — **PASS**

* Caja: `min μᵀw = μ̂ᵀw − δᵀ|w|` (lineal si todas las cotas inferiores ≥ 0; en general variables `a ≥ |w|`).
  Elipsoide: `μ̂ᵀw − κ‖Ω^{½}w‖` (cono con `ν ≥ κ‖L_Ωᵀw‖`). Σ escalada: `{aΣ: a∈[1,s]}` se reduce a `sΣ`
  (`wᵀΣw` creciente en `a`, correcto).
* **Contraste independiente** (`k_robust.py`, SLSQP sobre la utilidad de peor caso analítica):

| Conjunto | Parámetro | Utilidad peor caso motor | SLSQP |
|---|---|---|---|
| caja | δ = 0 / 0,01 / 0,03 / 0,06 / 0,10 | 0,05094227 / 0,04094227 / 0,02094227 / −0,00905773 / −0,04905773 | idénticos |
| elipsoide | κ = 0 / 0,5 / 1 / 2 / 3 | 0,05094227 / 0,02983431 / 0,00955072 / −0,03004046 / −0,06910660 | idénticos |
| Σ escalada | s = 1 / 1,5 / 2 | 0,05094227 / 0,03772612 / 0,02555815 | idénticos |

  La utilidad óptima del peor caso es **no creciente** en el radio (monótona) en los tres casos: un radio mayor no
  mejora el peor caso.
* `robust` sin ningún conjunto de incertidumbre → `UnsupportedCombinationError` (no se etiqueta como robusto la
  utilidad de B2). El shrinkage (`FIXED_INTENSITY`, `JORION`) es un **estimador** (`SHRUNK_HISTORICAL_MEAN`), no
  robustez; la fórmula de Jorion `δ = (N+2)/((N+2) + Y·q)` con `Y = T/trading_days` es correcta para `μ`, `Σ`
  anualizados y exige Σ definida positiva.
* **Sin SDP:** router rechaza SDP; `supports_sdp=False`; la incertidumbre general de Σ está declarada como no
  implementada (A-23). No se afirma soporte.
* Mutantes M10 (signo de la caja), M10b (radio elipsoidal descartado) **detectados**.
* INFO: con cartera long-only, presupuesto 1 y `δ` uniforme, la caja es un desplazamiento constante de la utilidad y
  la cartera robusta **coincide con la nominal** (visible en δ=0…0,10: utilidad baja 0,01 por cada 0,01 de δ sin
  cambio de composición). Matemáticamente correcto, pero la caja uniforme no protege en ese régimen.
* F-01 afecta a `robust` (VolatilityLimit del spec ignorado).

---

## 11. NONCONVEX_RESEARCH Verdict — **PASS** (contrato E-25), con F-09/F-10

E-25 exige únicamente arquitectura: familia, clase `NLP_NONCONVEX`, routing, interfaz `NonConvexAlgorithm` y guarda
de convexidad. Se cumple:

* `NonConvexBackend` sin algoritmos rechaza con `SolverError`/`RoutingError` explícito (E-25); no promete solver.
* Un problema con reformulación convexa se rechaza (NCV-002).
* Los claims son `LOCAL`/`FEASIBLE_ONLY`, nunca global.
* No hay algoritmo registrado por defecto; `SOL-007`/`NCV-004` son `PARTIAL`.

Observaciones: **F-09 (LOW, latente):** un resultado local convergido se mapea a `SolverStatus.OPTIMAL` (con
`optimality_claim=LOCAL`); `StrategyOptimizer.accepts()` trataría `OPTIMAL` como válido sin mirar el claim.
Inalcanzable hoy (registro vacío) pero peligroso al registrar el primer algoritmo. **F-10:** `IMPLEMENTATION_PLAN.md`
fija `NCV-001` en «máximo PARTIAL» y `NCV-004` como diferido `NOT_IMPLEMENTED`; `TRACEABILITY.md` marca `NCV-001`
`VALIDATED` (con el enunciado reescrito como «arquitectura») y `NCV-004` `PARTIAL`.

---

## 12. Financial Constraints — **PASS excepto F-01 (HIGH)**

Preservación verificada por tests y sondeos: presupuesto, límites individuales, grupos, costes de compra/venta,
liquidación completa (`K_E`, `exit_turnover`), turnover, cotas efectivas E-09/E-10/ADV-NAV (cotas compiladas),
restricciones de escenario. Max Sharpe con turnover/costes/`w₀` verificado contra SLSQP (§7); MIP y multiescenario
conservan las restricciones compiladas.

### F-01 (HIGH) — VolatilityLimit del `PortfolioSpec` ignorado en silencio

Sondeo `g_volspec.py` / `g2.py` (`four_asset_problem`, `MaxWeight=1`, `PortfolioSpec.volatility_limit = 0,10`):

| Ruta | `is_valid_solution` | Volatilidad recalculada | Límite |
|---|---|---|---|
| `StrategyOptimizer.cvar(... MAX_RETURN_WITH_LIMIT, max_cvar=0.5)` | **True** | **0,250** | 0,10 |
| `StrategyOptimizer.robust(..., λ=0.5, BOX)` | **True** | **0,200** | 0,10 |
| `MultiScenarioOptimizer.solve_worst_case(λ=0.5)` | **True** | **0,1637** | 0,10 |
| `MultiScenarioOptimizer.solve_base_with_stress(λ=0.5)` | **True** | **0,1312** | 0,10 |
| `StrategyOptimizer.cvar(MIN_CVAR)` | True | 0,0897 (cumple por casualidad) | 0,10 |
| `StrategyOptimizer.max_sharpe` / `volatility_target` / EXACT_MIP | True | respeta el límite | 0,10 |
| Frontera QP, `solve_expected_utility` | — | **rechazan** con `FrontierError` (D-6) | 0,10 |

`ARCHITECTURE.md` §3.6 D-6 declara «se rechaza en lugar de ignorarse» y `CLAUDE.md` prohíbe ignorar restricciones,
pero solo las rutas de fronteras QP y `ExpectedScenarioUtility` lo hacen. En `cvar`, `robust`, `worst_case` y
`base_with_stress` el límite se descarta y el `AdvancedSolutionValidator` ni siquiera recibe un
`VolatilityLimitCheck`, por lo que el resultado se marca **válido**. Ver §19.

Otras restricciones nuevas compatibles: `CVaR`/`robust`/multiescenario aceptan `NET` (costes dentro de la
optimización); FX no se ejercitó de forma independiente (no existe modelado FX específico distinto de los shocks
`FX_SHOCK` y del selector `CURRENCY`).

---

## 13. AdvancedSolutionValidator — **PASS**

Recalcula desde los pesos y datos económicos, nunca desde el solver: `√(wᵀΣw)`, CVaR (cálculo directo), Sharpe
(`(μ−rf)ᵀw` neto de coste en NET), cardinalidad y restricciones por escenario. Sondeo `j_valid.py` con puntos
sintéticos inválidos (todos **rechazados**, con el `constraint_id` correcto):

* límite de volatilidad violado → `VOLATILITY_LIMIT:p`; CVaR sobre límite → `CVAR_LIMIT:max`;
* Σw ≠ 1 → `BUDGET:sum`; peso sobre `MaxWeight` → `BOUNDS:A000:upper`; peso negativo long-only → `LONG_ONLY:A002`;
* NaN → `FINITE:weights`; ratio de Sharpe declarado incoherente → `SHARPE:consistent_ratio`;
* `z` no coherente con pesos → `CARDINALITY:weight_outside_composition`; `z` fraccionario → `CARDINALITY:integrality`.

Estados no óptimos con pesos factibles: `OPTIMAL_INACCURATE` con pesos válidos → `is_valid_solution=False`,
`claim=NOT_ASSESSED`; `SolveResult` impide construir `x` con `MAX_ITERATIONS`/`TIME_LIMIT`. Mutante M6 (validador
que acepta todo) **detectado**.

Alcance del validador: solo comprueba lo que se le pasa en `AdvancedChecks`; por eso F-01 (no se le pasa el límite).

---

## 14. Regression B1/B2/B3/F-3 — **PASS**

* Suite completa reproducida: **1454 passed**, 0 failed, 486,9 s (`python -m pytest -q`, `.venv`).
* Tests F-3/estado numérico ejecutados por separado: 143 passed (`test_numerical_recovery`,
  `test_known_inaccurate_point`, `test_f3_near_identical_net_budget`, `test_f3_post_merge_review`,
  `test_known_solver_status_cases`). Las siete instancias contractuales (77 puntos originalmente inválidos según
  `REMEDIATION_F3_NUMERICAL.md`) se prueban con `test_every_contract_instance_has_only_valid_optimal_points`
  (GROSS/NET); no recontrolé el número 77 por separado.
* **Comparación de valores contra el baseline** (`git archive numerical-f3-validated` en directorio aislado; mismo
  script en ambos árboles, 3 universos (6, 10, 15 activos) × `RISK_AVERSION_GRID`/`TARGET_RETURN_GRID` ×
  GROSS/NET): **240 puntos, 240 `OPTIMAL`, 0 diferencias de estado, 0 diferencias de pesos, máx. |Δw| = 0,0**
  (redondeo a 1e-9): sin variaciones económicas.
* Mutante M8 (recuperación F-3 desactivada) **detectado**.
* **Tres tests preexistentes modificados** (`git diff`):
  * `test_config_hashing.py`: añade las seis secciones nuevas al snapshot (esperado, el hash de configuración
    cambia de forma deliberada).
  * `test_router.py`: `match="mixto entero"` → `"MixedIntegerProblem"` y `match="Clarabel"` → `r"Clarabel|SDP"`.
    Todavía exige `RoutingError`; el matiz se refuerza en `test_router_block4.py`. No debilita el contrato
    (leve ampliación del patrón).
  * `test_architecture_rules.py`: elimina `clarabel`/`pyscipopt` de `FORBIDDEN_IMPORTS` y los sustituye por un test
    **más estricto** (confinamiento a su backend); añade `scenarios`; saca `constraints/conic.py` de la lista de
    bloques posteriores (D-1). Sin debilitamiento material.

---

## 15. Test and Mutation Evidence

Mutantes ejecutados en una **copia aislada** (`scratchpad/mut`, restaurada tras cada mutación), corriendo solo los
ficheros de test relevantes con `-x`. 29 mutantes: **27 detectados, 2 supervivientes**.

| # | Mutante | Resultado |
|---|---|---|
| M1 | `PSDFactor.transpose` devuelve `L` | detectado (`test_the_factor_reconstructs…`) |
| M1b | `volatility_cone` incrusta `L` en vez de `Lᵀ` | detectado (`test_the_volatility_cone_bounds_sqrt…`) |
| M2 / M2b / M2c | CC: sin `w₀κ`; presupuesto sin `κ`; sin offset `K_E` | detectados |
| M3 / M3b / M3c | CVaR: signo de pérdida; sin horizonte; sin pesos de observación | detectados |
| M4 / M4b / M4c | omitir `constraints_s`; retorno mínimo de estrés; volatilidad de estrés | detectados |
| M5 | MIQP enrutado como no mixto | detectado |
| M6 | validador que acepta todo | detectado |
| M7 / M7b | `Σz=K−1`; sin cota semicontinua superior | detectados |
| M8 | recuperación F-3 desactivada | detectado |
| M9 | `AlmostSolved → OPTIMAL` | detectado |
| M10 / M10b | caja con signo invertido; radio elipsoidal descartado | detectados |
| M11 | cono rotado `h−1 → h+1` | detectado |
| M12 | átomo de CVaR sin fraccionar | detectado |
| M14 | precondición A-13 de Sharpe omitida | detectado |
| M15b / M16 / M19 | probabilidades ignoradas; signo del epígrafe; Σp=1 no exigida | detectados |
| M17 / M18 | shock de volatilidad / de coste no aplicado | detectados |
| **M13** | `timelimit → OPTIMAL` en el mapa de SCIP | **superviviente** (F-04): ningún test ejerce el estado real `timelimit`; verifiqué a mano que el comportamiento real es correcto (`TIME_LIMIT`) |
| **M15** | agregación en `expected_moments` | **superviviente** (F-05): es código muerto |

No se ejecutó un mutante de «solver `OPTIMAL_INACCURATE` promovido en `assemble()`»; se cubrió con M9 y con la
comprobación directa de §13.

---

## 16. Performance

Reproducción (`block4_formulations.py --universe 10 20 --held 8`, ejecutado **en la copia aislada**, no en el
árbol principal; escribió su JSON en el scratchpad): mismos estados `OPTIMAL`, `is_valid=True`, mismos solvers. Los
tiempos del rerun fueron 0,30–0,87× los del JSON declarado (p. ej. `MAX_SHARPE` 10 activos: 12,9 ms vs 43,2 ms;
frontera independiente 80 ms vs 247 ms), coherente con la **bimodalidad de tiempos de la máquina** (memoria del
proyecto); por eso los milisegundos no son comparables entre ejecuciones y no aportan conclusión de rendimiento.
Las iteraciones de Clarabel no coinciden exactamente (JSON: 11; rerun y sondeo propio: 12; el rerun es determinista
entre procesos: mismo hash de pesos y 12 iteraciones en 3+3 ejecuciones), lo que sugiere que el JSON almacenado
procede de una revisión ligeramente anterior del código (F-11, INFO).

Desglose del benchmark: para las estrategias de un escenario separa `prepare` (compilación), `formulation_build`
(**residual** `total − prepare − solver − validación`), `solver_setup`, `solver_solve`, `validation`, `total`. No
excluye trabajo relevante en esas filas. **Los tres modos multiescenario solo reportan `total`, `solver_setup`,
`solver_solve`** (sin compilación/validación separadas) → F-11 (LOW).

Sondeo propio de casos degenerados (`f_perf.py`, mínimo de 3 ejecuciones, no es prueba de escalabilidad):

| Caso | Tiempo |
|---|---|
| Max Sharpe NET, n=50, Σ rango 3 + ridge | 61 ms |
| Max Sharpe NET, n=150 | 407 ms |
| `VOL_TARGET`, n=50 / n=150 | 46 ms / 355 ms |
| `MIN_CVAR`, n=50, T=2000 | 836 ms |
| `MIN_CVAR`, n=150, T=2000 | 2 968 ms (HiGHS, LP de 2 150 variables) |

No se observa explosión; CVaR con T grande crece con `T·n` (esperable). **No presento nada de esto como prueba de
escalabilidad productiva** (10–20 activos, 3 escenarios, 5 repeticiones, un proceso). Sin paralelismo (B5).

---

## 17. Architectural Deviations (ARCHITECTURE.md §3.6)

| # | Desviación declarada | Juicio |
|---|---|---|
| D-1 | cono en `formulations/conic.py`, no en `constraints/conic.py` | Aceptable (el cono es formulación, no restricción compilable). El test de arquitectura ya no lista `constraints/conic.py` |
| D-2 | `cross_check_with_second_solver` explícito; política no ampliada | Aceptable; SOL-014 → PARTIAL coherente |
| D-3 | validación MIP en `frontiers/`, no `candidates/` | Aceptable (evita que `candidates` importe backends) |
| D-4 | `ScenarioConfig` solo tolerancias; definiciones y modo como datos/argumentos | Aceptable; CFG-010 → PARTIAL coherente |
| D-5 | `inner_loop` en el constructor y en `route` | Aceptable |
| D-6 | `volatility_limit` **rechazado** en fronteras QP | **Aplicado de forma incompleta** (F-01): solo fronteras y `ExpectedScenarioUtility` |
| D-7 | formulaciones en `optimizers/formulations/*` sobre `ModelBuilder` | Aceptable |

Sin dependencias circulares (test de grafo acíclico pasa); `clarabel` y `pyscipopt` confinados a sus backends
(test). Sin código de B5/B6 (`ProcessPoolExecutor`, `multiprocessing`, `SharedMemory` no aparecen). Sin secretos ni
binarios accidentales en los ficheros sin seguimiento. Dependencias: `pyproject.toml` añade `clarabel>=0.11,<1`
(obligatoria) y `pyscipopt>=6` como extra opcional `exact-mip`; `requirements-lock.txt` fija `clarabel==0.11.1` y
`pyscipopt==6.2.1` (coinciden con lo instalado). HiGHS se usa vía `scipy.optimize.linprog` (sin dependencia nueva).
Duplicación/muerto: `expected_moments` (F-05). Excepciones absorbidas: `grep except` sobre los módulos B4 de escenarios, formulaciones, backends,
router, validador, estrategias y métricas → todas las cláusulas re-elevan un error tipado (`raise … from error`);
ninguna traga un error de solver.

---

## 18. Requirement Reconciliation

Parseo automático de la matriz de `TRACEABILITY.md`: **316** filas, estados: **224 VALIDATED, 38 PARTIAL, 0
IMPLEMENTED, 54 NOT_IMPLEMENTED** → coincide exactamente con lo declarado. (Los conteos aproximados de grep del
inicio de mi sesión diferían por el formato de la columna; el parseo por columna es el válido.)

Revisión de los requisitos señalados:

* `SCN-001..010`, `OPT-009..013`, `MIP-001/002/003/005/006/007`, `ROB-001..006`, `NCV-002`, `SOL-005/006/008/011`,
  `CON-004`, `FEA-005`, `TC-013`, `MET-004`, `VAL-003`: respaldados por implementación y por los contrastes de este
  informe → estados `VALIDATED` **razonables**. Reserva: en `OPT-009..012`/`SCN-005..007`, el defecto F-01 afecta a
  la combinación con `PortfolioSpec.volatility_limit`; recomiendo mantenerlos `VALIDATED` **condicionados** a
  corregir F-01 antes del cierre.
* `MIP-004`, `OPT-014`, `NCV-004`, `SOL-007`, `SOL-014`, `VAL-007`, `CON-010/011/019`, `CFG-010`, `DAT-015`,
  `OUT-001`: `PARTIAL` con motivo consignado — **correcto y honesto** (no se promociona una interfaz).
* `CON-015/016/017`, `FEA-008`, `VAL-006`, `RSK-004/005`, `NCV-003/005`, `VIS-003`: `NOT_IMPLEMENTED`, coherente.
* `SOL-002`: `VALIDATED` (Clarabel real con mapa de estados y tests); la celda de la matriz todavía dice
  «`map_clarabel_status` (B4, **prevista**)» (texto obsoleto, INFO).

**Discrepancias entre `MASTER_SPEC` / `IMPLEMENTATION_PROMPTS` / `IMPLEMENTATION_PLAN` / `TRACEABILITY`** (F-10):

1. `IMPLEMENTATION_PLAN.md` (l. 208): `NCV-001` «solo arquitectura → **máximo PARTIAL**»; `NCV-004` diferido
   `NOT_IMPLEMENTED`. `TRACEABILITY.md`: `NCV-001 = VALIDATED` (enunciado reescrito en la matriz para acotarlo a
   arquitectura) y `NCV-004 = PARTIAL`. Recomiendo `PARTIAL` para `NCV-001` o registrar una enmienda explícita.
2. El plan lista `OPT-014`, `VAL-007`, `OUT-001`, `DAT-015` como «(completa/o)» en B4; `TRACEABILITY.md` los deja
   `PARTIAL`. Es una **degradación honesta** respecto del plan, que debe reflejarse en el plan.
3. El plan incluye en B4 `CON-015/016/017`, `FEA-008`, `VAL-006`, `RSK-004/005` (TE/beta/factores/OAS/EWMA); no
   aparecen en el bloque B4 de `IMPLEMENTATION_PROMPTS.md` (que es la fuente autorizada) y quedan
   `NOT_IMPLEMENTED` con constancia en el CHANGELOG. Discrepancia plan ↔ prompts; no es un incumplimiento del prompt.

No cambié ningún estado durante la auditoría.

---

## 19. Findings

### F-01 — HIGH — `PortfolioSpec.volatility_limit` ignorado en silencio (BLOQUEANTE)

* **Archivo/función:** `portfolio_engine/frontiers/strategy_optimizer.py` — `StrategyOptimizer.cvar` (l. ~561) y
  `StrategyOptimizer.robust` (l. ~651); `portfolio_engine/scenarios/multi_scenario.py` —
  `MultiScenarioOptimizer.solve_worst_case` (l. ~284) y `solve_base_with_stress` (l. ~342).
* **Evidencia:** las cuatro rutas no leen `problem.spec.volatility_limit`, no añaden el cono y no pasan un
  `VolatilityLimitCheck` a `AdvancedChecks`; `assemble()` devuelve `is_valid_solution=True`.
* **Reproducción:** `four_asset_problem(CFG, max_weight=1.0, spec=spec_with(volatility_limit=0.10))`;
  `opt.cvar(p, GROSS, sc, MAX_RETURN_WITH_LIMIT, max_cvar=0.5)` → válido, vol=0,250;
  `opt.robust(p, GROSS, 0.5, mu_set=BOX(0,005))` → válido, vol=0,200; `solve_worst_case(λ=0.5)` → 0,1637;
  `solve_base_with_stress(λ=0.5)` → 0,1312. En cambio `solve_expected_utility` y las fronteras QP lanzan
  `FrontierError` («se rechaza en lugar de ignorarlo»). Script: `g_volspec.py`, `g2.py` (scratchpad).
* **Impacto:** un parámetro contractual de la cartera (`VolatilityLimit`) se viola en silencio y el resultado se
  presenta como válido; contradice D-6 y CLAUDE.md («nunca ignorar restricciones compiladas»).
* **Remediación:** en esas cuatro rutas, o (a) incorporar el cono `‖Lᵀw‖ ≤ σ_max` (ya existe
  `add_volatility_limit`) y un `VolatilityLimitCheck`, o (b) rechazar con `UnsupportedCombinationError` reutilizando
  `ContinuousFrontierEngine.reject_unenforced_constraints`. Añadir un test parametrizado «todas las estrategias con
  `volatility_limit` en el spec: cumplen o rechazan».

### F-02 — MEDIUM — `ruff format --check .` falla; gate declarado falso (BLOQUEANTE, trivial)

* **Archivo:** `README.md:223` (bloque de código Python en Markdown, alineación de comentario en
  `strategies = StrategyOptimizer(config)   # …`).
* **Evidencia/reproducción:** `.venv/Scripts/python.exe -m ruff format --check .` → «1 file would be reformatted,
  317 files already formatted», exit 1. `ruff format --check portfolio_engine tests benchmarks` → 303 ficheros OK.
  El mismo comando sobre `README.md` del baseline extraído → «1 file already formatted»: regresión introducida por B4.
* **Impacto:** la declaración «Ruff format --check: PASS» no es reproducible en la raíz.
* **Remediación:** corregir a mano ese bloque de `README.md`. **No** ejecutar `ruff format .` en la raíz (reescribe
  bloques de Markdown de otros documentos; ver memoria del proyecto).

### F-03 — MEDIUM — `SharpeOutcome.OPTIMAL` independiente del estado y de la validación; volatilidad cero inconsistente

* **Archivo/función:** `strategy_optimizer.py` — `StrategyOptimizer.max_sharpe` (l. ~340–343) y
  `_sharpe_applicability` (l. ~377–427).
* **Evidencia:** `outcome = UNBOUNDED_ZERO_VOLATILITY if vol <= zero_volatility_tolerance else OPTIMAL`, sin mirar
  `solve.status` ni la validación. Con Σ singular y exceso positivo en su núcleo, el punto interior deja ruido
  ~1e-11 > tolerancia 1e-12: n=50 → `UNBOUNDED_ZERO_VOLATILITY`; n=150 (mismo tipo de Σ rango 3) → `outcome=OPTIMAL`,
  `is_valid=False`, `notes=()`. En el caso de 3 activos con un activo sin riesgo (`Σ₀₀=0`, `e_edge.py`) el motor
  reportó `outcome=OPTIMAL`, Sharpe 3,05e9 frente a 1,65e9 implícito y `SHARPE:consistent_ratio` como única
  violación. Además, el resultado `NOT_APPLICABLE` conserva `status=OPTIMAL` (estado del LP de aplicabilidad).
* **Reproducción:** `e_edge.py` (caso «zero-vol») y `f_perf.py` (n=150 «singular rank3»).
* **Impacto:** el resultado **no se acepta** (`is_valid_solution=False`), así que no se emite una cartera errónea,
  pero la etiqueta `OPTIMAL` es engañosa y la distinción NOT_APPLICABLE/INFEASIBLE/UNBOUNDED/OPTIMAL exigida no es
  fiable en el caso degenerado.
* **Remediación:** derivar `outcome` de `(solve.status, report.is_valid)`; detectar volatilidad cero con una
  tolerancia relativa a la escala (p. ej. `r*`/`κ`) o cuando el ratio recalculado y el implícito discrepen;
  no devolver `status=OPTIMAL` para `NOT_APPLICABLE`.

### F-04 — LOW — Estado SCIP `timelimit` sin test (mutante M13 superviviente)

* **Archivo:** `optimizers/status.py` (`SCIP_STATUS_MAP`), `tests/unit/optimizers/test_mixed_integer_backend.py`
  (solo `node_limit`).
* **Evidencia:** el mutante `timelimit → OPTIMAL` sobrevive a 23 tests. Comportamiento real verificado a mano:
  `TIME_LIMIT`, `valid=False`, incumbente con cota dual.
* **Remediación:** test unitario que fuerce un límite de tiempo real (instancia de ~40 activos, `time_limit≈0,05`) y
  fije `TIME_LIMIT`/`MIP_INCUMBENT`/`valid=False`, más un test directo de `map_scip_status("timelimit")`.

### F-05 — LOW — `expected_moments` es código muerto duplicado

* **Archivo:** `optimizers/formulations/multi_scenario.py:114` (`expected_moments`); la agregación efectiva está en
  `scenarios/multi_scenario.py::MultiScenarioOptimizer._aggregate_model`.
* **Evidencia:** `grep expected_moments` → solo la definición; mutante M15 sobrevive.
* **Remediación:** eliminar o hacer que `_aggregate_model` la use (y testearla).

### F-06 — LOW — Sin «pulido» de la solución MIP; `MIP_PROVEN` en términos del objetivo interno de SCIP

* **Archivo:** `optimizers/scip_backend.py::_normalize`; `frontiers/exact_mip_validation.py::_outcome`.
* **Evidencia:** utilidad recalculada 4e-7…1,3e-6 bajo el óptimo por enumeración (3 casos); en el caso de 40
  activos la utilidad recalculada queda 2,4e-6 (2,2e-5 relativo) bajo `mip_utility_upper_bound` con
  `relative_gap=0,0` y `MIP_PROVEN` (tolerancia configurada 1e-6).
* **Remediación:** re-resolver el QP de composición fija (B2) con `z` fijado tras el MIP y reportar el gap con la
  utilidad recalculada, o documentar la tolerancia de factibilidad de SCIP en el claim.

### F-07 — LOW — `max_universe_size` solo se aplica en `ExactMIPValidator`

* **Archivo:** `frontiers/exact_mip_validation.py::validate_heuristic` (guarda); `optimizers/formulations/miqp.py`,
  `optimizers/router.py`, `optimizers/scip_backend.py` (sin guarda).
* **Impacto:** uso directo del constructor/router con un universo grande no está limitado.
* **Remediación:** mover la comprobación a `build_cardinality_miqp` o al enrutado de `EXACT_MIP`.

### F-08 — LOW — CVaR bruto bajo tratamiento NET

* **Archivo:** `optimizers/formulations/cvar.py::build_cvar_problem`.
* **Evidencia:** la pérdida es `−r_tᵀw` sin restar `TC(w)`; con `NET`, `MAX_RETURN_WITH_LIMIT` optimiza retorno neto
  pero el límite de CVaR es sobre pérdidas brutas.
* **Remediación:** documentarlo o restar el coste determinista (desplazamiento constante por escenario) en NET.
  Además: documentar que `SQRT_TIME` es un supuesto (no una propiedad general de colas).

### F-09 — LOW (latente) — `NonConvexBackend` mapea convergencia local a `OPTIMAL`

* **Archivo:** `optimizers/nonconvex_backend.py::solve` (`status = OPTIMAL if usable and converged`).
* **Impacto:** inalcanzable con el registro vacío; al registrar un algoritmo, `accepts(OPTIMAL)` aceptaría un óptimo
  local como firme.
* **Remediación:** estado propio (p. ej. `LOCAL_OPTIMAL`) o que `accepts()` exija `claim` global.

### F-10 — MEDIUM (documental) — Estados/alcance divergentes respecto de `IMPLEMENTATION_PLAN.md`

Ver §18 (`NCV-001` VALIDATED vs «máximo PARTIAL»; `NCV-004`; `OPT-014/VAL-007/OUT-001/DAT-015` «completa» vs
PARTIAL; `CON-015/016/017`, `FEA-008`, `VAL-006`, `RSK-004/005` en el plan pero no en los prompts). Además, la fila
`SOL-002` conserva el texto «(B4, prevista)».
* **Remediación:** decidir y registrar (a) `NCV-001` → `PARTIAL` o enmienda explícita; (b) actualizar el plan con
  las degradaciones a `PARTIAL`; (c) retirar «prevista» de `SOL-002`.

### F-11 — LOW/INFO — Benchmark: desglose incompleto y no reproducible bit a bit

* Filas multiescenario sin `prepare`/`validation`/`formulation_build`; `formulation_build` es un residual; el JSON
  guardado (11 iteraciones de Clarabel en `MAX_SHARPE`, 10 activos) no reproduce (12 iteraciones, determinista); los
  tiempos varían 0,3–0,9× entre ejecuciones (máquina bimodal). Evidencia descriptiva únicamente.

### F-12 — INFO — Higiene git

* Todo el Bloque 4 está **sin commit** (33 modificados + 55 sin seguimiento). `frontiers/session.py` figura
  modificado en `git status` pero **sin diferencia de contenido** (solo estado de stat). Ficheros de trabajo con
  finales de línea mixtos (p. ej. `optimizers/router.py`: índice LF, copia de trabajo CRLF); `git diff --check` sin
  errores de espacios. Sin secretos, sin binarios accidentales, sin código de B5/B6, históricos y `MASTER_SPEC`
  intactos.

### F-13 — INFO — Observaciones menores

* La reparación de Σ de un escenario no aparece en `ScenarioData.transformations` (sí en `covariance_repair`).
* `alpha` (CVaR) puede diferir de `var_period` cuando `(1−β)T` es entero (intervalo de VaR): comportamiento correcto.
* Un `-0.0` en un peso de `ExpectedScenarioUtility` (cosmético).
* En el modo robusto de caja con long-only y presupuesto 1, la caja uniforme no altera la composición.

---

## 20. Final Closure Recommendation

**No cerrar aún; cerrar tras corregir F-01 y F-02** (`PASS_WITH_CHANGES`).

Condiciones para el cierre formal:

1. **F-01** (HIGH): que `CVaR`, `Robust`, `WorstCase` y `BaseWithStressConstraints` apliquen o rechacen
   `PortfolioSpec.volatility_limit`, con test parametrizado que lo garantice.
2. **F-02**: corregir el bloque de `README.md:223` y confirmar `ruff format --check .` = exit 0.
3. Recomendado en la misma iteración: **F-03** (etiquetado de `SharpeOutcome`), **F-04** (test de `timelimit`) y
   **F-10** (reconciliar estados con el plan); F-05…F-09, F-11 pueden diferirse con constancia en la trazabilidad.
4. Tras las correcciones: repetir la suite completa, `mypy --strict`, `ruff check .`, `ruff format --check .`, y
   confirmar que ninguna corrección altera los 240 puntos de referencia de B2 ni los 143 tests de F-3.
5. Recordar que el Bloque 4 completo está **sin commit**: la rama no tiene historia de B4 que revisar; el commit debe
   hacerlo el usuario tras aplicar las correcciones.

No emito `PASS` porque existe un defecto material (F-01) que la suite verde no detecta, y porque dos de las
declaraciones de gate (`ruff format --check`) no se reproducen. No emito `FAIL` porque las formulaciones son
matemáticamente válidas, el routing es real, los escenarios transforman los datos, no hay regresión, la
trazabilidad reconcilia y los defectos bloqueantes son acotados y de corrección local.

---

```
BLOCK_4_INDEPENDENT_AUDIT_SUMMARY

Branch:
block4-scenarios-robust-optimization (HEAD 1c079f6 = baseline; B4 sin commit)

Baseline:
numerical-f3-validated (1c079f6) — 33 modificados (+1362/−145), 55 sin seguimiento

ScenarioEngine:
PASS — 10/10 tipos transforman μ_s/Σ_s; contraste analítico error 0; sin magnitudes hardcodeadas;
determinista; PSD/reparación registrada

Multi-scenario:
PASS (salvo F-01) — Expected/WorstCase/BaseWithStress coinciden con SLSQP; difieren de la solución independiente

Clarabel/SOCP:
PASS — Lᵀ (no L) verificado; singular/casi singular/vinculante/no vinculante/imposible cubiertos; mutantes detectados

Max Sharpe:
PASS matemático (Charnes–Cooper válido, restricciones no homogéneas conservadas, Δ ≤ 2e-10 vs SLSQP en 4 casos
incl. NET+turnover); F-03 (etiqueta OPTIMAL engañosa en caso degenerado)

CVaR:
PASS — CVaR manual y fraccionado exactos; MIN vs LIMIT distintos y verificados; F-08 (pérdida bruta en NET)

EXACT_MIP:
PASS — SCIP real; enumeración exhaustiva coincide; TIME_LIMIT ≠ OPTIMAL; MIP-004 PARTIAL correcto; F-06/F-07 LOW

Robust Optimization:
PASS — caja/elipsoide/Σ escalada = SLSQP; monótono en el radio; sin SDP declarado

NONCONVEX_RESEARCH:
PASS (E-25: solo arquitectura, falla explícitamente); F-09 latente, F-10 estado NCV-001

Solver routing:
PASS — QP→OSQP, LP→HiGHS, SOCP→Clarabel, MIQP→SCIP (nunca OSQP), ejecución real verificada

AdvancedSolutionValidator:
PASS — recalcula desde los pesos; 9 puntos sintéticos inválidos rechazados; INACCURATE no promovido

Regression B1/B2/B3/F3:
PASS — 240 puntos de frontera idénticos bit a bit al baseline; 143 tests F-3 en verde

Tests passed:
1454 (reproducido, 486,9 s)

Tests failed:
0

Mutants detected:
27 de 29 (supervivientes: M13 = test faltante de SCIP timelimit; M15 = código muerto)

Requirement totals:
316 = 224 VALIDATED + 38 PARTIAL + 0 IMPLEMENTED + 54 NOT_IMPLEMENTED (reconciliado por parseo)

Open blocking findings:
F-01 (HIGH) VolatilityLimit ignorado en CVaR/Robust/WorstCase/BaseWithStress;
F-02 (MEDIUM) ruff format --check falla en README.md:223

Open non-blocking findings:
F-03 (MEDIUM), F-10 (MEDIUM, documental), F-04, F-05, F-06, F-07, F-08, F-09 (LOW), F-11, F-12, F-13 (INFO)

Git status:
Sin commit/merge/push/tag/PR; único fichero nuevo por esta auditoría: AUDIT_BLOCK_4.md;
código, tests y documentación existentes sin modificar por el auditor

Closure recommendation:
No cerrar aún: corregir F-01 y F-02 (recomendado también F-03, F-04, F-10) y repetir el gate completo
```

AUDIT_BLOCK_4_STATUS = PASS_WITH_CHANGES
