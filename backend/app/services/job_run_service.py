import logging
import multiprocessing
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from queue import Empty
from typing import Callable
from typing import Literal

from app.config import get_env_str
from app.services.content_context_service import create_content_context
from app.services.participant_candidate_service import extract_candidate_people
from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
)
from app.services.speaker_diarization_service import (
    SpeakerDiarizationConfigurationError,
    SpeakerDiarizationRuntimeError,
    assign_speakers_to_transcript,
    diarize_audio_file,
)
from app.services.speaker_identity_service import (
    apply_speaker_identities,
    resolve_speaker_identities,
)
from app.services.transcription_service import (
    TranscriptSegment,
    TranscriptionResult,
    transcribe_audio_file,
)
from app.services.translation_service import (
    TranslationSegment,
    translate_segments_to_chinese,
)
from app.services.video_source_service import (
    SOURCE_MODE_SUBTITLE_FIRST,
    SourceMode,
    VideoSourceResult,
    fetch_video_source_from_info,
)
from app.services.yt_dlp_service import (
    VideoMetadata,
    build_video_metadata,
    extract_video_info,
)


logger = logging.getLogger(__name__)
SENTENCE_END_PATTERN = re.compile(r"[.!?。！？…][\"')\]]*$")
DEFAULT_TRANSLATION_COMPACT_SEGMENT_THRESHOLD = 50
DEFAULT_TRANSLATION_COMPACT_MAX_WORDS = 36
DEFAULT_TRANSLATION_COMPACT_MAX_DURATION_SEC = 14.0
DEFAULT_TRANSLATION_COMPACT_MAX_GAP_SEC = 1.3


JobStage = Literal["inspect", "fetch_source", "transcribe", "translate", "persist"]
JobProgressCallback = Callable[[JobStage, int, str], None]
JobCancellationChecker = Callable[[], bool]


@dataclass(frozen=True)
class JobStageTimeouts:
    inspect: int = 45
    fetch_source: int = 180
    transcribe: int = 900
    translate: int = 900

    def for_stage(self, stage: JobStage) -> int:
        if stage == "inspect":
            return self.inspect
        if stage == "fetch_source":
            return self.fetch_source
        if stage == "transcribe":
            return self.transcribe
        if stage == "translate":
            return self.translate
        return 120


class JobRunError(Exception):
    """Raised when the end-to-end job pipeline cannot produce a valid result."""


class JobCancelledError(JobRunError):
    """Raised when a running job has been cancelled by user."""


class JobStageTimeoutError(JobRunError):
    """Raised when a job stage exceeds its configured timeout."""

    def __init__(self, *, stage: JobStage, timeout_sec: int):
        super().__init__(f"Job stage '{stage}' timed out after {timeout_sec}s.")
        self.stage = stage
        self.timeout_sec = timeout_sec


