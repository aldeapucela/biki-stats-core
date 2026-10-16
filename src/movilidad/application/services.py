from collections.abc import Sequence

from movilidad.application.ports import ObservationRepository
from movilidad.domain.entities import Observation


class CurrentStationsService:
    def __init__(self, repository: ObservationRepository) -> None:
        self.repository = repository

    def list_current(self, provider_id: str) -> Sequence[Observation]:
        return self.repository.latest_observations(provider_id)
