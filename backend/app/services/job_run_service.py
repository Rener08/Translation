import logging
import threading
import time
from inspect import signature
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable, TypeVar

from app.config import ROOT_DIR, get_env_str, get_settings
from app.services.content_context_service import create_content_context
from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
)
from app.services.transcription_service import (
    TranscriptSegment,
    TranscriptionResult,
)
from app.services.video_source_service import (
    SOURCE_MODE_SUBTITLE_FIRST,
    SourceMode,
    VideoSourceResult,
    fetch_video_source_from_info,
)
from app.services.job_cancel_context import clear_cancel_event, set_cancel_event
from app.services.job_run_models import (
    FetchSourceStageOutput,
    InspectStageOutput,
    JobCancellationChecker,
    JobCancelledError,
    JobProgressCallback,
    JobRunError,
    JobRunPipelineState,
    JobRunResult,
    JobRunStageContext,
    JobStage,
    JobStageTimeoutError,
    JobStageTimeouts,
    PersistStageOutput,
    TranscribeStageOutput,
)
from app.services.yt_dlp_service import (
    VideoMetadata,
    build_video_metadata,
    extract_video_info,
)
from app.services.job_run_transcript import (
    _compact_transcript_segments,
    _job_run_should_attach_speakers,
    _maybe_attach_speakers,
    _raise_if_cancelled,
    _run_transcribe_stage,
    _run_transcription_process_with_timeout,  # re-exported for upload_job_service
    _should_compact_transcript_for_translation,
)


logger = logging.getLogger(__name__)


StageOutputT = TypeVar("StageOutputT")
StageValueT = TypeVar("StageValueT")


def _get_positive_int_env(name: str, default: int) -> int:
    raw_value = get_env_str(name)
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


_TRANSCRIBE_STAGE_SEMAPHORE = threading.BoundedSemaphore(
    _get_positive_int_env("TRANSCRIBE_STAGE_MAX_CONCURRENCY", 1)
)


@contextmanager
def _acquire_transcribe_stage_slot():
    _TRANSCRIBE_STAGE_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _TRANSCRIBE_STAGE_SEMAPHORE.release()


