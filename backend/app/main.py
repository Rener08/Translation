from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.api import build_api_router
from app.services.content_chat_service import answer_content_question
from app.services.content_rewrite_service import rewrite_content
from app.services.job_run_service import run_video_job_with_translation_config
from app.services.speaker_diarization_service import diarize_audio_file
from app.services.tmp_artifact_cleanup_service import cleanup_stale_tmp_artifacts
from app.services.transcription_service import transcribe_audio_file
from app.services.translation_service import discover_provider_models, translate_segments_to_chinese
from app.services.video_source_service import fetch_video_source
from app.services.yt_dlp_service import inspect_video_metadata


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await run_in_threadpool(cleanup_stale_tmp_artifacts)
    yield


app = FastAPI(title="YouTube Translator MVP API", lifespan=lifespan)

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

app.include_router(build_api_router())

# Backward-compatible symbol exports for tests and monkeypatch targets.
__all__ = [
    "app",
    "answer_content_question",
    "rewrite_content",
    "run_video_job_with_translation_config",
    "transcribe_audio_file",
    "diarize_audio_file",
    "inspect_video_metadata",
    "fetch_video_source",
    "translate_segments_to_chinese",
    "discover_provider_models",
]