@dataclass(frozen=True)
class JobRunResult:
    video: VideoMetadata
    source_type: Literal["captions", "audio"]
    transcript_en: TranscriptionResult
    translation_zh_segments: list[TranslationSegment]
    content_context_id: str


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
) -> JobRunResult:
    logger.info("Starting job run for %s", url)
    timeouts = _resolve_stage_timeouts(stage_timeout_seconds)
    emit_progress = progress_callback or _noop_progress
    _raise_if_cancelled(cancellation_checker)

    emit_progress("inspect", 12, "正在解析视频信息...")
    video_info = _run_stage_with_timeout(
        stage="inspect",
        timeout_sec=timeouts.inspect,
        func=extract_video_info,
        args=[url],
        cancellation_checker=cancellation_checker,
    )
    video = build_video_metadata(video_info)
    logger.info("Loaded metadata for %s (%s)", video.video_id, video.title)

    emit_progress("fetch_source", 25, "正在提取字幕或音频...")
    source = _run_stage_with_timeout(
        stage="fetch_source",
        timeout_sec=timeouts.fetch_source,
        func=fetch_video_source_from_info,
        args=[url, video_info],
        source_mode=source_mode,
        cancellation_checker=cancellation_checker,
    )
    logger.info("Selected source type %s for %s", source.source_type, video.video_id)

    emit_progress(
        "transcribe",
        45,
        "检测到字幕，正在整理文本..." if source.source_type == "captions" else "正在进行本地转录...",
    )
    transcript = _load_cached_material_transcript(video.video_id, source)
    if transcript is None:
        transcript = _run_transcribe_stage(
            source=source,
            timeout_sec=timeouts.transcribe,
            cancellation_checker=cancellation_checker,
        )
        _store_cached_material_transcript(video.video_id, source, transcript)
    else:
        logger.info(
            "Using cached transcript material for %s (source=%s)",
            video.video_id,
            source.source_type,
        )
    if _job_run_should_attach_speakers():
        transcript = _maybe_attach_speakers(
            video=video, source=source, transcript=transcript
        )
    else:
        logger.info(
            "Skipping speaker attachment during main job run for %s", video.video_id
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

    logger.info(
        "Prepared English transcript with %s segments for %s",
        len(transcript.segments),
        video.video_id,
    )

    emit_progress("translate", 70, "正在翻译中文字幕...")
    _raise_if_cancelled(cancellation_checker)
    translations = _run_stage_with_timeout(
        stage="translate",
        timeout_sec=timeouts.translate,
        func=translate_segments_to_chinese,
        args=[
            [
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                }
                for segment in transcript.segments
            ]
        ],
        translation_config=translation_config,
        cancellation_checker=cancellation_checker,
    )
    logger.info(
        "Translated %s segments for %s",
        len(translations),
        video.video_id,
    )
    content_context_id = create_content_context(
        video_id=video.video_id,
        video_url=url,
        video_title=video.title,
        video_duration_sec=video.duration_sec,
        video_uploader=video.uploader,
        video_thumbnail=video.thumbnail,
        source_type=source.source_type,
        transcript_en=transcript.text,
        translation_zh=_translation_segments_to_text(translations),
    )
    _raise_if_cancelled(cancellation_checker)

    return JobRunResult(
        video=video,
        source_type=source.source_type,
        transcript_en=transcript,
        translation_zh_segments=translations,
        content_context_id=content_context_id,
    )


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
        translate=_normalize_positive_timeout(override.get("translate"), base.translate),
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
    stage: JobStage,
    timeout_sec: int,
    func,
    args: list[object] | None = None,
    cancellation_checker: JobCancellationChecker | None = None,
    **kwargs,
):
    normalized_args = args or []
    started_at = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *normalized_args, **kwargs)
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


def _run_transcribe_stage(
    *,
    source: VideoSourceResult,
    timeout_sec: int,
    cancellation_checker: JobCancellationChecker | None = None,
) -> TranscriptionResult:
    _raise_if_cancelled(cancellation_checker)
    if source.source_type == "captions":
        return _transcript_from_caption_text(source.text)

    if source.source_type != "audio":
        raise JobRunError(
            f"Unsupported source_type returned by source service: {source.source_type}"
        )

    if not source.audio_file_path:
        raise JobRunError("Audio source did not include an audio_file_path.")

    return _run_transcription_process_with_timeout(
        audio_file_path=source.audio_file_path,
        timeout_sec=timeout_sec,
        cancellation_checker=cancellation_checker,
    )


def _run_transcription_process_with_timeout(
    *,
    audio_file_path: str,
    timeout_sec: int,
    cancellation_checker: JobCancellationChecker | None = None,
) -> TranscriptionResult:
    _raise_if_cancelled(cancellation_checker)
    # Keep pytest monkeypatch behavior deterministic in unit tests.
    if "pytest" in sys.modules:
        return _ensure_transcript_segments(transcribe_audio_file(audio_file_path))

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(
        target=_transcribe_audio_worker,
        args=(audio_file_path, result_queue),
        daemon=True,
    )
    process.start()
    started_at = time.monotonic()
    while process.is_alive():
        _raise_if_cancelled(cancellation_checker)
        if (time.monotonic() - started_at) >= float(timeout_sec):
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            raise JobStageTimeoutError(stage="transcribe", timeout_sec=timeout_sec)
        process.join(timeout=0.25)

    try:
        result = result_queue.get_nowait()
    except Empty as error:
        raise JobRunError(
            "Transcription process exited without a result payload."
        ) from error
    finally:
        result_queue.close()

    if not isinstance(result, dict):
        raise JobRunError("Transcription process returned an invalid result payload.")

    if not result.get("ok"):
        detail = str(result.get("error") or "Unknown transcription error.")
        raise JobRunError(detail)

    payload = result.get("result")
    if not isinstance(payload, dict):
        raise JobRunError("Transcription process returned malformed transcript payload.")
    return _deserialize_transcription_result(payload)


def _transcribe_audio_worker(audio_file_path: str, result_queue) -> None:
    try:
        result = _ensure_transcript_segments(transcribe_audio_file(audio_file_path))
        result_queue.put(
            {
                "ok": True,
                "result": _serialize_transcription_result(result),
            }
        )
    except Exception as error:
        result_queue.put(
            {
                "ok": False,
                "error": str(error),
            }
        )


