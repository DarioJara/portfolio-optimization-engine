# REMEDIATION_BLOCK_3_CLOSURE — Remediación final de datos del Bloque 3

**Rama:** `block3-candidate-engine` · **Baseline:** `block2-validated` · **Fecha:** 2026-09-24
**Origen:** `AUDIT_BLOCK_3_CLOSURE.md` (`PASS_WITH_CHANGES`; hallazgos F-1, F-2, F-6 bloqueantes).
**Restricciones cumplidas:** sin avance al Bloque 4; sin commit, merge, push, tag ni PR; `AUDIT_BLOCK_3.md`, `AUDIT_BLOCK_3_CLOSURE.md` y `REMEDIATION_BLOCK_3.md` sin modificar.

---

## F-1 status: CORREGIDO

`ADV` es exclusivamente el importe monetario medio negociado por día. Antes, el valor se usaba tal cual sin comprobar qué representaba.

## F-2 status: CORREGIDO

Con ADV/NAV activo, `ADVCurrency` y `NAVCurrency` son obligatorias. Antes, si faltaban ambas se suponía que coincidían.

## ADV unit contract

* **Representación tipada:** enum `AdvUnit` (`NOTIONAL_PER_DAY`, `SHARES_PER_DAY`, `CONTRACTS_PER_DAY`) en `models/enums.py`; `AssetMetadata.adv_unit` (columna `ADVUnit`) y `AssetMetadata.adv_source` (columna `ADVSource`, procedencia). `AssetMetadata.__post_init__` rechaza una unidad que no sea un `AdvUnit` (no se aceptan cadenas arbitrarias en llamadas directas); el cargador rechaza una `ADVUnit` desconocida con un error de datos (`INVALID_VALUE`).
* **Contrato verificable por activo:** unidad + divisa (`ADVCurrency`) + procedencia (`ADVSource`) + valor (`ADV ≥ 0` finito) + correspondencia por `AssetID` (los metadatos viven en el mismo registro del activo).
* **Reglas** (`constraints/liquidity.py::check_adv_unit`): solo `NOTIONAL_PER_DAY`; `SHARES_PER_DAY`/`CONTRACTS_PER_DAY` ⇒ error específico («no es un importe monetario y no se convierte implícitamente…»); unidad ausente ⇒ error; unidad desconocida ⇒ error. **Sin conversión** desde títulos (requeriría un precio y una política de valoración aprobados; no se inventa ninguna en B3).
* **Comprobación dimensional** (documentada en el módulo): `participación[1] · ADV[divisa/día] · días[día] / NAV[divisa] = adimensional`, es decir, un peso.
* La fórmula no cambia: `Capacity = Participation · ADVNotionalPerDay · LiquidationDays / NAV`.

## Currency and FX contract

* `ADVCurrency` y `NAVCurrency` **obligatorias** con la restricción activa: ambas ausentes ⇒ error; solo una ausente ⇒ error; nunca se supone igualdad por ausencia (`check_currencies`).
* Iguales ⇒ `ADV` directo. Distintas ⇒ tipo de cambio explícito del **par exacto** `(ADVCurrency → NAVCurrency)` en `constraints.liquidity.fx_rates`; orientación: **unidades de `NAVCurrency` por unidad de `ADVCurrency`**, `ADV_en_NAV = ADV · FX` (test sintético: 100 USD × 0,90 = 90 EUR; `1e8 USD × 0,90` con `NAV = 1e8 EUR`, `p = 0,10`, `días = 5` ⇒ capacidad 0,45). Sin inversión ni inferencia de pares (el par inverso se rechaza), `FX > 0` y finito, comparación exacta de etiquetas, trazabilidad en `LiquidityCapRule` (unidad, divisas, procedencia, FX).
* `PortfolioSpec.nav_currency` valida que sea texto no vacío; `NAV > 0` y finito ya se validaban. Ningún tipo de cambio se inventa; los valores explícitos solo existen en tests sintéticos.

## Restricted assets with missing ADV (F-4)

* **Causa:** el bloque de liquidez estaba en la rama de activos no restringidos del compilador, así que un activo restringido (cualquier política E-09) se omitía y su `ADV` faltante no se detectaba.
* **Corrección:** el bloque se aplica a **todo** activo de la composición; los topes de E-09/E-10 ya son `≤ max(w_current, capacidad)`, por lo que la semántica no cambia (`HOLD_OR_REDUCE` `[0; w]`, `FREEZE_WEIGHT` `[w; w]`, `FORCE_LIQUIDATE` `[0; 0]`), pero los datos se validan. El `CandidateEngine` ya validaba activos elegibles y actuales al iniciar (incluye los restringidos). No hay excepción funcional aprobada ni inventada.
* **Excepción documentada:** una posición actual que sale de la composición (venta completa) no necesita capacidad y no exige `ADV` al compilador (no hay restricción que comprobar sobre ella); el `CandidateEngine`, más estricto, valida todas las posiciones actuales al iniciar.
* **Tests:** activo restringido sin `ADV` ⇒ error bajo las 3 políticas; activo nuevo y existente sin `ADV` ⇒ error; `CandidateEngine` lo rechaza al iniciar.
* **Diagnósticos distintos:** error de datos (`ConstraintCompilationError` de datos), restricción infactible (`check_liquidity`, `pre_check_feasible = False`) y falta de convergencia del solver (estados de B2) siguen siendo categorías separadas.

