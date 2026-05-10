from pathlib import Path
from types import SimpleNamespace
import zipfile

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


def test_export_logs_excludes_desktop_log(monkeypatch, tmp_path) -> None:
    backend_log = tmp_path / "backend_run.log"
    frontend_log = tmp_path / "frontend_run.log"
    desktop_log = tmp_path / "desktop_crash.log"
    backend_log.write_text("backend", encoding="utf-8")
    frontend_log.write_text("frontend", encoding="utf-8")
    desktop_log.write_text("desktop", encoding="utf-8")

    monkeypatch.setattr(
        "app.api.routers.system.get_settings",
        lambda: SimpleNamespace(
            backend_log_file=backend_log,
            frontend_log_file=frontend_log,
            desktop_log_file=desktop_log,
        ),
    )

    response = client.get("/api/system/export-logs")
    assert response.status_code == 200
    body = response.json()
    archive_path = Path(body["archive_path"])
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path) as zf:
        assert sorted(zf.namelist()) == ["backend_run.log", "frontend_run.log"]


def test_readyz_endpoint() -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["tmp_writable"] == "ok"
    assert body["checks"]["job_queue_db"] == "ok"


def test_livez_endpoint() -> None:
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
