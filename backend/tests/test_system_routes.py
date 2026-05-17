from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient

from app.api.routers.system import PreflightCheck
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


def test_preflight_endpoint_reports_runtime_and_provider_readiness(monkeypatch) -> None:
    def make_check(name: str, label: str, ok: bool, detail: str) -> PreflightCheck:
        return PreflightCheck(name=name, label=label, ok=ok, detail=detail)

    monkeypatch.setattr(
        "app.api.routers.system._check_job_queue_db",
        lambda: make_check("job_queue_db", "job_queue_db", True, "job queue ok"),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_yaml_available",
        lambda: make_check("yaml_available", "YAML", True, "yaml ok"),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_yt_dlp",
        lambda: make_check("yt_dlp", "yt-dlp 安装", True, "yt-dlp ok"),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_js_runtime",
        lambda: make_check("js_runtime", "JS Runtime", True, "node ok"),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_ffmpeg",
        lambda: make_check("ffmpeg", "ffmpeg 安装", True, "ffmpeg ok"),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_tmp_dir",
        lambda: make_check("tmp_writable", "tmp 目录可写", True, "tmp ok"),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_yt_cookies",
        lambda: make_check("yt_cookies", "YouTube Cookies", True, "cookies ok"),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_translation_provider",
        lambda: make_check(
            "translation_provider",
            "翻译 provider",
            True,
            "openai · gpt-4.1-mini 可用",
        ),
    )
    monkeypatch.setattr(
        "app.api.routers.system._check_rewrite_provider",
        lambda: make_check(
            "rewrite_provider",
            "写作 provider",
            False,
            "ollama 检查失败: 无法访问 http://127.0.0.1:11434/api/tags",
        ),
    )

    response = client.get("/api/system/preflight")

    assert response.status_code == 200
    body = response.json()
    assert body["all_ok"] is False
    assert [check["name"] for check in body["checks"]] == [
        "job_queue_db",
        "yaml_available",
        "yt_dlp",
        "js_runtime",
        "ffmpeg",
        "tmp_writable",
        "yt_cookies",
        "translation_provider",
        "rewrite_provider",
    ]
    provider_checks = {check["name"]: check for check in body["checks"]}
    assert provider_checks["translation_provider"]["ok"] is True
    assert provider_checks["rewrite_provider"]["ok"] is False
    assert "无法访问" in provider_checks["rewrite_provider"]["detail"]


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
    assert body["probe_url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert body["target_url"] == "https://www.youtube.com/watch?v=abc123xyz"
    assert body["normalized_url"] == "https://www.youtube.com/watch?v=abc123xyz"
    assert body["video_id"] == "abc123xyz"
    assert body["title"] == "Demo title"
    assert body["source_strategy"] == "audio"
    assert body["cookies_configured"] is True
    assert body["cookies_file_exists"] is True
    assert body["cookies_active_for_yt_dlp"] is True
    assert body["cookie_mode"] == "cookies_file"
    assert body["error_code"] == "YOUTUBE_BOT_CHECK"
    assert body["retryable"] is True
    assert body["message"] == "YouTube 要求登录或人机验证。"
    assert body["recommended_action"] == "请更新 cookies.txt；如果仍失败，建议改走本地音频上传。"
    assert body["subtitles"] == []
    assert body["automatic_captions"] == []
    assert body["checks"]["public_probe_inspect"] == "ok"
    assert body["checks"]["target_inspect"] == "ok"
    assert body["checks"]["target_captions"] == "missing"
    assert body["checks"]["target_audio_probe"] == "failed"


def test_youtube_access_status_endpoint_normalizes_blank_url(monkeypatch) -> None:
    seen_urls: list[str | None] = []

    def fake_inspect(url):
        seen_urls.append(url)
        return YouTubeAccessStatusResult(
            ok=True,
            runtime_ok=True,
            target_ok=True,
            probe_url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
            target_url=url,
            source_strategy="unknown",
            cookies_configured=False,
            cookies_file_exists=False,
            cookies_active_for_yt_dlp=False,
            cookie_mode="none",
            message="当前环境可访问 YouTube 元数据接口。",
            recommended_action="",
            subtitles=[],
            automatic_captions=[],
            checks={"public_probe_inspect": "ok"},
        )

    monkeypatch.setattr("app.api.routers.system.inspect_youtube_access", fake_inspect)

    response = client.post(
        "/api/system/youtube-access-status",
        json={"url": "   "},
    )

    assert response.status_code == 200
    assert seen_urls == [None]
    body = response.json()
    assert body["ok"] is True
    assert "target_url" not in body
    assert body["runtime_ok"] is True
    assert body["target_ok"] is True
