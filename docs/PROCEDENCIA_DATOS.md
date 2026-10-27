# Procedencia y derechos de datos

- Feed GBFS oficial de BIKI Valladolid: https://valladolid.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json
- Origen candidato para la migración histórica: https://github.com/serherval/flujosbiki
- Issue central de migración: https://github.com/aldeapucela/biki-stats-core/issues/1

## Significado de `observed_at`

`observed_at` es el instante en que la estación reportó el dato (`last_reported` del feed `station_status` de GBFS v3). `collected_at` es el instante en que el collector lo capturó. Si el feed no trae `last_reported`, trae un valor que no se puede interpretar o lo trae en el futuro (más de 60 s), se usa la hora de captura y se registra un aviso.

Hasta la corrección de la [issue #31](https://github.com/aldeapucela/biki-stats-core/issues/31), el collector leía un campo inexistente (`last_report`) y guardaba la hora de captura en `observed_at`. Las observaciones capturadas antes del despliegue de esa corrección **conservan esa hora de captura**: no se reescriben porque no se guardó el valor original del proveedor. Las importadas de `flujosbiki` conservan la hora de su fuente.

**Antes de publicar o redistribuir** datos de terceros, verificar condiciones, derechos de explotación, atribuciones y compatibilidad con la licencia propuesta. La publicación en GitHub no implica por sí misma autorización para relicenciar datasets.

La [política CC BY-SA 4.0](../DATA_LICENSE.md) solo cubre contenido original autorizado de Aldea Pucela. El código está sujeto a la [AGPL v3](../LICENSE).
