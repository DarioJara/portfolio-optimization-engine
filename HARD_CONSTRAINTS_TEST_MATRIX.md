# HARD_CONSTRAINTS_TEST_MATRIX — Matriz de pruebas de aceptación

> Cada criterio del encargo → pruebas reales (ruta de tests relativa a la raíz), qué recuento
> **independiente** hace la prueba (sin usar el motor que valida) y su resultado. Los resultados
> proceden de ejecuciones reales registradas en `HARD_CONSTRAINTS_IMPLEMENTATION_REPORT.md` §4.
> «Unit» = `tests/unit/...`; «Int» = `tests/integration/...`.

## 1. Criterios de aceptación del encargo

| # | Criterio | Pruebas | Verificación independiente | Resultado |
|---|---|---|---|---|
| 1 | Cartera de 11 activos que conserva exactamente 11 | Unit `hard_constraints/test_final_validator.py::test_the_original_portfolio_is_accepted_and_keeps_exactly_eleven_positions`, `::test_cardinality_counts_real_positions_not_listed_assets`; Int `test_hard_constraints_pipeline.py::test_an_eleven_position_portfolio_keeps_exactly_eleven_positions`; Unit `candidates/test_mandate_search.py::test_a_fixed_size_mandate_reproduces_the_legacy_search_exactly` | cuenta `w_i > 1e-8` sobre los pesos publicados de **cada** punto aceptado y el tamaño de **cada** composición candidata; la equivalencia FIXED compara con el motor sin mandato | PASS |
| 2 | Máximo de 3 sustituciones | Unit `test_final_validator.py::test_three_replacements_are_accepted_and_four_are_rejected`; Int `::test_at_most_three_replacements_are_measured_against_the_original_portfolio`, `::test_a_tighter_replacement_budget_is_respected_and_originals_are_preserved`; Unit `candidates/test_mandate_search.py::test_component_limits_prune_the_search_not_only_the_final_check` | diferencia de conjuntos `positions − original` por punto aceptado (≤ 3, ≤ 1); la poda se contrasta con un presupuesto más amplio | PASS |
| 3 | Rechazo de una solución con 4 sustituciones | Unit `test_final_validator.py::test_three_replacements_are_accepted_and_four_are_rejected`, `::test_independent_additions_and_removals_are_not_replacements`, `::test_all_rejection_causes_are_recorded_not_only_the_first`; Unit `hard_constraints/test_counts_limits_and_preflight.py::test_counts_match_an_exhaustive_set_enumeration` | enumeración exhaustiva de subconjuntos para altas/bajas/sustituciones; `HC_REJECTED:MAX_REPLACEMENTS` sin `CARDINALITY` | PASS |
| 4 | Rechazo de 40 % en un activo con máximo 20 % | Unit `test_final_validator.py::test_forty_percent_in_one_asset_is_rejected_when_the_maximum_is_twenty`; Int `test_hard_constraints_pipeline.py::test_a_per_position_cap_is_enforced_inside_the_optimization_not_only_after`, `::test_a_rejected_point_is_never_in_the_accepted_set_and_keeps_all_its_causes` | valor 0,40 y límite 0,20 en la comprobación; en pipeline, `max(w) ≤ 0,12` y `Σw² ≤ 0,12` recalculados | PASS |
| 5 | Rechazo de volatilidad inferior al mínimo | Unit `test_final_validator.py::test_volatility_below_the_minimum_is_rejected`, `::test_the_volatility_tolerance_is_bounded_by_the_band_width`; Unit `frontiers/test_volatility_band.py` (mínimo activo) | `σ = 0,20·√Σw²` analítica (ρ = 0, σ_i = 0,20); exceso `= 0,01` | PASS |
| 6 | Rechazo de volatilidad superior al máximo | Unit `test_final_validator.py::test_volatility_above_the_maximum_is_rejected`, `::test_volatility_inside_the_band_is_accepted_and_recomputed_from_the_official_covariance`; Int `::test_accepted_points_and_band_proposals_are_inside_the_volatility_band` | `σ` recalculada con `√(wᵀΣw)` de la `Σ` del `RiskModel` y comparada con la de la validación | PASS |
| 7 | Rechazo de peso positivo inferior al mínimo por posición | Unit `test_final_validator.py::test_a_positive_weight_below_the_per_position_minimum_is_rejected`, `::test_weights_below_the_position_threshold_are_zero_and_never_hide_cardinality` | peso 0,004 > umbral 1e-8 ⇒ posición ⇒ viola el mínimo 0,02; el peso sub-umbral no cuenta pero su masa se vigila | PASS |
| 8 | Configuraciones matemáticamente inviables | Unit `hard_constraints/test_counts_limits_and_preflight.py::test_mathematically_infeasible_configurations_are_declared_before_solving` (9 casos), `::test_change_budgets_are_compared_with_what_each_size_requires`, `::test_decrease_with_forced_exits_needs_removal_budget_but_no_additions`, `::test_mandatory_holds_cannot_exceed_the_size`, `::test_target_outside_the_policy_and_missing_cardinality_are_infeasible`; Int `test_hard_constraints_pipeline.py::test_mathematically_infeasible_mandates_are_declared_infeasible_without_solving` (7 casos), `::test_forced_liquidation_without_replacement_budget_is_infeasible_before_solving`, `::test_a_mandate_that_cannot_be_met_after_searching_is_no_feasible_solution_not_infeasible`; Unit `frontiers/test_volatility_band.py::test_a_cap_below_the_minimum_variance_is_proven_infeasible_by_the_relaxation`, `::test_a_floor_above_every_attainable_volatility_is_not_found_but_not_claimed_infeasible` | causa conocida de antemano por caso; `frontiers_solved == 0`, sin puntos ni frontera continua (ningún solver invocado) | PASS |
| 9 | Activos congelados y restringidos | Int `test_hard_constraints_pipeline.py::test_a_frozen_restricted_asset_stays_in_every_proposal_at_its_current_weight`, `::test_a_force_liquidated_asset_leaves_and_counts_as_a_forced_replacement`, `::test_forced_liquidation_without_replacement_budget_is_infeasible_before_solving`, `::test_non_eligible_assets_never_enter_a_proposal`; Unit `test_final_validator.py::test_eligibility_and_mandate_of_the_final_composition_are_checked_from_raw_data`; Unit `hard_constraints/test_counts_limits_and_preflight.py::test_decrease_with_forced_exits_needs_removal_budget_but_no_additions` | peso del congelado = `w_current` en cada punto aceptado; `A002 ∉ posiciones` y `1 ≤ sustituciones ≤ 3` con `FORCE_LIQUIDATE`; ningún no elegible en las posiciones | PASS |
| 10 | Conservar al menos la rentabilidad esperada original | Unit `test_final_validator.py::test_expected_return_must_not_fall_below_the_original_when_configured`, `::test_an_absolute_expected_return_floor_and_net_treatment`; Int `test_hard_constraints_pipeline.py::test_the_original_expected_return_is_preserved_when_configured` | `μᵀw ≥ μᵀw0 − 1e-7` recalculado por punto aceptado; existen puntos de la frontera por debajo, rechazados con `MIN_EXPECTED_RETURN` | PASS |
| 11 | Equivalencia secuencial y paralela | Int `test_hard_constraints_parallel.py::test_parallel_results_and_audits_match_sequential_under_t1`, `::test_sequential_runs_carry_a_mandate_audit_with_nontrivial_verdicts`; Unit `frontiers/test_volatility_band.py::test_the_search_is_deterministic`; Int `test_hard_constraints_pipeline.py::test_the_pipeline_is_deterministic` | comparador T1 campo a campo (`compare_results`, 2 workers `spawn`) incluida la auditoría | PASS |
| 12 | Persistencia y reanudación sin alterar restricciones | Int `test_hard_constraints_parallel.py::test_resuming_with_the_same_mandate_restores_identical_results_and_audits`, `::test_resuming_with_a_different_mandate_is_rejected_and_the_journal_is_untouched`, `::test_the_audit_survives_the_json_journal_codec_exactly` | restauración idéntica (`tolerance=0`), `JournalIncompatibleError` con otro mandato o sin mandato, diario byte a byte intacto | PASS |
| 13 | Compatibilidad con los contratos originales y los 316 requisitos | Unit `test_traceability_contract.py` (2); Unit `hard_constraints/test_settings_and_loader.py::test_without_the_section_the_engine_and_its_config_hash_are_unchanged`; Int `test_hard_constraints_pipeline.py::test_without_a_mandate_the_pipeline_is_unchanged`; Unit `candidates/test_mandate_search.py::test_the_search_is_unchanged_when_the_mandate_section_is_absent`; suite completa existente (ver informe §4); Unit `test_architecture_rules.py` | 316 `RequirementID` únicos con los totales del resumen (238/42/36/0) leídos de `TRACEABILITY.md`; `ConfigHash` sin el campo si no hay mandato; suite B1–B5 sin cambios en verde | PASS |

