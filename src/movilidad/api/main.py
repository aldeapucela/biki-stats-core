import asyncio
import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from movilidad.api.errors import (
    ApiError,
    api_error_handler,
    database_error_handler,
    http_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from movilidad.api.routers.collector import router as collector_router
from movilidad.api.routers.health import router as health_router
from movilidad.api.routers.stations import router as stations_router
from movilidad.application.history_import import history_import_worker
from movilidad.application.services import AnalysisCache
from movilidad.core.config import get_settings
from movilidad.core.logging import configure_logging
from movilidad.infrastructure.db.connection import initialize_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    initialize_database(settings)
    app.state.analysis_cache = AnalysisCache()
    worker = (
        asyncio.create_task(history_import_worker(settings))
        if settings.history_import_on_startup
        else None
    )
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


app = FastAPI(
    title="BIKI API",
    version="0.1.0",
    description="API de datos de BIKI Valladolid de Aldea Pucela.",
    lifespan=lifespan,
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(sqlite3.Error, database_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    started_at = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("movilidad.api").info(
        "request completed",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        },
    )
    return response


app.include_router(health_router, prefix="/api/v1")
app.include_router(collector_router, prefix="/api/v1")
app.include_router(stations_router, prefix="/api/v1")


def run() -> None:
    import uvicorn

    uvicorn.run("movilidad.api.main:app", host="0.0.0.0", port=8000, reload=False)
