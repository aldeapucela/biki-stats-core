import re
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
            vehicle_types = (
                self._get_json(client, feeds["vehicle_types"]) if "vehicle_types" in feeds else {}
            )
            return self._normalise(station_info, station_status, vehicle_types)
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
        self,
        info: dict[str, Any],
        status: dict[str, Any],
        vehicle_types: dict[str, Any] | None = None,
    ) -> list[tuple[Station, Observation]]:
        stations = {str(item["station_id"]): item for item in info.get("stations", [])}
        mechanical_ids, electric_ids = self._vehicle_type_ids(vehicle_types or {})
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
                name=self._station_name(metadata.get("name"), station_id),
                latitude=metadata.get("lat"),
                longitude=metadata.get("lon"),
                capacity=raw.get("capacity", metadata.get("capacity")),
                is_active=raw.get("is_renting", 1) != 0,
            )
            observed_at = self._timestamp(raw.get("last_report"), now)
            mechanical_bikes, electric_bikes = self._bike_counts(raw, mechanical_ids, electric_ids)
            observation = Observation(
                provider_id=self.provider_id,
                station_id=station_id,
                observed_at=observed_at,
                collected_at=now,
                source="gbfs",
                capture_id="pending",
                mechanical_bikes=mechanical_bikes,
                electric_bikes=electric_bikes,
                free_docks=raw.get("num_docks_available"),
                capacity=station.capacity,
            )
            result.append((station, observation))
        return result

    @staticmethod
    def _vehicle_type_ids(vehicle_types: dict[str, Any]) -> tuple[set[str], set[str]]:
        mechanical: set[str] = set()
        electric: set[str] = set()
        for vehicle_type in vehicle_types.get("vehicle_types", []):
            vehicle_type_id = vehicle_type.get("vehicle_type_id")
            if vehicle_type.get("form_factor") != "bicycle" or not vehicle_type_id:
                continue
            if vehicle_type.get("propulsion_type") == "electric_assist":
                electric.add(str(vehicle_type_id))
            elif vehicle_type.get("propulsion_type") == "human":
                mechanical.add(str(vehicle_type_id))
        return mechanical, electric

    @staticmethod
    def _bike_counts(
        raw: dict[str, Any], mechanical_ids: set[str], electric_ids: set[str]
    ) -> tuple[int | None, int | None]:
        legacy = raw.get("num_bikes_available_types") or {}
        if legacy.get("mechanical") is not None or legacy.get("electric") is not None:
            return legacy.get("mechanical"), legacy.get("electric")
        available = raw.get("vehicle_types_available") or []
        if not available or not mechanical_ids and not electric_ids:
            return None, None
        mechanical = sum(
            int(item.get("count", 0))
            for item in available
            if str(item.get("vehicle_type_id")) in mechanical_ids
        )
        electric = sum(
            int(item.get("count", 0))
            for item in available
            if str(item.get("vehicle_type_id")) in electric_ids
        )
        return mechanical, electric

    @staticmethod
    def _station_name(value: Any, fallback: str) -> str:
        def clean(name: str) -> str:
            return re.sub(r"^\s*\d+\s+", "", name).strip() or fallback

        if isinstance(value, str) and value.strip():
            return clean(value)
        if isinstance(value, list):
            names = {
                item.get("language"): item.get("text") for item in value if isinstance(item, dict)
            }
            for language in ("es", "en"):
                if names.get(language):
                    return clean(str(names[language]))
            for item in value:
                if isinstance(item, dict) and item.get("text"):
                    return clean(str(item["text"]))
        if isinstance(value, dict) and value.get("text"):
            return clean(str(value["text"]))
        return fallback

    @staticmethod
    def _timestamp(value: Any, fallback: datetime) -> datetime:
        if value is None:
            return fallback
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
