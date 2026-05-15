import subprocess

from fastapi.testclient import TestClient

from app.config import (
    get_settings,
    get_yt_dlp_auth_args,
    get_yt_dlp_js_runtime_args,
    get_yt_dlp_remote_components,
    get_yt_dlp_youtube_extractor_args,
)
from app.main import app
from app.services.yt_dlp_service import (
    _video_info_cache_path,
    VideoChapter,
    VideoInspectError,
    VideoMetadata,
    YtDlpNotInstalledError,
    inspect_video_metadata,
)
from app.services.translation_service import (
    TranslationConfigurationError,
    TranslationProviderError,
)


client = TestClient(app)


def _assert_error_response(
    response,
    *,
    status_code: int,
    error_code: str,
    retryable: bool,
    detail: str,
) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail", "error_code", "retryable", "request_id"}
    assert body["detail"] == detail
    assert body["error_code"] == error_code
    assert body["retryable"] is retryable
    assert body["request_id"] == response.headers["x-request-id"]


def test_inspect_video_metadata_extracts_fields(monkeypatch) -> None:
    captured_command: list[str] = []

    def fake_run(*args, **kwargs):
        captured_command.extend(args[0])
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                '{"id":"abc123xyz","title":"Demo title","duration":321,'
                '"uploader":"Demo channel","thumbnail":"https://example.com/t.jpg",'
                '"description":"Demo description","channel":"Demo channel",'
                '"channel_id":"demo-channel-id","uploader_id":"@demo",'
                '"tags":["ai","kernels"],"categories":["Education"],'
                '"chapters":[{"start_time":0,"end_time":12.5,"title":"Intro"}],'
                '"subtitles":{"en":[{}],"en-US":[{}]},'
                '"automatic_captions":{"en":[{}]}}'
            ),
            stderr="",
        )

    monkeypatch.setattr("app.services.yt_dlp_service.subprocess.run", fake_run)

    metadata = inspect_video_metadata("https://www.youtube.com/watch?v=abc123xyz")

    assert "--cookies-from-browser" not in captured_command
    assert "--extractor-args" not in captured_command
    assert metadata == VideoMetadata(
        video_id="abc123xyz",
        title="Demo title",
        duration_sec=321,
        uploader="Demo channel",
        uploader_id="@demo",
        channel="Demo channel",
        channel_id="demo-channel-id",
        thumbnail="https://example.com/t.jpg",
        description="Demo description",
        tags=["ai", "kernels"],
        categories=["Education"],
        chapters=[VideoChapter(start_time=0.0, end_time=12.5, title="Intro")],
        subtitles=["en", "en-US"],
        automatic_captions=["en"],
    )


def test_inspect_video_metadata_uses_player_client_extractor_args(monkeypatch) -> None:
    captured_command: list[str] = []
    monkeypatch.setenv("YTDLP_YOUTUBE_PLAYER_CLIENTS", "web,mweb")
    monkeypatch.setattr("app.services.yt_dlp_service._load_cached_video_info", lambda _url: None)
    monkeypatch.setattr("app.services.yt_dlp_service._store_cached_video_info", lambda *args, **kwargs: None)

    def fake_run(*args, **kwargs):
        captured_command.extend(args[0])
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"id":"abc123xyz","title":"Demo title"}',
            stderr="",
        )

    monkeypatch.setattr("app.services.yt_dlp_service.subprocess.run", fake_run)

    inspect_video_metadata("https://www.youtube.com/watch?v=abc123xyz")

    assert "--extractor-args" in captured_command
    assert captured_command[captured_command.index("--extractor-args") + 1] == (
        "youtube:player-client=web,mweb"
    )


def test_inspect_video_metadata_uses_cache_when_fresh(monkeypatch) -> None:
    url = "https://www.youtube.com/watch?v=abc123xyz"
    cache_path = _video_info_cache_path(url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        '{"id":"abc123xyz","title":"Cached title"}',
        encoding="utf-8",
    )

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called when cache is fresh")

    monkeypatch.setattr("app.services.yt_dlp_service.subprocess.run", fail_run)

    metadata = inspect_video_metadata(url)

    assert metadata.video_id == "abc123xyz"
    assert metadata.title == "Cached title"
    cache_path.unlink(missing_ok=True)


