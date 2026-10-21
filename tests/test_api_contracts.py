from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from movilidad.api.main import app
from movilidad.core.config import Settings, get_settings
from movilidad.domain.entities import Capture, Observation, Station
from movilidad.infrastructure.db.connection import connect, ensure_schema
from movilidad.infrastructure.db.repository import SqliteObservationRepository


def _client_with_data(tmp_path, monkeypatch) -> TestClient:
    database = tmp_path / "contract.sqlite3"
    settings = Settings(BIKI_DATABASE_PATH=str(database))
    connection = connect(settings)
    ensure_schema(connection)
    repository = SqliteObservationRepository(connection)
    repository.ensure_provider("biki", "BIKI Valladolid", "gbfs")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    repository.save_capture(Capture("fixture", "biki", now))
    repository.acquire_capture_lock("biki", "fixture")
    repository.save_station(Station("biki", "1", "Fuente Dorada", 41.65, -4.72, 10), now)
    repository.save_observation(
        Observation("biki", "1", now - timedelta(minutes=5), now, "fixture", "fixture", 3, 2, 5, 10)
    )
    repository.save_observation(
        Observation("biki", "1", now, now, "fixture", "fixture", 4, 1, 5, 10)
    )
    repository.finish_capture("fixture", "success", 2, 0)
    connection.close()
    monkeypatch.setenv("BIKI_DATABASE_PATH", str(database))
    get_settings.cache_clear()
    return TestClient(app)


def test_station_list_and_detail_contract(tmp_path, monkeypatch) -> None:
    with _client_with_data(tmp_path, monkeypatch) as client:
        response = client.get("/api/v1/stations?limit=1")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["code"] == 200
        assert body["data"][0]["occupancy_percent"] == 50.0
        assert body["meta"]["pagination"]["has_more"] is False
        detail = client.get("/api/v1/stations/1")
        assert detail.status_code == 200
        assert detail.json()["data"]["station_id"] == "1"


def test_nearby_history_summary_and_cache(tmp_path, monkeypatch) -> None:
    with _client_with_data(tmp_path, monkeypatch) as client:
        nearby = client.get("/api/v1/stations/nearby?lat=41.65&lon=-4.72&radius_m=1000")
        assert nearby.status_code == 200
        assert nearby.json()["data"][0]["distance_m"] == 0

        start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        history = client.get(f"/api/v1/stations/1/history?from={start}&to={end}&granularity=raw")
        assert history.status_code == 200
        assert len(history.json()["data"]["points"]) == 2
        summary = client.get(f"/api/v1/stations/1/summary?from={start}&to={end}")
        assert summary.status_code == 200
        assert summary.json()["data"]["observations"] == 2

        etag = nearby.headers["etag"]
        cached = client.get(
            "/api/v1/stations/nearby?lat=41.65&lon=-4.72&radius_m=1000",
            headers={"If-None-Match": etag},
        )
        assert cached.status_code == 304


def test_validation_and_not_found_use_common_error_contract(tmp_path, monkeypatch) -> None:
    with _client_with_data(tmp_path, monkeypatch) as client:
        invalid = client.get("/api/v1/stations/nearby?lat=100&lon=0")
        assert invalid.status_code == 422
        assert invalid.json()["errors"][0]["code"] == "INVALID_QUERY_PARAMETER"
        missing = client.get("/api/v1/stations/404")
        assert missing.status_code == 404
        assert missing.json()["errors"][0]["code"] == "RESOURCE_NOT_FOUND"
