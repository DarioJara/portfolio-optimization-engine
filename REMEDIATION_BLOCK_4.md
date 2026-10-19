# REMEDIATION_BLOCK_4 — Remediación focalizada tras `AUDIT_BLOCK_4.md`

Fecha: 2026-10-19. Rama: `block4-scenarios-robust-optimization` (sin commit; baseline `numerical-f3-validated`).
Alcance: hallazgos F-01, F-02, F-03 y F-10 de `AUDIT_BLOCK_4.md` (`PASS_WITH_CHANGES`). Sin commit, push, merge,
PR ni tag; no se avanza al Bloque 5; `AUDIT_BLOCK_4.md`, `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md` y los
informes históricos no se modifican. **El Bloque 4 no se declara validado hasta superar la auditoría
independiente de cierre.**

## 1. F-01 (HIGH) — `PortfolioSpec.volatility_limit` ya no se ignora

**Causa.** `StrategyOptimizer.cvar`, `StrategyOptimizer.robust`, `MultiScenarioOptimizer.solve_worst_case` y
`solve_base_with_stress` no leían el límite ni lo pasaban al validador: resultado `is_valid_solution=True` con
volatilidad 1,3×–2,5× el límite.

**Decisión matemática (aplicar, no solo rechazar).** El mandato `√(wᵀΣw) <= σ_max` es convexo y ya existía su
formulación cónica: se **añade** a cada formulación el cono de segundo orden `‖Lᵀw‖₂ <= σ_max` con `Σ = LLᵀ` (Σ
del contexto de la composición, i.e. la del escenario BASE; PSD por autodescomposición, Σ singular admitida). Se
añade sin tocar el resto de restricciones (presupuesto, cotas, grupos, turnover, políticas E-09/E-10, costes NET con
liquidación, restricciones por escenario) ni el objetivo. Consecuencias de clase: CVaR (LP/QP) y robusta caja
(QP) con mandato pasan a **SOCP → Clarabel** (nunca OSQP/HiGHS con un cono); peor caso y BaseWithStress ya eran
SOCP/QP+cono.

**Rechazo explícito donde corresponde.** Antes del solver se aplica el mismo certificado de FEA-005 que
`volatility_target` (`StrategyOptimizer._volatility_certificate`): reglas deterministas y cartera de mínima
varianza validada. Si `σ_max < σ_min` el resultado es `INFEASIBLE`, `StatusSource.PRE_SOLVER_CHECK`, sin pesos,
con la causa `VOLATILITY_LIMIT_*` en `notes`. Las fronteras QP y `ExpectedScenarioUtility` conservan su rechazo
explícito (`FrontierError`, D-6): ninguna ruta lo ignora.

**Validación independiente.** `AdvancedChecks.volatility` recibe un `VolatilityLimitCheck` que recalcula
`√(wᵀΣw)` desde los pesos; el resultado solo es `is_valid_solution` si el estado es aceptable **y** el validador
aprueba. En multiescenario el mandato se **añade** (`dataclasses.replace`) a las comprobaciones por escenario.

**Cambios de código.** `optimizers/formulations/volatility.py` (`VolatilityCap`, `add_volatility_cap`);
argumento `volatility_cap` en `build_cvar_problem`, `build_robust_problem`, `build_worst_case_problem` y
`build_base_with_stress_problem`; `frontiers/strategy_optimizer.py` (`volatility_mandate`, `volatility_checks`);
`scenarios/multi_scenario.py` (`_with_mandate`).

**Pruebas nuevas** (`tests/unit/optimizers/test_volatility_mandate.py`, 27 tests; Σ 4×4 **no diagonal**,
correlaciones 0,1…0,4):
- por cada una de las cuatro estrategias: mandato vinculante cumplido y activo (`σ = σ_max`, validación con
  `VOLATILITY_LIMIT`, solver `CLARABEL`); mandato holgado = solución sin mandato; mandato por debajo de σ_min →
  `INFEASIBLE` previo al solver; mandato apenas sobre σ_min factible;
- oráculos independientes: SLSQP del epígrafe del peor caso, SLSQP de la utilidad robusta (caja) y búsqueda
  aleatoria factible para CVaR (20 000 carteras Dirichlet);
- **mutación**: se sustituye cada constructor por uno que descarta el cono; el resultado viola el límite y el
  validador lo rechaza (`is_valid_solution=False`);
- robusta con Σ escalada + mandato (dos conos) y tratamiento `NET`;
- **escenarios con restricciones incompatibles** + mandato: `ScenarioError` («incompatibles») e inviabilidad
  previa sin pesos, en peor caso y en BaseWithStress.

## 2. F-02 (MEDIUM) — `ruff format --check .`

