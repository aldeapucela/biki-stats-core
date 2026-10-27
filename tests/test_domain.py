from datetime import datetime, timedelta, timezone

import pytest

from movilidad.domain.entities import Observation
from movilidad.domain.rules import haversine_meters, is_stale, occupancy_percent


def test_observation_rejects_negative_counters() -> None:
    with pytest.raises(ValueError, match="no negativo"):
        Observation(
            provider_id="biki",
            station_id="1",
            observed_at=datetime.now(timezone.utc),
            collected_at=datetime.now(timezone.utc),
            source="test",
            capture_id="capture",
            mechanical_bikes=-1,
        )


def test_occupancy_and_geolocation_rules() -> None:
    assert occupancy_percent(10, 5) == 50.0
    assert occupancy_percent(0, 0) is None
    assert haversine_meters(41.65, -4.72, 41.65, -4.72) == 0


def test_is_stale_after_600_seconds_without_reporting() -> None:
    now = datetime.now(timezone.utc)
    assert is_stale(now - timedelta(seconds=599)) is False
    assert is_stale(now - timedelta(seconds=601)) is True
    assert is_stale(None) is True
