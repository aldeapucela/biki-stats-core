from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Station:
    provider_id: str
    station_id: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    capacity: int | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class Observation:
    provider_id: str
    station_id: str
    observed_at: datetime
    collected_at: datetime
    source: str
    capture_id: str
    mechanical_bikes: int | None = None
    electric_bikes: int | None = None
    free_docks: int | None = None
    capacity: int | None = None
    timestamp_ambiguous: bool = False

    def __post_init__(self) -> None:
        for field in ("mechanical_bikes", "electric_bikes", "free_docks", "capacity"):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValueError(f"{field} debe ser no negativo")


@dataclass(frozen=True, slots=True)
class Capture:
    capture_id: str
    provider_id: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class StationSnapshot:
    station: Station
    observation: Observation | None


@dataclass(frozen=True, slots=True)
class HistoryGroup:
    """Observaciones de una franja (hora o día UTC) con la misma capacidad y anclajes libres."""

    bucket: str
    capacity: int | None
    free_docks: int | None
    observations: int
    mechanical_sum: int | None
    mechanical_count: int
    electric_sum: int | None
    electric_count: int


@dataclass(frozen=True, slots=True)
class SummaryGroup:
    """Observaciones de un rango con los mismos contadores; `first_observed_at` es la primera."""

    capacity: int | None
    free_docks: int | None
    mechanical_bikes: int | None
    electric_bikes: int | None
    observations: int
    first_observed_at: datetime


@dataclass(frozen=True, slots=True)
class SummaryRange:
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    observed_hours: int
