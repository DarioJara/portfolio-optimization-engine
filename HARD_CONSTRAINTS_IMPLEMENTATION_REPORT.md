# HARD_CONSTRAINTS_IMPLEMENTATION_REPORT — Informe de implementación

> Rama `feature/hard-constraints-final-portfolios` (desde `origin/main` `75d8bb5`; el PR #9 de B5.5 no se
> ha tocado). SHA del código y las pruebas: **`03661f4`**. Este informe y los demás documentos se
> entregan en el commit siguiente (el SHA final se comunica en la respuesta de entrega).
> Documentos hermanos: `AUDIT_PORTFOLIO_HARD_CONSTRAINTS.md` (qué existía y qué faltaba),
> `HARD_CONSTRAINTS_DESIGN.md` (diseño y matemática), `HARD_CONSTRAINTS_TEST_MATRIX.md` (pruebas).

## 0. Control de alcance (CLAUDE.md)

| Concepto | Valor |
|---|---|
| Fase | Encargo «Hard Constraints y control de carteras finales» (fuera de las fases B1–B5 de `IMPLEMENTATION_PROMPTS.md`; autorizado expresamente por el usuario) |
| `RequirementID` afectados | ninguno cambia de estado. Evidencia nueva para `CON-010/011/019`, `FEA-002/005`, `VAL-001`, `CFG-017`. Requisitos **propuestos** `HC-001…HC-014` (fuera de los 316) |
| Módulos permitidos | `config` (sección nueva), `models` (datos nuevos), `hard_constraints` (nuevo), `constraints/integer.py`, `validation/composition_validator.py`, `candidates` (búsqueda por tamaño y fusión), `frontiers` (puerta y banda), `parallel/task.py` (rechazo de operaciones no cubiertas), `tests`, documentación |
| Fuera de alcance (no tocado) | formulaciones y backends de solver, tolerancias del solver, `MASTER_SPEC.md`, SQL Server/Arsys, benchmarks masivos, merge a `main`, PR #9 |

## 1. Resumen

El motor sin modificar **no** impedía carteras finales fuera de mandato: sobre una cartera de 11
posiciones publicaba como válidos 195 de 240 puntos con menos de 11 posiciones y 131 con más de 3
sustituciones (`AUDIT_PORTFOLIO_HARD_CONSTRAINTS.md` §3). Ahora, con `EngineConfig.hard_constraints`:

* una única fuente de verdad por cartera (`EffectiveHardConstraints`, hash y procedencia);
* factibilidad previa determinista (sin solver) → `INFEASIBLE`;
* búsqueda de composiciones por cada tamaño admisible (`FIXED` por defecto, `INCREASE`, `DECREASE`);
* validación final obligatoria de cada punto y de cada propuesta de banda, desde los pesos y la `Σ`
  oficial, con **todas** las causas de rechazo; los resultados originales se conservan;
* banda de volatilidad `HARD`: máximo convexo (SOCP) y mínimo no convexo con estrategia justificada y
  veredictos honestos (`OPTIMAL_CERTIFIED` / `FEASIBLE_LOCAL` / `NO_FEASIBLE_SOLUTION_FOUND`);
* sin la sección `[hard_constraints]` el motor es idéntico (`ConfigHash` `86af211e` intacto).

### Cómo activarlo

```python
import dataclasses
from portfolio_engine.config import load_engine_config, load_hard_constraints

config = load_engine_config("config/default_engine.toml")
config = dataclasses.replace(
    config, hard_constraints=load_hard_constraints("config/example_hard_constraints.toml")
)
result = GlobalCandidateFrontierEngine(config).solve(problem, CostTreatment.GROSS, method)
audit = result.hard_constraint_audit  # estado, veredicto por punto, causas, hash efectivo
final = result.accepted_points  # solo propuestas que cumplen todo el mandato
```

