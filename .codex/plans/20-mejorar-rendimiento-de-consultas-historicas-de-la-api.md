# Plan de la issue #20: Mejorar rendimiento de consultas históricas de la API

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/20
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** EN IMPLEMENTACIÓN (autorizada el 2026-10-25)
- **Rama futura:** `fix/20/rendimiento-consultas-historicas` (todavía no creada)
- **Base de rama:** `main`

## Resumen verificable de la issue

Las consultas `/stations/{id}/history` y `/stations/{id}/summary` de 7, 30 y 90 días son lentas y variables en producción (7 d hasta 4,65 s; 30 d entre 0,18 s y más de 20 s; 90 d hasta 2,9 s). La issue propone ocho mejoras (sacar `ensure_schema()` y WAL del ciclo de petición, instrumentar, agregar en SQLite, no duplicar la lectura, endpoint combinado, revisar `busy_timeout`, caché/agregados diarios) y seis criterios de aceptación. No tiene comentarios ni asignada.

## Qué se ha medido (antes de proponer nada)

Base sintética con la forma medida de la real: 104 estaciones, ~66 000 observaciones por estación (la API pública da 64 972 para la estación 72: 24-sep 1 496; 25-sep a 20-oct ~2 400/día; 21-oct 1 094; 22 a 24-oct 288/día), 6,86 M de filas, 1,3 GB, mismos índices que `ensure_schema`. Máquina de desarrollo (macOS, Python 3.14), no el servidor de producción. Scripts de medición fuera del repositorio.

**1. Desglose de una petición (mediana de 5, ms, caché de SQLite caliente):**

| Paso | 24 h | 7 d | 30 d | 90 d |
| --- | --- | --- | --- | --- |
| `connect` + `PRAGMA journal_mode=WAL` | 4,2 | 3,9 | 3,9 | 3,9 |
| `ensure_schema` | 0,1 | 0,1 | 0,1 | 0,1 |
| SQL (`fetchall`) | 0,9 | 42 | 262 | 267 |
| Filas a `Observation` (Python) | 1,5 | 44 | 397 | 412 |
| Agregar `history` (Python) | 0,3 | 19 | 167 | 141 |
| Calcular `summary` (Python) | 3,7 | 150 | 963 | 1 171 |
| **Total `history` / `summary`** | 9 / 11 | 107 / 113 | 1 208 / 1 053 | 868 / 1 109 |

**2. uvicorn real, 1 worker, cada cliente lanza `history` y `summary` a la vez (como el frontend), 30 d:**

| Clientes simultáneos | Mínimo | Mediana | Máximo |
| --- | --- | --- | --- |
| 1 | 2,6 s | 2,7 s | 2,9 s |
| 4 | 7,3 s | 13,1 s | 15,4 s |
| 10 | 20,7 s | 34,2 s | 39,9 s |

90 d con 10 clientes: 16,4 a 37,8 s. El tiempo crece casi linealmente con los clientes.

**3. Con un escritor activo** (104 inserciones cada 0,5 s, 227 ciclos, mucho más agresivo que el collector real, que escribe cada 300 s): 0 errores y sin cambio apreciable (1 cliente 1,9 a 2,6 s; 10 clientes 19 a 35 s).

**4. Plan de consulta (`EXPLAIN QUERY PLAN`):** la consulta usa `idx_observations_station_time`; la versión agregada añade `USE TEMP B-TREE FOR GROUP BY`. Observación aparte: ese índice cubre las mismas tres columnas que la clave primaria (`sqlite_autoindex_observations_1`), así que cada inserción mantiene dos índices idénticos.

### Lectura (observación, no veredicto)

- Lo que se ve en tres mediciones independientes (desglose en proceso, uvicorn real, carga concurrente): el tiempo se va en **Python** (crear objetos y calcular), no en SQL ni en abrir la conexión. Con un worker y el GIL, las peticiones se encolan y la latencia se multiplica por el número de clientes.
- **No se sostiene** con estas mediciones que `ensure_schema`/WAL (≈4 ms) ni los bloqueos de escritura (0 efecto con WAL) expliquen los segundos de la issue.
- **Sin medir:** producción real (CPU del servidor, caché fría, tráfico simultáneo, volumen real). Las cifras 2 a 23 s de producción son compatibles con esta cola, pero no se ha demostrado que sea la causa allí. Se propone medirlo con el script del apartado de pruebas.

### Prototipo de agregación en SQL (fuera del repositorio)

Agrupar en SQLite por franja (`substr(observed_at, 1, 13|10)`) y por (`capacity`, `free_docks`) y reducir en Python con las mismas funciones (`occupancy_percent`), acumulando la ocupación en céntimos enteros. Comparado con la implementación actual en 120 pares `history`+`summary` (24 estaciones × 1 d, 7 d, 30 d hora, 30 d día, 90 d día):

