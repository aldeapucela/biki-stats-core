from datetime import datetime, timezone

from movilidad.domain.entities import Capture, Observation, Station
from movilidad.infrastructure.db.repository import SqliteObservationRepository


def test_repository_is_idempotent_and_returns_latest(connection) -> None:
    repository = SqliteObservationRepository(connection)
    now = datetime.now(timezone.utc)
    repository.ensure_provider("biki", "BIKI Valladolid", "gbfs")
    repository.save_capture(Capture("capture-1", "biki", now))
    assert repository.acquire_capture_lock("biki", "capture-1") is True
    station = Station("biki", "1", "Centro", capacity=10)
    observation = Observation(
        "biki", "1", now, now, "test", "capture-1", mechanical_bikes=3, free_docks=7, capacity=10
    )
    repository.save_station(station, now)
    assert repository.save_observation(observation) is True
    assert repository.save_observation(observation) is False
    assert repository.latest_observations("biki")[0].mechanical_bikes == 3
    repository.finish_capture("capture-1", "success", 1, 0)
    assert repository.acquire_capture_lock("biki", "capture-2") is True


def test_history_range_uses_station_time_index(connection) -> None:
    plan = connection.execute(
        "EXPLAIN QUERY PLAN SELECT observed_at FROM observations "
        "WHERE provider_id = ? AND station_id = ? AND observed_at >= ? AND observed_at <= ?",
        ("biki", "1", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
    ).fetchall()

    assert any(
        "idx_observations_station_time" in row[3]
        or "idx_observations_station_history_covering" in row[3]
        for row in plan
    )