Único fichero afectado: `README.md` (bloque Python de la sección Bloque 4, comentarios alineados a mano). Se
reescribió a mano (comentarios sobre cada línea; además la firma de `ScenarioEngine.build` del ejemplo estaba
incompleta y se corrigió). No se ejecutó `ruff format .`. Resultado: `319 files already formatted`.

## 3. F-03 (MEDIUM) — etiqueta de `SharpeOutcome`

**Resolución de código.** `SharpeOutcome.OPTIMAL` solo se conserva si el resultado final es
`is_valid_solution` (estado aceptable **y** validación independiente). En otro caso el veredicto pasa a
`SOLVER_FAILURE` con la nota `SHARPE_SOLUTION_NOT_VALIDATED` y `optimality_claim = NOT_ASSESSED`. Test:
`test_max_sharpe.py::test_optimal_is_never_claimed_without_an_accepted_status_and_a_passing_validation`.

**Justificación (no se cambia).**
- Detección de volatilidad cero: se mantiene la tolerancia de configuración (`frontier.zero_volatility_tolerance`).
  Una tolerancia relativa a la escala sería un criterio nuevo sin respaldo en la configuración; el caso degenerado
  (Σ singular con ruido de punto interior ~1e-11) queda ahora correctamente etiquetado como **fallo**, no como
  óptimo; no se emite cartera errónea (ya no lo hacía: `is_valid_solution=False`).
- `NOT_APPLICABLE` conserva `status=OPTIMAL`: es el estado del **LP de aplicabilidad** (A-13), con
  `status_source=PRE_SOLVER_CHECK`, `weights=None`, `is_valid_solution=False` y `outcome` autoritativo; no existe un
  valor de `SolverStatus` adecuado y añadir uno afectaría al contrato de §45 (fuera de alcance). Cubierto por los
  tests existentes.

## 4. F-10 (MEDIUM, documental) — estados frente a `IMPLEMENTATION_PLAN.md`

- `NCV-001`: `VALIDATED` → **`PARTIAL`** (el plan fija «solo arquitectura → máximo PARTIAL»; los algoritmos siguen
  `NOT_IMPLEMENTED` por E-25). Resumen: 223 VALIDATED, 39 PARTIAL, 54 NOT_IMPLEMENTED, 0 IMPLEMENTED (316).
- `SOL-002`: retirado el texto obsoleto «(B4, prevista)».
- `OPT-014`, `VAL-007`, `OUT-001`, `DAT-015` permanecen `PARTIAL` (degradación honesta respecto del plan, ya
  motivada en la columna *Estado*). `CON-015/016/017`, `FEA-008`, `VAL-006`, `RSK-004/005` están en el plan pero no
  en `IMPLEMENTATION_PROMPTS.md` (fuente autorizada del bloque): siguen `NOT_IMPLEMENTED` con constancia en el
  CHANGELOG. **`IMPLEMENTATION_PLAN.md` no se edita** en esta remediación: reconciliarlo es una decisión del
  usuario.

## 5. No abordados (diferidos con constancia)

F-04 (test del estado SCIP `timelimit`), F-05 (`expected_moments` código muerto), F-06 (sin «pulido» MIP),
F-07 (`max_universe_size` solo en `ExactMIPValidator`), F-08 (CVaR bruto bajo `NET`), F-09 (`NonConvexBackend`
mapea convergencia local a `OPTIMAL`, latente) y F-11…F-13 quedan abiertos, fuera del alcance pedido. Ninguno
altera resultados válidos actuales.

## 6. Verificación ejecutada (2026-10-19)

| Comando | Resultado |
|---|---|
| `pytest -q` (suite completa) | **1482 passed**, 0 failed, 0 skipped (399 s) = 1454 + 27 (`test_volatility_mandate.py`) + 1 (F-03) |
| `mypy --strict portfolio_engine` | sin errores (158 ficheros) |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 319 files already formatted |
| `git diff --check` | sin errores de espacios (solo avisos LF/CRLF preexistentes) |

No regresión: B1/B2/B3/F-3 forman parte de la suite completa (todo verde), incluidos los tests de F-3 y de
`test_volatility_control.py`.

## 7. Limitaciones y preparación para la auditoría de cierre

- El mandato se aplica sobre el `Σ` del escenario BASE (la covarianza de la cartera); no se exige el límite bajo
  `Σ_s` de cada escenario (para eso existen los `stress_limits`).
- `ExpectedScenarioUtility` y las fronteras QP siguen **rechazando** el mandato (no lo aplican): decisión
  explícita D-6, no una pérdida silenciosa.
- Con mandato vinculante, CVaR/robusta se resuelven con Clarabel (más lento que HiGHS/OSQP); no se midió.
- Estado: F-01 y F-02 (bloqueantes) corregidos y verificados; F-03 resuelto y F-10 resuelto por decisión
  documentada. **Listo para la auditoría independiente de cierre**; Bloque 4 sin declarar validado hasta
  entonces. Se detiene aquí a la espera de autorización.
