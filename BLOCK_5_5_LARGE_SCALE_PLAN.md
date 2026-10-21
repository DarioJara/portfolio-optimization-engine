# BLOCK_5_5_LARGE_SCALE_PLAN — Estimación de duración, recursos y coste de las pruebas a gran escala (1.000 / 1.200 / 5.000 / 22.000 carteras)

Fecha: 2026-10-21. Rama `block5-benchmarks-final-audit`. **Documento de preparación: no se ha ejecutado ninguna carga de ≥ 1.000 carteras** (D-12,
`BLOCK_5_BENCHMARK_PLAN.md` §3). Las cifras son **aritmética sobre mediciones concretas** (`scale_run.py estimate`, `portfolio_engine.benchmark.scaling.project_capacity`),
con su factor de extrapolación declarado; **no sustituyen a la ejecución**. Los JSON de cada estimación están en `benchmarks/results/capacity_estimate_*.json`
(`metadata.executed = false`).

## 1. Qué hay medido y de dónde sale cada entrada

| Entrada | Valor medido | Fuente | Confianza |
|---|---|---|---|
| Coste secuencial por cartera, universo de 8 activos | `ENG-MIX-BASE`: 0,18 s (fase rápida) – 0,24 s (mediana) – 0,31 s (fase lenta) | `scaling_ENG-MIX-BASE_100portfolios_rates_*` y `…_10-100portfolios_*` (100 carteras; mismo trabajo, ×1,67 de diferencia entre campañas) | Media: 100 carteras, 3–5 repeticiones |
| Coste por clase con 20 posiciones y universo 700 | W0 0,03–0,06 s; W1 **3,27 s**; W3 0,03 s; W4 0,013–0,021 s | `scaling_classes_3portfolios_universe700_*` | **Baja**: 3 carteras por clase, 2 repeticiones; W2 y W5 sin medir a esta dimensión |
| Eficiencia en régimen estacionario (descontado el arranque) | 1–2 workers 0,90–1,0; **4 workers 0,64–0,90**; **8 workers 0,59 (una sola medición)** | `scaling_ENG-MIX-BASE_10-100portfolios_*` y `…_rates_*` (solo celdas de ≥ 100 carteras) | Media-baja: una mezcla, 100 carteras, dos campañas |
| Arranque del pool `spawn` | mediana 7–8 s; p95 21 s; máx. 30,5 s (4 workers, memoria saturada) | más de 80 arranques medidos en `scaling_*` | Media |
| Memoria | worker RSS 163–198 MB (USS 119–135 MB); coordinador 173–283 MB; pico 880 MB (4 workers), 1,5 GB (8) | `scaling_*` | Media; **el coordinador no se midió por encima de 300 tareas** |
| Diario | +0,12 s y ≈ 1 % sobre 12 carteras | `recovery_12portfolios_*` | Baja |

## 2. Proyección (duración, horas-núcleo y memoria)

`Óptimo / central / pesimista` combinan los rangos medidos de coste (mín./mediana/máx. de repeticiones) y de eficiencia; la columna **«Pesimista × 1,67»** añade la
variación de fase de la máquina observada con el *mismo* trabajo (29,8 s frente a 17,8 s). **Ningún intervalo cubre el riesgo de extrapolación** (×333 a ×7.333 sobre
3 carteras por clase en las filas «U=700»). En la primera tabla (BASE medido directamente) el rango de coste ya agrupa las dos campañas (fase rápida y lenta), así que la columna ×1,67 es
conservadora (cuenta dos veces esa variación).

#### BASE (8 activos, medido directamente)

