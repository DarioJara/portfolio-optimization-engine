# AUDIT_BLOCK_4_CLOSURE — Auditoría independiente de cierre del Bloque 4

Fecha: 2026-10-19. Rama: `block4-scenarios-robust-optimization` (sin commit; baseline `numerical-f3-validated`).
Entrada: `AUDIT_BLOCK_4.md` (`PASS_WITH_CHANGES`) y `REMEDIATION_BLOCK_4.md`. Alcance de escritura de esta
auditoría: solo este fichero. Mutantes, baseline extraído con `git archive` y scripts de sondeo viven fuera del
repositorio. No se modificó código, tests, `MASTER_SPEC.md` ni informes históricos; sin commit/push/PR/merge/tag.

Limitación: `MASTER_SPEC.md` no se releyó íntegro en esta pasada; las referencias a contrato (FEA-005, D-6, A-13)
proceden de la auditoría previa y de `REMEDIATION_BLOCK_4.md`.

## 1. Gate reproducido (`.venv`, ejecutado por el auditor)

| Comando | Resultado |
|---|---|
| `pytest -q` (suite completa) | **1482 passed**, 0 failed (390 s) — coincide con lo declarado |
| `mypy --strict portfolio_engine` | Success: no issues found in 158 source files |
| `ruff check .` | All checks passed |
| `ruff format --check .` | **320 files already formatted** (exit 0) |
| `git diff --check` | exit 0 (solo avisos LF/CRLF) |
| Tests F-3 + mandato + Sharpe (subconjunto) | 190 passed |

Nota: 320 ficheros frente a los 319 declarados por el implementador: la diferencia es `AUDIT_BLOCK_4.md`, creado
después de su ejecución. El README ya no falla.

## 2. F-01 — VolatilityLimit del spec: CORREGIDO

**Código revisado.** `formulations/volatility.py` añade `VolatilityCap` + `add_volatility_cap`, que inserta el cono
`‖Lᵀw‖ ≤ σ_max` (mismo `volatility_cone`, con `transpose`, ya verificado en la auditoría previa). Lo reciben
`build_cvar_problem`, `build_robust_problem`, `build_worst_case_problem` y `build_base_with_stress_problem`.
`StrategyOptimizer.volatility_mandate` aplica antes del solver el certificado FEA-005 (reglas deterministas +
cartera de mínima varianza validada) y devuelve `INFEASIBLE`/`PRE_SOLVER_CHECK` si `σ_max < σ_min`;
`volatility_checks` pasa un `VolatilityLimitCheck` al `AdvancedSolutionValidator`, que recalcula `√(wᵀΣw)`
desde los pesos. En multiescenario `_with_mandate` fusiona el mandato en las comprobaciones por escenario.

**Sondeo independiente propio** (`four_asset_problem`, `PortfolioSpec.volatility_limit` = 0,10 / 0,0875 / 0,05;
volatilidad recalculada con mi propia Σ):

| Ruta | lim 0,10 | lim 0,0875 | lim 0,05 |
|---|---|---|---|
| `cvar` MAX_RETURN_WITH_LIMIT | vol 0,10000 válido, CLARABEL | 0,0875 válido | INFEASIBLE, sin solver |
| `cvar` MIN_CVAR | 0,08965 (holgado) | 0,0875 | INFEASIBLE |
| `robust` (caja) / `robust` NET + Σ escalada | 0,10000 / 0,10000 | 0,0875 / 0,0875 | INFEASIBLE |
| `solve_worst_case` | 0,10000 | 0,0875 | INFEASIBLE |
| `solve_base_with_stress` | 0,10000 | 0,0875 | INFEASIBLE |
| `solve_expected_utility` | `FrontierError` (D-6) | igual | igual |

Antes: volatilidades 0,13–0,25 declaradas válidas. Ahora toda ruta cumple, rechaza o falla de forma explícita; el
solver pasa a CLARABEL (nunca OSQP/HiGHS con un cono). Oráculos independientes (SLSQP, no las formulaciones):
robusta + mandato: utilidad de peor caso 0,070865012543 (SLSQP) frente a 0,070865012578 (motor), pesos iguales a
4 decimales; BaseWithStress con mandato + estrés (σ_estrés ≤ 0,12): pesos `[.13145,.13937,.10545,.62374]` frente a
SLSQP `[.13145,.13936,.10545,.62374]`, σ_estrés = 0,1200000000 (en esa instancia el mandato de cartera no es
vinculante, 0,0938 < 0,11; el caso vinculante lo cubre la tabla anterior y los tests).

**Mutantes sobre los tests nuevos** (copia aislada, `test_volatility_mandate.py`, 27 tests): cono descartado en
todas las formulaciones, solo CVaR, solo robusta, solo peor caso, solo BaseWithStress; cono con `L` en vez de
`Lᵀ`; check del validador eliminado; mandato no fusionado en escenarios; certificado de inviabilidad omitido →
**9 de 9 detectados** (los tests ejercen `Σ` 4×4 no diagonal, así que `L` vs `Lᵀ` sí se distingue).

## 3. F-02 — Ruff: CORREGIDO

