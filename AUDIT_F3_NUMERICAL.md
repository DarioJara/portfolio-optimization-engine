# AUDIT_F3_NUMERICAL

# Auditoría cuantitativa independiente de la remediación F-3

**Rama auditada:** `fix/b2-numerical-f3` (árbol de trabajo, sin commits sobre `4089909`) · **Baseline:** tag `block3-validated` (`4089909`) · **Fecha:** 2026-09-24
**Alcance:** solo auditoría. No se modificó código, tests ni documentación existente; no hay commit, merge, push, tag ni PR; no se avanzó al Bloque 4. Único fichero creado en el repositorio: este informe. Todo el material auxiliar (scripts, copia del baseline, copia para mutantes) vive en el scratchpad de la sesión, fuera del árbol.

Entorno: `.venv` del proyecto (Python 3.13, osqp 1.1.3, scipy 1.18.1, numpy 2.5.3). El baseline se extrajo con `git archive block3-validated` y se ejecutó con `PYTHONPATH` apuntando a esa copia (se imprimió `portfolio_engine.__file__` para confirmar el árbol usado en cada ejecución).

---

## 1. Executive Summary

La remediación F-3 **corrige el defecto de forma real y reproducible**, con una transformación **algebraicamente exacta** (probada y verificada numéricamente), un oráculo LP que usa **las mismas filas** que el problema real, aceptación condicionada al `SolutionValidator` con el retorno objetivo original, y **cero deterioro** de resultados previamente `OPTIMAL`.

| Afirmación del implementador | Resultado de la auditoría |
|---|---|
| 77 puntos contractuales recuperados | **Confirmado** (reproducido: 77 → 0 inválidos, 14 fronteras GROSS/NET) |
| 212 puntos del barrido ampliado | **Confirmado** (reproducido: 17 fronteras / 212 puntos → 0; 11 200 fronteras, 224 000 puntos) |
| 1148 passed, 0 failed | **Confirmado** (ejecutado: `1148 passed in 140.83s`) |
| mypy / ruff | **Confirmado** (`Success: 126 files`; `All checks passed`; `259 files already formatted`) |
| Sin relajar tolerancias / sin cambiar `OPTIMAL` previos | **Confirmado** (11 183 fronteras sanas idénticas en iteraciones, hash de pesos y estados; 66 configuraciones propias idénticas al baseline) |
| Barrido 1400-2999 sin baseline | Correctamente presentado como «solo código nuevo»: 12 800 fronteras, 255 982 puntos, 0 inválidos (reproducido) |

No se hallaron hallazgos numéricos ni económicos bloqueantes. Se registran 8 hallazgos **no bloqueantes** (2 huecos de cobertura de tests detectados por mutación, 1 limitación de diagnóstico, 1 riesgo de rendimiento heredado y 4 precisiones documentales/observaciones). El más relevante es **AF3-01**: el test que la trazabilidad cita como evidencia de que «`OPTIMAL_INACCURATE` no se promueve» en el reintento **no ejercita** ese camino (el mutante que lo acepta sobrevive); el código es correcto por inspección, pero la evidencia citada es más débil de lo declarado.

**Decisión: `PASS`** (con recomendación de cerrar AF3-01/AF3-02 con dos tests antes o inmediatamente después de integrar).

---

## 2. Root Cause Verdict

**Veredicto: causa raíz correctamente identificada; el diagnóstico es coherente con la evidencia reproducida.**

Reproducción independiente del defecto en el baseline `block3-validated` (script propio, referencia independiente para `n = 2` = solución analítica; para `n = 3` NET = SLSQP por regiones de compra/venta; ambos del fixture del implementador pero re-invocados desde mi script):

| Instancia | GROSS (baseline) | NET (baseline) |
|---|---|---|
| (2, 84) | 18 `INFEASIBLE` | 0 |
| (2, 184) | 18 `INFEASIBLE` | 0 |
| (2, 193) | 18 `INFEASIBLE` | 0 |
| (2, 89) | 0 | 18 `INFEASIBLE` |
| (3, 67) | 0 | 3 `NUMERICAL_ERROR` |
| (2, 159) | 0 | 1 `MAX_ITERATIONS` |
| (2, 19) | 0 | 1 `OPTIMAL_INACCURATE` |
| **Total** | 54 | 23 → **77 puntos** |

Los cuatro estados originales (`INFEASIBLE`, `NUMERICAL_ERROR`, `MAX_ITERATIONS`, `OPTIMAL_INACCURATE`) se reproducen en el baseline. En la rama, los 77 puntos son `OPTIMAL`, válidos y verificados con una comprobación **propia e independiente del motor** (retorno bruto/neto recomputado desde `w`, `μ`, costes y `w0`; presupuesto; cotas): violación máxima `≤ 2·10⁻⁹` (la mayor, NET (2,159), es holgura de la tolerancia OSQP, muy por debajo de `constraint_tolerance = 1e-7`).

Mecanismo: la fila de retorno es casi paralela a la fila de presupuesto (retornos casi idénticos en GROSS; costes que casi anulan la pendiente de `μ` en NET), de modo que su información útil es ≪ su magnitud y ADMM (OSQP) declara inviabilidad espuria o no converge. Los casos son factibles (LP de HiGHS con las mismas filas: 77/77 factibles). La afirmación de que el ajuste de OSQP por sí solo no lo resuelve no se reprodujo punto a punto (fuera de alcance), pero la corrección funciona con la configuración de OSQP inalterada, lo que es coherente con la causa declarada.

---

## 3. Mathematical Equivalence

### 3.1 Demostración

Sea el problema canónico `min ½xᵀPx + qᵀx  s.a.  l ≤ Ax ≤ u`, con fila 0 = presupuesto `e` (`l₀ = u₀ = b`, garantizado por código: `normalize_return_row` lanza `FrontierError` si `l₀ ≠ u₀`) y fila de retorno `r` con `l_r = target + offset`, `u_r = +∞` (última fila de `_constraint_rows`; `offset = K_E/H` en NET y `0` en GROSS).

