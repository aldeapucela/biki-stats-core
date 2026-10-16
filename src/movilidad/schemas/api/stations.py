from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Location(BaseModel):
    latitude: float | None
    longitude: float | None


class Bikes(BaseModel):
    mechanical: int | None
    electric: int | None


class StationData(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    provider_id: str
    station_id: str
    name: str
    location: Location
    bikes: Bikes
    free_docks: int | None
    capacity: int | None
    occupancy_percent: float | None
    status: str
    observed_at: datetime | None
    collected_at: datetime | None
    data_age_seconds: int | None
    is_stale: bool
    distance_m: int | None = None


class StationListData(BaseModel):
    items: list[StationData]


class HealthData(BaseModel):
    service: str
    version: str
    database: str
    environment: str
    checked_at: datetime


class HistoryPoint(BaseModel):
    timestamp: datetime
    mechanical: float | None
    electric: float | None
    free_docks: float | None
    capacity: float | None
    occupancy_percent: float | None
    observations: int


class HistoryData(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    station_id: str
    provider_id: str
    from_: datetime = Field(alias="from")
    to: datetime
    granularity: str
    points: list[HistoryPoint]


class OccupancySummary(BaseModel):
    average_percent: float | None
    minimum_percent: float | None
    maximum_percent: float | None
    minimum_at: datetime | None
    maximum_at: datetime | None


class BikesSummary(BaseModel):
    mechanical_average: float | None
    electric_average: float | None
    free_docks_average: float | None
    total_bikes_average: float | None


class CompositionSummary(BaseModel):
    mechanical_percent: float | None
    electric_percent: float | None
    free_docks_percent: float | None


class SummaryData(BaseModel):
    station_id: str
    provider_id: str
    from_: datetime = Field(alias="from")
    to: datetime
    observations: int
    occupancy: OccupancySummary
    bikes: BikesSummary
    composition: CompositionSummary
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    missing_buckets: int
