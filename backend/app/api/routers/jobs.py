import logging
import inspect
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.error_mapping import classify_service_error
from app.api.runtime_deps import resolve
from app.config import get_env_str
from app.services.job_queue_service import get_job_record, submit_background_job, update_job_progress
from app.services.job_run_service import run_video_job_with_translation_config
from app.services.session_history_service import upsert_job_session
from app.youtube import (
    JobRunRequest,
    JobRunResponse,
    JobRunStatusResponse,
    JobTranscriptResponse,
    JobTranslationResponse,
    JobVideoResponse,
    TranscriptSegmentResponse,
    TranslateItemResponse,
    parse_youtube_url,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/api/jobs/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobRunStatusResponse,
    response_model_exclude_none=True,
)
async def run_job(request: JobRunRequest) -> JobRunStatusResponse:
    try:
        parsed = parse_youtube_url(str(request.url))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    translation_config = (
        request.translation_config.model_dump()
        if request.translation_config
        else None
    )
    stage_timeouts = _resolve_job_stage_timeouts_from_env()
    job_id = submit_background_job(
        lambda created_job_id: _run_job_background(
            created_job_id,
            parsed.normalized_url,
            request.source_mode,
            translation_config,
            stage_timeouts=stage_timeouts,
        )
    )
    return JobRunStatusResponse(
        ok=True,
        job_id=job_id,
        status="queued",
        progress_value=0,
        progress_text="已加入队列",
    )


@router.get(
    "/api/jobs/{job_id}",
    response_model=JobRunStatusResponse,
    response_model_exclude_none=True,
)
async def get_job_status(job_id: str) -> JobRunStatusResponse:
    record = get_job_record(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return _job_record_to_response(record)


def _run_job_background(
    job_id: str,
    normalized_url: str,
    source_mode: str,
    translation_config: dict[str, object] | None,
    *,
    stage_timeouts: dict[str, int],
) -> None:
    try:
        update_job_progress(
            job_id,
            status="running",
            progress_value=8,
            stage="inspect",
            timeout_sec=stage_timeouts["inspect"],
            progress_text="正在处理视频...",
        )

        result = _invoke_job_runner(
            resolve(
                "run_video_job_with_translation_config",
                run_video_job_with_translation_config,
            ),
            normalized_url=normalized_url,
            source_mode=source_mode,
            translation_config=translation_config,
            stage_timeouts=stage_timeouts,
            progress_callback=lambda stage, value, text: update_job_progress(
                job_id,
                status="running",
                stage=stage,
                progress_value=value,
                timeout_sec=stage_timeouts.get(stage),
                progress_text=text,
            ),
        )

        update_job_progress(
            job_id,
            status="running",
            stage="persist",
            progress_value=90,
            timeout_sec=stage_timeouts["persist"],
            progress_text="正在保存会话...",
        )
        _persist_job_session(
            result=result,
            normalized_url=normalized_url,
            source_mode=source_mode,
            translation_config=translation_config,
        )
        response = _build_job_run_response(result)
        update_job_progress(
            job_id,
            status="done",
            stage="persist",
            progress_value=100,
            timeout_sec=stage_timeouts["persist"],
            progress_text="处理完成",
            result=response.model_dump(mode="json"),
            error_code=None,
            retryable=None,
        )
    except Exception as error:
        classification = classify_service_error(error)
        logger.exception("Job run failed for %s", normalized_url)
        update_job_progress(
            job_id,
            status="failed",
            progress_value=100,
            progress_text="处理失败",
            error=str(error),
            error_code=classification.error_code,
            retryable=classification.retryable,
        )


def _persist_job_session(
    *,
    result,
    normalized_url: str,
    source_mode: str,
    translation_config: dict[str, object] | None,
) -> None:
    try:
        upsert_job_session(
            content_context_id=result.content_context_id,
            video_id=result.video.video_id,
            video_url=normalized_url,
            video_title=result.video.title,
            video_duration_sec=result.video.duration_sec,
            video_uploader=result.video.uploader,
            video_thumbnail=result.video.thumbnail,
            source_mode=source_mode,
            source_type=result.source_type,
            translation_provider=(
                str(translation_config.get("provider"))
                if translation_config and translation_config.get("provider")
                else None
            ),
            translation_model=(
                str(translation_config.get("model"))
                if translation_config and translation_config.get("model")
                else None
            ),
            transcript_en_text=result.transcript_en.text,
            transcript_en_segments=[
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "speaker": segment.speaker,
                }
                for segment in result.transcript_en.segments
            ],
            translation_zh_text="\n".join(
                item.translated_text.strip()
                for item in result.translation_zh_segments
                if item.translated_text.strip()
            ),
            translation_zh_segments=[
                {
                    "index": item.index,
                    "start": item.start,
                    "end": item.end,
                    "source_text": item.source_text,
                    "translated_text": item.translated_text,
                }
                for item in result.translation_zh_segments
            ],
        )
    except Exception:
        logger.warning("Failed to persist session history for %s", normalized_url)


