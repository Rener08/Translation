import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.services.content_chat_service import (
    ContentChatConfigurationError,
    ContentChatProviderError,
    answer_content_question,
)
from app.services.content_rewrite_service import (
    ContentRewriteEmptyOutputError,
    ContentRewriteConfigurationError,
    ContentRewriteInputError,
    ContentRewriteProviderError,
    rewrite_content,
)
from app.services.audio_download_service import AudioDownloadError
from app.services.caption_service import CaptionServiceError
from app.services.job_run_service import (
    JobRunError,
    run_video_job_with_translation_config,
)
from app.services.participant_candidate_service import extract_candidate_people
from app.services.session_history_service import (
    append_chat_exchange,
    list_session_history,
    load_session_history,
    record_rewrite_result,
    upsert_job_session,
)
from app.services.tmp_artifact_cleanup_service import cleanup_stale_tmp_artifacts
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
    LocalTranscriptionError,
    TranscriptionConfigurationError,
    transcribe_audio_file,
)
from app.services.translation_service import (
    TranslationConfigurationError,
    TranslationProviderError,
    discover_provider_models,
    translate_segments_to_chinese,
)
from app.services.video_source_service import fetch_video_source
from app.services.yt_dlp_service import (
    VideoInspectError,
    YtDlpNotInstalledError,
    inspect_video_metadata,
)
from app.youtube import (
    CandidatePersonResponse,
    ContentChatRequest,
    ContentChatResponse,
    ContentRewriteRequest,
    ContentRewriteResponse,
    DiarizeRequest,
    DiarizeResponse,
    DiarizedTranscriptSegmentResponse,
    JobRunRequest,
    JobRunResponse,
    JobTranscriptResponse,
    JobTranslationResponse,
    JobVideoResponse,
    ParseYouTubeRequest,
    ParseYouTubeResponse,
    ResolveSpeakersRequest,
    ResolveSpeakersResponse,
    ResolvedSpeakerMappingResponse,
    ResolvedTranscriptSegmentResponse,
    SessionHistoryDetailResponse,
    SessionHistoryListResponse,
    SessionHistorySummaryResponse,
    TranslateItemResponse,
    TranslateRequest,
    TranslateResponse,
    SpeakerTurnResponse,
    VideoChapterResponse,
    TranscriptSegmentResponse,
    TranscribeRequest,
    TranscribeResponse,
    VideoFetchSourceRequest,
    VideoFetchSourceResponse,
    VideoInspectRequest,
    VideoInspectResponse,
    VideoParticipantsRequest,
    VideoParticipantsResponse,
    parse_youtube_url,
)


