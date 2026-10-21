# INVESTIGATION_H1_B4 — Fragilidad numérica H-1 de B4 dependiente del hardware

Fecha: 2026-10-20. Rama: `block5-benchmarks-final-audit` (B5.5). Estado: **investigación documentada; sin cambios de
algoritmos, tolerancias ni tests** (la tarea B5.5 lo prohíbe sin una remediación independiente). Procede de
`AUDIT_BLOCK_5_3.md` H-1 y de `CHANGELOG.md` («Remediación tras AUDIT_BLOCK_5_3»).

## 1. Qué falla y dónde

Dos tests de B4 (`tests/unit/scenarios/test_multi_scenario.py`) fallan de forma intermitente en algunos runners de GitHub Actions
(AMD EPYC 7763; no se ha observado en Xeon ni en esta máquina Intel i7-13620H) **sin que cambie el código**:

| Test | Aserción que falla en CI (anotaciones del run `39428998923`, `bcada73`, EPYC 7763, Python 3.11.17) |
|---|---|
| `test_single_solutions_satisfy_the_constraints_of_every_scenario` | `solution.is_valid_solution` es `False` para `MULTI:WORST_CASE` (`solver_names=('CLARABEL',)`) con `worst_case_utility = -0.09260875000001824` y `solver_t = -0.09260875000001369` |
| `test_worst_case_maximizes_the_minimum_scenario_utility` | `result_oracle.success` es `False`: SLSQP (oráculo del propio test, `ftol=1e-15`) termina con «Positive directional derivative for linesearch» |

Dos hechos de esas anotaciones orientan el diagnóstico: (a) en el primer test las dos utilidades difieren en **4,6·10⁻¹⁵**, es decir, los
**pesos son numéricamente correctos**; lo que falla es la validez declarada; (b) el segundo mensaje es exactamente el de SLSQP, no del motor.

## 2. Mecanismo del primer fallo (motor)

`StrategyOptimizer.assemble` fija `is_valid_solution = report.is_valid and accepts(status)`. Con `solver.accept_inaccurate_solutions = false`,
un estado `OPTIMAL_INACCURATE` (Clarabel `AlmostSolved`) invalida la solución **aunque sus pesos cumplan todas las restricciones**
(`validation.violations` vacío). Con `ambiguous_status_policy = COLD_RETRY` el motor reintenta en frío, pero el reintento puede terminar
igual y «su estado nunca se mejora artificialmente» (`optimizers/router.py`).

El problema del test es una instancia **degenerada en el borde**: el mandato intersección tiene a la vez rotación máxima (0,05), peso
máximo (0,4) y límite de grupo (0,45) activos, más conos de segundo orden. Con la tolerancia cónica configurada
(`[conic] tol_gap_abs = tol_gap_rel = tol_feas = tol_infeas_* = 1e-9`) Clarabel está en el límite de lo alcanzable: unas pocas unidades
de redondeo deciden si alcanza `Solved` o termina en `AlmostSolved`.

### Experimento (reproducible, `benchmarks/scripts/h1_numerical_probe.py`)

No se dispone de la CPU que falla; se reproduce el **mecanismo** perturbando de forma determinista (semilla 0) los datos `b` y `q` que se
entregan a Clarabel en un error relativo `eps` (≈ lo que cambian el orden de sumas, FMA y vectorización entre CPU). 100 resoluciones por celda,
mismo problema que el primer test. Resultado de la ejecución sobre un árbol limpio (`3d0463b`; `benchmarks/results/h1_numerical_probe_20261020T204243Z.json`):

