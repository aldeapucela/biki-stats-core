# Plan de la issue #4: feat: definir rutas y contratos JSON de la API pública v1

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/4
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** IMPLEMENTADO Y VALIDADO
- **Rama:** `feat/4/contratos-api-v1`
- **Base de rama:** `main`
- **Dependencia:** issue #3 implementada en `feat/3/arquitectura-backend`

## Resumen verificable de la issue

La issue solicita diseñar y documentar, antes de programar, las rutas públicas v1 de solo lectura, sus parámetros, esquemas JSON, errores, estados HTTP, reglas de agregación y documentación OpenAPI para que la SPA de `biki-stats-web` pueda integrarse sin inventar contratos.

Requisitos confirmados:

- Envoltorio coherente para respuestas de negocio: `status`, `code`, `data`, `errors` y `meta` solo si se aprueba.
- `code` debe coincidir con el estado HTTP real.
- Claves JSON en inglés como propuesta; `station_id` es string; timestamps UTC RFC3339 con `Z`.
- `null` significa dato desconocido y no debe confundirse con cero.
- La captura del backend ocurre cada 5 minutos; la API debe comunicar frescura y no prometer tiempo real.
- La SPA es solo lectura y necesita estación actual, cercanía, histórico y resúmenes para 24 h, 7 d, 30 d y 90 d.
- El histórico legado tiene intervalos irregulares: no se pueden fabricar observaciones ni interpolar huecos.
- Deben documentarse paginación, filtros, errores, CORS, cacheado, OpenAPI y tests de contrato.

## Alcance y exclusiones

### Incluido

- Tabla definitiva de endpoints, métodos, parámetros, respuestas y estados HTTP.
- Contratos de éxito, vacío y error con ejemplos JSON válidos.
- Semántica de disponibilidad, frescura, estaciones inactivas, datos ausentes y ocupación.
- Reglas de histórico y resumen con observaciones irregulares, capacidad variable y cambios DST.
- Paginación, límites, ordenación, filtros, cacheado y cabeceras CORS.
- Catálogo estable de códigos de error y comportamiento de validación.
- Decisión sobre `/api/v1/health` frente a `/health` y precedencia de `/stations/nearby`.
- Plan de OpenAPI y validación automática de contratos durante la implementación.

### Fuera de alcance

- Implementar las rutas, modelos Pydantic, consultas SQL y tests de contrato definidos en este plan.
- Modificar la SPA o crear una issue en `biki-stats-web`.
- Cambiar la arquitectura de #3, la captura GBFS o la migración de #1.
- Añadir autenticación, escritura, alquiler, reserva o cualquier operación transaccional.

## Contexto técnico

- #3 deja FastAPI, `api`, `application`, `domain`, `infrastructure`, `schemas` y `core` como límites de la aplicación.
- La implementación actual expone únicamente `GET /api/v1/health`; las rutas de negocio están deliberadamente pendientes.
- La base conserva `observed_at`, `collected_at`, `capacity`, bicis mecánicas/eléctricas y anclajes libres por proveedor y estación.
- La API será pública de solo lectura, con CORS explícito por entorno y rate limiting en proxy/servidor.
- El frontend previsto usa los periodos 24 h/7 d/30 d/90 d y necesita indicar datos obsoletos, ausentes o simulados.

## Propuesta de contratos (NO EJECUTAR)

### Decisiones aprobadas

- Rutas y claves JSON en inglés.
- Envoltorio siempre formado por `status`, `code`, `data`, `errors` y `meta`.
- `meta.request_id` replica la cabecera `X-Request-ID`.
- `free_docks` representa anclajes libres y `occupancy_percent` se calcula como `(capacity - free_docks) / capacity * 100`; si la capacidad no es válida, el porcentaje es `null`.
- Listados con `limit`/`offset`, máximo 100 elementos; históricos con máximo 10.000 muestras.
- Medias por observación, sin ponderación temporal ni interpolación de huecos.
- `/api/v1/health` comprueba API y SQLite, no la disponibilidad del feed GBFS.
- Cacheado con `Cache-Control: public, max-age=30` y ETag.
- Errores públicos: `INVALID_QUERY_PARAMETER`, `RESOURCE_NOT_FOUND`, `SERVICE_UNAVAILABLE`, `INTERNAL_ERROR` y `RATE_LIMITED`.
- Estaciones con `status` separado de la frescura; contadores desconocidos son `null`.
- Histórico con `from`/`to` RFC3339, máximo 90 días y granularidades `raw`, `hour` y `day`.
- Cercanía mediante Haversine con `distance_m` y orden ascendente.
- Resumen con KPIs, composición, número de observaciones y timestamps de extremos.
- Colecciones vacías con `data: []`.
- `biki` es el proveedor por defecto; `provider_id` queda opcional para futura extensión.

