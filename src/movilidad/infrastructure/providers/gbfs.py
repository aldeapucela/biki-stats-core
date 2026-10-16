from datetime import datetime, timezone
from typing import Any

import httpx

from movilidad.domain.entities import Observation, Station


class GbfsProvider:
    provider_id = "biki"
    provider_name = "BIKI Valladolid"

    def __init__(
        self, discovery_url: str, timeout: float = 20.0, client: httpx.Client | None = None
    ) -> None:
        self.discovery_url = discovery_url
        self.timeout = timeout
        self._client = client

    def fetch(self) -> list[tuple[Station, Observation]]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            discovery = client.get(self.discovery_url)
            discovery.raise_for_status()
            feeds = self._feed_urls(discovery.json().get("data", {}).get("feeds", []))
            station_info = self._get_json(client, feeds["station_information"])
            station_status = self._get_json(client, feeds["station_status"])
            return self._normalise(station_info, station_status)
        finally:
            if owns_client:
                client.close()

    def _feed_urls(self, feeds: list[dict[str, Any]]) -> dict[str, str]:
        urls: dict[str, str] = {}
        for feed in feeds:
            name = feed.get("name")
            url = feed.get("url")
            if name and url:
                urls[name] = url
        missing = {"station_information", "station_status"} - urls.keys()
        if missing:
            raise ValueError(f"Faltan feeds GBFS requeridos: {', '.join(sorted(missing))}")
        return urls

    @staticmethod
    def _get_json(client: httpx.Client, url: str) -> dict[str, Any]:
        response = client.get(url)
        response.raise_for_status()
        return response.json().get("data", {})

    def _normalise(
        self, info: dict[str, Any], status: dict[str, Any]
    ) -> list[tuple[Station, Observation]]:
        stations = {str(item["station_id"]): item for item in info.get("stations", [])}
        now = datetime.now(timezone.utc)
        result: list[tuple[Station, Observation]] = []
        for raw in status.get("stations", []):
            station_id = str(raw.get("station_id", ""))
            metadata = stations.get(station_id)
            if not metadata:
                continue
            station = Station(
                provider_id=self.provider_id,
                station_id=station_id,
                name=str(metadata.get("name", station_id)),
                latitude=metadata.get("lat"),
                longitude=metadata.get("lon"),
                capacity=raw.get("capacity", metadata.get("capacity")),
                is_active=raw.get("is_renting", 1) != 0,
            )
            observed_at = self._timestamp(raw.get("last_report"), now)
            observation = Observation(
                provider_id=self.provider_id,
                station_id=station_id,
                observed_at=observed_at,
                collected_at=now,
                source="gbfs",
                capture_id="pending",
                mechanical_bikes=raw.get("num_bikes_available_types", {}).get("mechanical"),
                electric_bikes=raw.get("num_bikes_available_types", {}).get("electric"),
                free_docks=raw.get("num_docks_available"),
                capacity=station.capacity,
            )
            result.append((station, observation))
        return result

    @staticmethod
    def _timestamp(value: Any, fallback: datetime) -> datetime:
        if value is None:
            return fallback
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
