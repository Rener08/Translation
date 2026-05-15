import logging
import os
import sys
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_YTDLP_COOKIES_FILE = ROOT_DIR / "youtube-cookies.txt"
logger = logging.getLogger(__name__)

if "pytest" not in sys.modules:
    load_dotenv(ROOT_DIR / ".env")


def get_env_str(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def _get_env_bool(name: str, default: bool) -> bool:
    raw = get_env_str(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _get_env_int(name: str, default: int) -> int:
    raw = get_env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppSettings:
    api_auth_token: str
    api_rate_limit_per_minute: int
    trust_proxy_headers: bool
    trust_account_headers: bool
    deployment_profile: str
    cors_allowed_origins: tuple[str, ...]
    account_daily_request_limit: int
    account_max_concurrent_jobs: int
    account_max_history_sessions: int
    account_quota_db_path: Path
    max_video_duration_sec: int
    max_audio_bytes: int
    max_transcript_chars: int
    max_translation_segments: int
    enable_default_cookies_file: bool
    job_queue_db_path: Path
    yt_dlp_timeout_sec: int
    backend_log_file: Path
    frontend_log_file: Path
    desktop_log_file: Path


@dataclass(frozen=True)
class YtDlpCookieConfig:
    mode: str
    configured: bool
    active_for_yt_dlp: bool
    effective_path: Path | None
    requested_path: Path | None


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    deployment_profile = _normalize_deployment_profile(
        get_env_str("DEPLOYMENT_PROFILE") or get_env_str("APP_ENV")
    )
    cors_allowed_origins = _parse_cors_allowed_origins()
    api_auth_token = get_env_str("API_AUTH_TOKEN")
    if deployment_profile == "production" and not api_auth_token:
        raise RuntimeError("API_AUTH_TOKEN must be set when DEPLOYMENT_PROFILE=production.")

    return AppSettings(
        api_auth_token=api_auth_token,
        api_rate_limit_per_minute=max(0, _get_env_int("API_RATE_LIMIT_PER_MINUTE", 120)),
        trust_proxy_headers=_get_env_bool("TRUST_PROXY_HEADERS", False),
        trust_account_headers=_get_env_bool(
            "TRUST_ACCOUNT_HEADERS",
            deployment_profile != "production",
        ),
        deployment_profile=deployment_profile,
        cors_allowed_origins=cors_allowed_origins,
        account_daily_request_limit=max(0, _get_env_int("ACCOUNT_DAILY_REQUEST_LIMIT", 0)),
        account_max_concurrent_jobs=max(0, _get_env_int("ACCOUNT_MAX_CONCURRENT_JOBS", 0)),
        account_max_history_sessions=max(0, _get_env_int("ACCOUNT_MAX_HISTORY_SESSIONS", 0)),
        account_quota_db_path=Path(
            get_env_str("ACCOUNT_QUOTA_DB_PATH")
            or (ROOT_DIR / "tmp" / "account_quota.sqlite").as_posix()
        ).expanduser(),
        max_video_duration_sec=max(1, _get_env_int("MAX_VIDEO_DURATION_SEC", 7200)),
        max_audio_bytes=max(1, _get_env_int("MAX_AUDIO_BYTES", 500 * 1024 * 1024)),
        max_transcript_chars=max(1, _get_env_int("MAX_TRANSCRIPT_CHARS", 250_000)),
        max_translation_segments=max(
            1, _get_env_int("MAX_TRANSLATION_SEGMENTS", 1000)
        ),
        enable_default_cookies_file=_get_env_bool("YTDLP_ENABLE_DEFAULT_COOKIES_FILE", False),
        job_queue_db_path=Path(
            get_env_str("JOB_QUEUE_DB_PATH")
            or (ROOT_DIR / "tmp" / "job_queue.sqlite").as_posix()
        ).expanduser(),
        yt_dlp_timeout_sec=max(1, _get_env_int("YTDLP_SUBPROCESS_TIMEOUT_SEC", 300)),
        backend_log_file=Path(
            get_env_str("BACKEND_LOG_FILE") or (ROOT_DIR / "backend_run.log").as_posix()
        ).expanduser(),
        frontend_log_file=Path(
            get_env_str("FRONTEND_LOG_FILE") or (ROOT_DIR / "frontend_run.log").as_posix()
        ).expanduser(),
        desktop_log_file=Path(
            get_env_str("DESKTOP_LOG_FILE") or (ROOT_DIR / "desktop_crash.log").as_posix()
        ).expanduser(),
    )


def resolve_yt_dlp_cookie_config() -> YtDlpCookieConfig:
    requested_file = get_env_str("YTDLP_COOKIES_FILE")
    browser_source = get_env_str("YTDLP_COOKIES_FROM_BROWSER")
    cookie_header = get_env_str("YTDLP_COOKIE_HEADER")
    settings = get_settings()

    requested_path = _normalize_yt_dlp_cookies_path(requested_file) if requested_file else None
    default_file_exists = DEFAULT_YTDLP_COOKIES_FILE.exists()
    configured = bool(
        requested_file
        or browser_source
        or cookie_header
        or settings.enable_default_cookies_file
    )

    if requested_path is not None and requested_path.is_file():
        return YtDlpCookieConfig(
            mode="cookies_file",
            configured=configured,
            active_for_yt_dlp=True,
            effective_path=requested_path,
            requested_path=requested_path,
        )

    if requested_file:
        logger.warning(
            "Ignoring YTDLP_COOKIES_FILE=%s because the file does not exist or is not readable.",
            requested_file,
        )

    if browser_source:
        return YtDlpCookieConfig(
            mode="browser",
            configured=configured,
            active_for_yt_dlp=True,
            effective_path=None,
            requested_path=None,
        )

    if cookie_header:
        return YtDlpCookieConfig(
            mode="cookie_header",
            configured=configured,
            active_for_yt_dlp=True,
            effective_path=None,
            requested_path=None,
        )

    if settings.enable_default_cookies_file:
        return YtDlpCookieConfig(
            mode="default_cookies_file",
            configured=configured,
            active_for_yt_dlp=default_file_exists,
            effective_path=DEFAULT_YTDLP_COOKIES_FILE,
            requested_path=DEFAULT_YTDLP_COOKIES_FILE,
        )

    if requested_file:
        return YtDlpCookieConfig(
            mode="cookies_file",
            configured=configured,
            active_for_yt_dlp=False,
            effective_path=requested_path,
            requested_path=requested_path,
        )

    return YtDlpCookieConfig(
        mode="none",
        configured=configured,
        active_for_yt_dlp=False,
        effective_path=None,
        requested_path=None,
    )


def _normalize_deployment_profile(raw_value: str) -> str:
    normalized = str(raw_value or "").strip().lower()
    if normalized in {"production", "prod"}:
        return "production"
    if normalized in {"test", "testing"}:
        return "test"
    return "development"


def _parse_cors_allowed_origins() -> tuple[str, ...]:
    raw_value = get_env_str("CORS_ALLOWED_ORIGINS")
    if not raw_value:
        return ()
    origins = []
    seen = set()
    for item in raw_value.split(","):
        origin = item.strip()
        if not origin or origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return tuple(origins)


def get_yt_dlp_auth_args() -> list[str]:
    cookie_config = resolve_yt_dlp_cookie_config()
    if (
        cookie_config.mode == "cookies_file"
        and cookie_config.active_for_yt_dlp
        and cookie_config.effective_path is not None
    ):
        return ["--cookies", str(cookie_config.effective_path)]

    if cookie_config.mode == "browser":
        return ["--cookies-from-browser", get_env_str("YTDLP_COOKIES_FROM_BROWSER")]

    if (
        cookie_config.mode == "default_cookies_file"
        and cookie_config.active_for_yt_dlp
        and cookie_config.effective_path is not None
    ):
        return ["--cookies", str(cookie_config.effective_path)]

    if cookie_config.mode == "cookie_header":
        cookie_header = get_env_str("YTDLP_COOKIE_HEADER")
        if cookie_header:
            return ["--add-headers", f"Cookie: {cookie_header}"]

    return []


def _resolve_yt_dlp_cookies_file(raw_value: str) -> Path | None:
    candidate = _normalize_yt_dlp_cookies_path(raw_value)
    if candidate is None:
        return None
    if candidate.is_file():
        return candidate
    return None


def _normalize_yt_dlp_cookies_path(raw_value: str) -> Path | None:
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return None


def get_yt_dlp_proxy_args() -> list[str]:
    proxy = get_env_str("YTDLP_PROXY")
    if proxy:
        return ["--proxy", proxy]
    return []


def get_yt_dlp_remote_components() -> list[str]:
    remote_components = get_env_str("YTDLP_REMOTE_COMPONENTS")
    if remote_components:
        return ["--remote-components", remote_components]
    return []


def get_yt_dlp_youtube_extractor_args() -> list[str]:
    player_clients = _parse_yt_dlp_youtube_player_clients()
    if not player_clients:
        return []
    return ["--extractor-args", f"youtube:player-client={player_clients}"]


def get_yt_dlp_js_runtime_args() -> list[str]:
    js_runtimes = get_env_str("YTDLP_JS_RUNTIMES")
    if js_runtimes:
        resolved_js_runtimes = _resolve_yt_dlp_js_runtimes(js_runtimes)
        if resolved_js_runtimes:
            return ["--js-runtimes", resolved_js_runtimes]
        logger.warning(
            "Ignoring YTDLP_JS_RUNTIMES=%s because the configured runtime could not be resolved.",
            js_runtimes,
        )

    runtime_fallback = _detect_available_yt_dlp_js_runtime()
    if runtime_fallback:
        logger.info("Using yt-dlp JavaScript runtime fallback: %s", runtime_fallback)
        return ["--js-runtimes", runtime_fallback]

    return []


def _resolve_yt_dlp_js_runtimes(raw_value: str) -> str | None:
    value = str(raw_value or "").strip()
    if not value:
        return None

    runtime_name, runtime_path = _split_runtime_spec(value)
    if runtime_path:
        candidate = Path(runtime_path).expanduser()
        if candidate.exists():
            return value
        if runtime_name:
            detected = shutil.which(runtime_name)
            if detected:
                return runtime_name
        return None

    if runtime_name:
        detected = shutil.which(runtime_name)
        if detected:
            return runtime_name
        return None

    return None


def _detect_available_yt_dlp_js_runtime() -> str | None:
    for runtime_name in ("deno", "node", "quickjs", "bun"):
        if shutil.which(runtime_name):
            return runtime_name
    return None


def _split_runtime_spec(value: str) -> tuple[str, str]:
    normalized = str(value or "").strip()
    if not normalized:
        return "", ""

    for runtime_name in ("deno", "node", "quickjs", "bun"):
        prefix = f"{runtime_name}:"
        if normalized.lower().startswith(prefix):
            return runtime_name, normalized[len(prefix) :].strip()

    return normalized, ""


def _parse_yt_dlp_youtube_player_clients() -> str:
    raw_value = get_env_str("YTDLP_YOUTUBE_PLAYER_CLIENTS")
    if not raw_value:
        return ""

    normalized_clients: list[str] = []
    seen: set[str] = set()
    for item in raw_value.split(","):
        client = item.strip()
        if not client:
            continue
        canonical_client = client.replace("_", "-")
        if canonical_client in seen:
            continue
        seen.add(canonical_client)
        normalized_clients.append(canonical_client)

    return ",".join(normalized_clients)


def get_http_proxy_from_env() -> str:
    return (
        get_env_str("HTTP_PROXY")
        or get_env_str("http_proxy")
        or get_env_str("HTTPS_PROXY")
        or get_env_str("https_proxy")
    )
