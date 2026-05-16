import asyncio
from collections import deque
from contextlib import asynccontextmanager
import hmac
import logging
import sys
import threading
import time
import types
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import build_api_router
from app.api.error_mapping import (
    build_error_payload,
    default_error_code_for_status,
    default_retryable_for_status,
    normalize_http_exception_detail,
)
from app.config import get_settings, resolve_yt_dlp_cookie_config
from app.service_bindings import service_bindings
from app.services.account_quota_service import (
    default_account_quota_service,
    resolve_account_identity_from_request,
)
from app.services.content_chat_service import answer_content_question
from app.services.content_rewrite_service import rewrite_content
from app.services.job_run_service import run_video_job_with_translation_config
from app.services.speaker_diarization_service import diarize_audio_file
from app.services.tmp_artifact_cleanup_service import cleanup_stale_tmp_artifacts
from app.services.transcription_service import transcribe_audio_file
from app.services.translation_service import discover_provider_models, translate_segments_to_chinese
from app.services.upload_job_service import run_uploaded_audio_job_with_translation_config
from app.services.video_source_service import fetch_video_source
from app.services.writer_agent_service import run_writer_agent
from app.services.yt_dlp_service import inspect_video_metadata

logger = logging.getLogger(__name__)
settings = get_settings()
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = {}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def _periodic_cleanup():
    while True:
        await asyncio.sleep(3600)
        await run_in_threadpool(cleanup_stale_tmp_artifacts)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await run_in_threadpool(cleanup_stale_tmp_artifacts)
    _log_runtime_summary()
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="YouTube Translator MVP API", lifespan=lifespan)

_DEV_CORS_ALLOW_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8090",
    "http://127.0.0.1:8090",
)

