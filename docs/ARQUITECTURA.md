# Arquitectura del backend

La aplicación se divide en dos procesos operativos: `api` sirve consultas HTTP y `collector` captura datos GBFS. Ambos comparten dominio, casos de uso y repositorios, pero no comparten ciclo de vida. Compose ejecuta ambos servicios con una imagen y volumen SQLite compartidos. La API también expone un disparador manual opcional protegido por token.

```text
GBFS -> collector -> application -> SQLite <- application <- API FastAPI
          |              |             |                  |
       capture_id     dominio       WAL/locks        schemas Pydantic
```

## Capas

- `domain`: entidades e invariantes, sin red ni base de datos.
- `application`: casos de uso y puertos (`Protocol`) para repositorios y proveedores.
- `infrastructure`: SQLite, migraciones Alembic y adaptador GBFS.
- `collector`: pipeline `fetch -> validar -> normalizar -> persistir`.
- `api`: composición FastAPI, CORS, request ID y routers versionados.
- `schemas`: reservado para los contratos públicos de la issue #4.
- `core`: configuración tipada y logs JSON.

## Captura

El servicio `collector` ejecuta `movilidad-collector --loop`, sin puertos y sin dependencia de la API. Captura inmediatamente y espera `BIKI_CAPTURE_INTERVAL_SECONDS` tras cada intento; registra excepciones y reintenta tras el intervalo. SIGTERM/SIGINT permiten terminar la captura activa e interrumpen la espera. Compose concede 120 segundos de gracia (ajustables si aumenta el timeout HTTP); SIGKILL puede interrumpir una captura y no se cambia la recuperación de locks existente. La CLI sin argumentos sigue ejecutando una sola captura y propaga errores.

No se necesita GitHub Actions, cron ni secretos de GitHub para capturar. El endpoint manual `POST /api/v1/ops/collector/run` requiere `Authorization: Bearer` con `BIKI_COLLECTOR_TOKEN`; sin token configurado está deshabilitado (`503`). La frescura se mide con `observed_at` y `collected_at`.

El collector registra cada corrida y adquiere un lock por proveedor en SQLite. La clave de observación es `provider_id + station_id + observed_at`; repetir un feed no duplica observaciones. Los fallos liberan el lock y dejan la corrida en estado `failed`.

## Histórico y operación

El histórico permanente comparte la base con la operación, pero sus hechos se mantienen separados de los metadatos actuales. No se purgan observaciones históricas. Las copias deben ser diarias y también ejecutarse antes de migraciones o importaciones.

La importación inicial de `serherval/flujosbiki` descubre todos los CSV de `data/` en un commit
fijado, los procesa en streaming y registra el inventario y el resultado en
`historical_imports`. El proveedor consultable sigue siendo `biki` y la procedencia se conserva
en `source=flujosbiki`. La marca de importación completada vive en SQLite, por lo que sobrevive a
recrear el contenedor. Solo la API de Compose la lanza en segundo plano al arrancar; el collector no importa histórico; en desarrollo se usa
`movilidad-import-history --dry-run` o `movilidad-import-history`.

El CSV no contiene anclajes libres: cuando capacidad y ambos contadores son válidos se calcula
`free_docks = capacidad - mecanicas - electricas`, y ese valor debe documentarse como derivado.
Las horas locales se convierten desde `Europe/Madrid` a UTC; las horas ambiguas se conservan con
`timestamp_ambiguous=true` y las inexistentes se rechazan con informe.

El backup se puede crear con `python scripts/backup_sqlite.py backups/movilidad-$(date +%F).sqlite3`. El destino debe quedar fuera del volumen de la aplicación y su restauración debe comprobarse periódicamente.

En producción se ejecuta `alembic upgrade head` antes de arrancar los servicios. El arranque de la aplicación (y los puntos de entrada del collector y de la importación) usa una creación defensiva de tablas y fija `journal_mode=WAL` **una sola vez** (`init_database`); las peticiones HTTP solo abren la conexión con los pragmas por conexión (`foreign_keys`, `busy_timeout`).

La API pública es de solo lectura y acepta peticiones web desde `https://biki.aldeapucela.org` y los orígenes localhost configurados para desarrollo. El endpoint operativo está separado bajo `/ops` y protegido exclusivamente por Bearer; al no ser una llamada web de la aplicación, no depende de la validación de origen. El rate limiting se configura en el proxy o servidor. Las rutas de negocio y sus envoltorios JSON se definirán en la issue #4.

## Rendimiento de las consultas históricas

`/history` con `hour` o `day` y `/summary` no cargan las observaciones en Python: SQLite las agrupa (por franja UTC, capacidad y anclajes libres en `history`; por contadores iguales en `summary`) y el servicio reduce esos grupos. `raw` sigue devolviendo una fila por observación. Con un solo worker, el coste de una petición se reparte así (medido sobre ~66 000 observaciones por estación): antes dominaba Python (crear objetos y calcular, más de 1,5 s en 30 días) y las peticiones concurrentes se encolaban; ahora SQL agrupa en decenas de milisegundos.

Los resultados son los mismos que con el cálculo anterior fila a fila (`tests/reference_history.py` lo conserva como referencia). La ocupación media se acumula en céntimos enteros; solo en un empate exacto de redondeo (p. ej. media 85,835) se repite la suma original sobre las filas de esa franja, porque ahí el resultado dependía de la coma flotante.

Cada consulta deja un registro `consulta histórica` con `kind`, `station_id`, `granularity`, `duration_ms` (total), `sql_ms`, `rows` (observaciones leídas) y `groups` (grupos procesados).

Para medir una versión: `python scripts/bench_history.py` genera una base sintética, levanta uvicorn con un worker y lanza clientes concurrentes. `--src` apunta al `src/` de otra versión y `--database` reutiliza la misma base para comparar. No está en el CI porque los tiempos dependen de la máquina.
