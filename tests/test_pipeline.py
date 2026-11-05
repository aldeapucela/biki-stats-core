from datetime import datetime, timedelta, timezone

from movilidad.collector.pipeline import CapturePipeline
from movilidad.domain.entities import Observation, Station
from movilidad.infrastructure.db.repository import SqliteObservationRepository


class FakeProvider:
    provider_id = "fake"

    def fetch(self):
        now = datetime.now(timezone.utc)
        return [
            (
                Station("fake", "1", "Test", capacity=5),
                Observation(
                    "fake",
                    "1",
                    now,
                    now,
                    "fixture",
                    "pending",
                    mechanical_bikes=2,
                    free_docks=3,
                    capacity=5,
                ),
            )
        ]


def test_pipeline_records_capture_and_observation(connection) -> None:
    result = CapturePipeline(SqliteObservationRepository(connection), FakeProvider()).run()
    assert result not in {"skipped", ""}
    assert connection.execute("SELECT status FROM captures").fetchone()[0] == "success"
    assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


class ReportedAtProvider:
    """Estación que reporta a su hora y no vuelve a reportar entre dos capturas."""

    provider_id = "fake"

    def __init__(self, reported_at: datetime) -> None:
        self.reported_at = reported_at

    def fetch(self):
        now = datetime.now(timezone.utc)
        return [
            (
                Station("fake", "1", "Test", capacity=5),
                Observation(
                    "fake",
                    "1",
                    self.reported_at,
                    now,
                    "fixture",
                    "pending",
                    mechanical_bikes=2,
                    free_docks=3,
                    capacity=5,
                ),
            )
        ]


def test_pipeline_does_not_duplicate_station_that_did_not_report_again(connection) -> None:
    reported_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    repository = SqliteObservationRepository(connection)
    CapturePipeline(repository, ReportedAtProvider(reported_at)).run()
    CapturePipeline(repository, ReportedAtProvider(reported_at)).run()
    rows = connection.execute("SELECT observed_at, collected_at FROM observations").fetchall()
    assert len(rows) == 1
    assert rows[0]["observed_at"] < rows[0]["collected_at"]
    assert connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 2
