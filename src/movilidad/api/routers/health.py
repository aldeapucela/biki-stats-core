import sqlite3

from fastapi import APIRouter, Depends

from movilidad.api.dependencies import get_connection
from movilidad.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
    connection.execute("SELECT 1").fetchone()
    settings = get_settings()
    return {"status": "ok", "environment": settings.environment, "database": "ok"}
