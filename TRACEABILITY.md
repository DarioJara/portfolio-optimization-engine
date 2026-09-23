# TRACEABILITY

# Matriz de trazabilidad de requisitos — MASTER_SPEC.md

> **Fase:** PROMPT 0. **Ningún requisito está implementado.** Todos los estados son `NOT_IMPLEMENTED`.
> Los módulos y clases/funciones indicados son **previstos** (diseño en `ARCHITECTURE.md`); no existen en el repositorio.
>
> **Estados permitidos** (§77): `NOT_IMPLEMENTED` · `PARTIAL` · `IMPLEMENTED` · `VALIDATED`.
> Reglas (§78, CLAUDE.md): configuración, interfaz, stub o documentación **no** bastan para `IMPLEMENTED`. `VALIDATED` exige que el test de aceptación se haya ejecutado y pasado. Toda sustitución por aproximación se declara `PARTIAL` con la etiqueta `PARTIAL_IMPLEMENTATION` y su motivo (§79).
>
> **Tipo matemático:** `QP` · `SOCP` · `SDP` · `MIQP` · `MIQCP` · `MISOCP` · `NLP Convexo` · `NLP No Convexo` · `Heurístico` · y para requisitos no-optimización: `N/A-Datos`, `N/A-Infra`, `Álgebra lineal`, `Estadístico`, `Cerrado` (fórmula analítica).
>
> **Decisiones:** la columna *Dependencias* cita las ambigüedades `A-xx` de `ARCHITECTURE.md` §12 que afectan al requisito. Todas las decisiones A-01 … A-37 fueron **aceptadas por el usuario** en el cierre de PROMPT 0 (2026-09-23); las que modifican el contrato están incorporadas en `MASTER_SPEC.md` (Anexo A: F-01 … F-04, E-03, E-06, E-07, E-09, E-24, E-25).
>
> Ruta de módulo relativa a `portfolio_engine/` salvo indicación.

---

## Resumen

| Dominio | Prefijo | Secciones MASTER_SPEC | Nº requisitos | NOT_IMPLEMENTED | PARTIAL | IMPLEMENTED | VALIDATED |
|---|---|---|---|---|---|---|---|
| Gobierno y calidad | GOV | §0–3, §77–80 | 12 | 12 | 0 | 0 | 0 |
| Configuración | CFG | §4 | 18 | 18 | 0 | 0 | 0 |
| Datos, universo, carteras, validación | DAT | §5–7, §10 | 28 | 28 | 0 | 0 | 0 |
| Retornos y expected returns | RET | §8–9 | 11 | 11 | 0 | 0 | 0 |
| Riesgo / covarianza / PSD | RSK | §11 | 13 | 13 | 0 | 0 | 0 |
| Restricciones | CON | §12 | 22 | 22 | 0 | 0 | 0 |
| Factibilidad previa | FEA | §13 | 8 | 8 | 0 | 0 | 0 |
| Problemas de optimización | OPT | §14–22 | 14 | 14 | 0 | 0 | 0 |
| Costes, turnover, gross/net | TC | §23–25 | 13 | 13 | 0 | 0 | 0 |
| Candidate engine | CAN | §26–31 | 22 | 22 | 0 | 0 | 0 |
| Fronteras | FRN | §32–43 | 23 | 23 | 0 | 0 | 0 |
| Validación de soluciones | VAL | §44 | 10 | 10 | 0 | 0 | 0 |
| Solvers, estados, routing | SOL | §45–48 | 14 | 14 | 0 | 0 | 0 |
| Exact MIP | MIP | §49 | 7 | 7 | 0 | 0 | 0 |
| Non-convex research | NCV | §50–51 | 5 | 5 | 0 | 0 | 0 |
| Robust optimization | ROB | §52 | 6 | 6 | 0 | 0 | 0 |
| Escenarios | SCN | §53–54 | 10 | 10 | 0 | 0 | 0 |
| Métricas | MET | §55 | 6 | 6 | 0 | 0 | 0 |
| Paralelización / memoria / determinismo | PAR | §56–61 | 13 | 13 | 0 | 0 | 0 |
| Caché | CCH | §31, §62 | 5 | 5 | 0 | 0 | 0 |
| Outputs | OUT | §63–67 | 9 | 9 | 0 | 0 | 0 |
| Persistencia | PER | §68–69 | 10 | 10 | 0 | 0 | 0 |
| Reproducibilidad | REP | §70 | 4 | 4 | 0 | 0 | 0 |
| Benchmark | BEN | §71 | 8 | 8 | 0 | 0 | 0 |
| Tests e invariantes | TST | §72–76 | 22 | 22 | 0 | 0 | 0 |
| Visualización / principio final | VIS | §1, §82 | 3 | 3 | 0 | 0 | 0 |
| **Total** | | | **316** | **316** | **0** | **0** | **0** |

---

## GOV — Gobierno, principios y calidad (§0–3, §77–80)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| GOV-001 | §1 | Implementación en Python 3.11+ | `pyproject.toml` | `requires-python >= 3.11` | N/A-Infra | — | `tests/unit/test_environment.py::test_python_version` | 1 | NOT_IMPLEMENTED |
| GOV-002 | §2, §74-cierre | Prioridad: corrección matemática > integridad > robustez > … > memoria; nunca sacrificar corrección por latencia | transversal | política de revisión + tests numéricos de referencia | N/A-Infra | TST-004 | Toda optimización de rendimiento tiene test de equivalencia numérica contra referencia (`tests/numerical_regression/`) | 1–6 | NOT_IMPLEMENTED |
| GOV-003 | §3 | Código modular, tipado (type hints completos), dataclasses | todo el paquete | `mypy --strict` sobre `portfolio_engine/` | N/A-Infra | — | Ejecución `mypy` sin errores en gate de cada bloque | 1–6 | NOT_IMPLEMENTED |
| GOV-004 | §3 | Custom exceptions | `exceptions.py` | `PortfolioEngineError` y subclases (`DataValidationError`, `ConfigError`, `InfeasibleProblemError`, `SolverError`, `RoutingError`, …) | N/A-Infra | — | `tests/unit/test_exceptions.py` (jerarquía y uso en rutas de error) | 1 | NOT_IMPLEMENTED |
| GOV-005 | §3 | Logging estructurado | `utils/logging.py` | `get_logger`, formateador JSON con contexto (`BatchRunID`, `PortfolioID`, …) | N/A-Infra | — | `tests/unit/test_logging.py` (registro JSON parseable con campos obligatorios) | 1 | NOT_IMPLEMENTED |
| GOV-006 | §3 | Sin estado global mutable | todo el paquete | análisis de módulos | N/A-Infra | — | `tests/unit/test_architecture_rules.py::test_no_module_level_mutable_state` | 1 | NOT_IMPLEMENTED |
| GOV-007 | §3 | Dependency injection y Protocol/ABC donde aporte valor | todo el paquete | constructores con dependencias explícitas | N/A-Infra | — | Revisión + tests que inyectan dobles de prueba (fakes) de `DataSource`, `OptimizationBackend` | 1–6 | NOT_IMPLEMENTED |
| GOV-008 | §3 | Sin dependencias circulares | todo el paquete | grafo `ARCHITECTURE.md` §4.1 | N/A-Infra | — | `tests/unit/test_architecture_rules.py::test_import_graph_acyclic_and_layered` | 1 | NOT_IMPLEMENTED |
| GOV-009 | §3 | Sin funciones excesivamente largas ni duplicación | todo el paquete | lint (`ruff` con límites de complejidad de config) | N/A-Infra | — | `ruff check` sin errores en gate | 1–6 | NOT_IMPLEMENTED |
| GOV-010 | §0, §78, §79 | Ningún stub disfrazado; sustituciones declaradas `PARTIAL_IMPLEMENTATION` | `TRACEABILITY.md` | auditoría por gate | N/A-Infra | — | Auditoría de gate: cada fila `IMPLEMENTED`/`VALIDATED` enlaza un test existente y ejecutado | 1–6 | NOT_IMPLEMENTED |
| GOV-011 | §80 | No regresión: baseline antes, suite completa después, comparar | proceso | `pytest` completo + registro baseline en CHANGELOG | N/A-Infra | — | Gate de cada bloque registra resultados antes/después | 1–6 | NOT_IMPLEMENTED |
| GOV-012 | §1 | Escala objetivo: ~1.200 carteras, ~20 activos, ~700 universo, múltiples escenarios/composiciones/soluciones | `engine.py`, `parallel/` | `PortfolioEngine.run` | N/A-Infra | PAR-*, BEN-007 | `benchmarks/scripts/scale_run.py` con 1.200 carteras sintéticas (si recursos lo permiten; ver BEN-007) | 5 | NOT_IMPLEMENTED |

## CFG — Configuración (§4)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| CFG-001 | §4 | `EngineConfig` raíz inmutable que agrega subconfiguraciones | `config/engine_config.py` | `EngineConfig` | N/A-Infra | — | `tests/unit/config/test_engine_config.py` | 1 | NOT_IMPLEMENTED |
| CFG-002 | §4 | `DataConfig` (tolerancias de validación, mínimos de histórico, umbral stale, outliers, políticas de corrección) | `config/data_config.py` | `DataConfig` | N/A-Infra | A-34 | `test_data_config.py` | 1 | NOT_IMPLEMENTED |
| CFG-003 | §4 | `ReturnConfig` (tipo de retorno, TradingDays, justificación log, rf, modo expected return) | `config/return_config.py` | `ReturnConfig` | N/A-Infra | — | `test_return_config.py` | 1 | NOT_IMPLEMENTED |
| CFG-004 | §4 | `RiskConfig` (método de covarianza, tolerancia PSD, método de reparación, floor) | `config/risk_config.py` | `RiskConfig` | N/A-Infra | — | `test_risk_config.py` | 1 | NOT_IMPLEMENTED |
| CFG-005 | §4 | `ConstraintConfig` (LongOnly, límites globales, grupos, turnover, `restricted_existing_position_policy` (E-09), caja) | `config/constraint_config.py` | `ConstraintConfig` | N/A-Infra | A-09, A-12, A-30 | `test_constraint_config.py` | 1 (base), 2–4 (extensiones) | NOT_IMPLEMENTED |
| CFG-006 | §4 | `TransactionCostConfig` (unidad de entrada, precedencia de fuentes). El horizonte NO reside aquí: se toma de `OptimizationHorizonYears` (CFG-018) | `config/transaction_cost_config.py` | `TransactionCostConfig` | N/A-Infra | A-04, CFG-018 | `test_transaction_cost_config.py` | 1 | NOT_IMPLEMENTED |
| CFG-007 | §4, §41–43 | `FrontierConfig` (puntos, iniciales, adaptativo, grids θ/target, dedup, Pareto) | `config/frontier_config.py` | `FrontierConfig` | N/A-Infra | A-16, A-17, A-29 | `test_frontier_config.py` | 2 | NOT_IMPLEMENTED |
| CFG-008 | §4, §46–48 | `SolverConfig` (tolerancias, iteraciones, time limit, warm start, fallback/cross-check) | `config/solver_config.py` | `SolverConfig` | N/A-Infra | A-32, A-33 | `test_solver_config.py` | 2 | NOT_IMPLEMENTED |
| CFG-009 | §4, §26–30 | `CandidateConfig` (BeamWidth, swaps, 3-swap on/off, pesos de señales, exploración, tabu, shortlist) | `config/candidate_config.py` | `CandidateConfig` | N/A-Infra | A-18 | `test_candidate_config.py` | 3 | NOT_IMPLEMENTED |
| CFG-010 | §4, §53–54 | `ScenarioConfig` (definiciones, probabilidades, modo multi-escenario) | `config/scenario_config.py` | `ScenarioConfig` | N/A-Infra | A-22 | `test_scenario_config.py` | 4 | NOT_IMPLEMENTED |
| CFG-011 | §4, §56–60 | `ParallelConfig` (workers, PortfolioBatchSize/AUTO, shared-memory mode, hilos BLAS) | `config/parallel_config.py` | `ParallelConfig` | N/A-Infra | — | `test_parallel_config.py` | 5 | NOT_IMPLEMENTED |
| CFG-012 | §4, §71 | `BenchmarkConfig` (rendimiento; distinto de benchmark financiero) | `config/benchmark_config.py` | `BenchmarkConfig` | N/A-Infra | A-10 | `test_benchmark_config.py` | 2 (micro), 5 | NOT_IMPLEMENTED |
| CFG-013 | §4, §68–69 | `PersistenceConfig` (staging, destino, método de carga) | `config/persistence_config.py` | `PersistenceConfig` | N/A-Infra | — | `test_persistence_config.py` | 6 | NOT_IMPLEMENTED |
| CFG-014 | §3, §4 | Configuración inmutable (profunda) | `config/*` | `@dataclass(frozen=True)`, colecciones inmutables | N/A-Infra | — | **Bloque 1 obligatorio**: `tests/unit/config/test_config_immutability.py` (asignación y mutación de colecciones internas fallan) | 1 | NOT_IMPLEMENTED |
| CFG-015 | §4 | Sin parámetros financieros/matemáticos/operativos hardcodeados en código de negocio | todo el paquete | defaults solo en `config/default_engine.toml` / módulo de defaults | N/A-Infra | A-29 | `tests/unit/test_architecture_rules.py::test_no_business_literals` (escaneo AST de literales numéricos fuera de allowlist) | 1–6 | NOT_IMPLEMENTED |
| CFG-016 | Bloque 1 | Única fuente de verdad por propiedad; sin configuración duplicada; validación de coherencia cruzada | `config/loader.py` | `load_engine_config`, `validate_config` | N/A-Infra | — | `test_config_loader.py` (campos duplicados/incoherentes rechazados; p. ej. `InitialFrontierPoints ≥ FrontierPoints`, pesos de exploración que no suman 1) | 1 | NOT_IMPLEMENTED |
| CFG-017 | §31, §70 | `ConfigSnapshot` canónico y `ConfigHash` determinista | `config/hashing.py` | `config_snapshot`, `config_hash` | N/A-Infra | — | `test_config_hashing.py` (mismo contenido → mismo hash, independiente del orden de claves; cambio de un campo → hash distinto) | 1 | NOT_IMPLEMENTED |
| CFG-018 | §4, §25 (E-03) | Parámetro centralizado `OptimizationHorizonYears` (`EngineConfig.optimization_horizon_years`, `> 0`, defecto 1.0 declarado solo en la configuración por defecto); única fuente de verdad para comparar expected returns, transaction costs y métricas netas; incluido en `ConfigHash` | `config/engine_config.py`, `config/loader.py` | `EngineConfig.optimization_horizon_years` | N/A-Infra | A-03, CFG-015 | `tests/unit/config/test_optimization_horizon.py` (valor por defecto desde config, rechazo de `≤ 0`, no duplicado en subconfiguraciones, cambia `ConfigHash`) | 1 | NOT_IMPLEMENTED |

