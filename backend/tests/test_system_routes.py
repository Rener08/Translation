from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.services.youtube_access_service import YouTubeAccessStatusResult


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


def test_yt_dlp_cookies_endpoint_returns_missing_snapshot(monkeypatch) -> None:
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)
    monkeypatch.delenv("YTDLP_COOKIE_HEADER", raising=False)

    response = client.get("/api/system/yt-dlp-cookies")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["mode"] == "none"
    assert body["configured"] is False
    assert body["active_for_yt_dlp"] is False
    assert body["exists"] is False
    assert body["cookies_text"] == ""
    assert body["cookies_file"] == ""


def test_yt_dlp_cookies_endpoint_saves_and_clears(monkeypatch, tmp_path) -> None:
    cookies_path = tmp_path / "youtube-cookies.txt"
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(cookies_path))

    save_response = client.put(
        "/api/system/yt-dlp-cookies",
        json={"cookies_text": "a\tb\t/\tTRUE\t123\tSID\tcookie-value"},
    )
    assert save_response.status_code == 200
    save_body = save_response.json()
    assert save_body["ok"] is True
    assert save_body["mode"] == "cookies_file"
    assert save_body["configured"] is True
    assert save_body["active_for_yt_dlp"] is True
    assert save_body["exists"] is True
    assert cookies_path.exists()
    assert cookies_path.read_text(encoding="utf-8") == "a\tb\t/\tTRUE\t123\tSID\tcookie-value"

    read_response = client.get("/api/system/yt-dlp-cookies")
    assert read_response.status_code == 200
    read_body = read_response.json()
    assert read_body["mode"] == "cookies_file"
    assert read_body["configured"] is True
    assert read_body["exists"] is True
    assert read_body["cookies_text"] == "a\tb\t/\tTRUE\t123\tSID\tcookie-value"

    clear_response = client.delete("/api/system/yt-dlp-cookies")
    assert clear_response.status_code == 200
    clear_body = clear_response.json()
    assert clear_body["ok"] is True
    assert clear_body["mode"] == "cookies_file"
    assert clear_body["exists"] is False
    assert clear_body["cookies_text"] == ""
    assert not cookies_path.exists()


def test_readyz_endpoint() -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["tmp_writable"] == "ok"
    assert body["checks"]["job_queue_db"] == "ok"
    assert body["checks"]["yaml_available"] == "ok"
    assert body["checks"]["yt_dlp_cookies"] in {"unconfigured", "browser", "cookie_header", "ok"}


def test_livez_endpoint() -> None:
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_youtube_access_status_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routers.system.inspect_youtube_access",
        lambda url: YouTubeAccessStatusResult(
            ok=False,
            runtime_ok=True,
            target_ok=False,
            probe_url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
            target_url=url,
            normalized_url="https://www.youtube.com/watch?v=abc123xyz",
            video_id="abc123xyz",
            title="Demo title",
            source_strategy="audio",
            cookies_configured=True,
            cookies_file_exists=True,
            cookies_active_for_yt_dlp=True,
            cookie_mode="cookies_file",
            error_code="YOUTUBE_BOT_CHECK",
            retryable=True,
            message="YouTube 要求登录或人机验证。",
            recommended_action="请更新 cookies.txt；如果仍失败，建议改走本地音频上传。",
            subtitles=[],
            automatic_captions=[],
            checks={
                "public_probe_inspect": "ok",
                "target_inspect": "ok",
                "target_captions": "missing",
                "target_audio_probe": "failed",
            },
        ),
    )

    response = client.post(
        "/api/system/youtube-access-status",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["runtime_ok"] is True
    assert body["target_ok"] is False
    assert body["error_code"] == "YOUTUBE_BOT_CHECK"
    assert body["checks"]["target_audio_probe"] == "failed"
