# IMPLEMENTATION PROMPTS

# MOTOR DE OPTIMIZACIÓN CUANTITATIVA

---

# PROMPT 0 — ARQUITECTURA, TRAZABILIDAD Y PLAN DE DESARROLLO

Utiliza `MASTER_SPEC.md` como contrato técnico obligatorio del proyecto.

NO programes todavía el motor.

Tu objetivo exclusivo en esta fase es transformar la especificación maestra en un plan de implementación verificable.

## TAREAS

1. Leer completamente `MASTER_SPEC.md`.

2. Identificar todos los requisitos:

* funcionales;
* financieros;
* matemáticos;
* de arquitectura;
* rendimiento;
* paralelización;
* persistencia;
* validación;
* testing.

3. Crear:

`TRACEABILITY.md`.

Cada requisito deberá contener:

RequirementID

Descripción

Módulo responsable

Clase/función prevista

Tipo matemático

Dependencias

Test de aceptación

Estado.

Estados iniciales:

NOT_IMPLEMENTED.

4. Clasificar cada problema como:

QP

SOCP

MIQP

MIQCP

MISOCP

NLP Convexo

NLP No Convexo

Heurístico.

5. Diseñar la estructura definitiva del repositorio.

6. Crear un grafo lógico de dependencias.

7. Identificar contradicciones potenciales.

8. Definir interfaces públicas principales.

9. Definir los contratos de entrada y salida.

10. Crear:

`ARCHITECTURE.md`.

11. Crear:

`IMPLEMENTATION_PLAN.md`.

## REGLAS

No escribir código productivo.

No crear stubs.

No declarar nada como implementado.

No simplificar requisitos.

Si detectas una ambigüedad:

documentarla;

proponer una decisión;

mantenerla visible.

## SALIDA

ARCHITECTURE.md

TRACEABILITY.md

IMPLEMENTATION_PLAN.md.

Finalizar indicando:

PHASE_STATUS = READY_FOR_BLOCK_1

solo si el diseño no contiene contradicciones críticas.

---

# BLOQUE 1 — FOUNDATION: CONFIGURACIÓN, DATOS, RETORNOS Y RIESGO

Utiliza:

MASTER_SPEC.md

ARCHITECTURE.md

TRACEABILITY.md

IMPLEMENTATION_PLAN.md.

Implementa exclusivamente los cimientos del motor.

NO implementar aún:

CandidateEngine;

EfficientFrontier;

ScenarioEngine;

multiprocessing;

SQL Server;

MIQP;

NonConvex;

Beam Search.

## OBJETIVOS

Implementar:

1. configuración centralizada;

2. estructuras de datos;

3. validación de inputs;

4. returns engine;

5. expected-return interface;

6. covariance engine;

7. PSD diagnostics;

8. PSD repair;

9. transaction-cost data model;

10. portfolio-current-state model.

## CONFIGURACIÓN

Crear dataclasses inmutables.

Evitar configuración duplicada.

Una propiedad deberá tener una única fuente de verdad.

## DATA VALIDATION

Cubrir:

NaN;

inf;

duplicados;

precios no positivos;

históricos insuficientes;

stale data;

metadatos incompletos;

pesos inconsistentes.

## RETURNS

Implementar retornos aritméticos.

Annualization configurable.

## COVARIANCE

Implementar inicialmente:

Empirical

Ledoit-Wolf.

Arquitectura preparada para:

OAS

EWMA.

Verificar:

simetría;

PSD;

condition number;

eigenvalues.

## TESTS OBLIGATORIOS

Crear tests para:

returns correctos;

annualization;

missing data;

duplicados;

PSD;

near singular matrix;

singular matrix;

PSD repair;

config immutability;

transaction-cost input validation.

## DEFINITION OF DONE

El bloque no se considera completado mientras algún test falle.

Actualizar TRACEABILITY.md.

Estados posibles:

IMPLEMENTED

VALIDATED.

No avanzar al Bloque 2 automáticamente.

Finalizar con:

BLOCK_1_STATUS = PASS

o:

BLOCK_1_STATUS = FAIL.

---

# BLOQUE 2 — OPTIMIZADOR CONTINUO Y FRONTERA EFICIENTE

Utiliza todos los documentos y código producidos anteriormente.

Ejecuta primero todos los tests del Bloque 1.

Si fallan:

NO continuar.

Implementa exclusivamente optimización continua sobre composición fija.

NO implementar todavía:

CandidateEngine;

