import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from movilidad.api.dependencies import get_connection
from movilidad.api.responses import success
from movilidad.application.history_import import history_import_status
from movilidad.core.config import get_settings
from movilidad.schemas.api.common import Envelope
from movilidad.schemas.api.stations import HealthData

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Envelope[HealthData])
def health(request: Request, connection: sqlite3.Connection = Depends(get_connection)):
    connection.execute("SELECT 1").fetchone()
    settings = get_settings()
    import_state = history_import_status(settings)
    return success(
        request,
        HealthData(
            service="movilidad-api",
            version="0.1.0",
            database="ok",
            environment=settings.environment,
            checked_at=datetime.now(timezone.utc),
            history_import_status=import_state.get("status") if import_state else None,
            history_import_updated_at=(
                datetime.fromisoformat(import_state["updated_at"].replace("Z", "+00:00"))
                if import_state and import_state.get("updated_at")
                else None
            ),
        ).model_dump(mode="json", by_alias=True),
    )
