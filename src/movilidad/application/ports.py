from datetime import datetime
from typing import Protocol, Sequence

from movilidad.domain.entities import Capture, Observation, Station


class ObservationRepository(Protocol):
    def ensure_provider(self, provider_id: str, name: str, kind: str) -> None: ...

    def save_capture(self, capture: Capture) -> None: ...

    def finish_capture(
        self,
        capture_id: str,
        status: str,
        accepted: int,
        rejected: int,
        error_message: str | None = None,
    ) -> None: ...

    def save_station(self, station: Station, updated_at: datetime) -> None: ...

    def save_observation(self, observation: Observation) -> bool: ...

    def latest_observations(self, provider_id: str) -> Sequence[Observation]: ...

    def acquire_capture_lock(self, provider_id: str, capture_id: str) -> bool: ...


class MobilityProvider(Protocol):
    provider_id: str

    def fetch(self) -> Sequence[tuple[Station, Observation]]: ...
