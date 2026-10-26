import logging
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from threading import Lock

from movilidad.application.ports import ObservationRepository
from movilidad.domain.entities import Observation, StationSnapshot
from movilidad.domain.rules import data_age_seconds, haversine_meters, is_stale, occupancy_percent

logger = logging.getLogger(__name__)


class AnalysisCache:
    def __init__(self, ttl_seconds: float = 30, max_entries: int = 256) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[tuple[object, ...], tuple[float, dict[str, object]]] = {}
        self._lock = Lock()

    def get(self, key: tuple[object, ...]) -> dict[str, object] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return None
            return value

    def set(self, key: tuple[object, ...], value: dict[str, object]) -> None:
        with self._lock:
            if len(self._entries) >= self.max_entries:
                oldest_key = min(self._entries, key=lambda item: self._entries[item][0])
                self._entries.pop(oldest_key, None)
            self._entries[key] = (time.monotonic() + self.ttl_seconds, value)


class CurrentStationsService:
    def __init__(
        self, repository: ObservationRepository, analysis_cache: AnalysisCache | None = None
    ) -> None:
        self.repository = repository
        self.analysis_cache = analysis_cache

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
        started_at = time.perf_counter()
        if granularity == "raw":
            observations = self.repository.station_history(provider_id, station_id, start, end)
            points = aggregate_history(observations, start, end, granularity)
            processed = len(observations)
        else:
            rows = self.repository.station_history_buckets(
                provider_id, station_id, start, end, granularity
            )
            points = aggregate_bucket_rows(rows, start, end, granularity)
            processed = len(rows)
        logger.info(
            "historical query completed",
            extra={
                "station_id": station_id,
                "granularity": granularity,
                "processed_rows": processed,
                "history_points": len(points[:limit]),
                "sql_duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
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
        started_at = time.perf_counter()
        row = self.repository.station_summary_aggregate(provider_id, station_id, start, end)
        summary = summary_from_row(provider_id, station_id, start, end, row)
        logger.info(
            "historical summary completed",
            extra={
                "station_id": station_id,
                "observations": summary["observations"],
                "sql_duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        return summary

    def analysis(
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
        key = (provider_id, station_id, start, end, granularity, limit)
        if self.analysis_cache is not None:
            cached = self.analysis_cache.get(key)
            if cached is not None:
                logger.info(
                    "historical analysis cache hit",
                    extra={"station_id": station_id, "granularity": granularity},
                )
                return cached

        started_at = time.perf_counter()
        if granularity == "raw":
            observations = self.repository.station_history(provider_id, station_id, start, end)
            points = aggregate_history(observations, start, end, granularity)
            summary = summary_from_observations(provider_id, station_id, start, end, observations)
            observation_count = len(observations)
        else:
            rows = self.repository.station_history_buckets(
                provider_id, station_id, start, end, granularity
            )
            points = aggregate_bucket_rows(rows, start, end, granularity)
            summary_row = self.repository.station_summary_aggregate(
                provider_id, station_id, start, end
            )
            summary = summary_from_row(provider_id, station_id, start, end, summary_row)
            observation_count = int(summary["observations"])

        data = {
            "history": {
                "station_id": station_id,
                "provider_id": provider_id,
                "from": start,
                "to": end,
                "granularity": granularity,
                "points": points[:limit],
            },
            "summary": summary,
        }
        if self.analysis_cache is not None:
            self.analysis_cache.set(key, data)
        logger.info(
            "historical analysis completed",
            extra={
                "station_id": station_id,
                "granularity": granularity,
                "observations": observation_count,
                "history_points": len(points[:limit]),
                "sql_duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "cache_hit": False,
            },
        )
        return data


def summary_from_observations(
    provider_id: str,
    station_id: str,
    start: datetime,
    end: datetime,
    observations: Sequence[Observation],
) -> dict[str, object]:
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
    mechanical_average = _mean(_values(observations, "mechanical_bikes"))
    electric_average = _mean(_values(observations, "electric_bikes"))
    free_docks_average = _mean(_values(observations, "free_docks"))
    total_bikes = [
        observation.mechanical_bikes + observation.electric_bikes
        for observation in observations
        if observation.mechanical_bikes is not None and observation.electric_bikes is not None
    ]
    composition_total = sum(
        value
        for value in (mechanical_average, electric_average, free_docks_average)
        if value is not None
    )
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
        "composition": {
            "mechanical_percent": _percent_of(mechanical_average, composition_total),
            "electric_percent": _percent_of(electric_average, composition_total),
            "free_docks_percent": _percent_of(free_docks_average, composition_total),
        },
        "first_observed_at": observations[0].observed_at if observations else None,
        "last_observed_at": observations[-1].observed_at if observations else None,
        "missing_buckets": count_missing_buckets(observations, start, end, "hour"),
    }


def summary_from_row(
    provider_id: str,
    station_id: str,
    start: datetime,
    end: datetime,
    row,
) -> dict[str, object]:
    observations = int(row["observations"]) if row is not None else 0
    mechanical = row["mechanical_average"] if row is not None else None
    electric = row["electric_average"] if row is not None else None
    free_docks = row["free_docks_average"] if row is not None else None
    total_bikes = row["total_bikes_average"] if row is not None else None
    composition_total = sum(
        value for value in (mechanical, electric, free_docks) if value is not None
    )
    minimum_at = _parse_timestamp(row["minimum_at"]) if row and row["minimum_at"] else None
    maximum_at = _parse_timestamp(row["maximum_at"]) if row and row["maximum_at"] else None
    first_at = (
        _parse_timestamp(row["first_observed_at"]) if row and row["first_observed_at"] else None
    )
    last_at = _parse_timestamp(row["last_observed_at"]) if row and row["last_observed_at"] else None
    hourly_buckets = int(row["hourly_buckets"]) if row is not None else 0
    return {
        "station_id": station_id,
        "provider_id": provider_id,
        "from": start,
        "to": end,
        "observations": observations,
        "occupancy": {
            "average_percent": row["average_percent"] if row is not None else None,
            "minimum_percent": row["minimum_percent"] if row is not None else None,
            "maximum_percent": row["maximum_percent"] if row is not None else None,
            "minimum_at": minimum_at,
            "maximum_at": maximum_at,
        },
        "bikes": {
            "mechanical_average": mechanical,
            "electric_average": electric,
            "free_docks_average": free_docks,
            "total_bikes_average": total_bikes,
        },
        "composition": {
            "mechanical_percent": _percent_of(mechanical, composition_total),
            "electric_percent": _percent_of(electric, composition_total),
            "free_docks_percent": _percent_of(free_docks, composition_total),
        },
        "first_observed_at": first_at,
        "last_observed_at": last_at,
        "missing_buckets": max(_bucket_count(start, end, "hour") - hourly_buckets, 0),
    }


def aggregate_bucket_rows(rows, start: datetime, end: datetime, granularity: str):
    grouped = {
        _parse_timestamp(row["bucket"]): {
            "timestamp": _parse_timestamp(row["bucket"]),
            "mechanical": row["mechanical"],
            "electric": row["electric"],
            "free_docks": row["free_docks"],
            "capacity": row["capacity"],
            "occupancy_percent": row["occupancy_percent"],
            "observations": row["observations"],
        }
        for row in rows
    }
    points = []
    bucket_start = _floor_datetime(start, granularity)
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    while bucket_start <= end:
        points.append(grouped.get(bucket_start, _empty_bucket(bucket_start)))
        bucket_start += step
    return points


def _empty_bucket(timestamp: datetime) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "mechanical": None,
        "electric": None,
        "free_docks": None,
        "capacity": None,
        "occupancy_percent": None,
        "observations": 0,
    }


def _bucket_count(start: datetime, end: datetime, granularity: str) -> int:
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    current = _floor_datetime(start, granularity)
    count = 0
    while current <= end:
        count += 1
        current += step
    return count


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    bucket_start = _floor_datetime(start, granularity)
    grouped: dict[datetime, list[Observation]] = {}
    while bucket_start <= end:
        grouped[bucket_start] = []
        bucket_start += step
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
    value = value.astimezone(timezone.utc)
    if granularity == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


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
