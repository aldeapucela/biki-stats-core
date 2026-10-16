# API pública v1

La API es pública, de solo lectura y sirve datos de movilidad capturados por el collector. La captura ocurre aproximadamente cada cinco minutos; las respuestas no representan tiempo real.

## Respuesta común

Todas las respuestas JSON de negocio tienen esta forma:

```json
{
  "status": "success",
  "code": 200,
  "data": {},
  "errors": null,
  "meta": {
    "request_id": "uuid",
    "generated_at": "2026-10-16T10:00:00Z"
  }
}
```

Los errores mantienen el mismo envoltorio:

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
  "meta": {"request_id": "uuid"}
}
```

`code` coincide con el estado HTTP. `X-Request-ID` se devuelve siempre y se replica en `meta.request_id`. Las respuestas incluyen `ETag` y `Cache-Control: public, max-age=30`; un `If-None-Match` coincidente responde `304` sin cuerpo JSON.

## Rutas

| Método y ruta | Descripción | Estados |
| --- | --- | --- |
| `GET /api/v1/health` | Comprueba API y SQLite | `200`, `500` |
| `GET /api/v1/stations` | Estaciones actuales paginadas | `200`, `422`, `503` |
| `GET /api/v1/stations/{station_id}` | Detalle actual | `200`, `404`, `422`, `503` |
| `GET /api/v1/stations/nearby` | Estaciones ordenadas por distancia | `200`, `422`, `503` |
| `GET /api/v1/stations/{station_id}/history` | Observaciones o buckets históricos | `200`, `404`, `422`, `503` |
| `GET /api/v1/stations/{station_id}/summary` | KPIs y composición del intervalo | `200`, `404`, `422`, `503` |

`/stations/nearby` precede a `/{station_id}` en el router para evitar conflictos.

## Estaciones

`GET /api/v1/stations` admite:

- `q`: búsqueda por nombre.
- `status`: `active`, `inactive` o `unknown`.
- `has_electric`: booleano.
- `sort`: `name`, `occupancy_percent` o `data_age_seconds`.
- `order`: `asc` o `desc`.
- `limit`: 1–100; por defecto 50.
- `offset`: mayor o igual que 0.
- `provider_id`: opcional, por defecto `biki`.

Las colecciones vacías devuelven `data: []`. La paginación se encuentra en `meta.pagination` con `limit`, `offset`, `returned` y `has_more`.

Cada estación incluye `provider_id`, `station_id`, `name`, `location`, `bikes`, `free_docks`, `capacity`, `occupancy_percent`, `status`, `observed_at`, `collected_at`, `data_age_seconds` e `is_stale`.

`free_docks` son anclajes libres. `occupancy_percent` es `(capacity - free_docks) / capacity * 100`; si la capacidad es cero, desconocida o inconsistente, devuelve `null`.

## Cercanía

`GET /api/v1/stations/nearby` requiere `lat` y `lon`. Admite `radius_m` entre 1 y 10.000, `limit` entre 1 y 100 y `provider_id`.

La distancia se calcula con Haversine, se devuelve como `distance_m` y el resultado se ordena ascendentemente. Las coordenadas de consulta no se almacenan.

## Histórico

`GET /api/v1/stations/{station_id}/history` requiere `from` y `to` en RFC3339 con zona horaria. El intervalo máximo es de 90 días. Admite:

- `granularity=raw`: solo observaciones reales.
- `granularity=hour`: agrupación en horas UTC.
- `granularity=day`: agrupación en días UTC.
- `limit`: máximo 10.000 puntos.
- `provider_id`: por defecto `biki`.

Las medias se calculan por observación. No se interpolan huecos. En granularidades agrupadas, los buckets sin observaciones se representan con valores `null` y `observations: 0`.

## Resumen

`GET /api/v1/stations/{station_id}/summary` usa los mismos parámetros `from`, `to` y `provider_id` que histórico. Devuelve:

- Media, mínimo y máximo de ocupación.
- Instantes de mínimo y máximo.
- Medias de bicis mecánicas, eléctricas, anclajes libres y bicis totales.
- Composición media.
- Número de observaciones.
- Primer y último `observed_at`.
- Buckets sin observaciones.

Los datos ausentes son `null`; no se convierten en ceros. Los timestamps ambiguos heredados no se reinterpretan.

## Errores y frescura

| Código | HTTP | Uso |
| --- | --- | --- |
| `INVALID_QUERY_PARAMETER` | `422` | Parámetro ausente, inválido o fuera de límites |
| `RESOURCE_NOT_FOUND` | `404` | Estación inexistente |
| `SERVICE_UNAVAILABLE` | `503` | Dependencia de lectura no disponible |
| `INTERNAL_ERROR` | `500` | Error interno sanitizado |
| `RATE_LIMITED` | `429` | Límite aplicado por proxy o servidor |

`observed_at` es el instante del proveedor; `collected_at`, el de captura; `data_age_seconds`, la edad calculada; `is_stale` es `true` después de 600 segundos.

## OpenAPI

FastAPI publica el contrato generado en `/docs`, `/redoc` y `/openapi.json`. Los tests de contrato verifican rutas, envoltorio, validación, errores, ETag y respuestas de histórico/resumen.
