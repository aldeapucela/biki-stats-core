# Plan de la issue #3: feat: definir la arquitectura de software del backend de Movilidad

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/3
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** AUTORIZADO PARA IMPLEMENTACIÓN
- **Rama futura:** `feat/3/arquitectura-backend` (todavía no creada)
- **Base de rama:** `main`
- **Modo Plan:** no disponible en esta sesión; se mantiene el flujo de análisis y autorización explícita definido por el repositorio.

## Resumen verificable de la issue

La issue #3 solicita definir y aprobar la arquitectura técnica de `biki-stats-core` antes de desarrollar código: capas, responsabilidades, dependencias, persistencia SQLite, captura GBFS, configuración, despliegue Docker y pruebas.

Requisitos confirmados en la issue:

- Python + FastAPI + SQLite, con despliegue mediante Docker.
- Captura de GBFS cada 5 minutos; la frecuencia de captura no debe confundirse con el polling del frontend.
- El recolector debe ejecutarse de forma independiente de la API y controlar solapamientos, reintentos, fallos parciales, sello temporal e idempotencia.
- Debe conservarse el histórico, incluida la migración prevista en la issue #1, sin perder observaciones ni asumir intervalos uniformes.
- La arquitectura debe poder incorporar otros proveedores de movilidad además de BIKI.
- La API debe separar routers/dependencias/respuestas/errores, aplicación, dominio, infraestructura, collector, schemas y configuración/observabilidad.
- La issue #4 definirá posteriormente rutas y contratos JSON; este plan debe prever sus límites e integración, pero no implementarlos ni cerrarlos por adelantado.
- Código AGPL-3.0-only; la procedencia, autorización y licencia de datos externos deben verificarse antes de redistribuirlos.

## Alcance confirmado y exclusiones

### Incluido en esta issue

- Documento de arquitectura para nuevas personas colaboradoras, con diagrama de componentes y flujos.
- Estructura modular propuesta y límites entre API, aplicación, dominio, infraestructura, collector, schemas y core.
- Interfaces de repositorios y proveedores que permitan sustituir SQLite, GBFS o BIKI sin contaminar el dominio.
- Estrategia de SQLite: transacciones, WAL, índices, migraciones, copias/recuperación y convivencia entre captura e histórico.
- Diseño operativo del recolector independiente, su ejecución cada 5 minutos, reintentos, backoff, idempotencia, solapamientos y observabilidad.
- Política de separación entre snapshots operativos recientes e histórico permanente, compatible con #1.
- Configuración, secretos, CORS, health checks, Docker y perfiles de ejecución.
- Estrategia de pruebas unitarias, integración, contrato y fixtures deterministas.
- Dependencias y decisiones pendientes que deben cerrarse antes de codificar.

### Fuera de alcance

- Implementar código, tests, migraciones, Dockerfiles, dependencias, scripts o configuración.
- Implementar las rutas o los contratos JSON de la issue #4.
- Ejecutar la migración de #1 o importar datos de terceros.
- Diseñar la SPA, la cartografía o su frecuencia de consulta.
- Fijar nombres finales de rutas, campos JSON, códigos de error o agregaciones sin aprobarlos en #4.
- Incorporar autenticación, operaciones de alquiler/reserva u otros flujos transaccionales.

## Contexto y dependencias

- El repositorio está en preparación, sobre `main`, sin código funcional de aplicación.
- Documentación revisada: `README.md`, `docs/GUIA_DESARROLLO.md`, `docs/PROCEDENCIA_DATOS.md`, `CONTRIBUTING.md`, `AGENTS.md` y la skill de planificación.
- La issue #1 describe CSV con `station_id,nombre,mecanicas,electricas,capacidad,timestamp`, timestamps locales `Europe/Madrid` sin offset explícito, intervalos irregulares, posible ausencia de la estación 104 y necesidad de preservar procedencia, valores ausentes, hashes, reanudación e idempotencia.
- La issue #4 propone una API pública de solo lectura, prefijo `/api/v1`, respuestas envolventes coherentes y consultas actuales, cercanas e históricas. Sus decisiones permanecen pendientes en esa issue.
- La issue `biki-stats-web#1` necesita datos reales de la API, histórico 24 h/7 d/30 d/90 d y estados de frescura/sin datos; no autoriza a cerrar sus contratos desde esta issue.
- Fuente GBFS documentada: `https://valladolid.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json`.
- Debe verificarse la autorización y licencia del histórico procedente de `serherval/flujosbiki` antes de publicarlo.