def test_inspect_video_metadata_reports_missing_yt_dlp(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="No module named yt_dlp",
        )

    monkeypatch.setattr("app.services.yt_dlp_service.subprocess.run", fake_run)

    try:
        inspect_video_metadata("https://www.youtube.com/watch?v=abc123xyz")
    except YtDlpNotInstalledError as error:
        assert "yt-dlp is not installed" in str(error)
    else:
        raise AssertionError("Expected YtDlpNotInstalledError")


def test_inspect_video_metadata_normalizes_cookie_database_failure(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="ERROR: Could not copy Chrome cookie database. See https://example.com",
        )

    monkeypatch.setattr("app.services.yt_dlp_service.subprocess.run", fake_run)

    try:
        inspect_video_metadata("https://www.youtube.com/watch?v=abc123xyz")
    except VideoInspectError as error:
        assert str(error) == (
            "yt-dlp could not read Chrome cookies. Close all Chrome processes first, "
            "or export a cookies.txt file and set YTDLP_COOKIES_FILE in .env."
        )
    else:
        raise AssertionError("Expected VideoInspectError")


def test_inspect_video_metadata_rejects_unexpected_payload(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="null",
            stderr="",
        )

    monkeypatch.setattr("app.services.yt_dlp_service.subprocess.run", fake_run)

    try:
        inspect_video_metadata("https://www.youtube.com/watch?v=abc123xyz")
    except VideoInspectError as error:
        assert "unexpected metadata payload" in str(error)
    else:
        raise AssertionError("Expected VideoInspectError")


