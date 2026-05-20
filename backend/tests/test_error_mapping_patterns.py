"""
Unit tests for yt-dlp string pattern matching in classify_service_error.

Each test constructs an Exception with the exact pattern string and asserts
the expected error_code. If yt-dlp changes its error messages, these tests
will catch the regression before it silently breaks error classification.
"""

import pytest
from app.api.error_mapping import classify_service_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exc(msg: str) -> Exception:
    """Plain Exception — bypasses all isinstance checks, hits string matching."""
    return Exception(msg)


# ---------------------------------------------------------------------------
# Pattern: VIDEO_UNAVAILABLE
# ---------------------------------------------------------------------------

def test_video_unavailable_maps_to_video_unavailable() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] abc123: Video unavailable"))
    assert c.error_code == "VIDEO_UNAVAILABLE"
    assert c.status_code == 502
    assert c.retryable is True


# ---------------------------------------------------------------------------
# Pattern: VIDEO_PRIVATE
# ---------------------------------------------------------------------------

def test_private_video_maps_to_video_private() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] abc123: This is a private video"))
    assert c.error_code == "VIDEO_PRIVATE"
    assert c.status_code == 502
    assert c.retryable is False


# ---------------------------------------------------------------------------
# Pattern: VIDEO_REGION_BLOCKED (three variants)
# ---------------------------------------------------------------------------

def test_not_available_in_your_country_maps_to_region_blocked() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] abc123: This video is not available in your country"))
    assert c.error_code == "VIDEO_REGION_BLOCKED"
    assert c.retryable is False


def test_not_available_in_your_region_maps_to_region_blocked() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] abc123: This video is not available in your region"))
    assert c.error_code == "VIDEO_REGION_BLOCKED"
    assert c.retryable is False


def test_geo_restricted_maps_to_region_blocked() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] abc123: This video is geo-restricted"))
    assert c.error_code == "VIDEO_REGION_BLOCKED"
    assert c.retryable is False


# ---------------------------------------------------------------------------
# Pattern: YOUTUBE_429 (two variants)
# ---------------------------------------------------------------------------

def test_http_429_in_message_maps_to_youtube_429() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] HTTP Error 429: Too Many Requests"))
    assert c.error_code == "YOUTUBE_429"
    assert c.status_code == 502
    assert c.retryable is True


def test_too_many_requests_maps_to_youtube_429() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] Too many requests, please try again later"))
    assert c.error_code == "YOUTUBE_429"
    assert c.retryable is True


# ---------------------------------------------------------------------------
# Pattern: PO_TOKEN_REQUIRED
# ---------------------------------------------------------------------------

def test_po_token_required_maps_to_po_token_required() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] 403 Forbidden: this client requires a PO Token")
    )
    assert c.error_code == "PO_TOKEN_REQUIRED"
    assert c.status_code == 502
    assert c.retryable is True


def test_po_token_provider_none_debug_output_maps_to_po_token_required() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] [pot] PO Token Providers: none")
    )
    assert c.error_code == "PO_TOKEN_REQUIRED"
    assert c.retryable is True


# ---------------------------------------------------------------------------
# Pattern: COOKIE_STALE (two variants)
# ---------------------------------------------------------------------------

def test_provided_youtube_account_cookies_no_longer_valid_maps_to_cookie_stale() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] Provided YouTube account cookies are no longer valid")
    )
    assert c.error_code == "COOKIE_STALE"
    assert c.status_code == 502
    assert c.retryable is True


def test_cookies_are_stale_or_no_longer_bound_maps_to_cookie_stale() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] cookies are stale or no longer bound to the current session")
    )
    assert c.error_code == "COOKIE_STALE"
    assert c.retryable is True


# ---------------------------------------------------------------------------
# Pattern: BROWSER_COOKIE_LOCKED
# ---------------------------------------------------------------------------

def test_could_not_copy_chrome_cookie_database_maps_to_browser_cookie_locked() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] Could not copy Chrome cookie database")
    )
    assert c.error_code == "BROWSER_COOKIE_LOCKED"
    assert c.status_code == 502
    assert c.retryable is True


# ---------------------------------------------------------------------------
# Pattern: COOKIE_DECRYPT_FAILED
# ---------------------------------------------------------------------------

def test_failed_to_decrypt_with_dpapi_maps_to_cookie_decrypt_failed() -> None:
    c = classify_service_error(_exc("ERROR: [youtube] Failed to decrypt with DPAPI"))
    assert c.error_code == "COOKIE_DECRYPT_FAILED"
    assert c.status_code == 502
    assert c.retryable is False


# ---------------------------------------------------------------------------
# Pattern: YOUTUBE_BOT_CHECK
# ---------------------------------------------------------------------------

def test_sign_in_to_confirm_not_a_bot_maps_to_youtube_bot_check() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] Sign in to confirm you're not a bot")
    )
    assert c.error_code == "YOUTUBE_BOT_CHECK"
    assert c.status_code == 502
    assert c.retryable is True


# ---------------------------------------------------------------------------
# Pattern: COOKIE_REQUIRED (two variants)
# ---------------------------------------------------------------------------

def test_use_cookies_from_browser_flag_maps_to_cookie_required() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] Use --cookies-from-browser or --cookies to provide authentication")
    )
    assert c.error_code == "COOKIE_REQUIRED"
    assert c.status_code == 502
    assert c.retryable is True


def test_signed_in_browser_session_maps_to_cookie_required() -> None:
    c = classify_service_error(
        _exc("ERROR: [youtube] This video requires a signed-in browser session")
    )
    assert c.error_code == "COOKIE_REQUIRED"
    assert c.retryable is True


# ---------------------------------------------------------------------------
# Pattern: YTDLP_TIMEOUT (string-based, requires both substrings)
# ---------------------------------------------------------------------------

def test_timed_out_after_with_ytdlp_maps_to_ytdlp_timeout() -> None:
    c = classify_service_error(_exc("yt-dlp timed out after 30 seconds"))
    assert c.error_code == "YTDLP_TIMEOUT"
    assert c.status_code == 502
    assert c.retryable is True


def test_timed_out_after_without_ytdlp_does_not_map_to_ytdlp_timeout() -> None:
    """Both substrings required — missing 'yt-dlp' must not trigger YTDLP_TIMEOUT."""
    c = classify_service_error(_exc("timed out after 30 seconds"))
    assert c.error_code != "YTDLP_TIMEOUT"


# ---------------------------------------------------------------------------
# Non-matching / fallback cases
# ---------------------------------------------------------------------------

def test_unrelated_message_falls_back_to_unexpected_error() -> None:
    c = classify_service_error(_exc("something completely unrelated happened"))
    assert c.error_code == "UNEXPECTED_ERROR"
    assert c.status_code == 502
    assert c.retryable is False


def test_partial_pattern_does_not_match() -> None:
    """'video' alone must not trigger VIDEO_UNAVAILABLE."""
    c = classify_service_error(_exc("video processing failed"))
    assert c.error_code != "VIDEO_UNAVAILABLE"


def test_empty_message_falls_back_to_unexpected_error() -> None:
    c = classify_service_error(_exc(""))
    assert c.error_code == "UNEXPECTED_ERROR"
