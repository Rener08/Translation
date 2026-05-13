import logging

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.error_mapping import raise_mapped_http_exception
from app.api.runtime_deps import get_answer_content_question, get_run_writer_agent
from app.services.content_rewrite_service import (
    ContentRewriteEmptyOutputError,
    ContentRewriteProviderError,
)
from app.services.session_history_service import append_chat_exchange, record_rewrite_result
from app.youtube import ContentChatRequest, ContentChatResponse, ContentRewriteRequest, ContentRewriteResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/content-chat", response_model=ContentChatResponse)
async def content_chat(
    request: ContentChatRequest,
    answer_content_question_fn=Depends(get_answer_content_question),
) -> ContentChatResponse:
    try:
        result = await run_in_threadpool(
            answer_content_question_fn,
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
    except Exception as error:
        raise_mapped_http_exception(error)

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


@router.post("/api/content-rewrite", response_model=ContentRewriteResponse)
async def content_rewrite(
    request: ContentRewriteRequest,
    run_writer_agent_fn=Depends(get_run_writer_agent),
) -> ContentRewriteResponse:
    try:
        rewrite_config = (
            request.translation_config.model_dump()
            if request.translation_config
            else None
        )
        result = await run_in_threadpool(
            run_writer_agent_fn,
            source_text=request.source_text,
            rewrite_focus=request.rewrite_focus,
            rewrite_style=request.rewrite_style,
            rewrite_config=rewrite_config,
        )
    except ContentRewriteEmptyOutputError as error:
        raise_mapped_http_exception(error)
    except ContentRewriteProviderError as error:
        raise_mapped_http_exception(
            ContentRewriteProviderError(f"内容改写失败：上游模型服务返回错误。{error}")
        )
    except Exception as error:
        raise_mapped_http_exception(error)

    quality_issues = list(getattr(result, "quality_issues", ()) or [])
    detail_coverage_issues = list(getattr(result, "detail_coverage_issues", ()) or [])

    if request.content_context_id:
        try:
            await run_in_threadpool(
                record_rewrite_result,
                content_context_id=request.content_context_id,
                rewrite_style=request.rewrite_style,
                rewrite_focus=request.rewrite_focus,
                rewrite_source_text=request.source_text,
                rewritten_text=result.rewritten_text,
                rewrite_quality_issues=quality_issues,
                rewrite_detail_coverage_issues=detail_coverage_issues,
                rewrite_provider=result.provider,
                rewrite_model=result.model,
                writer_trace_id=getattr(result, "writer_trace_id", ""),
                writer_policy_version=getattr(result, "writer_policy_version", ""),
                writer_prompt_version=getattr(result, "writer_prompt_version", ""),
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
        quality_issues=quality_issues,
        detail_coverage_issues=detail_coverage_issues,
    )
