from __future__ import annotations


def get_inspect_video_metadata():
    from app import main as app_main

    return app_main.inspect_video_metadata


def get_fetch_video_source():
    from app import main as app_main

    return app_main.fetch_video_source


def get_transcribe_audio_file():
    from app import main as app_main

    return app_main.transcribe_audio_file


def get_diarize_audio_file():
    from app import main as app_main

    return app_main.diarize_audio_file


def get_translate_segments_to_chinese():
    from app import main as app_main

    return app_main.translate_segments_to_chinese


def get_answer_content_question():
    from app import main as app_main

    return app_main.answer_content_question


def get_run_writer_agent():
    from app import main as app_main

    return app_main.run_writer_agent


def get_discover_provider_models():
    from app import main as app_main

    return app_main.discover_provider_models


def get_run_video_job_runner():
    from app import main as app_main

    return app_main.run_video_job_with_translation_config