| Objetivo | Workers | Duración h (óptimo / central / pesimista) | Pesimista × 1,67 | Horas-núcleo (central) | Memoria pico (GB) | Factor de extrapolación |
|---|---|---|---|---|---|---|
| 1000 | 1 | 0.05 / 0.07 / 0.10 | 0.16 | 0.07 | 0.47 | ×10 |
| 1200 | 1 | 0.06 / 0.09 / 0.12 | 0.19 | 0.09 | 0.47 | ×12 |
| 5000 | 1 | 0.26 / 0.36 / 0.48 | 0.80 | 0.36 | 0.47 | ×50 |
| 22000 | 1 | 1.13 / 1.58 / 2.09 | 3.49 | 1.58 | 0.47 | ×220 |
| 1000 | 2 | 0.03 / 0.04 / 0.05 | 0.08 | 0.07 | 0.67 | ×10 |
| 1200 | 2 | 0.03 / 0.04 / 0.06 | 0.10 | 0.09 | 0.67 | ×12 |
| 5000 | 2 | 0.13 / 0.18 / 0.24 | 0.40 | 0.36 | 0.67 | ×50 |
| 22000 | 2 | 0.55 / 0.77 / 1.03 | 1.73 | 1.55 | 0.67 | ×220 |
| 1000 | 4 | 0.02 / 0.02 / 0.04 | 0.06 | 0.10 | 0.95 | ×10 |
| 1200 | 4 | 0.02 / 0.03 / 0.04 | 0.07 | 0.11 | 0.95 | ×12 |
| 5000 | 4 | 0.07 / 0.11 / 0.17 | 0.28 | 0.44 | 0.95 | ×50 |
| 22000 | 4 | 0.30 / 0.48 / 0.73 | 1.22 | 1.92 | 0.95 | ×220 |
| 1000 | 8 | 0.01 / 0.02 / 0.02 | 0.03 | 0.13 | 1.64 | ×10 |
| 1200 | 8 | 0.01 / 0.02 / 0.02 | 0.04 | 0.15 | 1.64 | ×12 |
| 5000 | 8 | 0.05 / 0.07 / 0.09 | 0.15 | 0.58 | 1.64 | ×50 |
| 22000 | 8 | 0.23 / 0.31 / 0.40 | 0.66 | 2.50 | 1.64 | ×220 |

#### BASE con costes por clase a U=700 / 20 posiciones

Clases usadas: 7; fracción sin medir (excluida y renormalizada): 16 % (W2-EXPECTED, W2-INDEPENDENT, W2-STRESS, W2-WORST-CASE, W5-EXACT-MIP); carteras medidas por clase: 3.

| Objetivo | Workers | Duración h (óptimo / central / pesimista) | Pesimista × 1,67 | Horas-núcleo (central) | Memoria pico (GB) | Factor de extrapolación |
|---|---|---|---|---|---|---|
| 1000 | 1 | 0.23 / 0.27 / 0.30 | 0.50 | 0.27 | 0.47 | ×333 |
| 1200 | 1 | 0.28 / 0.32 / 0.36 | 0.60 | 0.32 | 0.47 | ×400 |
| 5000 | 1 | 1.16 / 1.32 / 1.49 | 2.49 | 1.32 | 0.47 | ×1667 |
| 22000 | 1 | 5.10 / 5.80 / 6.54 | 10.93 | 5.80 | 0.47 | ×7333 |
| 1000 | 4 | 0.06 / 0.08 / 0.11 | 0.18 | 0.33 | 0.95 | ×333 |
| 1200 | 4 | 0.08 / 0.10 / 0.13 | 0.21 | 0.39 | 0.95 | ×400 |
| 5000 | 4 | 0.31 / 0.40 / 0.52 | 0.87 | 1.60 | 0.95 | ×1667 |
| 22000 | 4 | 1.37 / 1.75 / 2.28 | 3.81 | 7.00 | 0.95 | ×7333 |
| 1000 | 8 | 0.05 / 0.05 / 0.06 | 0.10 | 0.43 | 1.64 | ×333 |
| 1200 | 8 | 0.06 / 0.06 / 0.07 | 0.12 | 0.51 | 1.64 | ×400 |
| 5000 | 8 | 0.24 / 0.26 / 0.28 | 0.47 | 2.08 | 1.64 | ×1667 |
| 22000 | 8 | 1.04 / 1.14 / 1.24 | 2.07 | 9.12 | 1.64 | ×7333 |

#### LIGHT con costes por clase a U=700 / 20 posiciones

Clases usadas: 5; fracción sin medir (excluida y renormalizada): 6 % (W2-EXPECTED, W5-EXACT-MIP); carteras medidas por clase: 3.

