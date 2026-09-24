# MASTER SPEC

# MOTOR PROFESIONAL DE OPTIMIZACIÓN CUANTITATIVA DE CARTERAS MULTI-ESCENARIO

## 0. PROPÓSITO DEL DOCUMENTO

Este documento constituye el contrato técnico, matemático, funcional y arquitectónico del proyecto.

Toda implementación deberá respetar esta especificación.

Ningún módulo, algoritmo, restricción, solver o técnica de rendimiento podrá simplificarse silenciosamente.

Si alguna funcionalidad no ha sido implementada todavía deberá marcarse explícitamente como:

`NOT_IMPLEMENTED`

Una clase, interfaz, configuración, placeholder o stub NO implica que el requisito esté implementado.

Un requisito se considerará implementado únicamente cuando exista:

1. código funcional;
2. test de aceptación asociado;
3. validación del resultado;
4. integración con el motor cuando corresponda.

---

# 1. OBJETIVO GENERAL

Construir un motor profesional de optimización cuantitativa de carteras en Python 3.11+ capaz de procesar aproximadamente:

* 1.200 carteras;
* aproximadamente 20 activos por cartera;
* universo global aproximado de 700 activos;
* múltiples escenarios;
* múltiples composiciones candidatas;
* múltiples soluciones por cartera;
* fronteras eficientes;
* optimización bajo restricciones financieras y operativas.

El motor NO debe devolver únicamente un vector óptimo.

Debe construir un espacio de soluciones que permita comparar:

* cartera actual;
* rebalanceo;
* sustitución de activos;
* mínima varianza;
* máximo retorno;
* máximo Sharpe;
* control de volatilidad;
* solución robusta;
* frontera eficiente;
* frontera eficiente neta de costes;
* frontera global con sustitución de activos;
* escenarios de mercado.

---

# 2. PRIORIDADES

El motor deberá priorizar, en este orden:

1. corrección matemática;
2. integridad de restricciones;
3. robustez numérica;
4. calidad económica;
5. reproducibilidad;
6. auditabilidad;
7. mantenibilidad;
8. rendimiento;
9. eficiencia de memoria.

Nunca sacrificar corrección matemática por cumplir una cifra arbitraria de latencia.

---

# 3. PRINCIPIOS DE DESARROLLO

El código debe ser:

* modular;
* limpio;
* parametrizado;
* desacoplado;
* testeable;
* mantenible;
* extensible;
* tipado;
* reproducible;
* auditable.

Evitar:

* scripts monolíticos;
* números financieros hardcodeados;
* estado global mutable;
* dependencias circulares;
* duplicación;
* funciones excesivamente largas;
* stubs disfrazados de funcionalidades completas.

Usar:

* dataclasses;
* type hints;
* Protocol/ABC donde aporte valor;
* dependency injection;
* logging estructurado;
* custom exceptions;
* configuración inmutable.

---

# 4. PARAMETRIZACIÓN

Toda decisión financiera, matemática u operacional deberá proceder de configuración.

Estructuras recomendadas:

EngineConfig

DataConfig

ReturnConfig

RiskConfig

ConstraintConfig

CandidateConfig

ScenarioConfig

FrontierConfig

TransactionCostConfig

SolverConfig

ParallelConfig

PersistenceConfig

BenchmarkConfig.

`EngineConfig` contiene además el parámetro centralizado `OptimizationHorizonYears` (enmienda E-03, §25).

No utilizar constantes como:

0.02

0.15

20

30

0.19

252

1000

como decisiones de negocio o modelo dispersas dentro del código.

---

# 5. ENTRADAS DEL MOTOR

## 5.1 Histórico de mercado

Campos mínimos:

Date

Ticker

AdjustedClose.

Opcionales:

Volume

Bid

Ask

FXRate

MarketCap.

El origen podrá ser:

DataFrame

Parquet

CSV

SQL Server

API

u otro DataSource.

El optimizador no deberá depender directamente del origen físico.

---

# 6. UNIVERSO DE INVERSIÓN

Campos recomendados:

AssetID

Ticker

Sector

Industry

Country

Currency

AssetClass

EligibleFlag

LiquidityFlag

MinWeight

MaxWeight

EstimatedTransactionCost

BuyCost

SellCost

BidAskSpread

ADV

MarketCap

RestrictedAssetFlag.

---

# 7. CARTERAS ACTUALES

Campos:

PortfolioID

AssetID / Ticker

CurrentWeight.

Configuración por PortfolioID:

TargetPortfolioSize

VolatilityLimit

MaxTurnover

InvestmentUniverse

restricciones específicas.

El motor deberá preservar explícitamente la composición actual para poder calcular:

* turnover;
* costes de liquidación;
* activos nuevos;
* activos eliminados;
* distancia respecto a la cartera actual.

---

# 8. RETORNOS ESPERADOS

Soportar:

INTERNAL_ESTIMATION

EXTERNAL_ALPHA.

Métodos internos futuros:

historical mean;

EWMA;

factor models;

Bayesian models;

quantitative signals.

Nunca asumir que media histórica equivale automáticamente a alpha.

---

# 9. RETORNOS

Por defecto utilizar retornos aritméticos:

r[t,i] =
P[t,i] / P[t-1,i] - 1.

Anualización configurable:

mu_annual =
TradingDays * mu_daily

Sigma_annual =
TradingDays * Sigma_daily.