`min_active_weight` (peso mínimo estrictamente positivo por posición) es obligatorio con mandato; con
`min_volatility` hay que declarar `band_max_starts`, `band_max_iterations` y
`band_convergence_tolerance`. Ejemplo comentado: `config/example_hard_constraints.toml`.

## 2. Ficheros

**Nuevos:** `portfolio_engine/config/hard_constraints_config.py`, `portfolio_engine/models/hard_constraints.py`,
`portfolio_engine/hard_constraints/{__init__,counts,preflight,resolver,validator}.py`,
`portfolio_engine/candidates/merge.py`, `portfolio_engine/frontiers/{hard_constraint_gate,volatility_band}.py`,
`config/example_hard_constraints.toml`, `tests/fixtures/hard_constraints.py`, 8 ficheros de test
(§4), `evidence/hard_constraints/*`.

**Modificados (extensión retrocompatible):** `config/{__init__,engine_config,hashing,loader}.py`
(sección opcional; el campo se omite del hash si es `None`), `constraints/integer.py` (7 campos con valor
por defecto en `CompositionLimits`), `validation/composition_validator.py` (parámetro opcional
`limits`), `candidates/candidate_engine.py` (`search_with_mandate`, `_limits`, preflight),
`frontiers/global_frontier.py` (ruta con mandato, auditoría), `models/{enums,frontier}.py`,
`parallel/task.py` (rechazo previo de operaciones no cubiertas), `tests/unit/test_architecture_rules.py`
(nuevo paquete en el grafo de capas y dos constantes de seguridad con nombre), `TRACEABILITY.md`.

## 3. Estado de cada requisito del encargo

| # | Requisito | Estado | Existía / ampliado / desde cero |
|---|---|---|---|
| 1 | Límites de componentes (`max_added/removed/total/replacements`, altas/bajas independientes), respecto a la original y al resultado final | HC-002 **VALIDATED** | `max_new_assets`/`max_swaps`/`CompositionLimits` existían → **ampliados**; el resto **desde cero** |
| 2 | Cardinalidad `FIXED`/`INCREASE`/`DECREASE`, `target_size`, `min/max_size`, incompatibilidades previas, posiciones reales | HC-003, HC-004, HC-010 **VALIDATED** | **desde cero** (amplía FEA-002) |
| 3 | Banda `min/max_volatility` `HARD`, perfil/cartera, `Σ` oficial, tolerancia no material | HC-005 **VALIDATED** | `volatility_limit` existía → **ampliado**; `min`/banda **desde cero** |
| 3b | No convexidad de `σ_min` y estrategia | HC-006 **PARTIAL** | **desde cero** |
| 4 | `min/max_active_weight`, HHI, `N_eff`, bounds existentes, duro vs blando | HC-007 **PARTIAL**, HC-008 **PARTIAL** | bounds **existían**; resto **desde cero** |
| 5 | Precedencia, autorización, parámetros efectivos y hash | HC-009 **VALIDATED** | **desde cero** |
| 6 | Validación final con todas las causas; originales conservados | HC-011, HC-012 **VALIDATED** | **desde cero** |
| 7 | Aceptación 1–13 | véase `HARD_CONSTRAINTS_TEST_MATRIX.md` | — |
| 8 | Alcance/seguridad | cumplido (§7) | — |

HC-006/007/008/014 quedan `PARTIAL` por motivos concretos y declarados (§6 y `HARD_CONSTRAINTS_DESIGN.md` §13).

## 4. Pruebas ejecutadas realmente

Entorno: Windows 11, Python 3.13.6 (`.venv`), `numpy 2.5.3`, `scipy 1.18.1`, `osqp 1.1.3`, `clarabel 0.11.1`, `pandas 3.0.6`, `pytest 9.1.1`.