| Objetivo | Workers | Duración h (óptimo / central / pesimista) | Pesimista × 1,67 | Horas-núcleo (central) | Memoria pico (GB) | Factor de extrapolación |
|---|---|---|---|---|---|---|
| 1000 | 1 | 0.06 / 0.07 / 0.08 | 0.14 | 0.07 | 0.47 | ×333 |
| 1200 | 1 | 0.08 / 0.09 / 0.10 | 0.16 | 0.09 | 0.47 | ×400 |
| 5000 | 1 | 0.31 / 0.35 / 0.40 | 0.67 | 0.35 | 0.47 | ×1667 |
| 22000 | 1 | 1.36 / 1.55 / 1.75 | 2.92 | 1.55 | 0.47 | ×7333 |
| 1000 | 4 | 0.02 / 0.02 / 0.03 | 0.05 | 0.09 | 0.95 | ×333 |
| 1200 | 4 | 0.02 / 0.03 / 0.04 | 0.06 | 0.11 | 0.95 | ×400 |
| 5000 | 4 | 0.09 / 0.11 / 0.14 | 0.23 | 0.43 | 0.95 | ×1667 |
| 22000 | 4 | 0.37 / 0.47 / 0.61 | 1.02 | 1.88 | 0.95 | ×7333 |
| 1000 | 8 | 0.01 / 0.02 / 0.02 | 0.03 | 0.13 | 1.64 | ×333 |
| 1200 | 8 | 0.02 / 0.02 / 0.02 | 0.03 | 0.15 | 1.64 | ×400 |
| 5000 | 8 | 0.06 / 0.07 / 0.08 | 0.13 | 0.57 | 1.64 | ×1667 |
| 22000 | 8 | 0.28 / 0.31 / 0.33 | 0.56 | 2.45 | 1.64 | ×7333 |

#### HEAVY con costes por clase a U=700 / 20 posiciones

Clases usadas: 6; fracción sin medir (excluida y renormalizada): 26 % (W2-EXPECTED, W2-INDEPENDENT, W2-STRESS, W2-WORST-CASE, W5-EXACT-MIP); carteras medidas por clase: 3.

| Objetivo | Workers | Duración h (óptimo / central / pesimista) | Pesimista × 1,67 | Horas-núcleo (central) | Memoria pico (GB) | Factor de extrapolación |
|---|---|---|---|---|---|---|
| 1000 | 1 | 0.64 / 0.73 / 0.82 | 1.37 | 0.73 | 0.47 | ×333 |
| 1200 | 1 | 0.77 / 0.87 / 0.98 | 1.64 | 0.87 | 0.47 | ×400 |
| 5000 | 1 | 3.19 / 3.62 / 4.09 | 6.83 | 3.62 | 0.47 | ×1667 |
| 22000 | 1 | 14.02 / 15.93 / 17.98 | 30.03 | 15.93 | 0.47 | ×7333 |
| 1000 | 4 | 0.17 / 0.22 / 0.29 | 0.48 | 0.88 | 0.95 | ×333 |
| 1200 | 4 | 0.21 / 0.26 / 0.34 | 0.57 | 1.06 | 0.95 | ×400 |
| 5000 | 4 | 0.86 / 1.09 / 1.43 | 2.38 | 4.38 | 0.95 | ×1667 |
| 22000 | 4 | 3.76 / 4.81 / 6.27 | 10.47 | 19.24 | 0.95 | ×7333 |
| 1000 | 8 | 0.13 / 0.14 / 0.16 | 0.26 | 1.15 | 1.64 | ×333 |
| 1200 | 8 | 0.16 / 0.17 / 0.19 | 0.31 | 1.38 | 1.64 | ×400 |
| 5000 | 8 | 0.65 / 0.71 / 0.78 | 1.30 | 5.71 | 1.64 | ×1667 |
| 22000 | 8 | 2.86 / 3.13 / 3.41 | 5.69 | 25.05 | 1.64 | ×7333 |

#### CONIC con costes por clase a U=700 / 20 posiciones

Clases usadas: 7; fracción sin medir (excluida y renormalizada): 16 % (W2-STRESS, W2-WORST-CASE, W5-EXACT-MIP); carteras medidas por clase: 3.

| Objetivo | Workers | Duración h (óptimo / central / pesimista) | Pesimista × 1,67 | Horas-núcleo (central) | Memoria pico (GB) | Factor de extrapolación |
|---|---|---|---|---|---|---|
| 1000 | 1 | 0.12 / 0.14 / 0.16 | 0.26 | 0.14 | 0.47 | ×333 |
| 1200 | 1 | 0.15 / 0.17 / 0.19 | 0.31 | 0.17 | 0.47 | ×400 |
| 5000 | 1 | 0.60 / 0.68 / 0.77 | 1.28 | 0.68 | 0.47 | ×1667 |
| 22000 | 1 | 2.63 / 2.99 / 3.37 | 5.64 | 2.99 | 0.47 | ×7333 |
| 1000 | 4 | 0.03 / 0.04 / 0.06 | 0.09 | 0.17 | 0.95 | ×333 |
| 1200 | 4 | 0.04 / 0.05 / 0.07 | 0.11 | 0.21 | 0.95 | ×400 |
| 5000 | 4 | 0.16 / 0.21 / 0.27 | 0.45 | 0.83 | 0.95 | ×1667 |
| 22000 | 4 | 0.71 / 0.90 / 1.18 | 1.97 | 3.61 | 0.95 | ×7333 |
| 1000 | 8 | 0.03 / 0.03 / 0.03 | 0.05 | 0.23 | 1.64 | ×333 |
| 1200 | 8 | 0.03 / 0.03 / 0.04 | 0.06 | 0.27 | 1.64 | ×400 |
| 5000 | 8 | 0.12 / 0.14 / 0.15 | 0.25 | 1.08 | 1.64 | ×1667 |
| 22000 | 8 | 0.54 / 0.59 / 0.64 | 1.07 | 4.71 | 1.64 | ×7333 |

