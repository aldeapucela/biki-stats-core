# Plan de la issue #1: feat: migrar el histórico de flujosbiki preservando todos los datos

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/1
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** IMPLEMENTADO; VALIDACIÓN LOCAL COMPLETADA
- **Rama:** `feat/1/migrar-el-historico-de-flujosbiki-preservando-todos-los-datos`
- **Base de rama:** `main`

## Resumen verificable de la issue

Importar el histórico CSV de `serherval/flujosbiki` en SQLite, normalizarlo al modelo actual de estaciones y observaciones y conservar su procedencia. La importación inicial se ejecutará automáticamente al arrancar el contenedor, una sola vez por base de datos persistente, y podrá lanzarse manualmente en desarrollo con simulación, reintento y forzado explícito.

El origen no declara licencia. La implementación podrá probarse en desarrollo, pero la activación en PRO queda condicionada a confirmar autorización, condiciones de reutilización y atribución.

## Alcance confirmado y exclusiones

### Incluido

- Descubrir todos los CSV bajo `data/` en un commit concreto de `main`, incluyendo `data/archivo/*.csv` y `data/historico.csv`.
- Resolver y registrar el commit SHA del origen antes de descargar datos; procesar los CSV en streaming, sin cargarlos completos en memoria.
- Validar cabecera, encoding UTF-8, tipos, identificadores, rangos, nombres y timestamps; contabilizar aceptados, duplicados, conflictos y rechazos con contexto.
- Normalizar al proveedor `biki`, reutilizando la limpieza de nombres que elimina el prefijo numérico inicial.
- Persistir estaciones y observaciones históricas en las tablas vigentes; usar `source="flujosbiki"` y un `capture_id` propio de la importación.
- Usar `observed_at` convertido desde `Europe/Madrid` a UTC. Las horas ambiguas se importan con el primer `fold` determinista y `timestamp_ambiguous=true`.
- Derivar `free_docks` como `capacidad - mecanicas - electricas` únicamente cuando los valores sean válidos; documentar y contabilizar que no es un valor original del CSV.
- Registrar inventario, versión del origen, hashes/tamaños de archivos, rango temporal, estaciones, resultados y estado persistente de la importación.
- Ejecutar automáticamente el importador en el contenedor API de Compose/PRO, en segundo plano, con reintentos tras fallo y sin bloquear la disponibilidad general de la API.
- Exponer el estado de la importación en health/logs sin convertir un fallo histórico en una caída completa de la API.
- Añadir el comando `movilidad-import-history` con ejecución real, `--dry-run`, reintento seguro y `--force` explícito.
- Mantener la idempotencia con la clave existente `provider_id + station_id + observed_at`, evitando duplicados y registrando conflictos.
- Permitir consultar el histórico migrado más allá de la retención operativa de 90 días, respetando los límites de respuesta y paginación existentes.
- Documentar configuración, ejecución local, despliegue, autorización de datos, validación, rollback y procedencia.

### Excluido

- Cambios de frontend o nuevos contratos funcionales de `biki-stats-web`.
- Sincronización continua del repositorio de origen después de completar la primera importación.
- Purga o compactación de observaciones históricas.
- Corrección silenciosa de filas corruptas, timestamps ambiguos o valores fuera de rango.
- Publicación en PRO antes de confirmar los derechos de reutilización de los datos.

## Contexto y dependencias

- La arquitectura actual separa API, aplicación, dominio, infraestructura y collector; el importador será un caso de uso de aplicación con adaptador de origen GitHub y repositorio SQLite.
- `observations` ya tiene clave primaria `provider_id, station_id, observed_at`, `timestamp_ambiguous` y campos para las métricas necesarias.
- `station_history`, `history` y `summary` ya consultan observaciones por intervalo; la restricción de 90 días debe dejar de impedir el acceso al histórico permanente.
- SQLite se conserva en `/data/movilidad.sqlite3` en Compose, por lo que el estado de importación debe vivir en la misma base persistente.
- La API y el collector pueden arrancar a la vez; el importador necesitará una marca/lock propio para no competir ni duplicar la ingesta.
- La imagen actual no incluye Git; la obtención se hará por HTTP usando el árbol/commit de GitHub y descargas raw fijadas al SHA.
- La issue #4 define que los datos ausentes son `null`, no ceros, y que el histórico irregular no se interpola.

## Propuesta técnica (NO EJECUTAR)

1. **Configuración y origen**

   - Añadir configuración para activar el arranque (`BIKI_HISTORY_IMPORT_ON_STARTUP`), repositorio, rama/ref, intervalo de reintento y límites HTTP.
   - Compose/PRO activará el arranque automático; el valor por defecto al ejecutar la aplicación localmente será desactivado para que el desarrollo use el comando manual y los tests no dependan de red.
   - Resolver el SHA de `main` mediante GitHub, enumerar el árbol recursivo y seleccionar todos los CSV bajo `data/`. Descargar cada archivo desde la URL raw del SHA, conservando una manifest verificable.