Log returns podrán utilizarse únicamente cuando exista justificación explícita.

---

# 10. VALIDACIÓN DE DATOS

Comprobar:

duplicados;

fechas inconsistentes;

precios <= 0;

NaN;

inf;

históricos insuficientes;

precios stale;

outliers;

metadatos incompletos;

pesos inconsistentes;

límites incompatibles.

No corregir silenciosamente datos.

Registrar cualquier corrección.

---

# 11. MATRIZ DE COVARIANZA

Soportar:

EMPIRICAL

LEDOIT_WOLF

OAS

EWMA.

Antes de optimizar:

verificar finitos;

simetrizar:

Sigma =
(Sigma + Sigma.T) / 2;

calcular eigenvalues;

minimum eigenvalue;

condition number;

comprobar PSD.

Si es necesario:

eigenvalue floor;

nearest PSD

u otro método configurable.

> **Enmienda E-07 (cierre PROMPT 0, 2026-09-23, decisión A-07).** El soporte de `OAS` y `EWMA` sigue siendo requisito de esta sección, pero su implementación se difiere al Bloque 4. En el Bloque 1 solo se implementan `EMPIRICAL` y `LEDOIT_WOLF`; `OAS` y `EWMA` permanecen `NOT_IMPLEMENTED` (diferidos) hasta entonces.

Registrar:

CovarianceMethod

ConditionNumber

OriginalMinEigenvalue

CorrectedMinEigenvalue

CorrectionMagnitude.

---

# 12. RESTRICCIONES BÁSICAS

Soportar:

sum(w) = 1

LongOnly

MinWeight

MaxWeight

VolatilityLimit

MaxTurnover

SectorMin / SectorMax

CountryMin / CountryMax

AssetClassMin / AssetClassMax

CurrencyMin / CurrencyMax

MaximumNewAssets

MaximumSwaps

LiquidityConstraint

RestrictedAssets

CashAllocation

TrackingError

BetaLimit

FactorExposureLimits.

> **Enmienda E-09 (cierre documental PROMPT 0, 2026-09-23, decisión A-09) — activos restringidos ya presentes en cartera.**
>
> Un activo restringido que no está en la cartera actual nunca podrá incorporarse. Para un activo restringido que **ya está** en la cartera actual (`w_current_i > 0`), el tratamiento se rige por la política parametrizable `RestrictedExistingPositionPolicy`:
>
> | Política | Semántica | Límites efectivos del activo restringido `i` con `w_current_i > 0` |
> |---|---|---|
> | `HOLD_OR_REDUCE` | Puede mantener o reducir su peso, incluso hasta cero; nunca incrementarlo. | `0 <= w_i <= min(w_current_i, MaxWeight_i)` |
> | `FREEZE_WEIGHT` | El peso no puede incrementarse ni reducirse durante la optimización. | `w_i = w_current_i` |
> | `FORCE_LIQUIDATE` | La posición debe llevarse a cero, sujeto a factibilidad y restricciones aplicables. | `w_i = 0` (venta completa con su coste, §23) |
>
> Reglas:
>
> * La configuración productiva deberá exigir que la política se seleccione explícitamente cuando existan activos restringidos en cartera; si falta, la ejecución se detiene con error de configuración (no hay valor implícito).
> * En configuraciones de ejemplo y en tests que necesiten un valor concreto se usará `HOLD_OR_REDUCE`.
> * La decisión no podrá hardcodearse dentro del `CandidateEngine` ni del optimizador: ambos consumen límites y elegibilidad efectivos derivados de la configuración.
> * Si la política es incompatible con otras restricciones (p. ej. `FORCE_LIQUIDATE` con `MaxTurnover`, o `FREEZE_WEIGHT` con límites de peso o de grupo), el problema se declara inviable en la factibilidad previa (§13) con la causa registrada; nunca se relaja silenciosamente.

> **Enmienda E-10 (remediación del Bloque 3, 2026-09-24, decisión D-3 de `AUDIT_BLOCK_3.md`) — Existing Non-Buyable Position Policy.**
>
> Un activo **no comprable** es el que no admite nuevas compras: `EligibleFlag` falso, `LiquidityFlag` falso o desconocido cuando la política de banderas desconocidas es conservadora (`EXCLUDE`; `ERROR` detiene la ejecución), o activo fuera del `InvestmentUniverse` de la cartera. Para un activo no comprable **presente en la cartera actual** (`w_current_i > 0`) que no es restringido:
>
> `0 <= w_i <= min(w_current_i, MaxWeight_i)`
>
> Puede mantenerse o reducirse, incluso hasta cero, pero nunca incrementarse; **no** es una liquidación obligatoria. `MinWeight` no fuerza su incremento (como en `HOLD_OR_REDUCE`). Un activo no comprable que **no** está en la cartera no puede entrar (`w_i = 0`).
>
> Reglas:
>
> * La precedencia de `RestrictedExistingPositionPolicy` (E-09) se conserva: un activo restringido se rige por su política (`HOLD_OR_REDUCE`: `w <= w_current`; `FREEZE_WEIGHT`: `w = w_current`; `FORCE_LIQUIDATE`: `w = 0`), que es igual o más estricta que E-10.
> * La regla la consumen de forma coherente el filtro de elegibilidad, el compilador de restricciones, la factibilidad previa, el optimizador continuo, el `CandidateEngine` (screening y estimaciones), la `GLOBAL_CANDIDATE_FRONTIER`, el `SolutionValidator` (que la comprueba desde `w_current`, no desde los límites compilados) y los diagnósticos. No se hardcodea en el `CandidateEngine` ni en el optimizador.
> * Si los topes resultantes hacen imposible el presupuesto, un mínimo de grupo o cualquier otra restricción, el problema se declara inviable en la factibilidad previa (§13) con la causa registrada; nunca se relaja silenciosamente.
> * La restricción de participación en ADV/NAV (`LiquidityConstraint`) la define la aclaración E-11 (A-11), siguiente.

