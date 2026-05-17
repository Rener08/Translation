from __future__ import annotations

from typing import Any

from app.repositories.session_repository import (
    SAFE_CONTEXT_ID_PATTERN,
    SESSION_HISTORY_NAMESPACE,
    default_session_repository,
)


__all__ = [
    "SESSION_HISTORY_NAMESPACE",
    "SAFE_CONTEXT_ID_PATTERN",
    "append_chat_exchange",
    "list_session_history",
    "load_session_history",
    "record_rewrite_failure",
    "record_rewrite_result",
    "upsert_job_session",
]


def upsert_job_session(
    *,
    content_context_id: str,
    account_id: str | None = None,
    video_id: str,
    video_url: str,
    video_title: str,
    video_duration_sec: int | None = None,
    video_uploader: str | None = None,
    video_thumbnail: str | None = None,
    source_mode: str,
    source_type: str,
    translation_provider: str | None,
    translation_model: str | None,
    translation_base_url: str | None = None,
    skill_config_name: str | None = None,
    transcript_en_text: str,
    transcript_en_segments: list[dict[str, Any]],
    translation_zh_text: str,
    translation_zh_segments: list[dict[str, Any]],
) -> None:
    default_session_repository.upsert_job_session(
        content_context_id=content_context_id,
        account_id=account_id,
        video_id=video_id,
        video_url=video_url,
        video_title=video_title,
        video_duration_sec=video_duration_sec,
        video_uploader=video_uploader,
        video_thumbnail=video_thumbnail,
        source_mode=source_mode,
        source_type=source_type,
        translation_provider=translation_provider,
        translation_model=translation_model,
        translation_base_url=translation_base_url,
        skill_config_name=skill_config_name,
        transcript_en_text=transcript_en_text,
        transcript_en_segments=transcript_en_segments,
        translation_zh_text=translation_zh_text,
        translation_zh_segments=translation_zh_segments,
    )


def record_rewrite_result(
    *,
    content_context_id: str,
    rewrite_style: str | None = None,
    rewrite_focus: str | None,
    rewrite_source_text: str,
    rewritten_text: str,
    rewrite_quality_issues: list[str] | None = None,
    rewrite_detail_coverage_issues: list[str] | None = None,
    rewrite_provider: str,
    rewrite_model: str,
    translation_base_url: str | None = None,
    skill_config_name: str | None = None,
    writer_trace_id: str | None = None,
    writer_policy_version: str | None = None,
    writer_prompt_version: str | None = None,
) -> None:
    default_session_repository.record_rewrite_result(
        content_context_id=content_context_id,
        rewrite_style=rewrite_style,
        rewrite_focus=rewrite_focus,
        rewrite_source_text=rewrite_source_text,
        rewritten_text=rewritten_text,
        rewrite_quality_issues=rewrite_quality_issues,
        rewrite_detail_coverage_issues=rewrite_detail_coverage_issues,
        rewrite_provider=rewrite_provider,
        rewrite_model=rewrite_model,
        translation_base_url=translation_base_url,
        skill_config_name=skill_config_name,
        writer_trace_id=writer_trace_id,
        writer_policy_version=writer_policy_version,
        writer_prompt_version=writer_prompt_version,
    )


def record_rewrite_failure(
    *,
    content_context_id: str,
    rewrite_style: str | None = None,
    rewrite_focus: str | None,
    rewrite_source_text: str,
    rewrite_provider: str | None = None,
    rewrite_model: str | None = None,
    translation_base_url: str | None = None,
    skill_config_name: str | None = None,
    rewrite_failure_error_code: str | None = None,
    rewrite_failure_message: str | None = None,
    rewrite_failure_retryable: bool | None = None,
    rewrite_failure_details: list[str] | None = None,
) -> None:
    default_session_repository.record_rewrite_failure(
        content_context_id=content_context_id,
        rewrite_style=rewrite_style,
        rewrite_focus=rewrite_focus,
        rewrite_source_text=rewrite_source_text,
        rewrite_provider=rewrite_provider,
        rewrite_model=rewrite_model,
        translation_base_url=translation_base_url,
        skill_config_name=skill_config_name,
        rewrite_failure_error_code=rewrite_failure_error_code,
        rewrite_failure_message=rewrite_failure_message,
        rewrite_failure_retryable=rewrite_failure_retryable,
        rewrite_failure_details=rewrite_failure_details,
    )


def append_chat_exchange(
    *,
    content_context_id: str,
    question: str,
    answer: str,
) -> None:
    default_session_repository.append_chat_exchange(
        content_context_id=content_context_id,
        question=question,
        answer=answer,
    )


def load_session_history(
    content_context_id: str,
    *,
    account_id: str | None = None,
) -> dict[str, Any] | None:
    return default_session_repository.load_session_history(
        content_context_id,
        account_id=account_id,
    )


def list_session_history(
    limit: int | None = 20,
    *,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    return default_session_repository.list_session_history(limit=limit, account_id=account_id)