| `eps` (relativo) | tol 1e-9 (**configurada**): soluciones válidas | estados | iteraciones de Clarabel | tol 3e-9 | tol 1e-8 |
|---|---|---|---|---|---|
| 0 (sin perturbar) | 100/100 | 100 `OPTIMAL` | 10 | 100/100 | 100/100 |
| 1e-16 | **47/100** | 47 `OPTIMAL`, 53 `OPTIMAL_INACCURATE` (reintento en frío) | 9, 10, 20, 22 | 100/100 | 100/100 |
| 1e-15 | **35/100** | 35 / 65 | 9, 10, 20, 22 | 100/100 | 100/100 |
| 1e-14 | 35/100 | 35 / 65 | ídem | 100/100 | 100/100 |
| 1e-12 | 37/100 | 37 / 63 | ídem | 100/100 | 100/100 |
| 1e-10 | 5/100 | 5 / 95 | 9…28 | 100/100 | 100/100 |

Lectura: (1) sin perturbar, el motor es correcto y reproduce la «validez» de Windows/Intel; (2) **una perturbación de un solo ulp ya
invalida más de la mitad de las soluciones** cuando la tolerancia es 1e-9; (3) con 3e-9 o 1e-8 (el valor por defecto de Clarabel) **0 de 1.200
resoluciones** se degradan, también con perturbaciones 10⁴ veces mayores; (4) en ningún caso aparece una violación de restricciones
(`validation.violations` vacío): la solución es válida y el rechazo lo produce la política de estado, no el validador. La brecha
`|worst_case_utility − solver_t|` queda en 10⁻¹⁴…10⁻¹² (con la tolerancia configurada), coherente con los ≈5·10⁻¹⁵ de la anotación de CI.

## 3. Mecanismo del segundo fallo (oráculo del test)

El oráculo SLSQP usa `ftol = 1e-15` como precisión objetivo del valor de la función. El valor óptimo es `|x₄| ≈ 0,09`, cuyo ulp es
≈ 1,4·10⁻¹⁷: el objetivo equivale a ≈ 70 ulp, apenas por encima de la resolución de coma flotante (interpretación; lo que sí está medido es que
`success` pasa de 100 % a 67–76 % ante perturbaciones de 1 ulp y vuelve a 100 % con `ftol ≥ 1e-12`). Mismo problema, 100 arranques por celda con el punto inicial perturbado en `eps`:

| `ftol` | `eps` = 0 | `eps` = 1e-16 | `eps` = 1e-12 |
|---|---|---|---|
| **1e-15 (el del test)** | 100/100 | **67/100** (33 × «Positive directional derivative for linesearch») | **76/100** |
| 1e-12 | 100/100 | 100/100 | 100/100 |
| 1e-10 | 100/100 | 100/100 | 100/100 |

El mensaje coincide literalmente con el de CI. La dispersión del óptimo entre arranques es ≤ 5·10⁻¹³, mucho menor que las tolerancias
del test (`atol=1e-4` en pesos, `abs=1e-7` en el valor): el fallo es **del criterio de éxito del oráculo**, no del motor.

## 4. Qué se concluye y qué no

* **Concluido (con evidencia):** el mecanismo del primer fallo es la degradación `Solved → AlmostSolved` (⇒ `OPTIMAL_INACCURATE` ⇒ rechazo)
  de un problema cónico degenerado con tolerancia 1e-9, desencadenada por diferencias de redondeo del orden de 1 ulp; el del segundo es la
  fragilidad de SLSQP con `ftol = 1e-15`. Ambos son **independientes de B5** (B5 no toca estos módulos) y de los workers/caché.
* **No demostrado:** que el estado observado en el runner EPYC sea `AlmostSolved` (la anotación de CI trunca el `repr` del resultado). El
  paso `B5.5 H-1 numerical probe` de `ci.yml` anota el modelo de CPU y los porcentajes de validez en cada ejecución de CI; la sección 6
  recoge lo que haya aparecido.
* **No se cambia nada.** Subir la tolerancia cónica, aceptar `AlmostSolved` o relajar el oráculo son decisiones de una **remediación B4
  independiente**, con su propio baseline y revisión de impacto matemático (cualquier cambio de tolerancia afecta a todas las
  formulaciones cónicas y a `OPTIMAL` frente a `OPTIMAL_INACCURATE`, que `CLAUDE.md` exige distinguir).

