import logging

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.api.error_mapping import raise_mapped_http_exception
from app.api.runtime_deps import resolve
from app.services.content_chat_service import answer_content_question
from app.services.content_rewrite_service import (
    ContentRewriteEmptyOutputError,
    ContentRewriteProviderError,
    rewrite_content,
)
from app.services.session_history_service import append_chat_exchange, record_rewrite_result
from app.youtube import ContentChatRequest, ContentChatResponse, ContentRewriteRequest, ContentRewriteResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/content-chat", response_model=ContentChatResponse)
async def content_chat(request: ContentChatRequest) -> ContentChatResponse:
    try:
        result = await run_in_threadpool(
            resolve("answer_content_question", answer_content_question),
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
async def content_rewrite(request: ContentRewriteRequest) -> ContentRewriteResponse:
    try:
        rewrite_config = (
            request.translation_config.model_dump()
            if request.translation_config
            else None
        )
        result = await run_in_threadpool(
            resolve("rewrite_content", rewrite_content),
            source_text=request.source_text,
            rewrite_focus=request.rewrite_focus,
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