class JobRunStageMachine:
    def __init__(self, context: JobRunStageContext):
        self._context = context

    def run(self) -> JobRunResult:
        state = JobRunPipelineState(context=self._context)
        state = self._run_inspect_stage(state)
        state = self._run_fetch_source_stage(state)
        state = self._run_transcribe_stage(state)
        state = self._run_persist_stage(state)

        video = _require_stage_value(state.video, "video")
        source = _require_stage_value(state.source, "source")
        transcript = _require_stage_value(state.transcript, "transcript")
        content_context_id = _require_stage_value(
            state.content_context_id, "content_context_id"
        )

        return JobRunResult(
            video=video,
            source_type=source.source_type,
            transcript_en=transcript,
            content_context_id=content_context_id,
        )

    def _run_inspect_stage(self, state: JobRunPipelineState) -> JobRunPipelineState:
        output = self._run_stage(
            stage="inspect",
            progress_value=12,
            progress_text="正在解析视频信息...",
            timeout_sec=self._context.stage_timeouts.inspect,
            func=self._inspect_stage,
        )
        return replace(state, video_info=output.video_info, video=output.video)

    def _inspect_stage(self) -> InspectStageOutput:
        video_info = extract_video_info(self._context.url)
        video = build_video_metadata(video_info)
        logger.info("Loaded metadata for %s (%s)", video.video_id, video.title)
        _ensure_video_duration_within_limit(video)
        return InspectStageOutput(video_info=video_info, video=video)

    def _run_fetch_source_stage(self, state: JobRunPipelineState) -> JobRunPipelineState:
        video_info = _require_stage_value(state.video_info, "video_info")
        output = self._run_stage(
            stage="fetch_source",
            progress_value=25,
            progress_text="正在提取字幕或音频...",
            timeout_sec=self._context.stage_timeouts.fetch_source,
            func=lambda: self._fetch_source_stage(video_info),
        )
        return replace(state, source=output.source)

    def _fetch_source_stage(self, video_info: dict[str, object]) -> FetchSourceStageOutput:
        source = _call_fetch_video_source_from_info(
            self._context.url,
            video_info,
            source_mode=self._context.source_mode,
            cancellation_checker=self._context.cancellation_checker,
            caption_request_timeout_sec=self._context.stage_timeouts.fetch_source,
        )
        logger.info("Selected source type %s for %s", source.source_type, video_info.get("id"))
        if source.source_type == "audio" and source.audio_file_path:
            _ensure_audio_file_within_limit(source.audio_file_path)
        return FetchSourceStageOutput(source=source)

    def _run_transcribe_stage(self, state: JobRunPipelineState) -> JobRunPipelineState:
        source = _require_stage_value(state.source, "source")
        progress_text = (
            "检测到字幕，正在整理文本..."
            if source.source_type == "captions"
            else "正在进行本地转录..."
        )
        output = self._run_stage(
            stage="transcribe",
            progress_value=45,
            progress_text=progress_text,
            timeout_sec=self._context.stage_timeouts.transcribe,
            func=lambda: self._transcribe_stage(state),
        )
        return replace(state, transcript=output.transcript)

    def _transcribe_stage(self, state: JobRunPipelineState) -> TranscribeStageOutput:
        source = _require_stage_value(state.source, "source")
        video = _require_stage_value(state.video, "video")
        _raise_if_cancelled(self._context.cancellation_checker)
        transcript = _load_cached_material_transcript(self._context.url, source)
        if transcript is None:
            with _acquire_transcribe_stage_slot():
                transcript = _run_transcribe_stage(
                    source=source,
                    timeout_sec=self._context.stage_timeouts.transcribe,
                    cancellation_checker=self._context.cancellation_checker,
                )
                _raise_if_cancelled(self._context.cancellation_checker)
                if _job_run_should_attach_speakers():
                    transcript = _maybe_attach_speakers(
                        video=video,
                        source=source,
                        transcript=transcript,
                    )
                else:
                    logger.info(
                        "Skipping speaker attachment during main job run for %s",
                        video.video_id,
                    )

                _raise_if_cancelled(self._context.cancellation_checker)
                if _should_compact_transcript_for_translation(source.source_type, transcript):
                    compacted_transcript = _compact_transcript_segments(transcript)
                    if len(compacted_transcript.segments) < len(transcript.segments):
                        logger.info(
                            "Compacted transcript segments for translation from %s to %s for %s",
                            len(transcript.segments),
                            len(compacted_transcript.segments),
                            video.video_id,
                        )
                        transcript = compacted_transcript
                _store_cached_material_transcript(self._context.url, source, transcript)
        else:
            logger.info(
                "Using cached transcript material for %s (source=%s)",
                self._context.url,
                source.source_type,
            )
            if _job_run_should_attach_speakers():
                transcript = _maybe_attach_speakers(
                    video=video,
                    source=source,
                    transcript=transcript,
                )
            else:
                logger.info(
                    "Skipping speaker attachment during main job run for %s",
                    video.video_id,
                )
            if _should_compact_transcript_for_translation(source.source_type, transcript):
                compacted_transcript = _compact_transcript_segments(transcript)
                if len(compacted_transcript.segments) < len(transcript.segments):
                    logger.info(
                        "Compacted transcript segments for translation from %s to %s for %s",
                        len(transcript.segments),
                        len(compacted_transcript.segments),
                        video.video_id,
                    )
                    transcript = compacted_transcript

        _ensure_transcript_within_limits(transcript)
        logger.info(
            "Prepared English transcript with %s segments for %s",
            len(transcript.segments),
            video.video_id,
        )
        return TranscribeStageOutput(transcript=transcript)

    def _run_persist_stage(self, state: JobRunPipelineState) -> JobRunPipelineState:
        output = self._run_stage(
            stage="persist",
            progress_value=85,
            progress_text="正在生成内容上下文...",
            timeout_sec=self._context.stage_timeouts.persist,
            func=lambda: self._persist_stage(state),
        )
        return replace(state, content_context_id=output.content_context_id)

    def _persist_stage(self, state: JobRunPipelineState) -> PersistStageOutput:
        video = _require_stage_value(state.video, "video")
        source = _require_stage_value(state.source, "source")
        transcript = _require_stage_value(state.transcript, "transcript")
        content_context_id = create_content_context(
            video_id=video.video_id,
            video_url=self._context.url,
            video_title=video.title,
            video_duration_sec=video.duration_sec,
            video_uploader=video.uploader,
            video_thumbnail=video.thumbnail,
            source_type=source.source_type,
            transcript_en=transcript.text,
            translation_zh="",
            account_id=self._context.account_id,
        )
        return PersistStageOutput(content_context_id=content_context_id)

    def _run_stage(
        self,
        *,
        stage: JobStage,
        progress_value: int,
        progress_text: str,
        timeout_sec: int,
        func: Callable[[], StageOutputT],
    ) -> StageOutputT:
        _raise_if_cancelled(self._context.cancellation_checker)
        self._context.progress_callback(stage, progress_value, progress_text)
        _raise_if_cancelled(self._context.cancellation_checker)
        return _run_stage_with_timeout(
            stage=stage,
            timeout_sec=timeout_sec,
            func=func,
            cancellation_checker=self._context.cancellation_checker,
        )


