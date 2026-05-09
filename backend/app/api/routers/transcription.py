from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.api.error_mapping import raise_mapped_http_exception
from app.api.runtime_deps import resolve
from app.services.speaker_diarization_service import assign_speakers_to_transcript, diarize_audio_file
from app.services.transcription_service import transcribe_audio_file
from app.youtube import (
    DiarizeRequest,
    DiarizeResponse,
    DiarizedTranscriptSegmentResponse,
    SpeakerTurnResponse,
    TranscriptSegmentResponse,
    TranscribeRequest,
    TranscribeResponse,
)


router = APIRouter()


@router.post(
    "/api/transcribe",
    response_model=TranscribeResponse,
    response_model_exclude_none=True,
)
async def transcribe_audio(request: TranscribeRequest) -> TranscribeResponse:
    try:
        result = await run_in_threadpool(
            resolve("transcribe_audio_file", transcribe_audio_file),
            request.audio_file_path,
        )
    except Exception as error:
        raise_mapped_http_exception(error)

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


@router.post("/api/diarize", response_model=DiarizeResponse)
async def diarize_audio(request: DiarizeRequest) -> DiarizeResponse:
    try:
        transcript = await run_in_threadpool(
            resolve("transcribe_audio_file", transcribe_audio_file),
            request.audio_file_path,
        )
        diarization = await run_in_threadpool(
            resolve("diarize_audio_file", diarize_audio_file),
            request.audio_file_path,
        )
        aligned_transcript = await run_in_threadpool(
            assign_speakers_to_transcript, transcript, diarization
        )
    except Exception as error:
        raise_mapped_http_exception(error)

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