| Comprobación | Resultado |
|---|---|
| Baseline **antes** de modificar (`tests/unit/{constraints,validation,config,candidates}`) | **556 passed** (143 s) |
| Suite completa tras los cambios (`pytest tests`, una sola ejecución, sin carga concurrente) | **2095 passed, 10 skipped** en 1431 s (23 min 51 s) |
| Pruebas colectadas | 2105 = 1975 existentes + **130 nuevas** |
| Skips (10) | todos preexistentes y de plataforma (`forkserver` Linux, evidencia Linux de B5.4, `/dev/shm`, permisos POSIX); ninguna prueba nueva se omite |
| `mypy --strict portfolio_engine` | **sin errores** (186 ficheros) |
| `ruff check .` / `ruff format --check .` | **limpios** (409 ficheros) |
| `ConfigHash` de la configuración de ejemplo | `86af211e` (sin cambio) |
| Subconjuntos intermedios tras los cambios del núcleo | 892 passed / 13 skipped (`constraints`, `validation`, `config`, `candidates`, `frontiers`, arquitectura, `test_global_frontier_multi_composition`) |

Detalle de las 130 pruebas nuevas (todas pasan):

| Fichero | Pruebas |
|---|---|
| `tests/unit/hard_constraints/test_final_validator.py` | 19 |
| `tests/unit/hard_constraints/test_resolver_precedence.py` | 27 |
| `tests/unit/hard_constraints/test_counts_limits_and_preflight.py` | 20 |
| `tests/unit/hard_constraints/test_settings_and_loader.py` | 6 |
| `tests/unit/frontiers/test_volatility_band.py` | 9 |
| `tests/unit/frontiers/test_hard_constraint_gate.py` | 10 |
| `tests/unit/candidates/test_mandate_search.py` | 6 |
| `tests/unit/test_traceability_contract.py` | 2 |
| `tests/integration/test_hard_constraints_pipeline.py` | 25 |
| `tests/integration/test_hard_constraints_parallel.py` | 6 |

(Los ficheros de `tests/unit/hard_constraints` suman 72; el total de nuevas es 130.)

**No ejecutado:** CI de Linux (la suite no se ha lanzado en GitHub Actions: no se ha creado PR ni
disparador temporal, y el encargo limita el push a la rama); las pruebas con PySCIPOpt (opcional, no
instalado); benchmarks (excluidos por el encargo).

### Control de mutación

`evidence/hard_constraints/mutation_check.py` aplica 15 defectos plausibles (suelo de retorno ignorado,
mínimo de volatilidad sin comprobar, sustituciones como `max(a, r)`, posición con `>=`, tolerancia sin tope
de banda, relajar un máximo sin autorización, presupuesto de cambios ignorado en la factibilidad,
relajación sin comprobar el mínimo, corte tangente con signo cambiado, mandato fuera del hash, puerta que
acepta puntos no validados por el solver / sin pesos / `INFEASIBLE` sin prueba, etc.):
**15/15 detectados, 0 supervivientes** (`evidence/hard_constraints/mutation_check_result.txt`). La primera
pasada dejó sobrevivir dos mutantes de la puerta; se añadió `test_hard_constraint_gate.py` para
matarlos.

### Medición reproducible del motor sin modificar

`PYTHONPATH=. .venv/Scripts/python.exe evidence/hard_constraints/legacy_gap_measurement.py`:
240 puntos publicados y marcados válidos; posiciones por punto `{2:12, 3:13, 4:50, 5:17, 6:24, 7:7, 8:10,
9:23, 10:39, 11:45}`; sustituciones uno a uno `{0:20, 2:21, 3:68, 4:113, 5:18}`.

## 5. Decisiones de implementación que conviene revisar

1. **`min_active_weight` obligatorio** con mandato (sin él el QP deja miembros a cero y la cardinalidad
   real no es la contada). Es un `ConfigError`, no un valor implícito.
2. **`FIXED` por defecto** y cuenta como límite global (relajarlo exige autorización).
3. El **mandato se deriva al motor** (`derive_engine_config`) en lugar de modificar compilador o solvers:
   `max_active_weight` → `global_max_weight`, `min_active_weight` → `min_holding_weight`, etc.
