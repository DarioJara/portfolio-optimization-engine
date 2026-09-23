# Guía de uso en Claude Code / Cowork

## Archivos de gobierno

- `MASTER_SPEC.md`: contrato técnico, matemático y funcional permanente.
- `IMPLEMENTATION_PROMPTS.md`: Prompt 0 y Bloques 1–6 de implementación.
- `CLAUDE.md`: reglas permanentes que Claude debe respetar en el repositorio.

## Primera ejecución

En Claude Code, con esta carpeta seleccionada como proyecto local, enviar:

```text
Lee completamente:

- CLAUDE.md
- MASTER_SPEC.md
- IMPLEMENTATION_PROMPTS.md

Ejecuta exclusivamente:

"PROMPT 0 — ARQUITECTURA, TRAZABILIDAD Y PLAN DE DESARROLLO"

contenido en IMPLEMENTATION_PROMPTS.md.

No implementes todavía código productivo.

Debes crear exactamente:

- ARCHITECTURE.md
- TRACEABILITY.md
- IMPLEMENTATION_PLAN.md

Verifica que los requisitos de MASTER_SPEC.md queden trazados y clasificados.

No avances al Bloque 1.

Cuando termines, detente e indica:

PHASE_STATUS = READY_FOR_BLOCK_1

o explica por qué todavía no está preparado.
```

## Secuencia posterior

Ejecutar los bloques de uno en uno:

1. Prompt 0 — Arquitectura y trazabilidad.
2. Bloque 1 — Foundation.
3. Bloque 2 — Optimizador continuo y frontera eficiente.
4. Bloque 3 — Candidate Engine y Global Frontier.
5. Bloque 4 — Escenarios y optimización avanzada.
6. Bloque 5 — HPC, paralelización y performance.
7. Bloque 6 — Persistencia e integración de producción.

No avanzar si el bloque actual termina en `FAIL`.

## Git recomendado

Después de cada bloque validado:

```bash
git add .
git commit -m "Block N - validated"
```

La combinación de especificación, trazabilidad, tests y Git debe actuar como memoria persistente del proyecto.