> **Aclaración E-11 (A-11, remediación del Bloque 3, 2026-09-24) — `LiquidityConstraint` ADV/NAV con posición existente protegida.**
>
> `LiquidityCapacity_i = max_adv_participation · ADV_i · liquidation_days / NAV`.
>
> * Posición nueva: `w_i <= LiquidityCapacity_i`. Posición existente: `w_i <= max(w_current_i, LiquidityCapacity_i)`: no se obliga a liquidar una posición que ya supera el límite, pero no puede aumentar por encima de su peso actual. Las precedencias de E-09 (restringidos) y E-10 (no comprables) se conservan.
> * Configuración `[constraints.liquidity]`: `enabled`, `max_adv_participation` (`0 < p <= 1`), `liquidation_days` (`>= 1`) y `fx_rates` explícitos. Sin valores productivos por defecto. `enabled = false` no aplica la restricción; con `enabled = true` ambos parámetros son obligatorios y `NAV > 0`, `ADV_i >= 0` finitos; si falta o es inválido un dato requerido es un error de configuración/datos (nunca se desactiva en silencio).
> * **Unidad de `ADV` (cierre de datos):** `ADV` es exclusivamente el **importe monetario medio negociado por día** (`ADVUnit = NOTIONAL_PER_DAY`). No se admite un `ADV` en títulos, acciones o contratos por día (`SHARES_PER_DAY`, `CONTRACTS_PER_DAY`): se rechaza con un diagnóstico específico y **sin conversión implícita** (convertirlo exigiría un precio y una política de valoración aprobados). Una unidad ausente o desconocida también se rechaza. Cada activo declara unidad, divisa (`ADVCurrency`), procedencia (`ADVSource`) y valor `ADV >= 0` finito. Dimensionalmente `participación · ADV(divisa/día) · días / NAV(divisa)` es un peso adimensional.
> * **Divisas:** con la restricción activada `ADVCurrency` y `NAVCurrency` son **obligatorias**; si faltan ambas o solo una es un error (no se supone que coincidan). Si son iguales se usa `ADV` directamente; si difieren se exige el tipo de cambio explícito del par exacto con la orientación `unidades de NAVCurrency por unidad de ADVCurrency` (`ADV_en_NAV = ADV · FXRate`; p. ej. 0,90 EUR por USD: 100 USD = 90 EUR), positivo, finito y trazable. No se invierten ni infieren pares ni se inventan tipos; si falta, error.
> * **Datos ausentes:** todos los activos de la composición evaluada (incluidos los restringidos, sea cual sea su política E-09) deben tener los datos ADV/NAV; ninguna política E-09/E-10 exime de validarlos. Error de datos, restricción infactible y falta de convergencia del solver son diagnósticos distintos.
> * Es un límite de tamaño de posición: **no** garantiza que una venta pueda ejecutarse y es distinto de una futura restricción de volumen negociable por operación.
> * Incompatibilidades con mínimos, presupuesto o grupos se declaran en la factibilidad previa (§13, `FEA-006`) con la causa registrada.

---

# 13. FACTIBILIDAD PREVIA

Antes de llamar a cualquier solver comprobar reglas deterministas.

Ejemplos:

SUM(MinWeight) <= 1

SUM(MaxWeight) >= 1.

Comprobar incompatibilidades entre:

cardinalidad;

pesos;

sectores;

turnover;

volatilidad;

liquidez.

Si el problema es inviable antes del solver:

no ejecutar el solver;

registrar la causa.

---

# 14. ARQUITECTURA DE OPTIMIZACIÓN

Separar tres familias.

## FAST_PRODUCTION

```
Selección discreta previa
+
optimización continua convexa.
```

## EXACT_MIP

MIQP / MIQCP / MISOCP para validación exacta.

## NONCONVEX_RESEARCH

NLP / global heuristics cuando sea matemáticamente necesario.

---

# 15. OPTIMIZACIÓN CONTINUA

Para una composición fija:

sum(w) = 1

MinWeight <= w_i <= MaxWeight.

Activos no seleccionados no forman parte del vector de variables.

---

# 16. QUADRATIC UTILITY

Permitir:

```
maximize
    mu'w - lambda * w'Sigma w - TransactionCost(w, w_current)
```

`TransactionCost(w, w_current)` se expresa en unidades de retorno compatibles con `mu` (ver §25 y la enmienda E-03).

Utilizar OSQP cuando el problema sea QP con restricciones lineales.

---

# 17. MINIMUM VARIANCE

Resolver:

minimize

w' Sigma w

sujeto a restricciones.

---

# 18. MAXIMUM RETURN

Resolver:

maximize

mu' w

sujeto a restricciones.

---

# 19. TARGET RETURN

Resolver:

minimize

