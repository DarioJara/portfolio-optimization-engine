# BLOQUE 5.3 — Guía de implementación verificable

Estado: **PREPARADO, NO IMPLEMENTADO**. Rama: `block5-shared-memory-cache`, creada desde el merge verificado de B5.2 (`539d4b7e37384921dfbfe2a51a3c52d809ba5517`).

## Contratos de referencia

- `MASTER_SPEC.md` es la autoridad matemática. Revisar `BLOCK_5_IMPLEMENTATION_PLAN.md`, apartado B5.3, y `BLOCK_5_HPC_ARCHITECTURE.md`, apartados 7–9 y 14.
- No cambiar los algoritmos, solvers, tolerancias, estados, restricciones ni `EngineConfig.ConfigHash`.
- No integrar red, SQL Server, Arsys, Oracle, Windmill ni HERMES.
- Mantener la equivalencia T1 del ejecutor secuencial y el paralelo, incluida la prueba Linux real de `forkserver`.
- `cache.enabled=false` por defecto, con desactivación inmediata como vía de rollback.

## Orden de ejecución

1. **Baseline y perfilado**: ejecutar CI completa sobre la rama; registrar Python/OS, 1/2/4 workers, RAM/RSS, tamaño de payload, latencia de inicialización, tipos de carga W0–W5 y limitaciones de la máquina. Los benchmarks serán sintéticos y pequeños. No atribuir beneficios a un mecanismo sin medidas.
2. **Datos compartidos**: `parallel/shared_data.py` con `MarketSnapshot` inmutable y huella de contenido, estrategias `worker-local`, `np.load`/`memmap`, y, solo si se justifica, `multiprocessing.shared_memory`. Evitar serialización de matrices globales por tarea; toda referencia recibida debe verificarse; array no editable; limpieza en éxito/excepción e inventario de huérfanos ante muerte brusca. Las copias defensivas existentes en B1–B4 pueden impedir memoria física realmente compartida: medirlo y documentarlo sin eludir la seguridad matemática.
3. **Elegir por evidencia**: benchmark E4 controla arranque, serialización, tiempo total, RSS/PSS y recursos residuales. Seleccionar modo por defecto únicamente después de medir `spawn` y `forkserver`. Preservar el modo B5.2 como fallback.
4. **Clave de caché**: `cache/keys.py` con los componentes oficiales CCH-001…005, incluidos `CurrentPortfolioStateHash`, restricciones, configuración, datos, composición, estrategia y horizonte conforme a la especificación. La clave debe ser canónica; no deducirla de `CompositionHash` aislado. Probar cambios independientes de cada componente.
5. **Caché acotada**: `cache/result_cache.py`, `get_or_compute`, `max_entries`/`max_bytes`, métricas de hits/misses/evictions. Un hit evita completamente invocar al solver; los resultados cacheados no se comparten como objetos mutables entre carteras.
6. **Integración restringida**: elegir el nivel correcto de caché (worker local vs coordinador) y la coherencia con hashes, pid/worker y ciclo de vida. Nunca usar resultados de otra cartera bajo mandatos, costes, escenarios o fecha diferentes.
7. **Pruebas**: C-06, C-16, C-18 a C-23 de `BLOCK_5_BENCHMARK_PLAN.md`, equivalencia T1, cero llamadas `solve()` al repetir una clave, capacidad y expulsiones, ausencia de fuga y fallback. Incluir Linux `forkserver`, Windows `spawn` si está disponible. Ejecutar suite completa, mypy strict y Ruff al final.

## Puertas de calidad

- PAR-004, PAR-005, CCH-001…005 y CFG-011 solo pasan a `VALIDATED` con evidencia repetible.
- Cualquier divergencia de estado de solver requiere investigación, nunca aceptación automática.
- Evaluar `mu_set` serializable (M-2) sin romper el contrato matemático; si no se implementa, permanecerá `PARTIAL`.
- No empezar B5.4 automáticamente. No realizar pruebas >=1.000 carteras en Arsys ni usar datos reales sin autorización específica.
- Publicar PR en borrador tras auditoría independiente, sin merge automático.

## Riesgos abiertos, fuera de la aceptación B5.3

M-1 (initializer sin corte), D-DET (detección tardía), recuperación y diario quedan en B5.4. L-3 (temporales huérfanos) debe considerarse específicamente al añadir datos compartidos. No extrapolar los resultados de los benchmarks a 22.000 carteras.

Estado objetivo: `BLOCK_5_3_STATUS = PASS / PASS_WITH_CHANGES / BLOCKED` con métricas y pruebas reproducidas.
