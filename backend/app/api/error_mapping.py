from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from fastapi import HTTPException

from app.services.audio_download_service import AudioDownloadError, AudioDownloadTimeoutError
from app.services.caption_service import CaptionDownloadTimeoutError, CaptionServiceError
from app.services.content_chat_service import ContentChatConfigurationError, ContentChatProviderError
from app.services.content_rewrite_service import (
    ContentRewriteConfigurationError,
    ContentRewriteEmptyOutputError,
    ContentRewriteInputError,
    ContentRewriteProviderError,
)
from app.services.job_run_service import JobRunError, JobStageTimeoutError
from app.services.speaker_diarization_service import (
    SpeakerDiarizationConfigurationError,
    SpeakerDiarizationRuntimeError,
)
from app.services.transcription_service import (
    AudioFileNotFoundError,
    LocalTranscriptionError,
    TranscriptionConfigurationError,
)
from app.services.translation_service import TranslationConfigurationError, TranslationProviderError
from app.services.yt_dlp_service import VideoInspectError, YtDlpNotInstalledError


@dataclass(frozen=True)
class ErrorClassification:
    status_code: int
    error_code: str
    retryable: bool
    detail: str


def build_error_payload(
    *,
    detail: str,
    error_code: str,
    retryable: bool,
    request_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "detail": detail,
        "error_code": error_code,
        "retryable": retryable,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def default_error_code_for_status(status_code: int) -> str:
    if status_code == 400:
        return "INVALID_REQUEST"
    if status_code == 401:
        return "UNAUTHORIZED"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 409:
        return "CONFLICT"
    if status_code == 422:
        return "VALIDATION_ERROR"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code == 503:
        return "SERVICE_UNAVAILABLE"
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "UNEXPECTED_ERROR"


def default_retryable_for_status(status_code: int) -> bool:
    return status_code in {429, 502, 503}


def normalize_http_exception_detail(detail: object, status_code: int) -> tuple[str, str, bool]:
    if isinstance(detail, dict):
        if {"detail", "error_code", "retryable"} <= detail.keys():
            return (
                str(detail["detail"]),
                str(detail["error_code"]),
                bool(detail["retryable"]),
            )
        raw_detail = detail.get("detail") or detail.get("message") or detail.get("status") or detail
        error_code = str(detail.get("error_code") or default_error_code_for_status(status_code))
        if "retryable" in detail:
            retryable = bool(detail["retryable"])
        else:
            retryable = default_retryable_for_status(status_code)
        return _stringify_detail(raw_detail), error_code, retryable
    return _stringify_detail(detail), default_error_code_for_status(status_code), default_retryable_for_status(status_code)


def classify_service_error(error: Exception) -> ErrorClassification:
    message = str(error)
    lowered = message.lower()

    if isinstance(error, ContentRewriteInputError):
        return ErrorClassification(400, "REWRITE_INPUT_INVALID", False, message)
    if isinstance(error, ValueError):
        if "youtube" in lowered and ("valid" in lowered or "video_id" in lowered):
            return ErrorClassification(400, "YOUTUBE_URL_INVALID", False, message)
        return ErrorClassification(400, "INVALID_INPUT", False, message)
    if isinstance(error, AudioFileNotFoundError):
        return ErrorClassification(400, "AUDIO_FILE_NOT_FOUND", False, message)

    if isinstance(error, YtDlpNotInstalledError):
        return ErrorClassification(500, "YTDLP_NOT_INSTALLED", False, message)

    if isinstance(error, (AudioDownloadTimeoutError, CaptionDownloadTimeoutError)):
        return ErrorClassification(502, "YTDLP_TIMEOUT", True, message)

    if isinstance(
        error,
        (
            TranscriptionConfigurationError,
            TranslationConfigurationError,
            SpeakerDiarizationConfigurationError,
            ContentChatConfigurationError,
            ContentRewriteConfigurationError,
        ),
    ):
        return ErrorClassification(500, "CONFIGURATION_ERROR", False, message)

    if isinstance(error, JobStageTimeoutError):
        return ErrorClassification(
            502,
            f"{error.stage.upper()}_TIMEOUT",
            True,
            message,
        )

    if "video unavailable" in lowered:
        return ErrorClassification(502, "VIDEO_UNAVAILABLE", True, message)
    if "private video" in lowered:
        return ErrorClassification(502, "VIDEO_PRIVATE", False, message)
    if (
        "not available in your country" in lowered
        or "not available in your region" in lowered
        or "geo-restricted" in lowered
    ):
        return ErrorClassification(502, "VIDEO_REGION_BLOCKED", False, message)
    if "429" in lowered or "too many requests" in lowered:
        return ErrorClassification(502, "YOUTUBE_429", True, message)
    if (
        "provided youtube account cookies are no longer valid" in lowered
        or "cookies are stale or no longer bound" in lowered
    ):
        return ErrorClassification(502, "COOKIE_STALE", True, message)
    if "could not copy chrome cookie database" in lowered:
        return ErrorClassification(502, "BROWSER_COOKIE_LOCKED", True, message)
    if "failed to decrypt with dpapi" in lowered:
        return ErrorClassification(502, "COOKIE_DECRYPT_FAILED", False, message)
    if "sign in to confirm you're not a bot" in lowered:
        return ErrorClassification(502, "YOUTUBE_BOT_CHECK", True, message)
    if (
        "use --cookies-from-browser or --cookies" in lowered
        or "signed-in browser session" in lowered
    ):
        return ErrorClassification(502, "COOKIE_REQUIRED", True, message)
    if (
        "timed out after" in lowered
        and "yt-dlp" in lowered
    ):
        return ErrorClassification(502, "YTDLP_TIMEOUT", True, message)

    if isinstance(error, ContentRewriteEmptyOutputError):
        return ErrorClassification(502, "REWRITE_EMPTY", True, message)

    if isinstance(
        error,
        (
            ContentChatProviderError,
            ContentRewriteProviderError,
            TranslationProviderError,
            LocalTranscriptionError,
            SpeakerDiarizationRuntimeError,
            AudioDownloadError,
            CaptionServiceError,
            JobRunError,
            VideoInspectError,
        ),
    ):
        return ErrorClassification(502, "UPSTREAM_ERROR", True, message)

    return ErrorClassification(502, "UNEXPECTED_ERROR", False, message)


def raise_mapped_http_exception(error: Exception) -> None:
    classification = classify_service_error(error)
    raise HTTPException(
        status_code=classification.status_code,
        detail=build_error_payload(
            detail=classification.detail,
            error_code=classification.error_code,
            retryable=classification.retryable,
        ),
    ) from error


def _stringify_detail(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, (dict, list, tuple)):
        try:
            return json.dumps(detail, ensure_ascii=False)
        except TypeError:
            pass
    return str(detail)
