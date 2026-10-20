# Solicitud de auditoría independiente — Bloque 5.3

Rama: `block5-shared-memory-cache` (base `main` = `539d4b7`). **Solicitud original (la auditoría se realizó después: `AUDIT_BLOCK_5_3.md`, `PASS_WITH_CHANGES`; remediación en `CHANGELOG.md`).** Este documento la
solicitó; hasta que un auditor independiente emita su informe (`AUDIT_BLOCK_5_3.md`), la implementación no debe declararse
apta para integrar. Existe el PR #7 en borrador; no hay merge ni tag.

## 1. Alcance a auditar

Contratos: `BLOCK_5_3_EXECUTION_BRIEF.md`, `BLOCK_5_IMPLEMENTATION_PLAN.md`, `BLOCK_5_HPC_ARCHITECTURE.md` §7-9,
`ARCHITECTURE.md` §3.8, `MASTER_SPEC.md` (no modificado).

Código: `portfolio_engine/parallel/{shared_data,operation_cache,task,worker,executor,workload}.py`,
`portfolio_engine/cache/{keys,result_cache}.py`, `portfolio_engine/config/{parallel_config.py,default_parallel.toml}`.
Tests: `tests/unit/cache/`, `tests/unit/parallel/{test_shared_data,test_operation_cache}.py`,
`tests/integration/test_shared_data_equivalence.py`. Benchmark: `benchmarks/scripts/shared_data_cache.py` y
`benchmarks/results/shared_data_cache_20261020T100159Z.json`.

Requisitos que se proponen como `VALIDATED`: PAR-004, PAR-005, CCH-001…CCH-005, CFG-011. Siguen `PARTIAL`: PAR-013, BEN-004.

## 2. Afirmaciones que el auditor debe intentar refutar

1. **Equivalencia T1**: los tres modos de datos compartidos y la caché activada producen resultados equivalentes (mismas
   tolerancias que B1–B4, sin comparar tiempos, PID ni trazas) a la ejecución secuencial de referencia.
2. **Sin modificación matemática**: ningún solver, tolerancia, estado, restricción ni `ConfigHash` cambió; `MASTER_SPEC.md` intacto.
3. **Integridad**: una cabecera, manifiesto o *buffer* alterado se rechaza antes de deserializar (SHA-256).
4. **Referencia constante**: lo que viaja por el pipe de arranque es < 2 KB y no crece con el universo.
5. **Limpieza**: no quedan directorios `portfolio_engine_run_*` ni segmentos tras éxito, excepción o caída de worker.
6. **Clave completa**: cambiar cualquiera de los 10 componentes oficiales, `portfolio_id`, operación o datos cambia la clave;
   `CurrentPortfolioStateHash` siempre forma parte.
7. **Un acierto no resuelve**: 0 llamadas a cualquier backend/HiGHS; el resultado es una copia nueva (no mutable compartida).
8. **Nunca se cachea** un estado no definitivo, un resultado con límite de tiempo de pared ni `EXACT_MIP`.
9. **Límites**: `max_entries` y `max_bytes` se respetan; métricas coherentes.
10. **Desactivada por defecto** (`enabled = false`) y sin efecto observable cuando está desactivada.
11. Las cifras de `CHANGELOG.md` (B5.3) proceden del JSON de resultados y de la ejecución real; no hay extrapolación a producción.

## 3. Superficies de ataque sugeridas

- Colisiones de clave: dos entradas distintas con el mismo digest (p. ej. `ConstraintHash` por entradas, `snapshot_key`).
- Mutación de arrays «de solo lectura» desde el worker; vistas que sobreviven al cierre del `mmap`/segmento.
- Carreras en limpieza (Windows: ficheros abiertos; Linux: `/dev/shm`); reutilización de nombres de segmento.
- `inventory_orphans`/`remove_orphans`: ¿puede borrar recursos de un proceso vivo (reciclado de PID)?
- Resultados cacheados tras un fallo parcial o con estados mezclados; copias profundas vs. superficiales.
- Ruta de `ELLIPSOIDAL` en `STRATEGY_ROBUST` (no expresable: M-2 parcial).
- Compatibilidad `spawn` (Windows) / `forkserver` y `spawn` (Linux).

## 4. Reproducción

```bash
python -m pytest -q -p no:cacheprovider
python -m mypy --strict portfolio_engine
python -m ruff check .
python -m pytest -q tests/integration/test_shared_data_equivalence.py tests/unit/parallel/test_shared_data.py tests/unit/cache tests/unit/parallel/test_operation_cache.py
python benchmarks/scripts/shared_data_cache.py --universe 50 500 --workers 1 2 4 --repetitions 2
```

(No ejecutar `ruff format .` en la raíz: reescribe los bloques de código de los `.md`; usar `ruff format --check`.)

Evidencia ya registrada: `CHANGELOG.md` (Bloque 5.3) y `TRACEABILITY.md`.

## 5. Limitaciones conocidas (declaradas, no ocultas)

- Sin ventaja de arranque con datos compartidos; solo ahorro de memoria privada ≈ tamaño de los datos por worker.
- La caché no acierta entre carteras distintas (diseño) ni en workers de un solo uso.
- `mu_set` `ELLIPSOIDAL` pendiente (M-2). Abiertos para B5.4: M-1, D-DET, L-1, L-2, L-4.
- Dos pruebas preexistentes de B4 (`tests/unit/scenarios/test_multi_scenario.py`) fallan de forma intermitente en Linux:
  véase el apartado «Linux» del `CHANGELOG.md`. No se modificaron.
- `.github/workflows/b53-branch-ci.yml` era temporal y se eliminó en la remediación.
- Sin cargas ≥ 1.000 carteras ni acceso a SQL Server/Arsys (D-12).

## 6. Veredictos esperados

`PASS` / `PASS_WITH_CHANGES` / `BLOCKED`, con hallazgos clasificados por severidad y requisito afectado.