La transformación es `r' = s·(r − λe)`, `l'_r = s·(l_r − λb)`, `λ = rᵀe/eᵀe`, `s > 0`. Para todo `x` con `eᵀx = b` (fila 0 activa, igualdad):

`r'ᵀx − l'_r = s·(rᵀx − λeᵀx − l_r + λb) = s·(rᵀx − l_r) + sλ(b − eᵀx) = s·(rᵀx − l_r)`.

Como `s > 0`, `r'ᵀx ≥ l'_r ⇔ rᵀx ≥ l_r` **sobre el hiperplano de presupuesto**, y `u_r = +∞` es invariante. Por tanto:

* mismas variables (`x` no se transforma; los pesos se leen tal cual);
* mismo objetivo (`P`, `q` no se tocan; `dataclasses.replace(normalized.problem, q=q, ...)` reutiliza el `q` original);
* mismas restricciones económicas (las demás filas y `upper` no se tocan);
* mismo conjunto factible `{x : eᵀx = b, …, rᵀx ≥ l_r}` y mismas soluciones óptimas.

**Condición necesaria:** la equivalencia exige `eᵀx = b` exactamente. El contrato del problema lo impone como **igualdad** (fila 0 con `l = u`, verificado en código) y el `SolutionValidator` la comprueba con `budget_tolerance`. En aritmética finita, un residuo de presupuesto `ε_b` desplaza la fila transformada en `s·λ·ε_b` (equivale a `λ·ε_b` en unidades de retorno, `λ ~ 10⁻²…10⁻¹`, `ε_b ≲ 10⁻⁹` con `eps_abs = 1e-9`): despreciable, y **no puede provocar una aceptación indebida**, porque el punto recuperado se valida contra el retorno objetivo **original** (no el transformado). La normalización solo cambia `A[return_row, :]`, incluidas las columnas auxiliares `b, s` (el centrado solo resta `λ·e` en las columnas de peso, y `e` es cero en las auxiliares; correcto).

### 3.2 GROSS, NET y POST_COST_GROSS

* **GROSS:** `r = μ` (sin columnas auxiliares salvo turnover lifting, donde sus coeficientes son 0). `offset = 0`. Equivalencia directa.
* **NET:** `r = [μ, −c_b, −c_s]`; la cota incluye `+ K_E/H` (liquidación constante de activos retirados), que forma parte de `l_r` y por tanto se transforma como cualquier constante (`l'_r = s·(l_r − λb)`). Los costes de compra/venta viven en las columnas auxiliares, que se conservan; `b, s ≥ 0` y `w − b + s = w0` no se tocan. Sin ninguna dependencia de signo o de pendiente: equivalencia exacta también con retorno neto de pendiente casi nula (esa es precisamente la región donde el escalado ayuda).
* **POST_COST_GROSS:** no se optimiza; hereda los pesos de GROSS (`FrontierError` si se intenta construir). Verificado que hereda los pesos recuperados (test del implementador y 7/7 instancias con resultados idénticos a GROSS en la reproducción).

### 3.3 Verificación numérica independiente

Script propio sobre 5 tipos de problema (`plain`, `group`, `turnover`, `retired`, `singular`) × GROSS/NET × retornos dispersos y casi idénticos × escalas `{1, 10, 100}` (60 normalizaciones, `n = 6`):

* Las demás filas, `upper`, `q` y `P` son **idénticos bit a bit** al problema original.
* Identidad `r'x − l'_r = s·(rx − l_r)` sobre 200 vectores `x` aleatorios por caso con `Σw = b` (incluyen columnas auxiliares): error relativo máximo **3,3·10⁻¹⁰** (redondeo de punto flotante con `s` grande).
* Donde original y transformado resuelven, los pesos coinciden: `‖Δw‖∞ ≤ 4,6·10⁻⁸` (NET con dispersión 10⁻⁵, tolerancia OSQP), `≤ 10⁻¹⁵` en casos bien condicionados. En GROSS con retornos casi idénticos el original devuelve `INFEASIBLE` (el defecto) y el transformado `OPTIMAL` en las tres escalas.

**Veredicto: transformación matemáticamente equivalente; sin condiciones ocultas más allá de `eᵀx = b`, garantizada por el contrato.**

---

## 4. LP Oracle Verdict

`feasibility_oracle.lp_feasibility` construye `dataclasses.replace(problem, P = 0, q = 0, lower = lower, problem_class = LP)`: **misma `A`, mismo `upper`, mismo `lower` (con el retorno objetivo original)**, objetivo nulo, resuelto con `HiGHSLPBackend` (algoritmo distinto de ADMM). Por construcción cubre presupuesto, cotas por activo, restricciones de grupo, activos retirados (vía `return_offset` y `exit_turnover` en la fila de turnover), costes (columnas y fila de retorno neto), turnover y variables auxiliares: no existe una versión simplificada. No reutiliza ningún resultado de OSQP.

Reproducción (script propio, sesión con `TargetReturnGrid.solve_target`):

* **Caso A — factible declarado `INFEASIBLE` por OSQP:** (2,84) GROSS, (2,193) GROSS, (2,89) NET, con objetivos `R_max − {10⁻⁶, 10⁻⁷, 10⁻⁸, 0}`: OSQP `INFEASIBLE` → oráculo `FEASIBLE` → reintento normalizado `OPTIMAL` → `RECOVERED`, `valid = True`, violación `≤ 4,3·10⁻¹⁴`.
* **Caso B — objetivo realmente superior al máximo:** `R_max + {10⁻¹⁰, 10⁻⁹, 5·10⁻⁹, 10⁻⁸, 10⁻⁷, 10⁻⁶, 10⁻³}` (con `R_max` de un LP independiente `scipy.linprog`): `INFEASIBLE`, oráculo `INFEASIBLE`, `CONFIRMED_INFEASIBLE`, **sin ningún reintento** (`attempts = [ORIGINAL, LP_FEASIBILITY_ORACLE]`), sin solución expuesta. Confirmado en las cuatro instancias probadas, hasta un margen de `10⁻¹⁰` sobre el máximo.

