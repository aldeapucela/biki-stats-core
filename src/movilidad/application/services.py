import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from time import perf_counter

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
                rows = self.repository.occupancy_sequence(
                    provider_id, station_id, start, end, bucket
                )
                fallback_sql_seconds += perf_counter() - fallback_started
                return rows

            history_groups = self.repository.history_groups(
                provider_id, station_id, start, end, granularity
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
        total = totals.setdefault(group.bucket, _BucketTotals())
        total.add(group)
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    pattern = "%Y-%m-%dT%H" if granularity == "hour" else "%Y-%m-%d"
    points: list[dict[str, object]] = []
    moment = _floor_datetime(start, granularity)
    while moment <= end:
        key = moment.strftime(pattern)
        total = totals.get(key) or _BucketTotals()
        points.append(total.point(moment, lambda key=key: sequence(key)))
        moment += step
    return points


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
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


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