## Aplicación transversal

Una única implementación (`liquidity_capacity`) consumida por: modelos (`AssetMetadata`, `PortfolioSpec`, validación de tipos), configuración (`LiquidityConfig`/`FxRate` con validación en el constructor: las llamadas programáticas no pasan por el TOML), cargador de universo, compilador de restricciones, `CandidateEngine` (validación al iniciar, screening, cardinalidad), factibilidad previa (`check_liquidity`), frontera continua y frontera global (vía restricciones compiladas) y `SolutionValidator`. **Independencia del validador:** además del tope (`w ≤ max(w_current, capacidad)`, calculado desde la capacidad y el peso actual de la regla, no desde `compiled.upper`), comprueba de nuevo el contrato de datos de la regla (unidad `NOTIONAL_PER_DAY`, divisas, FX > 0 si difieren, capacidad finita ≥ 0); una regla manipulada con unidad `SHARES_PER_DAY` produce `LIQUIDITY_CAP:A000:data_contract`. Pruebas de llamada directa (sin loader) a `ContinuousFrontierEngine`, `CandidateEngine` y `GlobalCandidateFrontierEngine` con unidad en títulos y con divisas ausentes: los tres rechazan.

## E-09/E-10/E-11 regression

Precedencia intacta: `HOLD_OR_REDUCE`/`FREEZE_WEIGHT`/`FORCE_LIQUIDATE` (con la liquidez activa y ahora también con datos completos), E-10 (adversarial `w = 0,10`, capacidad `0,20`, `EligibleFlag = False` ⇒ máximo `0,10`) y E-11 (posición existente protegida, sin venta forzosa). Los 10 ficheros específicos de E-09/E-10/E-11 suman **230 passed**. No se debilitó E-09 ni E-10; los tests de liquidez previos se adaptaron al nuevo contrato (fixture con contrato de datos completo; dos tests cuyo comportamiento antiguo —ambas divisas ausentes admitidas, restringido sin validar— es precisamente lo corregido).

## F-4 / F-5 / F-7 / F-8

| ID | Causa | Impacto | ¿Corrección para el cierre? | Estado |
|---|---|---|---|---|
| **F-4** (LOW) | Bloque ADV/NAV en la rama no restringida del compilador | Dato `ADV` faltante de un restringido sin detectar | Sí (contradecía «datos faltantes ⇒ error») | **Corregido** (arriba) |
| **F-5** (LOW) | El `ConstraintSet` incorpora la política de banderas desconocidas y la configuración ADV/NAV, y las cotas compiladas incorporan E-10/E-11 | `ConstraintHash` distinto del de `block2-validated` para el mismo problema | No: el cambio es correcto; **se documenta** | **Documentado** (`ARCHITECTURE.md` §3.4 fila 16): el hash identifica el problema matemático resuelto; si la semántica cambió (nuevas restricciones o datos relevantes) no debe coincidir con el histórico, y forzar la igualdad haría que dos problemas distintos compartieran identidad. Resultados económicos verificados idénticos bit a bit en la auditoría. Las claves de caché del B5 parten de esta versión |
| **F-7** (INFO) | E-10 fija el límite inferior en 0, por encima de `MinWeight` y `min_holding_weight` (A-08), como `HOLD_OR_REDUCE` | Un activo no comprable puede quedar en peso 0 dentro de una composición con tenencia mínima estricta | No: decisión aprobada (E-10) | **Limitación residual documentada** (enmienda E-10 y `ARCHITECTURE.md` fila 17) |
| **F-8** (INFO) | f-strings con `np.float64` en `BOUNDS_CROSSED` | Mensaje cosmético | No | **Corregido** (`float(...)`; una línea) |

## CON-012 status

`VALIDATED` (considerado `PARTIAL` durante la corrección; devuelto tras corregir F-1/F-2/F-4 y pasar sus tests). No incluye —ni afirma— un límite de volumen negociable por operación ni la ejecutabilidad de una venta.

## FEA-006 status

