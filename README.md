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

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/ruff check src tests scripts
.venv/bin/uvicorn movilidad.api.main:app --reload
```

La API expone inicialmente `GET /api/v1/health`. Las rutas de negocio y sus contratos JSON se definirán en la issue #4.

Para ejecutar una captura manual con la configuración de `.env`, usa `.venv/bin/movilidad-collector`. El workflow de GitHub Actions programa la captura cada cinco minutos en un runner autoalojado con acceso al volumen SQLite.

## Docker

```bash
docker compose up --build api
docker compose --profile collector run --rm collector
```

Las migraciones de producción se ejecutan con `alembic upgrade head`. Consulta [la documentación de arquitectura](docs/ARQUITECTURA.md) para histórico, locks, backups y observabilidad.

Para ejecutar la validación completa local usa `scripts/validate.sh`. Añade `--docker-build` para construir las imágenes y `--live-feed` para consultar el feed GBFS real.

### Captura programada

En producción, `.github/workflows/collector.yml` ejecuta el collector cada cinco minutos en el runner autoalojado `movilidad`.

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
