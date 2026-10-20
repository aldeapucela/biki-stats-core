from fastapi.testclient import TestClient

from movilidad.api.main import app
from movilidad.core.config import get_settings


def _client(monkeypatch, token: str | None) -> TestClient:
    if token is None:
        monkeypatch.delenv("MOVILIDAD_COLLECTOR_TOKEN", raising=False)
    else:
        monkeypatch.setenv("MOVILIDAD_COLLECTOR_TOKEN", token)
    get_settings.cache_clear()
    return TestClient(app)


def test_collector_requires_token(monkeypatch) -> None:
    with _client(monkeypatch, "secret") as client:
        missing = client.post("/api/v1/ops/collector/run")
        invalid = client.post(
            "/api/v1/ops/collector/run", headers={"Authorization": "Bearer wrong"}
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    get_settings.cache_clear()


def test_collector_is_disabled_without_token(monkeypatch) -> None:
    with _client(monkeypatch, None) as client:
        response = client.post("/api/v1/ops/collector/run")

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "COLLECTOR_NOT_CONFIGURED"
    get_settings.cache_clear()


def test_collector_runs_with_valid_token(monkeypatch) -> None:
    monkeypatch.setattr("movilidad.api.routers.collector.run_capture", lambda: "capture-123")
    with _client(monkeypatch, "secret") as client:
        response = client.post(
            "/api/v1/ops/collector/run", headers={"Authorization": "Bearer secret"}
        )

    assert response.status_code == 200
    assert response.json()["data"] == {"capture_id": "capture-123"}
    get_settings.cache_clear()


def test_collector_uses_bearer_without_origin_requirement(monkeypatch) -> None:
    monkeypatch.setattr("movilidad.api.routers.collector.run_capture", lambda: "capture-123")
    with _client(monkeypatch, "secret") as client:
        response = client.post(
            "/api/v1/ops/collector/run",
            headers={
                "Authorization": "Bearer secret",
                "Origin": "https://otro-origen.example",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"] == {"capture_id": "capture-123"}
    get_settings.cache_clear()


def test_collector_reports_concurrent_capture(monkeypatch) -> None:
    monkeypatch.setattr("movilidad.api.routers.collector.run_capture", lambda: "skipped")
    with _client(monkeypatch, "secret") as client:
        response = client.post(
            "/api/v1/ops/collector/run", headers={"Authorization": "Bearer secret"}
        )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "CAPTURE_IN_PROGRESS"
    get_settings.cache_clear()


def test_collector_endpoint_is_hidden_from_openapi(monkeypatch) -> None:
    with _client(monkeypatch, "secret") as client:
        schema = client.get("/openapi.json").json()

    assert "/api/v1/ops/collector/run" not in schema["paths"]
    get_settings.cache_clear()