- **Resultado:** 0 diferencias.
- **Tiempo por par `history`+`summary`:** 1 186 ms actual → 167 ms con el prototipo (≈7×).
- **Lección:** una primera versión que sumaba `ocupación × n` en coma flotante dio 49,37 donde el código actual da 49,38 (media exacta 49,375, un empate real). Por eso el acumulador debe ser entero.
- **Límite:** datos sintéticos aleatorios; falta probar nulos, `capacity` nula, formatos mixtos de `observed_at` y los datos reales.

## Alcance confirmado y exclusiones

**Propuesto para esta issue (a confirmar en las dudas):**

1. Agregar `history` (`hour`/`day`) y `summary` en SQLite, sin materializar `Observation` por fila. `raw` queda como hoy.
2. Sacar `ensure_schema()` y `PRAGMA journal_mode=WAL` del ciclo de petición: ejecutarlos al arrancar la API (lifespan) y en los puntos de entrada del collector/importador. Producción ya ejecuta `alembic upgrade head` antes de arrancar (README, `docs/ARQUITECTURA.md`).
3. Instrumentar: tiempo total, tiempo SQL, filas leídas y grupos procesados por petición, en el log estructurado. Sin tocar el cuerpo de la respuesta.
4. Pruebas: equivalencia con la implementación actual, `EXPLAIN QUERY PLAN` y un script de carga reproducible fuera de CI.

**Fuera de esta issue / decisión pendiente:**

- Endpoint combinado `history`+`summary` (criterio de aceptación de la issue). Es un cambio de contrato aditivo y obliga a adaptar `biki-stats-web`#8. Con la agregación en SQL el par cuesta ≈170 ms, así que su beneficio es menor que antes de medir.
- Caché de resultados y tabla de agregados diarios: no hay evidencia de necesitarlos si el resultado con SQL se confirma.
- `busy_timeout=30000`: con las mediciones no hay evidencia de que genere esperas. Cambiarlo sin datos sería elegir un umbral que se puede medir.
- Índice redundante `idx_observations_station_time`: abrir issue aparte.
- Más workers de uvicorn / separar procesos: infraestructura, decide el mantenedor.

## Contexto y dependencias

- Código afectado: `src/movilidad/application/services.py` (`history`, `summary`, `aggregate_history`, `count_missing_buckets`), `infrastructure/db/repository.py` (`station_history`), `infrastructure/db/connection.py`, `api/dependencies.py`, `api/main.py` (lifespan), `application/capture.py`, `application/history_import.py`.
- Contratos que no pueden cambiar: `docs/API_V1.md`, `schemas/api/stations.py` (`HistoryData`, `SummaryData`), orden y redondeo de los valores, `missing_buckets` por hora, `minimum_at`/`maximum_at` = primera aparición.
- Consumidor: `biki-stats-web`#8 (carga del histórico). El PR web#15 ya cancela, cachea y muestra errores parciales; queda preparado un único punto de carga para enchufar el endpoint combinado.
- Mixto de formatos en `observed_at` (`…:30Z` y `…:30.959162Z`): la agrupación por prefijo funciona con ambos; el filtro de rango por cadena ya tenía esa particularidad y no se cambia.
- Tests con `TestClient(app)` sin gestor de contexto no ejecutan el lifespan: dependen del esquema que crean sus fixtures (ya llaman a `ensure_schema`).

## Propuesta técnica (NO EJECUTAR)

1. `connection.py`: separar `connect()` (solo pragmas por conexión: `foreign_keys`, `busy_timeout`) de una función de inicialización (`ensure_schema` + WAL) que se llama una vez.
2. `api/main.py` lifespan: inicializar la base una vez. `dependencies.get_connection` solo abre y cierra.
3. `repository.py`: dos métodos nuevos, `history_buckets(...)` y `summary_groups(...)`, que devuelven filas agrupadas. `station_history` queda para `raw`.
4. `services.py`: reducir los grupos con la misma lógica (`occupancy_percent`, `_mean`, `_percent_of`), ocupación en céntimos enteros, huecos rellenados como hoy.
5. Instrumentación con `time.perf_counter()` en servicio y repositorio y un registro por petición con `total_ms`, `sql_ms`, `rows`, `groups`.
6. Documentar en `docs/ARQUITECTURA.md` el modelo de coste y cómo medir.