Tolerancias ocultas: el LP usa `lp_feasibility_tolerance = 1e-9` (parámetro configurable ya existente, no introducido por F-3). En la práctica, con HiGHS el margen `+10⁻¹⁰` sobre `R_max` ya se declara `INFEASIBLE` en n = 2 (presolve). Ver AF3-03 para el caso no cubierto por el oráculo (estados ambiguos).

**Veredicto: el oráculo representa fielmente el problema; A activa recuperación, B permanece `INFEASIBLE` sin aceptar solución inexistente.**

---

## 5. Recovery State Machine

Máquina verificada por lectura de `numerical_recovery.py` y por ejecución/mutación:

```
OSQP → estado ∈ {OPTIMAL}: no interviene (fronteras sanas idénticas: 0 diferencias)
     → estado ∈ {INFEASIBLE, NUMERICAL_ERROR, MAX_ITERATIONS, OPTIMAL_INACCURATE, UNKNOWN} y hay retorno objetivo finito y numerical_recovery = true:
        [INFEASIBLE | NUMERICAL_ERROR | UNKNOWN] → LP HiGHS
              INFEASIBLE → CONFIRMED_INFEASIBLE (fin; estado original conservado)
        para cada escala en recovery_row_scales (≤ 3 QP, workspace nuevo, max_iter × 4):
              OPTIMAL y SolutionValidator(objetivo ORIGINAL) → RECOVERED (fin)
              OPTIMAL rechazado → registrado (rejected_by_validator), siguiente escala
        sin recuperación → NOT_RECOVERED; INFEASIBLE con LP FEASIBLE → NUMERICAL_ERROR; resto: estado original
```

Comprobaciones:

* **Trazabilidad (`SolveResult.recovery`)**: `RecoveryTrace(trigger_status, trigger_native_status, feasibility, attempts, outcome)` y por intento `strategy, solver_name, status, native_status, iterations, primal_residual, dual_residual, row_scale, rejected_by_validator`. Cubre estado inicial, motivo, veredicto LP, configuración/escala de cada intento, estados, iteraciones, residuales y estado final. El estado inicial se conserva (mutantes M6/M6b lo detectan). Las iteraciones del resultado suman todos los intentos (excepto el oráculo LP).
* **Punto recuperado inválido → rechazado:** cubierto por el test del validador (mutante M2 muerto).
* **`OPTIMAL_INACCURATE` no se promueve:** el código lo garantiza (`optimal = retried.status is SolverStatus.OPTIMAL`), pero ver **AF3-01**: el test asociado no ejercita el camino.
* **`INFEASIBLE` falso no queda como infactibilidad confirmada:** o se recupera, o se reclasifica a `NUMERICAL_ERROR` (reproducido con escala inservible `1e-9`, test del implementador).
* **`INFEASIBLE` verdadero no pasa a `OPTIMAL`:** caso B.
* **Límites deterministas / sin ciclos:** ≤ 1 LP + `len(recovery_row_scales)` QP por punto, sin recursión; el mutante M11 (escalera ×3) es detectado. Coste del punto patológico peor observado: 4 intentos, 294 000 iteraciones en 0,16 s (`(3,67)` NET a `R_max + 10⁻⁹`).
* La recuperación **solo** se activa con `target` (TARGET_RETURN_GRID, incluida la adaptativa): en mis barridos adversariales con `RISK_AVERSION_GRID` no hubo ninguna activación (`recovery_on_theta!! = 0`) y en el barrido principal la recuperación estuvo activa **solo** en las 17 fronteras defectuosas (0 fronteras sanas afectadas).

---

## 6. Financial Validation

Un punto recuperado debe cumplir simultáneamente: (1) estado final `OPTIMAL`; (2) restricciones originales; (3) retorno objetivo **original**; (4) tolerancias aprobadas sin relajar (`constraint_tolerance = bound_tolerance = budget_tolerance = 1e-7`, sin cambios en `config`); (5) `SolutionValidator` (`is_valid_solution`, `validation.is_valid`); (6) optimalidad contrastada (§7).

Verificado: `FrontierPoint.target_return` conserva el objetivo original; el validador se invoca con ese objetivo (`_passes_validation(retried, target)`), y el mutante M4a (validar contra `target − 10⁻³`) es detectado. Para cada uno de los 77 puntos recuperados, mi comprobación independiente (no usa `SolutionValidator`) da violación máxima `≤ 2·10⁻⁹`. `SolutionValidator` no se modificó (diff vacío).

---

## 7. Independent Optimality Evidence

`SolutionValidator` prueba factibilidad, no optimalidad; por tanto se contrastó la varianza de cada punto con referencias independientes:

