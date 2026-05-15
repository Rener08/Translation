import shutil

import pytest

from app.config import get_settings
from app.repositories.account_quota_repository import default_account_quota_repository
from app.services import job_queue_service
from app.services.account_quota_service import default_account_quota_service
from app.services.persistent_cache_service import CACHE_ROOT_DIR


ISOLATED_ENV_KEYS = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_TRANSLATION_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_TRANSLATION_MODEL",
    "LMSTUDIO_API_KEY",
    "LMSTUDIO_BASE_URL",
    "LMSTUDIO_TRANSLATION_MODEL",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_TRANSLATION_MODEL",
    "TRANSLATION_PROVIDER",
    "WHISPER_MODEL",
    "WHISPER_DEVICE",
    "WHISPER_COMPUTE_TYPE",
    "JOB_QUEUE_MAX_WORKERS",
    "JOB_RECORD_TTL_HOURS",
    "JOB_RECORD_MAX_COUNT",
    "TMP_ARTIFACT_TTL_HOURS",
    "YTDLP_SUBPROCESS_TIMEOUT_SEC",
    "YTDLP_COOKIES_FROM_BROWSER",
    "YTDLP_COOKIES_FILE",
    "YTDLP_COOKIE_HEADER",
    "YTDLP_ENABLE_DEFAULT_COOKIES_FILE",
    "JOB_QUEUE_DB_PATH",
    "API_AUTH_TOKEN",
    "API_RATE_LIMIT_PER_MINUTE",
    "DEPLOYMENT_PROFILE",
    "APP_ENV",
    "TRUST_ACCOUNT_HEADERS",
    "CORS_ALLOWED_ORIGINS",
    "ACCOUNT_DAILY_REQUEST_LIMIT",
    "ACCOUNT_MAX_CONCURRENT_JOBS",
    "ACCOUNT_MAX_HISTORY_SESSIONS",
    "ACCOUNT_QUOTA_DB_PATH",
    "MAX_VIDEO_DURATION_SEC",
    "MAX_AUDIO_BYTES",
    "MAX_TRANSCRIPT_CHARS",
    "MAX_TRANSLATION_SEGMENTS",
]


@pytest.fixture(autouse=True)
def isolate_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    for key in ISOLATED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    shutil.rmtree(CACHE_ROOT_DIR, ignore_errors=True)
    get_settings.cache_clear()
    executor = job_queue_service._JOB_EXECUTOR
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    job_queue_service._JOB_EXECUTOR = None
    job_queue_service._JOB_EXECUTOR_MAX_WORKERS = None
    job_queue_service.reset_job_queue_state_for_tests()
    default_account_quota_repository.reset_for_tests()
    default_account_quota_service._quota_repository.reset_for_tests()