**Cómo leerlo.**

* A la dimensión realista (20 posiciones, universo 700) y con 4 workers, **1.000 carteras `BASE` tardarían del orden de 4–11 minutos y 22.000 del orden de 1,4–3,8 horas**
  (≈ 7 horas-núcleo en el caso central); con la mezcla pesada (`HEAVY`, 50 % W1) 22.000 serían ≈ 3,8–10,5 horas (≈ 19 horas-núcleo). La mezcla ligera (`LIGHT`) ≈ 0,4–1,0 horas.
* Las filas de «U=700» **excluyen** las clases sin medición a esa dimensión (W2 y W5: 6–26 % de las carteras según la mezcla). W5 cuesta ≈ 0,9–1,5 s por cartera a 8 activos: un 1 % de W5
  añadiría ≈ 0,015 s por cartera de media, es decir **+10–20 % sobre `BASE`**. Hay que medirlas a dimensión realista antes de fiar la cifra.
* Con 8 workers la ganancia es pequeña (22.000 `BASE`: 1,75 h → 1,14 h en el caso central) y el pico de memoria sube a 1,6 GB: **la escalabilidad está limitada por la cola larga de W1/W5 y por el arranque, no
  por los núcleos** (§6.3 del informe). Más workers no ayudan a menos que se reparta el trabajo pesado (lotes pequeños, orden por coste estimado — LPT — que el plan prevé y aún no se aplica porque no hay coste
  previo por cartera).
* **Coste en dinero: no se calcula**. Se entrega en horas-núcleo; `scale_run.py estimate --price-per-core-hour <€/h>` lo convierte cuando el usuario aporte la tarifa (no se inventan precios).
  En Arsys (6 núcleos/12 hilos compartidos con SQL Server) las horas-núcleo equivalen a ocupar esos hilos: la ventana debe acordarse (D-12) y los workers limitarse (D-11).

## 3. Riesgos específicos de la gran escala (no verificados; son los que las pruebas autorizadas deben cerrar)

| Riesgo | Por qué importa | Qué lo cierra |
|---|---|---|
| Memoria del **coordinador** con N | Retiene los `TaskResult` hasta el final (≈ 11 KB serializados por cartera en la muestra; la huella en memoria es mayor y no está medida). 22.000 carteras podrían ser cientos de MB–GB | Medir RSS del coordinador a 1.000 y 5.000 (E10/P-02) y, si crece, volcar resultados al diario/`ResultSink` y liberar |
| Fugas en workers a miles de tareas | Solo se midieron 100 → 300 tareas (+1–4 MB, sin señal) | E10 a 1.000 / 5.000 tareas por worker; `max_tasks_per_child` como mitigación |
| Tamaño y tiempo de escritura del diario | 0,12 s por 12 carteras; con 22.000 son ≈ 2.000 *shards* y ≈ cientos de MB | Medir con diario activado en 1.000 |
| Cola larga | W1 3,3 s/cartera y W5 (MIP) con variabilidad: la última tarea fija el tiempo total | Orden por coste estimado (LPT), lote ≤ 5, plazo por tarea configurado |
| Arranque inflado por la memoria | 7–30 s por pool aquí; en Linux con `forkserver` y memoria libre será distinto | Medir en la máquina de destino (requiere autorización) |
| Contención con SQL Server (Arsys) | Los workers compiten por CPU/RAM con la base de datos | E12 con carga sintética y ventana acordada; reservar hilos (D-11) |
| H-1 (B4) | Un `OPTIMAL_INACCURATE` aleatorio en un runner/CPU concreto invalida una fracción de carteras (≈ 53 % en el problema degenerado de la sonda con perturbación de 1 ulp) | Remediación B4 independiente antes de una ejecución masiva de W2-WORST-CASE |
| Representatividad | Mezclas y universo sintéticos; sin distribución real de AAA-A | Cargas reales anonimizadas, previa autorización |