2. **Modelo de estado y concurrencia**

   - Crear mediante Alembic y `ensure_schema` una tabla de importaciones históricas con clave lógica única, commit/ref, manifest, timestamps, estado (`pending`, `running`, `completed`, `failed`), contadores y error resumido.
   - Reclamar la ejecución en una transacción SQLite; una ejecución `completed` se omite. Una ejecución `running` se considera activa mientras no supere el timeout de recuperación; una ejecución abandonada se puede reintentar sin marcarla completada.
   - La importación se ejecutará como una captura lógica trazable, con `capture_id` propio y transacción por lotes. Un fallo no marca éxito; el siguiente reintento usa `INSERT OR IGNORE` y clasifica duplicados/conflictos.
   - Coordinar el inicio con la captura GBFS mediante el estado/lock de importación y logs; nunca borrar observaciones actuales ni sobrescribir una fila existente con valores históricos.

3. **Normalización y persistencia**

   - Leer cada CSV con `csv.DictReader` en streaming y validar exactamente `station_id,nombre,mecanicas,electricas,capacidad,timestamp`.
   - Crear/actualizar la estación `biki` con nombre normalizado, capacidad y sin inventar coordenadas; la captura GBFS podrá completar metadatos actuales posteriormente.
   - Convertir la hora local naive de `Europe/Madrid` a UTC; conservar `timestamp_ambiguous` y reportar las filas afectadas. Usar el instante de importación como `collected_at`, porque el origen no proporciona ese momento.
   - Calcular `free_docks` solo si la resta es válida y no negativa; no convertir ausencias o errores a cero. Registrar el recuento de valores derivados en el informe.
   - Para la misma clave temporal, clasificar como duplicado idéntico o conflicto de valores; conservar la primera observación válida y no reemplazar datos existentes silenciosamente.

4. **Arranque, reintentos y modo manual**

   - Lanzar desde el lifespan de la API una tarea en segundo plano cuando la opción esté activa. La API seguirá sirviendo consultas mientras el estado sea `pending`/`running`/`failed`.
   - Tras un fallo, registrar el error y reintentar con un intervalo configurable, sin crear tareas concurrentes. El apagado del contenedor cancela la tarea sin marcar éxito.
   - Añadir `movilidad-import-history`: por defecto omite una importación completada; `--dry-run` valida y genera el inventario sin escribir; `--force` permite reprocesar explícitamente manteniendo la deduplicación; los errores producen código de salida no cero.
   - Añadir el estado resumido de importación al health existente y logs estructurados con commit, estado, contadores y error, manteniendo `200` para la disponibilidad de la API.

5. **Consulta, documentación y operación**

   - Ajustar el límite temporal de histórico para que una ventana válida pueda alcanzar observaciones antiguas; conservar `limit`, granularidad y protección frente a respuestas excesivas.
   - Documentar el origen, el commit importado, el significado de `source`, el cálculo de `free_docks`, DST, huecos, estación 104, estado de licencia y procedimiento de backup/rollback.
   - Actualizar Docker/Compose y `.env.example` con la activación y parámetros del importador. La guía de PRO indicará que la autorización de datos es un prerrequisito antes de activar la opción públicamente.

## Dudas y decisiones

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| ¿Cómo obtener el origen? | Snapshot GitHub; clonar con Git; incluir CSV en la imagen | Snapshot HTTP fijado al commit SHA, sin Git en la imagen | Resuelta |
| ¿Qué archivos importar? | Todos los CSV de `data/`; solo archivo; solo índice | Todos los CSV descubiertos en el árbol del commit, incluidos archivados y activo | Resuelta |
| ¿Dónde guardar el histórico? | SQLite principal; base separada; almacenamiento externo | SQLite principal, proveedor `biki`, compatible con las consultas existentes | Resuelta |
| ¿Qué hacer si falla el arranque? | Bloquear API; API degradada; reintentar en segundo plano | API disponible, estado visible y reintentos en segundo plano | Resuelta |
| ¿Qué hacer durante la importación? | Bloquear histórico; bloquear toda API; servir progresivamente | API disponible y datos visibles progresivamente | Resuelta |
| ¿Cuándo activar automáticamente? | Todo arranque; solo contenedor/PRO; nunca | Solo Compose/PRO; desarrollo local manual por defecto | Resuelta |
| ¿Qué hace el comando tras completar? | Reprocesar; fallar; omitir | Omitir por defecto y permitir `--force` | Resuelta |
| ¿Cómo tratar DST ambiguo? | Rechazar; hora local; importar y marcar | Importar con primer `fold`, UTC y `timestamp_ambiguous=true` | Resuelta |
| ¿Cómo tratar `free_docks`? | `null`; derivar; cero | Derivar con fórmula válida y documentar que no es original | Resuelta |
| ¿Qué condición legal aplica? | Publicar; solo local; autorización previa | Implementar y probar; activar en PRO solo tras confirmar autorización y atribución | Resuelta |
| ¿Cómo distinguir duplicados? | Ignorar; sobrescribir; conflicto explícito | Clave existente; conservar primera fila, contar idénticos y conflictos | Resuelta |
| ¿Qué `collected_at` usar? | Igual a `observed_at`; hora de importación; `null` | Hora de importación, porque la captura original no está disponible | Resuelta |

