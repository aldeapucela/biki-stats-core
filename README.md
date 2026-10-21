# BIKI · biki-stats-core

Backend de código abierto de [Aldea Pucela](https://aldeapucela.org/) para informar sobre las estaciones del servicio BIKI de Valladolid.

**Estado:** arquitectura base implementada: API FastAPI, collector GBFS, SQLite/Alembic y despliegue Docker.

- **Issues de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues (para dependencias cruzadas, enlazar las issues del otro repositorio por URL).
- [Cómo contribuir](CONTRIBUTING.md) · [Guía de desarrollo](docs/GUIA_DESARROLLO.md)
- [Arquitectura](docs/ARQUITECTURA.md)
- [Contrato de API v1](docs/API_V1.md)
- [Instrucciones de Codex](AGENTS.md) · [Skill de planificación](.agents/skills/github-issue-plan-first/SKILL.md)
- **Código:** [AGPL-3.0-only](LICENSE). **Datos propios autorizados:** [CC BY-SA 4.0](DATA_LICENSE.md), respetando derechos de terceros.

## Desarrollo local

Requisitos: Python 3.11 o superior. Docker solo es necesario para probar la imagen y Compose.

Configura el entorno Python:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Para levantar la API en modo desarrollo:

```bash
.venv/bin/uvicorn movilidad.api.main:app --reload --host 127.0.0.1 --port 8000
```

Comprueba el servicio:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Para ejecutar una captura GBFS manual contra el feed configurado:

```bash
.venv/bin/movilidad-collector
```

Para importar manualmente el histórico de `flujosbiki` en desarrollo:

```bash
.venv/bin/movilidad-import-history --dry-run
.venv/bin/movilidad-import-history
```

La primera orden descarga el snapshot fijado y valida los CSV sin modificar SQLite. La segunda
importa el histórico de forma idempotente. Si ya terminó correctamente, se omite; usa
`--force` únicamente para reprocesarlo explícitamente. El comando devuelve un resumen con
aceptados, duplicados, conflictos, rechazos y valores derivados.

La captura escribe en `./data/movilidad.sqlite3`. Para probar el endpoint remoto en local, define `BIKI_COLLECTOR_TOKEN` en `.env` y usa:

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  --header "Authorization: Bearer ${BIKI_COLLECTOR_TOKEN}" \
  http://127.0.0.1:8000/api/v1/ops/collector/run
```

Ejecuta las comprobaciones antes de abrir una PR:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
./scripts/validate.sh
```

La API expone `GET /api/v1/health`, las rutas de estaciones e histórico y el endpoint operativo protegido del collector.

## Variables de configuración

El archivo [.env.example](.env.example) contiene una plantilla. En local se copia a `.env`; en producción se crea un `.env` en el servidor y no se versiona.

| Variable | Valor por defecto de la aplicación | Uso |
| --- | --- | --- |
| `BIKI_ENV` | `development` | Entorno de ejecución. En producción usar `production`. |
| `BIKI_DATABASE_PATH` | `./data/movilidad.sqlite3` | Ruta SQLite. Compose la fija a `/data/movilidad.sqlite3`. |
| `BIKI_CORS_ORIGINS` | `http://localhost:5173,http://localhost:5174,https://biki.aldeapucela.org` | Orígenes permitidos separados por comas. En producción usar `https://biki.aldeapucela.org`. No se aplica como requisito de origen al endpoint Bearer del collector. |
| `BIKI_GBFS_URL` | Feed GBFS de BIKI Valladolid | URL de descubrimiento GBFS. |
| `BIKI_CAPTURE_INTERVAL_SECONDS` | `300` | Espera entre el final de un intento y el inicio del siguiente en modo `--loop`. |
| `BIKI_HTTP_TIMEOUT_SECONDS` | `20` | Timeout de las peticiones al proveedor GBFS. |
| `BIKI_LOG_LEVEL` | `INFO` | Nivel de logs. |
| `BIKI_COLLECTOR_TOKEN` | Vacío / endpoint desactivado | Token Bearer del endpoint operativo. Debe ser secreto en producción. |
| `BIKI_HISTORY_IMPORT_ON_STARTUP` | `false` | Activa la importación histórica automática. Compose la activa para la API. |
| `BIKI_HISTORY_SOURCE_REPOSITORY` | `serherval/flujosbiki` | Repositorio GitHub del histórico. |
| `BIKI_HISTORY_SOURCE_REF` | `main` | Rama o referencia cuyo commit se fija al comenzar la importación. |
| `BIKI_HISTORY_IMPORT_RETRY_SECONDS` | `300` | Espera entre reintentos automáticos tras un fallo. |

Compose aplica valores de producción propios para `BIKI_ENV`, CORS, GBFS, timeout y logging. La variable `BIKI_DATABASE_PATH` y el volumen `/data` no deben cambiarse sin actualizar también la persistencia de la API.

## Docker

```bash
docker compose up --build api collector
```

Compose construye una imagen local compartida desde el `Dockerfile` para dos servicios independientes: API y collector periódico, con el mismo volumen SQLite. El collector no publica puertos ni depende del healthcheck de la API. Las migraciones de producción se ejecutan con `alembic upgrade head`. Consulta [la documentación de arquitectura](docs/ARQUITECTURA.md) para histórico, locks, backups y observabilidad.

Para ejecutar la validación completa local usa `scripts/validate.sh`. Añade `--docker-build` para construir manualmente la imagen y `--live-feed` para consultar el feed GBFS real.

La integración continua ejecuta esta validación en todas las ramas y pull requests. Los cambios publicados en `main` calculan la siguiente versión a partir de Conventional Commits y crean un tag `x.y.z`.

## Despliegue en PRO

La API necesita una base de datos SQLite persistente. Un segundo contenedor, `collector`, captura directamente desde GBFS y escribe en la misma SQLite; no necesita token ni GitHub Actions. La API importa automáticamente el histórico al arrancar por primera vez y guarda el estado en SQLite; los siguientes arranques lo omiten. Crea un archivo `.env` junto a `docker-compose.yml`:

```dotenv
BIKI_ENV=production
BIKI_CORS_ORIGINS=https://biki.aldeapucela.org
BIKI_GBFS_URL=https://valladolid.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json
BIKI_CAPTURE_INTERVAL_SECONDS=300
BIKI_HTTP_TIMEOUT_SECONDS=20
BIKI_LOG_LEVEL=INFO
BIKI_HISTORY_IMPORT_ON_STARTUP=true
BIKI_HISTORY_SOURCE_REPOSITORY=serherval/flujosbiki
BIKI_HISTORY_SOURCE_REF=main
BIKI_HISTORY_IMPORT_RETRY_SECONDS=300
```

Antes de activar esta opción en PRO debe estar confirmada la autorización para reutilizar y
publicar el histórico de `flujosbiki`, junto con la atribución correspondiente. El origen no
declara una licencia por defecto.

`BIKI_DATABASE_PATH` no es necesario definirlo en el `.env`: Compose lo fija a `/data/movilidad.sqlite3` dentro de los contenedores. El volumen `movilidad-data` conserva la base de datos aunque se reconstruya el contenedor.

Construye la imagen local y levanta ambos servicios:

```bash
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d --no-build api collector
```

Comprueba el estado y los logs:

```bash
curl http://localhost:8004/api/v1/health
docker compose ps
docker compose logs -f api collector
```

Compose publica el puerto de la API exclusivamente en `127.0.0.1` del servidor
(`8004` por defecto, configurable con `PORT`), para que el acceso público pase por
Nginx y no se exponga directamente el backend. Esta restricción de entrada no
impide las conexiones salientes para consultar GBFS o importar el histórico y no
cambia la persistencia del volumen SQLite.

El reverse proxy del mismo servidor debe publicar la API bajo `https://api.aldeapucela.org/biki/` y permitir el origen `https://biki.aldeapucela.org`.

### Caché de Nginx

La API devuelve `ETag` y `Cache-Control: public, max-age=30`. Para reducir consultas repetidas
desde el frontend, configura Nginx para cachear únicamente las respuestas de lectura durante
30 segundos. La caché debe estar en el contexto `http` y las ubicaciones en el `server` HTTPS
que ya publica `/biki/`:

```nginx
# Contexto http {}
proxy_cache_path /var/cache/nginx/biki
    levels=1:2
    keys_zone=biki_api:10m
    max_size=128m
    inactive=5m
    use_temp_path=off;

upstream biki_api {
    server 127.0.0.1:8004;
}

# Contexto server {}
location = /biki/api/v1/health {
    proxy_pass http://biki_api/api/v1/health;
    proxy_cache off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /biki/api/v1/ops/collector/run {
    proxy_pass http://biki_api/api/v1/ops/collector/run;
    proxy_cache off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;
}

location /biki/ {
    proxy_pass http://biki_api/;
    proxy_cache biki_api;
    proxy_cache_methods GET HEAD;
    proxy_cache_valid 200 30s;
    proxy_cache_valid 404 5s;
    proxy_cache_lock on;
    proxy_cache_revalidate on;
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    proxy_cache_bypass $http_authorization;
    proxy_no_cache $http_authorization $upstream_http_set_cookie;
    add_header X-Cache-Status $upstream_cache_status always;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

No uses `proxy_ignore_headers Cache-Control`, `ETag` ni `Set-Cookie`: la aplicación ya marca
la frescura y las respuestas condicionadas. Comprueba el comportamiento con el encabezado
`X-Cache-Status` (`MISS`, `HIT` o `BYPASS`) y no caches nunca el endpoint `POST` protegido.

### Modificaciones en PRO

Para actualizar la versión desplegada, actualiza el código del repositorio, reconstruye los servicios y recrea los contenedores:

```bash
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d --no-build api collector
```

El volumen `movilidad-data` no se elimina durante la actualización, por lo que conserva el histórico.

Después de cada cambio comprueba:

```bash
docker compose ps
curl https://api.aldeapucela.org/biki/api/v1/health
docker compose logs --tail=100 api
```

El estado de la importación inicial se puede consultar en `GET /api/v1/health`, en los campos
`history_import_status` y `history_import_updated_at`. Un fallo del histórico no deja caída la
API: queda registrado y se reintenta según `BIKI_HISTORY_IMPORT_RETRY_SECONDS`.

Para volver a una versión anterior, cambia el código a un commit o tag existente y repite la construcción, migración y reinicio.

### Captura manual remota (opcional)

El servicio periódico no necesita `BIKI_COLLECTOR_TOKEN` ni secretos de GitHub. Solo para habilitar el disparador manual `POST /api/v1/ops/collector/run`, configura un token seguro en el servidor. El endpoint sigue oculto de OpenAPI y protegido por Bearer; sin token configurado devuelve `503`.

La URL pública completa es:

```text
https://api.aldeapucela.org/biki/api/v1/ops/collector/run
```

Para probar el disparador manual sin mostrar el token:

```bash
curl --fail-with-body --silent --show-error --max-time 180 \
  --request POST \
  --header "Authorization: Bearer ${BIKI_COLLECTOR_TOKEN}" \
  "https://api.aldeapucela.org/biki/api/v1/ops/collector/run"
```

Una respuesta `200` confirma la captura y devuelve `capture_id`; `401` indica credenciales inválidas, `409` que ya hay otra captura en curso y `503` que falta configurar el token. El comando CLI del collector sigue disponible para pruebas locales.

### Captura programada

Compose ejecuta `movilidad-collector --loop` en el servicio `collector`. Hace un intento inmediato y espera `BIKI_CAPTURE_INTERVAL_SECONDS` (300 por defecto) después de cada intento. Los errores quedan registrados y se reintenta tras la misma espera. No hay cron ni workflow de GitHub para capturas; desactiva cualquier programación externa anterior al desplegar para evitar solicitudes redundantes.

SIGTERM y SIGINT despiertan la espera y solicitan la salida; una captura activa termina antes de salir. Compose concede 120 segundos antes de forzar SIGKILL, margen para varias peticiones GBFS con timeout predeterminado de 20 segundos; no es una garantía de duración máxima. Aumenta `stop_grace_period` si aumentas el timeout o el proveedor tarda más. SIGKILL puede dejar locks pendientes según el comportamiento existente.

La API mantiene la importación histórica al arrancar. El collector no ejecuta el importador ni espera a que termine. Los locks SQLite existentes evitan solapes entre capturas manuales y periódicas. Para una captura puntual se conserva `movilidad-collector` sin argumentos, o `docker compose run --rm collector movilidad-collector`.