## 2. Cobertura por requisito propuesto

| HC | Pruebas principales |
|---|---|
| HC-001 | `unit/hard_constraints/test_settings_and_loader.py` |
| HC-002 | `unit/hard_constraints/test_counts_limits_and_preflight.py`; `unit/hard_constraints/test_final_validator.py`; `integration/test_hard_constraints_pipeline.py` |
| HC-003 | `unit/hard_constraints/test_resolver_precedence.py`; `unit/candidates/test_mandate_search.py`; pipeline `increase`/`decrease`/cold start |
| HC-004 | `unit/hard_constraints/test_final_validator.py` (cardinalidad real, umbral, masa sub-umbral); pipeline 11 posiciones |
| HC-005 | `unit/hard_constraints/test_final_validator.py` (banda, tolerancia material) |
| HC-006 | `unit/frontiers/test_volatility_band.py` (forma cerrada, no convexo con barrido independiente, cota superior, NO_FEASIBLE_FOUND vs INFEASIBLE_PROVEN) |
| HC-007 | `unit/hard_constraints/test_final_validator.py` (HHI, N_eff); `unit/frontiers/test_volatility_band.py::test_the_concentration_cap_is_a_second_order_cone_in_the_band_problem` |
| HC-008 | pipeline `test_the_secondary_diversification_objective_only_orders_admissible_points` |
| HC-009 | `unit/hard_constraints/test_resolver_precedence.py` (precedencia, relajamiento, autorización, hash, derivación) |
| HC-010 | `unit/hard_constraints/test_counts_limits_and_preflight.py`; pipeline inviable sin solver |
| HC-011 | `unit/hard_constraints/test_final_validator.py`; `unit/frontiers/test_hard_constraint_gate.py` |
| HC-012 | `unit/frontiers/test_hard_constraint_gate.py`; pipeline `no_feasible_solution` |
| HC-013 | `integration/test_hard_constraints_parallel.py`; `unit/test_traceability_contract.py` |
| HC-014 | `integration/test_hard_constraints_parallel.py::test_operations_outside_the_global_frontier_are_rejected_before_any_engine_runs` |

## 3. Pruebas de mutación manual (defectos plausibles que la suite debe detectar)

Ejecutadas con un script que aplica una mutación, corre las pruebas afectadas y restaura el fichero
(`HARD_CONSTRAINTS_IMPLEMENTATION_REPORT.md` §5). Cada mutante debe ser detectado (fallar) por alguna
prueba; los que sobrevivieron al primer intento condujeron a nuevas pruebas
(`test_hard_constraint_gate.py`).

| Mutante | Detectado por |
|---|---|
| suelo de retorno ignorado · volatilidad mínima sin comprobar · sustituciones = `max(a, r)` · posición con `>=` · tolerancia de volatilidad sin tope de banda · relajar un máximo sin autorización · límite de sustituciones ignorado · presupuesto de cambios ignorado en la factibilidad · relajación sin comprobar el mínimo · corte tangente con signo cambiado · el mandato no entra en el `ConfigHash` | unit + pipeline (ver informe) |
| la puerta acepta puntos que el solver no validó · ignora el estado del solver · acepta puntos sin pesos · declara `INFEASIBLE` sin prueba | `unit/frontiers/test_hard_constraint_gate.py` (añadida tras sobrevivir el primer intento) |