Global Candidate Frontier;

Beam Search;

Parallelization;

MIQP;

SQL Server.

## OBJETIVO PRINCIPAL

Partiendo de la cartera actual:

mantener exactamente los mismos activos

y generar múltiples soluciones eficientes modificando únicamente los pesos.

## IMPLEMENTAR

OptimizationBackend

OSQPBackend

ClarabelBackend si es requerido por los problemas incluidos

SolutionValidator

ContinuousFrontierEngine.

## SOLUCIONES

Minimum Variance

Maximum Return

Risk Aversion Grid

Target Return Grid.

Preparar arquitectura para:

Maximum Sharpe;

Volatility Control.

## RISK AVERSION

Usar:

theta = 1 / lambda.

Resolver:

```
minimize
    w'Sigma w - theta * mu'w.
```

Mantener:

P = 2 Sigma

constante.

Actualizar preferentemente:

q.

## TARGET RETURN

Resolver:

minimize

w'Sigma w

subject to:

mu'w >= R_target.

Mantener:

P

A

constantes cuando sea posible.

Actualizar bounds.

## COSTES

Implementar:

Gross Frontier

Net Frontier

Post-Cost Gross Frontier.

La Net Frontier deberá incorporar costes dentro de la optimización.

Para Risk Aversion:

```
minimize
    w'Sigma w - theta * mu'w + theta * TC(w).
```

`TC(w)` en unidades de retorno compatibles con `mu` según MASTER_SPEC §25 (enmienda E-03: `TC(w) = TransactionCostOneOff(w) / OptimizationHorizonYears`). En caso de conflicto prevalece MASTER_SPEC.md.

## LIQUIDACIONES

Incluir correctamente costes de activos que sean vendidos.

En Continuous Frontier normalmente todos los activos permanecen presentes, pero el modelo de costes deberá ser general.

## FRONTIER

Default:

20 puntos.

Configurable.

Implementar:

InitialFrontierPoints

AdaptiveFrontier

DeduplicatePoints.

## SOLUTION VALIDATOR

Validar independientemente:

sum weights;

bounds;

finite values;

todas las restricciones activas.

## TESTS CONTRACTUALES

Test Minimum Variance.

Test Maximum Return.

Test Risk Aversion.

Test Target Return.

Test Gross Frontier.

Test Net Frontier.

Test transaction-cost scaling.

Test CurrentWeight = OptimizedWeight:

Turnover = 0.

TransactionCost = 0.

Test:

ExpectedReturnNet <= ExpectedReturnGross

para costes positivos.

Test composición fija:

set(CurrentAssets) == set(FrontierAssets).

Test solver statuses.

Test infeasible problem.

## BENCHMARK

Medir:

setup;

update;

solve;

frontier total.

Comparar:

cold setup;

workspace reuse;

warm start.

## DEFINITION OF DONE

Debe ser posible producir un dataset:

Volatility

ExpectedReturnGross

ExpectedReturnNet

para graficar la frontera de una cartera.

No avanzar automáticamente al Bloque 3.

Finalizar:

BLOCK_2_STATUS = PASS / FAIL.

---

# BLOQUE 3 — CANDIDATE ENGINE, SUSTITUCIONES Y GLOBAL FRONTIER

Ejecutar primero TODOS los tests de bloques anteriores.

Si falla alguno:

NO continuar.

## OBJETIVO

Construir múltiples composiciones alternativas a partir de la cartera actual.

Contrato obligatorio:

generate_candidate_compositions(...)
-> list[CandidateComposition].

Está prohibido devolver únicamente una composición como implementación final.

## PARTIDA

CandidateEngine debe comenzar desde:

CurrentPortfolioComposition.

No construir una cartera desde cero ignorando la actual.

## IMPLEMENTAR

EligibilityFilter

CandidateScreening

SwapGenerator

LocalSearch

BeamSearch

CompositionHash

CandidateDiagnostics.

## SUSTITUCIONES

Implementar:

1-swap

2-swap.

3-swap opcional configurable.

## SCREENING

Utilizar múltiples señales:

alpha;

risk contribution;

diversification;

covariance;

utility gain;

cost;

liquidity;

sector fit.

Vectorizar el screening siempre que sea razonable.

Evitar loops Python innecesarios sobre cientos de activos.

## EXPLORATION / EXPLOITATION

Parametrizable.

## BEAM SEARCH

BeamWidth configurable.

Mantener múltiples composiciones por nivel.