logger = logging.getLogger(__name__)
app = FastAPI(title="YouTube Translator MVP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8090",
        "http://127.0.0.1:8090",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def cleanup_tmp_artifacts_on_startup() -> None:
    await run_in_threadpool(cleanup_stale_tmp_artifacts)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class ProviderModelsRequest(BaseModel):
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    base_url: str | None = None
    api_key: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


class ProviderModelsResponse(BaseModel):
    ok: bool
    provider: Literal["openai", "deepseek", "lmstudio", "ollama"]
    models: list[str]


@app.post("/api/provider-models", response_model=ProviderModelsResponse)
async def provider_models(
    request: ProviderModelsRequest,
) -> ProviderModelsResponse:
    try:
        models = await run_in_threadpool(
            discover_provider_models,
            provider=request.provider,
            base_url=request.base_url or "",
            api_key=request.api_key or "",
            extra_headers=request.extra_headers,
        )
    except TranslationConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except TranslationProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to discover provider models for %s", request.provider)
        raise HTTPException(
            status_code=502,
            detail="Failed to discover provider models.",
        ) from error
    return ProviderModelsResponse(ok=True, provider=request.provider, models=models)


@app.post("/api/parse-youtube", response_model=ParseYouTubeResponse)
async def parse_youtube(request: ParseYouTubeRequest) -> ParseYouTubeResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return ParseYouTubeResponse(
        ok=True,
        video_id=parsed.video_id,
        normalized_url=parsed.normalized_url,
    )


@app.post("/api/video/inspect", response_model=VideoInspectResponse)
async def inspect_video(request: VideoInspectRequest) -> VideoInspectResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        metadata = await run_in_threadpool(inspect_video_metadata, parsed.normalized_url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except YtDlpNotInstalledError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except VideoInspectError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to inspect video metadata: {error}",
        ) from error

    return VideoInspectResponse(
        ok=True,
        video_id=metadata.video_id,
        title=metadata.title,
        duration_sec=metadata.duration_sec,
        uploader=metadata.uploader,
        uploader_id=metadata.uploader_id,
        channel=metadata.channel,
        channel_id=metadata.channel_id,
        thumbnail=metadata.thumbnail,
        description=metadata.description,
        tags=metadata.tags,
        categories=metadata.categories,
        chapters=[
            VideoChapterResponse(
                start_time=chapter.start_time,
                end_time=chapter.end_time,
                title=chapter.title,
            )
            for chapter in metadata.chapters
        ],
        subtitles=metadata.subtitles,
        automatic_captions=metadata.automatic_captions,
    )


@app.post("/api/video/participants", response_model=VideoParticipantsResponse)
async def video_participants(
    request: VideoParticipantsRequest,
) -> VideoParticipantsResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        metadata = await run_in_threadpool(inspect_video_metadata, parsed.normalized_url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except YtDlpNotInstalledError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except VideoInspectError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to inspect video metadata: {error}",
        ) from error

    return VideoParticipantsResponse(
        ok=True,
        video_id=metadata.video_id,
        title=metadata.title,
        candidates=[
            CandidatePersonResponse(
                name=person.name,
                confidence=person.confidence,
                source_fields=person.source_fields,
                role_hints=person.role_hints,
                evidence=person.evidence,
            )
            for person in extract_candidate_people(metadata)
        ],
    )


@app.post("/api/video/resolve-speakers", response_model=ResolveSpeakersResponse)
async def resolve_video_speakers(
    request: ResolveSpeakersRequest,
) -> ResolveSpeakersResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        metadata = await run_in_threadpool(
            inspect_video_metadata, parsed.normalized_url
        )
        source = await run_in_threadpool(
            fetch_video_source,
            parsed.normalized_url,
            source_mode="force_audio",
        )
        if source.source_type != "audio" or not source.audio_file_path:
            raise VideoInspectError("Speaker resolution requires an audio source.")
        transcript = await run_in_threadpool(
            transcribe_audio_file, source.audio_file_path
        )
        diarization = await run_in_threadpool(
            diarize_audio_file, source.audio_file_path
        )
        diarized_transcript = await run_in_threadpool(
            assign_speakers_to_transcript, transcript, diarization
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except AudioFileNotFoundError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (
        TranscriptionConfigurationError,
        SpeakerDiarizationConfigurationError,
    ) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except YtDlpNotInstalledError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except (
        AudioDownloadError,
        CaptionServiceError,
        LocalTranscriptionError,
        SpeakerDiarizationRuntimeError,
        VideoInspectError,
    ) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    candidates = extract_candidate_people(metadata)
    speaker_mappings = resolve_speaker_identities(diarized_transcript, candidates)
    resolved_transcript = apply_speaker_identities(
        diarized_transcript, speaker_mappings
    )

    return ResolveSpeakersResponse(
        ok=True,
        video_id=metadata.video_id,
        title=metadata.title,
        audio_file_path=source.audio_file_path,
        speaker_count=diarization.speaker_count,
        candidates=[
            CandidatePersonResponse(
                name=person.name,
                confidence=person.confidence,
                source_fields=person.source_fields,
                role_hints=person.role_hints,
                evidence=person.evidence,
            )
            for person in candidates
        ],
        speaker_mappings=[
            ResolvedSpeakerMappingResponse(
                speaker_id=item.speaker_id,
                speaker=item.display_name,
                matched_candidate=item.matched_candidate,
                confidence=item.confidence,
                evidence=item.evidence,
            )
            for item in speaker_mappings
        ],
        segments=[
            ResolvedTranscriptSegmentResponse(
                index=segment.index,
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker_id=diarized_transcript.segments[index].speaker,
                speaker=segment.speaker,
            )
            for index, segment in enumerate(resolved_transcript.segments)
        ],
    )


@app.post("/api/video/fetch-source", response_model=VideoFetchSourceResponse)
async def fetch_source(request: VideoFetchSourceRequest) -> VideoFetchSourceResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        source = await run_in_threadpool(
            fetch_video_source,
            parsed.normalized_url,
            source_mode=request.source_mode,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except YtDlpNotInstalledError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except (CaptionServiceError, AudioDownloadError, VideoInspectError) as error:
        logger.error("Failed to fetch source: %s", error)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch video source: {error}",
        ) from error

    return VideoFetchSourceResponse(
        ok=True,
        source_type=source.source_type,
        language=source.language,
        text=source.text,
        audio_file_path=source.audio_file_path,
    )


@app.post(
    "/api/transcribe",
    response_model=TranscribeResponse,
    response_model_exclude_none=True,
)
async def transcribe_audio(request: TranscribeRequest) -> TranscribeResponse:
    try:
        result = await run_in_threadpool(
            transcribe_audio_file, request.audio_file_path
        )
    except AudioFileNotFoundError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except TranscriptionConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except LocalTranscriptionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return TranscribeResponse(
        ok=True,
        language=result.language,
        text=result.text,
        segments=[
            TranscriptSegmentResponse(
                index=segment.index,
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=segment.speaker,
            )
            for segment in result.segments
        ],
    )


@app.post("/api/diarize", response_model=DiarizeResponse)
async def diarize_audio(request: DiarizeRequest) -> DiarizeResponse:
    try:
        transcript = await run_in_threadpool(
            transcribe_audio_file, request.audio_file_path
        )
        diarization = await run_in_threadpool(
            diarize_audio_file, request.audio_file_path
        )
        aligned_transcript = await run_in_threadpool(
            assign_speakers_to_transcript, transcript, diarization
        )
    except AudioFileNotFoundError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (
        TranscriptionConfigurationError,
        SpeakerDiarizationConfigurationError,
    ) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except (LocalTranscriptionError, SpeakerDiarizationRuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return DiarizeResponse(
        ok=True,
        language=aligned_transcript.language,
        text=aligned_transcript.text,
        speaker_count=diarization.speaker_count,
        turns=[
            SpeakerTurnResponse(
                start=turn.start,
                end=turn.end,
                speaker=turn.speaker,
            )
            for turn in diarization.turns
        ],
        segments=[
            DiarizedTranscriptSegmentResponse(
                index=segment.index,
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=segment.speaker,
            )
            for segment in aligned_transcript.segments
        ],
    )


@app.post("/api/translate", response_model=TranslateResponse)
async def translate_segments(request: TranslateRequest) -> TranslateResponse:
    try:
        translations = await run_in_threadpool(
            translate_segments_to_chinese,
            [segment.model_dump() for segment in request.segments],
            translation_config=(
                request.translation_config.model_dump()
                if request.translation_config
                else None
            ),
        )
    except TranslationConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except TranslationProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return TranslateResponse(
        ok=True,
        translations=[
            TranslateItemResponse(
                index=item.index,
                start=item.start,
                end=item.end,
                source_text=item.source_text,
                translated_text=item.translated_text,
            )
            for item in translations
        ],
    )


@app.post("/api/content-chat", response_model=ContentChatResponse)
async def content_chat(request: ContentChatRequest) -> ContentChatResponse:
    try:
        result = await run_in_threadpool(
            answer_content_question,
            content_context_id=request.content_context_id,
            video_title=request.video_title,
            transcript_en=request.transcript_en,
            translation_zh=request.translation_zh,
            question=request.question,
            messages=[message.model_dump() for message in request.messages],
            chat_config=(
                request.chat_config.model_dump() if request.chat_config else None
            ),
        )
    except ContentChatConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except ContentChatProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    if request.content_context_id:
        try:
            await run_in_threadpool(
                append_chat_exchange,
                content_context_id=request.content_context_id,
                question=request.question,
                answer=result.answer,
            )
        except Exception:
            logger.warning(
                "Failed to persist chat history for %s",
                request.content_context_id,
            )

    return ContentChatResponse(
        ok=True,
        provider=result.provider,
        model=result.model,
        answer=result.answer,
    )


@app.get("/api/session-history", response_model=SessionHistoryListResponse)
async def session_history(limit: int = 20) -> SessionHistoryListResponse:
    return SessionHistoryListResponse(
        ok=True,
        items=[
            SessionHistorySummaryResponse.model_validate(item)
            for item in list_session_history(limit=limit)
        ],
    )


@app.get(
    "/api/session-history/{content_context_id}",
    response_model=SessionHistoryDetailResponse,
)
async def session_history_detail(content_context_id: str) -> SessionHistoryDetailResponse:
    payload = load_session_history(content_context_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session history not found.")

    return SessionHistoryDetailResponse.model_validate(payload)


@app.post("/api/content-rewrite", response_model=ContentRewriteResponse)
async def content_rewrite(request: ContentRewriteRequest) -> ContentRewriteResponse:
    try:
        rewrite_config = (
            request.translation_config.model_dump()
            if request.translation_config
            else None
        )
        result = await run_in_threadpool(
            rewrite_content,
            source_text=request.source_text,
            rewrite_focus=request.rewrite_focus,
            rewrite_config=rewrite_config,
        )
    except ContentRewriteInputError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ContentRewriteConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except ContentRewriteEmptyOutputError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ContentRewriteProviderError as error:
        raise HTTPException(
            status_code=502,
            detail=f"内容改写失败：上游模型服务返回错误。{error}",
        ) from error

    if request.content_context_id:
        try:
            quality_issues = list(getattr(result, "quality_issues", ()) or [])
            await run_in_threadpool(
                record_rewrite_result,
                content_context_id=request.content_context_id,
                rewrite_focus=request.rewrite_focus,
                rewrite_source_text=request.source_text,
                rewritten_text=result.rewritten_text,
                rewrite_quality_issues=quality_issues,
                rewrite_provider=result.provider,
                rewrite_model=result.model,
            )
        except Exception:
            logger.warning(
                "Failed to persist rewrite history for %s",
                request.content_context_id,
            )

    return ContentRewriteResponse(
        ok=True,
        provider=result.provider,
        model=result.model,
        rewritten_text=result.rewritten_text,
        quality_issues=list(getattr(result, "quality_issues", ()) or []),
    )


@app.post(
    "/api/jobs/run", response_model=JobRunResponse, response_model_exclude_none=True
)
async def run_job(request: JobRunRequest) -> JobRunResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        translation_config = (
            request.translation_config.model_dump()
            if request.translation_config
            else None
        )
        result = await run_in_threadpool(
            run_video_job_with_translation_config,
            parsed.normalized_url,
            source_mode=request.source_mode,
            translation_config=translation_config,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except AudioFileNotFoundError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (TranscriptionConfigurationError, TranslationConfigurationError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except YtDlpNotInstalledError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except (
        AudioDownloadError,
        CaptionServiceError,
        JobRunError,
        LocalTranscriptionError,
        TranslationProviderError,
        VideoInspectError,
    ) as error:
        logger.error("Job run failed for %s: %s", request.url, error)
        raise HTTPException(status_code=502, detail=str(error)) from error

    try:
        await run_in_threadpool(
            upsert_job_session,
            content_context_id=result.content_context_id,
            video_id=result.video.video_id,
            video_url=parsed.normalized_url,
            video_title=result.video.title,
            video_duration_sec=result.video.duration_sec,
            video_uploader=result.video.uploader,
            video_thumbnail=result.video.thumbnail,
            source_mode=request.source_mode,
            source_type=result.source_type,
            translation_provider=(
                request.translation_config.provider
                if request.translation_config
                else None
            ),
            translation_model=(
                request.translation_config.model if request.translation_config else None
            ),
            transcript_en_text=result.transcript_en.text,
            transcript_en_segments=[
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "speaker": segment.speaker,
                }
                for segment in result.transcript_en.segments
            ],
            translation_zh_text="\n".join(
                item.translated_text.strip()
                for item in result.translation_zh_segments
                if item.translated_text.strip()
            ),
            translation_zh_segments=[
                {
                    "index": item.index,
                    "start": item.start,
                    "end": item.end,
                    "source_text": item.source_text,
                    "translated_text": item.translated_text,
                }
                for item in result.translation_zh_segments
            ],
        )
    except Exception:
        logger.warning("Failed to persist session history for %s", request.url)

    return JobRunResponse(
        ok=True,
        video=JobVideoResponse(
            video_id=result.video.video_id,
            title=result.video.title,
            thumbnail=result.video.thumbnail,
            duration_sec=result.video.duration_sec,
            uploader=result.video.uploader,
        ),
        source_type=result.source_type,
        transcript_en=JobTranscriptResponse(
            text=result.transcript_en.text,
            segments=[
                TranscriptSegmentResponse(
                    index=segment.index,
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    speaker=segment.speaker,
                )
                for segment in result.transcript_en.segments
            ],
        ),
        translation_zh=JobTranslationResponse(
            segments=[
                TranslateItemResponse(
                    index=item.index,
                    start=item.start,
                    end=item.end,
                    source_text=item.source_text,
                    translated_text=item.translated_text,
                )
                for item in result.translation_zh_segments
            ]
        ),
        content_context_id=result.content_context_id,
    )
