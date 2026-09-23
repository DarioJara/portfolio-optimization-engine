# AUDIT_BLOCK_1 — Auditoría independiente del Bloque 1 (Foundation)

**Auditor:** sesión independiente (no autora de la implementación).
**Alcance:** commit baseline `e49c70e` ("Phase 0 - architecture, specification and traceability
baseline") → `HEAD` (`67a1f99`, "Block 1 - validated: foundation (config, data, returns, risk)").
**Método:** lectura completa de `CLAUDE.md`, `MASTER_SPEC.md`, `ARCHITECTURE.md`,
`TRACEABILITY.md`, `CHANGELOG.md`, `IMPLEMENTATION_PLAN.md`, `IMPLEMENTATION_PROMPTS.md`;
lectura directa del código fuente listado más abajo; ejecución real de `pytest`, `mypy --strict`,
`ruff check` y `ruff format --check`; revisión del `git diff e49c70e..HEAD` completo (94 ficheros,
+6940/-88 líneas). No se ha modificado ningún fichero del repositorio salvo la creación de este
informe. No se ha hecho commit.

---

## 1. Resultado formal de los comandos ejecutados

Ejecutados realmente en el entorno `.venv` del proyecto (no simulados ni estimados):

| Comprobación | Resultado real obtenido |
|---|---|
| `pytest -q` (suite completa) | **252 passed, 0 failed, 0 skipped** en 21.31 s |
| `pytest` (subconjunto returns/risk/data/config, re-ejecutado de forma independiente por el auditor) | **145 passed, 0 failed** en ~20.5 s |
| `mypy --strict portfolio_engine` | **0 errores, 53 ficheros** (`Success: no issues found`) |
| `ruff check .` | **0 violaciones** (`All checks passed!`) |
| `ruff format --check .` | **1 de 94 ficheros no formateado: `README.md`** (línea 61, falta una línea en blanco dentro de un bloque de código Python embebido). **93 ficheros correctos**, incluidos todos los de `portfolio_engine/` y `tests/`. |

**Conclusión de esta sección:** las cifras que `CHANGELOG.md` reporta (252 passed; mypy 0 errores
en 53 ficheros; ruff check 0 errores) son **reproducibles y verificadas de forma independiente**,
no inventadas. La única discrepancia es cosmética: el CHANGELOG afirma "85 ficheros ya
formateados" en `ruff format --check portfolio_engine tests` (alcance restringido a esos dos
directorios, donde en efecto no hay ficheros pendientes), mientras que ejecutar `ruff format
--check .` sobre todo el repo detecta `README.md` sin formatear. No es una discrepancia real: son
alcances de comando distintos, y `README.md` no es código fuente del motor. Clasificado como
**LOW** (hallazgo #10).

---

## 2. ¿Está justificado `BLOCK_1_STATUS = PASS`?

**Sí, con matices.** La justificación se apoya en tres pilares, todos verificados de forma
independiente:

1. **Los tests declarados existen y pasan de verdad** (sección 1).
2. **La matriz de trazabilidad cuadra aritméticamente**: `TRACEABILITY.md:49` — Total 316
   requisitos = 245 `NOT_IMPLEMENTED` + 13 `PARTIAL` + 0 `IMPLEMENTED` + 58 `VALIDATED`. Verificado
   fila por fila (GOV: 5+6+1=12 ✓; CFG: 9+2+7=18 ✓; DAT: 23+3+2=28 ✓; RET: 7+0+4=11 ✓; RSK:
   11+0+2=13 ✓; TC: 1+0+12=13 ✓; CAN/FRN/OPT/…: 0 VALIDATED, correcto porque ningún paquete de
   bloques 2–6 existe en el árbol de código, confirmado por `test_no_later_block_packages_exist`).
3. **Ningún requisito de bloques posteriores está marcado como `IMPLEMENTED`/`VALIDATED`**: no se
   detectó "avance silencioso" de alcance. El propio código declara explícitamente, en
   comentarios y docstrings, qué queda para el Bloque 2 (p. ej. `models/costs.py:4`: *"El cálculo
   de `TransactionCost(w)`... pertenece al Bloque 2"*).

**Matices que rebajan la confianza sin invalidar el PASS** (desarrollados en las secciones
siguientes): calidad desigual de las citas de evidencia dentro de los 58 `VALIDATED` (algunas
apuntan solo a un fichero de test, no a una función concreta), un caso de evidencia circular
(TST-018), y una `ARCHITECTURE.md` que no se ha actualizado para reflejar 6 decisiones de diseño
ya tomadas — reconocido por el propio equipo en el CHANGELOG, pero sigue siendo deuda documental
abierta a día de hoy.

**Veredicto de esta sección:** el `PASS` está soportado por evidencia real y verificable, no por
afirmaciones sin respaldo. No se ha encontrado ningún caso de un requisito declarado `VALIDATED`
sin código funcional o sin test que lo ejercite.

---

## 3. Auditoría de los 58 `VALIDATED` y los 13 `PARTIAL`

### 3.1 Los 58 `VALIDATED`

Revisados uno a uno contra `TRACEABILITY.md` y, para una muestra representativa, contra el código
y los tests citados directamente (no solo contra la tabla). Resumen:

- **~41 de 58** citan un test **nombrado explícitamente** (`::test_función`) que efectivamente
  ejercita el requisito de forma verificable de forma independiente. Ejemplos verificados
  directamente por el auditor: `RSK-002` (`test_empirical_matches_numpy_cov` — contraste real
  contra `numpy.cov`), `RSK-003` (`test_ledoit_wolf_matches_reference_implementation` — contraste
  real contra `sklearn.covariance.ledoit_wolf`), `RET-010` (`test_arithmetic_returns_exact_values`
  — valores numéricos exactos, no solo forma/tipo), `DAT-016`/`CON-021` (tests dedicados con casos
  manuales).
- **~16 de 58** (p. ej. `CFG-001`, `CFG-003`, `CFG-004`, `CFG-006`, `CFG-016`, `CFG-017`, `DAT-004`,
  `DAT-005`, `DAT-006`, `DAT-009`, `DAT-010`, `DAT-012`, `DAT-029`, `RET-002`, `RSK-013`, `TC-005`)
  citan **solo el nombre del fichero de test**, sin función concreta. Esto no invalida el
  requisito (el fichero existe, pasa, y en la lectura directa de varios de ellos —
  `test_covariance_estimators.py`, `test_architecture_rules.py` — el contenido es riguroso), pero
  reduce la trazabilidad exacta: un auditor no puede verificar automáticamente, sin abrir el
  fichero, qué aserción concreta respalda cada `RequirementID`.
- **1 caso de evidencia circular**: `TST-018` ("Tests obligatorios del Bloque 1 presentes y en
  verde") cita como evidencia *"Todos presentes y en verde (ver CHANGELOG, gate B1)"* — es decir,
  remite al propio CHANGELOG en lugar de a un artefacto de test verificable de forma
  independiente. Es un defecto de forma, no de fondo (el propio auditor ha verificado que los
  tests obligatorios sí existen y pasan), pero incumple el espíritu de `CLAUDE.md` (§77–79:
  "corrección... test de aceptación... ejecutado y pasado", no "referencia a otro documento").

**Verificación cruzada de calidad real de los tests VALIDATED (no solo cantidad):** se leyó el
código completo de `test_covariance_estimators.py` y `test_architecture_rules.py`. Ambos son
rigurosos: comparan contra referencias independientes (`numpy.cov`, `sklearn.covariance.
ledoit_wolf`), incluyen casos manuales calculados a mano, casos límite (`T < N`, matrices
singulares, `ddof` parametrizado), y las reglas de arquitectura usan análisis AST real (no
heurísticas de texto) para detectar dependencias circulares, estado global mutable, literales
numéricos de negocio y stubs disfrazados. No son tests vacíos ("solo comprueba que no lanza
excepción" o "solo comprueba el tipo de retorno").

### 3.2 Los 13 `PARTIAL`

Los 13 están justificados por una razón de alcance **explícita y correcta**: o bien son
transversales hasta el Bloque 6 (`GOV-002`, `GOV-003`, `GOV-007`, `GOV-009`, `GOV-010`, `GOV-011`,
`CFG-015`, `TST-001`, `TST-003`), o bien cubren solo la parte del requisito que corresponde al
Bloque 1 mientras el resto queda para bloques posteriores (`CFG-005` base vs. extensiones B2–B4;
`DAT-013` índice global vs. eligible/local en B3; `DAT-015` alpha vs. resto de entradas en B4;
`DAT-028` metadatos obligatorios vs. condicionales a restricciones de grupo en B2). **No se ha
detectado ningún caso de `PARTIAL` "disfrazado" de `VALIDATED`**, ni ningún requisito que debería
ser `PARTIAL` y aparece como `VALIDATED`.

Un punto débil: `GOV-007` (Dependency Injection / Protocol donde aporte valor) cita como evidencia
*"Tests inyectan configuraciones y fuentes alternativas"*, sin nombrar ningún test o fichero
concreto — el único caso de evidencia genuinamente vaga entre los 13.

---

## 4. Las 6 desviaciones respecto a `ARCHITECTURE.md`

Documentadas en `CHANGELOG.md:112-132`. Evaluación y clasificación de cada una:

### Desviación 1 — Resolución de costes unitarios fuera de `costs/`
*"Resolución de costes unitarios en `data/validation/transaction_cost_inputs.py` en lugar de
`costs/`. El paquete `costs/` queda para el cálculo de `TransactionCost(w)` y turnover del Bloque
2."*

Verificado en código: `models/costs.py:4` confirma explícitamente el deslinde. Es una separación
razonable entre *validación de inputs* (Bloque 1, sin optimización) y *cálculo funcional*
(Bloque 2, que consumirá el vector de costes ya validado). No introduce riesgo matemático ni
viola ninguna regla de capas.

**Clasificación: ACCEPT_WITH_CHANGES** — aceptar el diseño, pero actualizar `ARCHITECTURE.md` para
reflejar la ubicación real del módulo antes de que el Bloque 2 empiece a construir sobre él (si no,
la próxima sesión de implementación puede intentar recrear el módulo en la ubicación original
descrita en `ARCHITECTURE.md`, duplicando lógica).

### Desviación 2 — Dependencia `risk → returns`
*"Uso de `annualize_covariance`. El grafo de ARCHITECTURE §4.1 solo lista `risk → models,
config`. El grafo sigue siendo acíclico (test)."*

Verificado: `risk/risk_model_builder.py:54` importa y usa `annualize_covariance` de
`returns/annualization.py`. `test_architecture_rules.py::test_layered_dependencies` y
`::test_import_graph_is_acyclic` pasan realmente (confirmado en la ejecución de este auditor) y
la tabla `ALLOWED_DEPENDENCIES` del propio test ya incluye `"risk": {..., "returns"}` — es decir,
el test de gobernanza **ya fue actualizado** para permitir esta dependencia, aunque el documento
`ARCHITECTURE.md` no lo refleje todavía. Es una dependencia técnicamente necesaria (reutilizar la
anualización en vez de duplicarla) y no rompe la regla GOV-008 (sin ciclos).

**Clasificación: ACCEPT_WITH_CHANGES** — aceptar; actualizar el grafo de `ARCHITECTURE.md §4.1`
para que documento y test de gobernanza no diverjan (hoy el test ya es la fuente de verdad real,
pero el documento sigue describiendo una arista distinta).

### Desviación 3 — `CSVSource`/`ParquetSource` fusionados en `file_sources.py`
*"En un único módulo `data/sources/file_sources.py`."*

Es la desviación con **racional más escueto** de las 6 (una sola frase, sin justificación técnica
explícita más allá del hecho en sí). No es un problema de fondo — ambas fuentes comparten
canonicalización y es razonable agruparlas — pero incumple parcialmente el espíritu de
`CLAUDE.md` de documentar y justificar cada desviación, no solo declararla.

**Clasificación: ACCEPT_WITH_CHANGES** — aceptar el diseño (verificado en código: `DataSource`
Protocol se respeta, ambas fuentes producen tablas canónicas idénticas según
`test_all_sources_yield_identical_canonical_tables`), pero pedir que el CHANGELOG amplíe el
racional (p. ej. "comparten >80% de la lógica de canonicalización; separarlas sería duplicación
de código, violando GOV-009") para que la decisión sea auditable sin inferencia.

### Desviación 4 — `NEAREST_PSD` como proyección de Frobenius cerrada (Higham 1988) en vez de NLP
convexo alternante
*"ARCHITECTURE §9.2 (P23) la describía como proyección alterna (NLP convexo): ese algoritmo solo
es necesario para la matriz de correlación más cercana (diagonal unitaria). No es una
simplificación."*

Esta es la desviación **matemáticamente más sensible** de las 6, y la mejor justificada. Verificado
directamente en `psd_repair.py`: `nearest_psd_repair` implementa exactamente `V·max(Λ,0)·Vᵀ`
(Higham 1988), que es la solución **exacta y cerrada** al problema de la matriz PSD más cercana en
norma de Frobenius quitando la restricción de diagonal unitaria (esa restricción solo aplica al
problema de la *correlación* más cercana, no al de la *covarianza* más cercana). El argumento
matemático del CHANGELOG es correcto: el algoritmo alternante de Higham (1988/2002) para matrices
de correlación resuelve un problema *distinto* (con la restricción adicional `diag(X)=1`), y
aplicarlo aquí sería una complicación innecesaria, no una mayor fidelidad. Los tests
(`test_nearest_psd_is_frobenius_projection`, y la propiedad `test_nearest_psd_is_psd_idempotent_
and_closest`) verifican PSD, idempotencia y optimalidad de la proyección de forma independiente.

**Clasificación: ACCEPT** — es una corrección matemática legítima respecto a una descripción
imprecisa de `ARCHITECTURE.md` (que mezclaba dos problemas de proyección distintos), no una
simplificación que sacrifique corrección. Cumple exactamente la regla de `CLAUDE.md` de "no
modificar formulaciones matemáticas... sin documentarlo y justificarlo": aquí se documenta y
justifica con referencia bibliográfica y prueba matemática explícita. Se recomienda igualmente
reflejarlo en `ARCHITECTURE.md §9.2` para que el documento no quede desactualizado (ver hallazgo
#7), pero el contenido de la decisión en sí no requiere cambios.

### Desviación 5 — `PSDDiagnostics`, `PSDRepairReport`, `ExternalAlpha` reubicados en
`models/risk_model.py`
*"Para que `models` no dependa de `risk`."*

Verificado: preserva la regla de capas (`models` es la capa más baja junto con `exceptions`/
`utils`; si estas clases vivieran en `risk/`, `models` tendría que importar de `risk`, invirtiendo
la jerarquía declarada en `ARCHITECTURE §4.1` y verificada por `test_layered_dependencies`). Es una
decisión de ingeniería de software razonable y sin impacto matemático.

**Clasificación: ACCEPT_WITH_CHANGES** — aceptar; reflejar la reubicación en el diagrama de
módulos de `ARCHITECTURE.md`.

### Desviación 6 — `EngineConfig` sin campos de subconfiguraciones futuras
*"Se añadirán en su bloque para no crear placeholders."*

Correcto y coherente con `GOV-010` (sin stubs disfrazados) y con la regla explícita de
`CLAUDE.md`: *"Si durante una fase aparece una mejora perteneciente a un bloque posterior,
documentarla como pendiente y no implementarla salvo instrucción expresa."* Confirmado en
`config/engine_config.py`: no hay campos `frontier_config: FrontierConfig | None = None` ni
similares placeholders.

**Clasificación: ACCEPT** — sin cambios necesarios; es la decisión más alineada con las reglas
explícitas de `CLAUDE.md` de las 6.

### Resumen de las 6 desviaciones

| # | Desviación | Veredicto |
|---|---|---|
| 1 | Costes unitarios fuera de `costs/` | ACCEPT_WITH_CHANGES (actualizar ARCHITECTURE.md) |
| 2 | Dependencia `risk → returns` | ACCEPT_WITH_CHANGES (actualizar grafo §4.1) |
| 3 | `CSVSource`/`ParquetSource` fusionados | ACCEPT_WITH_CHANGES (ampliar racional documentado) |
| 4 | `NEAREST_PSD` cerrado (Higham) vs. NLP alternante | ACCEPT |
| 5 | `PSDDiagnostics`/`PSDRepairReport`/`ExternalAlpha` en `models/` | ACCEPT_WITH_CHANGES (reflejar en diagrama) |
| 6 | `EngineConfig` sin campos futuros | ACCEPT |

Ninguna de las 6 desviaciones sustituye Beam Search por Greedy, Global Frontier por una sola
composición, Net Frontier por Gross-menos-costes, SOCP por QP incompatible, ni MIQP por heurística
— las sustituciones expresamente prohibidas por `CLAUDE.md` no aparecen en este bloque (son
conceptos de bloques 2–4, todavía no implementados).

---

## 5. Corrección matemática — revisión directa de código

Revisado directamente por el auditor (no solo a través de subagentes) para: retornos,
anualización, covarianza empírica, Ledoit-Wolf, PSD diagnostics/repair, y confirmado por segunda
vía independiente (subagente especializado que ejecutó su propia batería de `pytest` sobre estos
módulos: **145 passed**) para el resto.

| Elemento | Fichero | Veredicto | Nota |
|---|---|---|---|
| Retornos aritméticos `r=P[t]/P[t-1]-1` | `returns/returns_engine.py:55` | **PASS** | Fórmula exacta según MASTER_SPEC §9; huecos y precios ≤0 rechazados explícitamente, nunca rellenados |
| Anualización lineal `mu_a=TD·mu`, `Σ_a=TD·Σ` | `returns/annualization.py:20-33` | **PASS** | `TradingDays` viene siempre de `ReturnConfig`, nunca hardcodeado (`grep 252` sin resultados en código de producción) |
| Covarianza empírica `S=Xc'Xc/(T-ddof)` | `risk/covariance/empirical.py` | **PASS** | `ddof` viene de config; contrastado contra `numpy.cov` con `ddof∈{0,1}` |
| Ledoit-Wolf (objetivo identidad escalada) | `risk/covariance/ledoit_wolf.py` | **PASS** | Implementación propia matemáticamente correcta (Ledoit-Wolf 2004); contrastada numéricamente contra `sklearn.covariance.ledoit_wolf` con `rtol=1e-10`, incluido el caso `T<N` (muestral singular) |
| Diagnóstico PSD (autovalores, número de condición, tolerancia relativa) | `risk/psd_diagnostics.py` | **PASS** | `condition_number=∞` si `λ_min≤0` (no confunde inviabilidad con fallo numérico); asimetría excesiva se **rechaza**, no se corrige silenciosamente (más estricto que el mínimo exigido) |
| Reparación PSD: eigenvalue floor / nearest PSD (Higham) | `risk/psd_repair.py` | **PASS** | Ver desviación 4 arriba; fórmulas correctas y verificadas por propiedades (Hypothesis) |
| Modelo de costes de transacción `TC(w)` | — (no existe en el árbol) | **NOT_IMPLEMENTED, correctamente declarado** | Solo existe el vector de costes unitarios resuelto y validado (`models/costs.py`, `TC-005`); `TransactionCost(w)`, turnover y liquidaciones completas quedan para el Bloque 2 — declarado explícitamente en el propio código (`models/costs.py:4`), no simulado ni asumido como implementado en ninguna parte de `TRACEABILITY.md` |
| `OptimizationHorizonYears` | `config/engine_config.py:37,51` | **PASS** | Positivo obligatorio, único origen de verdad, defecto `1.0` solo en `config/default_engine.toml`; correctamente **no consumido todavía** en retornos/costes netos (Bloque 2+), sin inconsistencia |
| `CurrentPortfolioStateHash` | `models/portfolio.py:133-145` | **PASS, con una observación (ver hallazgo #6)** | SHA-256 sobre pares `(AssetID, CurrentWeight)` ordenados, `float.hex` exacto, `-0.0→0.0`; nunca usa `hash()` de Python |
| `RestrictedExistingPositionPolicy` | `models/enums.py:48-53`, `data/validation/portfolio_validator.py` | **PASS para lo implementado; PARTIAL correctamente declarado para lo pendiente** | Enum y exigencia de selección explícita (E-09) implementados y testeados; la traducción de la política a cotas de optimización (`0≤w≤min(w_current,MaxWeight)`, etc.) queda para cuando exista `constraints/` (Bloque 2) |

**No se ha encontrado ninguna fórmula matemática incorrecta, ninguna sustitución silenciosa de
Beam Search/Global Frontier/SOCP/MIQP, ni ningún parámetro financiero/matemático hardcodeado en
código de producción** (verificado tanto por lectura directa como por el test AST
`test_no_business_numeric_literals`, que además se ejecutó realmente y pasó).

---

## 6. Hallazgos clasificados

### CRITICAL
Ninguno.

### HIGH
Ninguno. No se ha encontrado ningún caso de corrección matemática comprometida, requisito
`VALIDATED` sin test real, ni sustitución silenciosa de las prohibidas por `CLAUDE.md`.

### MEDIUM

**#1 — `MASTER_SPEC.md` no contiene fórmulas cerradas para covarianza empírica, shrinkage de
Ledoit-Wolf, ni los métodos de reparación PSD (eigenvalue floor / nearest PSD).**
`MASTER_SPEC.md §11` (líneas 360-410) solo enumera los métodos soportados y pasos cualitativos
("eigenvalue floor; nearest PSD u otro método configurable"), sin especificar la fórmula exacta.
Esto significa que, estrictamente, la verificación de "corrección matemática frente al contrato
autoritativo" (regla explícita de `CLAUDE.md`) para estos tres elementos solo puede hacerse contra
referencias externas (numpy, sklearn, Higham 1988) — que sí se han usado y son apropiadas, pero no
están ancladas textualmente en `MASTER_SPEC.md`. No es un defecto de implementación (el código es
correcto contra la literatura estándar), pero es un vacío del propio contrato que debería cerrarse
antes de que bloques posteriores dependan de interpretaciones no escritas.
*Recomendación:* añadir a `MASTER_SPEC.md §11` las fórmulas cerradas usadas (o al menos citar
explícitamente Ledoit & Wolf 2004 y Higham 1988 como referencia normativa), igual que ya se hace
para el modelo de costes y `OptimizationHorizonYears`.

**#2 — `ARCHITECTURE.md` no se ha actualizado para reflejar las 6 desviaciones y contiene una
afirmación obsoleta.**
`ARCHITECTURE.md:6` sigue diciendo *"Estado del código productivo: inexistente. Ningún requisito
está implementado. Todos los RequirementID están en NOT_IMPLEMENTED"* — literalmente falso tras el
cierre del Bloque 1 (58 `VALIDATED`, 13 `PARTIAL`). El propio CHANGELOG reconoce que las 6
decisiones están "pendientes de reflejar", así que esto es una inconsistencia documental
**declarada, no oculta**, pero sigue siendo deuda activa que puede confundir a quien lea solo
`ARCHITECTURE.md` (ARCHITECTURE.md §3 y §4.1 todavía describen `csv_source.py`/`parquet_source.py`
separados y el grafo de dependencias sin `risk → returns`).
*Recomendación:* actualizar `ARCHITECTURE.md` antes de iniciar el Bloque 2, como exige implícitamente
el propio proceso de la Desviación 1–2–3–5 (todas piden "reflejar en ARCHITECTURE.md").

**#3 — Evidencia circular en `TST-018`.**
La evidencia citada es *"Todos presentes y en verde (ver CHANGELOG, gate B1)"*, remitiendo al
mismo tipo de documento que se supone debe estar respaldado por trazabilidad independiente, en
vez de listar los tests concretos que lo verifican.
*Recomendación:* sustituir por una lista explícita (o un test que enumere y verifique la presencia
de los ficheros de test obligatorios del gate, análogo a `test_no_later_block_packages_exist`).

**#4 — Trazabilidad a nivel de fichero, no de función, en ~16 de los 58 `VALIDATED`.**
(`CFG-001`, `CFG-003`, `CFG-004`, `CFG-006`, `CFG-016`, `CFG-017`, `DAT-004`, `DAT-005`, `DAT-006`,
`DAT-009`, `DAT-010`, `DAT-012`, `DAT-029`, `RET-002`, `RSK-013`, `TC-005`.) No es un defecto de
fondo (los ficheros existen y pasan; varios de ellos fueron leídos directamente por el auditor y
son rigurosos), pero reduce la trazabilidad exacta requerida por `CLAUDE.md` §77–79 para que un
requisito sea auditable sin tener que inspeccionar manualmente cada fichero.
*Recomendación:* en el próximo gate, citar la función de test concreta (o, si un fichero entero
cubre el requisito con múltiples tests, enumerarlos).

### LOW

**#5 — `GOV-007` (DI/Protocol) tiene evidencia vaga.**
*"Tests inyectan configuraciones y fuentes alternativas"*, sin nombrar ningún test. El propio
código sí demuestra DI real (`DataSource` Protocol, constructores con inyección de config), pero
la fila de trazabilidad no lo ancla a un artefacto verificable.

**#6 — Exclusión implícita de pesos cero en `CurrentPortfolioStateHash`.**
`current_portfolio_state_hash` (`models/portfolio.py:144`) filtra pesos exactamente cero antes de
hashear. La Enmienda E-06 en `MASTER_SPEC.md` no especifica textualmente esta exclusión (dice
"a partir de los pares (AssetID, CurrentWeight)", sin mencionar pesos cero). Actualmente es una
red de seguridad sin efecto práctico porque `CurrentPortfolioState.__post_init__` ya rechaza pesos
cero en la construcción — pero si esta función se llama alguna vez con un diccionario externo que
sí contenga ceros (fuera de `CurrentPortfolioState`), el comportamiento de normalización es una
decisión de implementación no anclada textualmente en el contrato.
*Recomendación:* documentar explícitamente en `MASTER_SPEC.md` (o en el docstring, que ya lo hace
parcialmente) que los pesos cero se excluyen por definición del "estado" de cartera.

**#7 — `ruff format --check .` detecta `README.md` sin formatear (no es código fuente).**
Cosmético, sin impacto funcional ni en `portfolio_engine/` ni en `tests/`. Ver sección 1.

**#8 — Posible doble contabilidad de test para `DAT-022`/`DAT-023`/`DAT-024`.**
Los tres citan `test_bad_prices_are_detected_per_asset` como evidencia principal. Es
razonable si el test está parametrizado para cubrir precios ≤0, NaN e inf por separado, pero la
tabla de trazabilidad no lo deja explícito.

**#9 — Racional escueto en la Desviación 3 (fusión de `CSVSource`/`ParquetSource`).**
Ver sección 4.

**#10 — Discrepancia cosmética de alcance en el comando `ruff format --check` reportado en
CHANGELOG vs. reproducido por el auditor.**
Ver sección 1 (mismo hallazgo que #7, clasificado aparte por ser una diferencia de metodología de
reporting, no de resultado).

### INFO

**#11 — Tensión textual entre `IMPLEMENTATION_PROMPTS.md` y el uso real de `PARTIAL`.**
`IMPLEMENTATION_PROMPTS.md` (Bloque 1) describe el "Definition of Done" en términos de
`IMPLEMENTED`/`VALIDATED`, mientras que la práctica real (correcta, y alineada con `CLAUDE.md`)
usó `PARTIAL` para 13 requisitos transversales. No es una violación — `CLAUDE.md` tiene precedencia
declarada como documento de reglas de desarrollo — pero conviene que el prompt de bloque futuro
anticipe explícitamente el uso de `PARTIAL` para no generar la impresión de que el bloque está
"incompleto" cuando en realidad sigue el proceso correctamente.

**#12 — Limitaciones conocidas ya autodocumentadas de forma honesta.**
`CHANGELOG.md` ya declara, sin que el auditor haya tenido que descubrirlo: validación solo en
Python 3.13.6/Windows (no probado en 3.11/3.12 pese a `requires-python>=3.11`); comportamiento
conservador de `EXCLUDE_ASSET` ante calendarios desalineados; y una pérdida de precisión de LAPACK
(`eigvalsh`) en magnitudes de entrada extremas (~1e-160), detectada por Hypothesis y correctamente
excluida del generador de propiedades por no ser representativa de covarianzas reales. Se
considera buena práctica de transparencia, no un hallazgo que requiera acción.

---

## 7. Resumen ejecutivo

- **Tests, mypy y ruff**: verificados de forma real e independiente. Cifras del CHANGELOG
  confirmadas. Único hallazgo: formateo pendiente en `README.md` (no fuente).
- **Trazabilidad (58 VALIDATED + 13 PARTIAL)**: aritméticamente correcta y, en la muestra
  verificada directamente por este auditor, respaldada por tests reales y no vacíos. Debilidades
  de forma (evidencia a nivel de fichero en ~16 casos, un caso de evidencia circular) que no
  cambian el veredicto de fondo pero deberían corregirse.
- **6 desviaciones arquitectónicas**: ninguna sustituye los algoritmos que `CLAUDE.md` prohíbe
  sustituir; todas están matemáticamente justificadas o son decisiones de ingeniería razonables;
  la más significativa (Higham/Frobenius cerrado en vez de NLP alternante) es, de hecho, una
  corrección respecto a una imprecisión de `ARCHITECTURE.md`, no una simplificación. El punto
  débil común a las 6 es que `ARCHITECTURE.md` no se ha actualizado todavía — deuda documental
  reconocida por el propio equipo.
- **Corrección matemática**: sin errores encontrados en retornos, anualización, covarianza
  empírica, Ledoit-Wolf, diagnóstico y reparación PSD. El modelo de costes de transacción y la
  semántica operativa de `RestrictedExistingPositionPolicy` están correctamente declarados como
  pendientes (Bloque 2+), no simulados ni asumidos como completos en ningún documento.
- **Hardcoding y dependencias**: sin parámetros financieros/matemáticos hardcodeados en código de
  producción; separación runtime/dev correcta en `pyproject.toml`.

No se ha encontrado ningún hallazgo `CRITICAL` ni `HIGH`. Los hallazgos `MEDIUM` son de
trazabilidad documental y de completitud del contrato (`MASTER_SPEC.md`), no de corrección del
código ya escrito.

---

AUDIT_STATUS = PASS_WITH_CHANGES
