# Arquitectura del backend

La aplicación se divide en dos procesos operativos: `api` sirve consultas HTTP y `collector` captura datos GBFS. Ambos comparten dominio, casos de uso y repositorios, pero no comparten ciclo de vida. La API también expone un disparador operativo protegido para que GitHub Actions solicite capturas remotas sin acceder al volumen SQLite.

```text
                         GitHub Actions
                              |
                              | HTTPS + Bearer
                              v
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

GitHub Actions programa el workflow cada cinco minutos y solicita la captura mediante `POST /api/v1/ops/collector/run` sobre HTTPS. El endpoint requiere `Authorization: Bearer` con `BIKI_COLLECTOR_TOKEN`, no aparece en OpenAPI y responde con el resultado de la captura. El retraso de algunos minutos es admisible: la frescura se mide con `observed_at` y `collected_at`.

El collector registra cada corrida y adquiere un lock por proveedor en SQLite. La clave de observación es `provider_id + station_id + observed_at`; repetir un feed no duplica observaciones. Los fallos liberan el lock y dejan la corrida en estado `failed`.

## Histórico y operación

El histórico permanente comparte la base con la operación, pero sus hechos se mantienen separados de los metadatos actuales. No se purgan observaciones históricas. Las copias deben ser diarias y también ejecutarse antes de migraciones o importaciones.

La importación inicial de `serherval/flujosbiki` descubre todos los CSV de `data/` en un commit
fijado, los procesa en streaming y registra el inventario y el resultado en
`historical_imports`. El proveedor consultable sigue siendo `biki` y la procedencia se conserva
en `source=flujosbiki`. La marca de importación completada vive en SQLite, por lo que sobrevive a
recrear el contenedor. Compose puede lanzarla en segundo plano al arrancar; en desarrollo se usa
`movilidad-import-history --dry-run` o `movilidad-import-history`.

El CSV no contiene anclajes libres: cuando capacidad y ambos contadores son válidos se calcula
`free_docks = capacidad - mecanicas - electricas`, y ese valor debe documentarse como derivado.
Las horas locales se convierten desde `Europe/Madrid` a UTC; las horas ambiguas se conservan con
`timestamp_ambiguous=true` y las inexistentes se rechazan con informe.

El backup se puede crear con `python scripts/backup_sqlite.py backups/movilidad-$(date +%F).sqlite3`. El destino debe quedar fuera del volumen de la aplicación y su restauración debe comprobarse periódicamente.

En producción se ejecuta `alembic upgrade head` antes de arrancar los servicios. El arranque de la aplicación usa una creación defensiva de tablas para desarrollo local y tests.

La API pública es de solo lectura y acepta peticiones web desde `https://biki.aldeapucela.org` y los orígenes localhost configurados para desarrollo. El endpoint operativo está separado bajo `/ops` y protegido exclusivamente por Bearer; al no ser una llamada web de la aplicación, no depende de la validación de origen. El rate limiting se configura en el proxy o servidor. Las rutas de negocio y sus envoltorios JSON se definirán en la issue #4.
