from datetime import datetime, timezone

import pytest

from movilidad.domain.entities import Observation


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
