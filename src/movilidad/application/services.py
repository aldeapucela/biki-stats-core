import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from datetime import time as datetime_time
from fractions import Fraction
from threading import Lock
from time import perf_counter
from zoneinfo import ZoneInfo

from movilidad.application.ports import ObservationRepository
from movilidad.domain.entities import (
    HistoryGroup,
    Observation,
    StationSnapshot,
    SummaryGroup,
    SummaryRange,
)
from movilidad.domain.rules import data_age_seconds, haversine_meters, is_stale, occupancy_percent

logger = logging.getLogger("movilidad.history")
LOCAL_ZONE = ZoneInfo("Europe/Madrid")


class AnalysisCache:
    def __init__(self, ttl_seconds: float = 30, max_entries: int = 256) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[tuple[object, ...], tuple[float, dict[str, object]]] = {}
        self._lock = Lock()

    def get(self, key: tuple[object, ...]) -> dict[str, object] | None:
        now = perf_counter()
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
            self._entries[key] = (perf_counter() + self.ttl_seconds, value)


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
        started = perf_counter()
        if granularity == "raw":
            observations = self.repository.station_history(provider_id, station_id, start, end)
            sql_ms = (perf_counter() - started) * 1000
            points = [_point(observation) for observation in observations]
            rows = groups = len(observations)
        else:
            fallback_sql_seconds = 0.0

            def occupancy_sequence(bucket: str) -> OccupancyRows:
                nonlocal fallback_sql_seconds
                fallback_started = perf_counter()
                if granularity == "day":  # `bucket` es una fecha de Europe/Madrid
                    day_start, day_end = _madrid_day_bounds(bucket)
                    rows = self.repository.occupancy_sequence(
                        provider_id, station_id, max(start, day_start), min(end, day_end)
                    )
                else:
                    rows = self.repository.occupancy_sequence(
                        provider_id, station_id, start, end, bucket
                    )
                fallback_sql_seconds += perf_counter() - fallback_started
                return rows

            # El día de Madrid empieza en una hora entera UTC: se agrupa por hora en SQLite y
            # las horas se reparten por día en Python.
            history_groups = self.repository.history_groups(
                provider_id, station_id, start, end, "hour"
            )
            group_sql_seconds = perf_counter() - started
            points = aggregate_groups(
                history_groups,
                start,
                end,
                granularity,
                occupancy_sequence,
            )
            sql_ms = (group_sql_seconds + fallback_sql_seconds) * 1000
            rows = sum(group.observations for group in history_groups)
            groups = len(history_groups)
        _log_query("history", provider_id, station_id, granularity, started, sql_ms, rows, groups)
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
        started = perf_counter()
        groups, edges = self.repository.summary_groups(provider_id, station_id, start, end)
        group_sql_seconds = perf_counter() - started
        fallback_sql_seconds = 0.0

        def occupancy_sequence() -> OccupancyRows:
            nonlocal fallback_sql_seconds
            fallback_started = perf_counter()
            rows = self.repository.occupancy_sequence(provider_id, station_id, start, end)
            fallback_sql_seconds += perf_counter() - fallback_started
            return rows

        result = summarize_groups(
            groups,
            edges,
            provider_id,
            station_id,
            start,
            end,
            occupancy_sequence,
        )
        sql_ms = (group_sql_seconds + fallback_sql_seconds) * 1000
        rows = int(result["observations"])  # type: ignore[call-overload]
        _log_query("summary", provider_id, station_id, None, started, sql_ms, rows, len(groups))
        return result

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
                return cached
        history = self.history(provider_id, station_id, start, end, granularity, limit)
        summary = self.summary(provider_id, station_id, start, end)
        if history is None or summary is None:
            return None
        result = {"history": history, "summary": summary}
        if self.analysis_cache is not None:
            self.analysis_cache.set(key, result)
        return result


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


OccupancyRows = Iterable[tuple[int | None, int | None]]


def aggregate_groups(
    groups: Sequence[HistoryGroup],
    start: datetime,
    end: datetime,
    granularity: str,
    sequence: Callable[[str], OccupancyRows],
) -> list[dict[str, object]]:
    """Reduce los grupos de SQLite a un punto por franja, rellenando las franjas vacías.

    La ocupación de cada observación ya viene redondeada a 2 decimales; se acumula en
    céntimos enteros. `sequence(franja)` devuelve las filas de esa franja para los empates
    (ver `_occupancy_mean`).
    """
    totals: dict[str, _BucketTotals] = {}
    for group in groups:
        key = group.bucket if granularity == "hour" else _madrid_day_of_hour(group.bucket)
        total = totals.setdefault(key, _BucketTotals())
        total.add(group)
    points: list[dict[str, object]] = []
    moment = _floor_datetime(start, granularity)
    while moment <= end:
        key = (
            moment.strftime("%Y-%m-%dT%H")
            if granularity == "hour"
            else moment.astimezone(LOCAL_ZONE).strftime("%Y-%m-%d")
        )
        total = totals.get(key) or _BucketTotals()
        points.append(total.point(moment, lambda key=key: sequence(key)))
        moment = _next_bucket(moment, granularity)
    return points


