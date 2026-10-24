from datetime import datetime, timezone

from movilidad.application.services import aggregate_history
from movilidad.domain.entities import Observation


def _observation(moment: datetime) -> Observation:
    return Observation(
        "biki", "1", moment, moment, "test", "c", mechanical_bikes=1, free_docks=4, capacity=5
    )


def test_daily_buckets_start_at_madrid_midnight() -> None:
    # 2026-07-01 00:30 en Madrid (CEST, UTC+2) es 2026-06-30 22:30 UTC.
    moment = datetime(2026, 6, 30, 22, 30, tzinfo=timezone.utc)
    start = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    points = aggregate_history([_observation(moment)], start, end, "day")
    populated = [point for point in points if point["observations"]]
    assert [point["timestamp"] for point in populated] == [
        datetime(2026, 6, 30, 22, 0, tzinfo=timezone.utc)
    ]


def test_daily_buckets_survive_dst_change() -> None:
    # El 2026-10-25 Madrid pasa de CEST a CET: ese día dura 25 horas.
    start = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)
    points = aggregate_history([], start, end, "day")
    stamps = [point["timestamp"] for point in points]
    assert stamps == [
        datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc),
    ]
