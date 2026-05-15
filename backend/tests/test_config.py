import pytest

from app.config import get_settings


def test_get_settings_parses_cors_allowed_origins(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com, http://localhost:3000 , https://app.example.com")

    settings = get_settings()

    assert settings.cors_allowed_origins == (
        "https://app.example.com",
        "http://localhost:3000",
    )
    assert settings.deployment_profile == "development"


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
    assert str(settings.account_quota_db_path) == "/tmp/account-quota.sqlite"


def test_get_settings_requires_api_token_in_production(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "production")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="API_AUTH_TOKEN must be set"):
        get_settings()
