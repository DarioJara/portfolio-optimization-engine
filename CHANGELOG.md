# CHANGELOG

Formato: una entrada por bloque de implementación. Solo se registran resultados de ejecuciones
reales (CLAUDE.md, MASTER_SPEC §71, §80).

---

## [Bloque 1 — Foundation] — 2026-09-23

### Alcance

Configuración centralizada e inmutable, modelos de datos, validación de inputs, motor de
retornos, interfaz de expected returns, covarianza (Empirical y Ledoit-Wolf), diagnóstico y
reparación PSD, modelo de datos de costes de transacción, estado actual de cartera,
`OptimizationHorizonYears` (E-03) y `RestrictedExistingPositionPolicy` como configuración (E-09).

No se ha implementado nada de los bloques 2–6: no hay optimización, fronteras, CandidateEngine,
escenarios, solvers, paralelismo, caché ni persistencia (verificado por
`tests/unit/test_architecture_rules.py`). OAS y EWMA siguen diferidos (E-07) y no son
seleccionables.

### Baseline de no regresión (MASTER_SPEC §80)

- Commit de partida: `e49c70e` ("Phase 0 - architecture, specification and traceability baseline").
- Tests existentes antes del bloque: **0** (no había código). No hay resultados previos que comparar.

### Entorno

- `pyproject.toml`: runtime (`numpy`, `scipy`, `pandas`, `pyarrow`) separado del grupo `dev`
  (`pytest`, `hypothesis`, `mypy`, `ruff`, `scikit-learn` solo como referencia en tests).
- Entorno local `.venv` (Python 3.13.6). Nada instalado globalmente.
- `requirements-lock.txt`: versiones exactas del entorno validado (numpy 2.5.3, scipy 1.18.1,
  pandas 3.0.6, pyarrow 25.0.1, hypothesis 6.168.1, pytest 9.1.1, mypy 2.3.1, ruff 0.16.8,
  scikit-learn 1.9.1).
- `.gitignore`: artefactos de Python, `.venv/`, `1.-Version Anterior/` e `Instrucciones.txt`
  (no se versionan; no se han borrado del disco).
- No se ha consultado ni reutilizado código de `1.-Version Anterior/`.

### Añadido

- `portfolio_engine/exceptions.py`: jerarquía de excepciones del motor.
- `portfolio_engine/utils/`: hashing canónico (`canonical_json`, `canonical_float`,
  `hash_float_array`), logging estructurado JSON, arrays de solo lectura.
- `portfolio_engine/models/`: enums del Bloque 1, `AssetMetadata`/`Universe`, `AssetIndex`
  (nivel global), `PriceHistory`/`ReturnsMatrix`, `PortfolioSpec`/`WeightBounds`/
  `CurrentPortfolioState` (con `CurrentPortfolioStateHash`, E-06), `ExpectedReturns`/
  `ExternalAlpha`/`CovarianceEstimate`/`PSDDiagnostics`/`PSDRepairReport`/`RiskModel`
  (con `MuSigmaVersion`), `AssetCostVector`.
- `portfolio_engine/config/`: `EngineConfig` (con `optimization_horizon_years`), `DataConfig`,
  `ReturnConfig`, `RiskConfig`, `ConstraintConfig`, `TransactionCostConfig`; loader TOML estricto
  (claves desconocidas o ausentes = error, sin defaults implícitos); `ConfigSnapshot`/`ConfigHash`.
- `config/default_engine.toml`: única ubicación de valores de ejemplo (horizonte 1.0,
  `HOLD_OR_REDUCE`, etc.).
- `portfolio_engine/data/sources/`: `DataSource` (Protocol), `DataFrameSource`, `CSVSource`,
  `ParquetSource` y canonicalización estricta de tipos.
- `portfolio_engine/data/validation/`: `UniverseValidator`, `MarketDataValidator`,
  `PortfolioValidator`, `build_external_alpha`, `resolve_asset_costs`, `DataQualityReport` con
  `CorrectionLog`.
- `portfolio_engine/returns/`: `ReturnsEngine` (aritméticos; log solo con justificación),
  anualización lineal, `ExpectedReturnProvider`, `HistoricalMeanProvider`,
  `ExternalAlphaProvider`, factoría por configuración.
- `portfolio_engine/risk/`: `EmpiricalCovarianceEstimator`, `LedoitWolfCovarianceEstimator`
  (fórmula propia; sklearn solo como referencia en tests), diagnóstico PSD, reparación
  `EIGENVALUE_FLOOR` y `NEAREST_PSD`, `CovarianceBuilder`, `build_risk_model`.
- `README.md` con instalación y ejecución de tests; `CHANGELOG.md`.
- Tests: `tests/unit/` (config, data, costs, returns, risk, arquitectura, infraestructura) y
  `tests/property/` (Hypothesis).

### Modificado

- `ARCHITECTURE.md` e `IMPLEMENTATION_PLAN.md`: referencias obsoletas a "repositorio sin
  commits" sustituidas por el baseline `e49c70e`.
- `TRACEABILITY.md`: estados del Bloque 1 con evidencia real (ver abajo).

### Defecto encontrado y corregido durante el bloque

- `CSVSource`: `pandas.to_numeric` sobre texto no redondea correctamente y alteraba el último
  bit de los precios (diferencia ~1e-14 frente al original). Ahora los números que llegan como
  texto se parsean con `float()` (redondeo correcto). Lo detectó
  `tests/unit/data/test_sources.py`, endurecido a comparación exacta.

### Tests ejecutados (gate del Bloque 1)