Reproducido desde `.venv`: `ruff format --check .` → exit 0 (320 ficheros). `ruff check .` pasa. Un `README.md`
del baseline extraído sigue formateado; no se ejecutó `ruff format .`.

## 4. F-03 — etiqueta `SharpeOutcome`: RESUELTO (parcialmente por justificación)

`max_sharpe` degrada `OPTIMAL` a `SOLVER_FAILURE` (nota `SHARPE_SOLUTION_NOT_VALIDATED`, claim `NOT_ASSESSED`)
cuando el resultado no es `is_valid_solution`. Reproducido con los dos casos degenerados del informe previo
(Σ rango 3, n = 150; activo sin riesgo con exceso positivo): ambos dan ahora `outcome=SOLVER_FAILURE`,
`is_valid=False`, nota presente. Mutante que desactiva el relabel: detectado
(`test_optimal_is_never_claimed_without_an_accepted_status_and_a_passing_validation`).

Justificaciones aceptadas: la tolerancia de volatilidad cero sigue siendo la de configuración (no se inventa un
criterio relativo); `NOT_APPLICABLE` conserva `status=OPTIMAL` porque es el estado del LP de aplicabilidad, con
`PRE_SOLVER_CHECK`, sin pesos y `outcome` autoritativo.
Observación residual **F-03b (LOW)**: en el caso degenerado, `StrategyResult.status` sigue siendo `OPTIMAL`
mientras `outcome=SOLVER_FAILURE`; los consumidores deben leer `is_valid_solution`/`outcome`, no `status`.

## 5. F-10 — estados: RESUELTO

Parseo de `TRACEABILITY.md`: 316 requisitos = **223 VALIDATED + 39 PARTIAL + 0 IMPLEMENTED + 54
NOT_IMPLEMENTED**, coincide con `REMEDIATION_BLOCK_4.md`. `NCV-001` pasa a `PARTIAL` (acorde con el plan: «solo
arquitectura → máximo PARTIAL»); `SOL-002` ya no dice «prevista». La discrepancia plan ↔ prompts
(`CON-015/016/017`, `FEA-008`, `VAL-006`, `RSK-004/005`) y las degradaciones de `OPT-014`/`VAL-007`/`OUT-001`/
`DAT-015` se registran sin editar `IMPLEMENTATION_PLAN.md`; queda como decisión del usuario (no bloqueante).

## 6. Independencia de oráculos y cobertura

Los oráculos nuevos son independientes de las formulaciones: SLSQP del epígrafe del peor caso, SLSQP de la utilidad
robusta de caja, búsqueda aleatoria Dirichlet (20 000 carteras) para CVaR, y el test de mutación que sustituye cada
constructor por uno sin cono y exige que el validador rechace. Cobertura de las cuatro estrategias × (vinculante,
holgado, inferior a σ_min, apenas factible), NET, Σ escalada + mandato y restricciones de escenario incompatibles.
Hueco menor: el oráculo de CVaR con mandato es una cota por muestreo, no un óptimo exacto.

## 7. Regresión B1/B2/B3/F-3

* Suite completa verde (1482 = 1454 + 27 + 1).
* Frontera B2: 3 universos (6, 10, 15 activos) × `RISK_AVERSION_GRID`/`TARGET_RETURN_GRID` × GROSS/NET contra un
  `git archive numerical-f3-validated`: **240 puntos, 0 diferencias** de estado o pesos, todos `OPTIMAL`.
* Tests de F-3 y de estado numérico en verde (190 con el subconjunto indicado).

## 8. Hallazgos

Bloqueantes: **ninguno**.

No bloqueantes (arrastrados de `AUDIT_BLOCK_4.md`, sin cambios ni empeoramiento): F-04 (sin test del estado SCIP
`timelimit`), F-05 (`expected_moments` código muerto), F-06 (sin pulido de la solución MIP), F-07
(`max_universe_size` solo en `ExactMIPValidator`), F-08 (CVaR bruto bajo NET), F-09 (`NonConvexBackend` mapea
convergencia local a `OPTIMAL`, latente), F-11…F-13 (INFO). Nuevo: F-03b (LOW, arriba). Nota de rendimiento:
con mandato vinculante CVaR/robusta usan Clarabel en lugar de HiGHS/OSQP; no se midió el coste (declarado por el
implementador y no verificado por mí).

## 9. Estado de git

Rama correcta; sin commits sobre el baseline; 34 ficheros modificados y 58 sin seguimiento (incluye este informe,
`AUDIT_BLOCK_4.md` y `REMEDIATION_BLOCK_4.md`). `MASTER_SPEC.md`, `IMPLEMENTATION_PROMPTS.md`,
`IMPLEMENTATION_PLAN.md` y los informes históricos no figuran en el diff. El Bloque 4 sigue **sin commit**.

## 10. Recomendación

Los dos bloqueantes (F-01, F-02) están corregidos y verificados de forma independiente; F-03 y F-10 resueltos. El
Bloque 4 puede cerrarse formalmente. Quedan abiertos únicamente los LOW/INFO listados, que pueden diferirse con
constancia en la trazabilidad. El commit lo decide el usuario.

BLOCK_4_CLOSURE_STATUS = PASS