def _serialize_transcription_result(
    result: TranscriptionResult,
) -> dict[str, object]:
    return {
        "language": result.language,
        "text": result.text,
        "segments": [
            {
                "index": segment.index,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "speaker": segment.speaker,
            }
            for segment in result.segments
        ],
    }


def _deserialize_transcription_result(
    payload: dict[str, object],
) -> TranscriptionResult:
    language = str(payload.get("language") or "en")
    text = str(payload.get("text") or "").strip()
    raw_segments = payload.get("segments")
    segments: list[TranscriptSegment] = []
    if isinstance(raw_segments, list):
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, dict):
                continue
            segments.append(
                TranscriptSegment(
                    index=int(raw_segment.get("index", len(segments))),
                    start=float(raw_segment.get("start", 0.0)),
                    end=float(raw_segment.get("end", 0.0)),
                    text=str(raw_segment.get("text") or "").strip(),
                    speaker=(
                        str(raw_segment.get("speaker"))
                        if raw_segment.get("speaker") is not None
                        else None
                    ),
                )
            )

    return _ensure_transcript_segments(
        TranscriptionResult(
            language=language,
            text=text,
            segments=segments,
        )
    )


def _raise_if_cancelled(cancellation_checker: JobCancellationChecker | None) -> None:
    if cancellation_checker and cancellation_checker():
        raise JobCancelledError("Job was cancelled by user.")


def _noop_progress(_stage: JobStage, _value: int, _text: str) -> None:
    return


def _build_english_transcript(source: VideoSourceResult) -> TranscriptionResult:
    if source.source_type == "captions":
        return _transcript_from_caption_text(source.text)

    if source.source_type == "audio":
        if not source.audio_file_path:
            raise JobRunError("Audio source did not include an audio_file_path.")
        transcript = transcribe_audio_file(source.audio_file_path)
        return _ensure_transcript_segments(transcript)

    raise JobRunError(
        f"Unsupported source_type returned by source service: {source.source_type}"
    )


def _transcript_from_caption_text(text: str | None) -> TranscriptionResult:
    normalized_text = (text or "").strip()
    if not normalized_text:
        raise JobRunError("Caption source did not include caption text.")

    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    if not lines:
        raise JobRunError("Caption source did not include usable caption lines.")

    merged_lines = _merge_caption_lines(lines)

    return TranscriptionResult(
        language="en",
        text="\n".join(merged_lines),
        segments=[
            TranscriptSegment(
                index=index,
                start=0.0,
                end=0.0,
                text=line,
            )
            for index, line in enumerate(merged_lines)
        ],
    )


def _ensure_transcript_segments(result: TranscriptionResult) -> TranscriptionResult:
    if result.segments:
        return result

    normalized_text = result.text.strip()
    if not normalized_text:
        raise JobRunError("Transcription result did not include transcript text.")

    return TranscriptionResult(
        language=result.language or "en",
        text=normalized_text,
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=0.0,
                text=normalized_text,
            )
        ],
    )


def _maybe_attach_speakers(
    video: VideoMetadata,
    source: VideoSourceResult,
    transcript: TranscriptionResult,
) -> TranscriptionResult:
    if source.source_type != "audio" or not source.audio_file_path:
        return transcript

    try:
        diarization = diarize_audio_file(source.audio_file_path)
        diarized_transcript = assign_speakers_to_transcript(transcript, diarization)
        candidates = extract_candidate_people(video)
        if not candidates:
            return diarized_transcript

        identities = resolve_speaker_identities(diarized_transcript, candidates)
        return apply_speaker_identities(diarized_transcript, identities)
    except (
        SpeakerDiarizationConfigurationError,
        SpeakerDiarizationRuntimeError,
    ) as error:
        logger.warning("Speaker attachment skipped for %s: %s", video.video_id, error)
        return transcript


def _job_run_should_attach_speakers() -> bool:
    raw_value = get_env_str("JOB_RUN_ATTACH_SPEAKERS").lower()
    return raw_value in {"1", "true", "yes", "on"}


def _should_compact_transcript_for_translation(
    source_type: str,
    transcript: TranscriptionResult,
) -> bool:
    if source_type != "audio":
        return False
    if len(transcript.segments) < _get_positive_int_env(
        "JOB_TRANSLATION_COMPACT_SEGMENT_THRESHOLD",
        DEFAULT_TRANSLATION_COMPACT_SEGMENT_THRESHOLD,
    ):
        return False
    raw_value = get_env_str("JOB_TRANSLATION_COMPACT_SEGMENTS").lower()
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return True


