from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from app.services.audio_download_service import AudioDownloadError
from app.services.caption_service import CaptionServiceError
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


def classify_service_error(error: Exception) -> ErrorClassification:
    message = str(error)
    lowered = message.lower()

    if isinstance(error, ContentRewriteInputError):
        return ErrorClassification(400, "REWRITE_INPUT_INVALID", False, message)
    if isinstance(error, ValueError):
        return ErrorClassification(400, "INVALID_INPUT", False, message)
    if isinstance(error, AudioFileNotFoundError):
        return ErrorClassification(400, "AUDIO_FILE_NOT_FOUND", False, message)

    if isinstance(
        error,
        (
            TranscriptionConfigurationError,
            TranslationConfigurationError,
            SpeakerDiarizationConfigurationError,
            ContentChatConfigurationError,
            ContentRewriteConfigurationError,
            YtDlpNotInstalledError,
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

    if "429" in lowered or "too many requests" in lowered:
        return ErrorClassification(502, "YTDLP_429", True, message)
    if "sign in to confirm you're not a bot" in lowered:
        return ErrorClassification(502, "COOKIE_STALE", True, message)

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
    raise HTTPException(status_code=classification.status_code, detail=classification.detail) from error
