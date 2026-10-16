import sqlite3
from datetime import datetime, timezone

from movilidad.domain.entities import Capture, Observation, Station


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