## Pruebas y validación propuestas

- Parser con cabecera correcta, encoding, streaming, nombre con prefijo, números válidos, `null`/ausencias, rangos y filas corruptas.
- Normalización de fechas `Europe/Madrid`: UTC normal, hora inexistente, hora ambigua con flag y preservación de límites de archivo.
- Derivación válida de `free_docks`, rechazo de resultados negativos y ausencia de conversión ficticia a cero.
- Idempotencia: misma ejecución dos veces, duplicado idéntico entre archivos, conflicto de misma clave y observación actual protegida.
- Estado: primer arranque, importación completada, fallo, reintento, proceso abandonado, lock concurrente y apagado durante ejecución.
- `--dry-run`, `--force`, códigos de salida, resumen de contadores y ausencia de escritura en simulación.
- Descubrimiento de snapshot: commit, lista de archivos, hashes/tamaños, descarga parcial/fallida y manifest reproducible usando un cliente HTTP falso.
- API de histórico con datos anteriores a 90 días, datos actuales y huecos sin interpolación; health con estados de importación.
- Integración con SQLite/Alembic, volumen persistente Docker, arranque de Compose y reanudación tras recrear el contenedor.
- Validación completa: pytest, Ruff, Alembic, `scripts/validate.sh`, configuración Compose y prueba manual con fixture local sin depender del dataset remoto.

## Riesgos y criterios de aceptación

### Riesgos

- El snapshot actual supera cientos de MB; el importador debe ser streaming y el arranque puede tardar, por lo que se requieren logs de progreso y reintentos.
- GitHub o el origen pueden no estar disponibles; la API seguirá disponible, pero el histórico quedará visible como `failed` hasta recuperar la red.
- El repositorio origen no declara licencia; no activar la descarga pública en PRO sin autorización y atribución verificables.
- Dos procesos pueden compartir SQLite; la reclamación transaccional y la clave primaria deben evitar duplicados y bloqueos prolongados.
- `free_docks` derivado puede no representar exactamente los anclajes libres si el CSV no conserva toda la semántica; debe mostrarse como derivado en documentación y auditoría.

### Criterios de aceptación

- [ ] Un contenedor nuevo con volumen persistente descubre, valida, normaliza e importa todos los CSV del snapshot fijado, dejando inventario y manifest.
- [ ] Un segundo arranque con la misma base omite la importación completada y lo registra en logs/health.
- [ ] Un fallo no marca éxito; el proceso reintenta en segundo plano y puede recuperarse con el comando manual.
- [ ] La marca y el estado sobreviven a recrear el contenedor porque viven en SQLite persistente.
- [ ] No se duplican observaciones ni se sobrescriben datos actuales; duplicados y conflictos quedan contabilizados.
- [ ] Los valores originales se conservan, los nombres se normalizan, DST queda marcado y la estación 104 se documenta como ausente.
- [ ] `free_docks` solo se deriva con una fórmula válida y queda documentado como valor calculado.
- [ ] La ejecución manual soporta real, simulación y `--force`, con salida y códigos de error útiles.
- [ ] La API sigue disponible durante la importación y expone su estado sin romper el contrato existente.
- [ ] El histórico antiguo se consulta más allá de 90 días y los huecos no se rellenan ni interpolan.
- [ ] La documentación permite configurar local/PRO, hacer backup/rollback y verificar procedencia/licencia.
- [ ] Todas las pruebas automatizadas y la validación del repositorio pasan sin depender de red externa.

## Autorización expresa para empezar a escribir código

- [x] Todas las dudas resueltas.
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** `Implement the plan.` (usuario, 2026-10-20).

### Validación de implementación

- `pytest`: 23 tests superados.
- Ruff check y formato: superados.
- `scripts/validate.sh`: superado.
- Alembic y Compose config: superados.
- Snapshot GitHub: descubierto correctamente; simulación del CSV activo real: 100.464 filas válidas.
- Construcción Docker: iniciada con `scripts/validate.sh --docker-build`, pero detenida tras varios minutos sin salida durante la descarga/construcción.

**Mientras falte cualquiera de las condiciones anteriores, solo editar este documento.**