def test_get_yt_dlp_auth_args_prefers_cookie_file(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text("cookie", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(cookie_file))
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")

    assert get_yt_dlp_auth_args() == ["--cookies", str(cookie_file)]


def test_get_yt_dlp_auth_args_resolves_relative_cookie_file(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("cookie", encoding="utf-8")
    monkeypatch.setattr("app.config.ROOT_DIR", tmp_path)
    monkeypatch.setenv("YTDLP_COOKIES_FILE", "cookies.txt")

    assert get_yt_dlp_auth_args() == ["--cookies", str(cookie_file)]


def test_get_yt_dlp_auth_args_ignores_missing_cookie_file(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr("app.config.ROOT_DIR", tmp_path)
    monkeypatch.setenv("YTDLP_COOKIES_FILE", "missing-cookies.txt")
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")

    assert get_yt_dlp_auth_args() == ["--cookies-from-browser", "edge"]


def test_get_yt_dlp_auth_args_supports_browser_cookies(monkeypatch) -> None:
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")

    assert get_yt_dlp_auth_args() == ["--cookies-from-browser", "edge"]


def test_get_yt_dlp_js_runtime_args_falls_back_to_node_when_configured_runtime_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "YTDLP_JS_RUNTIMES",
        "deno:C:/missing/deno.exe",
    )

    def fake_which(name: str) -> str | None:
        if name == "node":
            return "C:/tools/node.exe"
        return None

    monkeypatch.setattr("app.config.shutil.which", fake_which)

    assert get_yt_dlp_js_runtime_args() == ["--js-runtimes", "node"]


def test_get_yt_dlp_remote_components_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("YTDLP_REMOTE_COMPONENTS", raising=False)

    assert get_yt_dlp_remote_components() == []


def test_get_yt_dlp_remote_components_uses_env_value(monkeypatch) -> None:
    monkeypatch.setenv("YTDLP_REMOTE_COMPONENTS", "ejs:github")

    assert get_yt_dlp_remote_components() == [
        "--remote-components",
        "ejs:github",
    ]


def test_get_yt_dlp_youtube_extractor_args_uses_env_value(monkeypatch) -> None:
    monkeypatch.setenv("YTDLP_YOUTUBE_PLAYER_CLIENTS", "web,mweb")

    assert get_yt_dlp_youtube_extractor_args() == [
        "--extractor-args",
        "youtube:player-client=web,mweb",
    ]


def test_inspect_video_endpoint_returns_metadata(monkeypatch) -> None:
    def fake_inspect(url: str) -> VideoMetadata:
        assert url == "https://www.youtube.com/watch?v=abc123xyz"
        return VideoMetadata(
            video_id="abc123xyz",
            title="Demo title",
            duration_sec=321,
            uploader="Demo channel",
            uploader_id="@demo",
            channel="Demo channel",
            channel_id="demo-channel-id",
            thumbnail="https://example.com/t.jpg",
            description="Demo description",
            tags=["ai", "kernels"],
            categories=["Education"],
            chapters=[VideoChapter(start_time=0.0, end_time=12.5, title="Intro")],
            subtitles=["en", "en-US"],
            automatic_captions=["en"],
        )

    monkeypatch.setattr("app.main.inspect_video_metadata", fake_inspect)

    response = client.post(
        "/api/video/inspect",
        json={"url": "https://youtu.be/abc123xyz?t=12"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "video_id": "abc123xyz",
        "title": "Demo title",
        "duration_sec": 321,
        "uploader": "Demo channel",
        "uploader_id": "@demo",
        "channel": "Demo channel",
        "channel_id": "demo-channel-id",
        "thumbnail": "https://example.com/t.jpg",
        "description": "Demo description",
        "tags": ["ai", "kernels"],
        "categories": ["Education"],
        "chapters": [
            {
                "start_time": 0.0,
                "end_time": 12.5,
                "title": "Intro",
            }
        ],
        "subtitles": ["en", "en-US"],
        "automatic_captions": ["en"],
    }


def test_inspect_video_endpoint_returns_install_error(monkeypatch) -> None:
    def fake_inspect(url: str) -> VideoMetadata:
        raise YtDlpNotInstalledError(
            "yt-dlp is not installed. Install it with `python -m pip install yt-dlp`."
        )

    monkeypatch.setattr("app.main.inspect_video_metadata", fake_inspect)

    response = client.post(
        "/api/video/inspect",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )

    _assert_error_response(
        response,
        status_code=500,
        error_code="YTDLP_NOT_INSTALLED",
        retryable=False,
        detail="yt-dlp is not installed. Install it with `python -m pip install yt-dlp`.",
    )


def test_inspect_video_endpoint_returns_yt_dlp_failure(monkeypatch) -> None:
    def fake_inspect(url: str) -> VideoMetadata:
        raise VideoInspectError("Video unavailable")

    monkeypatch.setattr("app.main.inspect_video_metadata", fake_inspect)

    response = client.post(
        "/api/video/inspect",
        json={"url": "https://www.youtube.com/watch?v=abc123xyz"},
    )

    _assert_error_response(
        response,
        status_code=502,
        error_code="VIDEO_UNAVAILABLE",
        retryable=True,
        detail="Failed to inspect video metadata: Video unavailable",
    )


def test_provider_models_returns_configuration_error(monkeypatch) -> None:
    def fail_discover(**kwargs):
        raise TranslationConfigurationError("Missing provider config")

    monkeypatch.setattr("app.main.discover_provider_models", fail_discover)

    response = client.post(
        "/api/provider-models",
        json={"provider": "openai"},
    )

    _assert_error_response(
        response,
        status_code=500,
        error_code="CONFIGURATION_ERROR",
        retryable=False,
        detail="Missing provider config",
    )


def test_provider_models_returns_provider_error(monkeypatch) -> None:
    def fail_discover(**kwargs):
        raise TranslationProviderError("Upstream provider failed")

    monkeypatch.setattr("app.main.discover_provider_models", fail_discover)

    response = client.post(
        "/api/provider-models",
        json={"provider": "openai"},
    )

    _assert_error_response(
        response,
        status_code=502,
        error_code="UPSTREAM_ERROR",
        retryable=True,
        detail="Upstream provider failed",
    )
