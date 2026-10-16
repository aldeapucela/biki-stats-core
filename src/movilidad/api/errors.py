import logging
import sqlite3

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from movilidad.api.responses import error

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, field: str | None = None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field


async def api_error_handler(request: Request, exc: ApiError) -> Response:
    return error(request, exc.status_code, exc.code, exc.message, exc.field)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
    details = exc.errors()
    first = details[0] if details else {"msg": "Parámetro inválido", "loc": []}
    location = first.get("loc", [])
    field = str(location[-1]) if location else None
    return error(request, 422, "INVALID_QUERY_PARAMETER", str(first.get("msg")), field)


async def http_error_handler(request: Request, exc: HTTPException) -> Response:
    codes = {
        404: "RESOURCE_NOT_FOUND",
        429: "RATE_LIMITED",
        503: "SERVICE_UNAVAILABLE",
    }
    return error(
        request, exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> Response:
    logger.error("Unhandled API error", exc_info=(type(exc), exc, exc.__traceback__))
    return error(request, 500, "INTERNAL_ERROR", "Se ha producido un error interno")


async def database_error_handler(request: Request, exc: sqlite3.Error) -> Response:
    logger.error("Database unavailable", exc_info=(type(exc), exc, exc.__traceback__))
    return error(request, 503, "SERVICE_UNAVAILABLE", "El servicio de datos no está disponible")