`VALIDATED` (ídem). `check_liquidity` detecta `LIQUIDITY_CAP_BELOW_MIN_WEIGHT` y `LIQUIDITY_CAPS_BELOW_BUDGET` antes del solver; los errores de datos son un diagnóstico distinto.

## Requirement totals

316 `RequirementID`, sin nuevos identificadores: **183 `VALIDATED`, 39 `PARTIAL`, 0 `IMPLEMENTED`, 94 `NOT_IMPLEMENTED`** (recontado por script sobre `TRACEABILITY.md`). Sin avance de B4–B6.

## Tests executed / passed / failed

| Comando | Resultado exacto |
|---|---|
| `pytest -q -p no:cacheprovider` | **1039 passed in 179,81 s** (0 failed, 0 skipped) = 1003 + 36 nuevos |
| 51 ficheros de test del baseline `block2-validated` (`git ls-tree`) | **560 passed** = 558 históricos + 2 tests de arquitectura añadidos en B3 |
| Ficheros específicos E-09/E-10/E-11 (10) | **230 passed** |
| `mypy --strict portfolio_engine` | `Success: no issues found in 124 source files` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `251 files already formatted` |

**Tests passed:** 1039. **Tests failed:** 0 en esta ejecución (el test de propiedades de B2 puede fallar de forma esporádica; ver F-3). Nuevos: `tests/unit/constraints/test_adv_data_contract.py` (36 tests: ADV monetario correcto; títulos y contratos; unidad ausente y desconocida —cargador y construcción directa—; ADV negativo/`NaN`/`inf`; divisas iguales; distintas con FX explícito y valor a mano; FX en orientación incorrecta; FX ausente; ambas divisas ausentes; una sola ausente; `ADVSource` ausente; restringido, nuevo y existente sin ADV; E-09/E-10/E-11; llamadas directas a frontera continua, `CandidateEngine` y frontera global; validador; 2 detectores de mutantes). Los valores esperados se calculan a mano (0,10 ; 0,45 ; 90 EUR).

## Mutant tests

Sobre una copia del árbol, restaurada tras cada uno; **10/10 detectados**: omitir la validación de unidad, aceptar títulos, aceptar unidad ausente, **suponer igualdad cuando faltan ambas divisas**, aceptar una sola divisa ausente, FX invertido, aceptar el par inverso, saltarse la validación para restringidos (F-4), apagar la comprobación de contrato del validador, no exigir `ADVSource`. Además, la suite incluye dos tests que **ejecutan** los mutantes (sustituyen `check_adv_unit` y `check_currencies` por versiones permisivas) y comprueban que las aserciones del contrato fallan: los dos mutantes pedidos (omitir la validación de unidad; suponer igualdad con ambas divisas ausentes) quedan detectados dentro de `pytest`.

## Inherited numerical issue F-3

**Remediación numérica independiente pendiente antes del Bloque 4.** Pertenece al motor validado del Bloque 2 y no se ha mezclado con esta remediación: se conservan los casos deterministas (`tests/unit/frontiers/test_known_solver_status_cases.py`, `test_known_inaccurate_point.py`), no se relajaron tolerancias ni se alteraron estados del solver, y `tests/property/test_invariants.py` puede seguir fallando de forma esporádica. No se declara resuelto.

## Files changed

* **Código:** `models/enums.py` (`AdvUnit`), `models/asset.py`, `models/portfolio.py` (validación de `nav_currency`), `data/sources/base.py`, `data/validation/universe_validator.py`, `constraints/liquidity.py`, `constraints/compiler.py`, `constraints/feasibility.py` (mensaje), `validation/solution_validator.py`, `config/constraint_config.py` (documentación de la orientación).
* **Tests:** nuevo `tests/unit/constraints/test_adv_data_contract.py`; adaptados `tests/fixtures/liquidity.py`, `tests/unit/constraints/test_liquidity_capacity.py`, `tests/integration/test_liquidity_pipelines.py` (contrato de datos completo).
* **Documentación (localizada):** `MASTER_SPEC.md` (E-11), `ARCHITECTURE.md` (A-11, filas 12, 16 y 17), `TRACEABILITY.md`, `CHANGELOG.md`, `README.md` y este informe.

## Git status

Todo sin commit: 37 ficheros modificados y 43 entradas sin seguimiento (incluido este informe y `AUDIT_BLOCK_3_CLOSURE.md`). `AUDIT_BLOCK_3.md`, `AUDIT_BLOCK_3_CLOSURE.md`, `REMEDIATION_BLOCK_3.md`, `IMPLEMENTATION_PLAN.md` e `IMPLEMENTATION_PROMPTS.md` sin cambios en esta tanda.

---

BLOCK_3_FINAL_REMEDIATION_STATUS = PASS