* **n = 2:** solución analítica exacta (`two_asset_reference`: argmin cuadrático recortado por intervalos de compra/venta). Puntos interiores de las 14 fronteras: GROSS `|Δvar| ≤ 3,5·10⁻¹⁷`; NET (2,89) `≤ 5,4·10⁻¹⁵`; NET (2,19) `≈ 9·10⁻¹⁰`; NET (2,159): los puntos recuperados coinciden con `1,4·10⁻¹⁵`.
* **n = 3 NET (3,67):** SLSQP por regiones (2³ regiones lineales de compra/venta): `|Δvar| ≤ 1,3·10⁻⁶` en todos los puntos, con el punto recuperado a `~10⁻⁹`.
* **Sobre el «1,3·10⁻⁷» declarado:** lo he reproducido, pero **no pertenece a un punto recuperado**: corresponde al índice 17 de la frontera NET (2,159), un punto `OPTIMAL` en el baseline (sin recuperación), con violación de retorno de `1,9·10⁻⁹` (holgura de la tolerancia de OSQP, amplificada por la pendiente de la frontera cerca del vértice). El punto recuperado de esa frontera (índice 16, objetivo `0,14256188`) coincide con la referencia a `1,4·10⁻¹⁵`. Ver AF3-04.
* **Extremo de máximo retorno (índice 19):** difiere de la referencia por `3,9·10⁻⁴` (2,84 GROSS), `4,2·10⁻⁶` (2,159 NET), `5,1·10⁻⁶` (2,89 NET). Es **idéntico en el baseline** (mismo valor antes y después) y se debe a la holgura de la etapa 2 de MaximumReturn (A-14, `max_return_tie_*_tolerance`), no a F-3. No es una regresión ni un hallazgo de F-3; se anota como observación heredada (AF3-08).
* No se aceptó ningún `OPTIMAL_INACCURATE` como `OPTIMAL` en ninguna ejecución (0 puntos con estado `OPTIMAL_INACCURATE` válidos en los barridos).

---

## 8. Contractual Cases

Las 7 instancias × GROSS/NET (POST_COST_GROSS hereda GROSS): **77 puntos inválidos → 0**, 14 fronteras × 20 puntos todos `OPTIMAL` con `is_valid_solution = True` (tabla completa en §2). Iteraciones tras la remediación (reproducidas): (2,84) GROSS 1 200 → 2 550; (2,89) NET 502 025 → 1 121 675; (3,67) NET 994 025 → 1 045 475; (2,159) NET 904 725 → 913 075; (2,19) NET 2 680 225 → 2 694 825; las 7 fronteras sin defecto conservan exactamente sus iteraciones (p. ej. (2,84) NET 4 775, (3,67) GROSS 9 650). Coinciden con la tabla del implementador.

## 9. Additional Sweeps

Script propio (misma lógica de generador que el test de propiedades), `TARGET_RETURN_GRID`, `n = 2…5`, GROSS/NET, ejecutado sobre **ambos árboles**:

| Barrido | Fronteras | Puntos | Baseline: inválidos | Rama: inválidos |
|---|---|---|---|---|
| Semillas 0-1399 | 11 200 | 224 000 | **17 fronteras / 212 puntos** | **0** |
| Semillas 1400-2999 (solo rama; **sin baseline medido**, no se presenta como antes/después) | 12 800 | 255 982 | — | **0** (10 fronteras / 142 puntos con recuperación activa, todos recuperados) |

Lista de las 17 fronteras defectuosas del baseline: `2|19 NET, 2|84 GROSS, 2|89 NET, 2|159 NET, 2|184 GROSS, 2|193 GROSS, 2|329 GROSS, 2|627 GROSS, 2|655 GROSS, 2|685 NET, 2|845 GROSS, 2|878 NET, 2|1115 NET, 2|1192 NET, 2|1229 NET, 2|1342 GROSS, 3|67 NET` (las 7 contractuales + 10 del barrido: coincide exactamente con lo declarado). **Fronteras sanas del baseline (11 183): idénticas en iteraciones totales, hash SHA-256 de pesos y cadena de estados (0 diferencias).** Recuperación activa en 0 fronteras sanas.

Recuperación (barrido 0-1399): 212 puntos con traza, 625 intentos totales (≈ 2,95 por punto: consistente con `ORIGINAL + LP + 1 reintento` en `INFEASIBLE` y `ORIGINAL + 1 reintento` en los demás; es decir, prácticamente **una sola escala (10)** por punto).

### 9.1 Escenarios adversariales focalizados (propios; recuperación activada vs desactivada, mismos datos)

Generador propio de instancias (n = 6 y 8; dispersión de retornos 0, 10⁻⁵, 10⁻⁶; costes de compra/venta aleatorios y asimétricos), GROSS y NET, `TARGET_RETURN_GRID` y `RISK_AVERSION_GRID`:

| Escenario | n | Resultado |
|---|---|---|
| `plain` (sin restricciones extra) | 6 | 216 puntos inválidos en baseline-equivalente (recuperación off) → 0 con recuperación; 216 `RECOVERED` |
| `group` (Tech ≤ 55 %, `MaxWeight` 0,5) | 6 | idem (216 → 0) |
| `turnover` (`MaxTurnover = 0,35`, activos NET con turnover lifting) | 6, 8 | 360 inválidos → 0 |
| `retired` (activo actual excluido de la composición: NET con `return_offset` ≠ 0) | 6, 8 | 360 inválidos → 0 |
| `singular` (Σ de rango reducido + 10⁻⁹·I) | 6, 8 | 360 + 1 inválidos → 0 |
| `RISK_AVERSION_GRID` (todos los escenarios) | 6, 8 | **0** puntos inválidos con y sin recuperación; recuperación nunca activada |
| **Puntos previamente `OPTIMAL` cuyo resultado cambia** | todos | **0** (`CHANGED_previously_optimal = 0`; comparación de pesos byte a byte, iteraciones y estado) |
| Excepciones | todos | 0 |

Además: **Frontera adaptativa** (`adaptive = true`, 8 puntos iniciales, tolerancia 0,02) sobre (2,84) GROSS, (2,89) NET, (3,67) NET: con recuperación, 20 puntos y 0 inválidos; sin recuperación, 9 puntos con 7 inválidos (2 casos) y 20 con 2 inválidos: la adaptativa se beneficia sin efectos secundarios. **Sigma casi singular** (10⁻⁹): cubierto. **E-09/E-10/E-11:** su comportamiento no cambia (módulos no tocados; suites de B3 verdes; 66 configuraciones idénticas, §11); no construí instancias F-3 específicas de E-09/E-11 (ver AF3-08, cobertura no exhaustiva).