def _compact_transcript_segments(
    transcript: TranscriptionResult,
) -> TranscriptionResult:
    max_words = _get_positive_int_env(
        "JOB_TRANSLATION_COMPACT_MAX_WORDS",
        DEFAULT_TRANSLATION_COMPACT_MAX_WORDS,
    )
    max_duration_sec = _get_positive_float_env(
        "JOB_TRANSLATION_COMPACT_MAX_DURATION_SEC",
        DEFAULT_TRANSLATION_COMPACT_MAX_DURATION_SEC,
    )
    max_gap_sec = _get_positive_float_env(
        "JOB_TRANSLATION_COMPACT_MAX_GAP_SEC",
        DEFAULT_TRANSLATION_COMPACT_MAX_GAP_SEC,
    )

    compacted: list[TranscriptSegment] = []
    current: TranscriptSegment | None = None

    for segment in transcript.segments:
        text = segment.text.strip()
        if not text:
            continue

        candidate = TranscriptSegment(
            index=segment.index,
            start=segment.start,
            end=segment.end,
            text=text,
            speaker=segment.speaker,
        )

        if current is None:
            current = candidate
            continue

        gap_sec = max(0.0, candidate.start - current.end)
        speaker_changed = bool(
            current.speaker and candidate.speaker and current.speaker != candidate.speaker
        )
        candidate_word_count = _word_count(current.text) + _word_count(candidate.text)
        candidate_duration_sec = max(candidate.end, current.end) - current.start
        current_is_sentence = _line_ends_sentence(current.text)
        current_long_enough = _word_count(current.text) >= max(8, max_words // 3)

        should_flush = (
            speaker_changed
            or gap_sec > max_gap_sec
            or candidate_word_count > max_words
            or candidate_duration_sec > max_duration_sec
            or (current_is_sentence and current_long_enough)
        )

        if should_flush:
            compacted.append(current)
            current = candidate
            continue

        merged_speaker = current.speaker or candidate.speaker
        current = TranscriptSegment(
            index=current.index,
            start=current.start,
            end=max(current.end, candidate.end),
            text=f"{current.text} {candidate.text}".strip(),
            speaker=merged_speaker,
        )

    if current is not None:
        compacted.append(current)

    if len(compacted) >= len(transcript.segments):
        return transcript

    reindexed_segments = [
        TranscriptSegment(
            index=index,
            start=segment.start,
            end=segment.end,
            text=segment.text,
            speaker=segment.speaker,
        )
        for index, segment in enumerate(compacted)
    ]
    return TranscriptionResult(
        language=transcript.language,
        text="\n".join(segment.text for segment in reindexed_segments).strip(),
        segments=reindexed_segments,
    )


def _line_ends_sentence(value: str) -> bool:
    return bool(SENTENCE_END_PATTERN.search(value.strip()))


def _word_count(value: str) -> int:
    return len(value.split())


def _get_positive_int_env(name: str, default: int) -> int:
    raw_value = get_env_str(name)
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _get_positive_float_env(name: str, default: float) -> float:
    raw_value = get_env_str(name)
    if not raw_value:
        return default
    try:
        parsed = float(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


CAPTION_SENTENCE_END_PATTERN = re.compile(r"[.!?。！？…][\"')\]]*$")
CAPTION_CONTINUATION_HINT_PATTERN = re.compile(r"^[a-z0-9\"'(<\\[]")


def _merge_caption_lines(lines: list[str]) -> list[str]:
    merged_lines: list[str] = []
    current_line = ""

    for line in lines:
        normalized_line = line.strip()
        if not normalized_line:
            continue

        if not current_line:
            current_line = normalized_line
            continue

        if _caption_line_ends_sentence(current_line):
            merged_lines.append(current_line)
            current_line = normalized_line
            continue

        if (
            len(current_line.split()) >= 18
            and normalized_line[:1].isupper()
            and not _looks_like_caption_continuation(normalized_line)
        ):
            merged_lines.append(current_line)
            current_line = normalized_line
            continue

        current_line = f"{current_line} {normalized_line}".strip()

    if current_line:
        merged_lines.append(current_line)

    return merged_lines or lines


def _caption_line_ends_sentence(value: str) -> bool:
    return bool(CAPTION_SENTENCE_END_PATTERN.search(value.strip()))


def _looks_like_caption_continuation(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    return bool(CAPTION_CONTINUATION_HINT_PATTERN.match(normalized))


def _translation_segments_to_text(segments: list[TranslationSegment]) -> str:
    return "\n".join(
        segment.translated_text.strip()
        for segment in segments
        if segment.translated_text.strip()
    ).strip()


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