## Dudas y decisiones (resolver TODAS antes de codificar)

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| 1. Alcance de este PR frente a las ocho mejoras de la issue | (a) los puntos 1 a 4 y el combinado en otro PR; (b) todo junto; (c) solo SQL | Recomendado (a): lo medido apunta a la agregación; el combinado es contrato nuevo y depende de web | Resuelta (recomendación) |
| 2. Cerrar la issue con (a) o dejarla abierta para el combinado | cerrar y abrir issue nueva del combinado / mantener abierta | Recomendado: PR con `Refs`, no `Closes`, y decidir al mergear | Resuelta (recomendación) |
| 3. Igualdad de resultados | idéntica al actual (acumulador entero y prueba de equivalencia) / tolerar ±0,01 en empates | Recomendado: idéntica, verificada con la implementación actual como oráculo en tests | Resuelta (recomendación) |
| 4. Conservar las funciones Python actuales como oráculo en los tests | sí (copiadas a `tests/`) / no | Recomendado: sí, solo en tests | Resuelta (recomendación) |
| 5. Dónde inicializar el esquema/WAL | lifespan de la API + entradas del collector / solo Alembic en producción | Recomendado: lifespan + entradas, mantiene el arranque defensivo de desarrollo | Resuelta (recomendación) |
| 6. `busy_timeout=30000` | dejarlo / bajarlo | Recomendado: dejarlo; sin evidencia. Si se baja, necesita medir qué espera el collector | Resuelta (recomendación) |
| 7. Script de carga (`scripts/bench_history.py`) | añadirlo al repo, fuera de CI / no añadirlo | Recomendado: añadirlo; una prueba con umbral en CI sería flaky y el umbral no está medido en producción | Resuelta (recomendación) |
| 8. Cifras de producción | alguien con acceso corre el script / tamaño real de la base / seguir con las sintéticas | Hace falta que nuke o pela corran el script en el servidor, o decir el tamaño real, para cerrar el criterio de «sin timeouts» | Abierta |
| 9. Asignación de la issue | asignarla a `pabloguti` al autorizar | Pendiente de Pablo | Resuelta (recomendación) |

## Pruebas y validación propuestas

- **Equivalencia:** para cada combinación de periodo y granularidad, `history` y `summary` nuevos == implementación actual sobre datos aleatorios con nulos, `capacity` nula, `free_docks` fuera de rango, huecos, formatos mixtos de `observed_at` y empates de redondeo (como el 49,375 hallado). Un test debe verse fallar si se acumula la ocupación en coma flotante.
- **Plan de consulta:** `EXPLAIN QUERY PLAN` de las consultas nuevas usa `idx_observations_station_time` y no hace `SCAN observations`.
- **Sin esquema por petición:** un test que cuente sentencias DDL y `PRAGMA journal_mode` durante una petición (debe ser 0) y se vea fallar con el código actual.
- **Instrumentación:** el log de la petición incluye `total_ms`, `sql_ms`, `rows`, `groups` y la respuesta no cambia.
- **Carga:** `scripts/bench_history.py` genera la base sintética, levanta uvicorn y lanza N clientes (`history`+`summary`) con y sin escritor; imprime mínimo, mediana, máximo. Se compara antes/después en el PR.
- **Regresión:** `pytest` completo (35 tests pasan hoy en `main`) y `ruff`.

## Riesgos y criterios de aceptación

- **Riesgo:** diferencias de redondeo respecto a hoy. Mitigación: acumulador entero y oráculo.
- **Riesgo:** mejora medida solo en sintético y local. Mitigación: script reproducible y petición a los mantenedores (duda 8); el PR lo dirá.
- **Riesgo:** quitar `ensure_schema` por petición rompe un despliegue sin Alembic. Mitigación: inicialización en lifespan.
- **Criterios de la issue y estado propuesto:**
  - Peticiones históricas sin esquema ni WAL: sí (punto 2).
  - Tiempos SQL y observaciones registrados: sí (punto 3).
  - Endpoint combinado sin lecturas duplicadas: **no en este PR** (duda 1).
  - 30 y 90 d sin timeouts en prueba concurrente representativa: medible con el script en local; en producción depende de la duda 8.
  - Contratos y resultados iguales: sí (duda 3).
  - `EXPLAIN QUERY PLAN`: sí.

## Autorización expresa para empezar a escribir código

- [x] Dudas 1 a 7 y 9 resueltas con las recomendaciones del plan; la 8 (cifras de producción) sigue abierta y se declara en el PR.
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** «So, adelante», respuesta de Pablo a «¿Puedo empezar a escribir código para la issue #20?» (2026-10-25).

**Mientras falte cualquiera de las condiciones anteriores, solo editar este documento.**

## Resultado de la implementación (2026-10-25)

- Hecho: puntos 1 a 4 del alcance propuesto. El endpoint combinado, la caché, los agregados diarios y `busy_timeout` quedan fuera, como se acordó.
- **Empates de redondeo:** la prueba de equivalencia con datos aleatorios encontró una diferencia que el prototipo no veía (85,835: el código anterior daba 85,84 por ruido de la suma en coma flotante, y el redondeo exacto 85,83). Con franjas de 12 observaciones, 1 de cada 12 medias es un empate exacto. Solución: acumular en céntimos enteros y, solo en un empate exacto, repetir la suma original sobre las filas de esa franja. Resultado: idéntico al anterior en las 23 pruebas de equivalencia.
- **Antes/después** con `scripts/bench_history.py` sobre la misma base (10 estaciones, 633 578 observaciones, 1 worker, medianas): 30 d `hour` 1 cliente 3,58 s → 0,73 s; 10 clientes 35,2 s → 3,05 s (máximo 42,7 s → 5,3 s). 90 d `day` 10 clientes 32,2 s → 1,07 s. Sin fallos en ningún caso.
- Sigue abierta la duda 8: no hay cifras de producción real.