Cobertura declarada de la prueba adversarial: representativa (no cartesiana): cubre los mecanismos que alteran filas/columnas de la fila de retorno (activos retirados → `return_offset`), estructura de restricciones (grupos, turnover, cotas) y condicionamiento (Σ singular, retornos casi idénticos, retornos dispersos con costes que anulan pendiente NET) y `n > 5`. No sustituye a una validación con datos de mercado reales.

---

## 10. Numerical Robustness

* **Escalera `[10, 1, 100]`** (`weight_scale` = máximo `|coef|` de peso de la fila centrada): en el barrido, la primera escala resuelve **todos** los puntos (212/212, y 142/142 en el barrido adicional; en mis 5 escenarios `n = 6/8`, 0 fallos tras la recuperación). Las escalas 1 y 100 **funcionan** como alternativas (mi test de equivalencia resolvió con las tres escalas todos los casos en que el original también resolvía (y los de GROSS casi idéntico, donde el original da `INFEASIBLE`); y con la escalera de un solo peldaño inservible `1e-9` el validador la rechaza correctamente). Sin embargo, **no se han necesitado con datos reales**: son una protección empírica no validada por casos que las requieran (AF3-05). La elección de 10 por el implementador se sostiene en su tabla de sensibilidad (1/10/100/1000 → 67/77/61/69 puntos de 77); dependencia de las semillas originales: los 77 puntos son la base de la calibración, pero la validación cruzada con 12 800 fronteras nuevas (semillas 1400-2999, más `n = 6/8` propios) sin un solo fallo indica que no hay sobreajuste evidente.
* **Ninguna escala funciona:** el punto queda `NOT_RECOVERED`, **inválido y correctamente etiquetado** (`NUMERICAL_ERROR` si venía de `INFEASIBLE` con LP factible; estado original en otro caso), nunca aceptado; verificado con `max_iterations = 25` y con escala `1e-9`.
* **Nuevos campos de `SolverConfig`:** `numerical_recovery: bool` (validado como booleano estricto: `1` → `ConfigError`) y `recovery_row_scales: tuple[float, ...]` (cada valor `> 0`; no vacía si la recuperación está activa; puede ser vacía con la recuperación desactivada). Valores por defecto en `config/default_engine.toml` (`true`, `[10.0, 1.0, 100.0]`); sin literales en el código de recuperación. Ambos campos son obligatorios (un TOML propio sin ellos falla con `ConfigError`, como el resto de la sección).
* **Serialización / `ConfigHash`:** `config_to_dict` serializa `recovery_row_scales` como lista y `numerical_recovery`; el hash cambia con cualquiera de los dos parámetros (verificado) y es estable entre construcciones idénticas. `ConfigHash` del baseline `1a28bd87…` → rama `3d1758c0…`: cambio legítimo (dos campos nuevos en el snapshot), esperado y documentado; **invalidará claves de caché futuras que incluyan `ConfigHash`**, lo cual es el comportamiento correcto (los resultados pueden diferir en fronteras defectuosas). No se exige igualdad con el hash histórico.

---

## 11. Regression B1/B2/B3

* `pytest -q` (con `-p no:cacheprovider`): **`1148 passed in 140.83s`**, 0 failed, 0 skipped (= 1039 baseline + 109 nuevos; el conteo coincide). Incluye B1 (config, datos, retornos, covarianza, costes), B2 (restricciones, factibilidad, backends, fronteras, validador, propiedades) y B3 (`CandidateEngine`, frontera global, E-09/E-10/E-11, Pareto global).
* `mypy --strict portfolio_engine`: `Success: no issues found in 126 source files`. `ruff check .`: `All checks passed!`. `ruff format --check .`: `259 files already formatted`. (Ejecutados solo en modo comprobación; **no** se ejecutó `ruff format .`.)
* **Huella independiente vs baseline** (no reutiliza la del implementador; 66 configuraciones propias: 5 tipos de problema × `n ∈ {4, 6}` × {GROSS, NET, POST_COST_GROSS} × {RISK_AVERSION_GRID, TARGET_RETURN_GRID} = 60, más `GlobalCandidateFrontierEngine` sobre `two_region_problem` × 3 tratamientos × 2 métodos = 6). Para cada punto: SHA-256 de pesos, estado, validez, iteraciones, retorno bruto/neto, volatilidad, coste de transacción, turnover; para la frontera global además `global_point_id`, bandera de eficiencia global e identificadores de candidatas. **72 de 72 claves idénticas; 0 diferencias.** Los puntos previamente `OPTIMAL` son idénticos en pesos, métricas, estados, iteraciones y banderas de validez. La única diferencia observada entre árboles (aparte del `ConfigHash`) son las fronteras defectuosas (inválidas → válidas), explicada.
* Módulos declarados sin cambios verificados en el diff: `osqp_backend.py`, `highs_backend.py`, `router.py`, `status.py`, `SolutionValidator`, `ConstraintCompiler`, `TransactionCostModel`, `CandidateEngine`, `global_frontier.py`, `pareto.py`, `outputs/`.

---

## 12. Performance

Recuento de llamadas (fiable) y tiempos (orientativos: la máquina es bimodal, ver memoria del proyecto; la ejecución de mis barridos se solapó con otros procesos):

| Medida (barrido 0-1399, 11 200 fronteras) | Baseline | Rama |
|---|---|---|
| Iteraciones OSQP totales | 149 087 500 | 153 274 125 (**+2,81 %**) |
| Frontera más cara (2,1115 NET) | — | 5,23 M iteraciones (2,3 s en esta máquina) |
| Tiempo acumulado (una ejecución) | 358,8 s | 334,0 s (ruido; no se usa como prueba) |