## Propuesta técnica (NO EJECUTAR)

### 1. Componentes y flujo

```text
             ┌──────────────────────────────┐
             │ Proveedor GBFS / futuro API   │
             └──────────────┬───────────────┘
                            │ fetch + normalización
                            v
┌──────────────────┐  ┌───────────────┐  ┌─────────────────────────┐
│ Collector        │─>│ Application   │─>│ Infrastructure          │
│ proceso separado │  │ ingest usecase│  │ SQLite + repositorios   │
└────────┬─────────┘  └───────────────┘  └────────────┬────────────┘
         │ métricas/logs                              │ lecturas
         v                                             v
┌──────────────────┐                          ┌──────────────────────┐
│ Core observability│                          │ Application consultas │
│ + configuración   │                          └──────────┬───────────┘
└──────────────────┘                                     │
                                                         v
                                              ┌──────────────────────┐
                                              │ API FastAPI solo GET │
                                              │ routers + schemas    │
                                              └──────────────────────┘
```

La API y el collector compartirían dominio, casos de uso e interfaces, pero tendrían puntos de entrada y ciclos de vida independientes. El collector escribiría snapshots mediante un caso de uso de ingestión; la API leería mediante casos de uso de consulta. Ninguna capa superior debería depender directamente de SQL, `httpx` o modelos GBFS.

### 2. Estructura modular propuesta

```text
src/movilidad/
  api/
    main.py                 # factoría/entrada FastAPI
    routers/                # rutas versionadas; contratos se concretan en #4
    dependencies.py         # composición de dependencias y sesiones
    responses.py            # envoltorios/respuestas comunes aprobados
    errors.py               # traducción de errores de aplicación
  application/
    services/               # consultas y operaciones coordinadas
    use_cases/              # ingestión, estado actual, histórico y agregados
    ports/                  # puertos de repositorios/proveedores/reloj
  domain/
    entities/               # estación, disponibilidad, observación
    value_objects/          # identificadores, timestamps, tipos y cantidades
    rules/                  # invariantes y cálculos sin I/O
    exceptions.py
  infrastructure/
    db/                     # conexión SQLite, migraciones, transacciones
    repositories/           # implementaciones de puertos
    providers/gbfs/         # cliente y adaptadores GBFS por proveedor
    observability/          # logging/métricas/trazas concretas
  collector/
    main.py                 # entrada del proceso de captura
    scheduler.py            # intervalo de 5 minutos y exclusión mutua
    pipeline.py             # fetch -> validar -> normalizar -> persistir
  schemas/
    api/                    # Pydantic público; se cierra en #4
    internal/                # DTOs de ingestión y persistencia
  core/
    config.py               # settings por entorno/variables
    logging.py              # logging estructurado y request/capture IDs
    health.py               # checks de proceso, base y última captura
```

La ubicación exacta de módulos podrá ajustarse durante la implementación si mantiene estos límites. `schemas` no sustituye a las entidades de dominio: los DTOs se validan en los bordes y se convierten explícitamente a objetos de dominio.

### 3. Dominio y datos