## DAT — Datos, universo, carteras y validación (§5–7, §10)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| DAT-001 | §5.1 | Esquema mínimo de histórico: Date, Ticker, AdjustedClose | `models/market_data.py` | `PriceHistory` | N/A-Datos | — | `tests/unit/data/test_price_history_schema.py` | 1 | NOT_IMPLEMENTED |
| DAT-002 | §5.1 | Campos opcionales: Volume, Bid, Ask, FXRate, MarketCap | `models/market_data.py` | `PriceHistory` | N/A-Datos | — | `test_price_history_schema.py::test_optional_fields` | 1 | NOT_IMPLEMENTED |
| DAT-003 | §5.1 | Abstracción `DataSource`; el optimizador no depende del origen físico | `data/sources/base.py` | `DataSource` (Protocol) | N/A-Infra | GOV-007 | `test_datasource_contract.py` (misma salida canónica desde fuentes distintas) | 1 | NOT_IMPLEMENTED |
| DAT-004 | §5.1 | Fuente DataFrame | `data/sources/dataframe_source.py` | `DataFrameSource` | N/A-Datos | DAT-003 | `test_dataframe_source.py` | 1 | NOT_IMPLEMENTED |
| DAT-005 | §5.1 | Fuente Parquet | `data/sources/parquet_source.py` | `ParquetSource` | N/A-Datos | DAT-003 | `test_parquet_source.py` | 1 | NOT_IMPLEMENTED |
| DAT-006 | §5.1 | Fuente CSV | `data/sources/csv_source.py` | `CSVSource` | N/A-Datos | DAT-003 | `test_csv_source.py` | 1 | NOT_IMPLEMENTED |
| DAT-007 | §5.1 | Fuente SQL Server | `data/sources/sqlserver_source.py` | `SQLServerSource` | N/A-Datos | A-28 | `tests/integration/test_sqlserver_source.py` (requiere instancia) | 6 | NOT_IMPLEMENTED |
| DAT-008 | §5.1 | Fuente API u otro DataSource (opcional, extensible) | `data/sources/` | implementación concreta según API del usuario | N/A-Datos | DAT-003 | Test de contrato con el API concreto (si el usuario lo define) | 6 (opcional) | NOT_IMPLEMENTED |
| DAT-009 | §6 | Esquema de universo (18 campos: AssetID … RestrictedAssetFlag) | `models/asset.py` | `AssetMetadata`, `Universe` | N/A-Datos | A-31 | `tests/unit/data/test_universe_schema.py` | 1 | NOT_IMPLEMENTED |
| DAT-010 | §7 | Esquema de carteras actuales (PortfolioID, AssetID/Ticker, CurrentWeight) | `models/portfolio.py` | `CurrentPortfolios` | N/A-Datos | — | `test_current_portfolios_schema.py` | 1 | NOT_IMPLEMENTED |
| DAT-011 | §7 | Configuración por cartera: TargetPortfolioSize, VolatilityLimit, MaxTurnover, InvestmentUniverse, restricciones específicas; precedencia documentada | `models/portfolio.py` | `PortfolioSpec`, `resolve_effective_limits` | N/A-Datos | A-11 | `test_portfolio_spec.py` (precedencia override > global > universo) | 1 | NOT_IMPLEMENTED |
| DAT-012 | §7 | Preservar explícitamente la composición actual (turnover, liquidaciones, nuevos/eliminados, distancia) | `models/portfolio.py` | `CurrentPortfolioState`, `CurrentPortfolioComposition` | N/A-Datos | — | **Bloque 1 obligatorio (portfolio-current-state model)**: `test_current_portfolio_state.py` | 1 | NOT_IMPLEMENTED |
| DAT-013 | §59, Bloque 3 | Índice de activos global ↔ elegible ↔ local de composición | `models/universe_index.py` | `AssetIndex`, `CompositionView` | N/A-Datos | A-31 | `test_asset_index.py` (B1: global); `tests/unit/candidates/test_index_mapping.py` (B3: tres niveles, TST-015) | 1 (global), 3 (tres niveles) | NOT_IMPLEMENTED |
| DAT-014 | §5–7 | Identidad `AssetID` canónica; resolución de `Ticker` validada | `models/asset.py` | `Universe.resolve` | N/A-Datos | A-31 | `test_asset_resolution.py` (ticker ambiguo/desconocido → error) | 1 | NOT_IMPLEMENTED |
| DAT-015 | §6.5 ARCH | Entradas opcionales: ExternalAlpha, ReferenceBenchmarkWeights, AssetBetas, FactorExposures, SimulatedReturns | `models/` | `ExternalAlpha`, `ReferenceBenchmark`, `FactorExposureTable`, `ScenarioReturnSamples` | N/A-Datos | A-10, A-35 | Tests de esquema por entrada (en el bloque que la usa) | 1 (alpha), 4 (resto) | NOT_IMPLEMENTED |
| DAT-016 | §31, §62 (E-06) | `CurrentPortfolioStateHash` determinista a partir de `(AssetID, CurrentWeight)`: pares ordenados por AssetID, pesos serializados exactamente (`float.hex`, `-0.0`→`0.0`, sin redondeo), filas de peso exactamente cero excluidas, SHA-256 | `models/portfolio.py` | `CurrentPortfolioState.current_portfolio_state_hash` | N/A-Infra | A-06, DAT-012 | `tests/unit/data/test_current_portfolio_state_hash.py` (invariante al orden de filas; cambia ante cualquier cambio de peso, incluso en el último bit; estable entre procesos) | 1 | NOT_IMPLEMENTED |
| DAT-020 | §10 | Detección de duplicados (Date, AssetID) y (PortfolioID, AssetID) | `data/validation/*` | `MarketDataValidator`, `PortfolioValidator` | N/A-Datos | — | **Bloque 1 obligatorio**: `test_validation_duplicates.py` | 1 | NOT_IMPLEMENTED |
| DAT-021 | §10 | Fechas inconsistentes (no monótonas, futuras, fuera de calendario, huecos anómalos) | `data/validation/market_data_validator.py` | `MarketDataValidator.check_dates` | N/A-Datos | — | `test_validation_dates.py` | 1 | NOT_IMPLEMENTED |
| DAT-022 | §10 | Precios ≤ 0 | `data/validation/market_data_validator.py` | `check_positive_prices` | N/A-Datos | — | `test_validation_prices.py` | 1 | NOT_IMPLEMENTED |
| DAT-023 | §10 | NaN (missing data) sin relleno silencioso | `data/validation/market_data_validator.py` | `check_missing` | N/A-Datos | — | **Bloque 1 obligatorio (missing data)**: `test_validation_missing.py` | 1 | NOT_IMPLEMENTED |
| DAT-024 | §10 | Valores inf | `data/validation/*` | `check_finite` | N/A-Datos | — | `test_validation_missing.py::test_inf` | 1 | NOT_IMPLEMENTED |
| DAT-025 | §10 | Histórico insuficiente (mínimo de observaciones de config) | `data/validation/market_data_validator.py` | `check_history_length` | N/A-Datos | CFG-002 | `test_validation_history.py` | 1 | NOT_IMPLEMENTED |
| DAT-026 | §10 | Precios stale (n días sin cambio, umbral de config) | `data/validation/market_data_validator.py` | `check_stale` | N/A-Datos | CFG-002 | `test_validation_stale.py` | 1 | NOT_IMPLEMENTED |
| DAT-027 | §10 | Outliers (método y umbral configurables; detectar y registrar, no corregir) | `data/validation/market_data_validator.py` | `check_outliers` | Estadístico | CFG-002 | `test_validation_outliers.py` | 1 | NOT_IMPLEMENTED |
| DAT-028 | §10 | Metadatos incompletos (campos obligatorios/condicionales del universo) | `data/validation/universe_validator.py` | `UniverseValidator` | N/A-Datos | A-04, A-10 | `test_validation_metadata.py` | 1 | NOT_IMPLEMENTED |
| DAT-029 | §10 | Pesos inconsistentes (suma ≠ 1 fuera de tolerancia, negativos con LongOnly, activo desconocido) | `data/validation/portfolio_validator.py` | `PortfolioValidator.check_weights` | N/A-Datos | A-34 | `test_validation_weights.py` | 1 | NOT_IMPLEMENTED |
| DAT-030 | §10 | Límites incompatibles (MinWeight > MaxWeight, fuera de [0,1], overrides contradictorios) | `data/validation/universe_validator.py` | `check_limits` | N/A-Datos | A-30 | `test_validation_limits.py` | 1 | NOT_IMPLEMENTED |
| DAT-031 | §10 | No corregir silenciosamente; registrar toda corrección | `data/validation/report.py` | `DataQualityReport`, `CorrectionLog` | N/A-Datos | — | `test_correction_log.py` (toda corrección permitida por política aparece en el log; sin política → error) | 1 | NOT_IMPLEMENTED |

## RET — Retornos y expected returns (§8–9)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| RET-001 | §8 | Interfaz de expected returns con modos INTERNAL_ESTIMATION / EXTERNAL_ALPHA | `returns/expected/base.py` | `ExpectedReturnProvider` | N/A-Infra | — | **Bloque 1 obligatorio (expected-return interface)**: `test_expected_return_interface.py` | 1 | NOT_IMPLEMENTED |
| RET-002 | §8 | EXTERNAL_ALPHA: ingesta, alineación por AssetID, conversión de horizonte declarado a base anualizada (compatible con `OptimizationHorizonYears`, E-03), validación | `returns/expected/external_alpha.py` | `ExternalAlphaProvider` | N/A-Datos | DAT-015, CFG-018 | `test_external_alpha.py` | 1 | NOT_IMPLEMENTED |
| RET-003 | §8 | INTERNAL_ESTIMATION: media histórica | `returns/expected/historical_mean.py` | `HistoricalMeanProvider` | Estadístico | RET-010 | `test_historical_mean.py` | 1 | NOT_IMPLEMENTED |
| RET-004 | §8 | Método futuro: EWMA de medias | `returns/expected/` | `EWMAMeanProvider` | Estadístico | RET-001 | Test al implementarse | futuro (opcional) | NOT_IMPLEMENTED |
| RET-005 | §8 | Método futuro: factor models | `returns/expected/` | `FactorModelProvider` | Estadístico | DAT-015 | Test al implementarse | futuro (opcional) | NOT_IMPLEMENTED |
| RET-006 | §8 | Método futuro: Bayesian models | `returns/expected/` | `BayesianProvider` | Estadístico | RET-001 | Test al implementarse | futuro (opcional) | NOT_IMPLEMENTED |
| RET-007 | §8 | Método futuro: quantitative signals | `returns/expected/` | `SignalProvider` | Estadístico | RET-001 | Test al implementarse | futuro (opcional) | NOT_IMPLEMENTED |
| RET-008 | §8 | Nunca asumir media histórica = alpha: el método queda etiquetado y se propaga a outputs (`ExpectedReturnMethod`) | `models/risk_model.py` | `ExpectedReturns.method`, `.mode` | N/A-Infra | REP-001 | `test_expected_return_labelling.py` (un provider histórico nunca se etiqueta como EXTERNAL_ALPHA) | 1 | NOT_IMPLEMENTED |
| RET-010 | §9 | Retornos aritméticos `r[t,i] = P[t,i]/P[t-1,i] − 1` por defecto | `returns/returns_engine.py` | `ReturnsEngine.compute` | Cerrado | DAT-001 | **Bloque 1 obligatorio (returns correctos)**: `test_returns_engine.py` (valores exactos en caso manual) | 1 | NOT_IMPLEMENTED |
| RET-011 | §9 | Anualización configurable: `mu_a = TD·mu_d`, `Σ_a = TD·Σ_d` | `returns/annualization.py` | `annualize_mean`, `annualize_covariance` | Cerrado | CFG-003 | **Bloque 1 obligatorio (annualization)**: `test_annualization.py` | 1 | NOT_IMPLEMENTED |
| RET-012 | §9 | Log returns solo con justificación explícita (campo obligatorio en config, registrado) | `returns/returns_engine.py` | `ReturnsEngine.compute(kind=LOG)` | Cerrado | CFG-003 | `test_log_returns_require_justification.py` | 1 | NOT_IMPLEMENTED |

