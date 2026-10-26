from datetime import datetime, timezone
from unittest.mock import Mock

from movilidad.application.services import CurrentStationsService, aggregate_history
from movilidad.domain.entities import HistoryGroup, Observation


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


def test_daily_history_uses_timezone_aware_aggregation() -> None:
    repository = Mock()
    repository.station_exists.return_value = True
    # 22:30 UTC es la hora UTC "2026-06-30T22" con una observación, capacidad 5 y 4 anclajes libres.
    repository.history_groups.return_value = [HistoryGroup("2026-06-30T22", 5, 4, 1, 1, 1, None, 0)]
    service = CurrentStationsService(repository)

    result = service.history(
        "biki",
        "1",
        datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        "day",
        10_000,
    )

    assert result is not None
    populated = [point for point in result["points"] if point["observations"]]
    assert [point["timestamp"] for point in populated] == [
        datetime(2026, 6, 30, 22, 0, tzinfo=timezone.utc)
    ]
    repository.station_history.assert_not_called()
    assert result["points"][1]["mechanical"] == 1.0
