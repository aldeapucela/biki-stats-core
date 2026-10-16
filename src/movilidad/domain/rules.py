import math
from datetime import datetime, timezone


def occupancy_percent(capacity: int | float | None, free_docks: int | float | None) -> float | None:
    if (
        capacity is None
        or free_docks is None
        or capacity <= 0
        or free_docks < 0
        or free_docks > capacity
    ):
        return None
    return round((capacity - free_docks) / capacity * 100, 2)


def data_age_seconds(observed_at: datetime | None, now: datetime | None = None) -> int | None:
    if observed_at is None:
        return None
    current = now or datetime.now(timezone.utc)
    observed = observed_at.astimezone(timezone.utc)
    return max(0, int((current - observed).total_seconds()))


def is_stale(observed_at: datetime | None, stale_after_seconds: int = 600) -> bool:
    age = data_age_seconds(observed_at)
    return age is None or age > stale_after_seconds


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(value)))
