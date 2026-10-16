import logging
from datetime import datetime, timezone
from uuid import uuid4

from movilidad.application.ports import MobilityProvider, ObservationRepository
from movilidad.domain.entities import Capture, Observation

logger = logging.getLogger(__name__)


class CapturePipeline:
    def __init__(self, repository: ObservationRepository, provider: MobilityProvider) -> None:
        self.repository = repository
        self.provider = provider

    def run(self) -> str:
        capture_id = str(uuid4())
        started_at = datetime.now(timezone.utc)
        self.repository.ensure_provider(self.provider.provider_id, "BIKI Valladolid", "gbfs")
        if not self.repository.acquire_capture_lock(self.provider.provider_id, capture_id):
            logger.info(
                "Captura omitida: ya existe otra ejecución",
                extra={"provider_id": self.provider.provider_id},
            )
            return "skipped"
        capture = Capture(capture_id, self.provider.provider_id, started_at)
        self.repository.save_capture(capture)
        accepted = rejected = 0
        try:
            for station, observation in self.provider.fetch():
                observation = (
                    Observation(**{**observation.__dict__, "capture_id": capture_id})
                    if hasattr(observation, "__dict__")
                    else Observation(
                        provider_id=observation.provider_id,
                        station_id=observation.station_id,
                        observed_at=observation.observed_at,
                        collected_at=observation.collected_at,
                        source=observation.source,
                        capture_id=capture_id,
                        mechanical_bikes=observation.mechanical_bikes,
                        electric_bikes=observation.electric_bikes,
                        free_docks=observation.free_docks,
                        capacity=observation.capacity,
                        timestamp_ambiguous=observation.timestamp_ambiguous,
                    )
                )
                self.repository.save_station(station, observation.collected_at)
                accepted += int(self.repository.save_observation(observation))
            self.repository.finish_capture(capture_id, "success", accepted, rejected)
            logger.info(
                "Captura completada",
                extra={"capture_id": capture_id, "provider_id": self.provider.provider_id},
            )
            return capture_id
        except Exception as exc:
            self.repository.finish_capture(capture_id, "failed", accepted, rejected, str(exc))
            logger.exception(
                "Captura fallida",
                extra={"capture_id": capture_id, "provider_id": self.provider.provider_id},
            )
            raise