## RSK — Covarianza y PSD (§11)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| RSK-001 | §11 | Interfaz `CovarianceEstimator` | `risk/covariance/base.py` | `CovarianceEstimator` | N/A-Infra | — | `test_covariance_interface.py` | 1 | NOT_IMPLEMENTED |
| RSK-002 | §11 | EMPIRICAL | `risk/covariance/empirical.py` | `EmpiricalCovariance` | Estadístico | RET-010 | `test_empirical_covariance.py` (vs `numpy.cov`) | 1 | NOT_IMPLEMENTED |
| RSK-003 | §11 | LEDOIT_WOLF | `risk/covariance/ledoit_wolf.py` | `LedoitWolfCovariance` | Cerrado | RET-010 | `test_ledoit_wolf.py` (vs referencia sklearn; intensidad de shrinkage ∈ [0,1]) | 1 | NOT_IMPLEMENTED |
| RSK-004 | §11 | OAS | `risk/covariance/oas.py` | `OASCovariance` | Cerrado | A-07 (aceptada: diferido) | `test_oas.py` (vs referencia) | 4 (diferido, E-07) | NOT_IMPLEMENTED |
| RSK-005 | §11 | EWMA | `risk/covariance/ewma.py` | `EWMACovariance` | Estadístico | A-07 (aceptada: diferido) | `test_ewma_covariance.py` | 4 (diferido, E-07) | NOT_IMPLEMENTED |
| RSK-006 | §11 | Verificar finitos | `risk/psd_diagnostics.py` | `diagnose_psd` | Álgebra lineal | — | `test_psd_diagnostics.py::test_non_finite_rejected` | 1 | NOT_IMPLEMENTED |
| RSK-007 | §11 | Simetrizar `Σ = (Σ + Σᵀ)/2` (registrando asimetría original) | `risk/psd_diagnostics.py` | `symmetrize` | Álgebra lineal | — | `test_psd_diagnostics.py::test_symmetrization` | 1 | NOT_IMPLEMENTED |
| RSK-008 | §11 | Eigenvalues, min eigenvalue, condition number | `risk/psd_diagnostics.py` | `PSDDiagnostics` | Álgebra lineal | — | **Bloque 1 obligatorio (PSD, near singular, singular)**: `test_psd_diagnostics.py` | 1 | NOT_IMPLEMENTED |
| RSK-009 | §11 | Comprobar PSD con tolerancia configurable | `risk/psd_diagnostics.py` | `is_psd` | Álgebra lineal | CFG-004 | `test_psd_diagnostics.py::test_psd_check` | 1 | NOT_IMPLEMENTED |
| RSK-010 | §11 | Reparación: eigenvalue floor | `risk/psd_repair.py` | `EigenvalueFloorRepair` | Álgebra lineal | CFG-004 | **Bloque 1 obligatorio (PSD repair)**: `test_psd_repair.py::test_eigen_floor` | 1 | NOT_IMPLEMENTED |
| RSK-011 | §11 | Reparación: nearest PSD (Higham) | `risk/psd_repair.py` | `NearestPSDRepair` | NLP Convexo (proyección alterna) | CFG-004 | `test_psd_repair.py::test_nearest_psd` (resultado PSD, distancia Frobenius mínima frente a floor en caso de referencia) | 1 | NOT_IMPLEMENTED |
| RSK-012 | §11 | Registrar CovarianceMethod, ConditionNumber, OriginalMinEigenvalue, CorrectedMinEigenvalue, CorrectionMagnitude | `risk/psd_repair.py`, `models/risk_model.py` | `PSDRepairReport`, `CovarianceEstimate.diagnostics` | N/A-Infra | — | `test_psd_repair.py::test_report_fields` | 1 | NOT_IMPLEMENTED |
| RSK-013 | §11, §31 | `RiskModel` global (mu, Σ read-only) con `MuSigmaVersion` determinista | `risk/risk_model_builder.py` | `RiskModelBuilder.build`, `RiskModel` | N/A-Infra | RSK-002..012, RET-* | `test_risk_model_builder.py` (arrays no escribibles; versión estable) | 1 | NOT_IMPLEMENTED |

## CON — Restricciones (§12)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| CON-001 | §12 | Presupuesto `Σw = 1` | `constraints/linear.py` | `BudgetConstraint` | QP (lineal) | — | `test_linear_constraints.py::test_budget` + VAL-002 | 2 | NOT_IMPLEMENTED |
| CON-002 | §12 | LongOnly | `constraints/linear.py` | `LongOnlyConstraint` | QP (lineal) | — | `test_linear_constraints.py::test_long_only` | 2 | NOT_IMPLEMENTED |
| CON-003 | §12 | MinWeight / MaxWeight (condicional a tenencia) | `constraints/linear.py` | `WeightBoundsConstraint` | QP (lineal) | A-30, DAT-011 | `test_linear_constraints.py::test_bounds` | 2 | NOT_IMPLEMENTED |
| CON-004 | §12, §21 | VolatilityLimit `sqrt(wᵀΣw) ≤ σ_max` | `constraints/conic.py` | `VolatilityLimitConstraint` | SOCP | SOL-005 | `tests/integration/test_volatility_limit.py` (B4) | 4 | NOT_IMPLEMENTED |
| CON-005 | §12, §24 | MaxTurnover (lineal vía b/s, incluye liquidaciones `E`) | `constraints/linear.py` | `TurnoverConstraint` | QP (lineal) | TC-010, TC-011 | `test_turnover_constraint.py` | 2 | NOT_IMPLEMENTED |
| CON-006 | §12 | SectorMin / SectorMax | `constraints/linear.py` | `GroupConstraint(Sector)` | QP (lineal) | DAT-009 | `test_group_constraints.py::test_sector` | 2 | NOT_IMPLEMENTED |
| CON-007 | §12 | CountryMin / CountryMax | `constraints/linear.py` | `GroupConstraint(Country)` | QP (lineal) | DAT-009 | `test_group_constraints.py::test_country` | 2 | NOT_IMPLEMENTED |
| CON-008 | §12 | AssetClassMin / AssetClassMax | `constraints/linear.py` | `GroupConstraint(AssetClass)` | QP (lineal) | DAT-009 | `test_group_constraints.py::test_asset_class` | 2 | NOT_IMPLEMENTED |
| CON-009 | §12 | CurrencyMin / CurrencyMax | `constraints/linear.py` | `GroupConstraint(Currency)` | QP (lineal) | DAT-009 | `test_group_constraints.py::test_currency` | 2 | NOT_IMPLEMENTED |
| CON-010 | §12 | MaximumNewAssets | `constraints/integer.py`, `candidates/` | `MaxNewAssetsConstraint` | Heurístico (B3) / MIQP (B4) | CAN-019, MIP-001 | `test_candidate_constraints.py::test_max_new_assets`; `test_exact_mip.py::test_max_new_assets` | 3, 4 | NOT_IMPLEMENTED |
| CON-011 | §12 | MaximumSwaps | `constraints/integer.py`, `candidates/` | `MaxSwapsConstraint` | Heurístico (B3) / MIQP (B4) | CAN-019, MIP-001 | `test_candidate_constraints.py::test_max_swaps`; `test_exact_mip.py::test_max_swaps` | 3, 4 | NOT_IMPLEMENTED |
| CON-012 | §12 | LiquidityConstraint (definición A-11) | `constraints/linear.py`, `candidates/eligibility.py` | `LiquidityConstraint` | QP (lineal) | A-11, DAT-011 | `test_liquidity_constraint.py` | 3 | NOT_IMPLEMENTED |
| CON-013 | §12 | RestrictedAssets: un activo restringido que no está en la cartera actual nunca se incorpora ni se compra | `constraints/linear.py`, `candidates/eligibility.py` | `RestrictedAssetsConstraint` | QP (lineal) | A-09, CON-021 | `test_restricted_assets.py::test_new_restricted_never_added` | 2 (fijo), 3 (elegibilidad) | NOT_IMPLEMENTED |
| CON-014 | §12 | CashAllocation (activo sintético CASH) | `constraints/linear.py`, `models/asset.py` | `CashAllocationConstraint` | QP (lineal) | A-12 | `test_cash_allocation.py` | 2 | NOT_IMPLEMENTED |
| CON-015 | §12 | TrackingError | `constraints/conic.py` | `TrackingErrorConstraint` | SOCP | A-10, DAT-015 | `test_tracking_error.py` | 4 | NOT_IMPLEMENTED |
| CON-016 | §12 | BetaLimit | `constraints/linear.py` | `BetaLimitConstraint` | QP (lineal) | A-10, DAT-015 | `test_beta_limit.py` | 4 | NOT_IMPLEMENTED |
| CON-017 | §12 | FactorExposureLimits | `constraints/linear.py` | `FactorExposureConstraint` | QP (lineal) | A-10, DAT-015 | `test_factor_limits.py` | 4 | NOT_IMPLEMENTED |
| CON-018 | §12 | Representación declarativa `ConstraintSet` + compilador a bloques lineales/cónicos/enteros + `ConstraintHash` | `constraints/constraint_set.py`, `constraints/compiler.py` | `ConstraintSet`, `ConstraintCompiler`, `CompiledConstraints` | N/A-Infra | CFG-005 | `test_constraint_compiler.py` (matrices correctas en caso manual; hash estable) | 2 | NOT_IMPLEMENTED |
| CON-019 | §7, §49 | Cardinalidad TargetPortfolioSize | `constraints/integer.py`, `candidates/` | `CardinalityConstraint` | Heurístico (B3) / MIQP (B4) | MIP-001 | `test_cardinality.py` | 3, 4 | NOT_IMPLEMENTED |
| CON-020 | §7, §12 | Restricciones específicas por cartera aplicadas con precedencia documentada | `constraints/compiler.py` | `ConstraintCompiler` | N/A-Infra | DAT-011 | `test_portfolio_specific_constraints.py` | 2 | NOT_IMPLEMENTED |
| CON-021 | §12 (E-09) | Enum `RestrictedExistingPositionPolicy` {HOLD_OR_REDUCE, FREEZE_WEIGHT, FORCE_LIQUIDATE} y campo de configuración (global + override por cartera); selección explícita obligatoria si existen activos restringidos con `CurrentWeight > 0`; `HOLD_OR_REDUCE` en config de ejemplo y fixtures | `models/enums.py`, `config/constraint_config.py`, `data/validation/portfolio_validator.py` | `RestrictedExistingPositionPolicy`, `ConstraintConfig.restricted_existing_position_policy` | N/A-Infra | A-09, CFG-005, DAT-011 | `tests/unit/config/test_restricted_policy_config.py` (restringido en cartera sin política → error; con política → aceptado; override por cartera respeta precedencia; config de ejemplo = HOLD_OR_REDUCE) | 1 | NOT_IMPLEMENTED |
| CON-022 | §12 (E-09) | Semántica de la política en optimización y búsqueda: HOLD_OR_REDUCE `0 ≤ w ≤ min(w_current, MaxWeight)` (prevalece sobre MinWeight); FREEZE_WEIGHT `w = w_current`; FORCE_LIQUIDATE `w = 0` con coste de venta; incompatibilidades → INFEASIBLE en pre-factibilidad; traducción en `ConstraintCompiler`/`EligibilityFilter`, nunca hardcodeada en `CandidateEngine` ni en backends | `constraints/compiler.py`, `constraints/feasibility.py`, `candidates/eligibility.py`, `validation/solution_validator.py` | `ConstraintCompiler`, `EligibilityFilter`, `check_restricted_policy` | QP (lineal) | CON-021, FEA-007, VAL-007 | `test_restricted_policy_semantics.py` (una prueba por política en frontera continua y global; FREEZE fijado en todas las composiciones; FORCE excluido con K_E; HOLD_OR_REDUCE nunca aumenta; conflictos con MaxTurnover/MaxWeight → INFEASIBLE sin llamar al solver) + `test_architecture_rules.py::test_policy_not_referenced_in_candidate_engine_or_backends` | 2 (continua), 3 (candidatos) | NOT_IMPLEMENTED |

## FEA — Factibilidad previa (§13)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| FEA-001 | §13 | Reglas deterministas antes de cualquier solver (`ΣMin ≤ 1`, `ΣMax ≥ 1` sobre la composición) | `constraints/feasibility.py` | `PreFeasibilityChecker.check_bounds` | N/A (reglas) | A-30 | `test_prefeasibility.py::test_bounds_rules` | 2 | NOT_IMPLEMENTED |
| FEA-002 | §13 | Cardinalidad vs pesos (`K·min Min ≤ 1 ≤ Σ top-K Max`) | `constraints/feasibility.py` | `check_cardinality` | N/A (reglas) | A-30 | `test_prefeasibility.py::test_cardinality_rules` | 3 | NOT_IMPLEMENTED |
| FEA-003 | §13 | Sectores / grupos vs límites de activos | `constraints/feasibility.py` | `check_groups` | N/A (reglas) | CON-006..009 | `test_prefeasibility.py::test_group_rules` | 2 | NOT_IMPLEMENTED |
| FEA-004 | §13 | Turnover mínimo forzado por límites > MaxTurnover | `constraints/feasibility.py` | `check_turnover` | N/A (reglas) | CON-005 | `test_prefeasibility.py::test_turnover_rules` | 2 | NOT_IMPLEMENTED |
| FEA-005 | §13 | Volatilidad: incompatibilidad VolatilityLimit (cotas deterministas + certificado de MinVariance documentado) | `constraints/feasibility.py` | `check_volatility` | N/A (reglas) + QP (certificado) | CON-004 | `test_prefeasibility.py::test_volatility_rules` | 4 | NOT_IMPLEMENTED |
| FEA-006 | §13 | Liquidez | `constraints/feasibility.py` | `check_liquidity` | N/A (reglas) | CON-012 | `test_prefeasibility.py::test_liquidity_rules` | 3 | NOT_IMPLEMENTED |
| FEA-007 | §13 | Si inviable: no ejecutar el solver y registrar la causa (`StatusSource=PRE_SOLVER_CHECK`) | `constraints/feasibility.py` | `FeasibilityReport` | N/A-Infra | A-15 | `test_prefeasibility.py::test_solver_not_called` (contador de llamadas del backend = 0) | 2 | NOT_IMPLEMENTED |
| FEA-008 | §13 | Restricciones que requieren datos ausentes (TE, beta, factores, liquidez) → error explícito de pre-factibilidad | `constraints/feasibility.py` | `check_required_inputs` | N/A (reglas) | A-10, A-11 | `test_prefeasibility.py::test_missing_inputs` | 4 | NOT_IMPLEMENTED |

