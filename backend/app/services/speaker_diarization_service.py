from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from pathlib import Path
import re
import subprocess
from typing import Any

from app.config import ROOT_DIR, get_env_str
from app.services.subprocess_utils import run_subprocess_killable
from app.services.transcription_service import (
    TranscriptSegment,
    TranscriptionResult,
)


class SpeakerDiarizationError(Exception):
    """Base error for speaker diarization failures."""


class SpeakerDiarizationConfigurationError(SpeakerDiarizationError):
    """Raised when speaker diarization is not configured correctly."""


class SpeakerDiarizationRuntimeError(SpeakerDiarizationError):
    """Raised when speaker diarization fails at runtime."""


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class SpeakerDiarizationResult:
    turns: list[SpeakerTurn]

    @property
    def speaker_count(self) -> int:
        return len({turn.speaker for turn in self.turns})


MIN_SHORT_TURN_DURATION = 1.0
MAX_SPEAKER_COUNT = 8
MIN_DOMINANT_SPEAKER_DURATION = 12.0
MERGEABLE_GAP_SECONDS = 0.35
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[a-zA-Z]:[\\/]")


def diarize_audio_file(audio_file_path: str) -> SpeakerDiarizationResult:
    file_path = _resolve_audio_file_path(audio_file_path)
    if not file_path.exists() or not file_path.is_file():
        raise SpeakerDiarizationRuntimeError(
            f"Audio file was not found: {audio_file_path}"
        )

    prepared_file_path = _prepare_audio_for_diarization(file_path)

    pipeline: Any = _get_diarization_pipeline()

    try:
        annotation: Any = pipeline(str(prepared_file_path))
    except SpeakerDiarizationConfigurationError:
        raise
    except Exception as error:
        raise SpeakerDiarizationRuntimeError(
            f"Speaker diarization failed: {error}"
        ) from error

    raw_turns: list[tuple[float, float, str]] = []
    for turn, _, label in annotation.itertracks(yield_label=True):
        start = _as_float(getattr(turn, "start", None))
        end = _as_float(getattr(turn, "end", None))
        raw_label = str(label or "").strip()
        if not raw_label or end <= start:
            continue
        raw_turns.append((start, end, raw_label))

    normalized_turns = _normalize_speaker_turns(raw_turns)
    if not normalized_turns:
        raise SpeakerDiarizationRuntimeError(
            "Speaker diarization did not return any usable speaker turns."
        )

    return SpeakerDiarizationResult(turns=normalized_turns)


def assign_speakers_to_transcript(
    transcript: TranscriptionResult,
    diarization: SpeakerDiarizationResult,
) -> TranscriptionResult:
    aligned_segments = [
        TranscriptSegment(
            index=segment.index,
            start=segment.start,
            end=segment.end,
            text=segment.text,
            speaker=_pick_best_speaker(segment, diarization.turns),
        )
        for segment in transcript.segments
    ]

    return TranscriptionResult(
        language=transcript.language,
        text=transcript.text,
        segments=aligned_segments,
    )


def _pick_best_speaker(
    segment: TranscriptSegment,
    speaker_turns: list[SpeakerTurn],
) -> str | None:
    best_speaker: str | None = None
    best_overlap = 0.0

    for turn in speaker_turns:
        overlap = _overlap_duration(segment.start, segment.end, turn.start, turn.end)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker

    if best_speaker is not None:
        return best_speaker

    if segment.end <= segment.start:
        midpoint = segment.start
    else:
        midpoint = segment.start + ((segment.end - segment.start) / 2)

    nearest_turn: SpeakerTurn | None = None
    nearest_distance: float | None = None
    for turn in speaker_turns:
        distance = _distance_to_turn(midpoint, turn)
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_turn = turn

    if nearest_turn is None:
        return None

    if nearest_distance is not None and nearest_distance <= 1.5:
        return nearest_turn.speaker
    return None


def _overlap_duration(
    segment_start: float,
    segment_end: float,
    turn_start: float,
    turn_end: float,
) -> float:
    effective_segment_end = max(segment_end, segment_start)
    overlap_start = max(segment_start, turn_start)
    overlap_end = min(effective_segment_end, turn_end)
    return max(0.0, overlap_end - overlap_start)


def _distance_to_turn(timestamp: float, turn: SpeakerTurn) -> float:
    if turn.start <= timestamp <= turn.end:
        return 0.0
    if timestamp < turn.start:
        return turn.start - timestamp
    return timestamp - turn.end