* **Coste del oráculo LP:** 4,3–5,9 ms por llamada (n = 2 GROSS y n = 5 NET, mediana de 20).
* **Reintentos:** 212 puntos recuperados con 625 intentos totales; la escalera completa no se agota en el caso real. Cota dura por punto: 1 LP + 3 QP de 200 000 iteraciones (+ el arranque original de 250 000).
* **Punto patológico no recuperable** (`(3,67)` NET a `R_max + 10⁻⁹`): 294 000 iteraciones / 0,16 s frente a 250 000 / 0,13 s sin recuperación: incremento aceptable.
* **Fronteras sanas:** no pagan nada (0 activaciones, 0 diferencias). **Fronteras defectuosas:** más caras (p. ej. (2,84) GROSS 1 200 → 2 550 iteraciones, ≈ 10× en tiempo por los ~10–18 llamadas al LP); es el coste de recuperar 18 puntos que antes eran inválidos.
* **NET n = 2 con > 1 M iteraciones agregadas:** existían en el baseline (p. ej. (2,89) NET 502 025; (2,19) NET 2,68 M) y son propiedad de ADMM en franjas casi degeneradas; la recuperación añade 12–120 % a esas fronteras concretas (p. ej. (2,89) NET 502 k → 1,12 M por 18 puntos recuperados). No hay degradación sistemática de fronteras sanas ni latencia patológica observada (máximo del barrido 2,3 s por frontera). Riesgo de timeouts en procesamiento multi-cartera: bajo pero real para carteras con muchas fronteras casi degeneradas; ver AF3-06.

---

## 13. Mutation Evidence

Copia aislada del árbol (scratchpad, no el repositorio). 14 mutantes; ejecutados los 4 ficheros de tests relevantes (`test_numerical_recovery.py`, `test_return_row_normalization.py`, `test_solver_recovery_config.py`, `test_known_solver_status_cases.py`; 118 tests; ejecución con `-x`).

| Mutante | Resultado |
|---|---|
| M1 desactivar el oráculo LP | **KILLED** |
| M2 aceptar el reintento sin `SolutionValidator` | **KILLED** |
| M3 aceptar `OPTIMAL_INACCURATE` como reintento válido | **SURVIVED** (AF3-01) |
| M4a validar contra un target relajado (`target − 10⁻³`) | **KILLED** |
| M4b omitir el desplazamiento del presupuesto en la cota transformada | **KILLED** |
| M5 invertir la escala (`/` en vez de `×`) en la cota | **KILLED** |
| M6 perder el intento original en la traza | **KILLED** |
| M6b perder el estado inicial (`trigger_status`) | **KILLED** |
| M7 no confirmar la infactibilidad del LP (tratar toda infactibilidad como numérica) | **KILLED** |
| M7b reclasificar `INFEASIBLE → NUMERICAL_ERROR` sin exigir veredicto `FEASIBLE` | **SURVIVED** (AF3-02) |
| M8 el oráculo con la fila de retorno libre (`problem.lower`) | **KILLED** |
| M9 ignorar `numerical_recovery = false` | **KILLED** |
| M10 el oráculo nunca devuelve `INFEASIBLE` | **KILLED** |
| M11 escalera sin límite (×3) | **KILLED** |
| M12 no centrar la fila de retorno | **KILLED** |

**12 de 14 detectados.** Los 2 supervivientes son huecos de cobertura, no defectos del código actual.

---

## 14. Traceability

* F-3 consta expresamente en `ARCHITECTURE.md` (nuevo §3.5 con decisiones `F3-01…F3-08`, y los dos módulos nuevos en el árbol), `TRACEABILITY.md` (nota de cabecera, evidencia ampliada en `FRN-008`, `FRN-023`, `VAL-001`, `SOL-002`, `OPT-005`, `CFG-008`, y fila de historial) y `CHANGELOG.md` (nueva sección «Remediación numérica independiente F-3», posterior a `block3-validated`).
* Total contractual **316** `RequirementID` (183 `VALIDATED`, 39 `PARTIAL`, 94 `NOT_IMPLEMENTED`) sin cambios; **ningún cambio de estado**; `SOL-002` sigue `PARTIAL` (Clarabel/B4). Verificado por diff de `TRACEABILITY.md` (solo añade evidencia, no toca columnas de estado).
* Informes históricos intactos: `git diff block3-validated` vacío para `AUDIT_BLOCK_*.md`, `REMEDIATION_BLOCK_3*.md`, `MASTER_SPEC.md` e `IMPLEMENTATION_PROMPTS.md`.
* Sin implementación prematura del Bloque 4 (sin Clarabel, SOCP, CVaR, escenarios, MIQP, multiprocessing ni persistencia; `optimizers/` solo gana `feasibility_oracle.py`).
* Precisión de la evidencia: ver AF3-01 (el test citado para «`OPTIMAL_INACCURATE` no se promueve» no lo ejercita).

---

## 15. Residual Findings (todos no bloqueantes)

### AF3-01 — Test de «no promoción de `OPTIMAL_INACCURATE`» no ejercita el camino (Media)
* **Evidencia:** el mutante M3 (`optimal = retried.status in (OPTIMAL, OPTIMAL_INACCURATE)`) **sobrevive** a los 118 tests. `test_an_inaccurate_retry_is_never_promoted_to_optimal` usa `max_iterations = 25` y los reintentos terminan `MAX_ITERATIONS`/`INFEASIBLE`, nunca `OPTIMAL_INACCURATE`. `TRACEABILITY.md` cita ese test como evidencia de `SOL-002`/`FRN-023`.
* **Impacto:** el código actual es correcto (`is SolverStatus.OPTIMAL`), pero una regresión futura podría promover un reintento inexacto sin que ningún test falle; la garantía «nunca se promueve» está respaldada solo por inspección.
* **Reproducción:** en la copia aislada, sustituir esa línea de `numerical_recovery.py` y ejecutar los 4 ficheros de tests: `118 passed`.
* **Recomendación:** añadir un test con un backend/`SolverRouter` simulado que devuelva `OPTIMAL_INACCURATE` en el reintento y comprobar `NOT_RECOVERED` y estado no `OPTIMAL`.