| Comprobación | Resultado |
|---|---|
| `pytest` (suite completa) | **252 passed, 0 failed, 0 skipped** (ejecución final tras la corrección del generador) |
| — de ellos, `-m property` (Hypothesis, 60 ejemplos por propiedad) | 8 passed |
| — de ellos, `-m architecture` | 8 passed |
| `mypy` (strict, `portfolio_engine/`) | 0 errores (53 ficheros) |
| `ruff check portfolio_engine tests` | 0 errores |
| `ruff format --check portfolio_engine tests` | 85 ficheros ya formateados |
| Control de mutaciones (script temporal, no versionado) | 19/19 mutaciones matemáticas o de validación hacen fallar la suite |

Tests obligatorios del Bloque 1 presentes y en verde: retornos aritméticos, anualización,
`OptimizationHorizonYears`, NaN, infinitos, duplicados, precios no positivos, histórico
insuficiente, metadatos, pesos actuales, Empirical, Ledoit-Wolf, simetría, autovalores,
número de condición, PSD, matriz casi singular, matriz singular, reparación PSD, inmutabilidad
de configuración, validación de inputs de costes, `RestrictedExistingPositionPolicy` y
propiedades con Hypothesis.

### Trazabilidad

- `VALIDATED` (58): GOV-001, GOV-004, GOV-005, GOV-006, GOV-008, CFG-001 … CFG-004, CFG-006,
  CFG-014, CFG-016, CFG-017, CFG-018, DAT-001 … DAT-006, DAT-009 … DAT-012, DAT-014, DAT-016,
  DAT-020 … DAT-027, DAT-029 … DAT-031, RET-001, RET-002, RET-003, RET-008, RET-010,
  RET-011, RET-012, RSK-001 … RSK-003, RSK-006 … RSK-013, CON-021, TC-005, TST-018.
- `PARTIAL` (13): GOV-002, GOV-003, GOV-007, GOV-009, GOV-010, GOV-011, CFG-015, TST-001,
  TST-003 (transversales hasta el Bloque 6); CFG-005 (base; extensiones B2–B4); DAT-013 (índice
  global; eligible/local en B3); DAT-015 (alpha; resto de entradas opcionales en B4); DAT-028
  (metadatos condicionales a restricciones de grupo en B2).

### Decisiones de implementación que afectan a `ARCHITECTURE.md` (pendientes de reflejar)

`ARCHITECTURE.md` no se ha modificado porque estas decisiones no estaban aprobadas previamente.
Se someten a revisión:

1. **Resolución de costes unitarios** en `data/validation/transaction_cost_inputs.py` (validación
   de inputs) en lugar de `costs/`. El paquete `costs/` queda para el cálculo de
   `TransactionCost(w)` y turnover del Bloque 2.
2. **Dependencia `risk → returns`** (uso de `annualize_covariance`). El grafo de ARCHITECTURE
   §4.1 solo lista `risk → models, config`. El grafo sigue siendo acíclico (test).
3. **`CSVSource` y `ParquetSource` en un único módulo** `data/sources/file_sources.py`.
4. **`NEAREST_PSD` como proyección de Frobenius en forma cerrada** (Higham, 1988:
   `V·max(Λ,0)·Vᵀ`), que es la solución exacta del problema de la matriz PSD más cercana para una
   covarianza. ARCHITECTURE §9.2 (P23) la describía como proyección alterna (NLP convexo): ese
   algoritmo solo es necesario para la matriz de correlación más cercana (diagonal unitaria).
   No es una simplificación. Probado: es PSD, idempotente y no está más lejos que otras
   matrices PSD.
5. **`PSDDiagnostics`, `PSDRepairReport` y `ExternalAlpha` en `models/risk_model.py`**, para
   que `models` no dependa de `risk`.
6. **`EngineConfig` sin campos para subconfiguraciones de bloques posteriores**. Se añadirán en
   su bloque para no crear placeholders.

### Limitaciones conocidas

- Validado solo con Python 3.13.6 en Windows 11. `requires-python >= 3.11` no se ha probado en
  3.11 ni 3.12. mypy no fija `python_version` porque los stubs de numpy 2.5 usan sintaxis ≥ 3.12.
- Alineación de calendario: el calendario de referencia es la unión de fechas. Con
  `EXCLUDE_ASSET`, un activo con fechas espurias haría marcar a los demás como
  `MISSING_OBSERVATION`. El comportamiento es conservador (falla o excluye; nunca rellena).
- Outliers, precios stale y huecos de calendario solo se detectan y registran; nunca se corrigen
  (por diseño, §10).
- `DAT-028`: los metadatos obligatorios condicionales a restricciones de grupo se exigirán en el
  Bloque 2, cuando existan esas restricciones.
- `DataQualityReport` conserva los errores de los activos excluidos. Un llamador que use
  `EXCLUDE_ASSET` debe consultar `report.corrections` y no `raise_if_errors()` sobre el
  resultado.
- Precisión de LAPACK con entradas cercanas al underflow: con matrices cuyas entradas son del
  orden de 1e-160, `np.linalg.eigvalsh` devuelve autovalores con error relativo ~2e-4, mientras
  que `np.linalg.eigh` (la ruta que usa el motor para diagnóstico y reparación) es exacta.
  Hypothesis lo detectó en el oráculo de un test de propiedades; el generador se restringe a
  magnitudes realistas (|x| ≥ 1e-6 o 0). No afecta a covarianzas reales, pero conviene tenerlo
  presente si se introducen otras rutinas espectrales.
- Fuentes SQL Server y API: Bloque 6.

### Estado

`BLOCK_1_STATUS = PASS`