## CANDIDATE OUTPUT

Por composición:

CompositionID

Assets

ParentComposition

SwapHistory

CandidateScore

EstimatedUtilityGain

EstimatedTurnover

EstimatedTransactionCost.

## GLOBAL CANDIDATE FRONTIER

Para cada composición finalista:

generar su frontera continua.

Después combinar los puntos.

Aplicar Pareto Global.

La salida deberá contener múltiples:

CompositionID.

## DOS FRONTERAS DIFERENTES

CONTINUOUS_FRONTIER

=

activos actuales.

GLOBAL_CANDIDATE_FRONTIER

=

múltiples composiciones.

No confundir ambas.

## COSTES DE ACTIVOS ELIMINADOS

Obligatorio.

Si un activo sale:

w_current > 0

w_new = 0,

contabilizar:

turnover;

sell cost.

## TEST CONTRACTUAL CRÍTICO

Construir dataset sintético donde existan varias composiciones válidas.

Comprobar:

candidate_compositions = generate(...)

assert len(candidate_compositions) > 1.

Después:

global_points = solve_global_frontier(...)

assert len(
unique(global_points.CompositionID)
) > 1.

## TEST DE LIQUIDACIÓN

Current:

A 10%

B 90%.

New:

C 10%

B 90%.

Debe existir:

venta A;

compra C;

turnover correcto;

coste correcto.

## TEST ÍNDICES

Garantizar mapeo correcto entre:

global asset index;

eligible universe index;

candidate-local index.

## PERFORMANCE

No copiar Sigma_700x700 por cartera.

Trabajar con índices.

Extraer:

Sigma_20x20

únicamente cuando la composición esté definida.

## DEFINITION OF DONE

Debe ser posible graficar simultáneamente:

Current Portfolio

Continuous Frontier

Global Candidate Frontier.

No avanzar automáticamente.

Finalizar:

BLOCK_3_STATUS = PASS / FAIL.

---

# BLOQUE 4 — ESCENARIOS, SOCP, ROBUSTEZ Y OPTIMIZACIÓN AVANZADA

Ejecutar tests previos.

## IMPLEMENTAR

ScenarioEngine.

Escenarios iniciales:

BASE

BULL

BEAR

STRESS

RATE_UP

RATE_DOWN

EQUITY_CRASH

CREDIT_WIDENING

FX_SHOCK

CUSTOM.

Cada escenario debe producir explícitamente:

mu_s

Sigma_s

cost_s

constraints_s.

## MULTI-SCENARIO

Implementar arquitectura para:

ScenarioIndependent

ExpectedScenarioUtility

WorstCase

BaseWithStressConstraints.

## MAX SHARPE

Implementar mediante formulación matemáticamente válida.

No tratarlo como QP estándar si no corresponde.

## VOLATILITY CONTROL

Usar SOCP/conic cuando corresponda.

## CLARABEL

Integrarlo realmente a través de SolverRouter.

No crear backend muerto.

## CVAR

Implementar al menos versión convexa sobre escenarios históricos/simulados.

## EXACT_MIP

Implementar inicialmente en modo de validación.

Debe permitir:

cardinality;

min position;

max position.

No utilizarlo en production inner loop.

## NONCONVEX_RESEARCH

Crear arquitectura.

Implementar solo algoritmos que realmente sean necesarios.

## ROBUST OPTIMIZATION

Añadir interfaz para:

return uncertainty;

covariance uncertainty;

worst-case objective.

## TESTS

Routing QP → OSQP.

Routing SOCP → Clarabel.

MIQP no enviado a OSQP.

Scenario-specific outputs.

Max Sharpe sanity tests.

Volatility constraints.

CVaR constraints.

Robust optimization tests.

## DEFINITION OF DONE

Una misma cartera podrá producir diferentes fronteras y soluciones por ScenarioID.

Finalizar:

BLOCK_4_STATUS = PASS / FAIL.

---

# BLOQUE 5 — HPC, PARALELIZACIÓN Y PERFORMANCE

No optimizar código matemáticamente incorrecto.

Ejecutar toda la suite previa primero.

## OBJETIVO

Escalar aproximadamente:

1.200 portfolios

× múltiples escenarios

× múltiples fronteras.

## IMPLEMENTAR

ProcessPoolExecutor

SharedMemory / memmap

PortfolioBatch

WorkerInitializer

WorkerContext

DynamicScheduling

Cache

BenchmarkSuite.

## UNIDAD DE PARALELIZACIÓN

