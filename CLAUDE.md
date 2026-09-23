# CLAUDE.md

## Autoridad del proyecto

`MASTER_SPEC.md` es la especificación técnica, matemática y funcional autoritativa del proyecto.

`IMPLEMENTATION_PROMPTS.md` define las fases de implementación autorizadas.

Antes de modificar código, leer siempre, en este orden:

1. `MASTER_SPEC.md`.
2. `ARCHITECTURE.md`, si existe.
3. `TRACEABILITY.md`, si existe.
4. `IMPLEMENTATION_PLAN.md`, si existe.
5. `CHANGELOG.md`, si existe.
6. El bloque relevante de `IMPLEMENTATION_PROMPTS.md`.

## Reglas obligatorias de desarrollo

- Nunca implementar más allá del bloque solicitado actualmente.
- Nunca avanzar automáticamente al siguiente bloque.
- Nunca simplificar silenciosamente un requisito.
- Nunca declarar un requisito como `IMPLEMENTED` solo porque exista una clase, interfaz, configuración, placeholder o stub.
- Un requisito solo puede considerarse `VALIDATED` cuando su implementación y sus tests de aceptación pasan realmente.
- Si un requisito no puede implementarse por completo, marcarlo como `PARTIAL` o `NOT_IMPLEMENTED`.
- Preservar toda funcionalidad previamente validada.
- Ejecutar los tests existentes antes de modificar módulos ya validados.
- Ejecutar la suite de tests relevante después de cada modificación.
- No inventar resultados de benchmarks.
- No afirmar que los tests han pasado si no se ejecutaron realmente.
- No modificar formulaciones matemáticas para facilitar la implementación sin documentarlo y justificarlo.
- Mantener actualizados `TRACEABILITY.md` y `CHANGELOG.md` después de cada bloque de implementación.
- No introducir parámetros financieros, matemáticos u operativos hardcodeados cuando deban proceder de configuración.
- No sustituir silenciosamente Beam Search por Greedy Search, Global Frontier por una sola composición, Net Frontier por Gross Frontier menos costes, SOCP por un QP incompatible, ni MIQP por una heurística.
- Cuando un requisito quede parcial, reflejarlo explícitamente en la trazabilidad y en el informe de la fase.

## Reglas de calidad cuantitativa

- La corrección matemática tiene prioridad sobre la velocidad.
- Toda solución del solver debe pasar una validación independiente.
- Diferenciar `OPTIMAL`, `OPTIMAL_INACCURATE`, `INFEASIBLE`, errores numéricos y límites de iteración/tiempo.
- Los costes de transacción deben incluir compras, ventas y liquidaciones completas de activos que salen de la cartera.
- La frontera neta debe incorporar los costes dentro de la optimización cuando se pretenda representar la verdadera `NET_FRONTIER`.
- El `CandidateEngine` debe partir de la composición actual y generar múltiples composiciones cuando corresponda.
- `CONTINUOUS_FRONTIER` y `GLOBAL_CANDIDATE_FRONTIER` son conceptos distintos y deben implementarse como pipelines distintos.
- No copiar matrices globales grandes por cartera si puede trabajarse con índices y submatrices pequeñas.

## Regla de no regresión

Antes de modificar un módulo validado:

1. Ejecutar tests existentes.
2. Registrar el baseline relevante.
3. Implementar el cambio.
4. Ejecutar nuevamente los tests.
5. Comparar resultados.
6. Corregir cualquier regresión antes de continuar.

## Gate de fase

Al final de cada bloque:

1. Ejecutar los tests aplicables.
2. Resumir los archivos modificados.
3. Resumir los tests realmente ejecutados y sus resultados.
4. Identificar incidencias o limitaciones pendientes.
5. Actualizar `TRACEABILITY.md`.
6. Actualizar `CHANGELOG.md`.
7. Detenerse.

Nunca continuar al siguiente bloque sin una instrucción explícita del usuario.

## Regla de estado

Usar únicamente estados verificables:

- `NOT_IMPLEMENTED`
- `PARTIAL`
- `IMPLEMENTED`
- `VALIDATED`

No utilizar `IMPLEMENTED` si falta código funcional, integración o test de aceptación.

## Control de alcance

Cada sesión de implementación debe comenzar identificando:

- el bloque actual;
- los `RequirementID` afectados;
- los módulos permitidos;
- los módulos fuera de alcance.

Si durante una fase aparece una mejora perteneciente a un bloque posterior, documentarla como pendiente y no implementarla salvo instrucción expresa.