## OPT — Familias y problemas de optimización (§14–22)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| OPT-001 | §14 | Tres familias separadas: FAST_PRODUCTION, EXACT_MIP, NONCONVEX_RESEARCH | `optimizers/router.py`, `models/enums.py` | `OptimizationFamily`, `SolverRouter` | N/A-Infra | SOL-008 | `test_router.py::test_families_isolated` | 2 (FAST), 4 (resto) | NOT_IMPLEMENTED |
| OPT-002 | §14 | FAST_PRODUCTION = selección discreta previa + optimización continua convexa | `engine.py`, `candidates/`, `frontiers/` | pipeline `GLOBAL_CANDIDATE_FRONTIER` | Heurístico + QP/SOCP | CAN-*, FRN-002 | `tests/integration/test_fast_production_pipeline.py` | 3 | NOT_IMPLEMENTED |
| OPT-003 | §15 | Composición fija: `Σw=1`, `Min ≤ w ≤ Max`; activos no seleccionados fuera del vector de variables | `optimizers/formulations/qp_builder.py` | `build_fixed_composition_problem` | QP | CON-018 | `test_qp_builder.py::test_variables_only_selected_assets` | 2 | NOT_IMPLEMENTED |
| OPT-004 | §16 | Quadratic utility `max μᵀw − λwᵀΣw − TC(w)` | `optimizers/formulations/qp_builder.py` | `build_utility_problem` | QP | A-02, TC-010 | `test_quadratic_utility.py` (vs solución independiente KKT/referencia) | 2 | NOT_IMPLEMENTED |
| OPT-005 | §16 | OSQP para QP con restricciones lineales | `optimizers/router.py` | regla de routing | QP | SOL-004, SOL-008 | TST-017 (`test_routing_qp_to_osqp`) | 2 | NOT_IMPLEMENTED |
| OPT-006 | §17 | Minimum Variance | `frontiers/explicit_portfolios.py` | `solve_minimum_variance` | QP | OPT-003 | **Contractual B2**: `test_minimum_variance.py` (vs solución analítica sin restricciones activas y vs referencia con restricciones) | 2 | NOT_IMPLEMENTED |
| OPT-007 | §18 | Maximum Return (lexicográfico, A-14) | `frontiers/explicit_portfolios.py` | `solve_maximum_return` | QP (LP) | A-14 | **Contractual B2**: `test_maximum_return.py` (vs solución cerrada de caja+presupuesto; desempate de mínima varianza) | 2 | NOT_IMPLEMENTED |
| OPT-008 | §19 | Target Return `min wᵀΣw` s.a. `μᵀw ≥ R` | `optimizers/formulations/qp_builder.py` | `build_target_return_problem` | QP | OPT-003 | **Contractual B2**: `test_target_return.py` (restricción activa cuando R > R_MV; inviable si R > R_max) | 2 | NOT_IMPLEMENTED |
| OPT-009 | §20 | Maximum Sharpe con formulación válida (Charnes–Cooper / SOCP / bisección) — nunca QP estándar incorrecto | `optimizers/formulations/sharpe.py`, `frontiers/explicit_portfolios.py` | `solve_maximum_sharpe` | SOCP | A-13, SOL-005 | **B4**: `test_max_sharpe.py` (vs bisección cuasiconvexa; Sharpe ≥ Sharpe de todos los puntos de frontera; caso sin exceso positivo → NOT_APPLICABLE) | 4 | NOT_IMPLEMENTED |
| OPT-010 | §21 | Volatility control `sqrt(wᵀΣw) ≤ VolLimit` con solver cónico | `optimizers/formulations/volatility.py` | `build_volatility_target_problem` | SOCP | CON-004 | **B4**: `test_volatility_control.py` (restricción activa, vol ≤ límite + tol) | 4 | NOT_IMPLEMENTED |
| OPT-011 | §22 | Minimizar CVaR (Rockafellar–Uryasev) | `optimizers/formulations/cvar.py` | `build_min_cvar_problem` | QP (LP) | A-35, DAT-015 | **B4**: `test_cvar.py::test_min_cvar` (vs CVaR empírico de la solución) | 4 | NOT_IMPLEMENTED |
| OPT-012 | §22 | Restricción `CVaR ≤ MaxCVaR` | `optimizers/formulations/cvar.py` | `add_cvar_constraint` | QP (LP) | OPT-011 | **B4**: `test_cvar.py::test_cvar_constraint` | 4 | NOT_IMPLEMENTED |
| OPT-013 | ARCH §9.2 | Cada problema declara su `ProblemClass` y familia (base del routing) | `optimizers/problem.py` | `CanonicalProblem.problem_class` | N/A-Infra | — | `test_problem_classification.py` (P1–P21 clasificados según ARCHITECTURE §9.2) | 2 (QP), 4 (resto) | NOT_IMPLEMENTED |
| OPT-014 | §82 | Estrategias nombradas por escenario (Current, MinVar, MaxRet, MaxSharpe, VolTarget, Robust…) con `StrategyID` | `frontiers/explicit_portfolios.py` | `NamedStrategyRunner` | QP/SOCP | A-20 | `test_named_strategies.py` | 2 (MinVar/MaxRet/Current), 4 (resto) | NOT_IMPLEMENTED |

## TC — Costes de transacción, turnover, gross/net (§23–25)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| TC-001 | §23 | `Δw = w_new − w_current` sobre la **unión** current ∪ new | `costs/transaction_cost_model.py` | `align_union` | Cerrado | DAT-012 | `test_transaction_costs.py::test_union_alignment` | 2 | NOT_IMPLEMENTED |
| TC-002 | §23 | Modelo asimétrico `Σ[Buy·max(Δ,0) + Sell·max(−Δ,0)]` (A-01) | `costs/transaction_cost_model.py` | `TransactionCostModel.cost` | Cerrado | A-01 | `test_transaction_costs.py::test_manual_values` | 2 | NOT_IMPLEMENTED |
| TC-003 | §23 | Liquidación completa: `w_current>0 ∧ w_new=0` → venta completa contabilizada | `costs/transaction_cost_model.py` | `TransactionCostModel.cost` | Cerrado | TC-001 | TST-014 (A/B → C/B) | 2, 3 | NOT_IMPLEMENTED |
| TC-004 | §23 | Costes no calculados solo sobre la nueva composición | `costs/transaction_cost_model.py` | `TransactionCostModel.cost` | Cerrado | TC-001 | `test_transaction_costs.py::test_exited_assets_included` | 2 | NOT_IMPLEMENTED |
| TC-005 | §6, §23, Bloque 1 | Modelo de datos de costes: fuentes, precedencia, unidades, validación (finitos, ≥ 0) | `models/costs.py`, `costs/transaction_cost_model.py` | `AssetCostVector`, `resolve_asset_costs` | N/A-Datos | A-04 | **Bloque 1 obligatorio (transaction-cost input validation)**: `test_transaction_cost_inputs.py` | 1 | NOT_IMPLEMENTED |
| TC-006 | §24 | Turnover `= 0.5·Σ abs(Δw)`, consistente con el modelo de costes | `costs/turnover.py` | `turnover` | Cerrado | TC-001 | `test_turnover.py` | 2 | NOT_IMPLEMENTED |
| TC-007 | §24 | Sin cartera actual: Turnover y TC = no disponibles (NULL + motivo), no inventados | `costs/`, `outputs/` | `Availability` | N/A-Infra | DAT-012 | `test_no_current_portfolio.py` | 2 | NOT_IMPLEMENTED |
| TC-008 | §25 | `ExpectedReturnGross = μᵀw`; `ExpectedReturnNet = Gross − TC` (A-02) | `metrics/portfolio_metrics.py` | `compute_metrics` | Cerrado | A-02 | `test_metrics.py::test_gross_net` | 2 | NOT_IMPLEMENTED |
| TC-009 | §25 | Costes en unidades compatibles con retorno sobre el horizonte `H = OptimizationHorizonYears`: `TransactionCost = TransactionCostOneOff / H`; `ExpectedReturnNet = μᵀw − TransactionCost`; outputs en base anualizada con `TransactionCostOneOff` adicional (E-03) | `costs/transaction_cost_model.py` | `to_return_units(tc_one_off, horizon)` | Cerrado | A-03, CFG-018 | `test_transaction_costs.py::test_horizon_units` + TST-022 | 2 | NOT_IMPLEMENTED |
| TC-010 | §37–38 | Costes linealizados dentro de la optimización (variables b/s) manteniendo convexidad | `optimizers/formulations/qp_builder.py` | `add_cost_lifting` | QP | TC-002 | `test_cost_lifting.py` (b·s = 0 en óptimo con costes > 0; TC de b/s = TC ex post) | 2 | NOT_IMPLEMENTED |
| TC-011 | §23, Bloque 3 | Coste constante `K_E` de activos que salen de la composición (no son variables) incluido en objetivo neto, target neto, turnover | `optimizers/formulations/qp_builder.py` | `exit_cost_offset` | QP | TC-003 | `test_cost_lifting.py::test_exit_offset` + TST-014 | 3 | NOT_IMPLEMENTED |
| TC-012 | §64 | `TransactionCostAsset` por activo en outputs | `metrics/contributions.py` | `asset_transaction_costs` | Cerrado | TC-002 | `test_contributions.py::test_asset_costs_sum_to_total` | 2 | NOT_IMPLEMENTED |
| TC-013 | §73 | Coste por escenario `cost_s` (multiplicadores de escenario) | `scenarios/scenario_engine.py` | `ScenarioData.cost_s` | Cerrado | SCN-002 | `test_scenario_costs.py` | 4 | NOT_IMPLEMENTED |

## CAN — Candidate engine (§26–31)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| CAN-001 | §26 | Contrato `generate_candidate_compositions(...) -> list[CandidateComposition]`; nunca una sola composición como implementación final | `candidates/candidate_engine.py` | `CandidateEngine.generate_candidate_compositions` | Heurístico | — | TST-012 (`len > 1`) | 3 | NOT_IMPLEMENTED |
| CAN-002 | §26 | Parte de `CurrentPortfolioComposition` (no construye desde cero ignorando la actual) | `candidates/candidate_engine.py` | idem | Heurístico | DAT-012 | `test_candidate_engine.py::test_starts_from_current` (todas las composiciones derivan de la actual por `SwapHistory`) | 3 | NOT_IMPLEMENTED |
| CAN-003 | §26 | 1-swap | `candidates/swap_generator.py` | `SwapGenerator.one_swap` | Heurístico | CAN-010 | `test_swap_generator.py::test_one_swap` | 3 | NOT_IMPLEMENTED |
| CAN-004 | §26 | 2-swap (vecindario restringido documentado, A-18) | `candidates/swap_generator.py` | `SwapGenerator.two_swap` | Heurístico | A-18 | `test_swap_generator.py::test_two_swap` (exhaustivo en universo pequeño vs enumeración) | 3 | NOT_IMPLEMENTED |
| CAN-005 | §26 | 3-swap opcional configurable | `candidates/swap_generator.py` | `SwapGenerator.three_swap` | Heurístico | CFG-009 | `test_swap_generator.py::test_three_swap_toggle` | 3 | NOT_IMPLEMENTED |
| CAN-006 | §26 | Local search | `candidates/local_search.py` | `LocalSearch` | Heurístico | CAN-003 | `test_local_search.py` (mejora monótona del score; alcanza óptimo local conocido en caso sintético) | 3 | NOT_IMPLEMENTED |
| CAN-007 | §26, §29 | Beam search: mejores B por iteración, BeamWidth configurable, varias composiciones por nivel | `candidates/beam_search.py` | `BeamSearch` | Heurístico | CAN-015 | `test_beam_search.py` (B > 1 mantiene B composiciones distintas; B=1 ≠ implementación final; encuentra óptimo que greedy no encuentra en caso diseñado) | 3 | NOT_IMPLEMENTED |
| CAN-008 | §26, §28 | Exploration vs exploitation: componentes alta convicción / diversificación / exploración configurables (sin hardcoding), semilla determinista | `candidates/exploration.py` | `ExplorationPolicy` | Heurístico | CFG-009, PAR-009 | `test_exploration.py` (proporciones respetadas; reproducible con semilla) | 3 | NOT_IMPLEMENTED |
| CAN-009 | §26 | Diversification candidates | `candidates/screening.py` | `diversification_candidates` | Heurístico | CAN-010 | `test_screening.py::test_diversification_candidates` | 3 | NOT_IMPLEMENTED |
| CAN-010 | §27 | Screening multiseñal: ExpectedAlpha, MarginalRiskContribution, DiversificationContribution, CovarianceWithPortfolio, ExpectedUtilityGain, RiskAdjustedReturn, Liquidity, TransactionCost, SectorFit | `candidates/screening.py` | `CandidateScreening.score` | Heurístico | RSK-013, TC-005 | `test_screening.py::test_all_signals_computed` (valores manuales por señal) | 3 | NOT_IMPLEMENTED |
| CAN-011 | §27 | No usar exclusivamente Alpha/Covariance | `candidates/screening.py` | pesos de señales en config | Heurístico | CAN-010 | `test_screening.py::test_not_alpha_over_cov_only` (cambiar peso de otra señal cambia el ranking) | 3 | NOT_IMPLEMENTED |
| CAN-012 | Bloque 3 | Screening vectorizado sin bucles Python sobre cientos de activos | `candidates/screening.py` | idem | Heurístico | PAR-006 | `test_screening.py::test_vectorized_equivalence` + benchmark | 3 | NOT_IMPLEMENTED |
| CAN-013 | Bloque 3 | EligibilityFilter (EligibleFlag, LiquidityFlag, Restricted, InvestmentUniverse) sobre índices | `candidates/eligibility.py` | `EligibilityFilter` | N/A (reglas) | CON-012, CON-013, CON-022 | `test_eligibility.py` | 3 | NOT_IMPLEMENTED |
| CAN-014 | §30 | Tabu search opcional con TabuTenure configurable | `candidates/tabu.py` | `TabuList` | Heurístico | CFG-009 | `test_tabu.py` (ciclo evitado en caso diseñado) | 3 | NOT_IMPLEMENTED |
| CAN-015 | §29, §31 | CompositionHash determinista desde IDs ordenados; deduplicación en beam | `candidates/composition_hash.py` | `composition_hash` | N/A-Infra | DAT-013 | `test_composition_hash.py` (orden de entrada irrelevante; duplicados eliminados) | 3 | NOT_IMPLEMENTED |
| CAN-016 | Bloque 3 | Salida por composición: CompositionID, Assets, ParentComposition, SwapHistory, CandidateScore, EstimatedUtilityGain, EstimatedTurnover, EstimatedTransactionCost | `models/composition.py` | `CandidateComposition` | N/A-Datos | — | `test_candidate_output_fields.py` | 3 | NOT_IMPLEMENTED |
| CAN-017 | Bloque 3 | CandidateDiagnostics por activo evaluado | `candidates/diagnostics.py` | `CandidateDiagnosticsBuilder` | N/A-Datos | OUT-004 | `test_candidate_diagnostics.py` | 3 | NOT_IMPLEMENTED |
| CAN-018 | §12, §26 | Movimientos respetan MaximumNewAssets, MaximumSwaps, TargetPortfolioSize | `candidates/swap_generator.py` | `MoveConstraints` | Heurístico | CON-010, CON-011, CON-019 | `test_candidate_constraints.py` | 3 | NOT_IMPLEMENTED |
| CAN-019 | ARCH A-19 | Movimientos ADD/DROP cuando `card(current) ≠ TargetPortfolioSize` | `candidates/swap_generator.py` | `SwapGenerator.add_drop` | Heurístico | A-19 | `test_swap_generator.py::test_add_drop` | 3 | NOT_IMPLEMENTED |
| CAN-020 | ARCH A-19, §24 | Modo COLD_START sin cartera actual (Turnover/TC no disponibles) | `candidates/candidate_engine.py` | `CandidateEngine` (cold start) | Heurístico | A-19, TC-007 | `test_candidate_engine.py::test_cold_start` | 3 | NOT_IMPLEMENTED |
| CAN-021 | Bloque 3 | Evaluación de composiciones (aproximación analítica o QP pequeño; modo configurable) | `candidates/candidate_engine.py` | `CompositionEvaluator` | Heurístico + QP | OPT-004 | `test_composition_evaluator.py` (modo QP = utilidad exacta del QP) | 3 | NOT_IMPLEMENTED |
| CAN-022 | §26 | La lista de candidatos incluye la composición actual como referencia comparativa | `candidates/candidate_engine.py` | idem | N/A-Infra | CAN-001 | `test_candidate_engine.py::test_current_included` | 3 | NOT_IMPLEMENTED |