def _madrid_day_of_hour(bucket: str) -> str:
    """Fecha de Europe/Madrid de una hora UTC `YYYY-MM-DDTHH`."""
    hour = datetime.strptime(bucket, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    return hour.astimezone(LOCAL_ZONE).strftime("%Y-%m-%d")


def _madrid_day_bounds(day: str) -> tuple[datetime, datetime]:
    """Primer y último instante (UTC) de una fecha de Europe/Madrid, con sus 23, 24 o 25 h."""
    first = datetime.strptime(day, "%Y-%m-%d").date()
    low = datetime.combine(first, datetime_time.min, tzinfo=LOCAL_ZONE)
    high = datetime.combine(first + timedelta(days=1), datetime_time.min, tzinfo=LOCAL_ZONE)
    return low.astimezone(timezone.utc), high.astimezone(timezone.utc) - timedelta(microseconds=1)


class _BucketTotals:
    def __init__(self) -> None:
        self.observations = 0
        self.mechanical = [0, 0]
        self.electric = [0, 0]
        self.free_docks = [0, 0]
        self.capacity = [0, 0]
        self.occupancy_cents = 0
        self.occupancy_count = 0

    def add(self, group: HistoryGroup) -> None:
        self.observations += group.observations
        # (acumulador, suma de los valores no nulos, cuántas observaciones aportan valor)
        for pair, total, count in (
            (self.mechanical, group.mechanical_sum, group.mechanical_count),
            (self.electric, group.electric_sum, group.electric_count),
            (
                self.free_docks,
                None if group.free_docks is None else group.free_docks * group.observations,
                0 if group.free_docks is None else group.observations,
            ),
            (
                self.capacity,
                None if group.capacity is None else group.capacity * group.observations,
                0 if group.capacity is None else group.observations,
            ),
        ):
            if total is not None and count:
                pair[0] += total
                pair[1] += count
        occupancy = occupancy_percent(group.capacity, group.free_docks)
        if occupancy is not None:
            self.occupancy_cents += round(occupancy * 100) * group.observations
            self.occupancy_count += group.observations

    def point(
        self, timestamp: datetime, sequence: Callable[[], OccupancyRows]
    ) -> dict[str, object]:
        return {
            "timestamp": timestamp,
            "mechanical": _mean_of(*self.mechanical),
            "electric": _mean_of(*self.electric),
            "free_docks": _mean_of(*self.free_docks),
            "capacity": _mean_of(*self.capacity),
            "occupancy_percent": _occupancy_mean(
                self.occupancy_cents, self.occupancy_count, sequence
            ),
            "observations": self.observations,
        }


def summarize_groups(
    groups: Sequence[SummaryGroup],
    edges: SummaryRange,
    provider_id: str,
    station_id: str,
    start: datetime,
    end: datetime,
    sequence: Callable[[], OccupancyRows],
) -> dict[str, object]:
    total = sum(group.observations for group in groups)
    sums = {name: [0, 0] for name in ("mechanical", "electric", "free_docks", "total_bikes")}
    occupancy_cents = occupancy_count = 0
    minimum: tuple[float, datetime] | None = None
    maximum: tuple[float, datetime] | None = None
    for group in groups:
        count = group.observations
        for name, value in (
            ("mechanical", group.mechanical_bikes),
            ("electric", group.electric_bikes),
            ("free_docks", group.free_docks),
        ):
            if value is not None:
                sums[name][0] += value * count
                sums[name][1] += count
        if group.mechanical_bikes is not None and group.electric_bikes is not None:
            sums["total_bikes"][0] += (group.mechanical_bikes + group.electric_bikes) * count
            sums["total_bikes"][1] += count
        occupancy = occupancy_percent(group.capacity, group.free_docks)
        if occupancy is None:
            continue
        occupancy_cents += round(occupancy * 100) * count
        occupancy_count += count
        # Como al recorrer en orden cronológico: gana la primera aparición del valor extremo.
        if minimum is None or (occupancy, group.first_observed_at) < minimum:
            minimum = (occupancy, group.first_observed_at)
        if (
            maximum is None
            or occupancy > maximum[0]
            or (occupancy == maximum[0] and group.first_observed_at < maximum[1])
        ):
            maximum = (occupancy, group.first_observed_at)
    mechanical_average = _mean_of(*sums["mechanical"])
    electric_average = _mean_of(*sums["electric"])
    free_docks_average = _mean_of(*sums["free_docks"])
    composition_total = sum(
        value
        for value in (mechanical_average, electric_average, free_docks_average)
        if value is not None
    )
    hours_in_range = (
        int((_floor_datetime(end, "hour") - _floor_datetime(start, "hour")) / timedelta(hours=1))
        + 1
    )
    return {
        "station_id": station_id,
        "provider_id": provider_id,
        "from": start,
        "to": end,
        "observations": total,
        "occupancy": {
            "average_percent": _occupancy_mean(occupancy_cents, occupancy_count, sequence),
            "minimum_percent": minimum[0] if minimum else None,
            "maximum_percent": maximum[0] if maximum else None,
            "minimum_at": minimum[1] if minimum else None,
            "maximum_at": maximum[1] if maximum else None,
        },
        "bikes": {
            "mechanical_average": mechanical_average,
            "electric_average": electric_average,
            "free_docks_average": free_docks_average,
            "total_bikes_average": _mean_of(*sums["total_bikes"]),
        },
        "composition": {
            "mechanical_percent": _percent_of(mechanical_average, composition_total),
            "electric_percent": _percent_of(electric_average, composition_total),
            "free_docks_percent": _percent_of(free_docks_average, composition_total),
        },
        "first_observed_at": edges.first_observed_at,
        "last_observed_at": edges.last_observed_at,
        "missing_buckets": hours_in_range - edges.observed_hours,
    }


def _log_query(
    kind: str,
    provider_id: str,
    station_id: str,
    granularity: str | None,
    started: float,
    sql_ms: float,
    rows: int,
    groups: int,
) -> None:
    logger.info(
        "consulta histórica",
        extra={
            "kind": kind,
            "provider_id": provider_id,
            "station_id": station_id,
            "granularity": granularity,
            "duration_ms": round((perf_counter() - started) * 1000, 1),
            "sql_ms": round(sql_ms, 1),
            "rows": rows,
            "groups": groups,
        },
    )


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


def _floor_datetime(value: datetime, granularity: str) -> datetime:
    value = value.astimezone(timezone.utc)
    if granularity == "day":
        local = value.astimezone(LOCAL_ZONE)
        midnight = datetime.combine(local.date(), datetime_time.min, tzinfo=LOCAL_ZONE)
        return midnight.astimezone(timezone.utc)
    return value.replace(minute=0, second=0, microsecond=0)


def aggregate_history(
    observations: Sequence[Observation], start: datetime, end: datetime, granularity: str
) -> list[dict[str, object]]:
    if granularity == "raw":
        return [_point(observation) for observation in observations]
    grouped: dict[datetime, list[Observation]] = {}
    moment = _floor_datetime(start, granularity)
    while moment <= end:
        grouped[moment] = []
        moment = _next_bucket(moment, granularity)
    for observation in observations:
        key = _floor_datetime(observation.observed_at, granularity)
        if key in grouped:
            grouped[key].append(observation)
    return [_aggregate_bucket(timestamp, values) for timestamp, values in grouped.items()]


def _next_bucket(moment: datetime, granularity: str) -> datetime:
    if granularity == "day":
        next_date = moment.astimezone(LOCAL_ZONE).date() + timedelta(days=1)
        return datetime.combine(next_date, datetime_time.min, tzinfo=LOCAL_ZONE).astimezone(
            timezone.utc
        )
    return moment + timedelta(hours=1)


def _aggregate_bucket(
    timestamp: datetime, observations: Sequence[Observation]
) -> dict[str, object]:
    def values(name: str) -> list[float]:
        return [
            float(value)
            for value in (getattr(item, name) for item in observations)
            if value is not None
        ]

    occupancy = [
        value
        for value in (occupancy_percent(item.capacity, item.free_docks) for item in observations)
        if value is not None
    ]
    return {
        "timestamp": timestamp,
        "mechanical": _mean(values("mechanical_bikes")),
        "electric": _mean(values("electric_bikes")),
        "free_docks": _mean(values("free_docks")),
        "capacity": _mean(values("capacity")),
        "occupancy_percent": _mean(occupancy),
        "observations": len(observations),
    }


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _mean_of(total: int, count: int) -> float | None:
    return round(total / count, 2) if count else None


def _occupancy_mean(cents: int, count: int, sequence: Callable[[], OccupancyRows]) -> float | None:
    """Media de la ocupación (ya redondeada por observación) con 2 decimales.

    Fuera de los empates la media exacta, redondeada a la mitad par, es la que daba la suma
    en coma flotante. En un empate exacto (p. ej. 85,835) el resultado de esa suma dependía
    del ruido de la coma flotante: ahí se repite la suma original fila a fila, en el mismo
    orden, para devolver exactamente lo mismo que antes.
    """
    if not count:
        return None
    if (2 * cents) % (2 * count) == count:
        values = [
            value
            for value in (occupancy_percent(capacity, free) for capacity, free in sequence())
            if value is not None
        ]
        return round(sum(values) / len(values), 2)
    return round(Fraction(cents, count)) / 100


def _percent_of(value: float | None, total: float) -> float | None:
    return round(value / total * 100, 2) if value is not None and total > 0 else None