w' Sigma w

subject to:

mu'w >= TargetReturn

más restricciones aplicables.

---

# 20. MAXIMUM SHARPE

Definir:

Sharpe(w) =
(mu-rf)'w
/
sqrt(w'Sigma w).

No formularlo incorrectamente como QP estándar.

Utilizar transformación válida:

SOCP

bisección

quasiconvex optimization

u otro método matemáticamente correcto.

---

# 21. VOLATILITY CONTROL

Permitir:

sqrt(w'Sigma w)
<=
VolatilityLimit.

Utilizar solver cónico cuando corresponda.

---

# 22. CVAR

La arquitectura deberá permitir:

minimize CVaR

o:

CVaR <= MaxCVaR.

---

# 23. COSTES DE TRANSACCIÓN

Definir:

delta_w =
w_new - w_current.

Modelo general:

```
TC(w) =
    SUM_i [
        BuyCost_i  * max(delta_w_i, 0)
      + SellCost_i * max(-delta_w_i, 0)
    ].
```

Debe incluir también activos que desaparecen completamente de la cartera.

Si:

w_current_i > 0

y:

w_new_i = 0,

deberá contabilizarse la venta completa.

No calcular costes únicamente sobre activos presentes en la nueva composición.

---

# 24. TURNOVER

Definir convencionalmente:

Turnover =
0.5 * SUM(abs(delta_w)).

La convención deberá mantenerse consistente con el modelo de costes.

Si no existe cartera actual:

Turnover y TransactionCost deberán marcarse como no disponibles, no inventarse.

---

# 25. GROSS Y NET RETURN

Calcular:

```
ExpectedReturnGross = mu'w.

ExpectedReturnNet = ExpectedReturnGross - TransactionCost.
```

Los costes deberán expresarse en unidades compatibles con retorno.

> **Enmienda E-03 (cierre PROMPT 0, 2026-09-23, decisión A-03) — horizonte de optimización.**
>
> Se define un parámetro explícito y centralizado `OptimizationHorizonYears` (símbolo `H`), con valor por defecto `1.0` declarado en la configuración (única fuente de verdad: `EngineConfig`). Ninguna fórmula podrá contener un horizonte de 1 año implícito o literal.
>
> Expected returns, transaction costs y métricas netas se comparan siempre sobre un horizonte compatible:
>
> ```
> mu, Sigma                    : anualizados (§9).
> TransactionCostOneOff(w)     : coste único del rebalanceo, fracción del NAV (modelo §23).
> TransactionCost(w)           = TransactionCostOneOff(w) / H     (unidades de retorno anualizado, compatibles con mu)
> ExpectedReturnNet            = mu'w - TransactionCost(w)
> ```
>
> Equivalencia en base horizonte: `H * ExpectedReturnNet = H * mu'w - TransactionCostOneOff(w)`. Ambas bases producen las mismas soluciones óptimas; los outputs se publican en base anualizada e incluyen `TransactionCostOneOff` para auditoría. En todas las fórmulas de §16, §20, §37, §38 y §55, `TC(w)` / `TransactionCost` denota el coste en unidades de retorno así definido.

---

# 26. CANDIDATE ENGINE

El CandidateEngine NO deberá devolver únicamente una composición.

Contrato obligatorio:

generate_candidate_compositions(...)
-> list[CandidateComposition].

Debe partir de:

CurrentPortfolioComposition.

Soportar:

1-swap;

2-swap;

3-swap opcional;

local search;

beam search;

exploration vs exploitation;

diversification candidates.

---

# 27. CANDIDATE SCREENING

Utilizar múltiples señales:

ExpectedAlpha

MarginalRiskContribution

DiversificationContribution

CovarianceWithPortfolio

ExpectedUtilityGain

RiskAdjustedReturn

Liquidity

TransactionCost

SectorFit.

No utilizar exclusivamente:

Alpha / Covariance.

---

# 28. EXPLORATION VS EXPLOITATION

Permitir componentes configurables:

alta convicción;

diversificación;

exploration.

Ejemplo orientativo:

70 / 20 / 10

sin hardcoding.

---

# 29. BEAM SEARCH

Mantener las mejores B composiciones por iteración.

BeamWidth configurable.

Evitar duplicados mediante:

CompositionHash.

---

# 30. TABU SEARCH

Opcional.

Evitar ciclos frecuentes de sustitución.

TabuTenure configurable.

---

# 31. COMPOSITION HASH

Debe construirse de forma determinista.

Utilizar los IDs ordenados de los activos.

La caché no deberá depender exclusivamente de CompositionHash.

Cuando se reutilicen resultados, la clave deberá incorporar también:

ScenarioID

ConstraintHash

MuSigmaVersion

TransactionCostHash

FrontierConfigHash

MarketDataTimestamp

CurrentPortfolioStateHash.

> **Enmienda E-06 (cierre PROMPT 0, 2026-09-23, decisión A-06).** `CurrentPortfolioStateHash` se calcula de forma determinista a partir de los pares `(AssetID, CurrentWeight)` de la cartera actual: pares ordenados por `AssetID`, pesos serializados de forma exacta y canónica (sin redondeo), con un algoritmo de hash criptográfico estable. Turnover, transaction costs, restricciones de turnover y Net Frontier dependen de los pesos actuales; por ello la caché deberá invalidarse cuando cambien. La clave de caché incluye también los componentes del Bloque 5 de `IMPLEMENTATION_PROMPTS.md` (`ScenarioHash`, `ConfigHash`).

---

# 32. CONTINUOUS FRONTIER

Debe mantener la composición actual.

Únicamente optimizar pesos.

Responder:

¿Qué conjunto eficiente puede alcanzarse sin cambiar activos?

---

# 33. GLOBAL CANDIDATE FRONTIER

Debe utilizar múltiples composiciones generadas por CandidateEngine.

Pipeline:

Current Portfolio

→ CandidateEngine

→ Composition A

→ Composition B

→ Composition C

→ ...

→ Frontier por composición

→ Global Pareto Envelope.

Responder:

¿Qué conjunto eficiente puede alcanzarse permitiendo selección/sustitución de activos?

---

# 34. FRONTERA EFICIENTE

No devolver únicamente una solución.

Para cada combinación:

PortfolioID

ScenarioID

FrontierType

CompositionID

generar múltiples puntos.

---

# 35. RISK AVERSION GRID

Preferir formulación que mantenga P constante.

Partir de:

maximize

mu'w - lambda w'Sigma w.

Para lambda > 0:

theta = 1/lambda.

Resolver:

```
minimize
    w'Sigma w - theta * mu'w.
```

Así:

P = 2 Sigma

permanece constante.

q(theta) =
-theta mu.

Esto permite:

solver workspace reuse;

q update;

warm start.

Calcular explícitamente:

MinimumVariance

MaximumReturn.

---

# 36. TARGET RETURN GRID

Resolver múltiples:

minimize

w'Sigma w

subject to:

mu'w >= R_target.

Mantener:

P constante;

A constante;

actualizar únicamente el bound cuando sea posible.

---

# 37. NET FRONTIER

La frontera neta NO deberá obtenerse únicamente restando costes después de optimizar la frontera bruta si se pretende representar la verdadera frontera neta.

Para Risk Aversion:

```
max:
    mu'w - TC(w) - lambda * w'Sigma w.
```

Con theta = 1/lambda:

```
min:
    w'Sigma w - theta * mu'w + theta * TC(w).
```

El coste deberá escalar también con theta.

---

# 38. NET TARGET RETURN FRONTIER

Cuando se genere una frontera de retorno objetivo neto:

```
mu'w - TC(w) >= NetTargetReturn.
```

Con costes linealizados, esta restricción puede mantenerse lineal.

---

# 39. POST_COST_GROSS_FRONTIER

También podrá calcularse opcionalmente:

POST_COST_GROSS_FRONTIER.

Representa:

frontera optimizada en términos brutos

y posteriormente evaluada después de costes.

No confundirla con NET_FRONTIER.

---

# 40. PARETO

Calcular:

IsGrossEfficient

IsNetEfficient.

Para frontera neta utilizar:

X = Volatility

Y = ExpectedReturnNet.

No eliminar necesariamente las soluciones dominadas del almacenamiento.

---

# 41. FRONTIER POINTS

Default inicial:

20.

Configurable.

Permitir:

10

20

30

50

u otros valores.

---

# 42. ADAPTIVE FRONTIER

Permitir:

InitialFrontierPoints < FrontierPoints.

Ejemplo:

8 puntos iniciales;

resolver;

detectar huecos/curvatura;

insertar nuevos;

máximo 20.

No declarar AdaptiveFrontier si únicamente se genera el grid completo desde el inicio.

---

# 43. DEDUPLICACIÓN

Detectar portfolios prácticamente idénticos mediante tolerancias en:

weights;

return;

volatility.

---

# 44. SOLUTION VALIDATOR

Toda solución de solver deberá pasar validación independiente.

Comprobar:

sum(weights);

lower bounds;

upper bounds;

finite weights;

volatility;

turnover;

sector constraints;

country constraints;

asset-class constraints;

tracking error;

cualquier restricción activa.

No aceptar automáticamente una solución porque el solver devuelva `SOLVED`.

---

# 45. ESTADOS DE SOLVER

Distinguir:

OPTIMAL

OPTIMAL_INACCURATE

INFEASIBLE

UNBOUNDED

MAX_ITERATIONS

TIME_LIMIT

NUMERICAL_ERROR

INSUFFICIENT_PROGRESS

UNKNOWN.

No confundir fallo numérico con inviabilidad matemática.

---

# 46. SOLVER ROUTING

Crear:

OptimizationBackend.

Backends:

OSQPBackend

ClarabelBackend

MixedIntegerBackend

NonConvexBackend.

Routing:

QP + linear constraints
→ OSQP.

SOCP / conic
→ Clarabel.

MIQP / MIQCP / MISOCP
→ solver compatible.

Nonconvex
→ NonConvexBackend.

---

# 47. OSQP FAST PATH

Utilizar API nativa.

Evitar canonicalización CVXPY en production hot path.

Reutilizar:

workspace;

P;

A;

factorizaciones cuando sea posible.

Actualizar únicamente:

q;

l;

u;

o elementos estrictamente necesarios.

---

# 48. CLARABEL

Utilizar para problemas cónicos.

Reutilizar datos/estructura cuando la API lo permita.

No asumir capacidades incorrectas del solver.

---

# 49. EXACT MIP

Variables:

z_i in {0,1}

w_i.

Restricciones:

MinWeight*z_i <= w_i <= MaxWeight*z_i

SUM(z_i) = TargetPortfolioSize.

Usar solver compatible.

> **Enmienda E-24 (cierre PROMPT 0, 2026-09-23, decisión A-24).** Backend open-source de referencia: **SCIP / PySCIPOpt**. La interfaz de `MixedIntegerBackend` deberá permitir opcionalmente otros backends (Gurobi, CPLEX, MOSEK) si existen licencias. Ningún solver comercial podrá ser dependencia obligatoria.

Principal finalidad:

validar heurísticas;

calcular optimality gap;

calibrar candidate engine.

---

# 50. NONCONVEX RESEARCH

Permitir opcionalmente:

IPOPT

SLSQP

trust-constr

Differential Evolution

CMA-ES

Basin Hopping

etc.

No utilizar estas técnicas si el problema puede mantenerse convexo.

> **Enmienda E-25 (cierre PROMPT 0, 2026-09-23, decisión A-25).** `NONCONVEX_RESEARCH` se conserva en la arquitectura (familia, clase de problema, routing y `NonConvexBackend`), pero no se implementará ningún solver no convexo concreto mientras no exista un caso financiero validado que lo requiera. Se preferirá siempre una reformulación convexa válida cuando exista. Las implementaciones concretas no convexas (y el multi-start de §51) permanecen `NOT_IMPLEMENTED` hasta que exista un caso de uso explícito.

---

# 51. MULTI-START

Para problemas no convexos utilizar múltiples puntos iniciales:

current portfolio;

equal weight;

minimum variance;

maximum alpha;

previous optimum;

random feasible.

No afirmar que una solución local es óptimo global.

---

# 52. ROBUST OPTIMIZATION

Arquitectura preparada para incertidumbre en:

mu

Sigma.

Permitir:

shrinkage de expected returns;

uncertainty sets;

worst-case utility.

---

# 53. SCENARIO ENGINE

Soportar:

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

Cada escenario podrá producir:

mu_s

Sigma_s

TransactionCosts_s

constraints_s.

---

# 54. OPTIMIZACIÓN MULTI-ESCENARIO

Soportar:

ScenarioIndependent

ExpectedScenarioUtility

WorstCase

BaseWithStressConstraints.

---

# 55. MÉTRICAS VECTORIALIZADAS

Para:

W in R^(K×N)

calcular vectorialmente:

ExpectedReturnGross

Variance

Volatility

Sharpe

Turnover

TransactionCost

ExpectedReturnNet

Herfindahl.

Evitar loops Python sobre FrontierPoint cuando pueda utilizarse NumPy.

---

# 56. PARALELIZACIÓN

Unidad principal:

PortfolioID / PortfolioBatch.

No crear una task por FrontierPoint.

Mantener puntos de una frontera en un mismo worker para reutilizar solver.

---

# 57. PORTFOLIO BATCHING

Configurable:

PortfolioBatchSize.

Permitir modo AUTO.

Evitar scheduling excesivo.

---

# 58. MEMORIA COMPARTIDA

Compartir estructuras globales read-only:

mu_global

Sigma_global

returns matrix

numeric metadata.

Utilizar, según benchmark:

multiprocessing.shared_memory

NumPy memmap

worker-local initialization.

Evitar transmitir/copiar repetidamente matrices globales.

---

# 59. REGLA CRÍTICA DE SUBMATRICES

No crear una copia completa:

Sigma[eligible,eligible]

por cartera si eligible puede aproximarse a todo el universo.

Trabajar con índices.

Extraer únicamente submatrices pequeñas cuando exista composición candidata.

Ejemplo:

Sigma_20x20.

---

# 60. THREAD OVERSUBSCRIPTION

Controlar:

OMP_NUM_THREADS

MKL_NUM_THREADS

OPENBLAS_NUM_THREADS

o utilizar `threadpoolctl`.

Benchmark inicial:

1 thread numérico por worker.

---

# 61. DETERMINISMO

Resultados reproducibles independientemente del orden de finalización de workers.

Introducir:

SequenceID.

Ordenar outputs cuando sea necesario.

Deterministic tie-breaking.

---

# 62. CACHE

La caché debe almacenar resultados reales.

No únicamente flags booleanos.

Ejemplo:

CompositionFrontierResult.

Una cache hit debe evitar realmente el cálculo.

Un cambio en los pesos de la cartera actual (`CurrentPortfolioStateHash`, §31) invalida los resultados cacheados de esa cartera.

---

# 63. OUTPUT: SCENARIO HEADER

Campos mínimos:

BatchRunID

PortfolioID

ScenarioID

StrategyID

ExpectedReturnGross

ExpectedReturnNet

Volatility

SharpeRatio

CVaR

Turnover

TransactionCost

HerfindahlIndex

NumberAssets

NumberNewAssets

NumberRemovedAssets

ObjectiveValue

IsGrossEfficient

IsNetEfficient

IsValidSolution

SolverStatus

SolverName

SolverIterations

SolverTime

TotalOptimizationTime.

---

# 64. OUTPUT: WEIGHTS

Campos:

BatchRunID

PortfolioID

ScenarioID

StrategyID

FrontierPointID

CompositionID

Ticker

CurrentWeight

OptimizedWeight

WeightChange

IsNewAsset

IsRemovedAsset

TransactionCostAsset

MarginalRiskContribution

ExpectedReturnContribution.

---

# 65. OUTPUT: FRONTIER POINTS

Campos:

PortfolioID

ScenarioID

FrontierType

FrontierPointID

CompositionID

TargetReturn

Theta

ExpectedReturnGross

ExpectedReturnNet

Volatility

SharpeRatio

Turnover

TransactionCost

IsGrossEfficient

IsNetEfficient

IsValidSolution.

---

# 66. OUTPUT: CANDIDATE DIAGNOSTICS

Campos:

PortfolioID

Ticker

CandidateType

CandidateScore

AlphaScore

DiversificationScore

MarginalUtility

LiquidityScore

TransactionCostEstimate

SelectedForOptimization

RejectionReason.

---

# 67. OUTPUT: SOLVER DIAGNOSTICS

Campos:

PortfolioID

ScenarioID

CompositionID

FrontierPointID

SolverName

SolverVersion

SolverStatus

Iterations

SetupTime

UpdateTime

SolveTime

ObjectiveValue

PrimalResidual

DualResidual

MaximumConstraintViolation

WarmStartUsed.

---

# 68. PERSISTENCIA

Workers no deberán escribir concurrentemente sobre una misma instancia DuckDB.

Arquitectura:

Workers

→ Result batches

→ Coordinator

→ staging

→ SQL Server.

Opcional:

Parquet shards.

---

# 69. SQL SERVER

Tablas sugeridas:

OptimizationRun

ScenarioHeader

ScenarioWeights

EfficientFrontierPoints

EfficientFrontierWeights

CandidateDiagnostics

SolverDiagnostics.

Usar:

BatchRunID.

Persistencia:

pyodbc fast_executemany

o BCP

según benchmark.

---

# 70. REPRODUCIBILIDAD

Guardar:

BatchRunID

InputDataTimestamp

ExecutionTimestamp

ConfigSnapshot

ConfigHash

EngineVersion

GitCommit

PythonVersion

NumPyVersion

SolverVersion

CovarianceMethod

ExpectedReturnMethod

RandomSeed.

---

# 71. BENCHMARK

Medir:

DataLoadTime

RiskModelTime

CandidateSelectionTime

SolverSetupTime

SolverUpdateTime

SolverSolveTime

FrontierTime

ValidationTime

IPC

StagingTime

DatabaseTime

PortfolioTotalTime

BatchTotalTime.

Reportar:

mean

p50

p95

p99

max

portfolios/second

frontiers/second

solver calls/second.

---

# 72. TESTS

Crear:

unit tests;

integration tests;

property tests;

numerical regression tests;

performance regression tests.

---

# 73. INVARIANTES FINANCIEROS

Como mínimo:

SUM(weights) ≈ 1.

Volatility >= 0.

TransactionCost >= 0.

Con costes positivos:

ExpectedReturnNet <= ExpectedReturnGross.

Si:

w_new == w_current,

entonces:

Turnover = 0

TransactionCost = 0.

Si un activo es eliminado:

w_current_i > 0

w_new_i = 0,

entonces deberá existir venta y coste correspondiente cuando los costes sean positivos.

---

# 74. TEST CONTINUOUS FRONTIER

Con composición actual fija:

todas las soluciones deberán contener exactamente el mismo conjunto de activos.

---

# 75. TEST GLOBAL FRONTIER

Para un ejemplo diseñado con varias alternativas:

CandidateEngine deberá generar:

len(candidate_compositions) > 1.

La Global Candidate Frontier deberá contener más de un CompositionID antes del filtrado Pareto cuando existan alternativas válidas.

---

# 76. TEST NET FRONTIER

Verificar algebraicamente que:

TransactionCost

queda correctamente escalado en la formulación Risk Aversion.

---

# 77. TRAZABILIDAD

Mantener:

TRACEABILITY.md.

Cada RequirementID deberá asociarse a:

módulo;

clase/función;

test;

estado.

Estados permitidos:

NOT_IMPLEMENTED

PARTIAL

IMPLEMENTED

VALIDATED.

---

# 78. REGLA DE IMPLEMENTACIÓN

Un requisito NO puede pasar a IMPLEMENTED si:

solo existe su configuración;

solo existe una interfaz;

solo existe un stub;

solo existe documentación;

el código todavía utiliza una aproximación distinta;

no existe test.

---

# 79. REGLA DE NO SIMPLIFICACIÓN

No sustituir silenciosamente:

Beam Search

por Greedy Search;

Global Frontier

por una única composición;

Net Frontier

por Gross Frontier menos costes;

SOCP

por QP incompatible;

MIQP

por heurística,

sin declarar explícitamente:

PARTIAL_IMPLEMENTATION.

---

# 80. NO REGRESIÓN

Antes de modificar un módulo:

ejecutar tests existentes;

registrar baseline;

implementar;

ejecutar nuevamente todos los tests;

comparar resultados.

No deteriorar funcionalidad previamente validada.

---

# 81. ESTRUCTURA RECOMENDADA

portfolio_engine/

```
config/

models/

data/

returns/

risk/

constraints/

scenarios/

candidates/

frontiers/

optimizers/

    base.py

    osqp_backend.py

    clarabel_backend.py

    mixed_integer_backend.py

    nonconvex_backend.py

validation/

parallel/

staging/

persistence/

benchmark/

utils/
```

tests/

benchmarks/

MASTER_SPEC.md

TRACEABILITY.md

CHANGELOG.md

README.md.

---

# 82. PRINCIPIO FINAL

El motor deberá generar un espacio de alternativas financieras válidas, no ocultarlo prematuramente mediante una única solución.

El resultado debe permitir visualizar:

Current Portfolio

Continuous Efficient Frontier

Global Candidate Frontier

Gross Frontier

Net Frontier

Minimum Variance

Maximum Sharpe

Maximum Return

Robust Portfolio

Scenario-specific portfolios.

El objetivo final es obtener un motor cuantitativo rápido, matemáticamente sólido, trazable y extensible cuya velocidad sea consecuencia de una arquitectura correcta y de benchmarks reales, no de simplificaciones silenciosas.

---

# ANEXO A. REGISTRO DE ENMIENDAS

| ID | Fecha | Origen | Secciones | Naturaleza | Descripción |
|---|---|---|---|---|---|
| F-01 | 2026-09-23 | A-01 (cierre PROMPT 0) | §23 | Corrección de formato | El operador entre los términos de compra y venta, corrompido como `*`, se restaura como `+`. Sin cambio de significado. |
| F-02 | 2026-09-23 | A-02 (cierre PROMPT 0) | §16, §25, §35, §37, §38 | Corrección de formato | Operadores `-`, `+`, `>=` convertidos por Markdown en encabezados `##`, subrayados `---`, líneas sueltas o citas `>` se restauran como ecuaciones en bloques de código. Sin cambio de significado. |
| F-03 | 2026-09-23 | Revisión global de fórmulas (cierre PROMPT 0) | §14 | Corrección de formato | `Selección discreta previa * optimización continua convexa`: el `*` suelto (viñeta Markdown) se restaura como `+`. Sin cambio de significado. |
| E-03 | 2026-09-23 | A-03 | §4, §16, §25 | Enmienda funcional aprobada | Parámetro centralizado `OptimizationHorizonYears` (defecto 1.0 en configuración) y compatibilidad de horizonte entre retornos, costes y métricas netas. |
| E-06 | 2026-09-23 | A-06 | §31, §62 | Enmienda funcional aprobada | `CurrentPortfolioStateHash` en la clave de caché e invalidación ante cambios de pesos actuales. |
| E-07 | 2026-09-23 | A-07 | §11 | Planificación aprobada | OAS/EWMA diferidos al Bloque 4. |
| E-09 | 2026-09-23 | A-09 | §12 | Enmienda funcional aprobada | Política `RestrictedExistingPositionPolicy` (`HOLD_OR_REDUCE`, `FREEZE_WEIGHT`, `FORCE_LIQUIDATE`) para activos restringidos ya en cartera; selección explícita obligatoria en producción; `HOLD_OR_REDUCE` en ejemplos y tests. |
| E-10 | 2026-09-24 | D-3 (`AUDIT_BLOCK_3.md`) | §12 | Enmienda funcional aprobada | Existing Non-Buyable Position Policy: un activo mantenido y no comprable (`EligibleFlag`/`LiquidityFlag` falsos o desconocidos con política conservadora, o fuera del `InvestmentUniverse`) cumple `0 <= w <= min(w_current, MaxWeight)`; puede mantenerse o reducirse, nunca incrementarse; no es liquidación obligatoria. Conserva la precedencia de E-09. |
| E-11 | 2026-09-24 | A-11 (aclaración) | §12, §13 | Enmienda funcional aprobada | `LiquidityCapacity = max_adv_participation·ADV·liquidation_days/NAV`; posición nueva `w <= capacidad`, existente `w <= max(w_current, capacidad)` (protegida, sin liquidación forzosa); `[constraints.liquidity]` sin valores por defecto (`enabled`, `max_adv_participation`, `liquidation_days`, `fx_rates`); `ADV` = importe monetario diario (`ADVUnit = NOTIONAL_PER_DAY`; títulos/contratos se rechazan sin conversión); `ADVCurrency` y `NAVCurrency` obligatorias (nunca se supone igualdad por ausencia); FX = unidades de NAVCurrency por unidad de ADVCurrency, par exacto explícito; datos requeridos también para activos restringidos; no garantiza ejecutabilidad de ventas. Conserva E-09 y E-10. |
| F-04 | 2026-09-23 | Cierre documental PROMPT 0 | `IMPLEMENTATION_PROMPTS.md`, Bloque 2 (RISK AVERSION y COSTES) | Corrección de formato en documento subordinado | Operadores perdidos por Markdown (`##`, `*` sueltos) restaurados: `minimize w'Sigma w - theta * mu'w` y `minimize w'Sigma w - theta * mu'w + theta * TC(w)`, coherentes con §35 y §37. Sin cambio de significado. |
| E-24 | 2026-09-23 | A-24 | §49 | Enmienda funcional aprobada | SCIP/PySCIPOpt como backend MIP de referencia; comerciales opcionales. |
| E-25 | 2026-09-23 | A-25 | §50, §51 | Enmienda funcional aprobada | NONCONVEX_RESEARCH solo arquitectura hasta caso de uso validado. |

Revisión global de fórmulas (cierre PROMPT 0): se revisaron todas las expresiones de §9, §11–13, §15–25, §31, §35–38, §40, §49, §55 y §73. Solo §14, §16, §23, §25, §35, §37 y §38 presentaban corrupción de formato; el resto es correcto.
