from app.api.error_mapping import classify_service_error
from app.services.audio_download_service import AudioDownloadTimeoutError
from app.services.yt_dlp_service import VideoInspectError, YtDlpNotInstalledError


def test_classify_service_error_detects_youtube_url_invalid() -> None:
    classification = classify_service_error(
        ValueError("URL must be a valid YouTube link.")
    )

    assert classification.error_code == "YOUTUBE_URL_INVALID"
    assert classification.retryable is False


def test_classify_service_error_detects_cookie_stale() -> None:
    classification = classify_service_error(
        VideoInspectError(
            "YouTube cookies are stale or no longer bound to the current session."
        )
    )

    assert classification.error_code == "COOKIE_STALE"
    assert classification.retryable is True


def test_classify_service_error_detects_youtube_bot_check() -> None:
    classification = classify_service_error(
        VideoInspectError("Sign in to confirm you're not a bot.")
    )

    assert classification.error_code == "YOUTUBE_BOT_CHECK"
    assert classification.retryable is True


def test_classify_service_error_detects_po_token_required() -> None:
    classification = classify_service_error(
        VideoInspectError(
            "ERROR: [youtube] 403 Forbidden: this client requires a PO Token"
        )
    )

    assert classification.error_code == "PO_TOKEN_REQUIRED"
    assert classification.retryable is True


def test_classify_service_error_detects_timeout() -> None:
    classification = classify_service_error(
        AudioDownloadTimeoutError("yt-dlp audio download timed out after 30s.")
    )

    assert classification.error_code == "YTDLP_TIMEOUT"
    assert classification.retryable is True


def test_classify_service_error_detects_missing_ytdlp() -> None:
    classification = classify_service_error(
        YtDlpNotInstalledError("yt-dlp is not installed.")
    )

    assert classification.error_code == "YTDLP_NOT_INSTALLED"
    assert classification.retryable is False
