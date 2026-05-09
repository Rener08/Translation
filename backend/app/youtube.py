from typing import Literal
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


SourceMode = Literal["subtitle_first", "force_audio"]


class ParseYouTubeRequest(BaseModel):
    url: HttpUrl


class ParseYouTubeResponse(BaseModel):
    ok: bool
    video_id: str
    normalized_url: str


class VideoInspectRequest(BaseModel):
    url: HttpUrl


class VideoParticipantsRequest(BaseModel):
    url: HttpUrl


class ResolveSpeakersRequest(BaseModel):
    url: HttpUrl


class VideoChapterResponse(BaseModel):
    start_time: float
    end_time: float | None = None
    title: str


class VideoInspectResponse(BaseModel):
    ok: bool
    video_id: str
    title: str
    duration_sec: int | None = None
    uploader: str | None = None
    uploader_id: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    thumbnail: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    chapters: list[VideoChapterResponse] = Field(default_factory=list)
    subtitles: list[str] = Field(default_factory=list)
    automatic_captions: list[str] = Field(default_factory=list)


class CandidatePersonResponse(BaseModel):
    name: str
    confidence: Literal["high", "medium", "low"]
    source_fields: list[str] = Field(default_factory=list)
    role_hints: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class VideoParticipantsResponse(BaseModel):
    ok: bool
    video_id: str
    title: str
    candidates: list[CandidatePersonResponse] = Field(default_factory=list)


class ResolvedSpeakerMappingResponse(BaseModel):
    speaker_id: str
    speaker: str
    matched_candidate: str | None = None
    confidence: Literal["high", "medium", "low", "unknown"]
    evidence: list[str] = Field(default_factory=list)


class ResolvedTranscriptSegmentResponse(BaseModel):
    index: int
    start: float
    end: float
    text: str
    speaker_id: str | None = None
    speaker: str | None = None


class ResolveSpeakersResponse(BaseModel):
    ok: bool
    video_id: str
    title: str
    audio_file_path: str
    speaker_count: int
    candidates: list[CandidatePersonResponse] = Field(default_factory=list)
    speaker_mappings: list[ResolvedSpeakerMappingResponse] = Field(default_factory=list)
    segments: list[ResolvedTranscriptSegmentResponse] = Field(default_factory=list)


class VideoFetchSourceRequest(BaseModel):
    url: HttpUrl
    source_mode: SourceMode = "subtitle_first"


class VideoFetchSourceResponse(BaseModel):
    ok: bool
    source_type: Literal["captions", "audio"]
    language: str | None = None
    text: str | None = None
    audio_file_path: str | None = None


class TranscribeRequest(BaseModel):
    audio_file_path: str


class DiarizeRequest(BaseModel):
    audio_file_path: str


class TranscriptSegmentResponse(BaseModel):
    index: int
    start: float
    end: float
    text: str
    speaker: str | None = None


class SpeakerTurnResponse(BaseModel):
    start: float
    end: float
    speaker: str


class DiarizedTranscriptSegmentResponse(BaseModel):
    index: int
    start: float
    end: float
    text: str
    speaker: str | None = None


class TranscribeResponse(BaseModel):
    ok: bool
    language: str
    text: str
    segments: list[TranscriptSegmentResponse] = Field(default_factory=list)


class DiarizeResponse(BaseModel):
    ok: bool
    language: str
    text: str
    speaker_count: int
    turns: list[SpeakerTurnResponse] = Field(default_factory=list)
    segments: list[DiarizedTranscriptSegmentResponse] = Field(default_factory=list)


class TranslationConfigRequest(BaseModel):
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"] = "openai"
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


class ChatConfigRequest(BaseModel):
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"] = "ollama"
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    custom_prompt: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


class TranslateSegmentRequest(BaseModel):
    index: int
    start: float
    end: float
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Segment text must not be empty.")
        return value


class TranslateRequest(BaseModel):
    segments: list[TranslateSegmentRequest] = Field(min_length=1)
    translation_config: TranslationConfigRequest | None = None


class TranslateItemResponse(BaseModel):
    index: int
    start: float
    end: float
    source_text: str
    translated_text: str


class TranslateResponse(BaseModel):
    ok: bool
    translations: list[TranslateItemResponse] = Field(default_factory=list)


class JobRunRequest(BaseModel):
    url: HttpUrl
    source_mode: SourceMode = "subtitle_first"
    translation_config: TranslationConfigRequest | None = None


class JobVideoResponse(BaseModel):
    video_id: str
    title: str
    thumbnail: str | None = None
    duration_sec: int | None = None
    uploader: str | None = None


class JobTranscriptResponse(BaseModel):
    text: str
    segments: list[TranscriptSegmentResponse] = Field(default_factory=list)


class JobTranslationResponse(BaseModel):
    segments: list[TranslateItemResponse] = Field(default_factory=list)


class JobRunResponse(BaseModel):
    ok: bool
    video: JobVideoResponse
    source_type: Literal["captions", "audio"]
    transcript_en: JobTranscriptResponse
    translation_zh: JobTranslationResponse
    content_context_id: str


