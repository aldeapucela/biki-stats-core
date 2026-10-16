import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from movilidad.api.routers.health import router as health_router
from movilidad.core.config import get_settings
from movilidad.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    yield


app = FastAPI(
    title="Movilidad API",
    version="0.1.0",
    description="API de datos de movilidad de Aldea Pucela.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("movilidad.api").info(
        "request completed", extra={"request_id": request_id, "path": request.url.path}
    )
    return response


app.include_router(health_router, prefix="/api/v1")


def run() -> None:
    import uvicorn

    uvicorn.run("movilidad.api.main:app", host="0.0.0.0", port=8000, reload=False)
