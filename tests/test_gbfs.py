import logging
from datetime import datetime, timedelta, timezone

from movilidad.infrastructure.providers.gbfs import GbfsProvider


def test_station_name_prefers_spanish_translation() -> None:
    value = [
        {"language": "en", "text": "Fuente Dorada"},
        {"language": "es", "text": "Fuente Dorada"},
    ]
    assert GbfsProvider._station_name(value, "unknown") == "Fuente Dorada"


def test_station_name_removes_initial_station_number() -> None:
    assert GbfsProvider._station_name("001 Fuente Dorada", "unknown") == "Fuente Dorada"


def test_station_name_falls_back_to_first_translation() -> None:
    value = [{"language": "fr", "text": "Place"}]
    assert GbfsProvider._station_name(value, "unknown") == "Place"


def test_bike_counts_support_gbfs_v3_vehicle_types() -> None:
    raw = {
        "vehicle_types_available": [
            {"vehicle_type_id": "FIT", "count": 6},
            {"vehicle_type_id": "EFIT", "count": 1},
        ]
    }
    assert GbfsProvider._bike_counts(raw, {"FIT"}, {"EFIT"}) == (6, 1)


INFO = {
    "stations": [
        {"station_id": "1", "name": "001 Plaza", "lat": 41.65, "lon": -4.72, "capacity": 10},
        {"station_id": "2", "name": "002 Campus", "lat": 41.66, "lon": -4.73, "capacity": 12},
    ]
}
VEHICLE_TYPES = {
    "vehicle_types": [
        {"vehicle_type_id": "FIT", "form_factor": "bicycle", "propulsion_type": "human"},
        {"vehicle_type_id": "EFIT", "form_factor": "bicycle", "propulsion_type": "electric_assist"},
    ]
}


def _status(**reported: object) -> dict:
    """`reported` asigna `last_reported` por estación; `None` omite el campo."""
    stations = []
    for station_id, value in reported.items():
        item = {
            "station_id": station_id.removeprefix("s"),
            "num_docks_available": 4,
            "is_renting": True,
            "vehicle_types_available": [
                {"vehicle_type_id": "FIT", "count": 2},
                {"vehicle_type_id": "EFIT", "count": 1},
            ],
        }
        if value is not None:
            item["last_reported"] = value
        stations.append(item)
    return {"stations": stations}


def _observations(status: dict) -> dict[str, tuple[datetime, datetime]]:
    result = GbfsProvider("https://example.test")._normalise(INFO, status, VEHICLE_TYPES)
    return {o.station_id: (o.observed_at, o.collected_at) for _, o in result}


def test_observed_at_comes_from_last_reported_of_each_station() -> None:
    status = _status(s1="2026-10-27T10:34:46.183Z", s2="2026-10-27T10:31:02Z")
    observed = _observations(status)
    assert observed["1"][0] == datetime(2026, 10, 27, 10, 34, 46, 183000, tzinfo=timezone.utc)
    assert observed["2"][0] == datetime(2026, 10, 27, 10, 31, 2, tzinfo=timezone.utc)
    # Antes todas las estaciones compartían la hora de captura.
    assert observed["1"][0] != observed["2"][0]
    assert observed["1"][1] == observed["2"][1]
    assert observed["1"][1] > observed["1"][0]


def test_observed_at_accepts_epoch_seconds() -> None:
    observed = _observations(_status(s1=1793097286, s2=None))
    assert observed["1"][0] == datetime(2026, 10, 27, 10, 34, 46, tzinfo=timezone.utc)


def test_observed_at_treats_timestamp_without_zone_as_utc() -> None:
    observed = _observations(_status(s1="2026-10-27T10:34:46", s2=None))
    assert observed["1"][0] == datetime(2026, 10, 27, 10, 34, 46, tzinfo=timezone.utc)


def test_observed_at_falls_back_to_capture_time_when_missing() -> None:
    before = datetime.now(timezone.utc)
    observed = _observations(_status(s1=None, s2=None))
    after = datetime.now(timezone.utc)
    for observed_at, collected_at in observed.values():
        assert observed_at == collected_at
        assert before <= observed_at <= after


def test_missing_last_reported_logs_one_warning_per_capture(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _observations(_status(s1=None, s2=None))
    avisos = [r for r in caplog.records if "sin last_reported" in r.getMessage()]
    assert len(avisos) == 1
    assert avisos[0].stations == 2


def test_no_warning_when_every_station_reports_last_reported(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _observations(_status(s1="2026-10-27T10:34:46Z", s2="2026-10-27T10:31:02Z"))
    assert caplog.records == []


def test_observed_at_falls_back_when_last_reported_is_invalid(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        observed = _observations(_status(s1="no-es-una-fecha", s2="2026-10-27T10:31:02Z"))
    assert observed["1"][0] == observed["1"][1]
    assert observed["2"][0] == datetime(2026, 10, 27, 10, 31, 2, tzinfo=timezone.utc)
    assert "last_reported no válido" in caplog.text


def test_observed_at_falls_back_when_last_reported_is_in_the_future(caplog) -> None:
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    near = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
    with caplog.at_level(logging.WARNING):
        observed = _observations(_status(s1=future, s2=near))
    assert observed["1"][0] == observed["1"][1]
    assert observed["2"][0] == datetime.fromisoformat(near)
    assert "en el futuro" in caplog.text
