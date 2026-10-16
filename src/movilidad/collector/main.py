from movilidad.collector.pipeline import CapturePipeline
from movilidad.core.config import get_settings
from movilidad.core.logging import configure_logging
from movilidad.infrastructure.db.connection import connect, ensure_schema
from movilidad.infrastructure.db.repository import SqliteObservationRepository
from movilidad.infrastructure.providers.gbfs import GbfsProvider


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    connection = connect(settings)
    ensure_schema(connection)
    try:
        repository = SqliteObservationRepository(connection)
        provider = GbfsProvider(settings.gbfs_url, settings.http_timeout_seconds)
        CapturePipeline(repository, provider).run()
    finally:
        connection.close()


if __name__ == "__main__":
    run()