- Separar metadatos de estación de los hechos de disponibilidad observados. Una estación puede cambiar nombre, capacidad, estado o proveedor sin reescribir observaciones pasadas.
- Modelar contadores como cantidades no negativas y permitir `None` cuando el origen desconoce un valor; nunca transformar desconocido en cero.
- Conservar `observed_at` del proveedor, `collected_at` del sistema y la procedencia de cada observación. Guardar la zona/origen original cuando el timestamp no sea inequívoco.
- Representar el proveedor y su identificador en la identidad lógica, para evitar colisiones cuando se incorporen más operadores.
- Dejar las reglas de ocupación y agregación como funciones de dominio deterministas, con capacidad variable y huecos explícitos. Las decisiones de contrato y promedio se aprobarán en #4.

### 4. Persistencia SQLite

Propuesta inicial, pendiente de validar con la migración de #1:

- Un archivo SQLite principal para operación y consulta, con tablas separadas para proveedores, estaciones/metadatos, observaciones y ejecuciones de captura/importación.
- La conservación a largo plazo no dependerá de purgar observaciones históricas: la retención operativa de 90 días, si se aprueba, afectará solo a snapshots o datos derivados claramente identificados.
- Índices compuestos orientados a `provider_id + station_id + observed_at`, además de índices para rangos temporales y consultas de estado actual.
- Claves de idempotencia explícitas, incluyendo procedencia/origen y una identidad de observación; los duplicados se resolverán de forma determinista sin sobrescribir silenciosamente valores distintos.
- WAL, transacciones cortas y una sola unidad de escritura coordinada para el collector; las lecturas de la API deben tolerar una captura en curso.
- Migraciones versionadas y reproducibles, ejecutadas antes de levantar API/collector; copias, integridad y restauración deberán documentarse.
- Importación de #1 mediante un adaptador separado, conservando archivos/ref/hashes e informes, sin mezclar la lógica CSV con el cliente GBFS.

### 5. Collector y proveedores

- El collector será un proceso/servicio Docker separado del proceso web, con ejecución configurada cada 5 minutos y posibilidad de ejecución manual controlada.
- La interfaz de proveedor abstraerá descubrimiento/descarga de feeds, parseo y mapeo a un modelo normalizado; el adaptador GBFS de BIKI será la primera implementación.
- El pipeline tendrá límites de tiempo, reintentos con backoff y jitter, validación de esquema/valores, registro de filas rechazadas y resultado parcial por feed/estación.
- Se impedirá el solapamiento mediante lock/advisory file o mecanismo equivalente compatible con el despliegue elegido; la alternativa final dependerá del entorno de producción.
- Cada corrida tendrá un `capture_id`, hora de inicio/fin, configuración/proveedor, estado, error resumido y contadores. Un fallo de un feed no debe convertir datos antiguos en datos frescos.
- La captura no se presentará como tiempo real: la API expondrá frescura según la observación y la última captura, conforme al contrato que apruebe #4.
- Los proveedores futuros deben poder añadirse como adaptadores sin modificar reglas centrales ni routers.

### 6. API, schemas y contratos

- FastAPI compondrá dependencias desde `core.config`, repositorios y casos de uso; los routers no realizarán SQL ni llamadas GBFS.
- Los modelos Pydantic públicos vivirán en `schemas/api` y se mantendrán alineados con OpenAPI.
- Los nombres, rutas, envoltorio `status/code/data/errors`, `meta`, paginación, errores y estados HTTP se decidirán en #4. Este plan solo reserva sus puntos de integración.
- La API será solo lectura en el primer alcance, con CORS limitado a los orígenes aprobados y cabeceras de trazabilidad sin exponer detalles internos.

### 7. Configuración, seguridad y observabilidad

- Settings tipados por entorno y variables de entorno; valores seguros por defecto, sin secretos en el repositorio ni en logs.
- Configuraciones separadas para desarrollo, test y producción, incluyendo URL/feeds GBFS, intervalo, ruta de SQLite, CORS, timeouts, retención y nivel de logs.
- Logging estructurado JSON con `request_id` y `capture_id`, eventos de inicio/fin, latencias, conteos y errores sanitizados. No registrar tokens ni payloads innecesarios.
- Health checks diferenciando proceso vivo, capacidad de servir y estado de dependencias/última captura; no declarar saludable al proveedor externo si la API aún puede servir histórico, salvo decisión operativa contraria.
- Métricas mínimas: duración y resultado de captura, edad de la observación más reciente, errores por proveedor/feed, filas aceptadas/rechazadas y latencia de consultas.