class JobRunStatusResponse(BaseModel):
    ok: bool
    job_id: str
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    progress_value: int = 0
    progress_text: str | None = None
    stage: Literal["inspect", "fetch_source", "transcribe", "translate", "persist"] | None = None
    started_at: str | None = None
    updated_at: str | None = None
    timeout_sec: int | None = None
    result: JobRunResponse | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool | None = None


class ProviderModelsRequest(BaseModel):
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    base_url: str | None = None
    api_key: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


class ProviderModelsResponse(BaseModel):
    ok: bool
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    models: list[str]


class ProviderTestConnectionRequest(BaseModel):
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


class ProviderTestConnectionResponse(BaseModel):
    ok: bool
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    reachable: bool
    selected_model: str | None = None
    discovered_models: list[str] = Field(default_factory=list)
    message: str


class ContentChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Chat message content must not be empty.")
        return value


class ContentChatRequest(BaseModel):
    content_context_id: str | None = None
    video_title: str | None = None
    transcript_en: str | None = None
    translation_zh: str | None = None
    question: str
    messages: list[ContentChatMessageRequest] = Field(default_factory=list)
    chat_config: ChatConfigRequest | None = None

    @field_validator("question")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be empty.")
        return value

    @model_validator(mode="after")
    def validate_context_inputs(self) -> "ContentChatRequest":
        if self.content_context_id and self.content_context_id.strip():
            return self

        if not str(self.transcript_en or "").strip():
            raise ValueError("transcript_en must not be empty when content_context_id is missing.")
        if not str(self.translation_zh or "").strip():
            raise ValueError("translation_zh must not be empty when content_context_id is missing.")
        return self


class ContentChatResponse(BaseModel):
    ok: bool
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    model: str
    answer: str


class ContentRewriteRequest(BaseModel):
    source_text: str
    rewrite_focus: str | None = Field(
        default=None,
        description=(
            "Rewrite instruction precedence: if this contains '{{transcript}}', "
            "backend treats it as a full writing prompt and injects source_text directly. "
            "Otherwise backend falls back to its managed rewrite references and routing."
        ),
    )
    translation_config: TranslationConfigRequest | None = None
    content_context_id: str | None = None

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_text must not be empty.")
        return value


class ContentRewriteResponse(BaseModel):
    ok: bool
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    model: str
    rewritten_text: str
    quality_issues: list[str] = Field(default_factory=list)


class SessionHistoryTurnResponse(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str


class SessionHistorySummaryResponse(BaseModel):
    content_context_id: str
    video_id: str | None = None
    video_url: str | None = None
    video_title: str | None = None
    video_duration_sec: int | None = None
    video_uploader: str | None = None
    video_thumbnail: str | None = None
    source_mode: SourceMode | None = None
    source_type: Literal["captions", "audio"] | None = None
    created_at: str
    updated_at: str
    has_rewrite: bool
    chat_turn_count: int
    transcript_preview: str = ""
    translation_preview: str = ""
    rewritten_preview: str = ""
    rewrite_quality_issue_count: int = 0


class SessionHistoryDetailResponse(BaseModel):
    content_context_id: str
    video_id: str | None = None
    video_url: str | None = None
    video_title: str | None = None
    video_duration_sec: int | None = None
    video_uploader: str | None = None
    video_thumbnail: str | None = None
    source_mode: SourceMode | None = None
    source_type: Literal["captions", "audio"] | None = None
    created_at: str
    updated_at: str
    translation_provider: str | None = None
    translation_model: str | None = None
    transcript_en_text: str = ""
    transcript_en_segments: list[TranscriptSegmentResponse] = Field(default_factory=list)
    translation_zh_text: str = ""
    translation_zh_segments: list[TranslateItemResponse] = Field(default_factory=list)
    rewrite_focus: str | None = None
    rewrite_source_text: str = ""
    rewritten_text: str = ""
    rewrite_quality_issues: list[str] = Field(default_factory=list)
    rewrite_provider: str | None = None
    rewrite_model: str | None = None
    chat_turns: list[SessionHistoryTurnResponse] = Field(default_factory=list)


class SessionHistoryListResponse(BaseModel):
    ok: bool
    items: list[SessionHistorySummaryResponse] = Field(default_factory=list)


class SystemExportLogsResponse(BaseModel):
    ok: bool
    archive_path: str
    included_files: list[str] = Field(default_factory=list)


class ParsedYouTubeUrl(BaseModel):
    video_id: str
    normalized_url: str


def parse_youtube_url(raw_url: str) -> ParsedYouTubeUrl:
    parsed_url = urlparse(raw_url)
    host = parsed_url.netloc.lower()
    path = parsed_url.path

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = path.lstrip("/").split("/")[0]
    elif host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }:
        if path == "/watch":
            video_id = parse_qs(parsed_url.query).get("v", [""])[0]
        elif path.startswith("/shorts/") or path.startswith("/live/") or path.startswith("/embed/"):
            parts = [part for part in path.split("/") if part]
            video_id = parts[1] if len(parts) >= 2 else ""
        else:
            raise ValueError("Unsupported YouTube URL format.")
    else:
        raise ValueError("URL must be a valid YouTube link.")

    if not video_id:
        raise ValueError("Could not find a YouTube video_id in the URL.")

    return ParsedYouTubeUrl(
        video_id=video_id,
        normalized_url=f"https://www.youtube.com/watch?v={video_id}",
    )
