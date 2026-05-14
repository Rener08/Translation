from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import TYPE_CHECKING

from app.config import ROOT_DIR, get_env_str
from app.services.persistent_cache_service import (
    build_cache_key,
    load_json_cache,
    store_json_cache,
)

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[a-zA-Z]:[\\/]")

class TranscriptionError(Exception):
    """Base error for transcription failures."""


class TranscriptionConfigurationError(TranscriptionError):
    """Raised when local transcription configuration is invalid."""


class AudioFileNotFoundError(TranscriptionError):
    """Raised when the requested audio file cannot be found."""


class LocalTranscriptionError(TranscriptionError):
    """Raised when local Whisper transcription fails."""


@dataclass(frozen=True)
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str
    speaker: str | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    language: str
    text: str
    segments: list[TranscriptSegment]


def transcribe_audio_file(audio_file_path: str) -> TranscriptionResult:
    file_path = _resolve_audio_file_path(audio_file_path)
    if not file_path.exists() or not file_path.is_file():
        raise AudioFileNotFoundError(
            f"Audio file was not found: {audio_file_path}"
        )

    cached_result = _load_cached_transcription(file_path)
    if cached_result is not None:
        return cached_result

    model = _get_whisper_model()

    try:
        raw_segments, info = model.transcribe(
            str(file_path),
            language="en",
            vad_filter=True,
        )
        segments = [
            TranscriptSegment(
                index=index,
                start=_as_float(segment.start),
                end=_as_float(segment.end),
                text=str(segment.text or "").strip(),
            )
            for index, segment in enumerate(raw_segments)
            if str(segment.text or "").strip()
        ]
    except ValueError as error:
        raise TranscriptionConfigurationError(str(error)) from error
    except Exception as error:
        raise LocalTranscriptionError(
            f"Local Whisper transcription failed: {error}"
        ) from error

    transcript_text = "\n".join(segment.text for segment in segments).strip()
    if not transcript_text:
        raise LocalTranscriptionError(
            "Local Whisper returned an empty transcript."
        )

    language = str(getattr(info, "language", "") or "").strip() or "en"

    result = TranscriptionResult(
        language=language,
        text=transcript_text,
        segments=segments,
    )
    _store_cached_transcription(file_path, result)
    return result


def _resolve_audio_file_path(audio_file_path: str) -> Path:
    raw_path = Path(audio_file_path)
    if raw_path.is_absolute() or WINDOWS_ABSOLUTE_PATH_PATTERN.match(str(audio_file_path)):
        allowed_root = (ROOT_DIR / "tmp").resolve()
        resolved = raw_path.resolve()
        if not resolved.is_relative_to(allowed_root):
            raise AudioFileNotFoundError(
                "Absolute audio paths are not allowed. Use a file under tmp/."
            )
        return resolved
    resolved = (ROOT_DIR / raw_path).resolve()
    allowed_root = (ROOT_DIR / "tmp").resolve()
    if not resolved.is_relative_to(allowed_root):
        raise AudioFileNotFoundError(
            "Audio file path must stay under tmp/."
        )
    return resolved


@lru_cache(maxsize=1)
def _get_whisper_model() -> WhisperModel:
    model_name = get_env_str("WHISPER_MODEL") or "base"
    device = get_env_str("WHISPER_DEVICE") or "cpu"
    compute_type = get_env_str("WHISPER_COMPUTE_TYPE") or "int8"

    try:
        from faster_whisper import WhisperModel as FasterWhisperModel
    except ModuleNotFoundError as error:
        raise TranscriptionConfigurationError(
            "Missing optional dependency 'faster-whisper'. "
            "Install backend requirements before enabling local transcription."
        ) from error

    try:
        return FasterWhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as error:
        raise TranscriptionConfigurationError(
            "Failed to load local Whisper model "
            f"'{model_name}' with device '{device}' and compute type '{compute_type}': {error}"
        ) from error


def _as_float(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _transcription_cache_key(file_path: Path) -> str:
    stat_result = file_path.stat()
    return build_cache_key(
        {
            "path": file_path.as_posix(),
            "size": stat_result.st_size,
            "mtime_ns": stat_result.st_mtime_ns,
            "model": get_env_str("WHISPER_MODEL") or "base",
            "device": get_env_str("WHISPER_DEVICE") or "cpu",
            "compute_type": get_env_str("WHISPER_COMPUTE_TYPE") or "int8",
        }
    )


def _load_cached_transcription(file_path: Path) -> TranscriptionResult | None:
    payload = load_json_cache("transcription", _transcription_cache_key(file_path))
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
        segments.append(
            TranscriptSegment(
                index=int(item.get("index") or 0),
                start=_as_float(item.get("start")),
                end=_as_float(item.get("end")),
                text=str(item.get("text") or "").strip(),
                speaker=str(item.get("speaker") or "").strip() or None,
            )
        )

    if not segments:
        return None

    return TranscriptionResult(language=language, text=text, segments=segments)


def _store_cached_transcription(
    file_path: Path,
    result: TranscriptionResult,
) -> None:
    store_json_cache(
        "transcription",
        _transcription_cache_key(file_path),
        {
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
        },
    )
