# Plan de la issue #31: fix: observed_at usa last_report y GBFS v3 publica last_reported

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/31
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** AUTORIZADO / EN IMPLEMENTACIÓN (2026-10-27)
- **Rama futura:** `fix/31/observed-at-usa-last-reported` (creada desde `main`)
- **Base de rama:** `main`

## Resumen verificable de la issue

`src/movilidad/infrastructure/providers/gbfs.py:80` hace `self._timestamp(raw.get("last_report"), now)`. El feed GBFS v3.0 de BIKI publica `last_reported`. Medido el 27-oct-2026: 104 apariciones de `last_reported`, 0 de `last_report` en `station_status`. Resultado: `observed_at` es siempre la hora de captura; en producción las 104 estaciones comparten el mismo `observed_at` (idéntico a `collected_at`), mientras que en el feed la edad real iba de 10 s a 270 s.

## Alcance confirmado y exclusiones

Dentro:
- Leer `last_reported` en el adaptador GBFS, con `now` como respaldo cuando falte o no sea válido.
- Tests del adaptador y de la regla de obsolescencia.
- Actualizar la documentación que describe `observed_at`.

Fuera (decisión pendiente, ver dudas):
- Reescribir el histórico ya guardado.
- Cambiar el umbral de 600 s de `is_stale` sin medirlo antes.
- Cambios de esquema o migraciones (no hacen falta).

## Contexto y dependencias

- `collected_at` ya guarda la hora de captura; no cambia.
- La clave de observación es `(provider_id, station_id, observed_at)` con `INSERT OR IGNORE` (`repository.py`, `save_observation`). Con la hora del proveedor, una estación que no reporta entre dos capturas produce la misma clave y la fila repetida se descarta: es el comportamiento deseado, pero baja el número de filas por día.
- `latest_observations` y `list_station_snapshots` usan `MAX(observed_at)`: pasan a ordenar por hora del proveedor.
- Ningún test actual menciona `last_report` ni fija `observed_at` desde el feed (`git grep` solo encuentra la línea de `gbfs.py`).
- Tiene efecto solo cuando se despliegue; `/health` no expone versión (ver core#32).

## Propuesta técnica (NO EJECUTAR)

1. En `GbfsProvider._normalise`, leer `raw.get("last_reported")`. `_timestamp` ya admite número (epoch) y cadena RFC 3339 con `Z`.
2. Si falta, es inválido o está en el futuro más allá de una tolerancia, usar `now` y dejar un registro de aviso (sin PII).
3. Test unitario con una respuesta real de `station_status` (cadena `2026-10-27T10:34:46.183Z`): `observed_at` sale de `last_reported`, `collected_at` es `now`.
4. Test de pipeline: dos capturas con el mismo `last_reported` generan una sola fila.
5. Test de regla: una estación con `last_reported` de hace más de 600 s da `is_stale = true`.
6. Documentar en `docs/PROCEDENCIA_DATOS.md` y `docs/API_V1.md` qué significa `observed_at` y desde qué fecha cambia.

## Dudas y decisiones (resolver TODAS antes de codificar)

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| ¿Qué hacer con el histórico ya guardado, que usa hora de captura? | A) Dejarlo y documentar la fecha de corte. B) Reescribirlo (imposible: no se guardó el dato original). | A: dejarlo y documentar (docs/PROCEDENCIA_DATOS.md) | Resuelta |
| ¿Mantener el umbral de 600 s de `is_stale`? Con hora del proveedor, una estación inactiva puede tardar en reportar. | A) Mantenerlo. B) Medir 24 h de intervalos entre reportes del feed antes de decidir. | Se mantiene 600 s; no se toca en esta issue. Medirlo (24 h de intervalos entre reportes) queda para una issue aparte | Resuelta |
| ¿Se acepta un `last_reported` en el futuro o muy antiguo? | A) Usarlo tal cual. B) Si está en el futuro, usar `now`. C) Descartar la observación. | B: futuro (>60 s) -> hora de captura + aviso; tolerancia de 60 s por desfase de reloj (en el feed del 27-oct ninguna estación reportaba en el futuro) | Resuelta |
| ¿Conservar el nombre antiguo `last_report` como respaldo? | A) Sí, por si cambia el feed. B) No, solo `last_reported`. | B: solo `last_reported` | Resuelta |
| ¿Quién despliega y cuándo? Cambia la semántica de los datos nuevos. | A) Los mantenedores tras mergear. B) Con aviso previo en la issue. | Los mantenedores despliegan tras mergear; la PR lo avisa (no se despliega desde aquí) | Resuelta |

## Pruebas y validación propuestas

- `.venv/bin/python -m pytest tests/test_gbfs.py tests/test_pipeline.py tests/test_repository.py tests/test_domain.py` y luego la suite completa con `./scripts/validate.sh`.
- `ruff check` y `ruff format --check`.
- Comprobación manual de solo lectura contra el feed real: `observed_at` de cada estación coincide con su `last_reported`.

## Riesgos y criterios de aceptación

Riesgos: cambia la serie temporal (menos filas por día si el proveedor repite reporte); estaciones que antes parecían frescas pueden verse como obsoletas si el proveedor tarda en reportar.

Criterios de aceptación (de la issue):
- `observed_at` coincide con `last_reported` del feed para cada estación.
- `is_stale` pasa a `true` si una estación lleva más de 600 s sin reportar.
- Tests de contrato y de adaptador actualizados.

## Autorización expresa para empezar a escribir código

- [x] Todas las dudas resueltas (con las opciones recomendadas del plan).
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** mensaje de Pablo del 2026-10-27: «escribe el codigo de la #31».

**Mientras falte cualquiera de las condiciones anteriores, solo editar este documento.**
