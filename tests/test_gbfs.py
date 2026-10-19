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