## FRN — Fronteras eficientes (§32–43)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| FRN-001 | §32 | CONTINUOUS_FRONTIER: composición actual fija, solo pesos | `frontiers/continuous_frontier.py` | `ContinuousFrontierEngine` | QP | OPT-003 | TST-011 | 2 | NOT_IMPLEMENTED |
| FRN-002 | §33 | GLOBAL_CANDIDATE_FRONTIER: múltiples composiciones → frontera por composición → envolvente Pareto global | `frontiers/global_frontier.py` | `GlobalCandidateFrontierEngine` | Heurístico + QP | CAN-001, FRN-017 | TST-012 | 3 | NOT_IMPLEMENTED |
| FRN-003 | §33, Bloque 3 | Las dos fronteras son pipelines distintos (no confundir) | `frontiers/` | clases distintas + `FrontierScope` | N/A-Infra | A-05 | `test_frontier_scopes.py` (continua nunca contiene CompositionID ≠ actual; global contiene > 1) | 3 | NOT_IMPLEMENTED |
| FRN-004 | §34 | Múltiples puntos por (PortfolioID, ScenarioID, FrontierType, CompositionID) | `frontiers/` | `CompositionFrontierResult` | N/A-Infra | — | `test_frontier_result.py` | 2 | NOT_IMPLEMENTED |
| FRN-005 | §35 | Risk Aversion Grid: `min wᵀΣw − θμᵀw`, `θ=1/λ`, `P=2Σ` constante, update de `q`, warm start | `frontiers/risk_aversion_grid.py` | `RiskAversionGrid` | QP | SOL-009 | **Contractual B2**: `test_risk_aversion_grid.py` (P no cambia entre puntos; solo q; resultados = cold solve) | 2 | NOT_IMPLEMENTED |
| FRN-006 | §35 | MinimumVariance y MaximumReturn calculados explícitamente | `frontiers/explicit_portfolios.py` | `solve_minimum_variance`, `solve_maximum_return` | QP | OPT-006, OPT-007 | `test_risk_aversion_grid.py::test_explicit_endpoints` | 2 | NOT_IMPLEMENTED |
| FRN-007 | §35 | Calibración del rango θ (explícito o AUTO desde endpoints) | `frontiers/theta_calibration.py` | `calibrate_theta_grid` | Cerrado | A-16 | `test_theta_calibration.py` | 2 | NOT_IMPLEMENTED |
| FRN-008 | §36 | Target Return Grid: P y A constantes, solo bound de la fila de retorno | `frontiers/target_return_grid.py` | `TargetReturnGrid` | QP | SOL-009 | **Contractual B2**: `test_target_return_grid.py` (A no cambia; solo l) | 2 | NOT_IMPLEMENTED |
| FRN-009 | §36 | Rango del target grid `[R_MV, R_max]` | `frontiers/target_return_grid.py` | `target_range` | Cerrado | A-17 | `test_target_return_grid.py::test_range` | 2 | NOT_IMPLEMENTED |
| FRN-010 | §37 | NET_FRONTIER (risk aversion) con `θ·TC(w)` dentro de la optimización | `frontiers/risk_aversion_grid.py` | `RiskAversionGrid(cost=NET)` | QP | TC-010, A-02 | **Contractual B2**: `test_net_frontier.py` + TST-013 | 2 | NOT_IMPLEMENTED |
| FRN-011 | §38 | NET target return `μᵀw − TC(w) ≥ NetTarget` lineal | `frontiers/target_return_grid.py` | `TargetReturnGrid(cost=NET)` | QP | TC-010 | `test_net_frontier.py::test_net_target_constraint` | 2 | NOT_IMPLEMENTED |
| FRN-012 | §39 | POST_COST_GROSS_FRONTIER opcional (bruta evaluada ex post), etiquetada distinto de NET | `frontiers/continuous_frontier.py` | `post_cost_evaluation` | Cerrado | A-05 | **Contractual B2**: `test_post_cost_gross.py` (NET domina o iguala a POST_COST en (vol, net)) | 2 | NOT_IMPLEMENTED |
| FRN-013 | §37, Bloque 2 | GROSS_FRONTIER | `frontiers/continuous_frontier.py` | `CostTreatment.GROSS` | QP | FRN-005 | **Contractual B2**: `test_gross_frontier.py` | 2 | NOT_IMPLEMENTED |
| FRN-014 | §40 | IsGrossEfficient (X=Vol, Y=Gross) | `frontiers/pareto.py` | `pareto_mask` | Cerrado | — | `test_pareto.py::test_gross` | 2 | NOT_IMPLEMENTED |
| FRN-015 | §40 | IsNetEfficient (X=Vol, Y=Net) | `frontiers/pareto.py` | `pareto_mask` | Cerrado | — | `test_pareto.py::test_net` | 2 | NOT_IMPLEMENTED |
| FRN-016 | §40 | No eliminar dominadas del almacenamiento | `frontiers/pareto.py`, `outputs/` | flags, no filtrado | N/A-Infra | — | `test_pareto.py::test_dominated_kept` | 2 | NOT_IMPLEMENTED |
| FRN-017 | §33 | Envolvente Pareto global sobre la unión de composiciones | `frontiers/global_frontier.py` | `global_pareto` | Cerrado | FRN-014, FRN-015 | `test_global_frontier.py::test_global_envelope` | 3 | NOT_IMPLEMENTED |
| FRN-018 | §41 | FrontierPoints default 20 (en config), configurable (10/20/30/50/…) | `config/frontier_config.py` | `FrontierConfig.frontier_points` | N/A-Infra | A-29 | `test_frontier_points.py` (parametrizado 10/20/30/50) | 2 | NOT_IMPLEMENTED |
| FRN-019 | §42 | AdaptiveFrontier real: iniciales < total, detección de huecos/curvatura, inserción, máximo | `frontiers/adaptive.py` | `AdaptiveFrontier` | QP | FRN-005, FRN-008 | `test_adaptive_frontier.py` (parámetros finales ≠ grid uniforme; inserciones en el mayor hueco; nunca excede el máximo) | 2 | NOT_IMPLEMENTED |
| FRN-020 | §43 | Deduplicación por tolerancias en pesos, retorno y volatilidad | `frontiers/dedup.py` | `deduplicate` | Cerrado | CFG-007 | `test_dedup.py` | 2 | NOT_IMPLEMENTED |
| FRN-021 | ARCH A-05 | `FrontierScope` × `CostTreatment` y `FrontierType` compuesto en outputs | `models/enums.py` | enums | N/A-Infra | A-05 | `test_frontier_type_encoding.py` | 2 | NOT_IMPLEMENTED |
| FRN-022 | Bloque 2 DoD | Dataset (Volatility, ExpectedReturnGross, ExpectedReturnNet) graficable por cartera | `outputs/builders.py` | `frontier_dataset` | N/A-Infra | FRN-001 | `tests/integration/test_frontier_dataset.py` | 2 | NOT_IMPLEMENTED |
| FRN-023 | §34, §44 | Puntos fallidos/inválidos se almacenan con `IsValidSolution=False` y se excluyen de Pareto | `frontiers/` | `FrontierPoint.is_valid` | N/A-Infra | VAL-009 | `test_frontier_invalid_points.py` | 2 | NOT_IMPLEMENTED |

## VAL — Validación independiente de soluciones (§44)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| VAL-001 | §44 | Toda solución pasa validación independiente; no aceptar por `SOLVED` del solver | `validation/solution_validator.py` | `SolutionValidator.validate` | N/A-Infra | — | `test_solution_validator.py::test_solver_optimal_but_invalid_rejected` (solución manipulada con estado OPTIMAL → inválida) | 2 | NOT_IMPLEMENTED |
| VAL-002 | §44 | sum(weights), lower bounds, upper bounds, finite weights | `validation/solution_validator.py` | `check_budget`, `check_bounds`, `check_finite` | N/A (verificación) | CON-001..003 | `test_solution_validator.py::test_basic_checks` | 2 | NOT_IMPLEMENTED |
| VAL-003 | §44 | Volatility (vs límite activo) | `validation/solution_validator.py` | `check_volatility` | N/A (verificación) | CON-004 | `test_solution_validator.py::test_volatility` | 2 (métrica), 4 (límite) | NOT_IMPLEMENTED |
| VAL-004 | §44 | Turnover (incluye liquidaciones) | `validation/solution_validator.py` | `check_turnover` | N/A (verificación) | CON-005, TC-006 | `test_solution_validator.py::test_turnover` | 2 | NOT_IMPLEMENTED |
| VAL-005 | §44 | Sector, country, asset-class (y currency) | `validation/solution_validator.py` | `check_groups` | N/A (verificación) | CON-006..009 | `test_solution_validator.py::test_groups` | 2 | NOT_IMPLEMENTED |
| VAL-006 | §44 | Tracking error | `validation/solution_validator.py` | `check_tracking_error` | N/A (verificación) | CON-015 | `test_solution_validator.py::test_tracking_error` | 4 | NOT_IMPLEMENTED |
| VAL-007 | §44 | Cualquier restricción activa del `ConstraintSet` (validación genérica por restricción compilada) | `validation/solution_validator.py` | `check_all(compiled)` | N/A (verificación) | CON-018 | `test_solution_validator.py::test_every_constraint_type_checked` | 2 (lineales), 3–4 (resto) | NOT_IMPLEMENTED |
| VAL-008 | §44 | Tolerancias de validación desde configuración | `validation/tolerances.py` | `ValidationTolerances` | N/A-Infra | CFG-008 | `test_validation_tolerances.py` | 2 | NOT_IMPLEMENTED |
| VAL-009 | §44, §63, §67 | Resultado: `IsValidSolution`, `MaximumConstraintViolation`, lista de violaciones | `models/solution.py` | `ValidationReport` | N/A-Infra | — | `test_solution_validator.py::test_report` | 2 | NOT_IMPLEMENTED |
| VAL-010 | §49, §12 | Validación de cardinalidad, nuevos activos y swaps | `validation/solution_validator.py` | `check_cardinality` | N/A (verificación) | CON-010, CON-011, CON-019 | `test_solution_validator.py::test_cardinality` | 3 | NOT_IMPLEMENTED |

## SOL — Estados, backends y routing (§45–48)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| SOL-001 | §45 | Enum de 9 estados (OPTIMAL … UNKNOWN) | `models/enums.py` | `SolverStatus` | N/A-Infra | — | `test_solver_status.py::test_enum_complete` | 2 | NOT_IMPLEMENTED |
| SOL-002 | §45 | No confundir fallo numérico con inviabilidad; `*_inaccurate` nunca promovido a estado firme | `optimizers/status.py` | `map_osqp_status`, `map_clarabel_status` | N/A-Infra | A-33 | **Contractual B2 (solver statuses)**: `test_solver_status.py::test_mapping_all_native_statuses` | 2 (OSQP), 4 (Clarabel) | NOT_IMPLEMENTED |
| SOL-003 | §46 | Interfaz `OptimizationBackend` + `BackendCapabilities` | `optimizers/base.py` | `OptimizationBackend` | N/A-Infra | — | `test_backend_contract.py` | 2 | NOT_IMPLEMENTED |
| SOL-004 | §46–47 | `OSQPBackend` con API nativa | `optimizers/osqp_backend.py` | `OSQPBackend` | QP | SOL-003 | `test_osqp_backend.py` | 2 | NOT_IMPLEMENTED |
| SOL-005 | §46, §48 | `ClarabelBackend` para problemas cónicos, integrado realmente vía router (no backend muerto) | `optimizers/clarabel_backend.py` | `ClarabelBackend` | SOCP | A-32, A-37 | `test_clarabel_backend.py` + TST-017 | 2 (si A-32) / 4 | NOT_IMPLEMENTED |
| SOL-006 | §46 | `MixedIntegerBackend` con SCIP/PySCIPOpt como referencia y backends comerciales opcionales (E-24) | `optimizers/mixed_integer_backend.py` | `MixedIntegerBackend` | MIQP/MIQCP/MISOCP | A-24, MIP-007 | `test_mixed_integer_backend.py` | 4 | NOT_IMPLEMENTED |
| SOL-007 | §46 | `NonConvexBackend` conservado en la arquitectura (interfaz + routing de `NLP_NONCONVEX`); sin algoritmo concreto hasta caso de uso validado (E-25). Máximo alcanzable sin caso de uso: `PARTIAL` | `optimizers/nonconvex_backend.py` | `NonConvexBackend` | NLP No Convexo | A-25 | `test_nonconvex_backend.py::test_no_algorithm_registered_raises` (un problema no convexo sin algoritmo registrado produce error explícito, nunca una solución) | 4 | NOT_IMPLEMENTED |
| SOL-008 | §46 | Routing: QP+lineal→OSQP; SOCP/cónico→Clarabel; MIQP/MIQCP/MISOCP→MIP; no convexo→NonConvex; incompatibles rechazados | `optimizers/router.py` | `SolverRouter.route` | N/A-Infra | OPT-013 | TST-017 | 2 (QP), 4 (resto) | NOT_IMPLEMENTED |
| SOL-009 | §47 | Reutilizar workspace, P, A, factorizaciones; actualizar solo q, l, u; warm start | `optimizers/osqp_backend.py` | `update`, `warm_start` | QP | SOL-004 | `test_osqp_backend.py::test_workspace_reuse` (una sola llamada a setup por grid; resultados = cold solve dentro de tolerancia) | 2 | NOT_IMPLEMENTED |
| SOL-010 | §47 | Sin canonicalización CVXPY en el hot path de producción | `optimizers/`, `frontiers/` | — | N/A-Infra | — | `test_architecture_rules.py::test_no_cvxpy_in_fast_path` (imports prohibidos en módulos FAST_PRODUCTION) | 2 | NOT_IMPLEMENTED |
| SOL-011 | §48 | Clarabel: reutilizar datos/estructura solo donde la API lo permita; capacidades verificadas, no asumidas | `optimizers/clarabel_backend.py` | `ClarabelBackend.capabilities` | N/A-Infra | A-37 | `test_clarabel_backend.py::test_declared_capabilities_are_real` | 4 | NOT_IMPLEMENTED |
| SOL-012 | §67 | Captura de diagnósticos del solver (iteraciones, tiempos setup/update/solve, residuos, WarmStartUsed, versión, estado nativo) | `optimizers/base.py` | `SolveResult` | N/A-Infra | OUT-005 | `test_solver_diagnostics.py` | 2 | NOT_IMPLEMENTED |
| SOL-013 | §45, Bloque 2 | Test de problema inviable: estado INFEASIBLE correcto (solver o pre-check) | `optimizers/`, `constraints/feasibility.py` | — | QP | SOL-002, FEA-007 | **Contractual B2 (infeasible problem)**: `test_infeasible_problem.py` | 2 | NOT_IMPLEMENTED |
| SOL-014 | §45 | Política de verificación cruzada configurable ante estados ambiguos (A-32/A-33) | `optimizers/router.py` | `CrossCheckPolicy` | N/A-Infra | A-32 | `test_cross_check_policy.py` | 2 | NOT_IMPLEMENTED |

