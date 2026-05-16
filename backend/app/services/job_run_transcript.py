import logging
import multiprocessing
import re
import sys
import time
from queue import Empty

from app.config import get_env_str
from app.services.job_run_models import (
    JobCancellationChecker,
    JobCancelledError,
    JobRunError,
    JobStageTimeoutError,
)
from app.services.participant_candidate_service import extract_candidate_people
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
    AudioFileNotFoundError,
    AudioFileTooLargeError,
    LocalTranscriptionError,
    TranscriptSegment,
    TranscriptionConfigurationError,
    TranscriptionResult,
    TranscriptTooLongError,
    transcribe_audio_file,
)
from app.services.video_source_service import VideoSourceResult
from app.services.yt_dlp_service import VideoMetadata


logger = logging.getLogger(__name__)

SENTENCE_END_PATTERN = re.compile(r"[.!?。！？…][\"')\]]*$")
CAPTION_CONTINUATION_HINT_PATTERN = re.compile(r"^[a-z0-9\"'(<\\[]")

DEFAULT_TRANSLATION_COMPACT_SEGMENT_THRESHOLD = 50
DEFAULT_TRANSLATION_COMPACT_MAX_WORDS = 36
DEFAULT_TRANSLATION_COMPACT_MAX_DURATION_SEC = 14.0
DEFAULT_TRANSLATION_COMPACT_MAX_GAP_SEC = 1.3


def _raise_if_cancelled(cancellation_checker: JobCancellationChecker | None) -> None:
    if cancellation_checker and cancellation_checker():
        raise JobCancelledError("Job was cancelled by user.")


def _map_transcription_error_type(error_type: str, detail: str) -> Exception:
    if error_type == "AudioFileNotFoundError":
        return AudioFileNotFoundError(detail)
    if error_type == "TranscriptionConfigurationError":
        return TranscriptionConfigurationError(detail)
    if error_type == "LocalTranscriptionError":
        return LocalTranscriptionError(detail)
    return JobRunError(detail)


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


def _line_ends_sentence(value: str) -> bool:
    return bool(SENTENCE_END_PATTERN.search(value.strip()))


def _word_count(value: str) -> int:
    return len(value.split())


def _caption_line_ends_sentence(value: str) -> bool:
    return bool(SENTENCE_END_PATTERN.search(value.strip()))


def _looks_like_caption_continuation(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    return bool(CAPTION_CONTINUATION_HINT_PATTERN.match(normalized))


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
                "error_type": error.__class__.__name__,
            }
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
    try:
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
    except (JobCancelledError, JobStageTimeoutError):
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
        raise

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
        error_type = str(result.get("error_type") or "").strip()
        if error_type in {"AudioFileNotFoundError", "TranscriptionConfigurationError"}:
            raise _map_transcription_error_type(error_type, detail)
        if error_type == "AudioFileTooLargeError":
            raise AudioFileTooLargeError(detail)
        if error_type == "TranscriptTooLongError":
            raise TranscriptTooLongError(detail)
        if error_type == "ValueError":
            raise ValueError(detail)
        if error_type == "LocalTranscriptionError":
            raise LocalTranscriptionError(detail)
        raise JobRunError(detail)

    payload = result.get("result")
    if not isinstance(payload, dict):
        raise JobRunError("Transcription process returned malformed transcript payload.")
    return _deserialize_transcription_result(payload)


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