### 8. Docker y operación

- Imagen reproducible con un mismo paquete de aplicación y entradas diferenciadas para API y collector.
- Contenedores/procesos separados, volumen persistente para SQLite y directorio de backups fuera de la imagen.
- El scheduler debe poder reiniciarse sin duplicar observaciones; las políticas de restart, backup y migración se documentarán junto al despliegue.
- La arquitectura no presupone Kubernetes ni servicios gestionados: se prioriza una operación pequeña y comprensible para un proyecto comunitario. Si el proveedor de hosting exige otro scheduler, solo debe cambiar el adaptador operativo, no el pipeline.

### 9. Pruebas previstas

- Unitarias: invariantes del dominio, normalización, timestamps, cálculos y deduplicación con reloj inyectable.
- Integración: repositorios contra SQLite temporal, transacciones, índices, migraciones, WAL y concurrencia básica API/collector.
- Collector: feeds simulados/fixtures locales, timeouts, reintentos, payload inválido, fallo parcial, ejecución repetida y solapamiento.
- Contrato: esquemas y respuestas FastAPI una vez aprobada #4; ejemplos de éxito, error, vacío y datos obsoletos.
- Operación: arranque de imágenes Docker, health checks, configuración por entorno y recuperación desde backup en un entorno de prueba.
- No depender de la red ni del feed GBFS real en la suite automatizada.

## Dudas y decisiones (resolver TODAS antes de codificar)

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| ¿Dónde conservar permanentemente el histórico de #1? | Misma SQLite con tablas/particiones lógicas; archivo SQLite histórico separado; otro almacén | SQLite única con separación lógica entre histórico permanente y snapshots operativos | Resuelta |
| ¿Qué política de retención se aplicará a snapshots y derivados? | Sin purga; purgar solo derivados/snapshots recientes; archivar antes de purgar | No purgar observaciones históricas ni datos heredados | Resuelta |
| ¿Cómo resolver timestamps ambiguos de `Europe/Madrid` del CSV legado? | Rechazar y reportar; conservar wall time como ambiguo; elegir offset mediante regla externa | Conservar y marcar la ambigüedad; no inventar el instante | Resuelta |
| ¿Dónde se ejecuta el scheduler de 5 minutos? | Contenedor collector con scheduler interno; cron externo que lance una ejecución; scheduler del proveedor | GitHub Actions programado lanza el comando del collector desde un runner autoalojado | Resuelta |
| ¿Cómo se evita el solapamiento? | Lock de archivo; lock transaccional SQLite; coordinación externa | Lock en SQLite más idempotencia; GitHub Actions también puede serializar workflows | Resuelta |
| ¿Qué volumen esperado y concurrencia se dimensionan? | Una escritura secuencial y lecturas SQLite; cola/proceso de escritura; migración a otro motor | SQLite con WAL, una escritura coordinada y lecturas concurrentes | Resuelta |
| ¿Qué proveedor de despliegue y dominio/orígenes CORS se usarán? | Un único origen aprobado; lista por entorno; wildcard público | Lista explícita por entorno: producción y orígenes locales configurables | Resuelta |
| ¿La API será pública sin autenticación y tendrá límites? | Pública sin auth y límites en proxy; API key; autenticación futura | API pública de solo lectura; rate limiting/cache en proxy o servidor | Resuelta |
| ¿Qué herramienta de migraciones y gestión de dependencias adoptar? | Alembic + `pyproject.toml`; migraciones SQL versionadas; otra herramienta | `pyproject.toml` + Alembic | Resuelta |
| ¿Qué logging y correlación requiere #4? | JSON con `request_id` en cabecera; JSON solo interno; incluirlo también en `meta` | Logs JSON + `X-Request-ID`; decidir en #4 si se refleja también en `meta` | Resuelta |
| ¿Cómo se identifica una observación única? | proveedor+estación+observed_at; proveedor+estación+observed_at+hash; ID de captura | Proveedor + estación + `observed_at`; conservar `capture_id` y registrar conflictos | Resuelta |
| ¿Qué alcance tiene la primera arquitectura frente a otros proveedores? | Solo BIKI; interfaz GBFS genérica; adaptadores GBFS y no-GBFS desde el inicio | Puerto genérico + adaptador GBFS BIKI; sin soporte no-GBFS inicial | Resuelta |

