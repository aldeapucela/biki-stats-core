from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from movilidad.api.dependencies import get_station_service
from movilidad.api.errors import ApiError
from movilidad.api.responses import success
from movilidad.application.services import CurrentStationsService
from movilidad.schemas.api.common import Envelope, PaginationMeta
from movilidad.schemas.api.stations import HistoryData, StationData, SummaryData

router = APIRouter(prefix="/stations", tags=["stations"])
MAX_HISTORY_DAYS = 90


@router.get("/nearby", response_model=Envelope[list[StationData]])
def nearby(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_m: int = Query(default=5000, ge=1, le=10_000),
    limit: int = Query(default=50, ge=1, le=100),
    provider_id: str = Query(default="biki"),
    service: CurrentStationsService = Depends(get_station_service),
):
    _check_provider(provider_id)
    data = service.nearby(provider_id, lat, lon, radius_m, limit)
    return success(
        request,
        [StationData.model_validate(item).model_dump(mode="json") for item in data],
    )


@router.get("", response_model=Envelope[list[StationData]])
def list_stations(
    request: Request,
    q: str | None = Query(default=None, max_length=100),
    status: Literal["active", "inactive", "unknown"] | None = None,
    has_electric: bool | None = None,
    sort: Literal["name", "occupancy_percent", "data_age_seconds"] = "name",
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    provider_id: str = Query(default="biki"),
    service: CurrentStationsService = Depends(get_station_service),
):
    _check_provider(provider_id)
    data, total = service.list_current(
        provider_id, q, status, has_electric, sort, order, limit, offset
    )
    pagination = PaginationMeta(
        limit=limit, offset=offset, returned=len(data), has_more=offset + len(data) < total
    )
    return success(
        request,
        [StationData.model_validate(item).model_dump(mode="json") for item in data],
        pagination=pagination,
    )


@router.get("/{station_id}", response_model=Envelope[StationData])
def station_detail(
    station_id: str,
    request: Request,
    provider_id: str = Query(default="biki"),
    service: CurrentStationsService = Depends(get_station_service),
):
    _check_provider(provider_id)
    data = service.get_current(provider_id, station_id)
    if data is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "La estación no existe", "station_id")
    return success(request, StationData.model_validate(data).model_dump(mode="json", by_alias=True))


@router.get("/{station_id}/history", response_model=Envelope[HistoryData])
def station_history(
    station_id: str,
    request: Request,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    granularity: Literal["raw", "hour", "day"] = "raw",
    limit: int = Query(default=10_000, ge=1, le=10_000),
    provider_id: str = Query(default="biki"),
    service: CurrentStationsService = Depends(get_station_service),
):
    _check_provider(provider_id)
    start, end = _validate_range(from_, to)
    data = service.history(provider_id, station_id, start, end, granularity, limit)
    if data is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "La estación no existe", "station_id")
    return success(request, HistoryData.model_validate(data).model_dump(mode="json", by_alias=True))


@router.get("/{station_id}/summary", response_model=Envelope[SummaryData])
def station_summary(
    station_id: str,
    request: Request,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    provider_id: str = Query(default="biki"),
    service: CurrentStationsService = Depends(get_station_service),
):
    _check_provider(provider_id)
    start, end = _validate_range(from_, to)
    data = service.summary(provider_id, station_id, start, end)
    if data is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "La estación no existe", "station_id")
    return success(request, SummaryData.model_validate(data).model_dump(mode="json", by_alias=True))


def _check_provider(provider_id: str) -> None:
    if provider_id != "biki":
        raise ApiError(
            422, "INVALID_QUERY_PARAMETER", "El proveedor no está disponible", "provider_id"
        )


def _validate_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ApiError(
            422, "INVALID_QUERY_PARAMETER", "Las fechas deben incluir zona horaria", "from/to"
        )
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if start >= end:
        raise ApiError(422, "INVALID_QUERY_PARAMETER", "from debe ser anterior a to", "from/to")
    if end - start > timedelta(days=MAX_HISTORY_DAYS):
        raise ApiError(
            422, "INVALID_QUERY_PARAMETER", "El intervalo máximo es de 90 días", "from/to"
        )
    return start, end