### Envoltorio común

Todas las respuestas de negocio JSON usarán la misma forma:

```json
{
  "status": "success",
  "code": 200,
  "data": {},
  "errors": null,
  "meta": {}
}
```

Para errores:

```json
{
  "status": "error",
  "code": 422,
  "data": null,
  "errors": [
    {
      "code": "INVALID_QUERY_PARAMETER",
      "message": "El parámetro limit debe ser un entero entre 1 y 100",
      "field": "limit"
    }
  ],
  "meta": {}
}
```

Propuesta: `meta` siempre estará presente como objeto, aunque vacío, para mantener un contrato estable; la decisión final debe confirmarse. Podrá contener `request_id`, paginación, frescura y enlaces sin mover esos datos a `data`.

### Endpoints candidatos a aprobar

| Método y ruta | Uso | Éxito | Errores principales |
| --- | --- | --- | --- |
| `GET /api/v1/health` | Estado mínimo del servicio y SQLite | `200` | `503` si no puede servir |
| `GET /api/v1/stations` | Lista actual de estaciones, filtros y paginación | `200`, `data: []` si no hay resultados | `422` |
| `GET /api/v1/stations/{station_id}` | Detalle actual de una estación | `200` | `404`, `503` |
| `GET /api/v1/stations/nearby` | Estaciones por distancia | `200`, `data: []` | `422` |
| `GET /api/v1/stations/{station_id}/history` | Serie histórica de observaciones/agrupaciones | `200`, `data: []` | `404`, `422`, `503` |
| `GET /api/v1/stations/{station_id}/summary` | Estadísticas del intervalo solicitado | `200` | `404`, `422`, `503` |

`/stations/nearby` debe registrarse antes de `/{station_id}` en el router o usar una ruta que no pueda confundirse con un identificador.

### Datos actuales

Propuesta de objeto de estación:

```json
{
  "station_id": "2",
  "name": "Fuente Dorada",
  "location": {"latitude": 41.6523, "longitude": -4.7245},
  "bikes": {"mechanical": 9, "electric": 3},
  "free_docks": 15,
  "capacity": 27,
  "occupancy_percent": 44.44,
  "status": "active",
  "observed_at": "2026-10-13T07:50:00Z",
  "collected_at": "2026-10-13T07:50:04Z",
  "data_age_seconds": 0
}
```

La propuesta debe aclarar si `occupancy_percent` representa anclajes ocupados (`capacity - free_docks`) o bicicletas disponibles respecto a capacidad. La API debe devolver `null` si falta el denominador o si la capacidad no es fiable.

### Parámetros

- Listado: `q`, `status`, `has_electric`, `limit`, `offset` y `sort`.
- Cercanía: `lat`, `lon`, `radius_m`, `limit`; coordenadas obligatorias juntas, límites máximos explícitos y distancia calculada en metros.
- Histórico: `from`, `to`, `granularity`, `limit`; fechas RFC3339 con zona explícita, ventanas máximas y resolución aprobada.
- Resumen: `from`, `to`; misma semántica temporal que histórico.

Propuesta: offset para el MVP por su simplicidad, límites máximos de 100 elementos y 10.000 muestras, y `meta.pagination` con `limit`, `offset`, `returned` y `has_more`. Cursor se deja para una evolución posterior.

### Histórico y estadísticas

- Periodos permitidos: 24 h, 7 d, 30 d y 90 d, expresados como ventanas relativas o fechas `from`/`to` según se apruebe.
- No interpolar observaciones ausentes; los huecos se representan como ausencia o `null` según el esquema final.
- La resolución solicitada debe limitar el número de puntos y documentar si agrupa por hora o día.
- La media inicial se propone por observación, no ponderada por duración, porque el histórico legado es irregular; se debe mostrar el número de observaciones y huecos.
- Máximos y mínimos se calculan solo sobre observaciones existentes y devuelven su timestamp.
- La ocupación total y los porcentajes se calculan solo cuando capacidad y componentes son compatibles; las anomalías se identifican, no se corrigen silenciosamente.
- Cambios DST y timestamps ambiguos heredados conservan su marca de ambigüedad y no deben generar instantes inventados.

## Dudas y decisiones (resolver TODAS antes de codificar)