## 5. Remediación propuesta (para una fase B4 independiente; no aplicada)

1. **Diagnóstico en CI** (barato, sin tocar semántica): que los dos tests, al fallar, impriman `status`, `status_source`, iteraciones de Clarabel,
   `validation.violations` y `lscpu`. Cierra la incertidumbre de §4.
2. **Oráculo del test 2:** usar `ftol ≥ 1e-12` (100 % de éxito en la sonda) o `trust-constr`/CVXPY como oráculo, y comparar el valor con la
   tolerancia ya existente (`abs=1e-7`); no depender de `result.success` con `ftol` por debajo de la resolución del objetivo.
3. **Política del motor (decisión de B4, con revisión matemática):** (a) elevar `tol_*` cónicas a un valor alcanzable en problemas
   degenerados (la sonda indica que 3e-9 ya basta; el defecto de Clarabel es 1e-8); o (b) conservar 1e-9 y reconocer explícitamente
   `AlmostSolved` tras la validación independiente (`accept_inaccurate_solutions = true` con el estado conservado como `OPTIMAL_INACCURATE`,
   nunca promovido a `OPTIMAL`); o (c) reintentar con tolerancias escalonadas registrando cuál se alcanzó. Cualquiera exige un test de
   regresión con perturbación de 1 ulp (la sonda de este documento es su prototipo) y un nuevo baseline de B4.
4. **Política de CI hasta entonces:** un fallo exacto de esos dos tests se re-ejecuta y se registra, nunca se enmascara (ya fijado en
   `AUDIT_BLOCK_5_3.md`).

## 6. Observaciones de CI en Linux durante B5.5

Durante B5.5 la CI (`ci.yml`, paso «B5.5 H-1 numerical probe») ejecutó la sonda de este documento en los runners de Linux y anotó los resultados (anotaciones públicas del run `39527318745`, `933c0cc`,
Linux 6.8 / Ubuntu 22.04 / Python 3.11.17):

| Runner | `tol` configurada 1e-9: validez con `eps` = 0 / 1e-16 / 1e-15 / 1e-14 / 1e-12 / 1e-10 | `tol` 3e-9 y 1e-8 | SLSQP `ftol=1e-15` con punto inicial perturbado (1e-16 / 1e-12) |
|---|---|---|---|
| Windows 11, i7-13620H (local) | 1,00 / 0,47 / 0,35 / 0,35 / 0,37 / 0,05 | 1,00 en todas | 0,67 / 0,76 |
| Linux, Intel Xeon Platinum 8573C (CI) | 1,00 / 0,47 / 0,45 / 0,37 / 0,27 / 0,02 | 1,00 en todas | 0,73 / 0,80 |

* **El mecanismo se reproduce en Linux/Intel con valores casi idénticos**: la degradación depende de que 1e-9 esté en el borde de lo alcanzable, no de Windows ni de una CPU concreta.
  Sin perturbar, el motor fue correcto en ambas plataformas (Linux: 9 iteraciones frente a 10 en Windows; brecha `|worst_case_utility − solver_t|` = 7·10⁻¹³ frente a 1·10⁻¹⁴).
* En los runs de B5.5 con pruebas ejecutadas los runners fueron Xeon (8573C ×2, 6973P-C) y un EPYC 9V45 (`ed3eab4`), y los dos tests de B4 **no fallaron** en ninguno: coherente con que el fallo original dependa de que el redondeo de la CPU caiga
  del lado `AlmostSolved`. El único EPYC 7763 sorteado (`f650607`) falló en la colección de pruebas por un defecto ajeno (extra `bench`), sin ejecutar ningún test: **el fallo original no se ha vuelto a observar ni
  descartado en esa CPU**.
* No hay motivo, con esta evidencia, para cambiar el diagnóstico de §4 ni la remediación de §5.
