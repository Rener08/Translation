from __future__ import annotations

import hashlib
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import ROOT_DIR
from app.services.content_context_service import create_content_context
from app.services.job_run_service import (
    JobCancelledError,
    JobRunResult,
    JobStageTimeoutError,
    _run_transcription_process_with_timeout,
)
from app.services.transcript_cleaner import clean_transcript
from app.services.transcription_service import TranscriptionResult
from app.services.translation_service import TranslationSegment
from app.services.upload_audio_service import build_upload_title
from app.services.yt_dlp_service import VideoMetadata


UPLOAD_SOURCE_MODE = "force_audio"
JobProgressCallback = Callable[[str, int, str], None]
JobCancellationChecker = Callable[[], bool]


@dataclass(frozen=True)
class UploadJobStageTimeouts:
    inspect: int = 30
    transcribe: int = 900
    persist: int = 30


def run_uploaded_audio_job_with_translation_config(
    audio_file_path: str,
    *,
    title: str | None = None,
    translation_config: dict[str, object] | None = None,
    progress_callback: JobProgressCallback | None = None,
    stage_timeout_seconds: dict[str, int] | None = None,
    cancellation_checker: JobCancellationChecker | None = None,
    account_id: str | None = None,
) -> JobRunResult:
    normalized_audio_file_path = _normalize_audio_file_path(audio_file_path)
    resolved_title = build_upload_title(title or Path(normalized_audio_file_path).name)
    timeouts = _resolve_stage_timeouts(stage_timeout_seconds)
    progress = progress_callback or _noop_progress

    progress("inspect", 12, "正在校验上传文件...")
    video = _run_stage_with_timeout(
        stage="inspect",
        timeout_sec=timeouts.inspect,
        cancellation_checker=cancellation_checker,
        func=lambda: _build_upload_metadata(
            audio_file_path=normalized_audio_file_path,
            title=resolved_title,
        ),
    )

    progress("transcribe", 45, "正在进行本地转录...")
    transcript = _run_stage_with_timeout(
        stage="transcribe",
        timeout_sec=timeouts.transcribe,
        cancellation_checker=cancellation_checker,
        func=lambda: _run_transcription_process_with_timeout(
            audio_file_path=normalized_audio_file_path,
            timeout_sec=timeouts.transcribe,
            cancellation_checker=cancellation_checker,
        ),
    )

    progress("persist", 85, "正在生成内容上下文...")
    content_context_id = _run_stage_with_timeout(
        stage="persist",
        timeout_sec=timeouts.persist,
        cancellation_checker=cancellation_checker,
        func=lambda: _persist_content_context(
            video=video,
            transcript=transcript,
            account_id=account_id,
        ),
    )

    return JobRunResult(
        video=video,
        source_type="audio",
        transcript_en=transcript,
        content_context_id=content_context_id,
        translation_zh_segments=[],
    )


def _normalize_audio_file_path(audio_file_path: str) -> str:
    raw_path = Path(str(audio_file_path or "").strip())
    if not str(raw_path):
        raise ValueError("audio_file_path is required.")
    resolved = (ROOT_DIR / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
    allowed_root = (ROOT_DIR / "tmp").resolve()
    if not resolved.is_relative_to(allowed_root):
        raise ValueError("audio_file_path must stay under tmp/.")
    if not resolved.exists() or not resolved.is_file():
        raise ValueError(f"Audio file was not found: {audio_file_path}")
    return resolved.relative_to(ROOT_DIR).as_posix()


def _build_upload_metadata(*, audio_file_path: str, title: str) -> VideoMetadata:
    digest = hashlib.sha1(audio_file_path.encode("utf-8")).hexdigest()[:12]
    return VideoMetadata(
        video_id=f"upload-{digest}",
        title=title,
    )


def _persist_content_context(
    *,
    video: VideoMetadata,
    transcript: TranscriptionResult,
    account_id: str | None,
) -> str:
    return create_content_context(
        video_id=video.video_id,
        video_url=None,
        video_title=video.title,
        video_duration_sec=video.duration_sec,
        video_uploader=video.uploader,
        video_thumbnail=video.thumbnail,
        source_type="audio",
        transcript_en=transcript.text,
        translation_zh="",
        account_id=account_id,
    )


def _resolve_stage_timeouts(raw_value: dict[str, int] | None) -> UploadJobStageTimeouts:
    defaults = UploadJobStageTimeouts()
    if not isinstance(raw_value, dict):
        return defaults
    return UploadJobStageTimeouts(
        inspect=_normalize_positive_timeout(raw_value.get("inspect"), defaults.inspect),
        transcribe=_normalize_positive_timeout(raw_value.get("transcribe"), defaults.transcribe),
        persist=_normalize_positive_timeout(raw_value.get("persist"), defaults.persist),
    )


def _normalize_positive_timeout(value: object, fallback: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if parsed <= 0:
        return fallback
    return parsed


def _run_stage_with_timeout(
    *,
    stage: str,
    timeout_sec: int,
    cancellation_checker: JobCancellationChecker | None,
    func,
):
    _raise_if_cancelled(cancellation_checker)
    started_at = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func)
    try:
        while True:
            _raise_if_cancelled(cancellation_checker)
            elapsed = time.monotonic() - started_at
            remaining = float(timeout_sec) - elapsed
            if remaining <= 0:
                future.cancel()
                raise JobStageTimeoutError(stage=stage, timeout_sec=timeout_sec)
            wait_slice = min(0.5, remaining)
            try:
                return future.result(timeout=wait_slice)
            except FutureTimeoutError:
                continue
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _raise_if_cancelled(cancellation_checker: JobCancellationChecker | None) -> None:
    if cancellation_checker and cancellation_checker():
        raise JobCancelledError("Job was cancelled by user.")


def _noop_progress(_stage: str, _value: int, _text: str) -> None:
    return