## MIP — Exact MIP (§49)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| MIP-001 | §49 | Variables `z∈{0,1}`, `w`; `MinWeight·z ≤ w ≤ MaxWeight·z`; `Σz = TargetPortfolioSize` | `optimizers/formulations/miqp.py` | `build_cardinality_miqp` | MIQP | A-24 | `test_exact_mip.py::test_formulation` (vs enumeración exhaustiva en universo pequeño) | 4 | NOT_IMPLEMENTED |
| MIP-002 | §49 | Solver compatible (MIQP no enviado a OSQP) | `optimizers/mixed_integer_backend.py` | `MixedIntegerBackend` | MIQP | SOL-006, MIP-007 | TST-017 (`test_miqp_not_routed_to_osqp`) | 4 | NOT_IMPLEMENTED |
| MIP-003 | §49 | Modo validación: optimality gap frente a la heurística | `optimizers/`, `candidates/` | `HeuristicGapReport` | MIQP | CAN-001 | `test_exact_mip.py::test_gap_report` | 4 | NOT_IMPLEMENTED |
| MIP-004 | §49 | Calibración del candidate engine con resultados MIP | `candidates/` | `calibration_report` | MIQP + Heurístico | MIP-003 | `test_exact_mip.py::test_calibration_output` | 4 | NOT_IMPLEMENTED |
| MIP-005 | Bloque 4 | No usar EXACT_MIP en el inner loop de producción | `optimizers/router.py` | guarda de familia | N/A-Infra | OPT-001 | `test_router.py::test_exact_mip_not_in_fast_path` | 4 | NOT_IMPLEMENTED |
| MIP-006 | §14, §49 | Variantes MIQCP / MISOCP (con VolLimit/TE) | `optimizers/formulations/miqp.py` | `build_cardinality_misocp` | MIQCP / MISOCP | CON-004, CON-015 | `test_exact_mip.py::test_misocp` | 4 | NOT_IMPLEMENTED |
| MIP-007 | §49 (E-24) | SCIP / PySCIPOpt como backend open-source de referencia; interfaz enchufable para Gurobi/CPLEX/MOSEK opcionales; ningún solver comercial como dependencia obligatoria | `optimizers/mixed_integer_backend.py`, `pyproject.toml` | `MixedIntegerBackend` (registro de implementaciones: `SCIPBackend` + opcionales detectados en tiempo de ejecución) | MIQP/MIQCP/MISOCP | A-24, SOL-006 | `test_mixed_integer_backend.py::test_scip_reference` y `::test_commercial_optional` (el paquete se importa y funciona sin solvers comerciales instalados; un backend comercial ausente se reporta como no disponible, sin error) | 4 | NOT_IMPLEMENTED |

## NCV — Non-convex research y multi-start (§50–51)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| NCV-001 | §50 | Arquitectura NONCONVEX_RESEARCH (familia, clase de problema, routing, interfaz de algoritmos). Los algoritmos concretos (IPOPT, SLSQP, trust-constr, DE, CMA-ES, Basin Hopping) quedan `NOT_IMPLEMENTED` hasta caso de uso validado (E-25) | `optimizers/nonconvex_backend.py` | `NonConvexAlgorithm` registry | NLP No Convexo | A-25 | `test_nonconvex_backend.py::test_registry_empty_by_default` (arquitectura; `PARTIAL` mientras no haya algoritmo) | 4 (arquitectura) | NOT_IMPLEMENTED |
| NCV-002 | §50 | No usar técnicas no convexas si el problema puede mantenerse convexo; preferir siempre reformulación convexa válida (guarda en router) | `optimizers/router.py` | guarda de convexidad | N/A-Infra | OPT-013 | `test_router.py::test_convex_problem_rejected_by_nonconvex_backend` | 4 | NOT_IMPLEMENTED |
| NCV-003 | §51 | Multi-start: current, equal weight, min variance, max alpha, previous optimum, random feasible | `optimizers/nonconvex_backend.py` | `MultiStartGenerator` | NLP No Convexo | FRN-006 | `test_multistart.py` (6 tipos de punto inicial factibles) | Diferido (condicional a caso de uso, E-25) | NOT_IMPLEMENTED |
| NCV-004 | §51 | No afirmar óptimo global desde solución local (flag `IsLocalOptimum`) | `models/solution.py` | `SolveResult.optimality_claim` | N/A-Infra | — | `test_multistart.py::test_no_global_claim` | Diferido (condicional a caso de uso, E-25) | NOT_IMPLEMENTED |
| NCV-005 | Bloque 4 | Algoritmo no convexo concreto para un caso financiero validado y explícito (no existe todavía) | `optimizers/nonconvex_backend.py` | según A-25 | NLP No Convexo | A-25 | Test sobre el problema no convexo acordado | Diferido (condicional a caso de uso, E-25) | NOT_IMPLEMENTED |

## ROB — Robust optimization (§52)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| ROB-001 | §52 | Shrinkage de expected returns | `returns/expected/` | `ShrinkageReturnAdjuster` | Estadístico | RET-001 | `test_return_shrinkage.py` | 4 | NOT_IMPLEMENTED |
| ROB-002 | §52 | Uncertainty set de μ (caja) | `optimizers/formulations/robust.py` | `box_mu_uncertainty` | QP | OPT-004 | `test_robust.py::test_box` (worst-case analítico) | 4 | NOT_IMPLEMENTED |
| ROB-003 | §52 | Uncertainty set de μ (elipsoidal) | `optimizers/formulations/robust.py` | `ellipsoidal_mu_uncertainty` | SOCP | SOL-005 | `test_robust.py::test_ellipsoidal` | 4 | NOT_IMPLEMENTED |
| ROB-004 | §52 | Incertidumbre en Σ (conjunto finito / escalado → SOCP; general → SDP opcional) | `optimizers/formulations/robust.py` | `covariance_uncertainty` | SOCP (SDP opcional) | A-23 | `test_robust.py::test_covariance_set` | 4 | NOT_IMPLEMENTED |
| ROB-005 | §52 | Worst-case utility | `optimizers/formulations/robust.py` | `worst_case_utility` | SOCP | ROB-002..004 | `test_robust.py::test_worst_case_utility` | 4 | NOT_IMPLEMENTED |
| ROB-006 | §82 | Robust Portfolio como estrategia nombrada en outputs | `frontiers/explicit_portfolios.py` | `StrategyID.ROBUST` | QP/SOCP | ROB-005 | `test_named_strategies.py::test_robust_output` | 4 | NOT_IMPLEMENTED |

## SCN — Escenarios (§53–54)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| SCN-001 | §53 | Tipos BASE, BULL, BEAR, STRESS, RATE_UP, RATE_DOWN, EQUITY_CRASH, CREDIT_WIDENING, FX_SHOCK, CUSTOM | `scenarios/definitions.py` | `ScenarioType`, `ScenarioDefinition` | N/A-Datos | A-22 | `test_scenario_definitions.py` | 4 | NOT_IMPLEMENTED |
| SCN-002 | §53 | Cada escenario produce explícitamente `mu_s`, `Sigma_s`, `cost_s`, `constraints_s` | `scenarios/scenario_engine.py` | `ScenarioEngine.build` | Cerrado | SCN-001 | `test_scenario_engine.py::test_outputs_explicit` | 4 | NOT_IMPLEMENTED |
| SCN-003 | §11, §53 | `Sigma_s` validada PSD (diagnóstico + reparación registrada) | `scenarios/scenario_engine.py` | uso de `diagnose_psd` | Álgebra lineal | RSK-008..012 | `test_scenario_engine.py::test_sigma_s_psd` | 4 | NOT_IMPLEMENTED |
| SCN-004 | §54 | ScenarioIndependent | `scenarios/multi_scenario.py` | `MultiScenarioMode.SCENARIO_INDEPENDENT` | QP/SOCP | FRN-001, FRN-002 | `test_multi_scenario.py::test_independent` | 4 | NOT_IMPLEMENTED |
| SCN-005 | §54 | ExpectedScenarioUtility | `optimizers/formulations/multi_scenario.py` | `expected_utility_problem` | QP | SCN-002 | `test_multi_scenario.py::test_expected_utility` (Σ̄ = Σp_sΣ_s) | 4 | NOT_IMPLEMENTED |
| SCN-006 | §54 | WorstCase | `optimizers/formulations/multi_scenario.py` | `worst_case_problem` | SOCP | SOL-005 | `test_multi_scenario.py::test_worst_case` | 4 | NOT_IMPLEMENTED |
| SCN-007 | §54 | BaseWithStressConstraints | `optimizers/formulations/multi_scenario.py` | `base_with_stress_problem` | SOCP | SOL-005 | `test_multi_scenario.py::test_base_with_stress` | 4 | NOT_IMPLEMENTED |
| SCN-008 | Bloque 4 | Outputs específicos por ScenarioID; una cartera produce fronteras distintas por escenario | `outputs/`, `engine.py` | `ScenarioID` en todas las tablas | N/A-Infra | SCN-004 | **B4 DoD**: `tests/integration/test_scenario_specific_outputs.py` | 4 | NOT_IMPLEMENTED |
| SCN-009 | §53 | `constraints_s` por escenario (overrides) | `scenarios/scenario_engine.py` | `ScenarioData.constraints_s` | N/A-Infra | CON-018 | `test_scenario_engine.py::test_constraint_overrides` | 4 | NOT_IMPLEMENTED |
| SCN-010 | §53 | Probabilidades de escenario válidas (≥0, suman 1 donde se requieran) | `scenarios/definitions.py` | validación | N/A-Datos | CFG-010 | `test_scenario_definitions.py::test_probabilities` | 4 | NOT_IMPLEMENTED |

## MET — Métricas vectorizadas (§55)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| MET-001 | §55 | Para `W∈R^{K×N}`: Gross, Variance, Volatility, Sharpe, Turnover, TC, Net, Herfindahl, vectorizados | `metrics/portfolio_metrics.py` | `compute_metrics` | Cerrado | TC-002, TC-006 | `test_metrics.py::test_vectorized_vs_scalar_reference` | 2 | NOT_IMPLEMENTED |
| MET-002 | §55 | Sin bucles Python por FrontierPoint cuando NumPy es aplicable | `metrics/portfolio_metrics.py` | idem | N/A-Infra | MET-001 | `test_metrics.py::test_no_python_loop` (inspección + benchmark K grande) | 2 | NOT_IMPLEMENTED |
| MET-003 | §64 | MarginalRiskContribution y ExpectedReturnContribution por activo | `metrics/contributions.py` | `marginal_risk_contribution`, `return_contribution` | Cerrado | MET-001 | `test_contributions.py` (Σ w_i·MRC_i = σ_p; Σ contribuciones = retorno) | 2 | NOT_IMPLEMENTED |
| MET-004 | §63 | CVaR como métrica (NULL si no hay escenarios de retorno) | `metrics/cvar_metric.py` | `historical_cvar` | Estadístico | A-35 | `test_cvar_metric.py` | 4 | NOT_IMPLEMENTED |
| MET-005 | §63 | NumberAssets, NumberNewAssets, NumberRemovedAssets | `metrics/portfolio_metrics.py` | `composition_counts` | Cerrado | DAT-012, A-08 | `test_metrics.py::test_counts` | 2 | NOT_IMPLEMENTED |
| MET-006 | §20, §55 | Sharpe con `rf` de configuración; NULL si volatilidad ≈ 0 | `metrics/portfolio_metrics.py` | `sharpe` | Cerrado | CFG-003 | `test_metrics.py::test_sharpe_zero_vol` | 2 | NOT_IMPLEMENTED |