def _build_job_run_response(result) -> JobRunResponse:
    return JobRunResponse(
        ok=True,
        video=JobVideoResponse(
            video_id=result.video.video_id,
            title=result.video.title,
            thumbnail=result.video.thumbnail,
            duration_sec=result.video.duration_sec,
            uploader=result.video.uploader,
        ),
        source_type=result.source_type,
        transcript_en=JobTranscriptResponse(
            text=result.transcript_en.text,
            segments=[
                TranscriptSegmentResponse(
                    index=segment.index,
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    speaker=segment.speaker,
                )
                for segment in result.transcript_en.segments
            ],
        ),
        translation_zh=JobTranslationResponse(
            segments=[
                TranslateItemResponse(
                    index=item.index,
                    start=item.start,
                    end=item.end,
                    source_text=item.source_text,
                    translated_text=item.translated_text,
                )
                for item in result.translation_zh_segments
            ]
        ),
        content_context_id=result.content_context_id,
    )


def _job_record_to_response(record: Any) -> JobRunStatusResponse:
    result = record.result
    job_result = JobRunResponse(**result) if isinstance(result, dict) else None
    return JobRunStatusResponse(
        ok=True,
        job_id=record.job_id,
        status=record.status,
        progress_value=record.progress_value,
        progress_text=record.progress_text or None,
        stage=record.stage,
        started_at=record.created_at,
        updated_at=record.updated_at,
        timeout_sec=record.timeout_sec,
        result=job_result,
        error=record.error or None,
        error_code=record.error_code,
        retryable=record.retryable,
    )


def _resolve_job_stage_timeouts_from_env() -> dict[str, int]:
    return {
        "inspect": _parse_positive_int_env("JOB_STAGE_TIMEOUT_INSPECT_SEC", 45),
        "fetch_source": _parse_positive_int_env("JOB_STAGE_TIMEOUT_FETCH_SOURCE_SEC", 180),
        "transcribe": _parse_positive_int_env("JOB_STAGE_TIMEOUT_TRANSCRIBE_SEC", 900),
        "translate": _parse_positive_int_env("JOB_STAGE_TIMEOUT_TRANSLATE_SEC", 900),
        "persist": _parse_positive_int_env("JOB_STAGE_TIMEOUT_PERSIST_SEC", 30),
    }


def _parse_positive_int_env(name: str, default: int) -> int:
    raw = get_env_str(name)
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    if parsed <= 0:
        return default
    return parsed


def _invoke_job_runner(
    run_callable,
    *,
    normalized_url: str,
    source_mode: str,
    translation_config: dict[str, object] | None,
    stage_timeouts: dict[str, int],
    progress_callback,
):
    kwargs: dict[str, object] = {
        "source_mode": source_mode,
        "translation_config": translation_config,
    }
    try:
        signature = inspect.signature(run_callable)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        parameters = signature.parameters
        if "stage_timeout_seconds" in parameters:
            kwargs["stage_timeout_seconds"] = stage_timeouts
        if "progress_callback" in parameters:
            kwargs["progress_callback"] = progress_callback

    return run_callable(normalized_url, **kwargs)
