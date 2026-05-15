from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.content_chat_service import answer_content_question
from app.services.content_rewrite_service import rewrite_content
from app.services.job_run_service import run_video_job_with_translation_config
from app.services.speaker_diarization_service import diarize_audio_file
from app.services.transcription_service import transcribe_audio_file
from app.services.translation_service import discover_provider_models, translate_segments_to_chinese
from app.services.video_source_service import fetch_video_source
from app.services.writer_agent_service import run_writer_agent
from app.services.yt_dlp_service import inspect_video_metadata


@dataclass
class ServiceBindings:
    inspect_video_metadata: Any
    fetch_video_source: Any
    transcribe_audio_file: Any
    diarize_audio_file: Any
    translate_segments_to_chinese: Any
    answer_content_question: Any
    run_writer_agent: Any
    discover_provider_models: Any
    run_video_job_with_translation_config: Any
    rewrite_content: Any


service_bindings = ServiceBindings(
    inspect_video_metadata=inspect_video_metadata,
    fetch_video_source=fetch_video_source,
    transcribe_audio_file=transcribe_audio_file,
    diarize_audio_file=diarize_audio_file,
    translate_segments_to_chinese=translate_segments_to_chinese,
    answer_content_question=answer_content_question,
    run_writer_agent=run_writer_agent,
    discover_provider_models=discover_provider_models,
    run_video_job_with_translation_config=run_video_job_with_translation_config,
    rewrite_content=rewrite_content,
)

