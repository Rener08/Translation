import pytest

from pathlib import Path

from app.config import (
    get_settings,
    get_yt_dlp_auth_args,
    get_yt_dlp_youtube_extractor_args,
    resolve_yt_dlp_cookie_config,
)


def test_get_settings_parses_cors_allowed_origins(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com, http://localhost:3000 , https://app.example.com")

    settings = get_settings()

    assert settings.cors_allowed_origins == (
        "https://app.example.com",
        "http://localhost:3000",
    )
    assert settings.deployment_profile == "development"
    assert settings.trust_account_headers is True


def test_get_settings_parses_processing_limits(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_VIDEO_DURATION_SEC", "1800")
    monkeypatch.setenv("MAX_AUDIO_BYTES", "123456")
    monkeypatch.setenv("MAX_TRANSCRIPT_CHARS", "654321")
    monkeypatch.setenv("MAX_TRANSLATION_SEGMENTS", "789")
    monkeypatch.setenv("YTDLP_SUBPROCESS_TIMEOUT_SEC", "42")
    monkeypatch.setenv("ACCOUNT_DAILY_REQUEST_LIMIT", "7")
    monkeypatch.setenv("ACCOUNT_MAX_CONCURRENT_JOBS", "3")
    monkeypatch.setenv("ACCOUNT_MAX_HISTORY_SESSIONS", "11")
    monkeypatch.setenv("ACCOUNT_QUOTA_DB_PATH", "/tmp/account-quota.sqlite")

    settings = get_settings()

    assert settings.max_video_duration_sec == 1800
    assert settings.max_audio_bytes == 123456
    assert settings.max_transcript_chars == 654321
    assert settings.max_translation_segments == 789
    assert settings.yt_dlp_timeout_sec == 42
    assert settings.account_daily_request_limit == 7
    assert settings.account_max_concurrent_jobs == 3
    assert settings.account_max_history_sessions == 11
    assert str(settings.account_quota_db_path).replace("\\", "/") == Path(
        "/tmp/account-quota.sqlite"
    ).as_posix()
    assert settings.trust_account_headers is True


def test_get_settings_disables_trusted_account_headers_in_production_by_default(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "demo-token")

    settings = get_settings()

    assert settings.deployment_profile == "production"
    assert settings.trust_account_headers is False


def test_get_settings_requires_api_token_in_production(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="API_AUTH_TOKEN must be set"):
        get_settings()


def test_resolve_yt_dlp_cookie_config_uses_absolute_cookie_file(monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()
    cookie_file = tmp_path / "youtube-cookies.txt"
    cookie_file.write_text("cookie", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(cookie_file))

    config = resolve_yt_dlp_cookie_config()

    assert config.mode == "cookies_file"
    assert config.configured is True
    assert config.active_for_yt_dlp is True
    assert config.effective_path == cookie_file
    assert get_yt_dlp_auth_args() == ["--cookies", str(cookie_file)]


def test_resolve_yt_dlp_cookie_config_falls_back_to_browser_when_file_missing(
    monkeypatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("YTDLP_COOKIES_FILE", "missing-cookies.txt")
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")

    config = resolve_yt_dlp_cookie_config()

    assert config.mode == "browser"
    assert config.configured is True
    assert config.active_for_yt_dlp is True
    assert config.effective_path is None
    assert get_yt_dlp_auth_args() == ["--cookies-from-browser", "edge"]


def test_resolve_yt_dlp_cookie_config_reports_missing_file_path(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("YTDLP_COOKIES_FILE", "missing-cookies.txt")

    config = resolve_yt_dlp_cookie_config()

    assert config.mode == "cookies_file"
    assert config.configured is True
    assert config.active_for_yt_dlp is False
    assert config.effective_path is not None
    assert config.effective_path.as_posix().endswith("missing-cookies.txt")
    assert get_yt_dlp_auth_args() == []


def test_get_yt_dlp_youtube_extractor_args_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("YTDLP_YOUTUBE_PLAYER_CLIENTS", raising=False)

    assert get_yt_dlp_youtube_extractor_args() == []


def test_get_yt_dlp_youtube_extractor_args_uses_env_value(monkeypatch) -> None:
    monkeypatch.setenv("YTDLP_YOUTUBE_PLAYER_CLIENTS", "android, ios ,android")

    assert get_yt_dlp_youtube_extractor_args() == [
        "--extractor-args",
        "youtube:player-client=android,ios",
    ]
