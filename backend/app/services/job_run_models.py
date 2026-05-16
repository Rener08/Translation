from dataclasses import dataclass, field
from typing import Callable, Literal

from app.services.transcription_service import TranscriptionResult
from app.services.translation_service import TranslationSegment
from app.services.video_source_service import SourceMode, VideoSourceResult
from app.services.yt_dlp_service import VideoMetadata


JobStage = Literal["inspect", "fetch_source", "transcribe", "persist"]
JobProgressCallback = Callable[[JobStage, int, str], None]
JobCancellationChecker = Callable[[], bool]


@dataclass(frozen=True)
class JobStageTimeouts:
    inspect: int = 45
    fetch_source: int = 180
    transcribe: int = 900
    persist: int = 30

    def for_stage(self, stage: JobStage) -> int:
        if stage == "inspect":
            return self.inspect
        if stage == "fetch_source":
            return self.fetch_source
        if stage == "transcribe":
            return self.transcribe
        if stage == "persist":
            return self.persist
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
    content_context_id: str
    translation_zh_segments: list[TranslationSegment] = field(default_factory=list)


@dataclass(frozen=True)
class JobRunStageContext:
    url: str
    translation_config: dict[str, object] | None
    source_mode: SourceMode
    stage_timeouts: JobStageTimeouts
    progress_callback: JobProgressCallback
    cancellation_checker: JobCancellationChecker | None
    account_id: str | None = None


@dataclass(frozen=True)
class JobRunPipelineState:
    context: JobRunStageContext
    video_info: dict[str, object] | None = None
    video: VideoMetadata | None = None
    source: VideoSourceResult | None = None
    transcript: TranscriptionResult | None = None
    content_context_id: str | None = None


@dataclass(frozen=True)
class InspectStageOutput:
    video_info: dict[str, object]
    video: VideoMetadata


@dataclass(frozen=True)
class FetchSourceStageOutput:
    source: VideoSourceResult


@dataclass(frozen=True)
class TranscribeStageOutput:
    transcript: TranscriptionResult


@dataclass(frozen=True)
class PersistStageOutput:
    content_context_id: str
