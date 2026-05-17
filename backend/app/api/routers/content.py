import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.api.error_mapping import classify_service_error, raise_mapped_http_exception
from app.api.runtime_deps import get_answer_content_question, get_run_writer_agent
from app.services.content_context_service import load_content_context
from app.services.content_rewrite_service import (
    ContentRewriteEmptyOutputError,
    ContentRewriteProviderError,
)
from app.services.skill_config_service import resolve_skill_config
from app.services.session_history_service import (
    append_chat_exchange,
    record_rewrite_failure,
    record_rewrite_result,
)
from app.youtube import ContentChatRequest, ContentChatResponse, ContentRewriteRequest, ContentRewriteResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/content-chat", response_model=ContentChatResponse)
async def content_chat(
    request: Request,
    body: ContentChatRequest,
    answer_content_question_fn=Depends(get_answer_content_question),
) -> ContentChatResponse:
    account_id = str(getattr(request.state, "account_id", "") or "").strip()
    resolved_context = None
    video_title = body.video_title
    transcript_en = body.transcript_en
    translation_zh = body.translation_zh
    content_context_id = str(body.content_context_id or "").strip() or None
    if content_context_id:
        resolved_context = load_content_context(
            content_context_id,
            account_id=account_id or None,
        )
        if resolved_context is None:
            raise HTTPException(status_code=404, detail="Content context not found.")
        video_title = video_title or resolved_context.video_title
        transcript_en = transcript_en or resolved_context.transcript_en
        translation_zh = translation_zh or resolved_context.translation_zh

    try:
        result = await run_in_threadpool(
            answer_content_question_fn,
            content_context_id=None,
            video_title=video_title,
            transcript_en=transcript_en,
            translation_zh=translation_zh,
            question=body.question,
            messages=[message.model_dump() for message in body.messages],
            chat_config=(
                body.chat_config.model_dump() if body.chat_config else None
            ),
        )
    except Exception as error:
        raise_mapped_http_exception(error)

    if content_context_id and resolved_context is not None:
        try:
            await run_in_threadpool(
                append_chat_exchange,
                content_context_id=content_context_id,
                question=body.question,
                answer=result.answer,
            )
        except Exception:
            logger.warning(
                "Failed to persist chat history for %s",
                content_context_id,
            )

    return ContentChatResponse(
        ok=True,
        provider=result.provider,
        model=result.model,
        answer=result.answer,
    )