if settings.deployment_profile == "production" and not settings.api_auth_token:
    raise RuntimeError("API_AUTH_TOKEN must be set when DEPLOYMENT_PROFILE=production.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins) or (
        [] if settings.deployment_profile == "production" else list(_DEV_CORS_ALLOW_ORIGINS)
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(build_api_router())


def _log_runtime_summary() -> None:
    cookie_config = resolve_yt_dlp_cookie_config()
    logger.info(
        "runtime_summary deployment_profile=%s api_auth_token_set=%s "
        "yt_dlp_cookie_mode=%s yt_dlp_cookie_path=%s yt_dlp_cookie_exists=%s "
        "job_queue_db_path=%s",
        settings.deployment_profile,
        bool(settings.api_auth_token),
        cookie_config.mode,
        cookie_config.effective_path.as_posix() if cookie_config.effective_path else "",
        bool(cookie_config.effective_path and cookie_config.effective_path.exists()),
        settings.job_queue_db_path.as_posix(),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = _resolve_request_id(request)
    return _standard_error_response(
        request_id=request_id,
        status_code=422,
        detail=_summarize_validation_errors(exc),
        error_code="VALIDATION_ERROR",
        retryable=False,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = _resolve_request_id(request)
    normalized_detail, error_code, retryable = normalize_http_exception_detail(exc.detail, exc.status_code)
    return _standard_error_response(
        request_id=request_id,
        status_code=exc.status_code,
        detail=normalized_detail,
        error_code=error_code,
        retryable=retryable,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = _resolve_request_id(request)
    logger.exception(
        "unhandled_exception request_id=%s method=%s path=%s",
        request_id,
        request.method,
        request.url.path,
    )
    from app.api.error_mapping import classify_service_error, build_error_payload
    classification = classify_service_error(exc)
    return _standard_error_response(
        request_id=request_id,
        status_code=classification.status_code,
        detail=classification.detail,
        error_code=classification.error_code,
        retryable=classification.retryable,
    )


@app.middleware("http")
async def security_and_observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id
    path = request.url.path
    method = request.method.upper()
    client_ip = _resolve_client_ip(request)
    account_identity = resolve_account_identity_from_request(
        request,
        settings=settings,
    )
    request.state.account_id = account_identity.account_id
    request.state.account_identity = account_identity

    # Token applies to all `/api/*` routes. Liveness URLs are `/health`, `/readyz`, `/livez` (no `/api` prefix).
    if settings.api_auth_token and path.startswith("/api/"):
        token = _extract_api_token(request)
        if not _is_valid_api_token(token, settings.api_auth_token):
            return _standard_error_response(
                request_id=request_id,
                status_code=401,
                detail="Unauthorized API request.",
                error_code=default_error_code_for_status(401),
                retryable=default_retryable_for_status(401),
            )

    if path.startswith("/api/") and method in MUTATING_METHODS:
        allowed = _consume_rate_limit_token(client_ip)
        if not allowed:
            return _standard_error_response(
                request_id=request_id,
                status_code=429,
                detail="Rate limit exceeded. Please retry later.",
                error_code=default_error_code_for_status(429),
                retryable=default_retryable_for_status(429),
            )

    if path.startswith("/api/"):
        quota_response = _enforce_account_quota(
            request_id=request_id,
            path=path,
            method=method,
            account_identity=account_identity,
        )
        if quota_response is not None:
            return quota_response

    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%s ip=%s account_id=%s",
        request_id,
        method,
        path,
        response.status_code,
        duration_ms,
        client_ip,
        account_identity.account_id,
    )
    return response

# Backward-compatible symbol exports for tests and monkeypatch targets.
__all__ = [
    "app",
    "answer_content_question",
    "rewrite_content",
    "run_writer_agent",
    "run_video_job_with_translation_config",
    "run_uploaded_audio_job_with_translation_config",
    "transcribe_audio_file",
    "diarize_audio_file",
    "inspect_video_metadata",
    "fetch_video_source",
    "translate_segments_to_chinese",
    "discover_provider_models",
]


_SERVICE_BINDING_NAMES = {
    "inspect_video_metadata",
    "fetch_video_source",
    "transcribe_audio_file",
    "diarize_audio_file",
    "translate_segments_to_chinese",
    "answer_content_question",
    "run_writer_agent",
    "discover_provider_models",
    "run_video_job_with_translation_config",
    "run_uploaded_audio_job_with_translation_config",
    "rewrite_content",
}


# 让测试中 monkeypatch.setattr(app.main, 'fn', mock) 能同时同步到 service_bindings。
# 原理：替换本模块的 __class__，使 __setattr__ 拦截对 _SERVICE_BINDING_NAMES 的赋值。
class _ServiceBindingModule(types.ModuleType):
    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        if name in _SERVICE_BINDING_NAMES:
            setattr(service_bindings, name, value)

    def __getattr__(self, name: str):
        if name in _SERVICE_BINDING_NAMES:
            return getattr(service_bindings, name)
        raise AttributeError(name)


_module = sys.modules[__name__]
_module.__class__ = _ServiceBindingModule


def _extract_api_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.headers.get("x-api-token", "").strip()


def _is_valid_api_token(token: str, expected_token: str) -> bool:
    if not expected_token:
        return True
    return hmac.compare_digest(token, expected_token)


def _standard_error_response(
    *,
    request_id: str,
    status_code: int,
    detail: str,
    error_code: str,
    retryable: bool,
) -> JSONResponse:
    payload = build_error_payload(
        detail=detail,
        error_code=error_code,
        retryable=retryable,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={"x-request-id": request_id},
    )


def _resolve_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    header_request_id = request.headers.get("x-request-id", "").strip()
    if header_request_id:
        return header_request_id
    return uuid4().hex


def _summarize_validation_errors(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "请求参数校验失败。"
    first_error = errors[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()) if part != "body")
    message = str(first_error.get("msg") or "请求参数校验失败。")
    if location:
        return f"{location}: {message}"
    return message


def _resolve_client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            first_ip = forwarded_for.split(",")[0].strip()
            if first_ip:
                return first_ip
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def _consume_rate_limit_token(client_ip: str) -> bool:
    limit = settings.api_rate_limit_per_minute
    if limit <= 0:
        return True
    now = time.time()
    window_start = now - 60.0
    key = client_ip or "unknown"
    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_BUCKETS.setdefault(key, deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def _enforce_account_quota(
    *,
    request_id: str,
    path: str,
    method: str,
    account_identity,
) -> JSONResponse | None:
    if method in MUTATING_METHODS:
        violation = default_account_quota_service.consume_daily_request(
            account_identity,
            settings=settings,
        )
        if violation is not None:
            return _standard_error_response(
                request_id=request_id,
                status_code=429,
                detail=violation.detail,
                error_code=violation.error_code,
                retryable=violation.retryable,
            )

    if path == "/api/jobs/run":
        violation = default_account_quota_service.check_job_start_quota(
            account_identity,
            settings=settings,
        )
        if violation is not None:
            return _standard_error_response(
                request_id=request_id,
                status_code=429,
                detail=violation.detail,
                error_code=violation.error_code,
                retryable=violation.retryable,
            )

    return None
