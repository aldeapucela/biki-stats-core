from datetime import datetime, timezone

import pytest

from movilidad.domain.entities import Observation
from movilidad.domain.rules import haversine_meters, occupancy_percent


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
