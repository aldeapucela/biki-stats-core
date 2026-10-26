import sqlite3
from collections.abc import Generator

from fastapi import Depends, Request

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
    request: Request,
    connection: sqlite3.Connection = Depends(get_connection),
) -> CurrentStationsService:
    cache = getattr(request.app.state, "analysis_cache", None)
    return CurrentStationsService(get_repository(connection), cache)
