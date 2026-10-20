from secrets import compare_digest

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from movilidad.api.errors import ApiError
from movilidad.api.responses import success
from movilidad.application.capture import run_capture
from movilidad.core.config import get_settings
from movilidad.schemas.api.collector import CollectorRunData
from movilidad.schemas.api.common import Envelope

router = APIRouter(prefix="/ops", tags=["operations"], include_in_schema=False)
bearer = HTTPBearer(auto_error=False)


def require_collector_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    configured_token = get_settings().collector_token
    if not configured_token:
        raise ApiError(
            503,
            "COLLECTOR_NOT_CONFIGURED",
            "La captura remota no está configurada",
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not compare_digest(credentials.credentials, configured_token)
    ):
        raise ApiError(401, "UNAUTHORIZED", "Credenciales no válidas")


@router.post(
    "/collector/run",
    response_model=Envelope[CollectorRunData],
    dependencies=[Depends(require_collector_token)],
)
def run_collector(request: Request):
    capture_id = run_capture()
    if capture_id == "skipped":
        raise ApiError(
            409,
            "CAPTURE_IN_PROGRESS",
            "Ya existe una captura en curso",
        )
    return success(request, CollectorRunData(capture_id=capture_id).model_dump())