### AF3-02 — Camino `INCONCLUSIVE` del oráculo sin test a nivel de frontera (Baja)
* **Evidencia:** el mutante M7b (reclasificar `INFEASIBLE → NUMERICAL_ERROR` sin exigir veredicto `FEASIBLE`) sobrevive. El caso `INCONCLUSIVE` (HiGHS alcanza un límite) se prueba a nivel de oráculo, pero no su efecto sobre el estado final del punto.
* **Impacto:** si HiGHS no concluye, la regla actual conserva `INFEASIBLE` (correcto y conservador); un cambio que lo reclasificara no sería detectado.
* **Reproducción:** ver M7b en §13.

### AF3-03 — El oráculo no se consulta para `MAX_ITERATIONS` / `OPTIMAL_INACCURATE` (Baja)
* **Evidencia:** `ORACLE_STATUSES = {INFEASIBLE, NUMERICAL_ERROR, UNKNOWN}`. En `(3,67)` NET a `R_max + 10⁻¹⁰` y `+10⁻⁹` (objetivos realmente infactibles) el punto termina `OPTIMAL_INACCURATE` / `MAX_ITERATIONS` con `feasibility = None`, no `INFEASIBLE` confirmado.
* **Impacto:** un objetivo infactible por un margen ≲ 10⁻⁹ se reporta con un estado ambiguo (inválido, no aceptado) en vez de `INFEASIBLE` confirmado. Es un diagnóstico más débil, no una aceptación indebida. No afecta a mallas de `TARGET_RETURN_GRID`, cuyo máximo es el extremo alcanzable.
* **Reproducción:** `TargetReturnGrid(session).solve_target(R_max + 1e-9)` sobre `nd.instance(3, 67)` NET.

### AF3-04 — Precisiones documentales en `REMEDIATION_F3_NUMERICAL.md` / `ARCHITECTURE.md` (Informativa)
* El «error de varianza máximo 1,3·10⁻⁷ (NET (2,159))» se presenta junto a las fronteras recuperadas, pero pertenece a un punto ya `OPTIMAL` en el baseline (§7); el punto recuperado coincide a `1,4·10⁻¹⁵`.
* «Un `INFEASIBLE` confirmado por el LP conserva `status_source = SOLVER`»: en `(3,67)` NET el estado conservado tiene `status_source = CROSS_CHECK`, porque el resultado inicial ya procedía de un cross-check de `solve_with_policy` (el código conserva `first.status_source`; el comportamiento es correcto, la frase es imprecisa).
* `ARCHITECTURE.md`: falta una línea en blanco antes del encabezado `### 3.5` (defecto de formato).

### AF3-05 — Escalera `[10, 1, 100]` empírica; peldaños 1 y 100 no exigidos por ningún caso real (Baja)
* **Evidencia:** 212/212 (y 142/142) puntos recuperados con la escala 10; la sensibilidad 1/10/100/1000 da 67/77/61/69 de 77 puntos.
* **Impacto:** no hay garantía general de que otras geometrías no necesiten más escalas; el fallo se degrada de forma segura (punto inválido y etiquetado). Reconocido por el implementador en §11.

### AF3-06 — Convergencia lenta de ADMM en NET n = 2 y riesgo de latencia (Baja, heredado)
* **Evidencia:** fronteras con hasta 5,2 M iteraciones (2,3 s); la recuperación añade ~2,8 % de iteraciones globales en el barrido y hasta ×2,2 en fronteras defectuosas concretas.
* **Impacto:** aceptable hoy; en lotes de muchas carteras casi degeneradas puede pesar. La solución estructural (segundo QP con método de punto interior, Clarabel en B4) está fuera de alcance; conviene reevaluar la escalera entonces.

### AF3-07 — `ConfigHash` cambia y `SolverConfig` gana dos campos obligatorios (Informativa)
* **Impacto:** invalida cachés/hashes previos (deseable); los TOML propios deben declarar los dos campos nuevos. Documentado.

### AF3-08 — Observaciones heredadas y de alcance (Informativas)
* La recuperación cubre solo puntos con retorno objetivo (`TARGET_RETURN_GRID`, incluida la adaptativa); MinVariance, la etapa 2 de MaximumReturn y `RISK_AVERSION_GRID` quedan fuera (sin fallos observados en mis barridos, 0 con y sin recuperación).
* El extremo de máximo retorno (índice 19) difiere de la varianza exacta por hasta `3,9·10⁻⁴` cuando la dispersión de retornos es ~10⁻⁶: consecuencia de la holgura A-14 de la etapa 2 de MaximumReturn, idéntica en el baseline; no es de F-3.
* `constraint_tolerance = 1e-7` no discrimina si la dispersión de retornos es ≲ 10⁻⁷ (heredado y documentado; el punto recuperado se valida y no se relaja nada).
* No se construyeron instancias F-3 específicas con E-09/E-11 ni con `MinWeight`/liquidez; su comportamiento se cubre por «módulos sin cambios + 72/72 huellas idénticas + suite B3 verde».

**Hallazgos bloqueantes abiertos: 0.**

---

## 16. Git Hygiene

```text
git branch --show-current       → fix/b2-numerical-f3
git diff --check                → sin salida (0 líneas)
git diff --stat block3-validated → 12 ficheros, +269 / −14 (tracked)
git ls-files --others --exclude-standard → 7 ficheros sin seguimiento (REMEDIATION_F3_NUMERICAL.md, numerical_recovery.py,
                                  feasibility_oracle.py, near_degenerate.py, 3 ficheros de tests)
git stash list                  → vacío
HEAD                            → 4089909 (= block3-validated; ningún commit de la remediación)
```

