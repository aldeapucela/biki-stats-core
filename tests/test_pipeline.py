from datetime import datetime, timezone

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
