from fastapi.testclient import TestClient

from movilidad.api.main import app
from movilidad.core.config import get_settings


def test_health_exposes_request_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIKI_DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    get_settings.cache_clear()
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["data"]["database"] == "ok"
    assert response.headers["x-request-id"]
