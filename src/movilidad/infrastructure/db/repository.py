import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from movilidad.domain.entities import (
    Capture,
    HistoryGroup,
    Observation,
    Station,
    StationSnapshot,
    SummaryGroup,
    SummaryRange,
)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_instant(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


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

    def save_historical_station(self, station: Station, updated_at: datetime) -> None:
        """Guarda una estación sin borrar metadatos actuales conocidos."""
        self.connection.execute(
            """INSERT INTO stations(provider_id, station_id, name, latitude, longitude,
            capacity, is_active, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_id, station_id) DO UPDATE SET name=excluded.name,
            capacity=COALESCE(excluded.capacity, stations.capacity),
            updated_at=CASE WHEN stations.updated_at > excluded.updated_at
                THEN stations.updated_at ELSE excluded.updated_at END""",
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

    def station_capacities(self, provider_id: str) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT station_id, capacity FROM stations "
            "WHERE provider_id = ? AND capacity IS NOT NULL",
            (provider_id,),
        ).fetchall()
        return {str(row["station_id"]): int(row["capacity"]) for row in rows}

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

    def save_historical_observation(self, observation: Observation) -> str:
        """Inserta sin commit y clasifica inserciones, duplicados y conflictos."""
        values = (
            observation.mechanical_bikes,
            observation.electric_bikes,
            observation.free_docks,
            observation.capacity,
            int(observation.timestamp_ambiguous),
        )
        existing = self.connection.execute(
            """SELECT mechanical_bikes, electric_bikes, free_docks, capacity,
            timestamp_ambiguous FROM observations
            WHERE provider_id = ? AND station_id = ? AND observed_at = ?""",
            (observation.provider_id, observation.station_id, iso(observation.observed_at)),
        ).fetchone()
        if existing:
            return "duplicate" if tuple(existing) == values else "conflict"
        self.connection.execute(
            """INSERT INTO observations(provider_id, station_id, observed_at, collected_at,
            source, capture_id, mechanical_bikes, electric_bikes, free_docks, capacity,
            timestamp_ambiguous) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        return "accepted"

    def historical_import_status(self, source_key: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM historical_imports WHERE source_key = ?", (source_key,)
        ).fetchone()
        return dict(row) if row else None

    def claim_historical_import(
        self,
        source_key: str,
        source_repository: str,
        source_ref: str,
        now: datetime,
        stale_after_seconds: int = 1800,
        force: bool = False,
    ) -> str:
        """Reclama la importación de forma atómica para evitar workers concurrentes."""
        now_iso = iso(now)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT status, updated_at FROM historical_imports WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if row and row["status"] == "completed" and not force:
                self.connection.commit()
                return "completed"
            if row and row["status"] == "running":
                updated = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
                if (now - updated).total_seconds() < stale_after_seconds:
                    self.connection.commit()
                    return "running"
            self.connection.execute(
                """INSERT INTO historical_imports(
                source_key, source_repository, source_ref, status, started_at, updated_at)
                VALUES (?, ?, ?, 'running', ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET source_repository=excluded.source_repository,
                source_ref=excluded.source_ref, status='running', started_at=excluded.started_at,
                finished_at=NULL, updated_at=excluded.updated_at, error_message=NULL""",
                (source_key, source_repository, source_ref, now_iso, now_iso),
            )
            self.connection.commit()
            return "claimed"
        except Exception:
            self.connection.rollback()
            raise

    def finish_historical_import(
        self,
        source_key: str,
        status: str,
        finished_at: datetime,
        *,
        source_commit: str | None = None,
        manifest_json: str | None = None,
        accepted: int = 0,
        duplicate: int = 0,
        conflict: int = 0,
        rejected: int = 0,
        derived: int = 0,
        error_message: str | None = None,
    ) -> None:
        self.connection.execute(
            """UPDATE historical_imports SET status=?, source_commit=?, manifest_json=?,
            finished_at=?, updated_at=?, accepted_count=?, duplicate_count=?, conflict_count=?,
            rejected_count=?, derived_count=?, error_message=? WHERE source_key=?""",
            (
                status,
                source_commit,
                manifest_json,
                iso(finished_at),
                iso(finished_at),
                accepted,
                duplicate,
                conflict,
                rejected,
                derived,
                error_message,
                source_key,
            ),
        )
        self.connection.commit()

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

    def history_groups(
        self, provider_id: str, station_id: str, start: datetime, end: datetime, granularity: str
    ) -> list[HistoryGroup]:
        """Agrega en SQLite por franja UTC (prefijo ISO de `observed_at`) y por capacidad/libres."""
        prefix = 13 if granularity == "hour" else 10
        rows = self.connection.execute(
            f"""SELECT substr(observed_at, 1, {prefix}) AS bucket, capacity, free_docks,
            COUNT(*) AS observations, SUM(mechanical_bikes) AS mechanical_sum,
            COUNT(mechanical_bikes) AS mechanical_count, SUM(electric_bikes) AS electric_sum,
            COUNT(electric_bikes) AS electric_count
            FROM observations WHERE provider_id = ? AND station_id = ?
            AND observed_at >= ? AND observed_at <= ?
            GROUP BY bucket, capacity, free_docks""",
            (provider_id, station_id, iso(start), iso(end)),
        ).fetchall()
        return [HistoryGroup(**dict(row)) for row in rows]

    def occupancy_sequence(
        self,
        provider_id: str,
        station_id: str,
        start: datetime,
        end: datetime,
        bucket: str | None = None,
    ) -> list[tuple[int | None, int | None]]:
        """Capacidad y anclajes de cada observación, en orden cronológico (solo para empates).

        Con `bucket` (prefijo ISO de una hora o día) se limita a esa franja.
        """
        low, high = iso(start), iso(end)
        if bucket:
            low, high = max(low, bucket), min(high, bucket + "~")  # "~" sigue a cualquier dígito/Z
        rows = self.connection.execute(
            """SELECT capacity, free_docks FROM observations
            WHERE provider_id = ? AND station_id = ? AND observed_at >= ? AND observed_at <= ?
            ORDER BY observed_at ASC""",
            (provider_id, station_id, low, high),
        ).fetchall()
        return [(row["capacity"], row["free_docks"]) for row in rows]

    def summary_groups(
        self, provider_id: str, station_id: str, start: datetime, end: datetime
    ) -> tuple[list[SummaryGroup], SummaryRange]:
        """Agrupa por contadores iguales: el resumen se calcula sobre ellos, no fila a fila."""
        params = (provider_id, station_id, iso(start), iso(end))
        where = (
            "FROM observations WHERE provider_id = ? AND station_id = ? "
            "AND observed_at >= ? AND observed_at <= ?"
        )
        rows = self.connection.execute(
            f"""SELECT capacity, free_docks, mechanical_bikes, electric_bikes,
            COUNT(*) AS observations, MIN(observed_at) AS first_observed_at {where}
            GROUP BY capacity, free_docks, mechanical_bikes, electric_bikes""",
            params,
        ).fetchall()
        edges = self.connection.execute(
            f"""SELECT MIN(observed_at) AS first_observed_at, MAX(observed_at) AS last_observed_at,
            COUNT(DISTINCT substr(observed_at, 1, 13)) AS observed_hours {where}""",
            params,
        ).fetchone()
        groups = [
            SummaryGroup(
                **{**dict(row), "first_observed_at": _parse_instant(row["first_observed_at"])}
            )
            for row in rows
        ]
        return groups, SummaryRange(
            first_observed_at=_parse_instant(edges["first_observed_at"]),
            last_observed_at=_parse_instant(edges["last_observed_at"]),
            observed_hours=edges["observed_hours"],
        )

    def acquire_capture_lock(
        self, provider_id: str, capture_id: str, stale_after_seconds: int = 900
    ) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = iso(now - timedelta(seconds=stale_after_seconds))
        try:
            orphans = self.connection.execute(
                "SELECT capture_id FROM capture_locks WHERE provider_id = ? AND acquired_at < ?",
                (provider_id, cutoff),
            ).fetchall()
            for orphan in orphans:
                self.connection.execute(
                    "UPDATE captures SET finished_at = ?, status = 'failed', "
                    "error_message = 'lock caducado: la captura no terminó' "
                    "WHERE capture_id = ? AND status = 'running'",
                    (iso(now), orphan["capture_id"]),
                )
                self.connection.execute(
                    "DELETE FROM capture_locks WHERE capture_id = ?", (orphan["capture_id"],)
                )
            self.connection.execute(
                "INSERT INTO capture_locks(provider_id, capture_id, acquired_at) VALUES (?, ?, ?)",
                (provider_id, capture_id, iso(now)),
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
