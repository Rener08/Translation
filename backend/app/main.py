from collections import deque
from contextlib import asynccontextmanager
import hmac
import logging
import threading
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import build_api_router
from app.config import get_settings
from app.services.content_chat_service import answer_content_question
from app.services.content_rewrite_service import rewrite_content
from app.services.job_run_service import run_video_job_with_translation_config
from app.services.speaker_diarization_service import diarize_audio_file
from app.services.tmp_artifact_cleanup_service import cleanup_stale_tmp_artifacts
from app.services.transcription_service import transcribe_audio_file
from app.services.translation_service import discover_provider_models, translate_segments_to_chinese
from app.services.video_source_service import fetch_video_source
from app.services.writer_agent_service import run_writer_agent
from app.services.yt_dlp_service import inspect_video_metadata

logger = logging.getLogger(__name__)
settings = get_settings()
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = {}


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


@app.middleware("http")
async def security_and_observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id
    path = request.url.path
    method = request.method.upper()
    client_ip = _resolve_client_ip(request)

    # Token applies to all `/api/*` routes. Liveness URLs are `/health`, `/readyz`, `/livez` (no `/api` prefix).
    if settings.api_auth_token and path.startswith("/api/"):
        token = _extract_api_token(request)
        if not _is_valid_api_token(token, settings.api_auth_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized API request."},
                headers={"x-request-id": request_id},
            )

    if path.startswith("/api/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
        allowed = _consume_rate_limit_token(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry later."},
                headers={"x-request-id": request_id},
            )

    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%s ip=%s",
        request_id,
        method,
        path,
        response.status_code,
        duration_ms,
        client_ip,
    )
    return response

# Backward-compatible symbol exports for tests and monkeypatch targets.
__all__ = [
    "app",
    "answer_content_question",
    "rewrite_content",
    "run_writer_agent",
    "run_video_job_with_translation_config",
    "transcribe_audio_file",
    "diarize_audio_file",
    "inspect_video_metadata",
    "fetch_video_source",
    "translate_segments_to_chinese",
    "discover_provider_models",
]


def _extract_api_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.headers.get("x-api-token", "").strip()


def _is_valid_api_token(token: str, expected_token: str) -> bool:
    if not expected_token:
        return True
    return hmac.compare_digest(token, expected_token)


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
