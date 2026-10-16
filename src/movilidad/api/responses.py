import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from movilidad.schemas.api.common import ErrorDetail, Meta, PaginationMeta


def make_meta(
    request: Request,
    pagination: PaginationMeta | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", request.headers.get("X-Request-ID", ""))
    return Meta(
        request_id=request_id,
        generated_at=datetime.now(timezone.utc),
        pagination=pagination,
        warnings=warnings or [],
    ).model_dump(mode="json")


def success(
    request: Request,
    data: Any,
    status_code: int = 200,
    pagination: PaginationMeta | None = None,
    warnings: list[str] | None = None,
) -> Response:
    payload = {
        "status": "success",
        "code": status_code,
        "data": data,
        "errors": None,
        "meta": make_meta(request, pagination, warnings),
    }
    return _json_response(request, payload, status_code)


def error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    field: str | None = None,
) -> Response:
    payload = {
        "status": "error",
        "code": status_code,
        "data": None,
        "errors": [ErrorDetail(code=code, message=message, field=field).model_dump()],
        "meta": make_meta(request),
    }
    return _json_response(request, payload, status_code)


def _json_response(request: Request, payload: dict[str, Any], status_code: int) -> Response:
    stable_payload = _without_volatile_fields(payload)
    stable_body = json.dumps(
        stable_payload, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode()
    etag = hashlib.sha256(stable_body).hexdigest()
    if request.headers.get("if-none-match") == etag and status_code == 200:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": "public, max-age=30"},
        )
    return JSONResponse(
        content=payload,
        status_code=status_code,
        headers={"ETag": etag, "Cache-Control": "public, max-age=30"},
    )


def _without_volatile_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile_fields(item)
            for key, item in value.items()
            if key not in {"request_id", "generated_at", "data_age_seconds", "is_stale"}
        }
    if isinstance(value, list):
        return [_without_volatile_fields(item) for item in value]
    return value