def run_video_job(
    url: str,
    source_mode: SourceMode = SOURCE_MODE_SUBTITLE_FIRST,
) -> JobRunResult:
    return run_video_job_with_translation_config(url, source_mode=source_mode)


def run_video_job_with_translation_config(
    url: str,
    translation_config: dict[str, object] | None = None,
    source_mode: SourceMode = SOURCE_MODE_SUBTITLE_FIRST,
    progress_callback: JobProgressCallback | None = None,
    stage_timeout_seconds: dict[str, int] | None = None,
    cancellation_checker: JobCancellationChecker | None = None,
    account_id: str | None = None,
) -> JobRunResult:
    logger.info("Starting job run for %s", url)
    timeouts = _resolve_stage_timeouts(stage_timeout_seconds)
    machine = JobRunStageMachine(
        JobRunStageContext(
            url=url,
            translation_config=translation_config,
            source_mode=source_mode,
            stage_timeouts=timeouts,
            progress_callback=progress_callback or _noop_progress,
            cancellation_checker=cancellation_checker,
            account_id=account_id,
        )
    )
    return machine.run()


def _resolve_stage_timeouts(
    override: dict[str, int] | None,
) -> JobStageTimeouts:
    if not isinstance(override, dict):
        return JobStageTimeouts()

    base = JobStageTimeouts()
    return JobStageTimeouts(
        inspect=_normalize_positive_timeout(override.get("inspect"), base.inspect),
        fetch_source=_normalize_positive_timeout(
            override.get("fetch_source"), base.fetch_source
        ),
        transcribe=_normalize_positive_timeout(override.get("transcribe"), base.transcribe),
        persist=_normalize_positive_timeout(override.get("persist"), base.persist),
    )


def _normalize_positive_timeout(value: object, fallback: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if parsed <= 0:
        return fallback
    return parsed


def _call_fetch_video_source_from_info(
    url: str,
    video_info: dict[str, object],
    *,
    source_mode: SourceMode,
    cancellation_checker,
    caption_request_timeout_sec: int | float | None,
):
    parameters = signature(fetch_video_source_from_info).parameters
    if "cancellation_checker" in parameters or "caption_request_timeout_sec" in parameters:
        return fetch_video_source_from_info(
            url,
            video_info,
            source_mode=source_mode,
            cancellation_checker=cancellation_checker,
            caption_request_timeout_sec=caption_request_timeout_sec,
        )
    return fetch_video_source_from_info(url, video_info, source_mode=source_mode)


def _run_stage_with_timeout(
    *,
    stage: JobStage,
    timeout_sec: int,
    func,
    args: list[object] | None = None,
    cancellation_checker: JobCancellationChecker | None = None,
    **kwargs,
):
    normalized_args = args or []
    cancel_event = threading.Event()

    def _wrapped():
        set_cancel_event(cancel_event)
        try:
            return func(*normalized_args, **kwargs)
        finally:
            clear_cancel_event()

    started_at = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_wrapped)
    try:
        while True:
            try:
                _raise_if_cancelled(cancellation_checker)
            except JobCancelledError:
                cancel_event.set()
                raise
            elapsed = time.monotonic() - started_at
            remaining = float(timeout_sec) - elapsed
            if remaining <= 0:
                cancel_event.set()
                future.cancel()
                raise JobStageTimeoutError(stage=stage, timeout_sec=timeout_sec)
            wait_slice = min(0.5, remaining)
            try:
                return future.result(timeout=wait_slice)
            except FutureTimeoutError:
                continue
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _noop_progress(_stage: JobStage, _value: int, _text: str) -> None:
    return


