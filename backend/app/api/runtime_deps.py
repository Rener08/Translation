from __future__ import annotations

from app.service_bindings import service_bindings


def get_inspect_video_metadata():
    return service_bindings.inspect_video_metadata


def get_fetch_video_source():
    return service_bindings.fetch_video_source


def get_transcribe_audio_file():
    return service_bindings.transcribe_audio_file


def get_diarize_audio_file():
    return service_bindings.diarize_audio_file


def get_translate_segments_to_chinese():
    return service_bindings.translate_segments_to_chinese


def get_answer_content_question():
    return service_bindings.answer_content_question


def get_run_writer_agent():
    return service_bindings.run_writer_agent


def get_discover_provider_models():
    return service_bindings.discover_provider_models


def get_run_video_job_runner():
    return service_bindings.run_video_job_with_translation_config


def get_run_uploaded_audio_job_runner():
    return service_bindings.run_uploaded_audio_job_with_translation_config
