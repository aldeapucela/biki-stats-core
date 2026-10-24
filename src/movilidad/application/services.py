from collections.abc import Sequence
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from movilidad.application.ports import ObservationRepository
from movilidad.domain.entities import Observation, StationSnapshot
from movilidad.domain.rules import data_age_seconds, haversine_meters, is_stale, occupancy_percent

LOCAL_ZONE = ZoneInfo("Europe/Madrid")


class CurrentStationsService:
    def __init__(self, repository: ObservationRepository) -> None:
        self.repository = repository

    def list_current(
        self,
        provider_id: str,
        query: str | None,
        status: str | None,
        has_electric: bool | None,
        sort: str,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        snapshots, total = self.repository.list_station_snapshots(
            provider_id, query, status, has_electric, sort, order, limit, offset
        )
        return [snapshot_to_dict(snapshot) for snapshot in snapshots], total

    def get_current(self, provider_id: str, station_id: str) -> dict[str, object] | None:
        snapshot = self.repository.get_station_snapshot(provider_id, station_id)
        return snapshot_to_dict(snapshot) if snapshot else None

    def nearby(
        self, provider_id: str, latitude: float, longitude: float, radius_m: int, limit: int
    ) -> list[dict[str, object]]:
        snapshots, _ = self.repository.list_station_snapshots(
            provider_id, None, None, None, "name", "asc", 10_000, 0
        )
        results: list[dict[str, object]] = []
        for snapshot in snapshots:
            if snapshot.station.latitude is None or snapshot.station.longitude is None:
                continue
            distance = haversine_meters(
                latitude, longitude, snapshot.station.latitude, snapshot.station.longitude
            )
            if distance <= radius_m:
                item = snapshot_to_dict(snapshot)
                item["distance_m"] = distance
                results.append(item)
        return sorted(results, key=lambda item: (item["distance_m"], item["station_id"]))[:limit]

    def history(
        self,
        provider_id: str,
        station_id: str,
        start: datetime,
        end: datetime,
        granularity: str,
        limit: int,
    ) -> dict[str, object] | None:
        if not self.repository.station_exists(provider_id, station_id):
            return None
        observations = self.repository.station_history(provider_id, station_id, start, end)
        points = aggregate_history(observations, start, end, granularity)
        return {
            "station_id": station_id,
            "provider_id": provider_id,
            "from": start,
            "to": end,
            "granularity": granularity,
            "points": points[:limit],
        }

    def summary(
        self, provider_id: str, station_id: str, start: datetime, end: datetime
    ) -> dict[str, object] | None:
        if not self.repository.station_exists(provider_id, station_id):
            return None
        observations = self.repository.station_history(provider_id, station_id, start, end)
        valid_occupancy = [
            (
                occupancy_percent(observation.capacity, observation.free_docks),
                observation.observed_at,
            )
            for observation in observations
        ]
        valid_occupancy = [
            (value, timestamp) for value, timestamp in valid_occupancy if value is not None
        ]
        occupancy_values = [value for value, _ in valid_occupancy]
        mechanical = _values(observations, "mechanical_bikes")
        electric = _values(observations, "electric_bikes")
        free_docks = _values(observations, "free_docks")
        total_bikes = [
            observation.mechanical_bikes + observation.electric_bikes
            for observation in observations
            if observation.mechanical_bikes is not None and observation.electric_bikes is not None
        ]
        mechanical_average = _mean(mechanical)
        electric_average = _mean(electric)
        free_docks_average = _mean(free_docks)
        composition_total = sum(
            value
            for value in (mechanical_average, electric_average, free_docks_average)
            if value is not None
        )
        composition = {
            "mechanical_percent": _percent_of(mechanical_average, composition_total),
            "electric_percent": _percent_of(electric_average, composition_total),
            "free_docks_percent": _percent_of(free_docks_average, composition_total),
        }
        minimum = min(valid_occupancy, default=(None, None), key=lambda item: item[0] or 0)
        maximum = max(valid_occupancy, default=(None, None), key=lambda item: item[0] or 0)
        return {
            "station_id": station_id,
            "provider_id": provider_id,
            "from": start,
            "to": end,
            "observations": len(observations),
            "occupancy": {
                "average_percent": _mean(occupancy_values),
                "minimum_percent": minimum[0],
                "maximum_percent": maximum[0],
                "minimum_at": minimum[1],
                "maximum_at": maximum[1],
            },
            "bikes": {
                "mechanical_average": mechanical_average,
                "electric_average": electric_average,
                "free_docks_average": free_docks_average,
                "total_bikes_average": _mean(total_bikes),
            },
            "composition": composition,
            "first_observed_at": observations[0].observed_at if observations else None,
            "last_observed_at": observations[-1].observed_at if observations else None,
            "missing_buckets": count_missing_buckets(observations, start, end, "hour"),
        }


def snapshot_to_dict(snapshot: StationSnapshot) -> dict[str, object]:
    station = snapshot.station
    observation = snapshot.observation
    capacity = (
        observation.capacity
        if observation and observation.capacity is not None
        else station.capacity
    )
    observed_at = observation.observed_at if observation else None
    return {
        "provider_id": station.provider_id,
        "station_id": station.station_id,
        "name": station.name,
        "location": {"latitude": station.latitude, "longitude": station.longitude},
        "bikes": {
            "mechanical": observation.mechanical_bikes if observation else None,
            "electric": observation.electric_bikes if observation else None,
        },
        "free_docks": observation.free_docks if observation else None,
        "capacity": capacity,
        "occupancy_percent": occupancy_percent(
            capacity, observation.free_docks if observation else None
        ),
        "status": "active" if station.is_active else "inactive",
        "observed_at": observed_at,
        "collected_at": observation.collected_at if observation else None,
        "data_age_seconds": data_age_seconds(observed_at),
        "is_stale": is_stale(observed_at),
        "distance_m": None,
    }


def aggregate_history(
    observations: Sequence[Observation], start: datetime, end: datetime, granularity: str
) -> list[dict[str, object]]:
    if granularity == "raw":
        return [_point(observation) for observation in observations]
    bucket_start = _floor_datetime(start, granularity)
    grouped: dict[datetime, list[Observation]] = {}
    while bucket_start <= end:
        grouped[bucket_start] = []
        bucket_start = _next_bucket(bucket_start, granularity)
    for observation in observations:
        key = _floor_datetime(observation.observed_at, granularity)
        if key in grouped:
            grouped[key].append(observation)
    return [_aggregate_bucket(timestamp, values) for timestamp, values in grouped.items()]


def count_missing_buckets(
    observations: Sequence[Observation], start: datetime, end: datetime, granularity: str
) -> int:
    points = aggregate_history(observations, start, end, granularity)
    return sum(point["observations"] == 0 for point in points)


def _point(observation: Observation) -> dict[str, object]:
    return {
        "timestamp": observation.observed_at,
        "mechanical": observation.mechanical_bikes,
        "electric": observation.electric_bikes,
        "free_docks": observation.free_docks,
        "capacity": observation.capacity,
        "occupancy_percent": occupancy_percent(observation.capacity, observation.free_docks),
        "observations": 1,
    }


def _aggregate_bucket(
    timestamp: datetime, observations: Sequence[Observation]
) -> dict[str, object]:
    mechanical = _values(observations, "mechanical_bikes")
    electric = _values(observations, "electric_bikes")
    free_docks = _values(observations, "free_docks")
    capacity = _values(observations, "capacity")
    occupancy = [
        value
        for value in (occupancy_percent(item.capacity, item.free_docks) for item in observations)
        if value is not None
    ]
    return {
        "timestamp": timestamp,
        "mechanical": _mean(mechanical),
        "electric": _mean(electric),
        "free_docks": _mean(free_docks),
        "capacity": _mean(capacity),
        "occupancy_percent": _mean(occupancy),
        "observations": len(observations),
    }


def _floor_datetime(value: datetime, granularity: str) -> datetime:
    """Trunca a la hora UTC o al día natural de Europe/Madrid; devuelve siempre UTC."""
    if granularity == "day":
        local = value.astimezone(LOCAL_ZONE)
        midnight = datetime.combine(local.date(), time.min, tzinfo=LOCAL_ZONE)
        return midnight.astimezone(timezone.utc)
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _next_bucket(bucket_start: datetime, granularity: str) -> datetime:
    if granularity == "day":
        # Se avanza por fecha local: los días de cambio horario duran 23 o 25 horas.
        next_date = bucket_start.astimezone(LOCAL_ZONE).date() + timedelta(days=1)
        return datetime.combine(next_date, time.min, tzinfo=LOCAL_ZONE).astimezone(timezone.utc)
    return bucket_start + timedelta(hours=1)


def _values(observations: Sequence[Observation], name: str) -> list[float]:
    return [
        float(value)
        for value in (getattr(item, name) for item in observations)
        if value is not None
    ]


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _percent_of(value: float | None, total: float) -> float | None:
    return round(value / total * 100, 2) if value is not None and total > 0 else None