## 4. Protecciones implementadas antes de pedir autorización

* `scale_run.py run` y `scaling.py` **rechazan** cualquier escala por encima de `max_portfolios_without_authorization` (999) salvo `--authorized-by <referencia>`; la prueba
  `test_the_scale_runner_refuses_mass_loads_without_authorization` lo verifica.
* `scaling.py --max-wall <s> --max-rss-mb <MB>`: un guarda (`Watchdog`) cancela la ejecución paralela por tiempo de pared o RSS de un worker; la celda queda `aborted`, **sin cifras de
  rendimiento** y sin contar como PASS (pruebas `test_the_watchdog_*` y `test_a_parallel_cell_that_exceeds_its_wall_limit_is_aborted_and_never_valid`).
* Cada celda valida T1, integridad y restricciones antes de aceptar su tiempo; un resultado erróneo invalida la medición.
* La referencia secuencial de una escala grande no es cancelable por el guarda: para 5.000/22.000 se recomienda **omitirla** y comparar contra una submuestra secuencial (decisión D-C).

## 5. Plan escalonado propuesto (cada paso exige su autorización expresa y puerta de proyección)

| Paso | Carga | Configuración propuesta | Duración estimada (central–pesimista ×1,67) | Criterio de continuar |
|---|---|---|---|---|
| P1 | 1.000 `ENG-MIX-BASE`, local (Windows) | `--workers 4 --methods sequential spawn --max-wall 1800 --max-rss-mb 400` | ≈ 5 min (central) – 11 min (pesimista ×1,67) | T1 y restricciones limpias; RSS del coordinador medido; sin fugas |
| P2 | 1.200 `ENG-MIX-BASE` (DoD oficial del Bloque 5) | igual que P1 + diario activado en una repetición | ≈ 6 min – 13 min | cierra BEN-007 / GOV-012 en su parte oficial |
| P3 | 5.000 `ENG-MIX-BASE` | `--workers 4`, sin referencia secuencial completa (submuestra de 200) | ≈ 24 min – 52 min (+ ≈ 1 h si se midiera la referencia secuencial completa) | deriva de latencia p95 < ±10 %; RSS acotado |
| P4 | 22.000 (mezcla acordada) | solo tras P1–P3 y con ventana acordada; `--max-wall` según la proyección de P3 | ≈ 1,75 h – 3,8 h (BASE); 4,8 h – 10,5 h (HEAVY) | capacidad objetivo |

## 6. Decisiones que necesito del usuario

| ID | Decisión | Opciones y recomendación |
|---|---|---|
| D-A | **Autorizar P1 (1.000)** y/o **P2 (1.200)** en esta máquina | Recomendado: autorizar P1 y P2 juntos; son ≈ 5–13 min cada uno con 4 workers según la proyección. Indicar `--authorized-by` |
| D-B | **Dónde** ejecutar 5.000/22.000 | Local (memoria saturada: 6,7–8,8 GB de swap, sin sentido para dimensionar) frente a Arsys (prohibido hasta nueva instrucción). Recomendado: liberar memoria/ejecutar en un equipo dedicado o autorizar Arsys en ventana acordada |
| D-C | Referencia secuencial en 5.000/22.000 | Omitirla y validar T1 contra una submuestra secuencial (recomendado) o aceptar horas de secuencial |
| D-D | **Mezcla de carga** (D-01) | Mantener `ENG-MIX-BASE/LIGHT/HEAVY/CONIC` (supuestos) o aportar la distribución real anonimizada; el modelo `N·Σ sᵢ·cᵢ` se comprobó con ±1,3 % en estas mezclas |
| D-E | Workers y reserva para SQL Server (D-11) | Medido hasta 8; recomendado ≤ 4 mientras no haya medidas en el servidor |
| D-F | Tarifa €/hora-núcleo (opcional) | Solo para convertir horas-núcleo en dinero |
| D-G | Enmienda del DoD (D-03) | Mantener 10/100/1.200 como cierre y 5.000/22.000 como capacidad (actual) o exigirlos |
| D-H | **Remediación B4 de H-1** | Autorizar una fase B4 independiente (tolerancia cónica / oráculo) antes de la ejecución masiva; ver `INVESTIGATION_H1_B4.md` |
| D-I | Medir W2 y W5 a dimensión realista | Requiere adaptar los fixtures de escenarios (ligados a 8 activos) y el límite de universo del MIP; sin esto, la proyección «U=700» excluye 6–26 % de las carteras |
