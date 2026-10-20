import sqlite3
from datetime import datetime, timezone

from movilidad.domain.entities import Capture, Observation, Station, StationSnapshot


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SqliteObservationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save_capture(self, capture: Capture) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO captures(capture_id, provider_id, started_at, status) "
            "VALUES (?, ?, ?, ?)",
            (capture.capture_id, capture.provider_id, iso(capture.started_at), "running"),
        )
        self.connection.commit()

    def ensure_provider(self, provider_id: str, name: str, kind: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO providers(id, name, kind, created_at) VALUES (?, ?, ?, ?)",
            (provider_id, name, kind, iso(datetime.now(timezone.utc))),
        )
        self.connection.commit()

    def finish_capture(
        self,
        capture_id: str,
        status: str,
        accepted: int,
        rejected: int,
        error_message: str | None = None,
    ) -> None:
        self.connection.execute(
            "UPDATE captures SET finished_at = ?, status = ?, accepted_count = ?, "
            "rejected_count = ?, error_message = ? WHERE capture_id = ?",
            (
                iso(datetime.now(timezone.utc)),
                status,
                accepted,
                rejected,
                error_message,
                capture_id,
            ),
        )
        self.connection.execute("DELETE FROM capture_locks WHERE capture_id = ?", (capture_id,))
        self.connection.commit()

    def save_station(self, station: Station, updated_at: datetime) -> None:
        self.connection.execute(
            """INSERT INTO stations(provider_id, station_id, name, latitude, longitude,
            capacity, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_id, station_id) DO UPDATE SET name=excluded.name,
            latitude=excluded.latitude, longitude=excluded.longitude,
            capacity=excluded.capacity, is_active=excluded.is_active,
            updated_at=excluded.updated_at""",
            (
                station.provider_id,
                station.station_id,
                station.name,
                station.latitude,
                station.longitude,
                station.capacity,
                int(station.is_active),
                iso(updated_at),
            ),
        )

    def save_observation(self, observation: Observation) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO observations(provider_id, station_id, observed_at,
            collected_at, source,
            capture_id, mechanical_bikes, electric_bikes, free_docks, capacity, timestamp_ambiguous)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation.provider_id,
                observation.station_id,
                iso(observation.observed_at),
                iso(observation.collected_at),
                observation.source,
                observation.capture_id,
                observation.mechanical_bikes,
                observation.electric_bikes,
                observation.free_docks,
                observation.capacity,
                int(observation.timestamp_ambiguous),
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def latest_observations(self, provider_id: str) -> list[Observation]:
        rows = self.connection.execute(
            """SELECT o.* FROM observations o JOIN (
            SELECT station_id, MAX(observed_at) observed_at FROM observations
            WHERE provider_id = ? GROUP BY station_id
            ) latest ON latest.station_id = o.station_id AND latest.observed_at = o.observed_at
            WHERE o.provider_id = ? ORDER BY o.station_id""",
            (provider_id, provider_id),
        ).fetchall()
        return [self._observation(row) for row in rows]

    def list_station_snapshots(
        self,
        provider_id: str,
        query: str | None,
        status: str | None,
        has_electric: bool | None,
        sort: str,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[StationSnapshot], int]:
        where = ["s.provider_id = ?"]
        params: list[object] = [provider_id]
        if query:
            where.append("LOWER(s.name) LIKE ?")
            params.append(f"%{query.lower()}%")
        if status in {"active", "inactive"}:
            where.append("s.is_active = ?")
            params.append(int(status == "active"))
        elif status == "unknown":
            where.append("s.is_active IS NULL")
        if has_electric is True:
            where.append("COALESCE(o.electric_bikes, 0) > 0")
        condition = " AND ".join(where)
        total = self.connection.execute(
            f"""SELECT COUNT(*) FROM stations s
            LEFT JOIN observations o ON o.provider_id = s.provider_id
                AND o.station_id = s.station_id
            AND o.observed_at = (SELECT MAX(o2.observed_at) FROM observations o2
                WHERE o2.provider_id = s.provider_id AND o2.station_id = s.station_id)
            WHERE {condition}""",
            params,
        ).fetchone()[0]
        sort_columns = {
            "name": "s.name",
            "occupancy_percent": "CASE WHEN o.capacity > 0 AND "
            "o.free_docks BETWEEN 0 AND o.capacity "
            "THEN (o.capacity - o.free_docks) * 1.0 / o.capacity ELSE NULL END",
            "data_age_seconds": "o.observed_at",
        }
        sort_sql = sort_columns.get(sort, "s.name")
        direction = "DESC" if order == "desc" else "ASC"
        rows = self.connection.execute(
            f"""SELECT s.provider_id, s.station_id, s.name, s.latitude, s.longitude, s.capacity,
            s.is_active, o.observed_at AS o_observed_at, o.collected_at AS o_collected_at,
            o.source AS o_source, o.capture_id AS o_capture_id, o.mechanical_bikes AS o_mechanical,
            o.electric_bikes AS o_electric, o.free_docks AS o_free_docks, o.capacity AS o_capacity,
            o.timestamp_ambiguous AS o_ambiguous
            FROM stations s LEFT JOIN observations o ON o.provider_id = s.provider_id
            AND o.station_id = s.station_id AND o.observed_at = (SELECT MAX(o2.observed_at)
                FROM observations o2 WHERE o2.provider_id = s.provider_id
                AND o2.station_id = s.station_id)
            WHERE {condition} ORDER BY {sort_sql} {direction}, s.station_id ASC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        return [self._snapshot(row) for row in rows], total

    def get_station_snapshot(self, provider_id: str, station_id: str) -> StationSnapshot | None:
        row = self.connection.execute(
            """SELECT s.provider_id, s.station_id, s.name, s.latitude, s.longitude, s.capacity,
            s.is_active, o.observed_at AS o_observed_at, o.collected_at AS o_collected_at,
            o.source AS o_source, o.capture_id AS o_capture_id, o.mechanical_bikes AS o_mechanical,
            o.electric_bikes AS o_electric, o.free_docks AS o_free_docks, o.capacity AS o_capacity,
            o.timestamp_ambiguous AS o_ambiguous
            FROM stations s LEFT JOIN observations o ON o.provider_id = s.provider_id
            AND o.station_id = s.station_id AND o.observed_at = (SELECT MAX(o2.observed_at)
                FROM observations o2 WHERE o2.provider_id = s.provider_id
                AND o2.station_id = s.station_id)
            WHERE s.provider_id = ? AND s.station_id = ?""",
            (provider_id, station_id),
        ).fetchone()
        return self._snapshot(row) if row else None

    def station_exists(self, provider_id: str, station_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM stations WHERE provider_id = ? AND station_id = ?",
                (provider_id, station_id),
            ).fetchone()
            is not None
        )

    def station_history(
        self, provider_id: str, station_id: str, start: datetime, end: datetime
    ) -> list[Observation]:
        rows = self.connection.execute(
            """SELECT provider_id, station_id, observed_at, collected_at, source, capture_id,
            mechanical_bikes, electric_bikes, free_docks, capacity, timestamp_ambiguous
            FROM observations WHERE provider_id = ? AND station_id = ?
            AND observed_at >= ? AND observed_at <= ? ORDER BY observed_at ASC""",
            (provider_id, station_id, iso(start), iso(end)),
        ).fetchall()
        return [self._observation(row) for row in rows]

    def acquire_capture_lock(self, provider_id: str, capture_id: str) -> bool:
        try:
            self.connection.execute(
                "INSERT INTO capture_locks(provider_id, capture_id, acquired_at) VALUES (?, ?, ?)",
                (provider_id, capture_id, iso(datetime.now(timezone.utc))),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            self.connection.rollback()
            return False

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> StationSnapshot:
        station = Station(
            provider_id=row["provider_id"],
            station_id=row["station_id"],
            name=row["name"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            capacity=row["capacity"],
            is_active=bool(row["is_active"]),
        )
        if row["o_observed_at"] is None:
            return StationSnapshot(station=station, observation=None)
        observation = Observation(
            provider_id=row["provider_id"],
            station_id=row["station_id"],
            observed_at=datetime.fromisoformat(row["o_observed_at"].replace("Z", "+00:00")),
            collected_at=datetime.fromisoformat(row["o_collected_at"].replace("Z", "+00:00")),
            source=row["o_source"],
            capture_id=row["o_capture_id"],
            mechanical_bikes=row["o_mechanical"],
            electric_bikes=row["o_electric"],
            free_docks=row["o_free_docks"],
            capacity=row["o_capacity"],
            timestamp_ambiguous=bool(row["o_ambiguous"]),
        )
        return StationSnapshot(station=station, observation=observation)

    @staticmethod
    def _observation(row: sqlite3.Row) -> Observation:
        return Observation(
            provider_id=row["provider_id"],
            station_id=row["station_id"],
            observed_at=datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")),
            collected_at=datetime.fromisoformat(row["collected_at"].replace("Z", "+00:00")),
            source=row["source"],
            capture_id=row["capture_id"],
            mechanical_bikes=row["mechanical_bikes"],
            electric_bikes=row["electric_bikes"],
            free_docks=row["free_docks"],
            capacity=row["capacity"],
            timestamp_ambiguous=bool(row["timestamp_ambiguous"]),
        )
