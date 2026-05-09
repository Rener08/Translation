from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_provider_test_connection_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.main.discover_provider_models",
        lambda **kwargs: ["deepseek-chat", "deepseek-reasoner"],
    )

    response = client.post(
        "/api/provider/test-connection",
        json={"provider": "deepseek"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["reachable"] is True
    assert body["selected_model"] == "deepseek-chat"
    assert body["discovered_models"] == ["deepseek-chat", "deepseek-reasoner"]


def test_export_logs_endpoint_returns_archive_path() -> None:
    response = client.get("/api/system/export-logs")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    archive_path = Path(body["archive_path"])
    assert archive_path.exists()
    assert archive_path.suffix == ".zip"


def test_readyz_endpoint() -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