## PAR — Paralelización, memoria, determinismo (§56–61)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| PAR-001 | §56 | Unidad de paralelización PortfolioID / PortfolioBatch; nunca una task por FrontierPoint | `parallel/batching.py`, `parallel/executor.py` | `PortfolioBatch`, `BatchExecutor` | N/A-Infra | — | `test_batching.py::test_task_granularity` | 5 | NOT_IMPLEMENTED |
| PAR-002 | §56 | Puntos de una frontera en el mismo worker (reutilización del solver) | `parallel/worker.py` | `WorkerContext` | N/A-Infra | SOL-009 | `test_worker.py::test_frontier_single_worker` | 5 | NOT_IMPLEMENTED |
| PAR-003 | §57 | PortfolioBatchSize configurable + AUTO; evitar scheduling excesivo | `parallel/batching.py` | `resolve_batch_size` | N/A-Infra | CFG-011 | `test_batching.py::test_auto_batch_size` | 5 | NOT_IMPLEMENTED |
| PAR-004 | §58 | Memoria compartida read-only (shared_memory / memmap / worker-local) elegida por benchmark | `parallel/shared_data.py` | `SharedArrayRegistry` | N/A-Infra | BEN-004 | `test_shared_data.py` (arrays read-only; ciclo de vida/unlink; spawn en Windows) | 5 | NOT_IMPLEMENTED |
| PAR-005 | §58 | No transmitir/copiar repetidamente matrices globales | `parallel/` | tasks con índices | N/A-Infra | PAR-004 | `test_shared_data.py::test_task_payload_small` (tamaño de payload de task acotado) | 5 | NOT_IMPLEMENTED |
| PAR-006 | §59 | Regla de submatrices: sin copia `Σ[eligible,eligible]`; índices; `Σ_20×20` solo con composición definida | `candidates/`, `frontiers/` | `CompositionView.sigma_sub` | N/A-Infra | DAT-013 | `tests/performance/test_no_full_sigma_copy.py` (tracemalloc: ninguna asignación O(N²) por cartera) | 3 | NOT_IMPLEMENTED |
| PAR-007 | §60 | Control de oversubscription (threadpoolctl / env vars); baseline 1 hilo por worker | `parallel/threading_control.py` | `limit_blas_threads` | N/A-Infra | — | `test_threading_control.py` | 5 | NOT_IMPLEMENTED |
| PAR-008 | §61 | Resultados reproducibles independientes del orden de finalización | `parallel/determinism.py` | ordenación final | N/A-Infra | — | `tests/integration/test_determinism.py` (1 vs N workers, batch sizes distintos → outputs idénticos byte a byte tras ordenar) | 5 | NOT_IMPLEMENTED |
| PAR-009 | §61, §70 | Derivación determinista de semillas por PortfolioID/ScenarioID | `parallel/determinism.py` | `derive_seed` | N/A-Infra | — | `test_determinism.py::test_seed_derivation_stable` | 3 | NOT_IMPLEMENTED |
| PAR-010 | §61 | SequenceID y tie-breaking determinista | `parallel/determinism.py` | `sequence_id`, `stable_sort_key` | N/A-Infra | — | `test_determinism.py::test_sequence_id` | 3 (tie-break), 5 | NOT_IMPLEMENTED |
| PAR-011 | Bloque 5 | Dynamic scheduling | `parallel/executor.py` | `BatchExecutor` | N/A-Infra | PAR-001 | `test_executor.py::test_dynamic_scheduling` | 5 | NOT_IMPLEMENTED |
| PAR-012 | Bloque 5 | Nº de workers configurable; nunca asumir CPU_COUNT | `config/parallel_config.py` | `ParallelConfig.workers` | N/A-Infra | CFG-011 | `test_parallel_config.py::test_no_implicit_cpu_count` | 5 | NOT_IMPLEMENTED |
| PAR-013 | Bloque 5 | WorkerInitializer / WorkerContext | `parallel/worker.py` | `WorkerInitializer`, `WorkerContext` | N/A-Infra | PAR-004, PAR-007 | `test_worker.py` | 5 | NOT_IMPLEMENTED |

## CCH — Caché (§31, §62)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| CCH-001 | §62 | La caché almacena resultados reales (`CompositionFrontierResult`), no flags | `cache/result_cache.py` | `ResultCache` | N/A-Infra | FRN-004 | `test_result_cache.py::test_stores_results` | 5 | NOT_IMPLEMENTED |
| CCH-002 | §31, Bloque 5 | Clave compuesta: CompositionHash, ScenarioID, ScenarioHash, ConstraintHash, MuSigmaVersion, TransactionCostHash, FrontierConfigHash, ConfigHash (incluye `OptimizationHorizonYears`), MarketDataTimestamp y **CurrentPortfolioStateHash siempre** (E-06) | `cache/keys.py` | `CacheKey` | N/A-Infra | A-06, DAT-016 | `test_cache_keys.py` (cambiar cualquier componente → miss; cambiar un peso actual → miss/invalidación) | 5 | NOT_IMPLEMENTED |
| CCH-003 | §62 | Una cache hit evita realmente el cálculo (0 llamadas al solver) | `cache/result_cache.py` | `get_or_compute` | N/A-Infra | CCH-001 | `test_result_cache.py::test_hit_avoids_solver` | 5 | NOT_IMPLEMENTED |
| CCH-004 | §31 | La caché no depende exclusivamente de CompositionHash | `cache/keys.py` | `CacheKey` | N/A-Infra | CCH-002 | `test_cache_keys.py::test_composition_hash_not_sufficient` | 5 | NOT_IMPLEMENTED |
| CCH-005 | Bloque 5 | Caché por worker con límite de memoria configurable y métricas hit/miss | `cache/result_cache.py` | `ResultCache(max_entries)` | N/A-Infra | CFG-011 | `test_result_cache.py::test_bounded` | 5 | NOT_IMPLEMENTED |

## OUT — Outputs (§63–67)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| OUT-001 | §63 | ScenarioHeader con todos los campos mínimos (+ `TransactionCostOneOff`, E-03) | `outputs/schemas.py`, `outputs/builders.py` | `ScenarioHeaderRow` | N/A-Datos | MET-*, SOL-012 | `test_output_schemas.py::test_scenario_header_fields` | 2 (parcial por campos), 4 (completo) | NOT_IMPLEMENTED |
| OUT-002 | §64 | Weights con todos los campos, sobre la unión current ∪ new | `outputs/schemas.py` | `WeightRow` | N/A-Datos | TC-001, MET-003 | `test_output_schemas.py::test_weights_fields_and_union` | 2 | NOT_IMPLEMENTED |
| OUT-003 | §65 | FrontierPoints con todos los campos (+ `TransactionCostOneOff`, E-03) | `outputs/schemas.py` | `FrontierPointRow` | N/A-Datos | FRN-* | `test_output_schemas.py::test_frontier_points_fields` | 2 | NOT_IMPLEMENTED |
| OUT-004 | §66 | CandidateDiagnostics con todos los campos | `outputs/schemas.py` | `CandidateDiagnosticsRow` | N/A-Datos | CAN-017 | `test_output_schemas.py::test_candidate_diagnostics_fields` | 3 | NOT_IMPLEMENTED |
| OUT-005 | §67 | SolverDiagnostics con todos los campos | `outputs/schemas.py` | `SolverDiagnosticsRow` | N/A-Datos | SOL-012 | `test_output_schemas.py::test_solver_diagnostics_fields` | 2 | NOT_IMPLEMENTED |
| OUT-006 | §24 | Semántica NULL + motivo para métricas no disponibles | `outputs/builders.py` | `Availability` | N/A-Infra | TC-007 | `test_output_nulls.py` | 2 | NOT_IMPLEMENTED |
| OUT-007 | §69, A-21 | ScenarioWeights vs EfficientFrontierWeights | `outputs/builders.py` | builders separados | N/A-Datos | A-21 | `test_output_schemas.py::test_weights_tables_split` | 2 | NOT_IMPLEMENTED |
| OUT-008 | §63, A-20 | Catálogo StrategyID | `models/enums.py` | `StrategyID` | N/A-Infra | A-20 | `test_strategy_ids.py` | 2 | NOT_IMPLEMENTED |
| OUT-009 | Bloque 3 | Tabla CandidateCompositions (contrato de salida del Bloque 3) | `outputs/schemas.py` | `CandidateCompositionRow` | N/A-Datos | CAN-016 | `test_output_schemas.py::test_candidate_compositions` | 3 | NOT_IMPLEMENTED |

## PER — Persistencia y producción (§68–69, Bloque 6)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| PER-001 | §68 | Workers → result batches → Coordinator → staging → SQL Server; workers nunca escriben concurrentemente en DuckDB | `staging/coordinator.py` | `Coordinator` | N/A-Infra | PAR-* | `tests/integration/test_coordinator_single_writer.py` | 6 | NOT_IMPLEMENTED |
| PER-002 | §68 | Staging (DuckDB opcional) | `staging/duckdb_staging.py` | `DuckDBStaging` | N/A-Infra | PER-001 | `test_duckdb_staging.py` | 6 | NOT_IMPLEMENTED |
| PER-003 | §68 | Parquet shards opcionales | `staging/parquet_staging.py` | `ParquetShardWriter` | N/A-Infra | PER-001 | `test_parquet_staging.py` | 6 | NOT_IMPLEMENTED |
| PER-004 | §69 | Tablas SQL Server: OptimizationRun, ScenarioHeader, ScenarioWeights, EfficientFrontierPoints, EfficientFrontierWeights, CandidateDiagnostics, SolverDiagnostics | `persistence/ddl/`, `persistence/sqlserver_writer.py` | DDL + `SQLServerWriter` | N/A-Infra | OUT-*, A-28 | `tests/integration/test_sqlserver_tables.py` (requiere instancia) | 6 | NOT_IMPLEMENTED |
| PER-005 | §69 | BatchRunID como clave de ejecución en todas las tablas | `persistence/` | esquema | N/A-Infra | REP-001 | `test_sqlserver_tables.py::test_batch_run_id` | 6 | NOT_IMPLEMENTED |
| PER-006 | §69 | pyodbc fast_executemany vs BCP según benchmark | `persistence/sqlserver_writer.py` | `FastExecutemanyWriter`, `BCPWriter` | N/A-Infra | BEN-008 | `benchmarks/scripts/sql_write_benchmark.py` (si ambos disponibles) | 6 | NOT_IMPLEMENTED |
| PER-007 | Bloque 6 | Idempotencia: identificar, reintentar, auditar, reproducir | `persistence/run_repository.py` | `RunRepository` | N/A-Infra | REP-001 | `test_idempotency.py` (reintento no duplica filas) | 6 | NOT_IMPLEMENTED |
| PER-008 | Bloque 6 | Errores: DB no disponible, escritura parcial, caída de worker, fallo de solver, cartera inválida; nunca perder todo el batch por una cartera | `engine.py`, `staging/`, `persistence/` | `ErrorRecoveryPolicy` | N/A-Infra | PAR-* | `tests/integration/test_error_recovery.py` (inyección de fallos) | 6 | NOT_IMPLEMENTED |
| PER-009 | Bloque 6 | Structured logging de producción + run metadata persistida | `utils/logging.py`, `persistence/run_repository.py` | — | N/A-Infra | GOV-005, REP-001 | `test_run_metadata_persisted.py` | 6 | NOT_IMPLEMENTED |
| PER-010 | Bloque 6 | Test end-to-end: datos → validación → riesgo → candidatos → escenarios → fronteras → validación → paralelo → outputs → persistencia | `tests/e2e/` | `test_end_to_end.py` | N/A-Infra | todos | `tests/e2e/test_end_to_end.py` | 6 | NOT_IMPLEMENTED |

## REP — Reproducibilidad (§70)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| REP-001 | §70 | RunMetadata: BatchRunID, InputDataTimestamp, ExecutionTimestamp, ConfigSnapshot, ConfigHash, EngineVersion, GitCommit, PythonVersion, NumPyVersion, SolverVersion, CovarianceMethod, ExpectedReturnMethod, RandomSeed | `models/run_metadata.py` | `RunMetadata.capture` | N/A-Infra | CFG-017 | `test_run_metadata.py` (todos los campos poblados o marcados UNAVAILABLE con motivo) | 6 | NOT_IMPLEMENTED |
| REP-002 | §70 | GitCommit (repositorio inicializado con `git init` en el cierre de PROMPT 0; `UNAVAILABLE` explícito solo si no hay commit disponible) | `models/run_metadata.py` | `detect_git_commit` | N/A-Infra | A-26 (ejecutada) | `test_run_metadata.py::test_git_commit` | 6 | NOT_IMPLEMENTED |
| REP-003 | §70 | RandomSeed propagada y usada en todas las fuentes de aleatoriedad | `parallel/determinism.py` | `derive_seed` | N/A-Infra | PAR-009 | `test_reproducibility.py` (dos ejecuciones con misma semilla → outputs idénticos) | 3 | NOT_IMPLEMENTED |
| REP-004 | §70 | Versiones de solvers registradas por ejecución y por diagnóstico | `models/run_metadata.py`, `optimizers/base.py` | `SolverVersion` | N/A-Infra | SOL-012 | `test_run_metadata.py::test_solver_versions` | 2 | NOT_IMPLEMENTED |

## BEN — Benchmark (§71)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| BEN-001 | §71 | Timers: DataLoad, RiskModel, CandidateSelection, SolverSetup, SolverUpdate, SolverSolve, Frontier, Validation, IPC, Staging, Database, PortfolioTotal, BatchTotal | `benchmark/timers.py` | `BenchmarkRecorder.stage` | N/A-Infra | — | `test_benchmark_timers.py` | 2 (subset), 5 (completo) | NOT_IMPLEMENTED |
| BEN-002 | §71 | Estadísticos mean, p50, p95, p99, max, portfolios/s, frontiers/s, solver calls/s | `benchmark/stats.py` | `summarize` | Estadístico | BEN-001 | `test_benchmark_stats.py` (vs cálculo manual) | 2 (subset), 5 | NOT_IMPLEMENTED |
| BEN-003 | Bloque 2 | Comparar cold setup vs workspace reuse vs warm start | `benchmark/suite.py` | `solver_reuse_benchmark` | N/A-Infra | SOL-009 | `benchmarks/scripts/solver_reuse.py` ejecutado; resultados reales guardados con RunMetadata | 2 | NOT_IMPLEMENTED |
| BEN-004 | Bloque 5 | Benchmarks de BatchSize (1, 5, 10, 20, AUTO), workers (1, 2, 4, 8, …) y modo de memoria compartida | `benchmark/suite.py` | `scaling_benchmark` | N/A-Infra | PAR-* | `benchmarks/scripts/scaling.py` ejecutado | 5 | NOT_IMPLEMENTED |
| BEN-005 | Bloque 5 | Baseline de rendimiento y detección de deterioros significativos | `benchmark/regression.py` | `compare_to_baseline` | Estadístico | BEN-002 | `tests/performance/test_performance_regression.py` | 5 | NOT_IMPLEMENTED |
| BEN-006 | §71, CLAUDE.md | No inventar benchmarks: solo resultados de ejecuciones reales con metadatos | `benchmarks/results/` | política | N/A-Infra | REP-001 | Auditoría: cada cifra citada en informes enlaza un fichero de resultados con RunMetadata | 2–6 | NOT_IMPLEMENTED |
| BEN-007 | Bloque 5 | Validar 10, 100 y 1.200 carteras (si los recursos lo permiten) | `benchmarks/scripts/scale_run.py` | — | N/A-Infra | GOV-012 | Ejecución real documentada | 5 | NOT_IMPLEMENTED |
| BEN-008 | Bloque 6 | Benchmark de escritura SQL (fast_executemany vs BCP) | `benchmarks/scripts/sql_write_benchmark.py` | — | N/A-Infra | PER-006 | Ejecución real documentada (si SQL Server y BCP disponibles) | 6 | NOT_IMPLEMENTED |