## Pruebas y validación propuestas

Antes de implementar, validar que el plan responde a todos los criterios de #3 y no fija decisiones reservadas a #4. Tras la autorización, la implementación deberá demostrar como mínimo:

1. El diagrama y la estructura modular no permiten que routers o dominio dependan directamente de SQLite/HTTP.
2. API y collector pueden arrancar por separado con la misma configuración y puertos de aplicación.
3. Dos ejecuciones del collector con el mismo feed son idempotentes y una ejecución concurrente no duplica observaciones.
4. Un fallo de red o de un feed conserva la última observación válida y deja trazabilidad de la captura fallida.
5. Los valores desconocidos, timestamps ambiguos y huecos históricos no se convierten en ceros ni observaciones inventadas.
6. El histórico migrado y las observaciones nuevas son consultables sin purga accidental y con procedencia diferenciada.
7. Los tests no requieren acceso a GBFS real y las migraciones/restauración se prueban en SQLite temporal.
8. Docker conserva la base en un volumen y expone health checks/logs suficientes para operación comunitaria.

## Riesgos y criterios de aceptación

### Riesgos

- SQLite puede quedar limitado por volumen, backups o escritura concurrente; se mitiga con WAL, una escritura coordinada, índices y medición antes de cambiar de motor.
- El histórico legado tiene timestamps locales irregulares y sin licencia declarada; no debe publicarse ni normalizarse silenciosamente.
- Los feeds GBFS pueden cambiar de versión/esquema o fallar parcialmente; el adaptador debe validar y aislar errores.
- El polling frecuente del frontend podría confundirse con frescura real; la API y documentación deben distinguir `observed_at`, `collected_at` y edad del dato.
- Un scheduler en Docker puede duplicar ejecuciones al reiniciar; el lock y la idempotencia son obligatorios.
- Cerrar rutas o campos en #3 crearía acoplamiento con #4; la arquitectura debe exponer puertos, no contratos definitivos.

### Criterios de aceptación de la issue #3

- Existe un documento comprensible con diagrama, componentes, límites, interfaces y alternativas descartadas.
- La estrategia SQLite documenta claves/índices, WAL, transacciones, migraciones, backups, recuperación y convivencia con #1.
- La captura se ejecuta independientemente de la API cada 5 minutos, con reintentos, control de solapamiento, idempotencia, fallos parciales y observabilidad.
- Se diferencia histórico permanente de retención operativa y se preserva la procedencia del histórico legado.
- Se definen configuración, Docker, CORS, health checks, seguridad, logs y métricas sin secretos.
- Se define una arquitectura extensible a más proveedores sin introducir abstracciones no necesarias para el MVP.
- Se explicita la dependencia de contratos y logging de #4 sin implementarlos.
- Se documentan pruebas unitarias, integración, collector, contrato y operación, con fixtures sin red.
- Todas las dudas de la tabla se resuelven y el plan queda aprobado antes de crear rama o escribir código.

## Autorización expresa para empezar a escribir código

- [x] Todas las dudas resueltas.
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** `Implement the plan.` (usuario, 2026-10-15)

**Mientras falte cualquiera de las condiciones anteriores, solo editar este documento.**