def _require_stage_value(value: StageValueT | None, name: str) -> StageValueT:
    if value is None:
        raise JobRunError(f"Missing required pipeline value: {name}.")
    return value


def _load_cached_material_transcript(
    video_id: str,
    source: VideoSourceResult,
) -> TranscriptionResult | None:
    key = _material_transcript_cache_key(video_id, source)
    payload = load_json_cache("material_transcript", key)
    if not isinstance(payload, dict):
        return None

    language = str(payload.get("language") or "").strip()
    text = str(payload.get("text") or "").strip()
    raw_segments = payload.get("segments")
    if not language or not text or not isinstance(raw_segments, list):
        return None

    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            return None
        segment_text = str(item.get("text") or "").strip()
        if not segment_text:
            continue
        segments.append(
            TranscriptSegment(
                index=int(item.get("index") or 0),
                start=_safe_float(item.get("start")),
                end=_safe_float(item.get("end")),
                text=segment_text,
                speaker=str(item.get("speaker") or "").strip() or None,
            )
        )

    if not segments:
        return None
    return TranscriptionResult(language=language, text=text, segments=segments)


def _store_cached_material_transcript(
    video_id: str,
    source: VideoSourceResult,
    transcript: TranscriptionResult,
) -> None:
    key = _material_transcript_cache_key(video_id, source)
    store_json_cache(
        "material_transcript",
        key,
        {
            "language": transcript.language,
            "text": transcript.text,
            "segments": [
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "speaker": segment.speaker,
                }
                for segment in transcript.segments
            ],
        },
    )


def _material_transcript_cache_key(video_id: str, source: VideoSourceResult) -> str:
    source_fingerprint = {
        "source_type": source.source_type,
        "language": source.language or "",
        "text": source.text or "",
        "audio_file_path": source.audio_file_path or "",
    }
    return build_cache_key(
        {
            "video_id": video_id,
            "source": source_fingerprint,
        }
    )


def _safe_float(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _ensure_video_duration_within_limit(video: VideoMetadata) -> None:
    max_video_duration_sec = get_settings().max_video_duration_sec
    if max_video_duration_sec <= 0:
        return

    duration_sec = video.duration_sec
    if duration_sec is None:
        return

    if duration_sec > max_video_duration_sec:
        raise ValueError(
            "Video duration is "
            f"{duration_sec}s, exceeding MAX_VIDEO_DURATION_SEC={max_video_duration_sec}."
        )


def _ensure_audio_file_within_limit(audio_file_path: str) -> None:
    max_audio_bytes = get_settings().max_audio_bytes
    if max_audio_bytes <= 0:
        return

    file_path = _resolve_job_audio_file_path(audio_file_path)
    if not file_path.exists() or not file_path.is_file():
        return

    audio_size = file_path.stat().st_size
    if audio_size > max_audio_bytes:
        raise ValueError(
            "Audio file is "
            f"{audio_size} bytes, exceeding MAX_AUDIO_BYTES={max_audio_bytes}."
        )


def _ensure_transcript_within_limits(transcript: TranscriptionResult) -> None:
    max_transcript_chars = get_settings().max_transcript_chars
    if max_transcript_chars > 0 and len(transcript.text.strip()) > max_transcript_chars:
        raise ValueError(
            "Transcript is "
            f"{len(transcript.text.strip())} characters, exceeding MAX_TRANSCRIPT_CHARS={max_transcript_chars}."
        )

    max_translation_segments = get_settings().max_translation_segments
    if max_translation_segments > 0 and len(transcript.segments) > max_translation_segments:
        raise ValueError(
            "Transcript has "
            f"{len(transcript.segments)} segments, exceeding MAX_TRANSLATION_SEGMENTS={max_translation_segments}."
        )


def _resolve_job_audio_file_path(audio_file_path: str) -> Path:
    raw_path = Path(audio_file_path)
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (ROOT_DIR / raw_path).resolve()
