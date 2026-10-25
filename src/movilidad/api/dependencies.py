import sqlite3
from collections.abc import Generator

from fastapi import Depends

from movilidad.application.services import CurrentStationsService
from movilidad.core.config import get_settings
from movilidad.infrastructure.db.connection import connect
from movilidad.infrastructure.db.repository import SqliteObservationRepository


def get_connection() -> Generator[sqlite3.Connection, None, None]:
    connection = connect(get_settings())
    try:
        yield connection
    finally:
        connection.close()


def get_repository(connection: sqlite3.Connection) -> SqliteObservationRepository:
    return SqliteObservationRepository(connection)


def get_station_service(
    connection: sqlite3.Connection = Depends(get_connection),
) -> CurrentStationsService:
    return CurrentStationsService(get_repository(connection))
