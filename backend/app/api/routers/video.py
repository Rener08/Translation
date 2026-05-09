from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.api.error_mapping import raise_mapped_http_exception
from app.api.runtime_deps import resolve
from app.services.participant_candidate_service import extract_candidate_people
from app.services.speaker_diarization_service import assign_speakers_to_transcript, diarize_audio_file
from app.services.speaker_identity_service import apply_speaker_identities, resolve_speaker_identities
from app.services.transcription_service import transcribe_audio_file
from app.services.video_source_service import fetch_video_source
from app.services.yt_dlp_service import VideoInspectError, inspect_video_metadata
from app.youtube import (
    CandidatePersonResponse,
    ParseYouTubeRequest,
    ParseYouTubeResponse,
    ResolveSpeakersRequest,
    ResolveSpeakersResponse,
    ResolvedSpeakerMappingResponse,
    ResolvedTranscriptSegmentResponse,
    VideoChapterResponse,
    VideoFetchSourceRequest,
    VideoFetchSourceResponse,
    VideoInspectRequest,
    VideoInspectResponse,
    VideoParticipantsRequest,
    VideoParticipantsResponse,
    parse_youtube_url,
)


router = APIRouter()


@router.post("/api/parse-youtube", response_model=ParseYouTubeResponse)
async def parse_youtube(request: ParseYouTubeRequest) -> ParseYouTubeResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
    except Exception as error:
        raise_mapped_http_exception(error)

    return ParseYouTubeResponse(
        ok=True,
        video_id=parsed.video_id,
        normalized_url=parsed.normalized_url,
    )


@router.post("/api/video/inspect", response_model=VideoInspectResponse)
async def inspect_video(request: VideoInspectRequest) -> VideoInspectResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        metadata = await run_in_threadpool(
            resolve("inspect_video_metadata", inspect_video_metadata),
            parsed.normalized_url,
        )
    except VideoInspectError as error:
        raise_mapped_http_exception(
            VideoInspectError(f"Failed to inspect video metadata: {error}")
        )
    except Exception as error:
        raise_mapped_http_exception(error)

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


@router.post("/api/video/participants", response_model=VideoParticipantsResponse)
async def video_participants(
    request: VideoParticipantsRequest,
) -> VideoParticipantsResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        metadata = await run_in_threadpool(
            resolve("inspect_video_metadata", inspect_video_metadata),
            parsed.normalized_url,
        )
    except VideoInspectError as error:
        raise_mapped_http_exception(
            VideoInspectError(f"Failed to inspect video metadata: {error}")
        )
    except Exception as error:
        raise_mapped_http_exception(error)

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


@router.post("/api/video/resolve-speakers", response_model=ResolveSpeakersResponse)
async def resolve_video_speakers(
    request: ResolveSpeakersRequest,
) -> ResolveSpeakersResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        metadata = await run_in_threadpool(
            resolve("inspect_video_metadata", inspect_video_metadata),
            parsed.normalized_url,
        )
        source = await run_in_threadpool(
            resolve("fetch_video_source", fetch_video_source),
            parsed.normalized_url,
            source_mode="force_audio",
        )
        if source.source_type != "audio" or not source.audio_file_path:
            raise ValueError("Speaker resolution requires an audio source.")
        transcript = await run_in_threadpool(
            resolve("transcribe_audio_file", transcribe_audio_file),
            source.audio_file_path,
        )
        diarization = await run_in_threadpool(
            resolve("diarize_audio_file", diarize_audio_file),
            source.audio_file_path,
        )
        diarized_transcript = await run_in_threadpool(
            assign_speakers_to_transcript, transcript, diarization
        )
    except Exception as error:
        raise_mapped_http_exception(error)

    candidates = extract_candidate_people(metadata)
    speaker_mappings = resolve_speaker_identities(diarized_transcript, candidates)
    resolved_transcript = apply_speaker_identities(diarized_transcript, speaker_mappings)

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


@router.post("/api/video/fetch-source", response_model=VideoFetchSourceResponse)
async def fetch_source(request: VideoFetchSourceRequest) -> VideoFetchSourceResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
        source = await run_in_threadpool(
            resolve("fetch_video_source", fetch_video_source),
            parsed.normalized_url,
            source_mode=request.source_mode,
        )
    except Exception as error:
        raise_mapped_http_exception(error)

    return VideoFetchSourceResponse(
        ok=True,
        source_type=source.source_type,
        language=source.language,
        text=source.text,
        audio_file_path=source.audio_file_path,
    )
