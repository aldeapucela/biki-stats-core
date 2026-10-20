from movilidad.collector.pipeline import CapturePipeline
from movilidad.core.config import Settings, get_settings
from movilidad.infrastructure.db.connection import connect, ensure_schema
from movilidad.infrastructure.db.repository import SqliteObservationRepository
from movilidad.infrastructure.providers.gbfs import GbfsProvider


def run_capture(settings: Settings | None = None) -> str:
    current = settings or get_settings()
    connection = connect(current)
    ensure_schema(connection)
    try:
        repository = SqliteObservationRepository(connection)
        provider = GbfsProvider(current.gbfs_url, current.http_timeout_seconds)
        return CapturePipeline(repository, provider).run()
    finally:
        connection.close()
