# Movilidad · biki-stats-core

Proyecto de código abierto de [Aldea Pucela](https://aldeapucela.org/) para informar sobre las estaciones del servicio BIKI de Valladolid.

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

La captura escribe en `./data/movilidad.sqlite3`. Para probar el endpoint remoto en local, define `MOVILIDAD_COLLECTOR_TOKEN` en `.env` y usa:

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  --header "Authorization: Bearer ${MOVILIDAD_COLLECTOR_TOKEN}" \
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
| `MOVILIDAD_ENV` | `development` | Entorno de ejecución. En producción usar `production`. |
| `MOVILIDAD_DATABASE_PATH` | `./data/movilidad.sqlite3` | Ruta SQLite. Compose la fija a `/data/movilidad.sqlite3`. |
| `MOVILIDAD_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173,https://movilidad.aldeapucela.org` | Orígenes permitidos separados por comas. En producción usar `https://biki.aldeapucela.org`. |
| `MOVILIDAD_GBFS_URL` | Feed GBFS de BIKI Valladolid | URL de descubrimiento GBFS. |
| `MOVILIDAD_CAPTURE_INTERVAL_SECONDS` | `300` | Intervalo de referencia de captura: 5 minutos. |
| `MOVILIDAD_HTTP_TIMEOUT_SECONDS` | `20` | Timeout de las peticiones al proveedor GBFS. |
| `MOVILIDAD_LOG_LEVEL` | `INFO` | Nivel de logs. |
| `MOVILIDAD_COLLECTOR_TOKEN` | Vacío / endpoint desactivado | Token Bearer del endpoint operativo. Debe ser secreto en producción. |
| `MOVILIDAD_IMAGE` | `credondoc/biki-stats-core:latest` en Compose | Imagen Docker que se despliega. Se recomienda fijar una versión `x.y.z`. |

Compose aplica valores de producción propios para `MOVILIDAD_ENV`, CORS, GBFS, timeout y logging. La variable `MOVILIDAD_DATABASE_PATH` y el volumen `/data` no deben cambiarse sin actualizar también la persistencia de API y collector.

## Docker

```bash
docker compose up --build api
docker compose --profile collector run --rm collector
```

Las migraciones de producción se ejecutan con `alembic upgrade head`. Consulta [la documentación de arquitectura](docs/ARQUITECTURA.md) para histórico, locks, backups y observabilidad.

Para ejecutar la validación completa local usa `scripts/validate.sh`. Añade `--docker-build` para construir las imágenes y `--live-feed` para consultar el feed GBFS real.

La integración continua ejecuta esta validación en todas las ramas y pull requests. Los cambios publicados en `main` calculan la siguiente versión a partir de Conventional Commits, crean un tag `x.y.z` y publican `credondoc/biki-stats-core:x.y.z` y `credondoc/biki-stats-core:latest`.

Para probar una imagen publicada en local:

```bash
MOVILIDAD_IMAGE=credondoc/biki-stats-core:1.2.3 docker compose pull
MOVILIDAD_IMAGE=credondoc/biki-stats-core:1.2.3 docker compose up api
```

## Despliegue en PRO

La imagen publicada necesita una base de datos SQLite persistente y, si se quiere mantener el histórico actualizado, un collector que comparta el mismo volumen con la API. Crea un archivo `.env` junto a `docker-compose.yml`:

```dotenv
MOVILIDAD_IMAGE=credondoc/biki-stats-core:0.2.0
MOVILIDAD_ENV=production
MOVILIDAD_COLLECTOR_TOKEN=replace-with-a-secret-token
MOVILIDAD_CORS_ORIGINS=https://biki.aldeapucela.org
MOVILIDAD_GBFS_URL=https://valladolid.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json
MOVILIDAD_CAPTURE_INTERVAL_SECONDS=300
MOVILIDAD_HTTP_TIMEOUT_SECONDS=20
MOVILIDAD_LOG_LEVEL=INFO
```

`MOVILIDAD_DATABASE_PATH` no es necesario definirlo en el `.env`: Compose lo fija a `/data/movilidad.sqlite3` dentro de los contenedores. El volumen `movilidad-data` conserva la base de datos aunque se actualice la imagen.

Descarga la imagen y levanta la API y el collector:

```bash
docker compose pull
docker compose run --rm api alembic upgrade head
docker compose up -d --no-build api
docker compose --profile collector up -d --no-build collector
```

Comprueba el estado y los logs:

```bash
curl http://localhost:8000/api/v1/health
docker compose ps
docker compose logs -f api
docker compose logs -f collector
```

El reverse proxy debe publicar la API bajo `https://api.aldeapucela.org/biki/` y permitir el origen `https://biki.aldeapucela.org`. No guardes credenciales de Docker Hub en el servidor: `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN` solo se usan como secretos de GitHub Actions para publicar imágenes.

### Modificaciones en PRO

Para actualizar la versión desplegada, modifica `MOVILIDAD_IMAGE` en el `.env` del servidor, descarga la nueva imagen y recrea los servicios sin construir localmente:

```bash
MOVILIDAD_IMAGE=credondoc/biki-stats-core:0.3.0 docker compose pull
MOVILIDAD_IMAGE=credondoc/biki-stats-core:0.3.0 docker compose run --rm api alembic upgrade head
MOVILIDAD_IMAGE=credondoc/biki-stats-core:0.3.0 docker compose up -d --no-build api
MOVILIDAD_IMAGE=credondoc/biki-stats-core:0.3.0 docker compose --profile collector up -d --no-build collector
```

También puedes dejar `MOVILIDAD_IMAGE=credondoc/biki-stats-core:0.3.0` en `.env` y ejecutar los comandos sin prefijar la variable. El volumen `movilidad-data` no se elimina durante la actualización, por lo que conserva el histórico.

Después de cada cambio comprueba:

```bash
docker compose ps
curl https://api.aldeapucela.org/biki/api/v1/health
docker compose logs --tail=100 api
docker compose logs --tail=100 collector
```

Para volver a una versión anterior, cambia `MOVILIDAD_IMAGE` a un tag existente y repite `pull`, la migración y el reinicio. No uses `latest` en PRO si necesitas poder identificar y revertir exactamente la versión desplegada.

En GitHub configura el secreto `MOVILIDAD_COLLECTOR_TOKEN` en `Settings > Secrets and variables > Actions`. Su valor debe coincidir con el token configurado en el `.env` del servidor. El workflow programado no necesita clonar el repositorio ni acceder al volumen SQLite: solo necesita conectividad HTTPS con la API.

### Captura remota desde GitHub Actions

La captura programada se solicita mediante `POST /api/v1/ops/collector/run`. El endpoint está oculto de OpenAPI y protegido con Bearer sobre HTTPS. Configura el mismo valor seguro en el servidor como `MOVILIDAD_COLLECTOR_TOKEN` y en GitHub como el secreto `MOVILIDAD_COLLECTOR_TOKEN`.

La URL pública completa es:

```text
https://api.aldeapucela.org/biki/api/v1/ops/collector/run
```

El workflow programado usa `COLLECTOR_API_URL` y falla si la API devuelve un error. Para probarlo manualmente sin mostrar el token:

```bash
curl --fail-with-body --silent --show-error --max-time 180 \
  --request POST \
  --header "Authorization: Bearer ${MOVILIDAD_COLLECTOR_TOKEN}" \
  "https://api.aldeapucela.org/biki/api/v1/ops/collector/run"
```

Una respuesta `200` confirma la captura y devuelve `capture_id`; `401` indica credenciales inválidas, `409` que ya hay otra captura en curso y `503` que falta configurar el token. El collector CLI y el cron local siguen disponibles como alternativa.

### Captura programada

En producción, `.github/workflows/collector.yml` solicita la captura remota cada cinco minutos mediante la API. El runner de GitHub no necesita acceso al volumen SQLite ni al repositorio; solo necesita conectividad HTTPS con `api.aldeapucela.org` y el secreto `MOVILIDAD_COLLECTOR_TOKEN`.

Para instalarlo mediante cron en un servidor Docker:

1. Copia `deploy/movilidad-collector.cron` y sustituye `/opt/movilidad/biki-stats-core` por la ruta del repositorio.
2. Instálalo para el usuario que tenga permisos para ejecutar Docker:

   ```bash
   crontab deploy/movilidad-collector.cron
   ```

3. Comprueba la entrada instalada y el log:

   ```bash
   crontab -l
   tail -f /opt/movilidad/biki-stats-core/collector.log
   ```

El collector usa locks en SQLite para evitar duplicar capturas si una ejecución tarda más de cinco minutos.
