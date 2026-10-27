import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from movilidad.domain.entities import Observation, Station

logger = logging.getLogger(__name__)

# Margen para absorber la diferencia entre el reloj local y el del proveedor. En el feed de
# BIKI (27-oct-2026) ninguna estación reportaba en el futuro: la más reciente tenía 10,8 s.
FUTURE_TOLERANCE = timedelta(seconds=60)


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
        without_last_reported = 0
        for raw in status.get("stations", []):
            station_id = str(raw.get("station_id", ""))
            metadata = stations.get(station_id)
            if not metadata:
                continue
            without_last_reported += raw.get("last_reported") is None
            station = Station(
                provider_id=self.provider_id,
                station_id=station_id,
                name=self._station_name(metadata.get("name"), station_id),
                latitude=metadata.get("lat"),
                longitude=metadata.get("lon"),
                capacity=raw.get("capacity", metadata.get("capacity")),
                is_active=raw.get("is_renting", 1) != 0,
            )
            observed_at = self._observed_at(raw, station_id, now)
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
        if without_last_reported:
            # Un único aviso por captura: si el feed dejara de publicar el campo, avisar por
            # estación inundaría el registro (una línea por estación y captura).
            logger.warning(
                "Estaciones sin last_reported; se usa la hora de captura",
                extra={"stations": without_last_reported, "total": len(result)},
            )
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

    @classmethod
    def _observed_at(cls, raw: dict[str, Any], station_id: str, now: datetime) -> datetime:
        """Hora a la que la estación reportó el dato (`last_reported` de GBFS v3).

        Si falta, no se puede interpretar o está en el futuro más allá de la tolerancia, se usa
        la hora de captura: es preferible un dato con hora aproximada a perder la observación.

        Siempre con precisión de segundo. `iso()` omite los microsegundos cuando valen 0 y, como
        texto, `...46Z` ordena después de `...46.183000Z`: con precisión mixta `MAX(observed_at)`
        podría elegir un dato anterior. La de segundo es además la de las filas importadas.
        """
        capture_second = now.replace(microsecond=0)
        value = raw.get("last_reported")
        if value is None:
            return capture_second
        try:
            observed_at = cls._timestamp(value, now)
        except (TypeError, ValueError, OverflowError, OSError):
            logger.warning(
                "last_reported no válido; se usa la hora de captura",
                extra={"station_id": station_id, "last_reported": str(value)[:40]},
            )
            return capture_second
        if observed_at > now + FUTURE_TOLERANCE:
            logger.warning(
                "last_reported en el futuro; se usa la hora de captura",
                extra={"station_id": station_id, "last_reported": str(value)[:40]},
            )
            return capture_second
        return observed_at.replace(microsecond=0)

    @staticmethod
    def _timestamp(value: Any, fallback: datetime) -> datetime:
        if value is None:
            return fallback
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
