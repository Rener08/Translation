from types import SimpleNamespace

from app.config import YtDlpCookieConfig
from app.services.caption_service import CaptionResult
from app.services.youtube_access_service import inspect_youtube_access


def _cookie_config() -> YtDlpCookieConfig:
    return YtDlpCookieConfig(
        mode="cookies_file",
        configured=True,
        active_for_yt_dlp=True,
        effective_path=None,
        requested_path=None,
    )


def test_inspect_youtube_access_runtime_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.youtube_access_service.resolve_yt_dlp_cookie_config",
        _cookie_config,
    )
    monkeypatch.setattr(
        "app.services.youtube_access_service.extract_video_info",
        lambda url: {"id": "probe", "title": "Probe"},
    )

    result = inspect_youtube_access()

    assert result.ok is True
    assert result.runtime_ok is True
    assert result.target_ok is True
    assert result.checks["public_probe_inspect"] == "ok"


def test_inspect_youtube_access_prefers_captions(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.youtube_access_service.resolve_yt_dlp_cookie_config",
        _cookie_config,
    )
    monkeypatch.setattr(
        "app.services.youtube_access_service.extract_video_info",
        lambda url: {
            "id": "abc123xyz",
            "title": "Demo title",
            "subtitles": {"en": [{"ext": "json3", "url": "https://example.com/en"}]},
            "automatic_captions": {},
        },
    )
    monkeypatch.setattr(
        "app.services.youtube_access_service.fetch_best_english_captions",
        lambda video_info: CaptionResult(language="en", text="hello world"),
    )

    result = inspect_youtube_access("https://www.youtube.com/watch?v=abc123xyz")

    assert result.ok is True
    assert result.target_ok is True
    assert result.source_strategy == "captions"
    assert result.checks["target_captions"] == "ok"
    assert result.checks["target_audio_probe"] == "skipped"


def test_inspect_youtube_access_surfaces_audio_probe_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.youtube_access_service.resolve_yt_dlp_cookie_config",
        _cookie_config,
    )
    monkeypatch.setattr(
        "app.services.youtube_access_service.extract_video_info",
        lambda url: {
            "id": "abc123xyz",
            "title": "Demo title",
            "subtitles": {},
            "automatic_captions": {},
        },
    )
    monkeypatch.setattr(
        "app.services.youtube_access_service.fetch_best_english_captions",
        lambda video_info: None,
    )

    def _fail_download(url: str, target_dir=None):
        raise RuntimeError("Sign in to confirm you're not a bot.")

    monkeypatch.setattr(
        "app.services.youtube_access_service.download_audio",
        _fail_download,
    )

    result = inspect_youtube_access("https://www.youtube.com/watch?v=abc123xyz")

    assert result.ok is False
    assert result.target_ok is False
    assert result.error_code == "YOUTUBE_BOT_CHECK"
    assert result.checks["target_audio_probe"] == "failed"