@router.post("/api/content-rewrite", response_model=ContentRewriteResponse)
async def content_rewrite(
    request: Request,
    body: ContentRewriteRequest,
    run_writer_agent_fn=Depends(get_run_writer_agent),
) -> ContentRewriteResponse:
    account_id = str(getattr(request.state, "account_id", "") or "").strip()
    reference_text = ""
    rewrite_config = body.translation_config.model_dump() if body.translation_config else None
    if body.content_context_id:
        context = load_content_context(
            body.content_context_id,
            account_id=account_id or None,
        )
        if context is None:
            raise HTTPException(status_code=404, detail="Content context not found.")
        reference_text = context.transcript_en

    try:
        skill_config = resolve_skill_config(skill_dir=None, config_name=body.skill_config_name)
        result = await run_in_threadpool(
            run_writer_agent_fn,
            source_text=body.source_text,
            reference_text=reference_text or None,
            rewrite_focus=body.rewrite_focus,
            rewrite_style=body.rewrite_style,
            rewrite_config=rewrite_config,
            skill_config=skill_config,
        )
    except ContentRewriteEmptyOutputError as error:
        _persist_rewrite_failure(
            content_context_id=body.content_context_id,
            rewrite_style=body.rewrite_style,
            rewrite_focus=body.rewrite_focus,
            rewrite_source_text=body.source_text,
            rewrite_config=rewrite_config,
            skill_config_name=body.skill_config_name,
            error=error,
        )
        raise_mapped_http_exception(error)
    except ContentRewriteProviderError as error:
        _persist_rewrite_failure(
            content_context_id=body.content_context_id,
            rewrite_style=body.rewrite_style,
            rewrite_focus=body.rewrite_focus,
            rewrite_source_text=body.source_text,
            rewrite_config=rewrite_config,
            skill_config_name=body.skill_config_name,
            error=error,
        )
        raise_mapped_http_exception(
            ContentRewriteProviderError(f"内容改写失败：上游模型服务返回错误。{error}")
        )
    except HTTPException:
        raise
    except Exception as error:
        _persist_rewrite_failure(
            content_context_id=body.content_context_id,
            rewrite_style=body.rewrite_style,
            rewrite_focus=body.rewrite_focus,
            rewrite_source_text=body.source_text,
            rewrite_config=rewrite_config,
            skill_config_name=body.skill_config_name,
            error=error,
        )
        raise_mapped_http_exception(error)

    quality_issues = list(getattr(result, "quality_issues", ()) or [])
    detail_coverage_issues = list(getattr(result, "detail_coverage_issues", ()) or [])

    if body.content_context_id:
        try:
            await run_in_threadpool(
                record_rewrite_result,
                content_context_id=body.content_context_id,
                rewrite_style=body.rewrite_style,
                rewrite_focus=body.rewrite_focus,
                rewrite_source_text=body.source_text,
                rewritten_text=result.rewritten_text,
                rewrite_quality_issues=quality_issues,
                rewrite_detail_coverage_issues=detail_coverage_issues,
                rewrite_provider=result.provider,
                rewrite_model=result.model,
                translation_base_url=(
                    str(rewrite_config.get("base_url"))
                    if rewrite_config and rewrite_config.get("base_url")
                    else None
                ),
                skill_config_name=body.skill_config_name,
                writer_trace_id=getattr(result, "writer_trace_id", ""),
                writer_policy_version=getattr(result, "writer_policy_version", ""),
                writer_prompt_version=getattr(result, "writer_prompt_version", ""),
            )
        except Exception:
            logger.warning(
                "Failed to persist rewrite history for %s",
                body.content_context_id,
            )

    return ContentRewriteResponse(
        ok=True,
        provider=result.provider,
        model=result.model,
        rewritten_text=result.rewritten_text,
        quality_issues=quality_issues,
        detail_coverage_issues=detail_coverage_issues,
    )


def _persist_rewrite_failure(
    *,
    content_context_id: str,
    rewrite_style,
    rewrite_focus,
    rewrite_source_text: str,
    rewrite_config: dict[str, object] | None,
    skill_config_name: str | None,
    error: Exception,
) -> None:
    if not content_context_id:
        return

    classification = classify_service_error(error)
    details = [
        f"写作风格：{rewrite_style or 'unknown'}",
        f"技能配置：{skill_config_name or 'unknown'}",
        f"改写重点：{rewrite_focus or '无'}",
        f"来源文本长度：{len(str(rewrite_source_text or '').strip())}",
    ]
    if rewrite_config:
        provider = str(rewrite_config.get("provider") or "").strip()
        model = str(rewrite_config.get("model") or "").strip()
        base_url = str(rewrite_config.get("base_url") or "").strip()
        if provider:
            details.append(f"provider：{provider}")
        if model:
            details.append(f"model：{model}")
        if base_url:
            details.append(f"base_url：{base_url}")

    try:
        record_rewrite_failure(
            content_context_id=content_context_id,
            rewrite_style=str(rewrite_style or "").strip() or None,
            rewrite_focus=str(rewrite_focus or "").strip() or None,
            rewrite_source_text=rewrite_source_text,
            rewrite_provider=str(rewrite_config.get("provider") or "").strip() if rewrite_config else None,
            rewrite_model=str(rewrite_config.get("model") or "").strip() if rewrite_config else None,
            translation_base_url=str(rewrite_config.get("base_url") or "").strip() if rewrite_config else None,
            skill_config_name=skill_config_name,
            rewrite_failure_error_code=classification.error_code,
            rewrite_failure_message=classification.detail,
            rewrite_failure_retryable=classification.retryable,
            rewrite_failure_details=details,
        )
    except Exception:
        logger.warning("Failed to persist rewrite failure for %s", content_context_id)