## TST — Tests e invariantes (§72–76 y tests contractuales de bloques)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| TST-001 | §72 | Unit tests | `tests/unit/` | pytest | N/A-Infra | — | Suite ejecutada en cada gate | 1–6 | NOT_IMPLEMENTED |
| TST-002 | §72 | Integration tests | `tests/integration/` | pytest | N/A-Infra | — | Suite ejecutada desde Bloque 2 | 2–6 | NOT_IMPLEMENTED |
| TST-003 | §72 | Property tests | `tests/property/` | hypothesis | N/A-Infra | A-27 (hypothesis como dependencia de desarrollo del proyecto, sin instalación global) | Propiedades de invariantes (§73) con generadores aleatorios | 1–6 | NOT_IMPLEMENTED |
| TST-004 | §72 | Numerical regression tests (golden files) | `tests/numerical_regression/` | pytest + golden | N/A-Infra | — | Comparación con tolerancias de config | 2–6 | NOT_IMPLEMENTED |
| TST-005 | §72 | Performance regression tests | `tests/performance/` | pytest marker `performance` | N/A-Infra | BEN-005 | Comparación contra baseline | 5 | NOT_IMPLEMENTED |
| TST-006 | §73 | Invariante `Σweights ≈ 1` | `tests/property/test_invariants.py` | — | N/A-Infra | VAL-002 | property test sobre toda solución válida | 2 | NOT_IMPLEMENTED |
| TST-007 | §73 | Invariante `Volatility ≥ 0` | `tests/property/test_invariants.py` | — | N/A-Infra | MET-001 | property test | 2 | NOT_IMPLEMENTED |
| TST-008 | §73 | Invariante `TransactionCost ≥ 0` | `tests/property/test_invariants.py` | — | N/A-Infra | TC-002 | property test | 2 | NOT_IMPLEMENTED |
| TST-009 | §73, Bloque 2 | Con costes positivos: `ExpectedReturnNet ≤ ExpectedReturnGross` | `tests/property/test_invariants.py` | — | N/A-Infra | TC-008 | **Contractual B2** | 2 | NOT_IMPLEMENTED |
| TST-010 | §73, Bloque 2 | `w_new == w_current` ⇒ Turnover = 0 y TC = 0 | `tests/unit/costs/test_zero_trade.py` | — | N/A-Infra | TC-002, TC-006 | **Contractual B2** | 2 | NOT_IMPLEMENTED |
| TST-011 | §74, Bloque 2 | Continuous frontier: todas las soluciones con exactamente el mismo conjunto de activos (`set(Current) == set(Frontier)`) | `tests/integration/test_continuous_frontier_fixed_set.py` | — | N/A-Infra | FRN-001, A-08 | **Contractual B2** | 2 | NOT_IMPLEMENTED |
| TST-012 | §75, Bloque 3 | Global frontier: `len(candidate_compositions) > 1` y `len(unique(CompositionID)) > 1` antes de Pareto | `tests/integration/test_global_frontier_multi_composition.py` | — | N/A-Infra | CAN-001, FRN-002 | **Contractual crítico B3** | 3 | NOT_IMPLEMENTED |
| TST-013 | §76, Bloque 2 | Verificación algebraica del escalado de TC con θ en Risk Aversion | `tests/unit/frontiers/test_net_cost_scaling.py` | — | QP | FRN-010 | **Contractual B2 (transaction-cost scaling)** — ver ARCHITECTURE §9.3 | 2 | NOT_IMPLEMENTED |
| TST-014 | §73, Bloque 3 | Liquidación: current A 10 %/B 90 % → new C 10 %/B 90 %: venta A, compra C, turnover 0,10, coste = Sell_A·0,1 + Buy_C·0,1 | `tests/unit/costs/test_liquidation.py` | — | Cerrado | TC-003, TC-011 | **Contractual B3** | 3 | NOT_IMPLEMENTED |
| TST-015 | Bloque 3 | Mapeo de índices global ↔ eligible ↔ candidate-local | `tests/unit/candidates/test_index_mapping.py` | — | N/A-Infra | DAT-013 | **Contractual B3** | 3 | NOT_IMPLEMENTED |
| TST-016 | §73 | Activo eliminado con costes positivos ⇒ existe venta y coste correspondiente | `tests/property/test_invariants.py` | — | N/A-Infra | TC-003 | property test | 3 | NOT_IMPLEMENTED |
| TST-017 | Bloque 4 | Routing: QP→OSQP; SOCP→Clarabel; MIQP no enviado a OSQP | `tests/unit/optimizers/test_router.py` | — | N/A-Infra | SOL-008 | **Contractual B4** (QP→OSQP ya en B2) | 2, 4 | NOT_IMPLEMENTED |
| TST-018 | Bloque 1 | Tests obligatorios B1: returns, annualization, missing data, duplicados, PSD, near singular, singular, PSD repair, config immutability, transaction-cost input validation | `tests/unit/` | ver RET-010, RET-011, DAT-023, DAT-020, RSK-008, RSK-010, CFG-014, TC-005 | N/A-Infra | — | Todos ejecutados y en verde en el gate B1 | 1 | NOT_IMPLEMENTED |
| TST-019 | Bloque 4 | Max Sharpe sanity, volatility constraints, CVaR constraints, robust optimization, scenario-specific outputs | `tests/` | ver OPT-009..012, ROB-*, SCN-008 | N/A-Infra | — | Todos ejecutados y en verde en el gate B4 | 4 | NOT_IMPLEMENTED |
| TST-020 | Bloque 6 | Test end-to-end completo | `tests/e2e/test_end_to_end.py` | — | N/A-Infra | PER-010 | Ejecutado en gate B6 | 6 | NOT_IMPLEMENTED |
| TST-021 | Bloque 6 | PRODUCTION_READINESS_REPORT.md con tests ejecutados/fallidos, benchmarks reales, pendientes, riesgos, limitaciones, dependencias, solvers | raíz | informe | N/A-Infra | todos | Informe generado a partir de ejecuciones reales | 6 | NOT_IMPLEMENTED |
| TST-022 | §25 (E-03) | Consistencia de horizonte: la frontera neta en base horizonte (`H·μᵀw − TC_one_off`) y en base anualizada (`μᵀw − TC_one_off/H`) dan las mismas soluciones para varios `H`; ningún horizonte literal en fórmulas | `tests/unit/frontiers/test_horizon_consistency.py` | — | QP | CFG-018, TC-009 | **Contractual B2** | 2 | NOT_IMPLEMENTED |

## VIS — Visualización y principio final (§1, §82)

| RequirementID | § | Descripción | Módulo responsable | Clase/función prevista | Tipo matemático | Dependencias | Test de aceptación | Bloque | Estado |
|---|---|---|---|---|---|---|---|---|---|
| VIS-001 | §1, §82 | El motor devuelve un espacio de soluciones, no un único vector | `engine.py`, `outputs/` | `PortfolioEngineResult` | N/A-Infra | FRN-*, OPT-014 | `tests/integration/test_solution_space.py` (≥ 1 frontera con múltiples puntos + estrategias nombradas por cartera) | 2–4 | NOT_IMPLEMENTED |
| VIS-002 | §82, Bloque 3 DoD | Graficar simultáneamente Current Portfolio, Continuous Frontier y Global Candidate Frontier | `outputs/builders.py` | `visualization_dataset` | N/A-Infra | FRN-002, FRN-022 | `tests/integration/test_visualization_dataset.py::test_block3_layers` | 3 | NOT_IMPLEMENTED |
| VIS-003 | §82 | Dataset completo: Current, Continuous, Global, Gross, Net, MinVar, MaxSharpe, MaxReturn, Robust, carteras por escenario | `outputs/builders.py` | `visualization_dataset` | N/A-Infra | VIS-002, SCN-008, ROB-006 | `test_visualization_dataset.py::test_all_layers` | 4 | NOT_IMPLEMENTED |

---

## Matriz de cobertura de secciones de MASTER_SPEC

Cada sección del MASTER_SPEC está asociada al menos a un RequirementID.

| § | Tema | RequirementIDs |
|---|---|---|
| 0 | Propósito / regla de implementado | GOV-010 |
| 1 | Objetivo general | GOV-001, GOV-012, VIS-001 |
| 2 | Prioridades | GOV-002 |
| 3 | Principios de desarrollo | GOV-003..GOV-009, CFG-014 |
| 4 | Parametrización | CFG-001..CFG-018 |
| 5 | Entradas (histórico) | DAT-001..DAT-008 |
| 6 | Universo | DAT-009, DAT-014, TC-005 |
| 7 | Carteras actuales | DAT-010..DAT-012, CON-020 |
| 8 | Retornos esperados | RET-001..RET-008 |
| 9 | Retornos | RET-010..RET-012 |
| 10 | Validación de datos | DAT-020..DAT-031 |
| 11 | Covarianza | RSK-001..RSK-013 |
| 12 | Restricciones básicas | CON-001..CON-022 |
| 13 | Factibilidad previa | FEA-001..FEA-008 |
| 14 | Arquitectura de optimización | OPT-001, OPT-002, MIP-006 |
| 15 | Optimización continua | OPT-003 |
| 16 | Quadratic utility | OPT-004, OPT-005 |
| 17 | Minimum variance | OPT-006 |
| 18 | Maximum return | OPT-007 |
| 19 | Target return | OPT-008 |
| 20 | Maximum Sharpe | OPT-009, MET-006 |
| 21 | Volatility control | OPT-010, CON-004 |
| 22 | CVaR | OPT-011, OPT-012 |
| 23 | Costes de transacción | TC-001..TC-005, TC-011 |
| 24 | Turnover | TC-006, TC-007, CON-005 |
| 25 | Gross y net return | TC-008, TC-009, CFG-018, TST-022 |
| 26 | Candidate engine | CAN-001..CAN-009, CAN-018..CAN-022 |
| 27 | Candidate screening | CAN-010..CAN-012 |
| 28 | Exploration vs exploitation | CAN-008 |
| 29 | Beam search | CAN-007, CAN-015 |
| 30 | Tabu search | CAN-014 |
| 31 | Composition hash / claves | CAN-015, CCH-002, CCH-004, DAT-016 |
| 32 | Continuous frontier | FRN-001 |
| 33 | Global candidate frontier | FRN-002, FRN-003, FRN-017 |
| 34 | Frontera eficiente (múltiples puntos) | FRN-004, FRN-023 |
| 35 | Risk aversion grid | FRN-005..FRN-007 |
| 36 | Target return grid | FRN-008, FRN-009 |
| 37 | Net frontier | FRN-010, FRN-013, TC-010 |
| 38 | Net target return frontier | FRN-011 |
| 39 | Post-cost gross frontier | FRN-012 |
| 40 | Pareto | FRN-014..FRN-016 |
| 41 | Frontier points | FRN-018 |
| 42 | Adaptive frontier | FRN-019 |
| 43 | Deduplicación | FRN-020 |
| 44 | Solution validator | VAL-001..VAL-010 |
| 45 | Estados de solver | SOL-001, SOL-002, SOL-013, SOL-014 |
| 46 | Solver routing | SOL-003..SOL-008 |
| 47 | OSQP fast path | SOL-009, SOL-010 |
| 48 | Clarabel | SOL-005, SOL-011 |
| 49 | Exact MIP | MIP-001..MIP-005, MIP-007, CON-019 |
| 50 | Nonconvex research | NCV-001, NCV-002, NCV-005 |
| 51 | Multi-start | NCV-003, NCV-004 |
| 52 | Robust optimization | ROB-001..ROB-006 |
| 53 | Scenario engine | SCN-001..SCN-003, SCN-009, SCN-010, TC-013 |
| 54 | Optimización multi-escenario | SCN-004..SCN-008 |
| 55 | Métricas vectorizadas | MET-001, MET-002, MET-006 |
| 56 | Paralelización | PAR-001, PAR-002 |
| 57 | Portfolio batching | PAR-003 |
| 58 | Memoria compartida | PAR-004, PAR-005 |
| 59 | Regla de submatrices | PAR-006, DAT-013 |
| 60 | Thread oversubscription | PAR-007 |
| 61 | Determinismo | PAR-008..PAR-010 |
| 62 | Cache | CCH-001, CCH-003, CCH-005, DAT-016 |
| 63 | Output ScenarioHeader | OUT-001, OUT-008, MET-004, MET-005 |
| 64 | Output Weights | OUT-002, MET-003, TC-012 |
| 65 | Output Frontier points | OUT-003 |
| 66 | Output Candidate diagnostics | OUT-004, CAN-017 |
| 67 | Output Solver diagnostics | OUT-005, SOL-012 |
| 68 | Persistencia | PER-001..PER-003 |
| 69 | SQL Server | PER-004..PER-006, OUT-007 |
| 70 | Reproducibilidad | REP-001..REP-004 |
| 71 | Benchmark | BEN-001..BEN-008 |
| 72 | Tests | TST-001..TST-005 |
| 73 | Invariantes financieros | TST-006..TST-010, TST-016 |
| 74 | Test continuous frontier | TST-011 |
| 75 | Test global frontier | TST-012 |
| 76 | Test net frontier | TST-013 |
| 77 | Trazabilidad | este documento, GOV-010 |
| 78 | Regla de implementación | GOV-010 |
| 79 | Regla de no simplificación | GOV-010 |
| 80 | No regresión | GOV-011 |
| 81 | Estructura recomendada | ARCHITECTURE.md §3 |
| 82 | Principio final | VIS-001..VIS-003, OPT-014, ROB-006 |

---

## Registro de cambios de estado

| Fecha | Fase/Bloque | RequirementIDs | Estado anterior → nuevo | Evidencia (tests ejecutados) |
|---|---|---|---|---|
| 2026-09-23 | PROMPT 0 | Todos (310 iniciales) | — → NOT_IMPLEMENTED | Ninguna (fase de diseño; no hay código ni tests) |
| 2026-09-23 | Cierre PROMPT 0 | CFG-018, DAT-016, MIP-007, TST-022 (nuevos); TC-009, RET-002, CCH-002, RSK-004, RSK-005, SOL-006, SOL-007, NCV-001 … NCV-005, REP-002, CFG-006, OUT-001, OUT-003 (redefinidos por decisiones A-03, A-06, A-07, A-24, A-25, A-26) | — → NOT_IMPLEMENTED (nuevos); sin cambio de estado (redefinidos) | Ninguna (fase de diseño; no hay código ni tests) |
| 2026-09-23 | Cierre documental PROMPT 0 | CON-021, CON-022 (nuevos); CON-013, CFG-005, CAN-013 (redefinidos por A-09/E-09) | — → NOT_IMPLEMENTED (nuevos); sin cambio de estado (redefinidos) | Ninguna (fase de diseño; no hay código ni tests) |