`git diff --name-status block3-validated`: 12 `M` (ARCHITECTURE.md, CHANGELOG.md, TRACEABILITY.md, config/default_engine.toml, solver_config.py, session.py, enums.py, solution.py, optimizers/__init__.py, formulations/__init__.py, qp_builder.py, test_known_solver_status_cases.py). El estado de `git status` tras mi auditoría es **idéntico** al inicial (verificado); el único fichero añadido es este informe (sin seguimiento, no confirmado en el árbol al momento de esta comprobación). No se ejecutaron `commit`, `merge`, `push`, `tag`, PR, ni `ruff format .`.

---

## 17. Final Decision

Todos los criterios de cierre se cumplen:

| Criterio | Estado |
|---|---|
| 77 puntos contractuales recuperados | ✔ reproducido |
| 212 puntos identificados recuperados | ✔ reproducido |
| Transformación matemáticamente equivalente | ✔ demostrada + verificada (60 normalizaciones, 12 000 vectores) |
| Oráculo LP representa el problema | ✔ mismas filas; caso A/B reproducidos |
| Puntos recuperados cumplen los criterios originales | ✔ validador + comprobación independiente |
| No se aceptan inexactos como óptimos | ✔ (código correcto; evidencia de test débil → AF3-01) |
| Sin regresiones económicas B1/B2/B3 | ✔ 1148 tests + 11 183 fronteras + 72 huellas idénticas |
| Estados y diagnósticos trazables | ✔ `RecoveryTrace` completa |
| Sin hallazgos numéricos bloqueantes abiertos | ✔ 0 |

Puede integrarse en `main` sin deteriorar B1, B2 ni B3. Recomendación: añadir los tests de AF3-01/AF3-02 (bajo coste) y corregir las precisiones de AF3-04 antes o justo después de la integración; ninguno condiciona el cierre.

---

F3_NUMERICAL_AUDIT_SUMMARY

Branch:
fix/b2-numerical-f3 (sobre block3-validated, `4089909`; sin commits nuevos)

Root cause:
Fila de retorno casi paralela a la de presupuesto (retornos casi idénticos en GROSS; costes que anulan la pendiente de μ en NET) → ADMM/OSQP declara `INFEASIBLE` espurio o no converge en puntos que un LP de HiGHS demuestra factibles. Diagnóstico confirmado.

Mathematical equivalence:
Demostrada (`r' = s(r − λe)`, `l' = s(l − λb)`, válido sobre `eᵀx = b`, garantizado por la igualdad de presupuesto del contrato) y verificada numéricamente (60 normalizaciones, error relativo máx. 3,3e-10; mismas filas restantes bit a bit; mismos pesos óptimos ≤ 4,6e-8). GROSS, NET (con `return_offset` y activos retirados) y POST_COST_GROSS cubiertos.

LP oracle:
Mismas filas `A`, `upper` y `lower` original; objetivo nulo; HiGHS. Caso A (factible, OSQP INFEASIBLE) → recupera; caso B (target > máximo, hasta +1e-10) → `INFEASIBLE` confirmado sin reintentos.

Recovered contractual points:
77 de 77 (7 instancias × GROSS/NET; POST_COST_GROSS hereda) → 0 inválidos.

Recovered sweep points:
212 de 212 (17 fronteras, n = 2..5, seeds 0..1399); barrido adicional 1400..2999 (sin baseline): 0 inválidos en 255 982 puntos, 142 recuperados.

False infeasibility:
Sin infactibilidad falsa residual: los `INFEASIBLE` espurios se recuperan o, si nada los recupera, se reclasifican a `NUMERICAL_ERROR`; los verdaderos permanecen `INFEASIBLE` confirmados por el LP.

Optimality evidence:
Solución analítica (n = 2), SLSQP por regiones (n = 3 NET), LP independiente del máximo retorno; puntos recuperados coinciden hasta 1e-9…1e-15; el «1,3e-7» declarado corresponde a un punto no recuperado; extremo de máximo retorno = holgura A-14 heredada e idéntica al baseline.

Regression B1/B2/B3:
Sin regresión: 1148 tests; 11 183 fronteras sanas idénticas (iteraciones, hash de pesos, estados); 66 configuraciones propias (72 series) idénticas al baseline en pesos, métricas, estados, iteraciones y validez, incluida la frontera global.

Tests passed:
1148

Tests failed:
0

Mutants detected:
12 de 14 (supervivientes: M3 aceptar `OPTIMAL_INACCURATE` en el reintento; M7b reclasificación sin veredicto `FEASIBLE`).

Performance:
+2,81 % de iteraciones OSQP en el barrido de 11 200 fronteras; oráculo 4–6 ms; peor punto no recuperable 0,16 s; fronteras sanas sin coste; fronteras NET n = 2 lentas por ADMM (hasta 5,2 M iteraciones, heredado).

Open blocking findings:
0

Open non-blocking findings:
8 (AF3-01 test que no ejercita `OPTIMAL_INACCURATE` [Media]; AF3-02 camino INCONCLUSIVE sin test; AF3-03 oráculo no consultado en estados ambiguos; AF3-04 precisiones documentales; AF3-05 escalera empírica; AF3-06 latencia ADMM heredada; AF3-07 ConfigHash/campos obligatorios; AF3-08 observaciones de alcance).

Git status:
Rama `fix/b2-numerical-f3`; 12 ficheros modificados + 7 sin seguimiento (idéntico al inicio de la auditoría) más este informe; `git diff --check` limpio; sin commit/merge/push/tag/PR.

Closure recommendation:
Integrable en `main`. Añadir antes o inmediatamente después los tests de AF3-01 y AF3-02 y corregir las precisiones de AF3-04; no condicionan el cierre.

AUDIT_F3_NUMERICAL_STATUS = PASS
