import sqlite3
from collections.abc import Generator

from movilidad.core.config import get_settings
from movilidad.infrastructure.db.connection import connect, ensure_schema
from movilidad.infrastructure.db.repository import SqliteObservationRepository


def get_connection() -> Generator[sqlite3.Connection, None, None]:
    connection = connect(get_settings())
    ensure_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def get_repository(connection: sqlite3.Connection) -> SqliteObservationRepository:
    return SqliteObservationRepository(connection)