PORTFOLIO_BATCH.

No FrontierPoint.

Todos los puntos de una misma frontera deberán permanecer en el mismo worker cuando esto permita reuse.

## SHARED DATA

Compartir read-only:

mu;

Sigma;

returns;

numeric metadata.

No enviar estas matrices en cada task.

## NO COPIA COMPLETA

No generar Sigma_eligible 700x700 por cartera si no es necesario.

## BATCHING

Benchmark:

BatchSize 1

5

10

20

AUTO.

## WORKERS

Benchmark:

1

2

4

8

...

hasta número razonable de cores.

No asumir automáticamente CPU_COUNT.

## BLAS THREADING

Controlar:

OMP_NUM_THREADS

MKL_NUM_THREADS

OPENBLAS_NUM_THREADS.

## CACHE

Debe almacenar resultados reales.

Cache key deberá incluir:

CompositionHash

ScenarioHash

ConstraintHash

MuSigmaVersion

CostHash

ConfigHash.

Una cache hit debe eliminar solver calls reales.

## DETERMINISMO

SequenceID.

Orden estable de outputs.

## BENCHMARKS

Medir:

candidate engine;

solver setup;

updates;

solve;

metrics;

IPC;

total portfolio;

total batch.

Reportar:

p50

p95

p99

portfolios/sec

solver calls/sec.

## REGRESSION PERFORMANCE

Crear baseline.

Detectar deterioros significativos.

## DEFINITION OF DONE

Validar al menos:

10 portfolios;

100 portfolios;

1.200 portfolios

si los recursos de ejecución disponibles lo permiten.

No inventar benchmarks que no hayan sido ejecutados.

Finalizar:

BLOCK_5_STATUS = PASS / FAIL.

---

# BLOQUE 6 — PERSISTENCIA, AUDITORÍA E INTEGRACIÓN DE PRODUCCIÓN

Ejecutar todos los tests previos.

## OBJETIVO

Convertir el motor validado en una aplicación productiva.

## IMPLEMENTAR

Coordinator

Staging

DuckDB opcional

Parquet shards opcionales

SQL Server Persistence

Structured Logging

Run Metadata

Error Recovery.

## CONCURRENCIA

Workers NO deberán escribir simultáneamente en una única instancia DuckDB.

Arquitectura:

Workers

→ result batches

→ Coordinator

→ staging

→ SQL Server.

## TABLAS

OptimizationRun

ScenarioHeader

ScenarioWeights

EfficientFrontierPoints

EfficientFrontierWeights

CandidateDiagnostics

SolverDiagnostics.

## AUDITORÍA

Guardar:

BatchRunID

InputDataTimestamp

ExecutionTimestamp

ConfigSnapshot

ConfigHash

EngineVersion

GitCommit

SolverVersions

RandomSeed.

## IDEMPOTENCIA

Una ejecución debe poder:

identificarse;

reintentarse;

auditarse;

reproducirse.

## SQL

Benchmark:

pyodbc fast_executemany

vs BCP

si ambos están disponibles.

## ERRORES

Gestionar:

database unavailable;

partial write;

worker crash;

solver failure;

invalid portfolio.

Nunca perder todo el batch por una sola cartera fallida.

## END-TO-END TEST

Input market data

→ validation

→ risk model

→ candidate engine

→ scenarios

→ frontiers

→ validation

→ parallel execution

→ outputs

→ persistence.

## DOCUMENTACIÓN

Actualizar:

README.md

ARCHITECTURE.md

TRACEABILITY.md

CHANGELOG.md.

## FINAL AUDIT

Para cada RequirementID de MASTER_SPEC:

comprobar estado.

No permitir:

IMPLEMENTED

si no existe test.

Objetivo final:

todos los requisitos necesarios para producción deben estar:

VALIDATED.

Los requisitos opcionales pueden quedar:

NOT_IMPLEMENTED

solo si están explícitamente documentados.

## SALIDA FINAL

Generar:

PRODUCTION_READINESS_REPORT.md

incluyendo:

tests ejecutados;

tests fallidos;

benchmarks reales;

funcionalidades pendientes;

riesgos técnicos;

limitaciones conocidas;

dependencias externas;

solvers requeridos.

No declarar:

PRODUCTION_READY

si existen requisitos críticos sin validar.

Finalizar únicamente con uno de:

PRODUCTION_READY

PRODUCTION_READY_WITH_LIMITATIONS

NOT_PRODUCTION_READY.