4. **`Σ w²` y `N_eff` se validan** (no se imponen) en la frontera QP; en la propuesta de banda sí entran
   como cono. No se cambia la clase del problema de las fronteras B2.
5. Con mandato, **solo `GLOBAL_FRONTIER`** impone el mandato; las demás operaciones se rechazan antes de
   ejecutar nada (`parallel/task.py::_mandate_problems`) en lugar de ignorarlo.
6. Con mandato, el `VolatilityLimit` de `PortfolioSpec` no llega a la frontera QP (la rechazaría); pasa a
   `max_volatility` y lo imponen la validación final y la propuesta de banda.

## 6. Limitaciones

* **Matemáticas.** `σ >= σ_min` es no convexa (NP-difícil en general). Se garantiza **admisibilidad** de lo
  devuelto y se certifica optimalidad global solo cuando la relajación convexa ya cumple la banda o
  alcanza su cota; en otro caso `FEASIBLE_LOCAL` con brecha. `NO_FEASIBLE_SOLUTION_FOUND` y
  `NO_FEASIBLE_SOLUTION` **no prueban inviabilidad** (la búsqueda de composiciones es heurística).
  `INFEASIBLE` solo se declara con una prueba determinista o un `INFEASIBLE` firme del solver.
* **Completitud.** La malla de la frontera puede no tocar una banda estrecha; la propuesta de banda
  (máximo retorno) lo mitiga, no lo elimina. Las composiciones se generan por utilidad, no por la banda.
* **Cobertura.** HC-014: operaciones distintas de `GLOBAL_FRONTIER` rechazadas con mandato. El perfil de
  riesgo se declara en la configuración, no en las tablas de entrada de carteras.
* **Objetivo secundario.** `diversification_penalty_weight` ordena propuestas admisibles; no entra en el
  objetivo de los solvers.
* **Plataforma.** Validado en Windows (`spawn`); sin ejecución en Linux ni en CI.
* **Persistencia empresarial.** La auditoría se serializa en el diario JSON local (probado); su
  almacenamiento en SQL Server pertenece al Bloque 6 y no se ha tocado.

## 7. Cumplimiento de las restricciones del encargo

| Restricción | Cumplimiento |
|---|---|
| Rama independiente desde `main`; no alterar el PR #9 | `feature/hard-constraints-final-portfolios` desde `origin/main` `75d8bb5`; PR #9 intacto |
| No modificar solvers ni tolerancias sin justificación | ningún backend, formulación ni tolerancia de solver modificados; las tolerancias de la validación final tienen techo `1e-6` y valores por defecto = los del solver |
| No redefinir `MASTER_SPEC.md` | intacto; enmiendas E-HC-01…07 documentadas para aprobación |
| No merge a `main`; no Arsys; no SQL Server | cumplido |
| No benchmarks masivos | no ejecutados |
| Commits y push solo a la rama independiente | dos commits en la rama; push solo a `origin/feature/hard-constraints-final-portfolios` |

## 8. Decisiones abiertas (resumen de `HARD_CONSTRAINTS_DESIGN.md` §13)

D-1 (certificado global para `σ_min`: ¿SCIP en `ExactMIPValidator`?) · D-2 (extender la validación a las
demás operaciones) · D-3 (cono `Σ w²` en la frontera continua) · D-4 (penalización de diversificación en
el objetivo de B2) · D-5 (perfil de riesgo desde las tablas de carteras).

## 9. Estado final

`FINAL_STATUS = READY_FOR_INDEPENDENT_AUDIT` — la implementación y sus pruebas están completas y en verde;
las limitaciones de §6 y las decisiones de §8 están declaradas para que el auditor las valore, ninguna
impide auditar. Si el auditor o el usuario consideran que el tratamiento de `σ_min` (D-1) o la cobertura
de operaciones (D-2) deben resolverse antes de aceptar la fase, pasaría a `NEEDS_METHODOLOGICAL_DECISION`.