| Duda | Alternativas | Recomendación | Estado |
| --- | --- | --- | --- |
| ¿Claves y rutas en inglés? | Inglés; español; mezcla | Inglés, coherente con GBFS y frontend | Resuelta |
| ¿`meta` en todas las respuestas? | Siempre objeto; solo cuando aporta datos; nunca | Siempre objeto, con paginación/frescura/request ID | Resuelta |
| ¿Health dentro de `/api/v1`? | Dentro; fuera; ambos | Mantener `/api/v1/health` | Resuelta |
| ¿Acceso público y rate limiting? | Público con proxy; API key; privado | Público de solo lectura, límites en proxy | Resuelta en #3 |
| ¿Cacheado? | `Cache-Control` corto; ETag; sin cache | `Cache-Control: public, max-age=30` y ETag | Resuelta |
| ¿Semántica de `free_docks`? | Anclajes libres; capacidad menos bicis; nullable si no fiable | Anclajes libres del feed; no derivar si el origen no lo declara | Resuelta |
| ¿Semántica de `occupancy_percent`? | Anclajes ocupados/capacidad; bicis/capacidad; no exponer al principio | Anclajes ocupados/capacidad, `null` ante capacidad cero/desconocida | Resuelta |
| ¿Paginación? | Offset; cursor; sin paginar | Offset con límites estrictos para MVP | Resuelta |
| ¿Promedios irregulares? | Por observación; ponderados por duración; ambos | Por observación y declarar observaciones/huecos | Resuelta |
| ¿Datos ausentes y estación inactiva? | `null`/`unknown`; excluir; estado separado | Estado separado y contadores `null` cuando falten | Resuelta |
| ¿`request_id` en `meta`? | Sí; solo cabecera; ambos | Cabecera y `meta.request_id` | Resuelta |
| ¿Límites temporales? | 24/7/30/90 días; cualquier rango; solo periodos fijos | RFC3339, máximo 90 días y máximo 10.000 muestras | Resuelta |

| ¿Cercanía? | Haversine; bounding box; cálculo frontend | Haversine, `distance_m`, radio 1–10.000 m y límite 1–100 | Resuelta |
| ¿Granularidades? | `raw`; `hour/day`; `raw/hour/day` | `raw`, `hour` y `day`, agrupadas en UTC | Resuelta |
| ¿Resumen? | Solo KPIs; KPIs + composición; serie duplicada | KPIs, composición, observaciones y timestamps de extremos | Resuelta |
| ¿Filtros de listado? | Solo búsqueda; búsqueda + estado/eléctricas; filtros completos | `q`, `status`, `has_electric`, `sort` y `order` | Resuelta |
| ¿Colección vacía? | `data: []`; `data: null`; 404 | `data: []` | Resuelta |
| ¿TTL inicial? | 30 segundos; 5 minutos; sin TTL | 30 segundos | Resuelta |
| ¿Proveedores? | BIKI por defecto; proveedor obligatorio; solo BIKI | `biki` por defecto y filtro opcional compatible con futuro | Resuelta |
| ¿Catálogo de errores? | Mínimo estable; solo HTTP; detallado | Cinco códigos legibles por máquinas | Resuelta |

## Pruebas y validación realizadas

- Tests de contrato para cada endpoint: éxito, vacío, parámetros inválidos, 404, 503 y errores internos sanitizados.
- Validar que `code` coincide con HTTP y que el envoltorio es estable.
- Tests de fechas con UTC, offset no UTC, DST y timestamps ambiguos.
- Tests de ocupación con capacidad cero, capacidad desconocida, `null`, discrepancias y contadores cero reales.
- Tests de histórico irregular sin interpolación y con límites de muestras.
- Tests de geolocalización: coordenadas incompletas, radio/límite fuera de rango y orden por distancia.
- OpenAPI generado por FastAPI, ejemplos JSON válidos y verificación contra schemas Pydantic.
- Prueba de integración con la SPA o fixtures equivalentes de #1, sin red.

## Criterios de aceptación

- Tabla aprobada de rutas, parámetros, estados HTTP y respuestas.
- Envoltorio único `status`, `code`, `data`, `errors` y decisión documentada sobre `meta`.
- Errores estables, legibles por máquinas y sin detalles internos.
- CORS, cacheado, rate limiting, paginación y límites documentados.
- Frescura, timestamps, datos ausentes, estaciones inactivas y origen de mediciones definidos.
- Reglas de ocupación, históricos, promedios, huecos y resúmenes reproducibles.
- OpenAPI, ejemplos y tests de contrato previstos para la implementación.
- Compatibilidad suficiente con la SPA y el histórico de #1.
- Todas las dudas resueltas y autorización explícita antes de crear código.

Validación ejecutada:

- `pytest`: 8 tests superados.
- `ruff check src tests`: superado.
- `scripts/validate.sh`: superado.
- `scripts/validate.sh --docker-build`: imágenes `api` y `collector` construidas correctamente.
- `git diff --check`: superado.
- OpenAPI: rutas y operaciones públicas verificadas.

## Autorización expresa para empezar a escribir código

- [x] Todas las dudas resueltas.
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** `Implement the plan.` (usuario, 2026-10-16)

**Mientras falte cualquiera de las condiciones anteriores, solo editar este documento.**