def _normalize_speaker_turns(
    raw_turns: list[tuple[float, float, str]],
) -> list[SpeakerTurn]:
    if not raw_turns:
        return []

    normalized_raw_turns = sorted(
        raw_turns, key=lambda item: (item[0], item[1], item[2])
    )
    normalized_raw_turns = _merge_adjacent_raw_turns(normalized_raw_turns)
    normalized_raw_turns = _smooth_short_interruptions(normalized_raw_turns)
    normalized_raw_turns = _collapse_rare_speakers(normalized_raw_turns)
    normalized_raw_turns = _merge_adjacent_raw_turns(normalized_raw_turns)

    ordered_labels: list[str] = []
    label_map: dict[str, str] = {}

    for _, _, raw_label in normalized_raw_turns:
        if raw_label not in label_map:
            ordered_labels.append(raw_label)
            label_map[raw_label] = f"Speaker {len(ordered_labels)}"

    return [
        SpeakerTurn(
            start=start,
            end=end,
            speaker=label_map[raw_label],
        )
        for start, end, raw_label in normalized_raw_turns
    ]


def _merge_adjacent_raw_turns(
    raw_turns: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    if not raw_turns:
        return []

    merged: list[list[float | str]] = []
    for start, end, raw_label in raw_turns:
        if not merged:
            merged.append([start, end, raw_label])
            continue

        last_start, last_end, last_label = merged[-1]
        if raw_label == last_label and start <= float(last_end) + MERGEABLE_GAP_SECONDS:
            merged[-1][1] = max(float(last_end), end)
            continue

        merged.append([start, end, raw_label])

    return [
        (float(start), float(end), str(raw_label)) for start, end, raw_label in merged
    ]


def _smooth_short_interruptions(
    raw_turns: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    if len(raw_turns) < 3:
        return raw_turns

    smoothed = list(raw_turns)
    for index in range(1, len(smoothed) - 1):
        start, end, raw_label = smoothed[index]
        duration = end - start
        if duration > MIN_SHORT_TURN_DURATION:
            continue

        prev_start, prev_end, prev_label = smoothed[index - 1]
        next_start, next_end, next_label = smoothed[index + 1]
        if prev_label != next_label:
            continue

        prev_gap = max(0.0, start - prev_end)
        next_gap = max(0.0, next_start - end)
        if prev_gap <= MERGEABLE_GAP_SECONDS and next_gap <= MERGEABLE_GAP_SECONDS:
            smoothed[index] = (start, end, prev_label)

    return smoothed


def _collapse_rare_speakers(
    raw_turns: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    durations_by_label: dict[str, float] = {}
    first_seen_by_label: dict[str, int] = {}
    for index, (start, end, raw_label) in enumerate(raw_turns):
        durations_by_label[raw_label] = durations_by_label.get(raw_label, 0.0) + (
            end - start
        )
        first_seen_by_label.setdefault(raw_label, index)

    if len(durations_by_label) <= MAX_SPEAKER_COUNT:
        return raw_turns

    dominant_labels = {
        raw_label
        for raw_label, duration in durations_by_label.items()
        if duration >= MIN_DOMINANT_SPEAKER_DURATION
    }

    if len(dominant_labels) > MAX_SPEAKER_COUNT:
        dominant_labels = set(
            label
            for label, _ in sorted(
                durations_by_label.items(),
                key=lambda item: (-item[1], first_seen_by_label[item[0]]),
            )[:MAX_SPEAKER_COUNT]
        )

    if not dominant_labels:
        dominant_labels = set(
            label
            for label, _ in sorted(
                durations_by_label.items(),
                key=lambda item: (-item[1], first_seen_by_label[item[0]]),
            )[:MAX_SPEAKER_COUNT]
        )

    collapsed: list[tuple[float, float, str]] = []
    for index, (start, end, raw_label) in enumerate(raw_turns):
        if raw_label in dominant_labels:
            collapsed.append((start, end, raw_label))
            continue

        replacement = _pick_replacement_label(
            raw_turns, index, dominant_labels, durations_by_label
        )
        collapsed.append((start, end, replacement))

    return collapsed


def _pick_replacement_label(
    raw_turns: list[tuple[float, float, str]],
    index: int,
    dominant_labels: set[str],
    durations_by_label: dict[str, float],
) -> str:
    _, _, _ = raw_turns[index]

    previous_label = next(
        (
            label
            for _, _, label in reversed(raw_turns[:index])
            if label in dominant_labels
        ),
        None,
    )
    next_label = next(
        (label for _, _, label in raw_turns[index + 1 :] if label in dominant_labels),
        None,
    )

    if previous_label and next_label and previous_label == next_label:
        return previous_label
    if previous_label and not next_label:
        return previous_label
    if next_label and not previous_label:
        return next_label
    if previous_label and next_label:
        previous_duration = durations_by_label.get(previous_label, 0.0)
        next_duration = durations_by_label.get(next_label, 0.0)
        return previous_label if previous_duration >= next_duration else next_label

    return max(
        dominant_labels,
        key=lambda label: (durations_by_label.get(label, 0.0), -raw_turns[0][0]),
    )


def _resolve_audio_file_path(audio_file_path: str) -> Path:
    raw_path = Path(audio_file_path)
    allowed_root = (ROOT_DIR / "tmp").resolve()
    if raw_path.is_absolute() or WINDOWS_ABSOLUTE_PATH_PATTERN.match(str(audio_file_path)):
        resolved = raw_path.resolve()
        if not resolved.is_relative_to(allowed_root):
            raise SpeakerDiarizationRuntimeError(
                "Absolute audio paths are not allowed. Use a file under tmp/."
            )
        return resolved

    resolved = (ROOT_DIR / raw_path).resolve()
    if not resolved.is_relative_to(allowed_root):
        raise SpeakerDiarizationRuntimeError(
            "Audio file path must stay under tmp/."
        )
    return resolved


def _prepare_audio_for_diarization(file_path: Path) -> Path:
    if file_path.suffix.lower() in {".wav", ".flac"}:
        return file_path

    converted_path = file_path.with_name(f"{file_path.stem}.diarize.wav")
    if (
        converted_path.exists()
        and converted_path.stat().st_mtime >= file_path.stat().st_mtime
    ):
        return converted_path

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(file_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(converted_path),
    ]
    try:
        completed = run_subprocess_killable(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            subprocess_timeout=60,
        )
    except subprocess.TimeoutExpired:
        if converted_path.exists():
            converted_path.unlink(missing_ok=True)
        raise SpeakerDiarizationRuntimeError(
            "ffmpeg audio conversion timed out after 60 seconds"
        )
    if completed.returncode != 0:
        message = (
            completed.stderr or completed.stdout or "ffmpeg conversion failed"
        ).strip()
        raise SpeakerDiarizationRuntimeError(
            f"Failed to prepare audio for diarization: {message}"
        )

    return converted_path


@lru_cache(maxsize=1)
def _get_diarization_pipeline() -> Any:
    token = get_env_str("PYANNOTE_AUTH_TOKEN")
    if not token:
        raise SpeakerDiarizationConfigurationError(
            "Speaker diarization requires PYANNOTE_AUTH_TOKEN in .env. "
            "Accept the pyannote speaker-diarization model license on Hugging Face first."
        )

    try:
        import torch  # type: ignore

        torch_version_module = import_module("torch.torch_version")
        torch_version_cls = getattr(torch_version_module, "TorchVersion")

        if hasattr(torch, "serialization") and hasattr(
            torch.serialization, "add_safe_globals"
        ):
            torch.serialization.add_safe_globals([torch_version_cls])

        from pyannote.audio import Pipeline  # type: ignore
    except ImportError as error:
        raise SpeakerDiarizationConfigurationError(
            "Speaker diarization requires the optional pyannote dependency. "
            "Install backend/requirements-diarization.txt in the backend virtualenv first."
        ) from error

    model_name = (
        get_env_str("PYANNOTE_DIARIZATION_MODEL") or "pyannote/speaker-diarization-3.1"
    )

    try:
        pipeline = Pipeline.from_pretrained(model_name, use_auth_token=token)
    except Exception as error:
        raise SpeakerDiarizationConfigurationError(
            f"Failed to load diarization pipeline '{model_name}': {error}"
        ) from error

    device_name = get_env_str("PYANNOTE_DEVICE")
    if device_name:
        try:
            import torch  # type: ignore

            pipeline.to(torch.device(device_name))
        except Exception as error:
            raise SpeakerDiarizationConfigurationError(
                f"Failed to move diarization pipeline to device '{device_name}': {error}"
            ) from error

    return pipeline


def _as_float(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0
