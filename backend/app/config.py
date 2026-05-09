import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_YTDLP_COOKIES_FILE = ROOT_DIR / "youtube-cookies.txt"

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
    enable_default_cookies_file: bool
    job_queue_db_path: Path
    yt_dlp_timeout_sec: int
    backend_log_file: Path
    frontend_log_file: Path
    desktop_log_file: Path


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings(
        api_auth_token=get_env_str("API_AUTH_TOKEN"),
        api_rate_limit_per_minute=max(0, _get_env_int("API_RATE_LIMIT_PER_MINUTE", 120)),
        enable_default_cookies_file=_get_env_bool("YTDLP_ENABLE_DEFAULT_COOKIES_FILE", False),
        job_queue_db_path=Path(
            get_env_str("JOB_QUEUE_DB_PATH")
            or (ROOT_DIR / "tmp" / "job_queue.sqlite").as_posix()
        ).expanduser(),
        yt_dlp_timeout_sec=max(30, _get_env_int("YTDLP_SUBPROCESS_TIMEOUT_SEC", 300)),
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


def get_yt_dlp_auth_args() -> list[str]:
    cookies_file = get_env_str("YTDLP_COOKIES_FILE")
    if cookies_file:
        return ["--cookies", cookies_file]

    cookies_from_browser = get_env_str("YTDLP_COOKIES_FROM_BROWSER")
    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]

    if get_settings().enable_default_cookies_file and DEFAULT_YTDLP_COOKIES_FILE.exists():
        return ["--cookies", str(DEFAULT_YTDLP_COOKIES_FILE)]

    cookie_header = get_env_str("YTDLP_COOKIE_HEADER")
    if cookie_header:
        return ["--add-headers", f"Cookie: {cookie_header}"]

    return []


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


def get_yt_dlp_js_runtime_args() -> list[str]:
    js_runtimes = get_env_str("YTDLP_JS_RUNTIMES")
    if js_runtimes:
        return ["--js-runtimes", js_runtimes]
    return []


def get_http_proxy_from_env() -> str:
    return (
        get_env_str("HTTP_PROXY")
        or get_env_str("http_proxy")
        or get_env_str("HTTPS_PROXY")
        or get_env_str("https_proxy")
    )
